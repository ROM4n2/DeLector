# C9 实施计划：C8 终审留档处置 + 「mock 漂移」静态闸

> **Goal**: 处置 C8 终审对抗性复核产出的 Yellow Cards（Y1~Y6，其中 **Y4 为活缺陷**），并把本次 CI 红灯暴露出的**新可闸化形状**（测试 patch 到已无调用点的符号）做成一道窄闸，使同类回归在任何未来贡献者的执行路径上响亮失败。
> **Tech Stack**: Python 3.11 / pytest / GitHub Actions (YAML) —— 零新依赖
> **Spec Reference**:
> - `docs/reviews/2026-10-18-c8-delivery.md`（C8 交付报告，含 Y1~Y6 的完整上下文）
> - `docs/reviews/2026-10-16-open-items-backlog.md`（C9 行）
> - `01-Rules/LAYERED-ARCHITECTURE.md` 无关；本计划的闸设计遵循技能 `mechanical-gate-authoring`（判据按机制形状、首日不许红、抑制必带理由、变异自证、禁止批量消音）
> **Global Constraints**:
> - **零新依赖**；闸为纯 stdlib 脚本 + CI job。
> - **不得放宽既有闸**：`tools/check_silent_degradation.py` 的 C1 收窄是已裁决的设计，**MUST NOT** 因 Y4 而重新放宽（这正是该闸头注释明确禁止的动作）。
> - **文件契约**：UTF-8 CRLF（0 lone LF）；`mypy --strict delector tools` / `mypy --follow-imports=skip tests` 零错误；`ruff check .` 零告警。
> - **并行占面（MUST）**：本工作流**禁触** C7 独占面（`static/german/workbench.html` · `static/js/**` · `static/css/**` · `tools/wb_*.mjs` · `tools/build_workbench_seed.py` · `tools/build_embedded_audio.py` · `tests/test_german_workbench.py` · `tests/test_workbench_tokens.py` · `tests/test_a1_workbench_source.py` · `tests/test_frontend_module_graph.py` · `tests/test_exam_domain.py` · `tests/test_audit_hardening.py` · `tests/test_wb_pair_persist_probe.py`）；亦**禁触** C6 面的 `tests/test_server.py` 与 `tests/test_desktop_shell.py`（C6 在其后开工，两者序贯）。
> **Branch**: `fix/c9-review-followups` —— 从 `master` 切出，全套门禁全绿后提 PR 合入。

---

## 🏛️ Decisions So Far

