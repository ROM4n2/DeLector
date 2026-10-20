# cards.js 状态收口（`cd-state.js`）实施计划

> **Goal**: 把 `static/js/cards.js` 的 15 个模块级可变状态收进单一 L1 状态容器 `static/js/cd-state.js`，使 `cards.js` 顶层 `let`/`var` 归零并被机械闸强制，同时视图函数、导出面、错误轨与四个 `node:vm` 探针的行为全部保持不变。
> **Tech Stack**: 原生 ES Modules（零构建）；Python 3.11 机械闸（`tools/check_frontend_layers.py`）；node:vm 行为探针（`tools/*.mjs`）
> **Spec Reference**: `docs/specs/2026-10-20-cards-state-view-decoupling-design.md`（方案 A）
> **Global Constraints**:
> - **导出面冻结**：`cards.js` 36 个具名导出 + 1 条 `export * from "./a1_cards.js"` 逐名不变；`main.js` 的 35 条具名导入零改动。
> - **零行为变更**：`cd-state.js` 的初值 MUST 逐字取自 `cards.js:29-36/429/659-666/1102-1106`；两个访问器 MUST 逐字复刻 `setCardSegment` / `stepDeck` 的写序列，**MUST NOT 顺手加固**（`stepDeck` 今天无夹取，夹取在 `renderDeckStage` 渲染期）。
> - **错误轨保真**：`notify(` / `alert(` / `console.error(` 行集合进出逐条相等。
> - **ESM 环不恶化**：`cards.js --export *--> a1_cards.js --import--> cards.js` 今天存在（靠函数提升成立）；MUST NOT 改变两模块求值顺序，MUST NOT 让 `getCachedVocabLemmas` 在模块求值期被调用。
> - **文件编码**：全仓 UTF-8 CRLF，0 lone LF。
> - **`cards.js` 不可被 node 导入**（`player.js:77` 在求值期碰 `localStorage`）⇒ 导出面只能静态判，MUST NOT 照抄 `rd-api.js` 的运行时 `Object.keys()` 判据。
> **Branch**: `refactor/cards-state-container` — 自 `master` 切出，经 PR 合入。

---

## 🧭 Decisions So Far

- **方案 A（单一状态容器）**，非 B（按簇切视图模块）：状态所有权矩阵实测显示写者极少（每状态 1~3 个），病灶是「状态无名且全局可见」，不是「状态分散」。B 的代价（4 个探针重定向 + 35 条导入重排 + 加剧既有环）全在破坏性一侧，收益未测。见设计稿 §5。
- **只两处收成访问器**（`enterSegment` / `stepDeckState`），其余状态直接字段访问：只有这两个写序列编码了真实不变量（切段复位卡组、移卡复位翻面）；再加十几个 getter/setter 是 YAGNI，且会把「谁在写」重新藏起来。
- **`renderDeckStage` 的渲染期夹取保持内联**：它依赖 `deck.length`，收进状态模块反而让它离数据更远。
- **`quizState` 零测试引用**（`grep tests/ tools/` = 0）⇒ 改名无断言代价，但其对象同一性从此没有测试守着，登记为本计划外的观察项。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: 闸立规（Gate-as-Spec，RED 先行） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `tools/check_frontend_layers.py`（`LAYER_SPEC` + `MUTABLE_STATE_MODULES`）
- Modify: `tests/test_frontend_layers.py`

**Interfaces:**
- Consumes: 既有 `LayerSpec(layer, ban_rules, allowed_imports)` / `MUTABLE_STATE_MODULES: Tuple[str, ...]`
- Produces:
  - `LAYER_SPEC["cd-state.js"] = LayerSpec(layer="L1 纯状态容器", ban_rules=("dom","network","toast","timer","dynamic-eval"), allowed_imports=())`
  - `MUTABLE_STATE_MODULES += ("cards.js",)` —— **首次**把 `cards.js` 纳入「零顶层可变状态」

**Injected Instincts:**
- [x] `[Instinct: Gate-Before-Code]`: 本任务**必须**结束于 RED。预期的红有两类，都属**声明在先**的合法红：① `cd-state.js:1:missing-layer-module`（1 处）；② `cards.js` 的 15 处 `禁mutable-state`。二者都只指向本次要动的东西，不产生连带红。
- [x] `[Instinct: No-Narrowing]`: 既有 6 个模块的 `ban_rules` / `allowed_imports` / `MUTABLE_STATE_MODULES` 成员 MUST 逐项不变（只许新增）。
- [x] `[Instinct: Fixture-Coverage]`: `tests/test_frontend_layers.py` 的最小夹具必须为**新声明的每个模块**提供占位文件，否则 `missing-layer-module` 会漏进别的规则的 `assert not rules` 里。

