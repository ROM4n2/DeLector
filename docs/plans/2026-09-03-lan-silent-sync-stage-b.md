# 局域网静默同步 Stage B（自动化 WebRTC + 持久配对凭证）Implementation Plan

> **Goal**: 在 Stage A「配对一次 + HTTP 轮询」之上，用 WebRTC DataChannel 实现持久配对凭证下的自动建连/重连与加密双向静默同步，并保留 HTTP 轮询为兜底通道。
> **Tech Stack**: Python 3.11（FastAPI 信令中继）/ 浏览器原生 WebRTC（RTCPeerConnection + DataChannel）/ 前端内联于 `static/german/workbench.html` 的 `wbsync` 模块。
> **Spec Reference**: `docs/specs/2026-09-03-lan-silent-sync-design.md`（§3.6 路线 B / §6）；`d:/Obsidian/Coding/08-Projects/DeLector/01-ADR/0004-lan-sync-webrtc-stage-b.md`（范围/架构锁定）。
> **Global Constraints**:
> - 合并权威唯一：所有到达的同步信封一律 `applyMerge(envelope, {silent: true})`，不得新写合并逻辑。
> - 信任模型不变：`GET /api/wb/state` 仍局域网开放；`PUT /api/wb/state` 仍 `X-WB-Key`；`GET /api/wb/state/key` 仍仅本机；`/info` 仍开放。
> - 密钥/凭证仅落 `app_settings` + `localStorage`，**绝不进 Git**（pre-commit 密钥扫描 + 本地存储）。
> - 端点仅绑 LAN 接口、拒绝非 RFC1918 源；密钥错误即 403（沿用 Stage A 已实现）。
> - 复用优先：信令中继复用 `routes_sync.py` 的内存缓存模式；凭证复用 `get_wb_sync_key()`（位于 `database.py`，**两端均从 `database` 导入，避免 `routes_*` ↔ `server` 循环依赖**）。
> - `test_german_workbench.py` 用**字符串 split** 解析 `workbench.html`（first-occurrence 语义）：新增内联模块须用**具名函数/表达式**，严禁提前引入其定位记号（`(async () => {`、`loadAll();`、`})();` 等），否则静默破坏几十条解析。
> - 测试纪律：每个 Task 走 RED→验证 RED→GREEN→验证 GREEN→提交；含「退回旧实现必红」的变异验证（继承 `tools/wb_*.mjs` 探针范式）。
> - 测试可达性：本环境**无法真跑 WebRTC E2E** → 服务端中继走纯 FastAPI 单测；前端走 node:vm 探针注入**桩 `RTCPeerConnection`** 验证建连/收发契约；真机（双浏览器 + 下次发版后的 Android APP）手动验证兜底。

---

## 上下文摄取（Phase 1 替代说明）
环境无 `omni_search` / `coding-vault-search` MCP，已用既有设计稿 + ADR-0004 + 真实代码锚点替代摄取：
- 信令：`routes_sync.py`（`/store` POST、`/fetch/{code}` GET、`/info` GET，当前**无** `X-WB-Key` 门；`test_sync_sdp_lan_accessible(lan_client)` 已守护「不得被仅本机门误伤」）。
- 镜像：`server.py:1430-1446`（`/api/wb/state` GET/PUT、`/api/wb/state/key` GET 走 `_require_localhost`）；`database.get_wb_sync_key()` 为密钥唯一来源。
- 前端：`static/german/workbench.html` 内 `wbsync.pair.*` / `applyMerge` / `push()` / `pull()`；`wbsync.pair` 已支持 `{host, key}` 持久化（`wb.pair.v1`）。
- 测试夹具：`test_server.py` 提供 `client`（127.0.0.1）与 `lan_client`（192.168.1.77）；wb CORS 中间件 `_wb_sync_cors` 覆盖 `/api/wb/state`、`/api/wb/state/key` 与 `/api/wb/sync/*`。

---

### Task 1: 信令端点 X-WB-Key 鉴权 [Role: TDD Builder]

**Files:**
- Modify: `routes_sync.py:54-79`（`sync_store_sdp`、`sync_fetch_sdp`）
- Test: `test_server.py`（新增 3 个用例 + 改造 1 个既有用例）