- **Y4 的裁定：修 + 另立判据，不放宽 C1。** `delector/routes/syntax_hard.py:254-255` 的 `except Exception: art_ids = []` 属**假值默认返回**形状（`return None/[]`、`x = []`），与 C1 收窄后覆盖的 `pass` 形态**机制不同**（前者让调用方拿到「空」而看不出异常，后者的错误路径被整块掐灭）。按闸自己的规矩「发现时另立判据」，本计划**先修 Y4**，并把「假值默认返回」的形状**登记为待观察类**——等出现**第二个实例**才升格为第三条判据（单实例判据＝按案例硬编码，是该闸的反模式）。
- **新闸的判据（mock 漂移）**：`tests/` 中形如 `monkeypatch.setattr(<alias>, "<symbol>", ...)` 的站点，若 `<symbol>` 在其目标生产模块里**已无任何调用点**，即判违规。本次 CI 红的 4 个失败（`httpx.get` → `httpx.stream` 的形状变更后补丁打空）正是此形状。这是一道**死测/假绿探测器**，不是风格检查。
- **为什么这两件事同批**：两者都是「把一次真实事故固化成不会复发的形状」，且都不碰 C6/C7 的占面。合并交付可省一轮 CI。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: 修 Y4 活缺陷（假值默认返回） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/routes/syntax_hard.py`（`:254-255` 附近）
- Test: 该缺陷的自然测试面（`tests/test_syntax_hard_api.py` 已有该路由的用例矩阵）

**Interfaces:**
- Consumes: 文章素材解析结果 `art_ids`
- Produces: 解析失败时**不再静默留空**——至少输出一条 warning 点名失败原因；若该空值会改变合并排名列表的内容，MUST 让调用方**可区分**「没有素材」与「素材解析失败」

**Injected Instincts:**
- [ ] `[Instinct: Empty-vs-Failed]`: 「空」与「失败」是两种语义，MUST NOT 折叠成同一个返回值。修法优先选自「让两者可区分」，其次才是「留痕」。
- [ ] `[Instinct: Do-Not-Widen-The-Gate]`: MUST NOT 为让新闸覆盖此站点而放宽 `check_silent_degradation.py` 的 C1。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 修 Y4 活缺陷.
> Mode: AFK | Role: TDD Builder
> Steps:
> 1. 实读 `delector/routes/syntax_hard.py:240-270`，确认 `art_ids` 的消费者与「空」在合并排名列表中的语义。
> 2. RED：写用例——让素材解析抛错，断言响应/日志**可区分**「无素材」与「解析失败」（按第 1 步选定的修法定断言）。
> 3. GREEN：按 `[Instinct: Empty-vs-Failed]` 实现。
> 4. 变异自证：去掉留痕/区分逻辑 ⇒ 新用例红；复原。
> 5. 跑 `python3 -m pytest tests/test_syntax_hard_api.py -q` + `ruff` + `mypy --strict delector/routes/syntax_hard.py`。
> Return: 摘要 + 物理凭据 + 变异自证原文。"

**Step Breakdown:**
- [ ] **Step 1**: 实读并判定「空 vs 失败」的可区分修法
- [ ] **Step 2**: RED（断言可区分性）
- [ ] **Step 3**: GREEN
- [ ] **Step 4**: 变异自证
- [ ] **Step 5**: 门禁 + Physical Evidence Gate
- [ ] **Step 6**: 原子提交（`fix(syntax): distinguish empty article material from a failed parse`）

---

### Task 2: 清 Y1 / Y2 / Y3 / Y5 / Y6 口径 [Tier: 1-Light] [Mode: AFK] [Role: Cleaner]

**Files:**
- Modify: `delector/core/db/content.py`（Y1：豁免理由只覆盖「单文件瞬时锁」，未覆盖「系统性裁剪失败 ⇒ 缓存无界增长」——**理由改准**，或按需补计数）
- Modify: `tools/build_dict.py`（Y2：豁免理由与该函数自身 docstring 相反；且吞掉的异常面比理由所述更宽）
- Modify: `tools/vault-proactive-scan.py`（Y3：`if not found_keys` 的 PASS 在**跳过文件未计数**时仍成立）
- Modify: `delector/services/tts.py`（Y5：`SSLCertVerificationError` 被当作可重试；`OSError(ENETUNREACH/EHOSTUNREACH)` 未被重试——与 docstring 的「连接/传输层」表述不符）
- Modify: `delector/services/tts.py`（Y6：错误信封不一致——裸 `_HandshakeError` vs `RuntimeError` 包装；若维持现状，MUST 在 docstring 写明是有意的）

**Injected Instincts:**
- [ ] `[Instinct: Reason-Must-Match-Code]`: Y1/Y2/Y3 的本质是**理由与代码不符**——修法优先改理由使其为真，只有当理由无法变真时才改代码。
- [ ] `[Instinct: Report-Dont-Silently-Fix]`: Y5 的两处误分类，修任一处都会改变真实重试行为 ⇒ 先算清代价（多试一次 vs 少试一次）再动，并在提交信息里写出算术。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: 清 Y1/Y2/Y3/Y5/Y6 口径.
> Mode: AFK | Role: Cleaner
> Steps:
> 1. 逐条实读源码与豁免注释，判定「改理由」还是「改代码」。
> 2. Y5：给出 `SSLCertVerificationError`（确定性失败，重试无意义）与 `OSError(ENETUNREACH/EHOSTUNREACH)`（传输层，理应重试）的处置算术。
> 3. 全部改完重跑 `python3 tools/check_silent_degradation.py` ⇒ MUST exit 0。
> 4. 跑 `python3 -m pytest tests/test_silent_degradation_incidents.py tests/test_server.py -q` + `ruff` + `mypy --strict`（改动文件）+ `mypy --follow-imports=skip tests`。
> Return: 摘要（逐条：改理由 or 改代码 + 为什么）+ 物理凭据。"

**Step Breakdown:**
- [ ] **Step 1**: 逐条判定修法（理由 vs 代码）
- [ ] **Step 2**: 实施 + Y5 的算术
- [ ] **Step 3**: 闸复跑 exit 0
- [ ] **Step 4**: 门禁 + Physical Evidence Gate
- [ ] **Step 5**: 原子提交（`chore(c9): align suppression reasons and retry classification`）

---

### Task 3: 「mock 漂移」静态闸 [Tier: 2-Standard] [Mode: AFK] [Role: Gate Engineer]
*(本次 4 个 CI 失败的形状；判据遵循 `mechanical-gate-authoring`)*

**Files:**
- Create: `tools/check_mock_drift.py`
- Create: `tests/test_check_mock_drift.py`
- Modify: `.github/workflows/ci.yml`（新增独立 job `mock-drift`）

**Interfaces:**
- Consumes: `tests/**/*.py` 与 `delector/**/*.py` + `tools/**/*.py`
- Produces: `def main(argv: Sequence[str] | None = None) -> int`，退出码 **0=通过 / 1=有违规 / 2=环境不可用**（与 `check_silent_degradation.py`、`check_master_commit_scope.py` 同形）

**闸的判据（**窄**，一条）**：
- 对 `tests/` 中每个 `monkeypatch.setattr(<obj>, "<symbol>", ...)`：
  1. 解析 `<obj>` 的来源（`import` 别名 → 模块）；
  2. 若 `<obj>` 指向**生产模块**（`delector.*` / `tools.*`），则要求 `<symbol>` 在该模块内**至少被调用/引用一次**（除定义点外）；
  3. 否则判违规 → 打印 `file:line | symbol | 目标模块 | 建议`。
- **抑制约定**：`# mock-drift-ok: <理由>`（同行或上一行），空理由即违规。
- **不做的**：不判断「patch 是否真的生效」「测试是否真的覆盖」——超出静态可达范围，做了就是假精度。

