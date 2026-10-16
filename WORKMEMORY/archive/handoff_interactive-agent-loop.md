---
to: any
from: codebuddy
created: 2026-10-14 23:40
role: IMPLEMENT | TEST | VERIFY
required_capability: go-1.20+ / python-3.11-with-deps
status: closed
---
# Handoff: DeLector 交互层 agent 循环实施（Task 3~6 待做）

## 任务上下文
依据 ADR-0023（vault `08-Projects/DeLector/01-ADR/0023-interactive-layer-verification-driven-agent-loop.md`，`accepted`，**§8 为定稿口径**）与实施计划 `docs/plans/2026-10-14-interactive-agent-loop.md`（在 master）。分支 **`feat/interactive-agent-loop`**（已推远端，**未开 PR**）。台账 `.vault-exec-ledger.json`：**2/7 完成**。

## 已完成（含证据：测试命令与结果）
- **Task 0** `b76d45a`（CRV PASS）：门禁加身份校验（探 `GET /api/health`，**接受 200 与 503、只读 `app`/`version`**，与 Python 侧 `probe_identity` 契约对齐）+ 起服失败即 **fail-fast**（不再向被占端口发业务请求）+ 动态空闲端口替代硬编码 8001。**修的是一类假绿**：外来服务若答得对，门禁会替它背书（RED 实测 `Errno 10048 ×29` + 外来服务回 500）。
- **Task 2 代码半** `42e8420`（CRV PASS）：解释器探测由 `exec.LookPath("python")` 单名改为候选链 `$DELECTOR_PYTHON` → `python3` → `python`，逐个**实测** `import uvicorn, fastapi`（15s 短超时），并把选定路径**透传到起服 argv[0]**（四个调用点全查、无残留硬编码）。RED 证据：旧代码即使 `python3` 带依赖仍 skip。
- **Task 1** `64f7abf`（CRV PASS）：门禁 5 由「恰好 2 行」（假设空库，被 `create_app()` 的 7 篇预置短文污染、恒红）改为**前后快照相对断言**（净增恰好 2 行且标题恰为本次 fixture）；`level=="A1"` 作用域由整表收窄到净增行。
- **集成门禁现状**：`cd agent && go test -tags integration ./...` ⇒ **116 PASS / 0 FAIL / 0 SKIP**（9 包全 ok）；`go build ./...` / `go vet ./...` / `go vet -tags integration ./...` / `go test ./...` 全 0；`gofmt -l` 空；改动文件纯 LF。

## 未完成 / 下一步（按序）
1. ~~**Task 2 CI 半**~~ — **已完成并回炉**（分支提交 `f96a8d2`）：零 SKIP 判据（两级 `go list` 差集收窄到集成专属包）+ `-count=1`。首轮 CRV 开出两张红卡：Skip⇒job 静默绿、Go 缓存复用旧 ok。：`.github/workflows/ci.yml` 新增 integration job（ubuntu；装 `requirements.txt`；`cd agent && go test -tags integration ./...`；**必须带 `timeout-minutes`**）。台账里 `Task-2` 处于 IN_PROGRESS，等它落地才能 complete。
2. ~~**Task 3**：LLM client 收口~~ — **已完成并回炉**（分支提交 `9e17399`）：红卡（可用 key 被误报连接失败）修为 `parse_json` 开关；收口守卫升级为**结构判据**；新模块登记进 2 个 canonical 打包位点 + `test_server.py` 守卫集合。 —— 5 处裸 HTTP（`delector/routes/main.py` 的 `413/516/1449/1544/2374`，超时 **30/15/20/10/30** 各写各的；生成路径**零 `max_tokens`**）→ 新建 `delector/services/llm_client.py`；payload **MUST** 带 `max_tokens`；超时由调用方传入（保值语义不变）；错误仍 502。TDD：`tests/test_llm_client.py`（mock transport，**不发真请求**）。
3. **Task 4**：循环内核 `delector/services/polish_loop.py` —— 模型驱动流转（有工具调用则继续/无则请求收尾）+ **收尾终审守卫**（无裁判裁决不许终止）+ `v_n ≥ v_{n-1} ⇒ break` 且回退 `argmin` 候选 + `judge_unreliable` 哨兵 + 每轮**前置**检查 `{max_tokens_total, deadline_s}` + 裁判异常按 errors-as-messages 单轮降级 + 证据注入按行数/字节双限截断。测试 `tests/test_ai_polish_loop.py`，**逐条变异自证**（抽掉守卫/预算/哨兵 ⇒ 必须红）。
4. **Task 5**：`delector/services/polish_tools.py` —— 工具白名单**恰好 3 项只读**（`writing_check` / `analyze` / `vocab_stats`）+ 前置钩子 + **同进程直调**；测试 MUST 断言白名单与 `TOOL_REGISTRY` 的**差集含 `ingest`/`export`/`tts`**。
5. **Task 6**：`ai-polish` 返回契约加 `converged` / `unconverged_reason`（**只增不改**）+ 前端 `static/js/writer.js` 逐轮进度/取消/未收敛 toast + 跑 `python tools/check_frontend_api_contract.py`（契约闸）+ 发版守护套件。
6. **收尾**：开 PR（base master）→ CI 绿 → 合并（**HARD GATE 4：落地 MUST 经 PR，不直推**）。

