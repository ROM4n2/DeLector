# 子计划 5/5 · KARTEI 去复习化（工作台词可见但不打分） Implementation Plan

> **Goal**: 消除"白复习"——用户在卡盒点复习一个工作台词，DSR 四列被写、卡面却因 `fsrs_s` 优先仍显示 `📚 工作台 · s=25`，**复习了但屏幕上什么都没变**，而工作台 FSRS 也没动。做法：**工作台词在卡盒保持可见（统一池的收益之一），但不渲染复习按钮**，只留 `📚 工作台 · s=…` ＋ "去工作台"跳转 ＋ `mastered` 按钮。
> **Tech Stack**: 原生 ES Modules 前端
> **Spec Reference**: `docs/reviews/2026-10-03-swarm-audit-master.md`（product-ux 座 P0「同一词被两台互不知情的排程引擎调度」）
> **Global Constraints**:
> - ⚠️ **改 `static/` ⇒ 触发发版红线**，与子计划 1/5、3/5 **打包同一次发版**。
> - **用户已决策（2026-10-04）：选 A（彻底分家）**，并采纳"可见但不可复习"这一补充形态。
> - **`mastered` 徽记永不隐藏**（`cards.js:207-210` 刚立的契约，T5 落地）⇒ 工作台词若被用户手动标已掌握，仍 MUST 保留 `mastered` 徽记与该徽记的按钮。
> - 门禁：全 `tools/*.mjs` 探针 ＋ `tests/test_frontend_module_graph.py` ＋ `tests/test_german_workbench.py` ＋ 分半 pytest ＋ `ruff`。

---

## 🏛️ Decisions So Far

**用户视角分析（决策依据，勿推翻）**

| 事实 | 位置 | 后果 |
|---|---|---|
| 「待复习」段 = 全部 `!mastered`，**与 due 无关** | `cards.js:146-147` | 工作台词虽被 T3 移出「今日到期」，**仍落在「待复习」段且可点四个复习按钮** |
| 复习只写 DSR 四列，**不碰 `fsrs_*`** | `main.py:1721-1728` | 卡盒复习对工作台的 FSRS 毫无影响 |
| 卡面**优先**看 `fsrs_s` | `cards.js:223-224` | 复习后卡面**仍显示** `📚 工作台 · s=25` ⇒ **用户看不到任何变化** |

⇒ **一次复习，两边都不记账**，且用户无法察觉。这比"两套排程打架"更隐蔽——它连打架都算不上，是纯粹的静默丢弃。

**为什么选 A 而不是 B/C**
- **B（写回工作台）**：FSRS 与 DSR 是两套算法，写回需映射与冲突处理（先写哪边、另一边如何对齐），且仓库有硬规则 **FSRS≠DSR**；她两个界面交替使用时会打架。
- **C（一键送入）**：多一个入口与心智，收益不比 A 多。
- **A ＋ 补刀**：卡盒回归"我全部词汇"的总览（统一池的收益保留），但**只读**——复习去工作台做，符合"在哪个界面学就在哪个界面复习"。

**不选"从卡盒消失"**：她可能想在卡盒里**浏览**背过的词；直接隐藏反而丢掉统一池的价值。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: 工作台词在卡盒不可复习 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `static/js/cards.js`（卡面渲染约 300-370，四个 `submitCardReview` 按钮所在块）
- Test: 新建 `tools/cards_workbench_no_review_probe.mjs`

**Interfaces:**
- Consumes: 既有 `cardStatsTag(card)`（`:207`，**本任务 MUST NOT 改它**）、`toggleMaster`、卡行 `card.fsrs_s`
- Produces: 一个**判据函数**（命名自拟，如 `isWorkbenchSourced(card)`）：`Number.isFinite(Number(card.fsrs_s)) && Number(card.fsrs_s) > 0`（与 `cardStatsTag` 的判据**必须逐字一致**，MUST NOT 复制第二份阈值）
- Produces: 卡面渲染分支——`isWorkbenchSourced(card)` 为真时：**不渲染** `submitCardReview` 的四个按钮（`cards.js:354-366`）、**保留** `mastered` 按钮（`:326-327`）、**追加**"去工作台复习"链接（`href` 沿用 `static/german/workbench.html` 的既有跨页跳转写法，**MUST NOT 自造路由**）