**Injected Instincts:**
- [ ] `[Instinct: Prove-It-Bites]`: MUST 用**本次真实的 4 处**回归做变异自证——把 `delector/routes/encounter.py` 的调用点临时改回 `httpx.get`（或在临时副本上模拟「符号已无调用点」），闸必须点名那 4 个 pytest 文件；复原后 exit 0。
- [ ] `[Instinct: No-Day-One-Red]`: 首跑 MUST 在当前树上通过；豁免逐处带理由。
- [ ] `[Instinct: State-The-Limit]`: 闸头注释 MUST 写明**它抓不到什么**（隔一层反射/setattr 字符串拼接的 patch、`importlib` 动态解析的符号、以及「符号仍被调用但语义已变」这类）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: 「mock 漂移」静态闸.
> Mode: AFK | Role: Gate Engineer
> Steps:
> 1. 读 `tools/check_silent_degradation.py` 作为先例，镜像其 argparse / 退出码 / `--report-only` 约定。
> 2. 先写**只报告模式**并全仓扫一遍，输出命中清单 + 计数；若 > 20 处，停下上报（同 C8 的反稀释规则）。
> 3. 实现判据；写 `tests/test_check_mock_drift.py`（正/负样本 + 空理由拒绝 + 退出码 0/1/2；用 tmp_path，绝不扫真仓）。
> 4. 变异自证：按上述 `[Instinct: Prove-It-Bites]` 复现本次 4 处回归 ⇒ 闸点名 ⇒ 复原 ⇒ exit 0。
> 5. 加 CI job `mock-drift`（fail-loud，无容错键）；既有 7 个 job 名 MUST 逐字不变（前后解析比对）。
> 6. 门禁：`pytest tests/test_check_mock_drift.py -v` + `ruff` + `mypy --strict tools/check_mock_drift.py` + YAML 解析 + CRLF。
> Return: 摘要 + 首扫清单 + 变异自证原文 + job 名前后对照 + 物理凭据。"

**Step Breakdown:**
- [ ] **Step 1**: 写只报告模式 + 全仓首扫（>20 停下上报）
- [ ] **Step 2**: 实现判据 + 单测（正负样本/空理由/退出码）
- [ ] **Step 3**: 变异自证（复现本次 4 处回归、点名、复原）
- [ ] **Step 4**: 加 CI job（fail-loud；既有 job 名逐字不变）
- [ ] **Step 5**: 门禁 + Physical Evidence Gate
- [ ] **Step 6**: 原子提交（`ci: add mock-drift gate`）

---

### Task 4: 门禁全景复核与交付 PR [Tier: 1-Light] [Mode: AFK] [Role: Cleaner]

**Files:**
- Modify: `WORKMEMORY/work.log` · `docs/reviews/2026-10-16-open-items-backlog.md`（C9 行改完成态）

**Step Breakdown:**
- [ ] **Step 1**: 逐字复刻 CI 门禁：`mypy --strict delector tools`；`mypy --follow-imports=skip tests`；`ruff check .`；`cd agent && go test ./... -count=1 && gofmt -l .`
- [ ] **Step 2**: **全量 pytest**（本计划新增了一道 CI job 且改了生产代码，定向不足以证明无回归）
- [ ] **Step 3**: 闸双跑：`check_silent_degradation.py` 与 `check_mock_drift.py` 均 exit 0
- [ ] **Step 4**: CRLF 卫生（0 lone LF）
- [ ] **Step 5**: 追加 `WORKMEMORY/work.log` DONE
- [ ] **Step 6**: 推送分支 + 创建 PR（base=master；因改 CI 定义，合并走 SSH 本地 `--no-ff`）

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Unknown 1: 「假值默认返回」是否会生出第二个实例]**：Y4 修完后，该形状剩下的实例数未知。**只有出现第二个实例才升格为第三条判据**（单实例判据＝按案例硬编码）。若在 C6/C7 或后续工作中再次撞到，立即回填本条。
- **[Unknown 2: `serpentine` 式的间接 patch]**：`mock-drift` 闸对「间接 patch」（经 `setattr(obj, name_var)`、`importlib`、或转存到中间变量再 patch）不可达。**不做投机覆盖**；若将来出现实例，按闸的规矩另立判据并在闸头登记该极限。
- **[Unknown 3: Y3 的跳过计数是否值得做成汇总断言]**：`vault-proactive-scan.py` 的 PASS 在跳过文件时仍成立。修法是「跳过即计数并在结论里体现」。属工具自身体检，优先级低于本计划其余项；若 Task 2 顺带能做则做，不做则留档。

---

## 🚫 Out of Scope

- **不放宽 `check_silent_degradation.py` 的任何判据**（Y4 的处置见 Decisions）。
- 不做 C6（测试文件切分）与 C7（workbench 拆分）——各自独立工作流。
- 不引入任何新依赖；不为 mock-drift 闸引入 AST 之外的重型分析。
- 不修 C8 已交付范围内、复核判为 PASS 的代码。