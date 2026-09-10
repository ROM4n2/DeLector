# 内容供给侧：预置分级短文本包 + 自动化验收 Implementation Plan

> **Goal**: 把「遇见区能读但没得读」补上——① 用自动化 E2E + 行为探针替代 A7 双端手工冒烟（取得读中环可用的持续证据）；② job#1 离线产一次分级短文本包随发布内置、首启空库幂等 seed，让真实用户在手机端 **0 操作**就有分级短文可读。
> **Tech Stack**: Python 3.11 + FastAPI（`delector/` 包）/ SQLite `encounter_texts` / 原生 ES Module（`deck-bridge.js`）/ pytest + TestClient + node 探针
> **Spec Reference**: ADR-0010（遇见区 i+1 阅读桥）· ADR-0004（LAN 同步，记为下一阶段）· `delector/data/corpus_dict.py::OFFICIAL_CORPUS`（预置素材源）· Vault `PYTHON-STANDARDS` §8.2（断言契约）/ `AUTOMATION-GOTCHAS` §5（反冻结集合）
> **Global Constraints**:
> - 不引入新第三方依赖；预置内容**零 LLM、零网络、字节可复现**。
> - import 期不得联网/抛异常（红线 9）——生成模块须为**纯数据**。
> - `POST /api/encounter/texts`、`/import-pack` 受 `_require_localhost` 闸（红线 7）；跨边界契约必须行为探针（红线 11）。
> - 新增数据模块必须同步打包面（PyInstaller / build-release Linux+macOS / spec）+ 守卫逐条钉死。
> - 分支 `feature/encounter-content-supply` 逐 Task 原子 commit；CPE 实现 + CRV/主线程验收；收尾开 PR 合 master。

---

### Task 1: A7 服务端全链路 E2E [TDD Builder]
**Files**: Create `tests/test_encounter_journey_e2e.py`
**要点**: `TestClient(app, client=("127.0.0.1", 54321))` + 本机库夹具；6 用例——deck 镜像写入（≥3 `reps>0`）/ 加短文 201+列表 / annotate 已知-未知**双向**断言 / 本地词典离线取义（AI tier 打桩抛错）/ 进卡后镜像回读（word-only）/ 无 key PUT 403。
**Step Breakdown**: 写 6 用例 → 跑绿 → 变异自检（每条断言的"改错即红"推演）→ commit。

### Task 2: 客户端行为探针 [TDD Builder]
**Files**: Create `tests/test_encounter_journey_probe.py`
**要点**: 用**真实 annotate JSON**（TestClient 走真实路由）驱动逐字节拷贝的 `deck-bridge.mjs`（node 直跑）；断言 `known_tokens>0`、`known_rate>0`（且与 known/total 自洽）、`unknown_top` 排除已背词、`addCardToDeck` word-only（words+1 / cards 不变）、`DECK_KEYS` 常量钉死。node 缺失显式 skip。
**Step Breakdown**: 沿用 `tests/test_encounter_addcard.py` 探针模式 → 5 用例绿 → 变异自检 → commit。

### Task 3: 离线产包脚本 + 生成数据模块 [Builder]
**Files**: Create `tools/build_encounter_seed.py`、`delector/data/encounter_seed_dict.py`
**要点**: 读 `OFFICIAL_CORPUS` → `process_german_text` 分词 → `delector.tools.vocab_stats`（同源纯函数）填 `analysis` → `encounter-pack/v1`（`pack_id=seed-corpus-<id>`、`estimated_cefr` 取语料权威 cefr、`glosses=[]`）；CLI `--out/--levels(A1,A2)/--created-at`；产物为纯数据 Python 字面量模块。
**Step Breakdown**: 写脚本 → 跑生成 → 全包过 `validate_pack` → 两次生成字节一致 → 导入零 spaCy 验证 → commit。