**Injected Instincts:**
- [ ] `[Instinct: Single-Source-Threshold]`: 工作台来源判据 MUST 复用 `cardStatsTag` 的同一判据，**禁**复制第二份 `> 0` 阈值（否则两处漂移 ⇒ 标签与按钮不一致）。
- [ ] `[Instinct: Mastered-Badge-Forever]`: `mastered` 徽记与按钮 MUST 保留（用户亲手设的标记，永不隐藏）。
- [ ] `[Instinct: No-New-Route]`: "去工作台"跳转 MUST 沿用**既有**跨页写法，MUST NOT 臆造路由。
- [ ] `[Instinct: Empty-Hint-Human]`: 替代按钮的位置 MUST 给一句人话（如「在工作台复习」），MUST NOT 留空白或显示技术字段名。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 工作台词在卡盒可见但不可复习。
> Mode: AFK | Role: TDD Builder
> Goal: 消除「点了复习、卡面无变化、两边都不记账」的白复习。
> Target Files: Modify `static/js/cards.js`；Test 新建 `tools/cards_workbench_no_review_probe.mjs`。
> Interfaces: Produces `isWorkbenchSourced(card)` 判据（与 `cardStatsTag` 同一阈值）；工作台词时**不渲染**四个 `submitCardReview` 按钮、**保留** `mastered` 按钮、追加"去工作台"链接（沿用既有跨页写法）。
> Injected Instincts: Single-Source-Threshold / Mastered-Badge-Forever / No-New-Route / Empty-Hint-Human。
> TDD Steps:
> 1. 先读 `static/js/cards.js` 的卡面渲染块（`:300-370`）、`cardStatsTag`（`:207-226`）、`submitCardReview`（`:394`），以及 `static/german/workbench.html` 的既有跨页跳转写法。
> 2. 写探针（RED）：桩一张工作台词（`fsrs_s=25`、`mastered=0`）⇒ 断言渲染结果**不含** `submitCardReview`、**含** `mastered` 按钮、**含**"去工作台"链接；再桩一张普通 reader 卡 ⇒ 断言四个复习按钮**仍在**（旧语义不回归）。
> 3. 确认红，贴输出。
> 4. 改 `cards.js`（GREEN），复跑确认绿。
> 5. 变异验证：把判据阈值改成 `>= 0`（或反向）⇒ 工作台词用例必红；把 `mastered` 按钮也隐藏 ⇒ 必红。
> 6. 门禁：全 `tools/*.mjs` 探针 + `tests/test_frontend_module_graph.py tests/test_german_workbench.py -q` + `ruff`。
> Return: Summary + 物理执行回执。"

**Step Breakdown:**
- [ ] **Step 1: 读代码 + 写探针（RED）**
- [ ] **Step 2: 确认红**
- [ ] **Step 3: 改 `cards.js`（GREEN）**
- [ ] **Step 4: 复跑 + 全探针**
- [ ] **Step 5: 变异验证两条**
- [ ] **Step 6: Physical Evidence Gate**
- [ ] **Step 7: Git 原子 commit**

---

## 🌫️ Fog of War

- **[Fog 1] "去工作台"的目标落点**：跳到工作台首页，还是跳到该词所在的那篇短文/该词条？后者需要 `wb_state` 定位，实现更重。**本任务先跳工作台入口**（沿用既有跨页写法），精准定位另立。
- **[Fog 2] 「今日到期」段呢**：T3 已排除工作台词，但若将来 due 谓词改动，MUST 复查本任务的按钮隐藏是否覆盖全部四个可复习入口（当前只有卡面这一处）。
- **[Fog 3] 工作台侧是否需要"这个词我在卡盒也看得到"的反向提示**：暂不需要（用户已选彻底分家）。

---

## 🚫 Out of Scope

- 不改后端（`delector/` 零改动）——DSR 四列写入逻辑保持原样，只是不再对工作台词可达
- 不删 `submitCardReview`（普通卡仍需它）
- 不改 `cardStatsTag`（T5 刚落地，是本任务复用的判据来源）
- 不做 Fog 1 的精准定位跳转
