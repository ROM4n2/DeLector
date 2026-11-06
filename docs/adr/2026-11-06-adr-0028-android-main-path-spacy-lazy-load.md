# ADR-0028: Android 主分析路径使用 spaCy 惰性加载

- **状态**：ACCEPTED
- **日期**：2026-11-06
- **决策者**：席皓宇 (Haoyu Xi)
- **关联 ADR**：
  - [[0018-performance-measurement-before-runtime-swap]]（§7.6：冷启动瓶颈是 spaCy 模型加载 ≈1.47s，占首启 58%；首选修法是惰性加载）
  - [[0027-nlp-model-sm-only]]（模型档位只支持 `de_core_news_sm`；本 ADR 不改档位）
- **关联规格**：`docs/specs/2026-11-06-android-spacy-parity-spec.md`
- **关联运行时文档**：`docs/agents/android-local-runtime.md`、`docs/agents/architecture.md`

---

## 1. 背景与问题陈述 (Context and Problem Statement)

`delector/nlp_engine/processor.py:240-246` 在 Android（Chaquopy）运行时按平台把主分析路径的 `nlp` 设为 `None`：

```python
elif _android_runtime:
    # Android：模型以裸源码目录拷贝、无 dist-info，spacy.load(名字) 必失败；导入期加载只会
    # 白白阻塞启动页，且必须避免 spacy.cli.download 起 pip 子进程。既有行为已实际退化到纯 Python
    #（docs/agents/architecture.md）——这里显式化：不导入期加载、不联网下载，直接降级（红线 1）。
    nlp = None
    NLP_ENGINE = "pure_python"
    NLP_ENGINE_DETAIL = "Android：模型不在导入期加载（无 dist-info/避免 pip 下载），走纯 Python 降级"
```

由此 `process_german_text()` 在 Android 上走纯 Python 分支（`processor.py:579-581`），产出与 spaCy 分支存在结构性差距：

| 能力 | 纯 Python 主路径现状 | 性质 |
| --- | --- | --- |
| 格（`case`） | 恒为空字符串（`processor.py:537`） | 漏（缺字段） |
| 依存（`dep`/`head_*`） | 字段不存在 | 漏 |
| 五场域（`topology`） | 仅 `mittelfeld` 有值（`processor.py:550-556`） | 漏 |
| 从句树（`clause_tree`） | 固定 `hauptsatz` 单节点（`processor.py:557-567`） | 漏 |
| 可分动词 | 不识别 `compound:prt/svp/PTKVZ` | 漏 |
| 词性（`pos`） | 启发式：首字母大写 → `NOUN`，其余 → `ADV`（`processor.py:528`） | **错**（动词/形容词可能被标错） |

**核心判据：宁漏勿错。** 缺字段（漏）可接受；标错词性/格位（错）不可接受。纯 Python 主路径不是"少标"，而是会**标错**——因此不能作为 Android 的长期规格。

同时，同一进程里 `syntax_tree.get_spacy_nlp()`（`syntax_tree.py:71-89`）走裸 `spacy.load`，在 Android 上实际能成功加载；设备上 `/api/settings` 报 `pure_python`、`/api/syntax/spacy-status` 报 `{"path":"spacy","error":""}`，形成"同一进程两套引擎"的事实矛盾。

**历史权衡（保留，不抹掉）**：2026-11-06 的 ADR-0028 草稿一度选择"保持纯 Python 主路径，把降级规格化"。该方向被本判据推翻：能力缺口中的 `pos` 是"错"而非"漏"，不可接受。被否理由见 §5。

---

## 2. 决策 (Decision)

1. **Android 主分析路径使用 spaCy 模型 `de_core_news_sm`**：`process_german_text` 在 Android 上走与桌面相同的 `_LazyNlp` 路径；删除 `processor.py:240-246` 的平台硬编码 `nlp = None` 分支。
2. **惰性加载**：导入期不加载模型；首次真正需要 NLP 时才加载（`_LazyNlp` + 双检锁）。
3. **本地三级回退**：`spacy.load(名称)` → `importlib.import_module(名称).load()` → 数据目录 glob；任一成功即用。
4. **失败硬失败**：三级回退全部失败时抛 `RuntimeError`，`NLP_ENGINE` 变为 `"spacy(加载失败)"`；**不得**回退纯 Python（No-Silent-Failure）。
5. **禁止运行期下载**：Android 不得调用 `spacy.cli.download`、不得起 pip 子进程、不得联网。该门控必须放在 `_load_model_with_autodownload()` **内部**（`processor.py:96-114`），不能只依赖调用方不进入该函数。
6. **统一加载器**：`syntax_tree.get_spacy_nlp()`（`syntax_tree.py:71-89`）收敛到 `processor._load_spacy_model()`，保留 `_spacy_load_error` 诊断语义；消除"同一进程两套引擎"。
7. **桌面端行为不变**：本 ADR 只改 Android 路径；桌面仍走原有惰性加载与下载兜底语义。

