# 设计规格：Android 主分析路径与桌面同口径使用 spaCy

- **状态**：ACCEPTED（U2：统一为 spaCy）
- **日期**：2026-11-06
- **关联**：`docs/adr/2026-11-06-adr-0028-android-main-path-spacy-lazy-load.md`、ADR-0018 §7.6、ADR-0027
- **范围**：本规格定义 Android 主分析路径从"纯 Python 降级"改为"spaCy 惰性加载 + 本地三级回退 + 硬失败 + 禁下载"的设计与验收；**本轮只写文档与计划，不改代码/测试/workflow**。
- **前身**：本规格替代 2026-11-06 早先的 `2026-11-06-android-pure-python-degradation-spec.md`（该方向已由用户否决）。

---

## 1. 问题陈述

### 1.1 问题：纯 Python 主路径会"标错"，不只是"少标"

Android（Chaquopy）运行时，`delector/nlp_engine/processor.py:240-246` 按平台硬编码把主分析路径的 `nlp` 设为 `None`：

```python
elif _android_runtime:
    # Android：模型以裸源码目录拷贝、无 dist-info，spacy.load(名字) 必失败；导入期加载只会
    # 白白阻塞启动页，且必须避免 spacy.cli.download 起 pip 子进程。既有行为已实际退化到纯 Python
    #（docs/agents/architecture.md）——这里显式化：不导入期加载、不联网下载，直接降级（红线 1）。
    nlp = None
    NLP_ENGINE = "pure_python"
    NLP_ENGINE_DETAIL = "Android：模型不在导入期加载（无 dist-info/避免 pip 下载），走纯 Python 降级"
```

> **历史注释说明**：该代码块中的"无 dist-info ⇒ `spacy.load` 必失败"已被 2026-11-05 实测推翻（APK 内含 `de_core_news_sm-3.8.0.dist-info/`，`spacy.load` 可成功）。原文保留以记录当时的决策依据，不追改历史结论。

因此 `process_german_text` 在 Android 上走纯 Python 分支（`processor.py:579-581`），产出与 spaCy 分支存在结构性差距：

| 能力 | 纯 Python 现状 | 性质 |
| --- | --- | --- |
| 格（`case`） | 恒为空字符串（`processor.py:537`） | 漏 |
| 依存（`dep`/`head_*`） | 字段不存在 | 漏 |
| 五场域（`topology`） | 仅 `mittelfeld` 有值（`processor.py:550-556`） | 漏 |
| 从句树（`clause_tree`） | 固定 `hauptsatz` 单节点（`processor.py:557-567`） | 漏 |
| 可分动词 | 不识别 `compound:prt/svp/PTKVZ` | 漏 |
| 词性（`pos`） | 启发式：首字母大写 → `NOUN`，其余 → `ADV`（`processor.py:528`） | **错** |

### 1.2 现状证据（修复前状态，已由 ADR-0028 决策改变）

| # | 证据 | 位置 | 等级 |
| --- | --- | --- | --- |
| E1 | 平台分支硬编码 `nlp = None` | `processor.py:240-246` | 代码可读 |
| E2 | 纯 Python 分支的产出形状 | `processor.py:515-576` | 代码可读 |
| E3 | 两条分支写入同一版本号 `PROCESSED_JSON_VERSION = "3.5.0"` | `processor.py:32`、`572`、`636` | 代码可读 |
| E4 | 设备上 `/api/settings` 的 `nlp_engine` 为 `pure_python` | `docs/agents/android-local-runtime.md:116` | 已实测（2026-11-05 交接记录） |
| E5 | 同进程 `/api/syntax/spacy-status` 返回 `{"path":"spacy","error":""}` | `docs/agents/android-local-runtime.md:116` | 已实测（2026-11-05 交接记录） |
| E6 | APK 内含完整 `de_core_news_sm-3.8.0.dist-info/`（12 个文件），`spacy.load` 可成功 | `docs/agents/architecture.md:121-122` | 已实测（2026-11-05 交接记录） |
| E7 | 测试把降级钉成规格 | `tests/test_server_android_fallback.py:118`（`assert "ENGINE=pure_python" in out`） | 代码可读 |
| E8 | 阅读器消费 `sent.topology` 渲染"五场域详细网格" | `static/js/reader.js:1292` | 代码可读 |
| E9 | `syntax_tree.get_spacy_nlp()` 走裸 `spacy.load`，无三级回退 | `syntax_tree.py:71-89` | 代码可读 |
| E10 | ADR-0018 §7.6：冷启动瓶颈是 spaCy 模型加载 ≈1.47s（占首启 58%），首选修法是惰性加载 | `docs/adr/2026-10-09-adr-0018-performance-measurement-before-runtime-swap.md:221-228` | 代码/文档可读 |

