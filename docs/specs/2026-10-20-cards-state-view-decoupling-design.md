# cards.js 状态与视图解耦 · 设计稿

> **性质**：设计稿（`docs/specs/`），不是实施计划。落地时要另立 `docs/plans/` 计划。
> **上游**：`docs/plans/archive/2026-10-19-reader-js-layer-split.md` 的 Fog of War Unknown 1
> （原话：cards.js「要回答的是**状态与视图怎么分**…与 writer.js/reader.js 的『抽纯簇』是两个不同的设计问题 ⇒ MUST 另立计划」）。
> **前三个样本**：`wr-format`/`wr-api`（PR #160）、`rd-syntax`（PR #161）、`rd-api`（PR #164）。
> **基线**：master `5f887ae`。

---

## 0. 结论先行

**推荐方案 A：把 15 个模块级 `let` 收进单一状态容器模块 `static/js/cd-state.js`，视图函数原地不动。**

理由：`cards.js` 的病灶**不是「状态散落在很多函数里」**，而是「状态是模块全局的、无名的」。实测所有权矩阵显示写者极少（每个状态 1~3 个函数），真正的问题是 42 个顶层函数**谁都能读写、没有编译期约束、探针必须按名字打桩**。把状态收进一个文件后：写入面变成一份可读清单；机械闸可以首次对 `cards.js` 强制「零顶层 `let`」；而**不搬任何函数**意味着四个 `node:vm` 探针的函数切片全部继续有效。

**明确不推荐**「按簇切 5 个视图模块」——那是**第二跳**，收益未测，风险高（见 §5）。

> **本稿 §9 的三条未决项已在成稿前实测收敛**（旧状态名仅 12 处；`quizState` 零测试引用；`stepDeck` 无夹取）。其中一条**推翻了我初稿里的访问器设计** —— 详见 §6.1 的警告块。设计稿里写错的接口比写漏的更危险：它会被照着实现。

---

## 1. 实测基线

| 指标 | 值 | 重算方式 |
| --- | --- | --- |
| 行数 | **1335** | `wc -l static/js/cards.js` |
| 顶层函数 | **42** | 见下方 token 脚本 |
| 顶层 `let`/`var` | **15** | 同上 |
| 具名导出 | **36** + `export * from './a1_cards.js'` | §2 双口径 |
| 消费者 | `main.js` 35 个具名；`a1_cards.js` 1 个；`cloze.js` 1 个 | `grep "from \"./cards.js\""` |
| 触碰 cards.js 的测试/探针文件 | **17** | §4 |
| 其中 `node:vm` 真跑探针 | **4** | §4 |
| 触碰模块状态的顶层函数 | **25 / 42** | §2 矩阵 |

> 全部由 token 流测量（`tools/check_frontend_layers.py::read_js`），非正则猜名 —— 本仓此前三次栽在「手挑清单」与「按命中行分类」。

---

## 2. 状态所有权矩阵

15 个模块级可变状态，按**谁写它们**分成 5 个簇：

### 簇 1 · 卡册浏览（catalog）

| 状态 | 初值/用途 | 写者 | 读者 |
| --- | --- | --- | --- |
| `cardSegment` | 当前段（vocab/grammar/…） | `setCardSegment` | `getCardViewMode`、`renderCardsGrid` |
| `cardViewMode` | 列表/卡片视图 | `setCardViewMode` | `getCardViewMode`、`renderCardsGrid` |
| `cachedCards` | 卡缓存 | `loadCards` | `getCachedVocabLemmas`、`renderCardsGrid` |
| `cachedDueCards` | 待复习缓存 | `loadCards`、`refreshDueCount` | `renderCardsGrid` |

### 簇 2 · 翻牌卡组（deck）

| 状态 | 用途 | 写者 | 读者 |
| --- | --- | --- | --- |
| `deckIndex` | 当前卡位 | `setCardSegment`、`renderDeckStage`、`stepDeck` | （仅作下标/比较） |
| `deckFlipped` | 是否已翻面 | `setCardSegment`、`toggleDeckFlip`、`stepDeck` | `renderDeckStage`、`attachDeckSwipeListener` |
| `_lastFlipTime` | 防抖时间戳 | `toggleDeckFlip` | — |
| `_reviewInFlight` | 评分重入闸 | `submitCardReview` | — |