**Interfaces:**
- Consumes: `get_wb_sync_key()`（from `database`）
- Produces: `POST /api/wb/sync/store`、`GET /api/wb/sync/fetch/{code}` 现须 `X-WB-Key` 头；`/info` 不变

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 1: 信令端点 X-WB-Key 鉴权。
> Goal: `routes_sync.py` 的 `/store` 与 `/fetch/{code}` 在拿到与 `get_wb_sync_key()` 一致的 `X-WB-Key` 时才放行；缺/错 key → 403。`/info` 保持开放。
> Target Files: Modify `routes_sync.py`，Test `test_server.py`。
> 约束：从 `database` 导入 `get_wb_sync_key`（勿从 `server` 导入以免循环依赖）。
> TDD Steps:
> 1. 在 `test_server.py` 写 `test_sync_store_requires_key`（无 key → 403）、`test_sync_fetch_requires_key`（无 key → 403）、`test_sync_store_with_key_ok`（带 key → 200 且返回 code）。(RED)
> 2. 运行 `pytest -q test_server.py -k sync` 验证上述失败。
> 3. 在 `routes_sync.py` 两个端点加 `X-WB-Key` 校验。(GREEN)
> 4. 改造既有 `test_sync_sdp_lan_accessible(lan_client)`：在请求中附带 `X-WB-Key` 头（其值取自 `get_wb_sync_key()`），保证该守护用例仍绿。
> 5. 运行 `pytest -q test_server.py -k sync` 全绿。
> 6. 原子提交 `fix(server): signaling endpoints require X-WB-Key`。
> Return: 摘要 + 测试执行证据。"

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）** — 新增 3 个鉴权用例
- [ ] **Step 2: 运行并验证失败（预期 403 未出现）**
- [ ] **Step 3: 最小实现（GREEN）** — `routes_sync.py` 两端点校验 `X-WB-Key`
- [ ] **Step 4: 改造既有用例** — `test_sync_sdp_lan_accessible` 补 key 头
- [ ] **Step 5: 运行测试全绿**
- [ ] **Step 6: Git 原子提交**

---

### Task 2: 持久配对凭证模型 + 撤销 [Role: TDD Builder]

**Files:**
- Modify: `database.py`（新增 `set_wb_sync_key()`）
- Modify: `server.py:1443-1446`（`GET /api/wb/state/key` 旁新增 `POST /api/wb/state/key`，`_require_localhost` + 调 `set_wb_sync_key` 重新生成）
- Modify: `static/german/workbench.html`（`wbsync.pair` 增加 `revokePair()`；UI 增加「撤销配对/重新生成密钥」入口）
- Test: `test_server.py`（`test_wb_state_key_regenerate_requires_localhost`、`test_wb_state_key_regenerate_changes_key`）；`tools/wb_pair_persist_probe.mjs`（node:vm 探针）

**Interfaces:**
- Consumes: `get_wb_sync_key()`（database）
- Produces: `set_wb_sync_key(new_key)`（database，新）；`POST /api/wb/state/key`（server，本机）；`wbsync.pair.revoke()`（前端）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 2: 持久配对凭证 + 撤销。
> Goal: 服务端支持重新生成同步密钥（仅本机）；前端 `wbsync.pair` 增加 `revokePair()`，调用 `POST /api/wb/state/key` 后清空远端配对状态并强制重新配对。
> Target Files: Modify `database.py`、`server.py`、`static/german/workbench.html`；Test `test_server.py` + 新建 `tools/wb_pair_persist_probe.mjs`。
> 约束：`set_wb_sync_key` 写 `app_settings`；`POST /api/wb/state/key` 须 `_require_localhost`；前端改动**不得**引入 `test_german_workbench.py` 的定位记号。
> TDD Steps:
> 1. 写 `test_wb_state_key_regenerate_requires_localhost`（lan_client → 403）、`test_wb_state_key_regenerate_changes_key`（client 调 POST 后 GET /key 值变化且旧 key 写 403）。(RED)
> 2. 运行验证失败。
> 3. 实现 `set_wb_sync_key` + `POST /api/wb/state/key` + 前端 `revokePair`。(GREEN)
> 4. 写 `tools/wb_pair_persist_probe.mjs`：注入 `wbsync` 源码（node:vm），断言 `pair.set` 落 `wb.pair.v1` 且 `revokePair` 触发 `POST /api/wb/state/key` 并清本地配对；做变异验证（删 `revokePair` 的 POST 调用 → 探针红）。
> 5. 运行 `pytest -q test_server.py -k wb_state_key` 与 `node --check` / 探针全绿。
> 6. 原子提交 `feat(server,frontend): persistent pairing credential + revoke`。
> Return: 摘要 + 测试执行证据。"

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）** — 服务端 2 用例
- [ ] **Step 2: 运行验证失败**
- [ ] **Step 3: 最小实现（GREEN）** — `set_wb_sync_key` + 端点 + 前端 `revokePair`
- [ ] **Step 4: 前端探针 + 变异验证**
- [ ] **Step 5: 全部测试绿**
- [ ] **Step 6: Git 原子提交**

---

### Task 3: WebRTC 信令中继（服务端）[Role: TDD Builder]