### 1.3 两层语义（修复前状态）

| 层 | 入口 | 是否加载 spaCy | 产出 |
| --- | --- | --- | --- |
| **主分析路径**（修复前） | `process_german_text()` | 否（`nlp = None`） | 纯 Python：`case` 恒空、无 `dep/head_*`、`topology` 仅 `mittelfeld`、`clause_tree` 单节点 |
| **句法专线** | `syntax_tree.get_spacy_nlp()` / `analyze_sentence_topology()` / `analyze_syntax_tree()` | 是（按需 `spacy.load`） | 真模型：依赖句法、五场域、从句树 |

这解释了 E4 与 E5 的表面矛盾：`/api/settings` 报的是**主分析路径**的引擎；`/api/syntax/spacy-status` 报的是**句法专线**的引擎。**ADR-0028 决定用 U2 消除该矛盾**：主路径也使用 spaCy，且句法专线收敛到同一加载器。

### 1.4 核心判据：宁漏勿错

- **漏**（缺字段）可接受；**错**（标错词性/格位）不可接受。
- 纯 Python 主路径的 `pos` 启发式会产出错误词性，因此不可接受。
- 这是本规格选择 U2 的唯一决定性理由；"实现更省事/更省内存"不构成保留纯 Python 的理由。

---

## 2. 目标与非目标

### 2.1 目标

1. **同口径**：Android 主路径与桌面使用同一套 `_LazyNlp` + 本地三级回退 + 硬失败语义。
2. **惰性**：导入期不加载模型；首次真正需要 NLP 时才加载。
3. **禁下载**：Android 运行期不得调用 `spacy.cli.download`、不得起 pip 子进程、不得联网。
4. **硬失败**：本地三级回退全部失败时抛错，**不得**返回纯 Python 结果。
5. **单一加载器**：`syntax_tree.get_spacy_nlp()` 收敛到统一加载器（实现于 2026-11-06 迁至 `delector/nlp_engine/model_loader.py`，`processor` 保留转发入口），保留 `_spacy_load_error` 诊断。
6. **可测量**：改造前后在模拟器上记录冷启动首响、首次分析墙钟、`am start -W TotalTime`、进程 RSS。
7. **可回退**：任一实现步骤可单独 revert；不涉及 schema/协议变更。

### 2.2 非目标

1. **不追求**模型档位变更（仍为 `de_core_news_sm`，ADR-0027）。
2. **不默认重算** Android 存量纯 Python 文章（同版本号，惰性迁移不命中；需重新导入或另立任务）。
3. **不做**真机（arm64）验证（本机无设备；只有 x86_64 模拟器）。
4. **不改变**桌面端已有行为（下载兜底语义保持不变）。
5. **不处理** Android 更新 chip / PWA 安装提示。
6. **不删除** B9 五级链的 L3/L5（需独立反证）。

---

## 3. 决策