### 簇 3 · 测验（quiz）

| 状态 | 用途 | 写者 | 读者 |
| --- | --- | --- | --- |
| `quizState` | **单个对象，从不重新绑定**，字段就地改 | （`quizState.x = …`，非重绑定） | `startQuiz`、`renderCurrentQuizCard`、`flipFlashcard`、`submitFlashcard`、`checkDictation`、`advanceQuiz`、`submitChoice`、`finishQuiz`（**8 个**） |

### 簇 4 · 介词矩阵（prep）

| 状态 | 写者 | 读者 |
| --- | --- | --- |
| `_prepMatrixCache` | `loadPrepMatrix` | `renderPrepMatrix` |
| `_prepLoading` | `loadPrepMatrix` | — |
| `_prepCaseFilter` | `filterPrepCase` | `renderPrepMatrix` |
| `_prepSearchQuery` | `searchPrepCollocations` | `renderPrepMatrix` |
| `_prepSearchTimer` | `searchPrepCollocations` | — |

### 簇 5 · 瞬时 UI（toast）

| 状态 | 写者 | 读者 |
| --- | --- | --- |
| `undoToastTimer` | `showUndoToast` | — |

**从矩阵读出的三条真实不变量**（今天只存在于代码顺序里，没有任何东西守着）：

1. **切段必须重置卡组**：`setCardSegment` 同时写 `cardSegment` / `deckIndex` / `deckFlipped` 三者。任何人改它时漏一个，就会出现「换段后停在上一次的卡位、且显示已翻面」。
2. **移动卡位必须复位翻面**：`stepDeck` 同写 `deckIndex` + `deckFlipped`。
3. **`quizState` 是就地可变对象**，8 个函数共享同一引用；任何「替换成新对象」的写法都会让别处的闭包读到旧对象。

---

## 3. 导出面与依赖形状

- **36 个具名导出** + 1 条 `export * from "./a1_cards.js"`（把 10 个 A1 函数做成 barrel 再导出）。
- 消费方：`main.js`（35 具名）、`a1_cards.js`（`getCachedVocabLemmas`）、`cloze.js`（`showUndoToast`）。

### ⚠️ 已存在的 ESM 环（本次设计必须不恶化）

```
cards.js   -- export * from -->  a1_cards.js
a1_cards.js -- import { getCachedVocabLemmas } -->  cards.js
```

这是**今天就在跑的环**，靠「函数声明提升 + 调用发生在运行时而非模块求值期」侥幸成立。前端的 `reverse-dependency` 闸只覆盖 `LAYER_SPEC` 里的模块，`cards.js` 不在其中，所以没有任何东西拦它。

**设计要求**：本次改动 MUST NOT 改变这两个模块的求值顺序，MUST NOT 让 `getCachedVocabLemmas` 在模块求值期被调用。是否根治此环 **另立事项**（见 §7）。

---

## 4. 约束面：17 个文件的探针盘点

按 `monolith-split-readiness` 的失败模式分类（这决定「什么能搬」）：

| 类 | 文件 | 钉住的东西 | 状态搬家后是否破 |
| --- | --- | --- | --- |
| **A 类（切函数体真跑）** | `tools/cards_catalog_tag_probe.mjs` | `isWorkbenchSourced` / `cardStatsTag` / `renderCatalogGrid` | 函数不动 ⇒ **不破** |
| | `tools/cards_wb_source_probe.mjs` | `isWorkbenchSourced` / `cardStatsTag` / `renderDeckStage` | 同上 |
| | `tools/cards_workbench_no_review_probe.mjs` | `cardStatsTag` / `renderDeckStage` / `isWorkbenchSourced` | 同上 |
| | `tools/ia_dom_mount_probe.mjs` | `setCardSegment` / `renderCardsGrid` 切片 + 内容扫描 | 同上 |
| **B 类（整份源码做内容断言）** | `tests/test_audit_hardening.py`(5) / `test_frontend_guards.py` / `test_frontend_security.py` / `test_prep_matrix.py` / `test_exam_domain.py`(1) / `test_goethe_a1.py` / `test_server_backup_restore.py`(3) / `test_german_workbench.py` | 具体字符串：`/api/prep/matrix`、`BACKUP_LS_EXCLUDE`、`setExamVocabLevel`、alert→notify 文案、XSS sink 形态 | **部分会破**：状态名若改（`deckIndex`→`cardState.deckIndex`），任何按旧名做内容断言的站点都会红 |
| **C 类（无关）** | `test_frontend_layers.py` / `test_frontend_module_graph.py` / `test_server.py` | 只把 `'./cards.js'` 当任意 import 目标 / 只查存在性 | **不破** |

