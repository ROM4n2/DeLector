# 子计划 3/5 · 前端竞态与反馈修正 Implementation Plan

> **Goal**: 修三个用户可直接撞上的缺陷：① 快速点两篇短文会**读到后点的那篇、却以为在读先点的那篇**，并把两篇都记已读；② 遇见区弹层在手机**每屏最后一行**点词完全无反馈；③ 遇见区**列表**与**详情**已知词来源不同源，清过站点数据/换浏览器时列表说"偏难 0%"、点进去说"已覆盖 82%"。
> **Tech Stack**: 原生 ES Modules 前端
> **Spec Reference**: `docs/reviews/2026-10-03-swarm-audit-master.md`（frontend-architect 座 P1 三条 + CRV 对抗验证修正）
> **Global Constraints**:
> - ⚠️ **改 `static/` ⇒ 触发发版红线**，与子计划 1/5、5/5 **打包同一次发版**。
> - **`api()` 已原生支持 `opts.signal`**（`static/js/core.js:99-107`：外部 signal 合并 + `removeEventListener` 清理 + `finally` 清 timer）⇒ **零新依赖**。
> - 门禁：**全 `tools/*.mjs` 探针** MUST 全绿 ＋ `tests/test_frontend_module_graph.py` ＋ `tests/test_german_workbench.py` ＋ 分半 pytest ＋ `ruff`。

---

## 🏛️ Decisions So Far

