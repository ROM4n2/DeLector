# C1 实施计划：裁判结论回灌（Verifier-in-the-Loop）

> **Goal**: 依据 ADR-0024 §6 硬依赖与 ADR-0023 路线图，为 `polish_loop` 引入闭环裁判反馈通道（Verifier-in-the-loop），解决「生产链路上循环计数的与模型能看见的是两套规则」的机制断层；使模型在多轮润色中能够感知具体违规项并实施定向修复，同时受控于适用性闸、双限截断、三角一致性与停止策略。
> **Tech Stack**: Python 3.11 / FastAPI / spaCy 3.8 / pytest / DeepSeek Chat API
> **Spec Reference**: 
> - `docs/adr/2026-10-16-adr-0024-gaming-control-experiment-verdict-metric.md`（§6 四条硬依赖与资产折旧）
> - `docs/reviews/2026-10-16-judge-gaming-control-experiment.md`（60 局全量对照实验数据）
> - `docs/reviews/2026-10-16-open-items-backlog.md`（C1 行）
> - `docs/plans/2026-10-15-a1-judge-expansion.md`（裁判接入与分流）
> **Global Constraints**:
> - **四条硬依赖不可逾越**：
>   1. 裁判 FP 标定基线必须锁定（`tools/bench_judge_fp.py` 零误报，防止把误报作为必须修复指令回灌给模型）；
>   2. 回灌内容 MUST 过适用性闸（`violations_for` / `_polish_violations_of`）与双限截断（`truncate_evidence`: 40 行 / 4000 字节），严防跨文体污染（如散文被喂 A1 书信格式指令）与 prompt 溢出；
>   3. 三角一致性先于回灌落地：明确循环裁判（带 NLP）、模型自查工具 `writing_check`（不带 NLP）、与回灌源的优先级与判定标准；
>   4. 阴性对照不变量 `last_candidate(A2) ≈ last_candidate(A3)` 必须锁定为动产品代码前的基线。
> - **资产折旧隔离**：明确标注回灌落地后，ADR-0024 与 ADR-0023 §4.3 的结论只对「准入式裁判」生效，本计划落地时需重新分域或定义新评估基线。
> - **零外部破坏性**：全依赖必须可注入（`judge`、`violations_of`、`chat`、`clock`），单测严禁真调外部 LLM 或真实数据库。
> - **编码规范**：全文件 CRLF 行尾；`mypy --strict delector` 零错误；`ruff check .` 零告警；用例运行最坏 < 5s。
> **Branch**: `feature/c1-verifier-in-the-loop`（经 PR 合入 master，不直推）

---

### Task 1: 三角一致性规范定案与自查工具对齐 [Tier: 2-Standard] [Role: Architect]

**Files:** Modify `delector/services/polish_tools.py` · Modify `delector/tools/writing_check.py` · Test `tests/test_polish_loop.py`

**Context & Hazard:**
当前存在三方断层：
1. 循环裁判（`writing.analyze_a1_email`）带完整 spaCy NLP 与语法检测；
2. 模型自查工具 `writing_check`（`delector/tools/writing_check.py:14`）明确 `without_nlp=True`，语法族违规对模型主动查询不可见；
3. 将来的回灌源直接把裁判 violations 注入提示词。
若不统一，模型主动查到的结果与外部回灌的结果自相矛盾。

**Key Interfaces & Changes:**
- 规范三角优先级：
  - 终审与回灌权威源：统一收口至 `judge_fn` 与 `violations_of`（带文本族分流）；
  - `writing_check` 工具定位：作为轻量级交互工具，其输出结构必须与 `violations_of` 的键名对齐（`level`, `category`, `message`）；
  - 若运行环境支持轻量 NLP，探索向 `writing_check` 暴露一致的语法检测，或在工具输出中明确标注 `[快速模式: 不含深层语法规则]`，引导模型以回灌的裁判反馈为准。

**Step Breakdown:**
- [x] Step 1: 编写契约测试，断言 `writing_check` 与 `default_violations_of` 违规条目数据结构的一致性（schema 契约）。
- [x] Step 2: 调整 `polish_tools.py` 与 `writing_check.py`，消除字段歧义，统一输出口径。
- [x] Step 3: 运行 `pytest tests/test_polish_tools.py` 验证契约。

---

### Task 2: 适用性闸与双限截断的回灌格式化器（Evidence Renderer） [Tier: 1-Solo] [Role: TDD Builder]

**Files:** Modify `delector/services/polish_loop.py` · Test `tests/test_polish_loop.py`

**Context & Hazard:**
回灌内容不能裸塞 JSON。如果把非适用违规（如散文模式下的 A1 格式族 `a1_salutation_missing`）灌给模型，会诱导模型在散文中强加称呼语，直接破坏已建立的契约（`tests/test_server.py:6833`）。此外，海量违规可能撑爆上下文。

**Key Interfaces & Changes:**
- 实现纯函数 `format_judge_feedback(violations: list[dict[str, Any]], *, text_type: str = "letter") -> str`：
  1. 适用性过滤：仅保留与当前 `text_type` 匹配的违规（复用 `_polish_violations_of` / 适用性逻辑）；
  2. 格式化渲染：将违规列表转化为紧凑、结构化的德语/双语诊断提示（标明类别、位置、错误描述与修正指引）；
  3. 双限截断：强制通过 `truncate_evidence(..., max_lines=40, max_bytes=4000)` 处理。
