# A1 裁判集扩充（ADR-0023 第 ④ 步）实施计划

> **Goal**: 把 `ai-polish` 循环的裁判从「6 条书信格式/字数浅规则」扩到 **A1 真实评分维度的语法层**，从而抬掉 ADR-0023 §4.3 的「裁判集未扩到位之前不得宣称已实现」门槛；同时把循环的真实迭代价值面从「仅 A1 书信体」扩到**任意德语文本**。
> **Tech Stack**: Python 3.11 / spaCy 3.8.16 + `de_core_news_sm` / pytest（本仓无 pytest-asyncio）
> **Spec Reference**: ADR-0023（vault `08-Projects/DeLector/01-ADR/0023-…md`，`accepted`，§8 为定稿口径）—— **本子计划 = §8.5 施行顺序的第 ④ 步**；前序计划 `docs/plans/2026-10-14-interactive-agent-loop.md`（Task 0~6 已合入 master，PR #136）
> **Global Constraints**:
> - **禁止 LLM 裁判**：vault `01-Rules/AGENT-CONDUCT.md:249` 的三层校验明确 LLM-as-a-Judge **只用于无法形式化定义的开放语言**、**严禁参与物理真值判断**。语法维度是可形式化的 ⇒ MUST 确定性规则。LLM 辅助若将来要加，只能落在 advisory（`level=warning`）且不得阻止收敛（见 Fog of War）。
> - **误报（FP）是一等公民**：每条新规则 MUST 同时具备①正样本零误报 ②负样本能报 ③边界不报 三条用例；**官方 `A1_SCHREIBEN_TEIL2` 的 10 篇 `sample_email` 在扩后裁判下 `violations == 0` 是硬门**（连官方范文都报错 ⇒ 规则过严 ⇒ 循环永不可能收敛）。
> - **静默降级 = 静默假收敛（红线 1）**：`analyze_a1_email` 现为**纯规则、不依赖 spaCy**。接入语法维度后，若运行时无 spaCy ⇒ 语法违规会**静默消失**，裁判会判出「零违规」。故裁判输出 MUST 带引擎标记（如 `judge_engine` / `degraded`），且**端点 MISS 把降级状态带到返回体**（不得让"没检查"看起来像"检查通过"）。
> - **接线缝 MUST 显式登记（评审 RED#1）**：任何"裁判能力"的改动 MUST **同时指名"谁把它送进循环"**。本次固化 = 端点 `_run_polish` 注入 `judge=`（含 nlp 来源）。**禁止**只改 `writing.py` 就让 7 个任务的测试全绿 —— 那是 dead-green（生产路径上语法裁判恒不生效，而 §4.3 判据表还能被打勾解除）。
> - **降级态的诚实性（评审 RED#2 + 编排者修正）**：目标不变 —— **"没检查" MUST NOT 被当成"检查通过"**。但实现**分两层**，因为**运行期 fail-closed 会在 Android 上把功能打回原文**（实测依据：`delector/nlp_engine/processor.py:192-198` —— Android 分支**显式** `nlp=None`、不加载不下载 ⇒ 引擎恒 `rules_only`；此时若禁止收敛，循环的 `argmin` 回退会返回**原文** ⇒ 即 ADR §10.3 记过的「用户点了润色拿回原文」回归）：
>   1. **运行期 fail-open + 显式标记**：降级时循环照常收敛，但响应体 MUST 带 `judge_engine` / `judge_degraded`，前端 MUST 给出**可见提示**（不是 error toast，而是"语法检查未启用"一类）。
>   2. **声明 / 门禁层 fail-closed**：**任何人（含 §4.3 解除判据表、发行说明、宣传文案）在 `judge_degraded == true` 时 MUST NOT 把该次运行当"全引擎零违规"的证据**；判据表 MUST 显式列出「降级运行时 `converged` 的语义边界」这一行。
>   ⚠️ 禁止用"降级时塞一条人造 violation"实现 —— 那是把"没检查"伪装成"检测到错误"，同样违反不撒谎纪律。
> - **既有断言冲突的裁决规则（本次新增）**：当"只增不改"与某条既有测试的 **pin 对象本身错误**（钉住的是默认值而非生产装配）冲突时，允许把该 pin **从默认值改为装配点** —— 属**强化**不是放宽，但 MUST 在提交信息里逐条写明"改的是哪条断言、为什么这是强化"。
> - **只增不改**：`analyze_a1_email` 既有的 `suggestions` 字段与 `detect_*` 既有返回形状逐字不动，新增统一形状的并列字段；`tests/test_writing_rules.py`（34 条）与 `tests/test_goethe_a1_writing.py` 既有断言不许放宽。
> - 测试**一律 stub**（真 `DEEPSEEK_API_KEY` 在门禁上恒 skip = 没有测试）；spaCy 相关用例沿用既有的 `nlp` fixture 惯例。
> - 行尾 CRLF；提交信息中文 + 行号/函数锚点。
> **Branch**: `feat/a1-judge-expansion`（从 `master` 开；实现类任务全部在该分支上做、经 PR 落地）

---

## 🔬 Phase 1 物理取证（2026-10-15 实测，非引述）

**探针**：`nlp = nlp_engine.processor._resolve_nlp_model()`（spaCy 3.8.16 + `de_core_news_sm`），对 9 句带定向错误的德语逐一打印 POS / `morph(Case,Tense)` / `dep` / 位置，并同时跑仓内两件既有确定性算力。

