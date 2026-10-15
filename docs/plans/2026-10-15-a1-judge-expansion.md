# A1 裁判集扩充（ADR-0023 第 ④ 步）实施计划

> **Goal**: 把 `ai-polish` 循环的裁判从「6 条书信格式/字数浅规则」扩到 **A1 真实评分维度的语法层**，从而抬掉 ADR-0023 §4.3 的「裁判集未扩到位之前不得宣称已实现」门槛；同时把循环的真实迭代价值面从「仅 A1 书信体」扩到**任意德语文本**。
> **Tech Stack**: Python 3.11 / spaCy 3.8.16 + `de_core_news_sm` / pytest（本仓无 pytest-asyncio）
> **Spec Reference**: ADR-0023（vault `08-Projects/DeLector/01-ADR/0023-…md`，`accepted`，§8 为定稿口径）—— **本子计划 = §8.5 施行顺序的第 ④ 步**；前序计划 `docs/plans/2026-10-14-interactive-agent-loop.md`（Task 0~6 已合入 master，PR #136）
> **Global Constraints**:
> - **禁止 LLM 裁判**：vault `01-Rules/AGENT-CONDUCT.md:249` 的三层校验明确 LLM-as-a-Judge **只用于无法形式化定义的开放语言**、**严禁参与物理真值判断**。语法维度是可形式化的 ⇒ MUST 确定性规则。LLM 辅助若将来要加，只能落在 advisory（`level=warning`）且不得阻止收敛（见 Fog of War）。
> - **误报（FP）是一等公民**：每条新规则 MUST 同时具备①正样本零误报 ②负样本能报 ③边界不报 三条用例；**官方 `A1_SCHREIBEN_TEIL2` 的 10 篇 `sample_email` 在扩后裁判下 `violations == 0` 是硬门**（连官方范文都报错 ⇒ 规则过严 ⇒ 循环永不可能收敛）。
> - **静默降级 = 静默假收敛（红线 1）**：`analyze_a1_email` 现为**纯规则、不依赖 spaCy**。接入语法维度后，若运行时无 spaCy ⇒ 语法违规会**静默消失**，裁判会判出「零违规」。故裁判输出 MUST 带引擎标记（如 `judge_engine` / `degraded`），且**端点 MISS 把降级状态带到返回体**（不得让"没检查"看起来像"检查通过"）。
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
- Modify: `delector/routes/main.py`（`_a1_violations_if_letter` 改走统一抽取器；返回体透出引擎标记）
- Test: `tests/test_writing_rules.py`（追加）+ `tests/test_ai_polish_loop.py`（不动既有）

**Interfaces:**
- Consumes: `analyze_a1_email(text, leitpunkte) -> dict`（既有）；`detect_determiner_noun_agreement` / `detect_preposition_case` 的 span 形状 `{severity, error_type, corrected_form, explanation_zh, start, end}`
- Produces: `def collect_violations(analysis: dict[str, Any]) -> list[dict[str, Any]]` —— 统一形状 `{"rule": str, "level": "error"|"warning", "message": str, "span": tuple[int, int] | None}`；**新键优先、旧键回退**（`violations` → legacy `suggestions` 的 `level=="error"` 过滤）
- Produces: `analyze_a1_email` 追加并列字段 `violations: list[dict]` 与 `judge_engine: str`（`"rules+spacy"` / `"rules_only"`），**既有键逐字不动**
- Produces（端点侧）: `_PolishOutcome` 追加 `judge_engine: str`；响应体 `result` 追加 `judge_degraded: bool`（**只增不改**）

> ⚠️ 本任务只立形状与降级标记，**不加任何新规则**（接线在 Task 2+）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "统一 A1 裁判的违规形状并加引擎降级标记。现状：`analyze_a1_email` 出 `{suggestions:[{rule,level,message}]}`（纯规则），而 `detect_*` 出 `{severity,error_type,corrected_form,explanation_zh,start,end}`（spaCy span）—— 两套形状让端点层 `_a1_violations_if_letter` 只能认一套。① 在 `delector/services/writing.py` 加 `collect_violations(analysis)`：统一形状 `{rule,level,message,span}`，**新键 `violations` 优先、legacy `suggestions` 回退**，`level` 只认 `error`（warning 不阻止收敛 —— 这是 Task 4/5/6 已钉死的语义）；② `analyze_a1_email` **追加**并列字段 `violations` 与 `judge_engine`（`rules+spacy` / `rules_only`），既有键与既有断言逐字不动；③ 端点 `_a1_violations_if_letter` 改用 `collect_violations`，`_PolishOutcome`/响应体加 `judge_engine`/`judge_degraded`（只增不改，前端文案表不动）。TDD：先在 `tests/test_writing_rules.py` 写 RED（统一形状 + 回退 + level 过滤），再实现。RUN：`python -m pytest tests/test_writing_rules.py tests/test_goethe_a1_writing.py tests/test_ai_polish_loop.py tests/test_server.py -q`（既有断言只许新增不许放宽）。"