| 编号 | 决策 |
| --- | --- |
| D1 | 删除 `processor.py:240-246` 的 `elif _android_runtime:` 平台分支；Android 与桌面同走 `_LazyNlp()`。 |
| D2 | `_LazyNlp` 首次调用时加载；导入期不加载。 |
| D3 | 本地三级回退：`spacy.load` → `importlib.import_module(名称).load()` → 数据目录 glob。 |
| D4 | 三级回退全部失败 → `RuntimeError`；`NLP_ENGINE = "spacy(加载失败)"`；不回退纯 Python。 |
| D5 | Android 禁止 `spacy.cli.download`；门控放在 `_load_model_with_autodownload()` **内部**（`processor.py:96-114`），不只依赖调用方。 |
| D6 | `syntax_tree.get_spacy_nlp()`（`syntax_tree.py:71-89`）改用统一加载器（2026-11-06 实现迁至 `model_loader.py`，`processor` 保留转发入口）；保留 `_spacy_load_error`。 |
| D7 | 桌面端行为不变。 |

---

## 4. 用户旅程与影响（修复后）

### 4.1 Happy Path（≤ 3 步）

1. Android 用户导入一篇新文章 → `process_german_text` 首次调用。
2. `_LazyNlp` 触发 `_resolve_nlp_model()` → 本地三级回退成功（不下载）；模型加载一次，后续复用。
3. 阅读器拿到真实 `case`/`dep`/`head_*`、五场域、从句树、可分动词；与桌面同口径。

### 4.2 失败路径

1. 本地三级回退全部失败 → `RuntimeError` + `NLP_ENGINE = "spacy(加载失败)"`。
2. 用户/维护者通过 `/api/settings` 与错误响应看到真实原因；不会得到"看起来正常但实际标错"的纯 Python 结果。

### 4.3 状态可见性（修复后）

- `/api/settings`：`nlp_engine == "spacy"`（加载成功后）。
- `/api/syntax/spacy-status`：`{"path":"spacy","error":""}`。
- 两者不再矛盾；都指向同一加载器。

---

## 5. 能力对照：修复前 vs 修复后

| 能力 | 修复前（纯 Python） | 修复后（spaCy） |
| --- | --- | --- |
| 格（`case`） | 恒空 | `morph.get("Case")` 真实值 |
| 依存（`dep`/`head_*`） | 不存在 | 真实依存与中心词 |
| 五场域（`topology`） | 仅 `mittelfeld` | 真实 `vorfeld/linke_klammer/mittelfeld/rechte_klammer/nachfeld` |
| 从句树（`clause_tree`） | 单节点 `hauptsatz` | 真实主从/并列结构 |
| 可分动词 | 不识别 | 识别 `compound:prt/svp/PTKVZ` 并回写 `separable` |
| 词性（`pos`） | 启发式（可能标错） | `token.pos_` |

---

## 6. 架构与数据

### 6.1 组件改动

| 组件 | 改动 |
| --- | --- |
| `processor.py:240-246` | 删除平台分支；Android 落入 `else: nlp = _LazyNlp()` |
| `processor.py:96-114` | `_load_model_with_autodownload()` 内部加 Android 本地-only 门控：`if _android_runtime: return _load_spacy_model(SPACY_MODEL_NAME)` |
| `processor.py:124-167` | `_resolve_nlp_model()` 不变（双检锁、硬失败、状态回填） |
| `syntax_tree.py:71-89` | `spacy.load(SPACY_MODEL_NAME)` → 统一加载器（2026-11-06 实现迁至 `model_loader.py`）；保留 `_spacy_load_error` |
| `routes/main.py::/api/settings` | 不变（live 读 `processor.NLP_ENGINE`） |
| `routes/syntax_hard.py::/api/syntax/spacy-status` | 不变（统一加载器后口径一致） |

### 6.2 数据与持久化

- **不做 schema 改动**；`PROCESSED_JSON_VERSION` 仍为 `"3.5.0"`（`processor.py:32`）。
- 两条分支同版本号（`processor.py:572`/`636`）；Android 存量纯 Python 结果不会被惰性迁移（`routes/articles.py:170-172`）重算。
- **默认不重算**：存量文章仍为纯 Python 产物；PR 必须写明"需重新导入或另立任务重算"。

---

## 7. 边界、风险与回退