| 维度（ADR §4.3 点名 + 实测新增） | 实测信号 | 仓内既有算力 | 结论 |
| --- | --- | --- | --- |
| 格的使用 · 冠词-名词一致 | ✅ `morph.Case` 齐（`meinem/meinen` 分 `Dat/Acc`） | ✅ `detect_determiner_noun_agreement`（`writing.py:288`）—— 实测 `Ich habe ein Hund.` ⇒ 报 `einen Hund`（`error_type=artikel`） | **接线即可** |
| 格的使用 · 介词支配格 | ✅ | ✅ `detect_preposition_case`（`writing.py:374`）—— 实测 `Ich fahre mit den Bus.` ⇒ 报 `dem Bus`（`error_type=kasus`） | **接线即可** |
| 格的使用 · **动词支配格** | ✅ 形态可解析 | ❌ **缺**：实测 `Ich helfe meinen Bruder.`（helfen 支配 Dat）⇒ 两件**都报 0** | **需新建 + 动词→格词表** |
| 动词位置（V2） | ✅ `ROOT` token 位置可分：正确句 `habe` 在 1，错句 `ich habe` ⇒ `habe` 在 2 | ❌ | **可纯规则化**（需从句/疑问/祈使豁免） |
| 语序（主谓宾 / 情态动词框架） | ⚠️ **解析不可靠**：`Ich muss gehen heute nach Hause.` ⇒ `muss` 被判 `dep=nk`、`gehen` 当 `ROOT` | ❌ | **先做 FP 标定，不得直接上** |
| 时态一致性 | ⚠️ `morph.Tense` 有（`gehe`=Pres），但「时间副词 → 时态」需词表，且历史现在时等属合法用法 | ❌ | **先做 FP 标定** |
| （实测新增）主谓一致 | ✅ `Number` 可分（`Die Kinder`=Plur vs `spielt`=Sing） | ❌ | **可纯规则化**（§4.3 未点名，需你拍板是否纳入） |

**另外两条测量结论**：
- **现有 6 条规则的清单**（`grep '"rule":' delector/services/writing.py`）：`a1_word_count`（偏短/偏多两支）、`a1_greeting_missing`、`a1_greeting_comma`、`a1_greeting_body_lowercase`、`a1_valediction_comma`、`a1_valediction_missing` ⇒ **全部是格式/字数，语法零覆盖**。
- **正样本集现成**：`delector/data/a1_writing_dict.py` 的 `A1_SCHREIBEN_TEIL2` 含 **10 篇官方范文**（字段 `sample_email`）+ `leitpunkte` + `useful_phrases`。这是 FP 标定的现成金标准，不需要自造。

---

## 🏛️ Decisions So Far

| # | 决策 | 依据 |
| --- | --- | --- |
| D1 | 语法维度**一律确定性规则**，不引入 LLM 裁判 | vault `AGENT-CONDUCT §10.2` 三层校验 |
| D2 | 裁判输出**扩并列字段**（统一形状），`suggestions` 逐字不动 | 只增不改（既有 34 条 `test_writing_rules` + 契约闸） |
| D3 | **官方 10 篇范文零违规**是每加一条规则都要过的硬门 | 否则裁判过严 ⇒ `v` 恒 > 0 ⇒ 循环永不收敛（新引入的失败模式） |
| D4 | spaCy 缺失 ⇒ 裁判 MUST **显式标记降级**，端点 MUST 透出 | 红线 1：静默降级会给错结果；这里表现为**静默假收敛** |
| D5 | ADR §4.3 门槛的**解除**由判据 + 用户拍板决定，agent 不自行解禁 | §4.3 原文「不得宣称已实现」 |

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: 违规形状统一 + 引擎降级标记（只增不改） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/services/writing.py`（新增统一抽取器与形状常量）
- Modify: `delector/nlp_engine/processor.py`（**新增只读** `get_loaded_nlp()`：只读 `_nlp_resolved` / `_nlp_model`，**不触发加载、绝不触发 `spacy.cli.download`**）
- Modify: `delector/routes/main.py`（`_a1_violations_if_letter` 改走统一抽取器；**`_run_polish` 注入 `judge=` 并接住引擎标记**；返回体透出 `judge_degraded`）
- Test: `tests/test_writing_rules.py`（追加）+ `tests/test_server.py`（**端点级接线回归，MUST**）+ `tests/test_ai_polish_loop.py`（按下面裁决规则处理那一条 pin）

**Interfaces:**
- Consumes: `analyze_a1_email(text, leitpunkte) -> dict`（既有）；`detect_determiner_noun_agreement` / `detect_preposition_case` 的 span 形状 `{severity, error_type, corrected_form, explanation_zh, start, end}`
- Produces: `def collect_violations(analysis: dict[str, Any]) -> list[dict[str, Any]]` —— 统一形状 `{"rule": str, "level": "error"|"warning", "message": str, "span": tuple[int, int] | None}`；**新键优先、旧键回退**（`violations` → legacy `suggestions` 的 `level=="error"` 过滤）
- Produces: `analyze_a1_email` 追加并列字段 `violations: list[dict]` 与 `judge_engine: str`（`"rules+spacy"` / `"rules_only"`），**既有键逐字不动**
- Produces（端点侧）: `_PolishOutcome` 追加 `judge_engine: str`；响应体 `result` 追加 `judge_degraded: bool`（**只增不改**）
- Produces（**接线缝，评审 RED#1 的闭环点**）: `def _make_judge(leitpunkte: list[str] | None, nlp: Any | None) -> Callable[[str], dict]`（端点侧装配器；**内部接住 verdict 的 `judge_engine` 交给 `_JudgeRecorder`**）+ `class _JudgeRecorder`（与既有 `_PolishReplyRecorder` 同形，`main.py:2238-2292`）
- Produces（**降级诚实性，评审 RED#2 的闭环点，按 Global Constraints 的分层方案**）: `judge_engine` 由裁决**如实透出**（引擎可用 ⇒ `"rules+spacy"`；不可用 ⇒ `"rules_only"`）并经 `_JudgeRecorder` 进 `_PolishOutcome` ⇒ 响应体 `judge_degraded` 忠实；**运行期不禁止收敛**（见 Global Constraints 的 Android 证据），门禁层的 fail-closed 由 Task 7 的判据表承担

> ⚠️ 本任务只立**形状 + 接缝 + fail-closed**，**不加任何新规则**（新规则在 Task 2+）。
> ⚠️ **不允许**"只改 `writing.py` 就算完"：MUST 有一条**走端点**的用例证明语法违规真被计数且 `judge_degraded is False`（否则就是 dead-green）。
> ⚠️ **既有 pin 的处置**：`tests/test_ai_polish_loop.py::test_real_judge_is_wired_by_default` 逐字钉住「内核默认裁判 = `writing.analyze_a1_email`」。本任务按 Global Constraints 的裁决规则把它**从默认值改为装配点**（断言生产链路 `_run_polish` 装配的裁判是 A1 裁判 + nlp；不是放宽 —— 旧 pin 钉的是"内核自带业务"，新 pin 钉的是"业务在产品层装配"），并在提交信息里逐条写明。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "统一 A1 裁判的违规形状并加引擎降级标记。现状：`analyze_a1_email` 出 `{suggestions:[{rule,level,message}]}`（纯规则），而 `detect_*` 出 `{severity,error_type,corrected_form,explanation_zh,start,end}`（spaCy span）—— 两套形状让端点层 `_a1_violations_if_letter` 只能认一套。① 在 `delector/services/writing.py` 加 `collect_violations(analysis)`：统一形状 `{rule,level,message,span}`，**新键 `violations` 优先、legacy `suggestions` 回退**，`level` 只认 `error`（warning 不阻止收敛 —— 这是 Task 4/5/6 已钉死的语义）；② `analyze_a1_email` **追加**并列字段 `violations` 与 `judge_engine`（`rules+spacy` / `rules_only`），既有键与既有断言逐字不动；③ 端点 `_a1_violations_if_letter` 改用 `collect_violations`，`_PolishOutcome`/响应体加 `judge_engine`/`judge_degraded`（只增不改，前端文案表不动）。TDD：先在 `tests/test_writing_rules.py` 写 RED（统一形状 + 回退 + level 过滤），再实现。**④（评审 RED#1，MUST）堵接缝**：`processor.py` 加只读 `get_loaded_nlp()`（不触发加载/下载）；`_run_polish` 改为**注入** `judge=_make_judge(leitpunkte, get_loaded_nlp())`；新增 `_JudgeRecorder` 接住 verdict 里的 `judge_engine`；在 `tests/test_server.py` 加**走端点**的用例（注入可用 nlp + 喂带语法错的非书信体文本 ⇒ 断言违规真被计数 且 `judge_degraded is False`）。**⑤（评审 RED#2，MUST）降级诚实性**：`judge_engine` 如实透出（可用 ⇒ `rules+spacy`；不可用 ⇒ `rules_only`）并把 `judge_degraded` 送进响应体与前端提示；**运行期 fail-open**（Android `nlp=None`，fail-closed 会让 argmin 回退返回原文 = 功能报废）、**声明/门禁层 fail-closed**（Task 7 的判据表在 `judge_degraded==true` 时不得被用作"全引擎通过"的证据）。两条用例：引擎可用 ⇒ `judge_degraded is False`；引擎不可用 ⇒ `judge_degraded is True` 且 `converged` 的语义边界写进 docstring。禁止靠塞人造 violation 实现。RUN：`python -m pytest tests/test_writing_rules.py tests/test_server.py tests/test_goethe_a1_writing.py tests/test_ai_polish_loop.py -q`（既有断言只许新增不许放宽；那条 pin 按裁决规则改造并在提交信息写明）。"

**Step Breakdown:**
- [x] Step 1: 写失败测试（RED：统一形状 / legacy 回退 / `level=warning` 不入违规 / **端点接线** / **降级态不返回 converged:true**）
- [x] Step 2: 跑并记录预期失败原文（**注意 RED 的形态是"报 0"或"字段缺失"，不是报错**）
- [x] Step 3: 实现 `collect_violations` + `violations`/`judge_engine` 并列字段 + `get_loaded_nlp()` + `_make_judge`/`_JudgeRecorder` + 端点注入与 `judge_degraded` 透出（GREEN）
- [x] Step 4: 变异自证（① 删回退分支 ⇒ 红；② 删 `level` 过滤 ⇒ warning 入违规 ⇒ 红；③ **端点不注入 judge（退回内核默认）⇒ 端点接线用例 MUST 红**；④ **`_make_judge` 去掉 fail-closed ⇒ 降级态用例 MUST 红**）
- [x] Step 5: 关联套件 + `ruff` + mypy 四档 + 原子提交（提交信息逐条写明那条 pin 的改造理由）

---

### Task 2: 接线既有算力（冠词-名词一致 + 介词支配格）+ 官方范文零违规门 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/services/writing.py`（`analyze_a1_email` 接 `nlp`，复用 `detect_*`）
- Test: `tests/test_writing_rules.py`、`tests/test_goethe_a1_writing.py`