### 4b. 四个 vm 探针的共同前置

四个探针都是「剥 import/export → 整份源码进 `node:vm` 真跑」，沙箱里有：

```js
// ↓ cards.js 的模块级环境
esc, jsAttr, attachDeckSwipeListener, state: {},
vm.runInContext("var deckIndex = 0; var deckFlipped = false;", ctx)   // prelude
```

**关键约束**：状态搬进 `cd-state.js` 后，被剥掉 import 的源码里 `cardState` 会变成自由标识符 ⇒ 四个探针 MUST 各加一条沙箱桩（与 `rd-api` 那次给 `cards_count_probe` 补 `fetchCardCounts` 同形），否则 `ReferenceError`。

### 4c. cards.js 无法被 node 直接导入

```
ReferenceError: localStorage is not defined
    at static/js/player.js:77:10
```

`cards.js → player.js` 在模块求值期就碰 `localStorage` ⇒ **`rd-api.js` 那套「问引擎要导出面」的运行时判据不适用于 cards.js**。cards.js 的导出面只能静态判 + 用 vm 探针做行为级旁证。这是本设计里一条硬边界，必须写进后续计划，避免有人照抄 `rd-api` 的做法然后在 CI 上炸。

---

## 5. 候选方案与权衡

| 方案 | 形态 | 优点 | 代价 | 判定 |
| --- | --- | --- | --- | --- |
| **A（推荐）** | 单一 `cd-state.js` 持有 15 个状态，`cards.js` 改为 `import { cardState } from './cd-state.js'`；函数原地不动 | 写入面成清单；可首次对 `cards.js` 强制零顶层 `let`；函数不搬 ⇒ 4 个 A 类探针零损伤 | 四个 vm 探针各加一条桩；B 类内容断言需逐个核（状态名变化） | **做** |
| B | 按 5 簇切 5 个视图模块（catalog/deck/quiz/prep/toast） | 单文件更小 | 4 个 A 类探针的函数切片**全部要重定向**；35 个 main.js 导入面重排；环风险上升 | **不做**（第二跳） |
| C | 状态留在 cards.js，只加访问器函数 | 零探针改动 | 15 个 `let` 仍全局可见，闸无法立规 ⇒ 只是风格改善 | **不做** |
| D | 状态机 / reducer | 可测状态迁移 | 视图层无时间旅行需求，YAGNI | **不做** |

**为什么不是 B**：B 的收益（单文件更小）不是当前痛点 —— 痛点是「状态无主」。而 B 的代价（4 个探针重定向 + 35 条导入重排 + 加剧已有环）全部落在**破坏性**一侧。先做 A，把状态收口与闸立规拿到手；B 是否值得，等 A 落地后按实测再判。

---

## 6. 方案 A 的形态

### 6.1 `static/js/cd-state.js`（约 120 行）

```js
/* DeLector - Cards 状态容器（L1 纯层：零 DOM / 零网络 / 零提示 / 零定时器） */
'use strict';

export const cardState = {
  // 簇 1 卡册浏览
  catalog: { segment: 'vocab', viewMode: 'grid', cards: null, dueCards: null },
  // 簇 2 翻牌卡组
  deck: { index: 0, flipped: false, lastFlipTime: 0, reviewInFlight: false },
  // 簇 3 测验（对象就地可变，与现状一致）
  quiz: null,
  // 簇 4 介词矩阵
  prep: { cache: null, loading: false, caseFilter: 'all', searchQuery: '', searchTimer: 0 },
  // 簇 5 瞬时 UI
  toast: { undoTimer: 0 },
};

/** 切段：必须同时复位卡位与翻面（`setCardSegment` 的三写不变量收口于此）。 */
export function enterSegment(segment) {
  cardState.catalog.segment = segment;
  cardState.deck.index = 0;
  cardState.deck.flipped = false;
}

/** 移动卡位：**逐字复刻** `stepDeck` 的两写，不含任何夹取（见下方警告）。 */
export function stepDeckState(delta) {
  cardState.deck.index += delta;
  cardState.deck.flipped = false;
}
```