**Step Breakdown:**
- [ ] Step 1: 写失败测试（RED：统一形状 / legacy 回退 / `level=warning` 不入违规）
- [ ] Step 2: 跑并记录预期失败原文
- [ ] Step 3: 实现 `collect_violations` + `violations`/`judge_engine` 并列字段 + 端点透出（GREEN）
- [ ] Step 4: 变异自证（把回退分支删掉 ⇒ 相关用例红；把 `level` 过滤删掉 ⇒ warning 入违规 ⇒ 红）
- [ ] Step 5: 关联套件 + `ruff` + mypy 四档 + 原子提交

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
- [ ] Step 1: 写失败测试（RED：负样本两例报违规 + 官方 10 篇零违规门）
- [ ] Step 2: 跑并记录预期失败原文（**红色是"报 0"，不是"报错"**）
- [ ] Step 3: 实现接线（GREEN）
- [ ] Step 4: 变异自证（关掉一致性检查 ⇒ 负样本用例红；把双格介词豁免删掉 ⇒ 官方范文门红）
- [ ] Step 5: 关联套件 + ruff + mypy 四档 + 原子提交

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
- [ ] Step 1: 写失败测试（RED：负样本报 1 条 + 4 条 FP 守卫各不报）
- [ ] Step 2: 跑并记录预期失败原文
- [ ] Step 3: 实现（GREEN）
- [ ] Step 4: 变异自证（抽掉 FP 守卫 ⇒ 对应用例红）
- [ ] Step 5: 官方范文零违规门仍绿 + 原子提交

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
- [ ] Step 1: 写失败测试（RED：负样本报 1 条 + 正样本 0 条 + 数据自检 + FP 守卫）
- [ ] Step 2: 跑并记录预期失败原文
- [ ] Step 3: 数据 + 规则实现（GREEN）
- [ ] Step 4: 变异自证 + 官方范文零违规门复核
- [ ] Step 5: 原子提交

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
- [ ] Step 1: 写失败测试（RED：错句报 1 条 + 正句 0 条 + 6 条豁免各 0 条）
- [ ] Step 2: 跑并记录预期失败原文
- [ ] Step 3: 实现（GREEN）
- [ ] Step 4: 变异自证（抽掉任一条豁免 ⇒ 对应用例红）+ 官方范文零违规门复核
- [ ] Step 5: 原子提交

---

### Task 6: 语序（情态框架）与时态一致性的 **FP 标定实验**（决定做/不做/降级） [Tier: 3-Critical] [Mode: HITL] [Role: TDD Builder]

**Files:**
- Create: `tools/bench_judge_fp.py`（可复跑标定脚本，输入 = 正样本集 + 负样本集，输出 = 每条候选规则的 FP/FN 计数与样例行）
- Test: `tests/test_judge_fp_bench.py`（脚本自身的行为契约：喂已知样本 ⇒ 已知计数）

**Interfaces:**
- Consumes: `A1_SCHREIBEN_TEIL2`（10 篇官方范文，正样本）· 自建负样本集（每维 ≥5 句手工构造的定向错误句）· 候选规则（本任务**只写探测实现，不接线**）
- Produces: `python tools/bench_judge_fp.py` 的**原始输出**（每维 FP 率 / FN 率 / 误报样例逐条列出）+ 一份结论：每维 ∈ {**接线为 error** | **接线为 warning(advisory)** | **不做**}，附判据与阈值