**Interfaces:**
- Consumes: `detect_determiner_noun_agreement(tokens, base) -> list[dict]`（`writing.py:288`）· `detect_preposition_case(tokens, base) -> list[dict]`（`writing.py:374`）· `processor` 的惰性 `nlp`
- Produces: `def analyze_a1_email(text: str, leitpunkte: Optional[List[str]] = None, nlp: Optional[Any] = None) -> Dict[str, Any]` —— **签名向后兼容**（第三个参数可选）；`nlp is None` ⇒ 不产语法违规且 `judge_engine="rules_only"`；`nlp` 可用 ⇒ 语法违规并入 `violations`（`level="error"`）且 `judge_engine="rules+spacy"`

**关键设计（沿用既有惯例，勿自造）**：`analyze_essay_text(text, nlp)` 已是「显式传 nlp、无则纯 Python 降级」的形状 ⇒ 本任务照抄该形状，**不在 `writing.py` 里自己读全局 nlp**（否则 import 期/测试期行为不可控，且违反既有分层）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "把仓内**已有**的两件确定性语法算力接进 A1 裁判（照抄 `analyze_essay_text(text, nlp)` 的「显式传 nlp」惯例，不要在模块内自读全局 nlp）。① `analyze_a1_email(text, leitpunkte=None, nlp=None)`：`nlp` 可用时把 `detect_determiner_noun_agreement` + `detect_preposition_case` 的 span 折进 `violations`（映射 `error_type`→`rule`、`explanation_zh`→`message`、`start/end`→`span`、severity→level），`nlp is None` 时不产语法违规并把 `judge_engine` 置 `rules_only`。② **硬门（D3）**：新增用例遍历 `delector/data/a1_writing_dict.A1_SCHREIBEN_TEIL2` 的 10 篇 `sample_email`，断言在这两件算力下 **`violations == 0`**（官方范文被报违规 ⇒ 规则过严 ⇒ 必须修规则或收窄触发条件，不许改断言）。③ 负样本用例：`Ich habe ein Hund.` 与 `Ich fahre mit den Bus.` MUST 各报 1 条；边界用例：无冠词 / 双格介词（`in/auf`）/ 固定搭配 MUST **不报**（既有 `test_two_case_preposition_skipped` 等已覆盖，别删）。RUN：`python -m pytest tests/test_writing_rules.py tests/test_goethe_a1_writing.py -q`。"

