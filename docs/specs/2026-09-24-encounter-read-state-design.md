# 遇见区「已读状态 + 推荐顺延」设计

- **日期**：2026-09-24
- **状态**：设计已定（用户已裁定两个决策点），待 `/vault-plan` → `/vault-exec`
- **类别**：Bounded（既有遇见区的范围限定增强，无新子系统）
- **前置**：v5.11.0「i+1 就近选材」（`docs/specs/2026-09-23-encounter-i1-content-and-selection-design.md`）

---

## 1. 问题与用户价值 (Problem Statement & User Value)

**一句话**：v5.11.0 的推荐机制**自己制造了一个新需求** —— 列表没有"已读"概念。

**现状取证**（读代码所得）：

| 事实 | 证据 |
|---|---|
| 推荐基于**覆盖率**，与"读没读过"无关 | `renderI1Hint(ranked, knownSet)` 用 `topPick(ranked)`（`encounter.js:297-316`） |
| 覆盖率只随本机 deck 变化，读完一篇**不影响**排序与推荐 | `rankEntries(knownSet, merged)` 只吃 `total_tokens`/`lemma_seq`（`enc-i1.js`） |
| 列表卡片无任何"读过"标记 | `i1CardHtml(t, cov)`（`encounter.js:232-245`） |
| 进入阅读的唯一入口是 `openText(id)` | `encounter.js:428`（`search.js:33` 亦复用） |

**缺口（真实痛点，7 篇起显现）**：
1. 用户按推荐读完那篇 → 推荐条**不会顺延**，下次打开仍指向同一篇，用户可能以为"就这一篇"或直接放弃；
2. 列表顺序固定 → 看不出"哪几篇我读过了"、还剩几篇；
3. 4 篇时这问题不明显（一屏看完），**7 篇开始它才是主诉求**。

**目标场景**：用户在手机上读完 1–3 篇后回到遇见区 —— 应能一眼看出读过的、并被推荐到**下一篇没读过的**。

**用户价值**：把"读过"变成一等状态，使 v5.11.0 的推荐从"一次性指路"变成**可推进的阅读队列**。

### 非目标 (Non-goals)

- **不做跨端同步**：`enc.*`/`delector_*` 类进度不走 LAN 同步（本项目同步面只覆盖 `wb.*` 背词 deck）。已读**本机判定**，跨端不一致列为后续候选。
- **不做"读完"显式按钮**：已读判定 = **打开即已读**（用户已裁定）。
- **不改列表排序**：已读不沉底（用户已裁定），只加标记。
- **不做手动"标为未读" UI**：纯函数 `unmarkRead` 备而不用。
- **不做阅读次数 / 停留时长 / 最近读排序**：schema 存时间戳已留扩展位，但本次不消费。
- **不动服务端**：无新端点、无新表、无迁移、无索引端点改动。

---

## 2. 用户旅程与核心流程 (User Journey & Core Flow)

**已读标记（零新交互）**
1. 用户点开某篇 → `openText` 渲染成功 → 写已读（幂等）。
2. 返回列表 → 该篇带 `✓ 已读` 标记（标题轻微降权），**位置不变**。

**推荐顺延（≤1 步）**

| 场景 | 推荐条表现 |
|---|---|
| 有**未读**的 i+1 | 现状文案不变（「✅ 正好读：《X》 已背词 91%」） |
| i+1 全读完，但仍有未读（偏简单/偏难） | 「i+1 都读完了，试试《X》（偏简单 96%）」 |
| **全部已读** | 「🎉 7 篇都读过了」完成态（替代推荐条） |
| 未背词（`hasCoverage === false`） | 引导文案优先，**不变**（新用户不能只看 0%） |

**边界**：索引端点失败 → 列表完全退回原行为（无徽章、无推荐条），但**已读标记仍照常显示**（它不依赖索引）。

---

## 3. 架构与数据模型 (Architecture & Data Models)

### 3.1 存储键与 schema