| 风险 | 说明 | 处置 |
| --- | --- | --- |
| **首次分析加载耗时** | 桌面 1.5–1.7s；Android **未实测** | 实施时在模拟器测量并写入 ADR/PR；若超阈值，触发 ADR-0028 §6 复审 |
| **常驻内存峰值** | **未实测** | 用 `adb shell dumpsys meminfo` 记录 RSS |
| **低端机 OOM** | **未实测** | 硬失败可见；若目标基线不可用，触发复审 |
| **`syntax_tree` 裸 `spacy.load`** | 无三级回退，换打包方式会 E050 | 本规格要求统一到 `_load_spacy_model`；实施完成前仍存在 |
| **导入期意外加载** | 删除平台分支后，若导入期有代码调用 `process_german_text`，会触发加载 | 用子进程哨兵测试守住；`_preset_processed_json_lite` 已避免导入期调用（`content.py:196-215`） |
| **存量数据不重算** | 同版本号 | 默认接受；PR"已知边界"写明 |
| **回退** | 单 commit revert 即可恢复平台分支；无 DB/协议变更 | `git revert` 后全量测试复绿 |

---

## 8. 测试策略

### 8.1 RED（实现前先红）

1. `test_android_import_selects_lazy_spacy_not_none`
   - 子进程注入 `ANDROID_ROOT=/system`，patch `spacy.load` 为哨兵；
   - 断言导入成功、`NLP_ENGINE == "spacy"`、`nlp is not None`、导入期哨兵未被调用。
   - 现状下会因 `ENGINE=pure_python` / `nlp is None` 变红。

2. `test_android_runtime_load_never_downloads`
   - patch `_load_spacy_model` 抛错 + `spacy.cli.download` 哨兵；
   - 断言 `_resolve_nlp_model()` 抛 `RuntimeError` 且哨兵未调用。

3. `test_android_load_failure_is_loud_not_pure`
   - patch 本地加载失败；调用 `process_german_text("Der Hund schläft.")`；
   - 断言抛 `RuntimeError`，且**不返回**纯 Python 结果；`NLP_ENGINE == "spacy(加载失败)"`。

4. 更新 `tests/test_server_android_fallback.py:118`
   - `assert "ENGINE=pure_python" in out` → `assert "ENGINE=spacy" in out`；
   - 保留 `assert "DOWNLOAD_ATTEMPTED" not in out`；
   - 失败消息写明"这是 ADR-0028 决策，不是回归"。

5. `test_processor_and_syntax_tree_share_engine_status`
   - 统一加载器后，`process_german_text` 与 `get_spacy_nlp()` 的引擎状态一致。

### 8.2 GREEN

- 删除平台分支；
- `_load_model_with_autodownload` 加 Android 本地-only 门控；
- `syntax_tree.get_spacy_nlp` 收敛到 `_load_spacy_model`；
- `syntax_tree.analyze_syntax_tree` 在模型不可用时抛 `RuntimeError`（A7：D4 覆盖所有 spaCy 调用点），空输入仍返回 `sentence_count: 0`；
- 注释/展示字符串同步（删掉"无 dist-info"失效理由）。

### 8.3 测量（必须有数字）

在模拟器上记录改造前后（**未执行**：T5/T6 未执行，用户暂不开模拟器；本节保留为执行清单）：

| 指标 | 采集方式 |
| --- | --- |
| 冷启动到 `/api/health` 首响 | PowerShell `Measure-Command { Invoke-WebRequest ... }` |
| 首次分析墙钟 | 导入一句 V2 主句并计时 |
| `am start -W` TotalTime | `adb shell am start -W -n org.delector.app.emulator/org.delector.app.MainActivity` |
| 进程 RSS | `adb shell dumpsys meminfo org.delector.app.emulator` |

数字写入 ADR-0028 §4.2 与 PR 描述；不得用"未实测"交差，也不得用桌面基准顶替 Android、不得写成"预计/约"。截至 2026-11-06：**T5/T6 未执行，故上述数字均未测量**。

### 8.4 具名变异