**Step Breakdown:**
- [x] **Step 0（✅ 2026-10-15 已跑，评审黄卡已消）**：官方 `A1_SCHREIBEN_TEIL2` 10 篇 `sample_email` 在两件既有算力下 **误报 0/10**（逐篇 `det=0 prep=0`；评审点名的高危句 `für Ihre 2-Zimmer-Wohnung` / `vom 15. bis 18. August` / `im Preis enthalten` 均不误报）⇒ **本任务是"接线"而非"修规则"**，硬门基线绿。执行时把这条基线**落成用例**（不是再跑一次人眼）。
- [x] Step 1: 写失败测试（RED：负样本两例报违规 + 官方 10 篇零违规门）
- [x] Step 2: 跑并记录预期失败原文（**红色是"报 0"，不是"报错"**）
- [x] Step 3: 实现接线（GREEN）
- [x] Step 4: 变异自证（关掉一致性检查 ⇒ 负样本用例红；把双格介词豁免删掉 ⇒ 官方范文门红）
- [x] Step 5: 关联套件 + ruff + mypy 四档 + 原子提交

---

### Task 3: 新增规则——主谓一致（`Number` 一致） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/services/writing.py`（新增 `detect_subject_verb_agreement`）
- Test: `tests/test_writing_rules.py`

**Interfaces:**
- Consumes: spaCy `doc` 的 `tok.morph.get("Number")` 与 `tok.dep_ == "sb"`（实测：`Die Kinder spielt im Garten.` ⇒ `Kinder`=Plur、`spielt`=Sing）
- Produces: `def detect_subject_verb_agreement(tokens: List[Any], base: int) -> List[Dict[str, Any]]`（返回同 `detect_*` 既有 span 形状）

**Subagent Prompt Scaffold (for /dfs-exec):**
> "新增主谓一致规则 `detect_subject_verb_agreement(tokens, base)`，返回与 `detect_determiner_noun_agreement` **完全同形状**的 span 列表。判据：主语 `dep=="sb"` 的 `Number` 与定式动词的 `Number` 不一致即报错（实测锚点：`Die Kinder spielt im Garten.` ⇒ `Kinder`=Plur / `spielt`=Sing ⇒ MUST 报 1 条；`Die Kinder spielen im Garten.` ⇒ MUST 报 0 条）。**FP 守卫必须先写**：① 主语含并列（`Anna und Tom`）/② 主语是集合名词（`die Familie`）/③ 主语为 `man`、不定代词 /④ 复合时态（`hat ... gemacht`，`Number` 落在助动词上）⇒ 一律**不报**（宁漏不误）。每条 FP 守卫都要有用例。RUN：`python -m pytest tests/test_writing_rules.py -q`。⚠️ 若实测发现 spaCy 的 `Number` 在常见结构上不可靠（如 `es gibt`），**不要硬做** —— 停手报告，把该维度降级登记。"

**Step Breakdown:**
- [x] Step 1: 写失败测试（RED：负样本报 1 条 + 4 条 FP 守卫各不报）
- [x] Step 2: 跑并记录预期失败原文
- [x] Step 3: 实现（GREEN）
- [x] Step 4: 变异自证（抽掉 FP 守卫 ⇒ 对应用例红）
- [x] Step 5: 官方范文零违规门仍绿 + 原子提交

---

### Task 4: 新增规则——动词支配格（Rektion）+ 动词→格词表 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `delector/data/a1_verb_case.py`（A1 高频动词 → 支配格的事实数据 + 来源标注）
- Modify: `delector/services/writing.py`（新增 `detect_verb_case_government`；复用 `decline_determiner` 生成 `corrected_form`）
- Test: `tests/test_writing_rules.py`、`tests/test_a1_verb_case_data.py`（数据自检）

**Interfaces:**
- Consumes: `decline_determiner(lemma, gender, number, case)`（`writing.py:158`）· A1 动词清单来源 `delector/data/a1_dict.py`（`GOETHE_A1_VOCAB`）
- Produces: `A1_VERB_CASES: dict[str, str]`（lemma → `"Dat"` / `"Acc"` / `"Dat+Acc"`）+ `def detect_verb_case_government(tokens: List[Any], base: int) -> List[Dict[str, Any]]`

**实测锚点**：`Ich helfe meinen Bruder.`（helfen 支配 Dat）⇒ 现有的冠词一致与介词支配**两件都报 0**（探针实测）⇒ 这是真实缺口，且是最典型的 A1 语法点。

> ⚠️ **词表是人工登记的事实数据，不是生成物**：条目 MUST 标来源（歌德 A1 词表 + 教科书级支配格常识），MUST NOT 从 LLM 生成；并写一条数据自检测试（键必须都在 `a1_dict` 的 A1 lemma 里、值必须 ∈ {Dat, Acc, Dat+Acc}）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "新增动词支配格规则。① 建 `delector/data/a1_verb_case.py`，内容 = **人工登记**的 A1 高频动词→支配格映射（如 `helfen: Dat`、`danken: Dat`、`sehen: Acc`、`es gibt: Acc`…），条目数**先只收你能逐条确认的**，每个条目带一行来源注释；**禁止**用 LLM 批量生成（这是事实数据，不是文本生成）。② `detect_verb_case_government(tokens, base)`：找动词（`VERB`/`AUX`）→ 查表 → 取其宾语 NP 的 `morph.Case` 与之比对，不一致则用 `decline_determiner` 生成 `corrected_form` 并报 error（实测锚点：`Ich helfe meinen Bruder.` MUST 报 1 条；`Ich helfe meinem Bruder.` MUST 报 0）。③ FP 守卫：动词不在表内 / 反身动词 / 可分前缀动词 / 名词化动词 ⇒ 不报。④ 数据自检测试（键 ⊆ A1 lemma、值集合合法）。RUN：`python -m pytest tests/test_writing_rules.py tests/test_a1_verb_case_data.py -q`。**官方 10 篇范文零违规门（Task 2 起）必须仍绿。**"

**Step Breakdown:**
- [x] Step 1: 写失败测试（RED：负样本报 1 条 + 正样本 0 条 + 数据自检 + FP 守卫）
- [x] Step 2: 跑并记录预期失败原文
- [x] Step 3: 数据 + 规则实现（GREEN）
- [x] Step 4: 变异自证 + 官方范文零违规门复核
- [x] Step 5: 原子提交

---

### Task 5: 新增规则——主句动词位置（V2） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/services/writing.py`（新增 `detect_verb_second_position`）
- Test: `tests/test_writing_rules.py`