- **键名**：`delector_encounter_read_v1`
- **schema**：`{"v": 1, "read": {"<textId>": <tsMs>}}`

**为什么用 `delector_` 前缀而不是 `enc.`**（关键决策，依据 `static/js/cards.js:897-900` 的前缀契约）：

| 前缀 | 语义 | 是否随备份 |
|---|---|---|
| `delector_`（`BACKUP_LS_PREFIX`） | 主站学习进度（如 `delector_*`） | **是**（导出 + 还原；还原前会清空该前缀再整体灌入） |
| `wb.`（`BACKUP_LS_WORKBENCH_PREFIX`） | 背词工作台进度/设置 | 是 |
| `enc.`（如 `enc.desktop.v1`） | **设备本地偏好**（桌面地址记忆） | 否 |
| `delector_streak_celebrated`（`BACKUP_LS_TRANSIENT`） | 瞬态标记 | 否（显式排除） |

⇒ 已读是**学习进度**而非设备偏好：用 `delector_encounter_read_v1` 即**自动随备份/还原迁移**，且 `cards.js` **零改动**。

**为什么存时间戳而不是布尔**：同样成本，为将来「最近读过的」「读了几次」留扩展位（本次不消费）。

### 3.2 纯函数模块 `static/js/enc-read.js`

与 `enc-i1.js` / `deck-bridge.js` 同纪律：**零 import、模块顶层不碰浏览器全局、坏输入不抛**，`storage` 由调用方注入 → 可被 `node:vm` 探针直接切真实源码运行。

```js
export const READ_KEY = "delector_encounter_read_v1";

export function loadRead(storage);                  // -> {v:1, read:{}}  坏 JSON/缺键 → 空态
export function markRead(storage, id, nowMs);       // -> boolean  幂等：已读返回 false 且不写盘
export function isRead(state, id);                  // -> boolean
export function unmarkRead(storage, id);            // -> boolean  纯函数备用，本次无 UI
export function pickUnread(ranked, readState);      // -> ranked 中首个未读条目 | null
```

- `pickUnread` 只做**顺序扫描**（`ranked` 已由 `rankEntries` 排好序：i1 > easy > hard、组内 rate 降序）→ 未读池的首条若为 `non-i1`，则池内必无 i1（自洽）。
- `markRead` 幂等判据：`read[id]` 已存在 → 返回 `false`、**不写盘**（字节零变化，可断言）。
- 写盘失败（隐私模式 / 配额）→ 静默 `false`，不抛。

### 3.3 集成点（三处，均为叠加）

| 位置 | 改动 |
|---|---|
| `openText(id)`（`encounter.js:428`） | 渲染成功后 `markRead(encStorage(), id, Date.now())`（失败静默） |
| `i1CardHtml(t, cov, readState)` | 已读 → 追加 `<span class="enc-read-mark">✓ 已读</span>` + 卡片类 `is-read` |
| `renderTextList(texts, ranked = null, readState = null)` | 透传 `readState` 到卡片（默认参数，**不传时逐字保持既有行为**） |
| `renderI1Hint(ranked, knownSet, readState = null)` | 用 `pickUnread` 取代 `topPick`；`null` → 完成态；`band !== "i1"` → 降级文案 |

**排序不变**：`rankEntries` 的输出顺序原样使用，已读不影响位置（避免叠两层排序让人困惑）。

**样式**：`static/style.css` 新增 `.enc-read-mark`（沿用既有 Editorial token，不新造硬编码色值）与 `.is-read .encounter-card-title` 轻降权；移动端断点内补规则。

---

## 4. 边界与韧性 (Edge Cases & Resilience)