**2026-11-06 澄清（D4 适用范围）**：D4 的"失败硬失败"适用于**所有 spaCy 调用点**，不只主分析路径。`syntax_tree.analyze_syntax_tree()` 在 `nlp is None` 时原实现返回 `_analyze_syntax_tree_pure_python(...)`，属于同一类静默降级；现改为抛 `RuntimeError`，并区分"模型加载失败"与"无数据"。理由：句法专线的纯 Python 产物同样是**错误标注**（无依存/五场域/从句树）而非"缺字段"，与宁漏勿错冲突；不澄清会留下后端唯一一处仍可静默降级的 spaCy 消费点。该澄清由用户于 2026-11-06 拍板（A7）。

---

## 3. 理由 (Rationale)

1. **宁漏勿错**：纯 Python 的 `pos` 启发式会产出错误词性，错误比缺失更有害；spaCy 提供真实 `case`/`dep`/`head_*`/五场域/从句树/可分动词。
2. **惰性加载已经满足冷启动预算**：ADR-0018 §7.6 判定冷启动只应走"惰性加载/延后模型加载"；本决策不在导入期加载，因此不违背该结论。
3. **单一引擎**：主路径与句法专线共用同一加载器，`/api/settings` 与 `/api/syntax/spacy-status` 不再互相矛盾。
4. **失败可见**：硬失败让模型不可用暴露在 `/api/settings` 与错误响应中，而不是用纯 Python 结果掩盖。

---

## 4. 后果 (Consequences)

### 4.1 正面

- Android 主路径获得真实格/依存/五场域/从句树/可分动词，与桌面同口径。
- 同一进程只有一个 NLP 引擎，状态端点一致。
- 导入期仍不加载，启动页预算不被模型加载直接挤占。

### 4.2 代价（必须如实记录，不许粉饰）

- **首次分析多付一次模型加载**：Android **未测量**。原因：测量任务 T5/T6 未执行（用户暂不开模拟器）。桌面基准 1.5–1.7s（`processor.py:81-83`）**不得**用来顶替 Android 数字。
- **模型常驻内存峰值**：**未测量**。原因同上（T5/T6 未执行，未采集 `adb shell dumpsys meminfo`）。
- **低端机 OOM 风险**：**未测量**。原因同上；当前无法判断目标设备是否可用。加载失败会按 D4 硬失败。
- **`syntax_tree.py:84` 裸 `spacy.load` 无三级回退**（已由 `2f79ccb` 消除）：现收敛到 `processor._load_spacy_model`，与主路径共用三级回退与 Android 禁下载门控。
- **句法专线也已改为硬失败**（A7，2026-11-06）：`analyze_syntax_tree()` 在模型不可用时抛 `RuntimeError`，不再返回纯 Python 拓扑；空输入仍返回 `sentence_count: 0`（"无数据"与"分析失败"可区分）。
- **两层口径已消除**：主路径与句法专线共用同一加载器与失败语义（`af027f8`、`2f79ccb`、A7）。

### 4.3 数据与迁移

- 不做 schema 改动；`PROCESSED_JSON_VERSION` 仍为 `"3.5.0"`（`processor.py:32`）。
- Android 存量纯 Python 结果与 spaCy 结果**同版本号**（`processor.py:572`/`636`），惰性迁移判据（`routes/articles.py:170-172`）不会命中。
- **默认不重算**：存量文章仍为纯 Python 产物；需重新导入或另立任务重算。该边界必须写进 PR 的"已知边界"，不得偷偷做掉。

### 4.4 不变

- 桌面端行为不变。
- 模型档位仍为 `de_core_news_sm`（ADR-0027）。
- `try_load_nlp_no_download()` 的"失败返回 `None`、绝不下载"语义不变。