**Interfaces:**
- Consumes: spaCy `doc`（`tok.dep_ == "ROOT"` 的位置；实测：`Gestern habe ich gearbeitet.` ⇒ `habe` 在 index 1；`Gestern ich habe gearbeitet.` ⇒ `habe` 在 index 2）
- Produces: `def detect_verb_second_position(tokens: List[Any], base: int) -> List[Dict[str, Any]]`

**豁免面（必须逐条有用例，缺一条就会大批误报）**：从句（含 `dep="cs"` 的从属连词 / 关系代词）· 疑问句（`?` 结尾 / 疑问词开头）· 祈使句 · 并列句第二分句 · 引号内直接引语 · 列举/标题式片段。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "新增主句动词位置规则（德语 V2）。实测信号：主句定式动词 MUST 落在第二位置；`Gestern habe ich gearbeitet.`（`habe` index 1）正确，`Gestern ich habe gearbeitet.`（`habe` index 2）错误。实现 `detect_verb_second_position(tokens, base)`，返回既有 span 形状。**豁免面逐条写用例**（从句 / 疑问句 / 祈使句 / 并列句 / 直接引语 / 标题式片段）—— 这些结构里 V2 不成立，漏一条豁免就会在真实文本上大批误报。区分主句/从句优先用 `dep`（`ROOT` vs `cs`/`mo` 等）而不是标点启发。RUN：`python -m pytest tests/test_writing_rules.py -q`。"

**Step Breakdown:**
- [x] Step 1: 写失败测试（RED：错句报 1 条 + 正句 0 条 + 6 条豁免各 0 条）
- [x] Step 2: 跑并记录预期失败原文
- [x] Step 3: 实现（GREEN）
- [x] Step 4: 变异自证（抽掉任一条豁免 ⇒ 对应用例红）+ 官方范文零违规门复核
- [x] Step 5: 原子提交

---

### Task 6: 语序（情态框架）与时态一致性的 **FP 标定实验**（决定做/不做/降级） [Tier: 3-Critical] [Mode: HITL] [Role: TDD Builder]

**Files:**
- Create: `tools/bench_judge_fp.py`（可复跑标定脚本，输入 = 正样本集 + 负样本集，输出 = 每条候选规则的 FP/FN 计数与样例行）
- Test: `tests/test_judge_fp_bench.py`（脚本自身的行为契约：喂已知样本 ⇒ 已知计数）

**Interfaces:**
- Consumes: `A1_SCHREIBEN_TEIL2`（10 篇官方范文，正样本）· 自建负样本集（每维 ≥5 句手工构造的定向错误句）· 候选规则（本任务**只写探测实现，不接线**）
- Produces（**可证伪签名，评审黄卡已补**）: `def measure_candidates(candidates: Sequence[Candidate], positives: Sequence[str], negatives: Sequence[str]) -> Report`（`Report = {per_candidate: [{name, fp, fn, fp_samples: list[str], fn_samples: list[str]}], verdict: dict[str, str]}`）+ CLI `python tools/bench_judge_fp.py --json`（**退出码 0 = 标定完成；非 0 = 样本集自身无效**）；每维结论 ∈ {**接线为 error** | **接线为 warning(advisory)** | **不做**}，附判据与阈值

> **为什么这维度必须是 HITL + Tier 3**：探针已实测 spaCy 对 `Ich muss gehen heute nach Hause.` 的**框架解析失败**（`muss` 判 `nk`、`gehen` 判 `ROOT`）⇒ 直接接线会**误报**，而误报比漏报危险（模型会去"修"一个不存在的错误 = 奖励黑客的反面）。做/不做是**产品语义决定**，必须人拍板。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "做一次可复跑的 FP 标定实验，**不接线**。① 建 `tools/bench_judge_fp.py`：对两条候选维度（情态动词框架语序 / 时间副词与时态一致性）各写一版**探测实现**（可住在脚本里，不必进 `writing.py`），在 a) 官方 10 篇 `sample_email`（正样本，期望 FP=0）与 b) 每维 ≥5 句手工定向错误句（负样本，期望能报）上逐句跑，输出原始计数表 + 误报样例全文。② 建 `tests/test_judge_fp_bench.py` 钉脚本自身行为（给固定样本 ⇒ 固定计数；不许"跑得过但数不清"）。③ 产出**带阈值的结论建议**（例如：FP 率 ≤ 某值 ⇒ 可做 error；否则 warning 或不做的理由），并**把误报样例原文带回**（不许只报比例 —— 比例无法证伪判据）。RUN：`python tools/bench_judge_fp.py` 与 `python -m pytest tests/test_judge_fp_bench.py -q`，原始输出全带回。⚠️ 若某维在正样本上就误报 ⇒ **如实结论是"不做"**，不许调样本让它好看。"

**HITL 裁决（用户 2026-10-15 拍板，Step 4 已结）**：
- **A 维（情态动词框架语序）= 不做**。依据：实测负样本 6/7（「实词夹在情态动词与末位动词之间」整族不可见 ⇒ FN），且样本外追补的 3 句逗号并列**正确**句全部误报（⇒ 若计入对照组，warning 档条件亦不成立）——**FP 与 FN 同源**，两侧都破。标定产物与数据保留在 `tools/bench_judge_fp.py` 作记录，**不接线**（后来者勿把它当"只是还没接线"）。
- **B 维（时间副词 ↔ 时态一致性）= 接线为 `level="warning"`（advisory）**。依据：正样本 FP 0/35、负样本 7/7、对照 0/6，两档阈值均成立（样本偏小：7 错 + 6 对照 ⇒ 先 advisory，积累真实用法后再议升 error）。**不阻断收敛**：`violations_of` 只认 `level=="error"`（Task 4 已钉死的语义）。
- **advisory 的可见性**（编排者定的最小实现）：warning 必须真能被看到，否则是 no-op ⇒ 响应体 `result` 追加 `judge_advisories: list[str]`（**只增不改**），前端渲染与本计划的 Task 7 同批。

**Step Breakdown:**
- [x] Step 1: 建正/负样本集（负样本每维 ≥5 句，逐句标注期望）
- [x] Step 2: 写探测实现 + 脚本（含脚本自身测试）
- [x] Step 3: 跑出原始计数表与误报样例
- [x] Step 4: **HITL**：把结论（做 error / warning / 不做）交用户拍板
- [x] Step 5: 按拍板结论决定是否接线（若接线 ⇒ 走 Task 2~5 同款门禁：正样本零违规 + FP 守卫 + 变异自证）+ 原子提交