**只有这两处收成访问器**，因为只有它们编码了真实不变量（§2 末尾三条）。其余状态走直接字段访问 —— 再加十几个 getter/setter 就是 YAGNI，且会把「谁在写」这件事又藏回函数后面。

> ### ⚠️ 一个差点被「顺便修正」的行为变更
>
> 本稿初版把移动卡位写成 `advanceDeck(delta, total)`，自带 `Math.max(0, Math.min(...))` 夹取。
> 读原文后确认**这是错的**：`stepDeck` 今天**没有任何夹取**，它只是
> `setTimeout(() => { deckIndex += direction; deckFlipped = false; renderCardsGrid(); }, 160)`；
> 真正的边界修正在**渲染期**——`renderDeckStage` 里 `if (deckIndex >= deck.length) deckIndex = Math.max(0, deck.length - 1)`，
> 而按钮的 `disabled` 由 `deckIndex === 0` / `deckIndex >= total - 1` 保证「走到头就点不动」。
>
> 若照初版实现，`stepDeck` 会在越界时提前夹住，与「靠 disabled 挡住 + 渲染期纠正」的既有语义产生可观测差异（例如 decks 变化后往回走一步的行为）。**访问器 MUST 逐字复刻，MUST NOT 顺手加固。**
>
> `renderDeckStage` 里那行渲染期夹取**保持内联**，不收成访问器：它是对「传入列表长度」的渲染期纠正，与 `stepDeck` 无关；把它藏进 `cd-state.js` 反而让这个纠正离它依赖的 `deck.length` 更远。

### 6.2 `cards.js` 的改动

- 删掉 15 个顶层 `let`（含 5 处簇内初始值）。
- `import { cardState, enterSegment, stepDeckState } from './cd-state.js';`
- 逐处把 `deckIndex` → `cardState.deck.index` 等；`setCardSegment` / `stepDeck` 改为调用 `enterSegment` / `stepDeckState`。
- **函数结构、导出名、错误轨、API 调用一律不动。**

### 6.3 四个 vm 探针的桩

每个探针的沙箱加一条（与既有 `state: {}` 同级）：

```js
cardState: { catalog: {...}, deck: { index: 0, flipped: false, ... }, quiz: null, prep: {...}, toast: {...} },
```

prelude 的 `var deckIndex/deckFlipped` 可以保留（无害），也可以删 —— 落地时以「探针实跑绿」为准，不做预防性改动。

---

## 7. 本轮明确不做

- **不切视图模块**（方案 B 留待第二跳，需先测）。
- **不根治 `cards↔a1_cards` 的 ESM 环** —— 那是独立缺陷，须单独立项（它今天就在跑，且与本设计正交）。
- **不动 `export * from './a1_cards.js'`** 这条 barrel（`main.js` 经它转发 A1 契约，动了断链）。
- **不动 API 调用面**。若将来要抽 `cards` 的持久化层（对标 `wr-api`/`rd-api`），那是**第三个**独立问题，本次不混做。
- **不碰 `a1_cards.js` / `static/german/**` / 后端**。

---

## 8. 验收判据（机械、可变异自证）

1. **状态收口**：`cards.js` 顶层 `let`/`var` 计数 **== 0**；`cd-state.js` 顶层 `let`/`var` 计数 **== 15 个字段所在的一个 `const`**。
2. **闸立规**：`cards.js` 与 `cd-state.js` 进 `LAYER_SPEC`
   - `cards.js`：新增「禁零顶层可变状态」（这是它首次被该规则覆盖）
   - `cd-state.js`：L1 纯层（禁 DOM/网络/提示/定时器，`allowed_imports=()`）