**Step Breakdown:**
- [ ] **Step 1**: 记基线（`python3 tools/check_frontend_layers.py` exit 0 PASS；`pytest tests/test_frontend_layers.py -q` 现数）
- [ ] **Step 2**: `LAYER_SPEC` 增 `cd-state.js`；`MUTABLE_STATE_MODULES` 增 `cards.js`
- [ ] **Step 3**: 跑闸，留 **RED 凭据**：应得 1 处 `missing-layer-module` + **15 处** `static/js/cards.js:*:L1…禁mutable-state`
- [ ] **Step 4**: 补用例：`cd-state.js` 的 L1 禁令（DOM/网络/提示/定时器/越界 import）、`cards.js` 的顶层 `let` 必红
- [ ] **Step 5**: 变异自证：往 `cards.js` 加一个 `let` ⇒ 闸红且报 `禁mutable-state`；往 `cd-state.js` 注入 `document.` ⇒ 报 `禁dom`
- [ ] **Step 6**: `ruff` / `mypy` / CRLF
- [ ] **Step 7**: 提交 `test(frontend): register cd-state.js and enforce zero top-level state in cards.js`

---

### Task 2: 建 `static/js/cd-state.js` [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `static/js/cd-state.js`
- Test: `tests/test_cards_state_split.py`（本任务只建 2 条：容器形状 + 访问器行为）

**Interfaces:**
- Produces:
  ```js
  export const cardState = { catalog, deck, quiz, prep, toast };   // 形状见设计稿 §6.1
  export function enterSegment(segment) -> void       // 三写：catalog.segment / deck.index / deck.flipped
  export function stepDeckState(delta) -> void        // 两写：deck.index += delta / deck.flipped = false
  ```

**Injected Instincts:**
- [x] `[Instinct: Verbatim-Initial]`: 15 个字段初值 MUST 逐字等于 `cards.js` 原文（`segment: "due"` / `viewMode: "deck"` / `prep.loading: null` 是「正在飞的请求」而非布尔）。
- [x] `[Instinct: No-Silent-Hardening]`: `stepDeckState` **不加夹取**。`stepDeck` 今天的边界语义是「靠按钮 `disabled` 挡 + `renderDeckStage` 渲染期纠正」。
- [x] `[Instinct: L1-Purity]`: 本文件零 DOM / 零网络 / 零提示 / 零定时器 / 零顶层 `let`。

**Step Breakdown:**
- [ ] **Step 1**: 写失败用例（RED）：断言 `cardState` 五簇字段齐全且初值等于原值；`enterSegment('prep')` 后三字段正确；`stepDeckState(1)` 只改 `index` 与 `flipped`、越界不夹
- [ ] **Step 2**: 跑用例确认失败（模块不存在）
- [ ] **Step 3**: 实现 `cd-state.js`
- [ ] **Step 4**: 闸转绿第一半：`missing-layer-module` 消失，`cards.js` 的 15 处 `禁mutable-state` **仍在**（Task 3 才消）
- [ ] **Step 5**: 用例全绿 + `node --check` + CRLF
- [ ] **Step 6**: 提交 `feat(rd): introduce cd-state.js as the single cards state container`

---

### Task 3: `cards.js` 改向（删 15 个 `let`，接入容器） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `static/js/cards.js`（仅状态相关的行，函数体只改标识符）

**Interfaces:**
- Consumes: `import { cardState, enterSegment, stepDeckState } from './cd-state.js';`
- Produces: `cards.js` 顶层 `let`/`var` **== 0**；导出面与函数结构不变

**Injected Instincts:**
- [x] `[Instinct: Rename-Only]`: 逐处 `deckIndex` → `cardState.deck.index` 等；`setCardSegment` → `enterSegment(seg)` + 保留 DOM 类切换 + `renderCardsGrid()`；`stepDeck` 的 `setTimeout` 回调内 `cardState.deck.index += direction; cardState.deck.flipped = false;`（定时器留在视图层）。
- [x] `[Instinct: Render-Clamp-Stays]`: `renderDeckStage` 的 `if (deckIndex >= deck.length) …` 改写为 `cardState.deck.index` 但**仍内联**。
- [x] `[Instinct: Error-Rail]`: 本任务 MUST NOT 触碰任何 `notify(`/`alert(`/`console.error(` 行。
- [x] `[Instinct: Link-Time]`: 改完跑 `node --check`（`.mjs` 副本），并确认与 `a1_cards.js` 的环未被改变求值顺序。