**Files:**
- Create: `routes_rtc.py`（`/api/wb/rtc/signal` POST 与 GET，按**配对密钥**建邮箱：存 `offer/answer/candidate`，带 `X-WB-Key`，内存缓存 + TTL + 容量上限，复用 `routes_sync.py` 的清理模式）
- Modify: `server.py`（顶部 `app.include_router(routes_rtc.router)`）
- Test: `test_server.py`（`test_rtc_signal_requires_key`、`test_rtc_signal_roundtrip`、`test_rtc_signal_no_cross_key`）

**Interfaces:**
- Consumes: `get_wb_sync_key()`（database）
- Produces: `POST /api/wb/rtc/signal`、`GET /api/wb/rtc/signal`（均以配对密钥为邮箱 id，替代 Stage A 的 6 位短码）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 3: WebRTC 信令中继（服务端）。
> Goal: 新增 `routes_rtc.py`，用配对密钥作邮箱 id（持久、非短码），缓存 offer/answer/ICE candidate，供两端建连交换；须 `X-WB-Key`；内存 TTL≈60s + 容量上限。
> Target Files: Create `routes_rtc.py`，Modify `server.py`（include router），Test `test_server.py`。
> 约束：从 `database` 导入 `get_wb_sync_key`；复用 `routes_sync.py` 的 `_cleanup_sync_cache` 思路但不共享可变全局（独立锁与缓存）。
> TDD Steps:
> 1. 写 `test_rtc_signal_requires_key`（无 key → 403）、`test_rtc_signal_roundtrip`（A 以 key 存 offer，B 以同 key 取回）、`test_rtc_signal_no_cross_key`（不同 key 互不可见）。(RED)
> 2. 运行验证失败。
> 3. 实现 `routes_rtc.py` + 注册 router。(GREEN)
> 4. 运行 `pytest -q test_server.py -k rtc` 全绿。
> 5. 原子提交 `feat(server): webrtc signaling relay keyed by pairing key`。
> Return: 摘要 + 测试证据。"

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）**
- [ ] **Step 2: 运行验证失败**
- [ ] **Step 3: 最小实现（GREEN）** — `routes_rtc.py` + 注册
- [ ] **Step 4: 运行全绿**
- [ ] **Step 5: Git 原子提交**

---

### Task 4: 前端 WebRTC 建连 + DataChannel [Role: TDD Builder]

**Files:**
- Modify: `static/german/workbench.html`（新增 `wbsync.rtc` 模块：`connect(pair)` 建 `RTCPeerConnection`、建 DataChannel、经 `routes_rtc` 交换 offer/answer/candidate（带 `X-WB-Key`）、`onopen` 发 `snapshot()`、`onmessage` → `applyMerge(env, {silent:true})`）
- Test: `tools/wb_rtc_connect_probe.mjs`（node:vm + 桩 `RTCPeerConnection`）

**Interfaces:**
- Consumes: `routes_rtc` 端点、`snapshot()`、`applyMerge(data, opts)`
- Produces: `wbsync.rtc.connect(pair)`、`wbsync.rtc.sendEnvelope(env)`

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 4: 前端 WebRTC 建连 + DataChannel。
> Goal: `wbsync.rtc.connect(pair)` 用桩可测的方式建立 P2P DataChannel；建连后发快照、收信封静默合并。
> Target Files: Modify `static/german/workbench.html`（新增 `wbsync.rtc`）; 新建 `tools/wb_rtc_connect_probe.mjs`。
> 约束：内联具名函数，不引入 `test_german_workbench.py` 的定位记号；合并只能走 `applyMerge(env,{silent:true})`。
> TDD Steps:
> 1. 写 `wb_rtc_connect_probe.mjs`：注入源码，桩 `RTCPeerConnection`（记录 `createDataChannel`、捕获 `createOffer` 结果并断言被 POST 到 `/api/wb/rtc/signal` 带 `X-WB-Key`）；模拟对端发来的信封 → 断言 `applyMerge` 以 `silent:true` 被调用。(RED：源码尚无 `wbsync.rtc`)
> 2. 实现 `wbsync.rtc.connect` + `sendEnvelope`。(GREEN)
> 3. 变异验证：把 `applyMerge` 调用改回非 silent → 探针红。
> 4. 运行 `node --check` + 探针全绿；确认 `test_german_workbench.py` 仍全绿（未破坏解析）。
> 5. 原子提交 `feat(frontend): webrtc datachannel connect`。
> Return: 摘要 + 探针证据。"

**Step Breakdown:**
- [ ] **Step 1: 写前端探针（RED）**
- [ ] **Step 2: 最小实现（GREEN）**
- [ ] **Step 3: 变异验证**
- [ ] **Step 4: 运行 `test_german_workbench.py` 全绿**
- [ ] **Step 5: Git 原子提交**

---

### Task 5: 自动重连 + 静默对账 + HTTP 兜底 [Role: TDD Builder]