---

### Task 7: 适用性闸门收窄（循环价值面扩到任意德语文本）+ §4.3 门槛解除判据 [Tier: 2-Standard] [Mode: HITL] [Role: TDD Builder]

**Files:**
- Modify: `delector/routes/main.py`（`_a1_violations_if_letter` 的闸门范围 + **文本族感知的系统提示词装配**）
- Modify: `static/js/writer.js`（**降级可见提示的生产者** —— 评审黄卡：Global Constraints 要求"前端 MUST 给出可见提示"，但此前**没有任何任务的 Files 覆盖 `static/`** ⇒ 该 MUST 无生产者。实现：`judge_degraded === true` 时给一句**非阻断**提示（如"语法检查未启用：本机未加载德语模型，本次仅做格式/字数检查"），不是 error toast）
- Modify: `delector/services/polish_loop.py`（**只加一个可选参数** `system_prompt: str | None = None`（None ⇒ 用现有 A1 默认值，向后兼容）；业务提示词由产品层传入 —— 见下方"立论冲突的解法"）
- Modify: `docs/plans/2026-10-15-a1-judge-expansion.md`（本文件：记录解除判据与实测值）
- Test: `tests/test_goethe_a1_writing.py` + **`tests/test_server.py`（评审黄卡：该文件此前未列入 ⇒ 会让一条既有回归闸变成 dead-green，见 scaffold ③）**

**要解决的现状（实测）**：`_a1_violations_if_letter` 目前「称呼语不合法 ⇒ 零违规」，因为当时的裁判**只有书信格式规则**。扩了语法维度后，前提变了：**语法违规与题材无关** ⇒ 语法维度对任何德语文本都该生效，只有书信格式/字数规则保留"仅书信体"闸门。这一步把循环的真实迭代价值面从「仅 A1 书信体」扩到「任意德语文本」。

**Interfaces:**
- Consumes: `collect_violations(...)`（Task 1）· 各维度规则 · `polish_loop.run_polish_loop(system_prompt=...)`（本任务新增的可选参数）
- Produces（**可证伪签名，评审黄卡已补**）: `def violations_for(kind: str, verdict: dict[str, Any]) -> list[dict[str, Any]]`（`kind ∈ {"letter", "prose"}`：`letter` ⇒ 格式族 + 语法族全计；`prose` ⇒ **只计语法族**）+ `def pick_system_prompt(kind: str) -> str`（文本族 → 提示词；**业务知识住在产品层**）+ `docs/plans` 里的 **§4.3 解除判据表**（每条判据 + 实测值 + 是否满足）

> **立论冲突的解法（评审黄卡 #2，选 b 而非 a）**：原立论"把循环的真实迭代价值面扩到任意德语文本"与内核里**逐字 A1 书信**的 `POLISH_LOOP_SYSTEM_PROMPT`（`polish_loop.py:144-152`）直接冲突 —— 对非书信体，它会**诱导模型加一个称呼语**，而格式族规则此时已被关掉 ⇒ 污染无守卫。故选 b：**提示词按文本族参数化**，由产品层（`main.py`）装配。这同时朝 `architecture.md` 登记的"业务知识上提"方向挪了一步（与日后 Pi 式重构同向、不冲突）。⚠️ 若执行中发现该参数化会破坏 `tests/test_ai_polish_loop.py` 里钉住提示词/契约的用例，按 Global Constraints 的裁决规则处理并逐条写明。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "收窄适用性闸门的范围。现状：`_a1_violations_if_letter` 因当时裁判只有书信格式规则而做成「称呼语不合法 ⇒ 零违规」；语法维度接线后**前提变了** —— 语法与题材无关。改法：闸门改按**规则族**分流 —— ① 格式/字数族（`a1_greeting_*` / `a1_valediction_*` / `a1_word_count`）仍仅对书信体生效；② 语法族（冠词-格一致 / 介词支配格 / 动词支配格 / 主谓一致 / V2）对**任意德语文本**生效。测试 MUST 覆盖：非书信体文本带语法错误 ⇒ **真被计数**（与今日"零违规"对比，这是行为变更）；书信体文本的格式规则语义不变。③ 同时在本计划文件里落一张 **§4.3 解除判据表**（维度数 / 官方正样本零误报 / 负样本 recall / 非书信文本可判 / 降级标记可见性 各条 + 实测值），**满足与否由用户拍板**，agent 不自行解禁。RUN：`python -m pytest tests/test_goethe_a1_writing.py tests/test_server.py tests/test_ai_polish_loop.py -q` + 全量。⚠️ 本任务会改变产品行为（非书信文本从"首轮即接受"变为"真迭代"），执行前 MUST 先跑一遍 `tests/test_server.py::test_ai_polish_diff_mocked` 系用例确认既有断言仍成立。"

**Step Breakdown:**
- [x] Step 1: 写失败测试（RED：非书信体带语法错误 ⇒ 被计数）
- [x] Step 2: 跑并记录预期失败原文
- [x] Step 3: 闸门按规则族分流（GREEN）
- [x] Step 4: 全量套件 + 契约闸 + §4.3 解除判据表落盘
- [x] Step 5: **改写 `tests/test_server.py::test_ai_polish_non_letter_text_is_not_rolled_back`**（评审黄卡③：它在"现状 / 仅接 nlp / 收窄闸门"**三态下都绿** ⇒ 已不守卫任何东西）为能区分行为的两条：① 非书信体 + 语法错（且桩模型不修）⇒ 断言语法违规**真被计数**；② 明确并钉住收窄后的产品语义（该修不动时是回退原文还是首轮即接受）—— 后者正是 ADR §10.3「功能忘了判就是报废」失败模式的重现，MUST 有断言，不许只留在 Fog of War。
- [x] Step 6: **HITL**：判据表交用户拍板（是否允许宣称"已实现"）+ 原子提交

### §4.3 解除判据表（2026-10-15 实测值；签批归用户）