> **为什么这维度必须是 HITL + Tier 3**：探针已实测 spaCy 对 `Ich muss gehen heute nach Hause.` 的**框架解析失败**（`muss` 判 `nk`、`gehen` 判 `ROOT`）⇒ 直接接线会**误报**，而误报比漏报危险（模型会去"修"一个不存在的错误 = 奖励黑客的反面）。做/不做是**产品语义决定**，必须人拍板。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "做一次可复跑的 FP 标定实验，**不接线**。① 建 `tools/bench_judge_fp.py`：对两条候选维度（情态动词框架语序 / 时间副词与时态一致性）各写一版**探测实现**（可住在脚本里，不必进 `writing.py`），在 a) 官方 10 篇 `sample_email`（正样本，期望 FP=0）与 b) 每维 ≥5 句手工定向错误句（负样本，期望能报）上逐句跑，输出原始计数表 + 误报样例全文。② 建 `tests/test_judge_fp_bench.py` 钉脚本自身行为（给固定样本 ⇒ 固定计数；不许"跑得过但数不清"）。③ 产出**带阈值的结论建议**（例如：FP 率 ≤ 某值 ⇒ 可做 error；否则 warning 或不做的理由），并**把误报样例原文带回**（不许只报比例 —— 比例无法证伪判据）。RUN：`python tools/bench_judge_fp.py` 与 `python -m pytest tests/test_judge_fp_bench.py -q`，原始输出全带回。⚠️ 若某维在正样本上就误报 ⇒ **如实结论是"不做"**，不许调样本让它好看。"

**Step Breakdown:**
- [ ] Step 1: 建正/负样本集（负样本每维 ≥5 句，逐句标注期望）
- [ ] Step 2: 写探测实现 + 脚本（含脚本自身测试）
- [ ] Step 3: 跑出原始计数表与误报样例
- [ ] Step 4: **HITL**：把结论（做 error / warning / 不做）交用户拍板
- [ ] Step 5: 按拍板结论决定是否接线（若接线 ⇒ 走 Task 2~5 同款门禁：正样本零违规 + FP 守卫 + 变异自证）+ 原子提交

---

### Task 7: 适用性闸门收窄（循环价值面扩到任意德语文本）+ §4.3 门槛解除判据 [Tier: 2-Standard] [Mode: HITL] [Role: TDD Builder]

**Files:**
- Modify: `delector/routes/main.py`（`_a1_violations_if_letter` 的闸门范围）
- Modify: `docs/plans/2026-10-15-a1-judge-expansion.md`（本文件：记录解除判据与实测值）
- Test: `tests/test_goethe_a1_writing.py`

**要解决的现状（实测）**：`_a1_violations_if_letter` 目前「称呼语不合法 ⇒ 零违规」，因为当时的裁判**只有书信格式规则**。扩了语法维度后，前提变了：**语法违规与题材无关** ⇒ 语法维度对任何德语文本都该生效，只有书信格式/字数规则保留"仅书信体"闸门。这一步把循环的真实迭代价值面从「仅 A1 书信体」扩到「任意德语文本」。

**Interfaces:**
- Consumes: `collect_violations(...)`（Task 1）· 各维度规则
- Produces: 闸门按**规则族**分流（格式族：仅书信体；语法族：任何文本）+ `docs/plans` 里的**§4.3 解除判据表**（每条判据 + 实测值 + 是否满足）

**Subagent Prompt Scaffold (for /dfs-exec):**
> "收窄适用性闸门的范围。现状：`_a1_violations_if_letter` 因当时裁判只有书信格式规则而做成「称呼语不合法 ⇒ 零违规」；语法维度接线后**前提变了** —— 语法与题材无关。改法：闸门改按**规则族**分流 —— ① 格式/字数族（`a1_greeting_*` / `a1_valediction_*` / `a1_word_count`）仍仅对书信体生效；② 语法族（冠词-格一致 / 介词支配格 / 动词支配格 / 主谓一致 / V2）对**任意德语文本**生效。测试 MUST 覆盖：非书信体文本带语法错误 ⇒ **真被计数**（与今日"零违规"对比，这是行为变更）；书信体文本的格式规则语义不变。③ 同时在本计划文件里落一张 **§4.3 解除判据表**（维度数 / 官方正样本零误报 / 负样本 recall / 非书信文本可判 / 降级标记可见性 各条 + 实测值），**满足与否由用户拍板**，agent 不自行解禁。RUN：`python -m pytest tests/test_goethe_a1_writing.py tests/test_server.py tests/test_ai_polish_loop.py -q` + 全量。⚠️ 本任务会改变产品行为（非书信文本从"首轮即接受"变为"真迭代"），执行前 MUST 先跑一遍 `tests/test_server.py::test_ai_polish_diff_mocked` 系用例确认既有断言仍成立。"