## 风险与坑
- **别据「门禁绿」判定产品绿**：CI 不覆盖窗口形态；本批只到"测试基础设施可信"这一层。
- **动态端口有 TOCTOU 窗口**（`net.Listen(":0")` → 关闭 → 交给 uvicorn）：撞车靠 Supervisor 重试兜底，CRV 判低风险；但**不要**把它扩成"默认绑 8001"（那会退回静默打到外来服务的老路）。
- **`integration_test.go` 的 `HealthURL` 探针指向 `/api/tools/`**（不是 `/api/health`）：外来服务更容易在探针处回 200，目前靠 `assertSupervisorIdentity` 兜底（黄牌，Task 0 域外）。
- **`TestRunEndToEnd` 的 `PythonCmd` 透传只有结构验证**，缺该用例自身原始输出（黄牌）。
- **相对断言不覆盖"既有行被删改"**：`addedRows` 只遍历 after（import-pack 语义为只增；若要覆盖，加一条"before 标题多重集 ⊆ after"）。
- **Task 3 已完成** ⇒ 循环可按 token 预算调用；`DEFAULT_MAX_TOKENS = 4096` 是**保守占位**（计划 Unknown B：待 Task 4 的 stub 基线给出）⇒ **Task 4 MUST 给出该数的实测依据**。；**Task 6 必须与前端同批**（`ENDPOINT-CONTRACT-FRONTEND-SYNC` 规矩）。
- **（已更新）后来动了 Python 生产代码**：Task 3 新建 `delector/services/llm_client.py` 并收口 5 处；打包面已同步登记（2 个 canonical 位点 + 守卫集合）。⇒ Task 3~6 才开始动产品代码，Tier 2 纪律照旧（先 RED、变异自证、CRV 独立验收）。
- 计划外触碰过的文件：`agent/run_integration_test.go`（Task 0 时为恢复编译 +6 行；Task 2 代码半时透传解释器）—— 后续任务若再动它，注意它是**第三个**调用点。

## 关联
- 计划：`docs/plans/2026-10-14-interactive-agent-loop.md`（含执行期发现 + 顺序调整）
- 决议：ADR-0023（vault）+ §9 语言边界
- 另一份仍开放的交接包：`handoff_no-console-feedback-gaps.md`（真机双击验收 + digest 归一历史事件头）

---

## 响应（2026-10-15 02:40 | codebuddy）—— 本包任务已全部完成，**status: closed**

读包 → 执行完剩余三项 → 开 PR。台账 `.vault-exec-ledger.json` 现为 **7/7 completed**（Task-5 一度漏登，本次补记 `1cb60fc`）。

- **Task 4** `ff7235a`（CRV 一轮红卡：DI 参数「越界」经核对系误判——它正是本包风险节要求的「全部依赖注入」；`cancelled` 确属越界 ⇒ **回写计划**后结清）：`delector/services/polish_loop.py`。**风险节第 5 条要求的 `DEFAULT_MAX_TOKENS` 实测依据已给出**：最坏输入 2000 字符（端点 `req.text[:2000]`）录制桩跑满 3 轮 ⇒ 单轮最坏 691 token（139/139/2073 字符 ÷ 折算 3.0）、3 轮合计 785、保守 3×691=2073 ⇒ 保留 4096（2.97× 余量）；`TOTAL=4096 < 4096×3`（非真空闸）；`deadline=18.0 <` 前端 25s。本机**无真 tokenizer**（tiktoken/transformers 均 ModuleNotFoundError）⇒ 折算系数登记 UNVERIFIED 假设。
- **Task 5** `1cb60fc`（CRV 首轮 REWORK 后 APPROVED）：`polish_tools.py`。红卡是**判据失效型**：`analyze` 的「只读不下载」是无条件宣称，实际 `processor.py:95-114` 桌面缺模型会真跑 `spacy.cli.download` ⇒ 改成条件式说明 + 非真空测试（模型不可用时该测试红）。
- **Task 6** `2e61c88`（CRV 首轮 REWORK 后结清）：端点接循环 + `converged`/`unconverged_reason` 只增不改 + SSE 进度/取消 + toast + 契约闸。红卡：**断连收尸必须放 `try/finally` 的同步 `task.cancel()`** —— uvicorn 0.54 `spec_version=2.3` 下 starlette `listen_for_disconnect` **抢先**取消生成器，生成器内轮询 `is_disconnected()` 几乎永远输给它（原取消用例直接迭代 `body_iterator`，绕开了 `StreamingResponse.__call__` ⇒ 测不到）。
- **收尾**：PR **#136**（base master，HARD GATE 4 未直推）⇒ CI `38668055637` **success**。全量 `pytest -q` **1898 passed + 2 skipped**；ruff 0；mypy `--strict delector` 66 files 0；契约闸 PASS。
- **剩余待办（用户 2026-10-15 指示暂缓，非遗漏）**：① Android 真机点检（本批动了 `static/`，且 **SSE 的 `fetch` + `ReadableStream` 在 WebView 上未验证** —— 跑不了会降级到一次性 JSON，但降级路径本身必须真机确认）；② ADR-0023 §6 回写（Unknown B/C 定案）；③ Unknown A 子计划（裁判集扩充 —— **当前循环的实际收益面只有 A1 书信体**，闸门使非书信文本首轮即接受）；④ 有 Key 后回测真实轮次分布与真 token 计数。