| # | 判据 | 口径 | 实测 | 满足 |
| --- | --- | --- | --- | --- |
| 1 | **维度覆盖**（ADR §4.3 点名四项：动词位置 / 时态一致性 / 语序 / 格的使用） | 每项 MUST 有确定性规则且接线 | **动词位置** = `wortstellung`（主句 V2 + 8 豁免）✅ · **格的使用** = `artikel` + `kasus` + `rektion` 三条 ✅ · **时态一致性** = `tempus`（**warning/advisory**，按用户裁决）🟡 · **语序（主谓宾/情态框架）** = **经实测评审判定不做**（负样本 6/7 + 样本外正确句 3/3 误报 ⇒ FP/FN 同源）❌ | **部分**（3 error + 1 advisory + 1 明确不做） |
| 2 | **官方正样本零误报** | 10 篇 `A1_SCHREIBEN_TEIL2.sample_email` 逐句 error 级违规 == 0 | `FP_TOTAL 0`（逐篇全 0） | ✅ |
| 3 | **更宽的合法句硬门** | `COMMON_CORRECT_SENTENCES`（≥51 句，含类覆盖清单）零语法族违规 **且** `judge_engine == "rules+spacy"`（防降级假绿） | **51 句全绿** | ✅ |
| 4 | **编排者独立广度扫雷** | 另取 30 句常见正确德语（焦点小词/自由第三格/前置状语/从句前置/疑问祈使/反身/可分动词…） | **FP = 0** | ✅ |
| 5 | **负样本召回** | 每个已接线维度都有定向错误句用例（且变异自证：抽掉守卫即红） | 三新维度 + 两个既有算力各有负样本用例；变异自证 5 组以上 | ✅ |
| 6 | **非书信文本可判** | 语法族对**任意德语文本**生效（不再要求书信体） | 已落地（闸门按规则族分流：格式族仅书信体、语法族任意文本） | ✅ |
| 7 | **降级可见性**（不许"没检查"伪装成"检查通过"） | `judge_engine`/`judge_degraded` 忠实透出 + 前端非阻断提示 | 已落地（含 no-key 路径抑制不实文案） | ✅ |
| 8 | **"浅裁判失效"对照实验**（奖励黑客的正面证据：模型学会通过检查 vs 真变好） | 需真实模型与 Key | **未做**（阻塞于 `DEEPSEEK_API_KEY` 缺失） | ❌ |

**判据结论（供签批）**：第 1 项**部分**满足、第 8 项**未做** ⇒ 建议**只允许限定表述**，例如「裁判已扩到 A1 语法维度（动词位置 + 格的使用三规则 error 级、时态一致性 advisory；语序经实测评审判定不做）」，**不建议**解禁 §4.3 原文所禁的那句无条件"已实现"—— 因为第 8 项（浅裁判是否真被模型针对）尚无证据。

**已知边界（随判据表一并登记）**：① 书信缺称呼语 ⇒ 判据 `greeting.valid` 归 prose ⇒ 格式族（含 `a1_greeting_missing`）**永远不被计数**（继承自旧闸门）；② 候选侧 kind 逐候选翻转（旧欠账，未收口）；③ 非书信文本模型修不动 ⇒ `no_improvement` ⇒ **回退原文**（有断言 + 三处 docstring，前端给人话原因码）；④ advisory 在 argmin 回退路径下可能与出口文本不对应（不进任何计数）；⑤ warning 级条目按族分居 `violations`（格式族）/ `advisories`（语法族），取全集需并集两键。

---

### Task 8: 内核接缝加固（超时 / 线程 / 不可达分支） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

> **由来**：评审 RED#3 与模式 3 要点 4。**不是** Pi 式重构（那已暂缓）—— 本任务只在既有结构上补三处缝，不重画层。

**Files:**
- Modify: `delector/services/polish_loop.py`（`dispatch` 包超时；同步 `judge` 移出事件循环）
- Modify: `delector/routes/main.py`（删/修那个**不可达**的 `except LLMError` 分支；SSE 侧错误帧语义）
- Test: `tests/test_ai_polish_loop.py`、`tests/test_server.py`

**Interfaces:**
- Consumes: `asyncio.wait_for(...)` · `asyncio.to_thread(...)` · 既有 `DEFAULT_PER_CALL_TIMEOUT_S` / 剩余 deadline 口径
- Produces: ① `dispatch` 调用 MUST 受 `asyncio.wait_for(timeout=min(剩余 deadline, DEFAULT_PER_CALL_TIMEOUT_S))` 约束（超时 ⇒ errors-as-messages，不炸循环）；② 同步 `judge` MUST 经 `asyncio.to_thread`（否则 `task.cancel()` 掐不断它、且会阻塞同进程的 `/api/health` 与其他路由）；③ SSE 的 LLMError 语义：要么让 `_run_polish` 原样抛出、要么在流层捕获 `HTTPException` —— **不允许存在"永不命中的 except"**

**Subagent Prompt Scaffold (for /dfs-exec):**
> "补三处接缝。① `polish_loop.py` 的 `dispatch`（:412）目前**无超时**：包 `asyncio.wait_for`，超时按 errors-as-messages 返回工具失败消息（不炸循环）；② 同步裁判 `judge`（:330/:439）直接跑在事件循环上 ⇒ 移 `asyncio.to_thread`，使 (a) `task.cancel()` 真能掐断、(b) 长裁判不阻塞 `/api/health` 与其他路由；用例钉住"取消时裁判线程不再被等待"/"裁判期间 health 仍可应答"（后者可用事件循环探针）。③ 修 `main.py` 的**不可达分支**：`_run_polish`（:2342-2344）已把 `LLMError` 转成 `HTTPException(502)`，而 `_polish_event_stream`（:2439-2442）写的是 `except llm_client.LLMError` ⇒ 该分支永不命中、流内 error 帧永不发出、用户拿到通用文案而非 `e.detail` 人话。断言：注入的 chat 在流中途抛 LLMError ⇒ 用户**看得到** `e.detail`（走 error 帧或明确的状态码，二选一并在注释写明为什么）。RUN：`python -m pytest tests/test_ai_polish_loop.py tests/test_server.py -q` + 全量。"

**Step Breakdown:**
- [x] Step 1: 写失败测试（RED：dispatch 无超时 / 同步裁判阻塞事件循环 / error 帧不可达）
- [x] Step 2: 跑并记录预期失败原文
- [x] Step 3: 三处实现（GREEN）
- [x] Step 4: 变异自证（抽掉 `wait_for` ⇒ 超时用例红；抽掉 `to_thread` ⇒ 阻塞探针红；把 except 改回 LLMError ⇒ error 帧用例红）
- [x] Step 5: 全量 + ruff + mypy 四档 + 原子提交