### Task 4: seed 运行时接线 [TDD Builder]
**Files**: Modify `delector/core/database.py`（`seed_preset_encounter_texts` + `__all__`）、`delector/server.py`（import/`__all__`/`create_app` 调用）；Create `tests/test_encounter_seed.py`
**要点**: 空库守卫（`count==0`）+ 逐包 `import_encounter_pack`（`pack_id` 幂等）+ 逐包异常隔离（`logging.error` 可观测）；**不进 `init_db()`**（保住既有"空库=空列表"6 条契约），由 `create_app()` 在 `seed_preset_articles()` 后调用；测试含数据契约/幂等/非空库不触碰/脚本可复现/AST 探针（`create_app` 函数体切片断言）。
**Step Breakdown**: 写 seeder → 接线 → 11 用例 → 幂等与非侵入验证 → commit。

### Task 5: 打包面同步 [Builder]
**Files**: Modify `package_windows.py`、`.github/workflows/build-release.yml`（Linux+macOS 两处）、`tests/test_server.py`（守卫集合 8→9）
**要点**: 第 9 个 data dict 逐条钉死（AUTOMATION-GOTCHAS §5）；`DeLector.spec` 为本地产物（`.gitignore` 排除），守卫已 skip 兜底。
**Step Breakdown**: 三处注册 → 守卫扩集 → 守卫测试绿 → commit。

### Task 6: 收官 [Verifier]
**Files**: Modify `WORKMEMORY/PROJECT_OVERVIEW.md`、`WORKMEMORY/work.log`；Create 本计划文档
**要点**: 全量门禁 + Go 门禁；A7 手工段落改写为自动化等价物 + 残余真机风险；开 PR 合 master。

---

## 执行状态（2026-09-10 收官）

- 状态：**DONE**（T1–T6 全绿，PR 见 work.log）
- 逐 Task commit：T1 `a317ff2`（A7 服务端 E2E，6 用例）→ T2 `5324578`（客户端行为探针，5 用例）→ T3 `bf68a21`（离线产包脚本 + 4 包数据模块）→ T4 `6057c5a`（seeder 接线 + 11 用例）→ T5 `590d066`（打包面 8→9）→ T6（测试隔离修复 + 状态回填 + PR）。
- 门禁证据：pytest 全量 **716 collected / 715 passed + 1 skipped**；`agent`：`go vet ./...` 0 错、`gofmt -l .` 空、`go test -race ./...` 8 包全 ok。
- 预置内容实况：4 包（A1×2 / A2×2，`pack_id=seed-corpus-*`），`raw_text` 324–492 字符，`glosses` 空，`analysis` 含 `tokens_total/known_count/known_rate/level_hint/unknown_lemmas`；`estimated_cefr` 取语料权威 cefr（不被 `level_hint` 启发式覆盖）。
- **偏差与踩坑记录**：
  1. **T6 全量首跑 2 红**（`test_goethe_a1_lesen/hoeren` → `no such table: exam_trials`）：根因是 `delector/server.py:339` 的**模块级单例 `app = create_app()`** 在收集期按当时 env 建库并被多模块共用；T1/T2 新测试用**直接赋值** env + fixture **删库文件**，把该共享库删掉 → 其它模块 app 指向空库。修法：env 改 `setdefault`、fixture 改为**幂等建表 + 清表、永不删库文件**。教训已写入 OVERVIEW。
  2. T5 计划要求的 `DeLector.spec` 不存在（`.gitignore` 排除的本地 PyInstaller 产物），守卫已 `pytest.skip` 兜底 → 仅改三处。
  3. T3 生成物 `unknown_lemmas` 含 `{"lemma": "--", "count": n}`（spaCy 把破折号切为 token，`vocab_stats` 既有行为）——未改该纯函数，记为已知。
  4. 预置包数量受 `OFFICIAL_CORPUS` 中 A1/A2 素材量限制（共 4 篇）；增补需扩 levels 或补语料后重跑脚本。
- 已知边界（不进本轮）：桌面→手机 WiFi 推送（复用 ADR-0004）；预置包 gloss 富化（`import_encounter_pack` 按 `pack_id` 幂等**不更新**，需换 `pack_id` 或清表重导）；Android 真机 WebView/IndexedDB 行为（发版后一次性真机点检）。