**Step Breakdown:**
- [ ] **Step 1**: 记基线（`grep -c "^let " static/js/cards.js` = 15；导出面 36 + 1 barrel；错误轨条数）
- [ ] **Step 2**: 加 import，删 15 个 `let`
- [ ] **Step 3**: 逐处改标识符（含 `setCardSegment` / `stepDeck` / `renderDeckStage` / 8 个 quiz 读者 / 5 个 prep 函数）
- [ ] **Step 4**: 闸转绿全绿：`python3 tools/check_frontend_layers.py` exit 0
- [ ] **Step 5**: `node --check`（`.mjs` 副本）exit 0；导出面 36 + barrel 不变；错误轨进出相等
- [ ] **Step 6**: 提交 `refactor(rd): move cards.js module state into cd-state.js`

---

### Task 4: 四个 `node:vm` 探针加桩 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `tools/cards_catalog_tag_probe.mjs`、`tools/cards_wb_source_probe.mjs`、`tools/cards_workbench_no_review_probe.mjs`、`tools/ia_dom_mount_probe.mjs`

**Interfaces:**
- Consumes: 各探针既有 sandbox 对象（已含 `esc` / `jsAttr` / `attachDeckSwipeListener` / `state: {}`）
- Produces: sandbox 新增 `cardState` 桩（五簇齐全，初值同 `cd-state.js`）

**Injected Instincts:**
- [x] `[Instinct: Seam-Minimal]`: 只加 `cardState` 一条桩；既有 `var deckIndex/deckFlipped` prelude 保留不删（无害），**不预防性拓宽**别的 seam。
- [x] `[Instinct: Fail-Loud]`: 桩缺失时探针 MUST 以 `ReferenceError` 响亮失败并 exit 1，MUST NOT 静默跳过。

**Step Breakdown:**
- [ ] **Step 1**: 先跑 4 个探针，记录当前失败形态（预期 `ReferenceError: cardState is not defined` 或同类）
- [ ] **Step 2**: 逐个加 `cardState` 桩
- [ ] **Step 3**: 4 个探针全绿 + 对应 pytest wrapper（`tests/test_cards_*.py` / `test_exam_domain.py` / `test_prep_matrix.py`）全绿
- [ ] **Step 4**: 变异自证：删掉其中一个桩 ⇒ 该探针必须 exit 1 且 stderr 含 `cardState`
- [ ] **Step 5**: 提交 `test(probes): stub cardState in the four node:vm cards probes`

---

### Task 5: 8 个旧状态名**断言**站点逐条处置 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

> 旧状态名共被引用 **12 处**，其中 **4 处是探针 prelude 桩**（`cards_wb_source_probe` 的 `deckIndex`/`deckFlipped`、`cards_workbench_no_review_probe` 的同名两处）已由 Task 4 一并处理。本任务只管剩下的 **8 处断言站点**。

**Files:**
- Modify: `tests/test_frontend_guards.py`（4 处）、`tests/test_audit_hardening.py`（1 处）、`tests/test_prep_matrix.py`（1 处）、`tools/ia_dom_mount_probe.mjs`（2 处：1 处功能正则 + 1 处 `problems.push` 文案）

**Interfaces:**
- Consumes: 设计稿 §9 的四类分类表
- Produces: 12 个站点全部改到新形态，**判别力不降**

**Injected Instincts:**
- [x] `[Instinct: Shape-Preserved]`: ②类 5 处（`test_frontend_guards` 4 + `test_audit_hardening` 1）只换标识符，**断言形状逐字不动**（`if (X) return` / `X = true` / `X = false` / `disabled = true` / `finally`；`X !== "prep"`）。
- [x] `[Instinct: Discrimination-Risk]`（**本计划最高优先**）: `ia_dom_mount_probe.mjs:204` 的正则 `/cardSegment\s*===?\s*['"]a1['"]/` 改名后会失配 ⇒ **真回归也绿**。MUST 改正则 **且** 补变异自证。
- [x] `[Instinct: Seam-Retarget]`: `test_prep_matrix.py:130` 的 `"_prepMatrixCache" in _CARDS` 改到两文件接缝上（`_CARDS + _CD_STATE`）。

**Step Breakdown:**
- [ ] **Step 1**: 逐站点记录改动前该断言抓的是什么事故
- [ ] **Step 2**: 改 ②类 5 处（只换名）
- [ ] **Step 3**: 改 ③类 1 处（改到接缝）
- [ ] **Step 4**: 改 ④类：`ia_dom_mount_probe.mjs` 的功能正则 + 同文件的 `problems.push` 文案，然后补变异自证
- [ ] **Step 5**: 全部相关用例绿
- [ ] **Step 6**: 提交 `test: retarget the 12 state-name assertion sites onto cardState`