**Step Breakdown:**
- [ ] Step 1: 写失败测试（RED：非书信体带语法错误 ⇒ 被计数）
- [ ] Step 2: 跑并记录预期失败原文
- [ ] Step 3: 闸门按规则族分流（GREEN）
- [ ] Step 4: 全量套件 + 契约闸 + §4.3 解除判据表落盘
- [ ] Step 5: **HITL**：判据表交用户拍板（是否允许宣称"已实现"）+ 原子提交

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Unknown A] LLM 辅助裁判的落点**：vault `AGENT-CONDUCT §10.2` 只允许 LLM-as-Judge 判「无法形式化定义的开放语言」（如语气得体性 / Leitpunkte 的**语义**覆盖 vs 今日的关键词匹配）。具体哪些维度落到这条、以及它是否值得成本，**待 Task 6 的 FP 标定把"确定性做不到"这件事测出来再判** —— 现在拆任务就是投机。
- **[Unknown B] 官方评分维度的口径**：vault 内**没有**歌德 A1 Schreiben 官方评分表（已搜，零命中）⇒ 本计划以 ADR §4.3 点名的四项 + 实测可判性为准。若日后拿到官方评分表，维度优先级需重排（可能新增"语用/语域得体"）。
- **[Unknown C] 裁判变严对收敛率的影响**：error 级违规变多后，**官方范文仍必须 `v == 0`**（Task 2 起的硬门）；但真实用户文本的 `v` 分布会整体上移 ⇒ `max_turns=3` 是否够、`no_improvement` 是否会变成常态，须在有 Key 后回测（与 ADR §6 Unknown 2 同一笔账）。
- **[Unknown D] B1/B2 维度**：本计划只做 A1。跨等级复用（`syntax_score` 的 7 维难度 / `detect_*` 是否可参数化到 B1）不在此评估。
- **[Unknown E] Pi 式分层重构（已拍板：日后单独做，本计划不做）**：目标形态 = ① **层间类型三态递进**（`Tool` 名片 → `AgentTool extends Tool` 工人 → `ToolDefinition` 产品组件，**只加不改**）；② **依赖单向**（消掉实测到的两组双向耦合：`core ⇄ nlp_engine`、`services ⇄ tools`）；③ **层序声明**（当前仓内**零处**声明，导致 `LAYERED-ARCHITECTURE §1` 连"违规"都无法判定）；④ 把业务知识（A1 提示词 / 默认裁判）从机制内核提到产品层。**判据来源**：`01-Rules/LAYERED-ARCHITECTURE.md`（实证对象 = Pi-Agent 的 `pi-ai`/`pi-agent-core`/`pi-coding-agent`）+ 2026-10-15 双席位评审（code-reviewer/layering + sre-resilience）。**为什么现在不做**：三态递进需先有「第二个实现」才有内容（现只有一个工具面、一个裁判）——提前定接口正是 §2 反模式；且本子计划的目标是抬 §4.3 门槛，与分层重构正交。**将来启动时的前置**：先落层序声明，再做 ①②③④（顺序见评审报告）。

## 🚫 Out of Scope

- **不引入 LLM 裁判**（D1 / vault 规则）；Fog of War Unknown A 若将来要加，也只能是 advisory。
- **不改循环内核**（`polish_loop.py` 的停止策略/预算/哨兵已定稿并有 25 条测试钉住）。
- **不做 B1/B2 评分维度**；不扩到口语/写作 Teil 1。
- **不改前端契约形状**（只可能新增一个 `judge_degraded` 布尔；不做新 UI）。
- **不动 `TOOL_REGISTRY` 与工具白名单**（Task 5 已定稿为恰好 3 项只读）。
- **❌ 不在此子计划做「Pi 式分层重构」（用户 2026-10-15 明确拍板：暂缓，日后单独重构）**。目标形态已登记在 Fog of War Unknown E：`Tool → AgentTool extends Tool → ToolDefinition` 三态递进 + 依赖单向 + 层序声明。**本子计划的一切改动 MUST NOT 依赖该重构**（RED 修复走「端点注入缝」路径，与重构正交）。