| 场景 | 行为 |
|---|---|
| localStorage 坏 JSON / 缺键 / 非对象 | `loadRead` → 空态 `{v:1, read:{}}`，UI 全部按"未读"渲染 |
| localStorage 不可用（隐私模式） | `encStorage()` 返回 `null` → `markRead` 静默返回 `false`，UI 零影响 |
| 写盘失败（配额） | 静默 `false`，不抛、不弹错；下次打开仍算未读 |
| 已读 id 指向**已删除**的短文 | 无害：标记按当前 `id` 查，孤儿 id 永不被渲染 |
| 索引端点失败（`ranked = null`） | 列表退回原顺序、无徽章、无推荐条，但**已读标记仍显示** |
| 条目无覆盖率（手工短文 / 未分析行） | 已读标记照常显示（两件事独立） |
| 未背词 + 全部未读 | 引导文案优先（**不变**） |
| 未背词 + 全部已读 | 仍显示引导文案（"先背词"的信息价值高于"读完了"） |
| `ranked` 为空数组 / 非数组 | `pickUnread` → `null` → `hideI1Hint()`（与现状一致） |
| 还原备份 | `delector_` 前缀整体覆盖 → 已读随备份迁移；`enc.desktop.v1` 不受影响 |
| Android | 改动含 `static/` → **必须发版 + 覆盖安装**才生效 |

---

## 5. 测试策略 (Test Strategy)

### 5.1 行为探针（`tools/wb_enc_read_probe.mjs` + `tests/test_enc_read_probe.py`）

`node:vm` 切 **`static/js/enc-read.js` 真实源码**（照抄 `tools/wb_enc_i1_probe.mjs` 的切法），注入桩 storage，覆盖：

1. **空态**：无键 / 坏 JSON / 非对象 → `loadRead` 返回空态且不抛；
2. **幂等**：`markRead` 首次 `true` 且写盘；二次同一 id → `false` 且**存储字节零变化**；
3. **多篇**：连续标记 3 篇 → `read` 含 3 键、时间戳单调递增；
4. **`isRead`**：命中 / 未命中 / `null` id / 空 state；
5. **`unmarkRead`**：删除已存在 id → `true` 且从存储移除；删不存在 → `false` 且不写盘；
6. **`pickUnread`**：① 全未读 → 返回首条；② 首条已读 → 返回第二条；③ 跳过多个已读；④ 全已读 → `null`；⑤ `ranked` 非数组/空 → `null`；⑥ **纯函数**（不改入参与其元素，深比较入参快照）。

### 5.2 UI 契约（`tests/test_encounter_ui_probes.py` 追加）

- `enc-read.js` 被 `encounter.js` import（模块图可达，满足 `test_frontend_module_graph.py`）；
- `enc-read-mark` 标记与 `is-read` 类名出现在卡片渲染路径；
- `renderTextList` / `renderI1Hint` 的新形参**带默认值**（保证旧调用形态不破）；
- 完成态 / 降级文案常量存在且经 `esc(`；
- 已读标记的渲染值经 `esc(`。

### 5.3 关键不变量

> **I-2（幂等）**：`markRead` 对同一 id 二次调用**不写盘**（存储字符串逐字节不变）。
> **I-3（顺延正确性）**：推荐条的 pick ≡ `pickUnread(ranked, readState)`；全已读 → `null` → 完成态。
> **I-4（降级不破坏）**：`ranked = null` 时列表行为与 v5.11.0 **逐字一致**（已读标记是唯一增量）。

### 5.4 收尾门禁

- 全量 pytest **分半跑**（`--ignore=tests/test_server.py` + 单跑 `tests/test_server.py`）；
- `ruff check .` 零告警 / `mypy --strict delector tools` 零 error / 全 `tools/*.mjs` 零漂移。

---

## 6. 关联索引

- `docs/plans/2026-09-24-encounter-read-state.md`（实施计划）
- `docs/specs/2026-09-23-encounter-i1-content-and-selection-design.md`（前置能力：i+1 就近选材）
- `docs/plans/2026-09-10-encounter-content-supply.md`（遇见区内容供给侧）
- `01-Rules/STORED-DATA-BACKFILL.md`（「只增 + 只补空 + 幂等」语义参照）
