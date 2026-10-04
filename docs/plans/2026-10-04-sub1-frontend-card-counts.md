# 子计划 1/5 · 前端切计数端点 Implementation Plan

> **Goal**: `refreshCardCounters()` 改打 `GET /api/cards/counts`，消灭"为了一个 `length` 角标而 `SELECT *` 全表 + 逐卡 FSRS 递推"。
> **Tech Stack**: 原生 ES Modules 前端（`static/js/`）
> **Spec Reference**: `docs/plans/2026-10-03-rank-cache-and-card-counts.md` Fog 1
> **Global Constraints**:
> - ⚠️ **本计划改 `static/` ⇒ 触发项目红线「必须发版 + Android 覆盖安装」**。已与子计划 3（前端竞态）、子计划 5（KARTEI 去复习化）**打包同一次发版**。
> - 端点已就绪（`delector/routes/main.py:726` `get_card_counts`，master `8fef26d`），返回 `{vocab_total, vocab_mastered, grammar_total, grammar_mastered, total}`。
> - 门禁：`ruff` ＋ 两道 mypy ＋ 分半 pytest ＋ **全 `tools/*.mjs` 探针**（前端改动 MUST 全绿）。

---

## 🏛️ Decisions So Far

- **只改 URL 与取值，不改函数结构**：`refreshCardCounters` 的两个角标 DOM id（`card-count` / `mob-card-count`）、`catch {}` 静默兜底、调用点（7 处，跨 5 个模块）**全部不动**。
- **失败必须静默**（现状 `catch (e) {}`）：角标是次要信息，失败时保留旧数字比显示 0 更合理。**MUST NOT** 在失败时把角标清 0。
- **只用 `total`**：端点另 4 个字段当前无消费方（Reviewer 判为预留）。本任务**不**去消费它们，避免超出范围。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: `refreshCardCounters` 切换到计数端点 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `static/js/reader.js:711-722`（`refreshCardCounters`）
- Test: `tools/cards_count_probe.mjs`（新建，照仓库既有 `node:vm` 探针范式）

**Interfaces:**
- Consumes: `api(path, opts)`（`static/js/core.js:99`，已支持 `signal`，本任务不需要）
- Produces: `refreshCardCounters()` 内部改 `await api("/api/cards/counts")`，取值 `data.total`；**函数签名与导出不变**（7 个调用点零改动）

**Injected Instincts:**
- [ ] `[Instinct: Failure-Silent]`: `catch` MUST 保持静默且 **MUST NOT** 把角标写成 `0`（失败时保留旧值）。
- [ ] `[Instinct: Contract-Frozen]`: `GET /api/cards` 与 `GET /api/cards/due` 的前端消费方式零改动（`cards.js:78-83` 不动）。
- [ ] `[Instinct: No-Silent-Field-Drop]`: 若端点返回体缺 `total`（代理截断等），MUST 走 catch 兜底而非显示 `undefined`。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: `refreshCardCounters` 切到 `GET /api/cards/counts`。
> Mode: AFK | Role: TDD Builder
> Goal: 角标只取 `total`，不再拉全量卡片。
> Target Files: Modify `static/js/reader.js:711-722`；Test 新建 `tools/cards_count_probe.mjs`。
> Interfaces: Produces `refreshCardCounters()` 改打 `/api/cards/counts` 取 `data.total`；**签名/导出/两个角标 DOM id/catch 静默兜底全部不变**。
> Injected Instincts: Failure-Silent（失败保留旧值，MUST NOT 写 0）/ Contract-Frozen / No-Silent-Field-Drop。
> TDD Steps:
> 1. 先读 `static/js/core.js` 的 `api()` 与 `tools/wb_cards_vocab_unwrap_probe.mjs` 的探针范式（`node:vm` 切真源码 + 桩 fetch）。
> 2. 写探针（RED）：桩 `api` 记录被请求 path ⇒ 断言它是 `/api/cards/counts` 且**不是** `/api/cards`；桩返回 `{total: 7}` ⇒ 断言两个角标都变成 `7`；桩抛错 ⇒ 断言角标**保持原值不被清 0**。
> 3. 跑 `node tools/cards_count_probe.mjs` 确认红，贴输出。
> 4. 改 `reader.js`（GREEN），复跑确认绿。
> 5. 变异验证：URL 改回 `/api/cards` ⇒ 探针红；`data.total` 改成 `data.vocab_total` 而桩只给 total ⇒ 探针红。
> 6. 门禁：全 `tools/*.mjs` 探针 + `python -m pytest tests/test_frontend_module_graph.py tests/test_german_workbench.py -q` + `python -m ruff check .`。
> Return: Summary + 物理执行回执。"

**Step Breakdown:**
- [ ] **Step 1: 写探针（RED）**
- [ ] **Step 2: 确认红**
- [ ] **Step 3: 改 `reader.js`（GREEN）**
- [ ] **Step 4: 复跑 + 全探针**
- [ ] **Step 5: 变异验证两条**
- [ ] **Step 6: Physical Evidence Gate**
- [ ] **Step 7: Git 原子 commit**

---

## 🌫️ Fog of War

- **[Fog 1] 另 4 个字段何时被消费**：`vocab_mastered` 等 4 字段当前无消费方。若将来要在角标显示"已掌握 N"，另立任务（MUST NOT 顺手加）。
- **[Fog 2] 发版窗口**：本子计划**不含**发版。合并后与子计划 3/5 打包；是否再等 Fog 3（keyset 分页）进同一版，待定。

---

## 🚫 Out of Scope

- 不改 `GET /api/cards` / `GET /api/cards/due` 的前端消费方式
- 不删 `loadCards`（`cards.js:78` 仍需全量渲染卡盒）
- 不动其余 6 个 `refreshCardCounters` 调用点（函数签名不变即零改动）