- **Task 1 的窗口是秒级不是毫秒级**（CRV 独立核验）：`delector/routes/encounter.py` 的 annotate docstring 自陈「**P0 直跑、禁缓存**」⇒ spaCy 每次真跑；本轮又新增 `await Promise.all([resolveDeck(), fetchKnownLemmas()])`（`encounter.js:496`）⇒ 单次 `openText` 最坏 **3 次 RTT + 1 次全量标注**。
- **`markRead` 幂等写盘且不检查"是不是用户最后点的那个"** ⇒ 晚到的那篇也被记已读 → 被 `pickUnread` 永久剔出 i+1 推荐。
- **`renderTextDetailAnnotated` 无"已渲染就 return"早退**，`renderReaderShell` 是整体覆写 `rd.innerHTML` ⇒ 晚到者必定覆盖先到者。
- **Task 3 危害已下调**（CRV 修正）：两条路径**都** merge 了 `known-lemmas`，差异**只在工作台 deck 那一半** ⇒ 真实症状是"徽章与覆盖率不一致"，非全量撕裂。
- **`resolveDeck()` 已在文件内**（`encounter.js:95`）且已实现「本机空 → 拉镜像 → 合并」完整降级链 ⇒ Task 3 是**纯复用**，不写新逻辑。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: `openText` 加请求代号 + 取消旧 in-flight [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `static/js/encounter.js`（`openText` 约 521-545；`renderTextDetailAnnotated` 约 496 的空 annotate 守卫；`showView` 约 400-450）
- Test: 新建 `tools/enc_open_race_probe.mjs`（`node:vm` 切真源码 + 桩 `api`，**可控 resolve 时序**）

**Interfaces:**
- Consumes: `api(path, {signal})`、`fetchText` / `fetchAnnotate` / `renderTextDetailAnnotated` / `markRead` / `resetSessionReview`
- Produces: 模块级 `let _openSeq = 0`、`let _openCtrl = null`；`openText(id)` 开头 `const seq = ++_openSeq; if (_openCtrl) _openCtrl.abort();`，并把 `ctrl.signal` 透传给两个 fetch；**两处** `if (seq !== _openSeq) return;` 守卫（第一处在两个 fetch 之后；第二处在 `renderTextDetailAnnotated` 之后、**`markRead` 之前**）
- Produces: `showView` 复用同一 `seq` 计数器（覆盖"跨调用旧响应覆盖"）

**Injected Instincts:**
- [ ] `[Instinct: Mark-Read-After-Guard]`: `markRead` MUST 排在**第二道守卫之后** —— 只给真正上屏的那篇记已读。
- [ ] `[Instinct: Guard-Before-Overwrite]`: 第二道守卫 MUST 在 `renderTextDetailAnnotated` **之后**（覆写发生在那里）；第一道守卫用于省掉无谓 annotate 开销。
- [ ] `[Instinct: No-Leak]`: `AbortController` MUST 存进模块变量以便下次 `abort()`；`api()` 已自清 timer。
- [ ] `[Instinct: Empty-Annotate-Early]`: 空 annotate 的降级守卫 MUST **上移到任何 `await` 之前** ⇒ 无 token 的短文零额外往返。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: `openText` 加请求代号 + 取消旧 in-flight。
> Mode: AFK | Role: TDD Builder
> Goal: 消除「点 A 读到 B」与「两篇都被记已读」。
> Target Files: Modify `static/js/encounter.js`；Test 新建 `tools/enc_open_race_probe.mjs`。
> Interfaces: Produces 模块级 `_openSeq`/`_openCtrl`；两处 `if (seq !== _openSeq) return;`；`ctrl.signal` 透传；`markRead` 在第二道守卫之后；空 annotate 守卫上移到 await 之前。
> Injected Instincts: Mark-Read-After-Guard / Guard-Before-Overwrite / No-Leak / Empty-Annotate-Early。
> TDD Steps:
> 1. 读 `static/js/core.js:99-107` 确认 `api()` 的 signal 契约，再读 `openText` / `renderTextDetailAnnotated` / `showView` / `markRead`。
> 2. 写探针（RED），**用可控 resolve 时序的桩 `api`**：
>    - A：点 A（慢）后点 B（快）⇒ 断言最终渲染的是 B、**A 的 `markRead` 未被调用**、B 的被调用；
>    - B：A 在 B 之后才 resolve ⇒ 断言 A **不**覆写 DOM（检查最终 `innerHTML` 标记）；
>    - C：第二次 `openText` ⇒ 断言第一次的 `ctrl.signal` 被 abort。
> 3. 跑探针确认红，贴输出。
> 4. 改 `encounter.js`（GREEN），复跑确认绿。
> 5. 变异验证：删第二道守卫 ⇒ A/B 必红；`markRead` 移到第一道守卫之前 ⇒ A 必红。
> 6. 门禁：全 `tools/*.mjs` 探针 + `tests/test_frontend_module_graph.py tests/test_german_workbench.py -q` + `ruff`。
> Return: Summary + 物理执行回执。"

**Step Breakdown:**
- [ ] **Step 1: 写探针（RED）** → **Step 2: 确认红** → **Step 3: 改代码（GREEN）** → **Step 4: 复跑 + 全探针** → **Step 5: 变异验证两条** → **Step 6: Physical Evidence Gate** → **Step 7: Git 原子 commit**

---

### Task 2: 遇见区弹层加垂直视口夹取 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `static/js/encounter.js:966-970`（`top = Math.round(rect.bottom + 6)` 附近）
- Test: 新建 `tools/enc_popover_clamp_probe.mjs`

**Interfaces:**
- Consumes: `getBoundingClientRect()`、`window.innerHeight`、`pop.offsetHeight`
- Produces: `top` 增加下边界夹取；空间不足时**向上翻转**（`rect.top - offsetHeight - 6`）并再次夹取到 `>= 8`；`left` 既有逻辑不变

**Injected Instincts:**
- [ ] `[Instinct: Flip-Not-Clamp-Only]`: MUST **向上翻转**再夹取，MUST NOT 只做 `Math.min`（否则贴屏顶仍可能被切）。
- [ ] `[Instinct: No-Layout-Thrash]`: MUST NOT 在同一帧反复读 `offsetHeight`（读一次、算一次、写一次）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: 遇见区弹层垂直夹取 + 向上翻转。
> Mode: AFK | Role: TDD Builder
> Goal: 手机上点每屏最后一行时弹层不再整体落到屏幕外。
> Target Files: Modify `static/js/encounter.js:966-970`；Test 新建 `tools/enc_popover_clamp_probe.mjs`。
> Interfaces: Produces `top` 下边界夹取 + 空间不足时向上翻转并夹 `>= 8`；`left` 不变。
> Injected Instincts: Flip-Not-Clamp-Only / No-Layout-Thrash。
> TDD Steps:
> 1. 探针（RED）：桩 `getBoundingClientRect` 返回贴近视口底部的 rect + `innerHeight=640` + `offsetHeight=180` ⇒ 断言写入的 `style.top` **在视口内**（`0 <= top <= 640-180-8`）。
> 2. 确认红。3. 改代码。4. 确认绿。
> 5. 变异验证：删翻转分支只留 `Math.min` ⇒ 必红。
> 6. 门禁：全探针 + `tests/test_frontend_module_graph.py tests/test_german_workbench.py -q`。
> Return: Summary + 回执。"

**Step Breakdown:**
- [ ] **Step 1: 探针（RED）** → **Step 2: 确认红** → **Step 3: 改代码（GREEN）** → **Step 4: 复跑** → **Step 5: 变异验证** → **Step 6: 门禁** → **Step 7: commit**

---

### Task 3: 遇见区列表与详情共用同一 deck 解析 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `static/js/encounter.js:446`（列表 `buildKnownSet(loadDeck(encStorage()))` ⇒ 改用 `resolveDeck()`）
- Test: 新建 `tools/enc_known_same_source_probe.mjs`

**Interfaces:**
- Consumes: `resolveDeck()`（**已存在**，`encounter.js:95`）、`buildKnownSet`、`mergeKnownLemmas`
- Produces: 列表与详情**同源**：`showView` 内 `await resolveDeck()` 再 `buildKnownSet(deck)`；MUST NOT 新写一套镜像兜底（复用阶梯）

**Injected Instincts:**
- [ ] `[Instinct: Reuse-Ladder]`: MUST 复用 `resolveDeck()`，MUST NOT 新写一份「本机空就拉 `/api/wb/state`」的逻辑。
- [ ] `[Instinct: Behaviour-Behind-Flag]`: 改动 MUST NOT 改变**离线**行为（`resolveDeck` 拉镜像失败时静默回退本机，沿用既有 catch）。
- [ ] `[Instinct: No-Silent-Coverage-Drop]]: 若 `resolveDeck()` 抛错，MUST 沿用既有降级（MUST NOT 让整个列表渲染失败）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: 遇见区列表与详情共用同一 deck 解析。
> Mode: AFK | Role: TDD Builder
> Goal: 消除「列表说偏难 0%、点进去说已覆盖 82%」的自相矛盾。
> Target Files: Modify `static/js/encounter.js:446`；Test 新建 `tools/enc_known_same_source_probe.mjs`。
> Interfaces: Produces `showView` 改用 `await resolveDeck()` + `buildKnownSet(deck)`；`resolveDeck` 本身零改动。
> Injected Instincts: Reuse-Ladder / Behaviour-Behind-Flag / No-Silent-Coverage-Drop。
> TDD Steps:
> 1. 探针（RED）：桩 `loadDeck` 返回空 + 桩 `api('/api/wb/state')` 返回含 2 个已学词的 deck ⇒ 断言**列表**的 knownSet 含这 2 个词（当前实现不含 ⇒ 红）。
> 2. 确认红。3. 把 `showView` 改用 `resolveDeck()`。4. 确认绿。
> 5. 变异验证：把 `showView` 改回 `loadDeck` ⇒ 必红。
> 6. 门禁：全探针 + 两个前端测试文件。
> Return: Summary + 回执。"

**Step Breakdown:**
- [ ] **Step 1: 探针（RED）** → **Step 2: 确认红** → **Step 3: 改代码（GREEN）** → **Step 4: 复跑** → **Step 5: 变异验证** → **Step 6: 门禁** → **Step 7: commit**

---

## 🌫️ Fog of War

- **[Fog 1] 失败反馈文案**：离线时 `showView` 会把 `fetch` 的原始错误（`Failed to fetch` / `NetworkError`）直接上屏（`encounter.js` 约 424-431）。是否要翻成"检查网络后重试"人话？**属独立 UX 任务**，本子计划不做。
- **[Fog 2] `fetchKnownLemmas` 无 in-flight 去重**：同一次会话会被请求 N+1 次。优化它需引入模块级 promise 缓存（范式见 `a1_cards.js:62-64` 的 `_examVocabLoadingPromises`）⇒ **独立任务**，避免与 Task 3 的 deck 改动纠缠。
- **[Fog 3] 覆盖率行不携带来源/降级信息**：`renderCoverage` 只写「已背词覆盖 X/Y 词位（N%）」，用户不知道其中一路刚失败。需 UI 决策。

---

## 🚫 Out of Scope

- 不改 `delector/`（后端零改动）
- 不做离线文案（Fog 1）、不做 known-lemmas 去重缓存（Fog 2）
- 不动 `reader.js`（属子计划 1/5）