---

### Task 6: 变异自证套件 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create/Modify: `tests/test_cards_state_split.py`

**Interfaces:**
- Produces: 6 条变异自证（每条断言**期望的规则名或断言名**，不接受「exit 非 0」）

**Step Breakdown（每条：注入 ⇒ 红且报出期望名 ⇒ 复原 ⇒ 绿）**
- [ ] **M1**: `cards.js` 加回顶层 `let` ⇒ 闸报 `禁mutable-state`
- [ ] **M2**: `cd-state.js` 注入 `document.` ⇒ 闸报 `禁dom`
- [ ] **M3**: `cd-state.js` 注入 `import { esc } from './core.js'` ⇒ 报 `越界import`
- [ ] **M4**: `enterSegment` 删掉 `deck.flipped = false` ⇒ 用例红（否则该不变量无人守）
- [ ] **M5**: `stepDeckState` 加上夹取 ⇒ 用例红（守住「逐字复刻」）
- [ ] **M6**: 删掉 `ia_dom_mount_probe` 的 `cardState` 桩 ⇒ 探针 exit 1 且 stderr 含 `cardState`
- [ ] **提交** `test(rd): add mutation proofs for the cards state container`

---

### Task 7: 门禁全景复核与 PR [Tier: 1-Light] [Mode: AFK] [Role: Cleaner]

**Step Breakdown:**
- [ ] **Step 1**: 六道 Python 机械闸全 exit 0
- [ ] **Step 2**: `ruff check .` / `mypy --strict delector tools` / `mypy --follow-imports=skip tests`
- [ ] **Step 3**: Go 8 包 + `gofmt -l .`
- [ ] **Step 4**: 全量 pytest **单条串行分批**（153+ 文件）
- [ ] **Step 5**: CRLF 卫生（全部改动文件 0 lone LF）
- [ ] **Step 6**: `WORKMEMORY/work.log` DONE 事件（≤4KB）
- [ ] **Step 7**: 推分支 + 建 PR，并逐步骤确认 CI 真跑了新断言

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Unknown 1: 方案 B 的真实收益]**：A 落地后按实测（单文件行数、探针锚点密度、`main.js` 导入面）再判是否按簇切视图模块。MUST NOT 在 A 之前预先论证。
- **[Unknown 2: `cards ↔ a1_cards` 的 ESM 环]**：今天真实存在，靠函数声明提升成立，前端 `reverse-dependency` 闸不覆盖 `cards.js`（不在 `LAYER_SPEC`）。是否根治、怎么根治（把 `getCachedVocabLemmas` 下沉到更低的模块？把 barrel 换成显式再导出？）须单独立项。本计划只要求**不恶化**。
- **[Unknown 3: `cardState.quiz` 的对象同一性无测试守着]**：8 个函数共享同一引用是硬约束，但 `grep tests/ tools/` 对 `quizState` 零命中。要不要补一条「同一性」钉子（例如断言 `openQuizOverlay` 与 `finishQuiz` 拿到同一对象）待定 —— 补的话它属于新增断言，需说明判别力来源。

---

## 🚫 Out of Scope

- **不切视图模块**（方案 B，见 Unknown 1）。
- **不抽持久化层**：`cards.js` 有 13 处 `await api(`，对标 `wr-api`/`rd-api` 的抽离是**第三个**独立问题。
- **不动 `export * from "./a1_cards.js"`** barrel（`main.js` 经它转发 A1 契约）。
- **不动 `a1_cards.js` / `static/german/**` / 后端任何文件**。
- **不做 `cards.js` 的 API 调用面改动**；不改任何端点或请求形状。
- **不新增业务断言**；新增测试只允许出现在 `tests/test_frontend_layers.py` 与 `tests/test_cards_state_split.py`。

---

## ✅ 执行凭据

### Task 1（+1b）闸立规 · commit `c290fed` + `482ca2f`

**RED（计划预期）**：`exit 1 · 16 处违规` = 1 × `cd-state.js:1:missing-layer-module` + **15** × `cards.js:<line>:零顶层可变状态契约禁mutable-state`，无第三类。15 行号 = `29,30,31,32,33,34,35,36,429,659,1102,1103,1104,1105,1106`（独立词法器复算集合相等；12 个嵌套 `let` 未被误报）。