**Files:**
- Modify: `static/german/workbench.html`（boot 编排：优先 `wbsync.rtc.connect`；`connectionstatechange` 失败/关闭 → 去抖重建（用缓存凭证）；连续失败 N 次 → 降级回 Stage A 的 `push()/pull()` 轮询；所有合并走 `applyMerge(silent)`）
- Test: `tools/wb_rtc_reconnect_probe.mjs`（模拟 `connectionstatechange` → 断言重建被调用；RTC 不可用时断言降级标志）

**Interfaces:**
- Consumes: `wbsync.rtc`、`wbsync.push()`、`wbsync.pull()`、`applyMerge`
- Produces: `wbsync.autoSync()` 编排器（对外统一入口）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 5: 自动重连 + 静默对账 + HTTP 兜底。
> Goal: `wbsync.autoSync()` 优先 WebRTC，断线去抖重建，失败降级到 Stage A HTTP 轮询；全程静默合并。
> Target Files: Modify `static/german/workbench.html`; 新建 `tools/wb_rtc_reconnect_probe.mjs`。
> 约束：沿用 `applyMerge(silent)`；不引入测试定位记号；降级路径复用既有 `push/pull`（勿重写）。
> TDD Steps:
> 1. 写 `wb_rtc_reconnect_probe.mjs`：注入源码，桩 `RTCPeerConnection` 触发 `connectionstatechange='failed'` → 断言 `connect` 被再次调用（去抖）；桩 `RTCPeerConnection=undefined` → 断言 `autoSync` 置降级标志并启用 HTTP 轮询。(RED)
> 2. 实现 `wbsync.autoSync` 编排 + 去抖 + 降级。(GREEN)
> 3. 变异验证：删降级分支 → 探针红。
> 4. 运行探针 + `test_german_workbench.py` 全绿。
> 5. 原子提交 `feat(frontend): auto-reconnect + http fallback`。
> Return: 摘要 + 探针证据。"

**Step Breakdown:**
- [ ] **Step 1: 写重连/降级探针（RED）**
- [ ] **Step 2: 最小实现（GREEN）**
- [ ] **Step 3: 变异验证**
- [ ] **Step 4: 运行 `test_german_workbench.py` 全绿**
- [ ] **Step 5: Git 原子提交**

---

### Task 6: 集成回归 + 文档回填 + ledger（收尾）[Role: Integrator]

**Files:**
- Modify: `AGENTS.md`（路由清单补 `/api/wb/rtc/signal` + Stage B 小节）、`FEATURES.md`（§十三 行升级为「WebRTC 加密静默」）、`docs/specs/2026-09-03-lan-silent-sync-design.md`（§6 Stage B 勾选）、`docs/plans/2026-09-03-lan-silent-sync-stage-a-ledger.md`（追加 Stage B Task 行 + 真机手动验证清单：桌面↔桌面浏览器可先于 APP；APP 挂下次发版）
- Test: 回归 `test_server.py -k "wb or sync or rtc"`、`test_german_workbench.py`、`test_frontend_module_graph.py`

**Interfaces:**
- Consumes: 上述全部实现
- Produces: 文档/ledger 落地 + 三次原子提交（`feat(server): ...`、`feat(frontend): ...`、`docs: Stage B ...`）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 6: 集成回归 + 文档回填。
> Goal: 跑全量定向回归，把 Stage B 结果回填 AGENTS/FEATURES/spec/ledger。
> Target Files: 上述 4 个文档；回归测试。
> 约束：定向回归须全绿（server wb/sync/rtc 组 + workbench + module_graph）；ledger 注明 APP 路径待下次发版验证。
> Steps:
> 1. 跑 `pytest -q test_server.py -k 'wb or sync or rtc'`、`test_german_workbench.py`、`test_frontend_module_graph.py`，确认全绿。
> 2. 回填文档：AGENTS 路由表 + Stage B 小节；FEATURES §十三；spec §6 勾选；ledger 追加 Task 行 + 真机清单。
> 3. 三次原子提交（server / frontend / docs）。
> Return: 摘要 + 回归证据 + 提交哈希。"

**Step Breakdown:**
- [ ] **Step 1: 跑定向回归全绿**
- [ ] **Step 2: 回填 4 个文档**
- [ ] **Step 3: 三次原子提交**

---

## Phase 3: Downstream Dispatch
Plan generated with subagent prompt scaffolds (Tasks 1–6). 初始化 ledger 并用 `/vault-exec` 执行？建议执行顺序严格按 Task 1→6（M1 信令鉴权 → M2 持久凭证 → M3 信令中继 → M4 前端建连 → M5 重连兜底 → M6 回归回填）。

> 注意：M5 的 Android APP 真机验证须等**下次发版**（旧版 APK 未内嵌 Stage A+B 代码），与 Stage A 收尾结论一致；本环境无法真跑 WebRTC E2E，所有 WebRTC 行为以桩 `RTCPeerConnection` + 中继往返单测 + 真机手动验证兜底。