- 注入消息格式定义：`[裁判反馈] 检测到以下未达标项，请在下一轮修改中重点修正：\n{evidence}`。

**Step Breakdown:**
- [x] Step 1: RED —— 编写 `test_format_judge_feedback`：测试过滤非适用违规、测试超过 40 行或 4000 字节时的精准截断、测试空违规时的安全退出。
- [x] Step 2: GREEN —— 在 `polish_loop.py` 中实现 `format_judge_feedback`。
- [x] Step 3: REFACTOR —— 确保与 `truncate_evidence` 及 `default_violations_of` 纯函数无缝组合。

---

### Task 3: 润色循环集成回灌通道与停止策略适配 [Tier: 2-Standard] [Role: TDD Builder]

**Files:** Modify `delector/services/polish_loop.py` · Test `tests/test_polish_loop.py`

**Context & Hazard:**
当前 `run_polish_loop` 在每轮拿到候选 `candidate` 后计算 `v`。若 `v >= prev_v`，在第 1 轮就直接触发 `REASON_NO_IMPROVEMENT` 退出，且 `messages` 中从未回灌违规。
在 Verifier-in-the-Loop 下：
- 当 `v > 0` 且未达到终止条件时，必须将格式化后的裁判反馈追加进 `messages`；
- 需允许至少一次基于反馈的重试尝试（避免第 1 轮 `v_1 == v_0` 时被 `v >= prev_v` 机械杀死而无法利用反馈）；
- 必须保持死循环防护：若在获得反馈后下一轮仍无改善（或连续两轮违规数不降），依然坚决触发 `REASON_NO_IMPROVEMENT` 或 `REASON_JUDGE_UNRELIABLE`；
- 保持 argmin 保护性回退不变（保护用户不受劣质修改影响）。

**Step Breakdown:**
- [x] Step 1: RED —— 编写测试用例：
  1. 验证第 1 轮有违规时，第 2 轮模型收到的 `messages` 末尾包含 `[裁判反馈]`；
  2. 验证模型在收到反馈后修复违规，循环顺利收敛至 `REASON_OK`；
  3. 验证模型无视反馈连续不改善时，循环受控退出并触发保护性回退。
- [x] Step 2: GREEN —— 在 `run_polish_loop` 中串联回灌逻辑，精细化 `prev_v` 与反馈轮次状态机。
- [x] Step 3: 运行 `tests/test_polish_loop.py` 全量用例，确认既有 stub 测试与新逻辑全部兼容。

---

### Task 4: 端到端路由接入与分流透传 [Tier: 2-Standard] [Role: Integrator]

**Files:** Modify `delector/routes/main.py` · Test `tests/test_server.py`

**Context & Hazard:**
`routes/main.py` 的 `/api/polish` 是真实入口，负责区分文本族（书信 vs 散文）、选择提示词与违规抽取器。必须确保回灌通道在路由层正确绑定对应文本族的适用性闸，不影响现有的 SSE 进度推送事件（`on_progress`）。

**Key Interfaces & Changes:**
- 在 `routes/main.py` 调用 `run_polish_loop` 处透传文本族标识；
- `on_progress` 回调新增 `event: "judge_feedback"`，使前端能够在界面上实时感知「裁判已指出错误，AI 正在二轮修正」；
- 契约验证：散文润色绝对不触发书信称呼语违规回灌。

**Step Breakdown:**
- [x] Step 1: RED —— 在 `tests/test_server.py` 增加模拟集成测试：散文输入带语法瑕疵，验证反馈中不包含 A1 称呼语指令；验证进度流中产生合法的 feedback 事件。
- [x] Step 2: GREEN —— 接通 `routes/main.py` 中的参数与进度事件透传。
- [x] Step 3: 回归跑 `tests/test_server.py` 相关润色测试。

---

### Task 5: 阴性对照复测与 ADR-0024 资产折旧再标定 [Tier: 3-Critical] [Role: Benchmarker]

**Files:** Modify `tools/bench_judge_gaming.py` · Modify `tests/test_bench_judge_gaming.py` · Update docs

**Context & Hazard:**
依据 ADR-0024 §6 第 4 条：回灌落地改变了 A3 臂的自变量本质（从「单比特准入」变成了「交互式反馈信号」）。必须更新 harness 并明确标注实验分域。

**Key Interfaces & Changes:**
- 更新 `bench_judge_gaming.py`，支持 `--feedback` / `--no-feedback` 模式对照；
- 运行确定性 mock 套件（`tests/test_bench_judge_gaming.py`），确保新旧两套评测逻辑互不干扰；
- 在 `docs/reviews/` 中登记新架构下的基准记录。

**Step Breakdown:**
- [x] Step 1: 在 harness 中实现回灌开关与参数化。
- [x] Step 2: 运行 `pytest tests/test_bench_judge_gaming.py` 确保 100% 通过。
- [x] Step 3: 更新相关文档引用。

---

### Task 6: 门禁复核、文档与交接收尾 [Tier: 1-Solo] [Role: Cleaner]

**Step Breakdown:**
- [x] Step 1: 逐字复刻 CI 门禁命令：
  - `mypy --strict delector tools`
  - `mypy --follow-imports=skip tests`
  - `ruff check .`
- [x] Step 2: 跑关联测试套件与全量定向冒烟。
- [x] Step 3: 确保全文件 CRLF 且无 lone LF；检查并更新 `WORKMEMORY/work.log`。