**实施中发现计划未预见的结构问题（已证必要）**：`check_layer_bans` 的顶层 `let` 扫描原本**嵌在 `LAYER_SPEC` 循环内**，因此「把 `cards.js` 加进 `MUTABLE_STATE_MODULES`」**产生零违规**。故提取 `top_level_mutable_tokens()` 并新增「仅受可变状态约束」的独立遍历（规则 ⑦）。两条反事实证明：
- 把 `cards.js` 放进 `LAYER_SPEC` ⇒ **231 处违规**（152 dom / 40 network / 15 toast / 5 timer / 15 mutable / 4 越界 import），216 处连带红 ⇒ 留在外面是正确判断；
- 去掉新遍历 ⇒ `cards.js` 违规归 **0** ⇒ 重构是达成计划自身判据的必要条件。

**独立评审 PASS**：12 例等价性对照（内联 vs 提取实现）全部同计数/同行号/同规则串；既有两个模块的违规顺序不变；`top_level_mutable_tokens` 置空会同时静默 ③ 与 ⑦（单一真相源）；测试 diff **零条非头部删行**。

**评审驱动的三条收口（`482ca2f`）**：
1. `③b` 一名两义（import 白名单 vs 可变状态）⇒ 新遍历改编号 **⑦**，import 侧 ③b 不动；
2. `MUTABLE_STATE_ONLY_LAYER` 原为 `"L1 零顶层可变状态契约"`，把**视图模块** `cards.js` 标成 L1 ⇒ 改为 `"零顶层可变状态契约"`（无层声明），并加断言钉住「不得以 L1/L2 开头」；
3. **静默失效**：MSM-only 模块缺失时原为 `if not path.exists(): continue` ⇒ 若 `cards.js` 改名，15 处钉子**无声消失**。改为报 `missing-mutable-state-module`；两个最小夹具补 `cards.js` 占位（移除占位会令 4 条**无关**用例因规则泄漏而红，已实测）。

**编排者独立复验**：真实树 `1 + 15`；旧标签全仓 0 残留；临时改名 `cards.js` ⇒ 闸报 `missing-mutable-state-module:只受零顶层可变状态契约约束的模块不存在：cards.js`（2 处：该条 + 已知的 `cd-state.js`）；复原后回到 15；`pytest tests/test_frontend_layers.py` = **1 failed（仅 `test_gate_script_exits_zero_on_real_tree`，计划内已知红）/ 97 passed**。

### Task 2（+2b）建 `cd-state.js` · commit `ee58daf` + `67d75d3`

**闸分解**：`1 + 15` → **`0 + 15`**（`cd-state.js` 零违规、`missing-layer-module` 消失；`cards.js` 的 15 处原样留给 Task 3）。

**独立评审 PASS，且初值是机械证明的**：评审写了 `node compare_init.mjs` —— 程序化提取 `cards.js` 全部顶层 `let`、求值字面量、与容器做**类型严格**深比较：

```
cards.js top-level `let` count = 15
lets NOT mapped to container: []   → 1:1，没漏没造
VERDICT: all 15 initial values type-identical
```

类型敏感已实测：`flipped→0`、`loading→false`、`undoTimer→0`、`due_count→"0"`、`quiz.mode→false` 各自都会红。**「15 字段 vs 24 叶子」确认是纯嵌套**（3 个对象值的 `let` 展开 12 个叶子），无凭空字段。

**评审用变异证明的两个测试洞（已由 Task 2b 补，并被我独立复验）**：

| 洞 | 证明 | 补法 |
| --- | --- | --- |
| **A 守卫不对称** | 给 `stepDeckState` 加第三个写 `deck.lastFlipTime = Date.now()` ⇒ **5 条全绿** | 新增 `test_step_deck_state_changes_exactly_two_fields`，断言改动路径集**恰为** `{deck.index, deck.flipped}` |
| **B 脏集不全** | `enterSegment` 的「先弄脏」只覆盖 13/24 叶子 ⇒ 写回**初值**（`prep.searchQuery = ""` / `quiz.correct = 0`）**全绿** | 脏化改为递归遍历**全部 24 叶子**并注入可区分哨兵，且断言叶子集 == 期望集、无重复无遗漏 |

**编排者独立复验（不采信汇报）**：三个变异各自**只红对应那一条**，control 复原后 `6 passed`：

```
a. stepDeckState +3rd write          exit=1 red=['test_step_deck_state_changes_exactly_two_fields']
b. enterSegment 写回初值 searchQuery    exit=1 red=['test_enter_segment_writes_exactly_three_fields']
c. enterSegment 写回初值 quiz.correct   exit=1 red=['test_enter_segment_writes_exactly_three_fields']
control                             6 passed
```

**这条形态值得记**：变更检测若靠「先把其余字段弄脏」，脏集**必须是全集** —— 否则「写回初值」这个动作天然隐形。这不是实现 bug，是守卫强度问题，而它只在被变异打中时才暴露。