---

## 5. 被否方案 (Alternatives Considered)

### 5.1 保持纯 Python 主路径 —— 否决

- 能力缺口不可接受：`case` 恒空、无 `dep/head_*`、`topology` 仅 `mittelfeld`、`clause_tree` 单节点、可分动词不识别。
- 决定性理由：`pos` 启发式会**标错**词性（首字母大写 → `NOUN`，其余 → `ADV`），不是"少标"。
- 判据：宁漏勿错；错误标注不可接受。
- 本方案曾是 2026-11-06 草稿的选择，现被推翻；保留此条以记录权衡。

### 5.2 回退纯 Python（可用性优先）—— 否决

- 本地模型加载失败时回退纯 Python，会制造静默降级，违反 No-Silent-Failure。
- 失败必须可见：硬失败 + `spacy(加载失败)`，让用户/维护者知道设备上模型不可用。

### 5.3 导入期强制加载模型 —— 否决

- 直接违反 ADR-0018 §7.6 的冷启动结论：模型加载 ≈1.47s（占首启 58%），不应进入导入关键路径。
- 本 ADR 选择惰性加载，保留启动页预算。

### 5.4 统一为纯 Python（句法专线也降级）—— 否决

- 会同时失去句法专线现有的真实依存/五场域/从句树；与宁漏勿错的方向相反。
- 产品能力净损失，且未来复审时要再恢复。

---

## 6. 复审触发条件 (Revisit Triggers)

满足任一条件时，必须重新评估本决策并另开 ADR（不得直接改代码）：

1. **Android 首次分析墙钟超出可接受阈值**（阈值需在实施测量后确定并写入本 ADR）。
2. **模型常驻内存峰值或低端机 OOM 超出可接受范围**（以实施测量的 RSS 为准）。
3. **目标设备基线无法加载 `de_core_news_sm`**（ABI、内存或打包限制）。
4. **冷启动预算成为硬约束，且惰性加载无法保留**。
5. **模型打包方式变更导致 E050，且三级回退无法覆盖**。

---

## 7. 守卫 (Guards)

1. `tests/test_server_android_fallback.py:118` 的断言从

   ```python
   assert "ENGINE=pure_python" in out
   ```

   改为

   ```python
   assert "ENGINE=spacy" in out
   ```

   并在失败消息里写明"这是 ADR-0028 决策，不是回归"。
2. 新增/补强（全部放在既有 `tests/test_server_android_fallback.py`，避免新增测试文件导致 CI 分片遗漏）：
   - `test_android_import_selects_lazy_spacy_not_none`：子进程注入 `ANDROID_ROOT`，patch `spacy.load` 为哨兵；断言导入成功、`NLP_ENGINE == "spacy"`、`nlp is not None`、导入期哨兵未被调用。
   - `test_android_runtime_load_never_downloads`：patch `_load_spacy_model` 抛错 + `spacy.cli.download` 哨兵；断言抛 `RuntimeError` 且哨兵未调用。
   - `test_android_load_failure_is_loud_not_pure`：断言加载失败时**不返回**纯 Python 结果。
   - `test_processor_and_syntax_tree_share_engine_status`：统一加载器后，两端引擎状态一致。
3. 保留既有 `test_android_spacy_download_gated_by_is_android_static`（`is_android()` 早于 `from spacy.cli import download`）；本 ADR 要求进一步把门控放进 `_load_model_with_autodownload()`。

---

## 8. 证据等级与边界

- **已实测**：APK 内含 `de_core_news_sm-3.8.0.dist-info/`（12 个文件）；设备上 `/api/settings` = `pure_python`；`/api/syntax/spacy-status` = `{"path":"spacy","error":""}`（2026-11-05 交接记录；本 ADR 编写时未复跑）。
- **代码可读**：`processor.py:240-246`、`515-576`、`572`、`636`、`96-114`；`syntax_tree.py:71-89`；`routes/articles.py:170-172`；`tests/test_server_android_fallback.py:118`。
- **未测量（T5/T6 未执行，用户暂不开模拟器）**：Android 首次模型加载耗时、内存峰值、低端机 OOM、arm64 真机行为。T5/T6 执行时必须测量；不得把"未测量"写成"预计/约"，也不得用桌面基准顶替。