---

## 📌 登记（进 backlog，**不**塞进本计划）

> 评审发现、但属既有行为或与"抬 §4.3 门槛"无关 ⇒ 只登记，不在本计划动手。

| # | 事项 | 证据 | 为什么不现在做 |
| --- | --- | --- | --- |
| B1 | 润色入口对**用户输入**静默截断到 2000 字符，无提示、无标记 | `main.py:2465/:2481` `req.text[:2000]`；响应体无字段 | 既有行为，与裁判集无关；应配 UI 提示或 `input_truncated` 字段 |
| B2 | `truncate_evidence` 截断**不可见**、无逃生通道 | `polish_loop.py:222-237`（纯前缀裁剪、无标记、不落盘） | 与"零违规"叠加会放大假收敛；最小修法是尾部加确定性标记（"无标记 ⇒ 必未截断"），另立任务 |
| B3 | 循环级 token 闸**只累计 completion**，注入证据带来的 prompt 增长不在任何闸内 | `polish_loop.py:49-55`（自认）、`:357` | 今天有界性靠 `max_turns=3`；**若将来抬轮数 MUST 先把证据计入闸**（Fog Unknown C 的前置条件） |
| B4 | `services ⇄ tools` 双向包依赖；且 `polish_tools` 一被 import 就间接拉起白名单**明确排除**的 `tts`/`ingest`/`export` 三个模块 | `polish_tools.py:60` + `tools/__init__.py:11-27` | 属 Pi 式重构域（已暂缓）；差集守卫只挡"白名单加项"，挡不住"import 期拉起" |

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Unknown A] LLM 辅助裁判的落点**：vault `AGENT-CONDUCT §10.2` 只允许 LLM-as-Judge 判「无法形式化定义的开放语言」（如语气得体性 / Leitpunkte 的**语义**覆盖 vs 今日的关键词匹配）。具体哪些维度落到这条、以及它是否值得成本，**待 Task 6 的 FP 标定把"确定性做不到"这件事测出来再判** —— 现在拆任务就是投机。
- **[Unknown B] 官方评分维度的口径**：vault 内**没有**歌德 A1 Schreiben 官方评分表（已搜，零命中）⇒ 本计划以 ADR §4.3 点名的四项 + 实测可判性为准。若日后拿到官方评分表，维度优先级需重排（可能新增"语用/语域得体"）。
- **[Unknown C] 裁判变严对收敛率的影响**：error 级违规变多后，**官方范文仍必须 `v == 0`**（Task 2 起的硬门）；但真实用户文本的 `v` 分布会整体上移 ⇒ `max_turns=3` 是否够、`no_improvement` 是否会变成常态，须在有 Key 后回测（与 ADR §6 Unknown 2 同一笔账）。
- **[Unknown D] B1/B2 维度**：本计划只做 A1。跨等级复用（`syntax_score` 的 7 维难度 / `detect_*` 是否可参数化到 B1）不在此评估。
- **[Unknown F] Android 上 `try_load_nlp_no_download()` 到底能不能加载成功（真机未验证）**：`processor.py:192-198` 的**导入期** Android 分支显式 `nlp=None`，但新助手走的是 `_load_spacy_model()` 的**路径回退**（glob `{name}-*`，`processor.py:61-72`）—— 而 Android 的模型正是"裸源码目录拷进 Chaquopy"。⇒ **若回退命中，Android 也能拿到 `rules+spacy`（比预期更好）；若失败，则 `rules_only` + 可见提示**。② 已知副作用（评审黄卡）：该助手**不读** `_android_runtime`，失败时也不写全局 ⇒ Android 上模型缺失会**每次润色都重试本地加载**（无记忆、重复耗时）。**验证归属**：Android 真机点检（用户 2026-10-15 指示暂缓）；若届时确认恒失败，再决定是"加 `if _android_runtime: return None`"还是"加进程内失败记忆"。
- **[Unknown E] Pi 式分层重构（已拍板：日后单独做，本计划不做）**：目标形态 = ① **层间类型三态递进**（`Tool` 名片 → `AgentTool extends Tool` 工人 → `ToolDefinition` 产品组件，**只加不改**）；② **依赖单向**（消掉实测到的两组双向耦合：`core ⇄ nlp_engine`、`services ⇄ tools`）；③ **层序声明**（当前仓内**零处**声明，导致 `LAYERED-ARCHITECTURE §1` 连"违规"都无法判定）；④ 把业务知识（A1 提示词 / 默认裁判）从机制内核提到产品层。**判据来源**：`01-Rules/LAYERED-ARCHITECTURE.md`（实证对象 = Pi-Agent 的 `pi-ai`/`pi-agent-core`/`pi-coding-agent`）+ 2026-10-15 双席位评审（code-reviewer/layering + sre-resilience）。**为什么现在不做**：三态递进需先有「第二个实现」才有内容（现只有一个工具面、一个裁判）——提前定接口正是 §2 反模式；且本子计划的目标是抬 §4.3 门槛，与分层重构正交。**将来启动时的前置**：先落层序声明，再做 ①②③④（顺序见评审报告）。

## 🚫 Out of Scope

- **不引入 LLM 裁判**（D1 / vault 规则）；Fog of War Unknown A 若将来要加，也只能是 advisory。
- **不改循环内核结构**（`polish_loop.py` 的停止策略/预算/哨兵已定稿并有 25 条测试钉住）；**允许**经**注入缝 / 可选参数**改变裁判与提示词语义（Task 1 的 `judge=`、Task 7 的 `system_prompt=`）—— 这是评审三张 RED 的修复路径，也朝 `docs/agents/architecture.md` 登记的"业务知识上提"同向。
- **不做 B1/B2 评分维度**；不扩到口语/写作 Teil 1。
- **不改前端契约形状**（只可能新增一个 `judge_degraded` 布尔；不做新 UI）。
- **不动 `TOOL_REGISTRY` 与工具白名单**（Task 5 已定稿为恰好 3 项只读）。
- **❌ 不在此子计划做「Pi 式分层重构」（用户 2026-10-15 明确拍板：暂缓，日后单独重构）**。目标形态已登记在 Fog of War Unknown E：`Tool → AgentTool extends Tool → ToolDefinition` 三态递进 + 依赖单向 + 层序声明。**本子计划的一切改动 MUST NOT 依赖该重构**（RED 修复走「端点注入缝」路径，与重构正交）。