3. **导出面不变**：36 具名 + 1 条 barrel re-export，逐名相同（静态口径；cards.js 无法运行时导入，见 §4c）。
4. **行为不变**：4 个 vm 探针 + 17 个触碰文件全绿，且 B 类内容断言的**判别力不下降**（若因状态改名必须改断言，须逐个说明「改完仍能抓到原来那个事故」）。
5. **变异自证**：至少 4 条 —— ①在 cards.js 加回顶层 `let` ⇒ 闸红且报 `禁mutable-state`；②`cd-state.js` 里碰 `document` ⇒ 闸红；③`enterSegment` 漏复位 `flipped` ⇒ 必须有用例红（否则该不变量没被守住）；④探针桩缺失 ⇒ 探针必须以 `ReferenceError` 响亮失败，不许静默跳过。
6. **错误轨与导出面冻结**：`notify(`/`alert(`/`console.error(` 行集合进出相等；`main.js` 的 35 条导入零改动。
7. **`ia_dom_mount_probe` 的正则判别力**（§9 站点 ④）：改完正则后 MUST 补一条变异 —— 把 `cardState.catalog.segment === 'a1'` 分流段加进 `renderCardsGrid`，探针必须**红**；否则等于守卫已死而无人知。

---

## 9. 三条未决项的实测结论（初稿写「未测量」，现已量掉）

### Unknown 1 → 已解：旧状态名在测试/探针里只被引用 **12 处**，分三类

| 类 | 站点 | 改法 | 判别力 |
| --- | --- | --- | --- |
| **① 探针 prelude 桩** | `cards_wb_source_probe.mjs`（`deckIndex`/`deckFlipped`）、`cards_workbench_no_review_probe.mjs`（同）×4 处 | 换成 `cardState` 沙箱桩 | 不涉及断言 |
| **② 内容存在性，形状可原样保留** | `test_frontend_guards.py` 4 处（`if (_reviewInFlight) return` / 成对置位 / `disabled = true` / `finally`）、`test_audit_hardening.py` 1 处（`cardSegment !== "prep"`） | 只换标识符，**断言形状逐字不动** | **不降**（改动后必须跑一遍「删掉重入闸 ⇒ 仍红」的变异证明） |
| **③ 名字存在性，需改指向** | `test_prep_matrix.py:130` `"_prepMatrixCache" in _CARDS` | 缓存搬去 `cd-state.js` ⇒ 断言改到**接缝**（cards.js + cd-state.js 两文件）上的 `cardState.prep.cache` | 不降（仍钉「存在一个模块级缓存，懒加载一次」） |
| **④ ⚠️ 判别力风险：改名后正则失配** | `tools/ia_dom_mount_probe.mjs:204` `if (/cardSegment\s*===?\s*['"]a1['"]/.test(renderGridBody))` | 正则必须跟着改成新形态 | **会静默下降**：改名后正则匹配不上，即使有人把 `a1` 分流段加回来也会 **GREEN**。MUST 改正则 **且** 补一条变异自证（加回 `cardState.catalog.segment === 'a1'` 分支 ⇒ 探针必须红） |

**④ 是这次测量里最重要的一条**：它是唯一一个「改完看起来全绿、其实守卫已经死了」的站点。

### Unknown 2 → 已解：`quizState` 在测试与探针里 **零引用**

```
grep -rn "quizState" tests/ tools/  →  0 命中
```

没有任何用例钉它的对象同一性或字段形状 ⇒ 把它改成 `cardState.quiz` 无断言代价。§2 里「8 个读者共享同一引用」仍是实现约束（MUST NOT 改成每次返回新对象），但**没有测试守着它** —— 这本身值得登记：`cardState.quiz` 的同一性目前只能靠代码评审维持。

### Unknown 3 → 已解，且抓出本稿初版的一处行为变更

见 §6.1 的警告块：`stepDeck` **无夹取**，夹取在 `renderDeckStage` 的渲染期。初稿的 `advanceDeck(delta, total)` 会改变可观测行为，已改为逐字复刻的 `stepDeckState(delta)`。

### 仍留雾里

- **Unknown 5**：方案 B（按簇切视图模块）的真实收益。A 落地后按其结果决定。
- **Unknown 6**：`cards↔a1_cards` 的 ESM 环要不要根治、怎么根治。独立事项。

## 10. 建议分期

| 期 | 内容 | 可独立合并 |
| --- | --- | --- |
| 1 | 产出实施计划（任务切分 + 12 个断言站点的逐条处置表） | 是 |
| 2 | 引入 `cd-state.js` + 闸立规（RED 先行：先注册 `cd-state.js` 让 `missing-layer-module` 红） | 是 |
| 3 | `cards.js` 改向 + 四个探针加桩 + B 类断言逐条核 | 是 |
| 4 | 变异自证 + 全量门禁 + PR | 是 |