| 变异 | 期望 |
| --- | --- |
| 把平台分支改回 `nlp = None` | `test_android_import_selects_lazy_spacy_not_none` 变红 |
| 允许 Android 走 `spacy.cli.download` | `test_android_runtime_load_never_downloads` 变红 |
| 本地加载失败时返回纯 Python 结果 | `test_android_load_failure_is_loud_not_pure` 变红 |
| `syntax_tree` 改回裸 `spacy.load` | `test_processor_and_syntax_tree_share_engine_status` 变红 |
| `syntax_tree` 加载失败回退纯 Python | `test_syntax_tree_load_failure_is_loud_not_pure` 变红 |

---

## 9. 验收判据（可执行、可证伪）

1. **状态一致**〔待 T5/T6 执行〕：模拟器 `/api/settings` 的 `nlp_engine == "spacy"`；`/api/syntax/spacy-status == {"path":"spacy","error":""}`；两者不再矛盾。
2. **数据形状**〔待 T5/T6 执行〕：导入一句 V2 主句后 GET 文章，至少一个 token 的 `case` 非空且 `dep` 非空；`topology` 的 `vorfeld/linke_klammer/mittelfeld/rechte_klammer/nachfeld` 不全为空。
3. **导入期不加载**：子进程哨兵断言导入成功且 `spacy.load` 未被调用。
4. **运行期不下载**：`DOWNLOAD_ATTEMPTED` 哨兵未出现；`_load_model_with_autodownload` 在 Android 分支不进入 `from spacy.cli import download`。
5. **失败硬失败**：本地三级回退全部失败时抛 `RuntimeError`，`NLP_ENGINE == "spacy(加载失败)"`，**不返回**纯 Python 结果。
6. **单一加载器**：`syntax_tree.get_spacy_nlp()` 与 `processor` 使用同一加载器；`test_processor_and_syntax_tree_share_engine_status` 绿。
7. **桌面回归**：`pytest tests -q` 全绿；桌面 `nlp_engine` 仍为 `spacy`；桌面冷启动不因导入期加载劣化。
8. **测量留痕**〔待 T5/T6 执行〕：ADR-0028 §4.2 与 PR 描述包含改造前后的冷启动首响、首次分析墙钟、`am start -W TotalTime`、RSS 数字。截至 2026-11-06 未执行，ADR 中相应项标记为 `未测量`。
9. **变异验证**：§8.4 五条变异分别变红，还原后复绿。
10. **存量边界**：PR"已知边界"明确写"Android 存量纯 Python 文章未重算，需重新导入或另立任务"。
11. **句法专线硬失败**（A7）：模型不可用时 `analyze_syntax_tree("…")` 抛 `RuntimeError`，信息区分"模型加载失败"与"无数据"；空输入仍返回 `sentence_count: 0`；`test_syntax_tree_load_failure_is_loud_not_pure` 与 `test_syntax_tree_error_distinguishes_no_data` 绿。

---

## 10. 证据等级图例

| 等级 | 含义 |
| --- | --- |
| **已实测** | 有可复跑的观察记录（本会话或交接文档中的设备/命令输出） |
| **代码可读** | 直接读源码/文档可确认，未运行 |
| **推断** | 由证据推导，未直接观察 |
| **未验证** | 尚未取得证据，不得当作结论 |

E4/E5/E6 为"已实测（2026-11-05 交接记录，本会话未复跑）"；Android 加载耗时/内存/OOM 为"未验证"，实施时必须测量。

---

## 11. 遗留事项（不阻塞本规格，但必须在 PR 写明）

1. **Android 存量文章不重算**：同版本号，惰性迁移不命中；需重新导入或另立任务。
2. **arm64 真机未验证**：本机无设备；模拟器结果不得写成"真机已验证"。
3. **阈值未定**：Android 首次加载耗时/内存的可接受阈值需在实施测量后写入 ADR-0028 §6。
4. **B9 L3/L5**：零命中不等于死代码，删除前需构造 `Token` fixture 反证不可达；不在本规格范围。
