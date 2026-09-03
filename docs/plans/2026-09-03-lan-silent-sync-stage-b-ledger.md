# Stage B（自动化 WebRTC + 持久配对凭证）执行 Ledger

> 计划：`docs/plans/2026-09-03-lan-silent-sync-stage-b.md`
> ADR：`d:/Obsidian/Coding/08-Projects/DeLector/01-ADR/0004-lan-sync-webrtc-stage-b.md`
> 基线提交：`3df9d84`

## 执行模式降级说明（如实记录）

vault-exec 的 Zero-Edit Iron Rule 要求「编排者主线程不直接改生产代码，全部交给子代理」。本环境不具备该前提，故如实降级并记录：

- **无写码子代理**：`task` 工具仅提供只读的 `code-explorer`，无法派发 TDD Builder / Reviewer 子代理。降级为「编排者主线程直写 + 严格 TDD（RED → 验证 RED → GREEN → 验证 GREEN）+ 每 Task 原子提交」；Maker-Checker 环节由主线程自查（变异验证 + 定向回归）替代。**未伪造子代理派发记录**。
- **无 `scripts/vault_exec_state.py`**：vault-exec 目录下只有 SKILL.md，不存在该 ledger CLI。ledger 用本 Markdown 文件维护，沿用 Stage A ledger 约定。
- **无 WebRTC E2E 能力**：本环境不能真跑 P2P。服务端走纯 FastAPI 单测；前端走 node:vm 探针注入桩 `RTCPeerConnection`；真机（双桌面浏览器 + Android APP 下次发版）手动验证兜底。

## 任务进度

| # | 任务 | 状态 | 提交 | 测试证据 |
|---|------|------|------|----------|
| 1 | M1 信令端点 X-WB-Key 鉴权 | 完成 | `db59bdf` | sync/cors/wb/lan_info 24 passed；前端 2 文件 87 passed |
| 2 | M2 持久配对凭证 + 撤销 | 完成 | `0d572cb` + `37f135c` | 服务端 26 passed；前端 7 探针全 PASS + 36 passed |
| 3 | M3 WebRTC 信令中继 routes_rtc | 完成 | `d782d56` | rtc/sync/wb/cors/lan_info 30 passed |
| 4 | M3 前端 WebRTC 建连 + DataChannel | 完成 | `2d5ee4b` | 8 探针全 PASS + 40 passed |
| 5 | M4 自动重连 + 静默对账 + HTTP 兜底 | 完成 | `689388e` | 9 探针全 PASS + 40 passed |
| 6 | 回归 + 文档回填 | 完成 | `3df9d84` 之后共 7 次提交 | 见下 |

## Task 1 详情（M1 信令鉴权）

**改动**：`routes_sync.py` 新增 `_verify_wb_key()` 守卫（缺/错 key 变 403），`/store` 与 `/fetch/{code}` 两个端点加 `Request` 参数并在**消费短码之前**校验（保证 403 无副作用）；`/info` 保持开放。`server.py` 预检 `Access-Control-Allow-Methods` 补 `POST`（抽常量 `_WB_CORS_ALLOW_METHODS`）。

**发现的真实缺陷（计划外，回归补漏）**：CORS 预检只放行 `GET, PUT, OPTIONS`，而 `/store` 是 POST。一旦要求 `X-WB-Key`，跨域浏览器会在预检阶段被拒、信令永远发不出去。已补 `POST` 并加回归测试 `test_sync_store_preflight_allows_post_and_key`。

**新增测试**：`test_sync_store_requires_key`、`test_sync_fetch_requires_key`（含「403 不得消费短码」的副作用断言）、`test_sync_store_preflight_allows_post_and_key`。

**同步改造的既有用例**：`test_sync_sdp_store_and_fetch`、`test_sync_sdp_fetch_invalid_code`、`test_sync_sdp_lan_accessible`（改为 client + lan_client 双夹具）、`test_sync_sdp_cache_capacity_and_size_limit`、`test_task1_sync_router_thread_safety`（历史用例，首轮 grep 未覆盖到，第二轮回归才暴露）。

**RED 验证**：3 个新测试全红（预检报错原文 `assert 'POST' in 'GET, PUT, OPTIONS'` 坐实缺陷），9 个既有 sync 用例仍绿。

## Task 2 详情（M2 持久配对凭证 + 撤销）—— 服务端已完成

**改动**：`database.py` 新增 `regenerate_wb_sync_key()`（生成新 32 位 hex 并覆盖 `app_settings.wb_sync_key`）；
`server.py` 新增 `POST /api/wb/state/key`（`_require_localhost` 守护，仅本机可调）。

**与计划的一处偏差（有意为之）**：计划 Interface 写的是 `set_wb_sync_key(new_key)`，实际改为
`regenerate_wb_sync_key()`——无任何调用方需要「设置成任意值」，且生成逻辑留在 `database.py`
可避免给 `server.py` 引入 `secrets` 导入（该文件原本就没导入）。符合 YAGNI。

**新增测试**：`test_wb_state_key_regenerate_requires_localhost`（局域网不得重置别人凭证）、
`test_wb_state_key_regenerate_invalidates_old_key`（旧 key 立即 403、新 key 可用、GET 回读一致）。

**RED 验证**：2 个新测试全红（`405 Method Not Allowed` vs 期望 403/200），既有 1 个绿。

**前端（提交 `37f135c`）**：`wbsync` 内新增 `async revokePair()` 并经 `pair.revoke` 导出，宿主面板
加「撤销配对」按钮。`revokePair` POST `/api/wb/state/key`，成功后 `clearPair()` 并把 `_key` **换成
服务端下发的新 key** —— 这一步是关键：不换 key 的话主机会被自己作废的 key 卡死
（`pushNow` 开头 `if (!_enabled || !_key) return` 直接短路，连本机都推不动）。

**探针**：`tools/wb_pair_persist_probe.mjs` 钉 5 条契约（set 落盘含 host+key / revoke 真的 POST
服务端重生成 / revoke 清掉 localStorage 且 pairInfo 归 null / revoke 返回新 key / 撤销后 pushNow
用**新** key）。**变异验证**：删掉 `_key = newKey` 这一行 → 探针红（报「撤销后 pushNow 没有推送」），
证明「换 key」不是死断言。7 个既有 wbsync 探针复跑全 PASS。

## Task 3 详情（M3 WebRTC 信令中继）—— 已完成

**改动**：新建 `routes_rtc.py`，`POST/GET /api/wb/rtc/signal`；`server.py` 注册 router，并把
`_WB_CORS_PREFIX` 改成 `_WB_CORS_PREFIXES` 元组（`str.startswith` 接受元组，多点改动）。

**设计要点（与 Stage A 短码中转的三处不同）**：
- 邮箱 id 用**配对密钥的 sha256 摘要**，不是 6 位短码：持久凭证下两端长期共用一把 key，
  不必每次会话再生成/抄写短码。用摘要而非密钥原文，避免密钥在内存结构里多留一份明文。
- 每条信令带 `sender`（客户端自生成的会话 id），GET 只投递「别人发的」：发信端若收到自己
  的回声，两端会互相把对方的旧 offer 当成新 offer 反复重建连接。
- GET 带 `after` 游标，只返回游标之后的消息，避免每轮轮询重放整个建连过程。

**新增测试**：`test_rtc_signal_requires_key`、`test_rtc_signal_roundtrip`（含「发信端收不到自己
信令」断言）、`test_rtc_signal_cursor_filters_consumed`、`test_rtc_signal_cors_preflight_allows_post`
（新前缀也要过跨域预检，否则 APP WebView 发不出信令）。

**RED 验证**：4 个新测试全红（`405 Method Not Allowed`，路由尚不存在）。
**变异验证**：去掉 `m["sender"] != client` 过滤 → `test_rtc_signal_roundtrip` 红，证明回声隔离不是死断言。

**容量/时效**：每邮箱 50 条、最多 50 个邮箱（FIFO 淘汰最久没动静的）、TTL 120s、单条 payload 32KB。

## Task 4 详情（M3 前端 WebRTC 建连）—— 已完成

**改动**：`static/german/workbench.html` 内 `wbsync` 新增 `rtc` 子系统，经 `wbsync.rtc` 导出
`{connect, supported, send, close}`。

**关键设计**：
- **角色免协商**：是否已配对决定角色——已配对到远端的一侧（`_pair` 存在）发 offer，宿主侧应答。
  不必再设计「谁先发起」的协商，也不会出现双方同时 offer 打架（glare）。
- **信封与 HTTP PUT 同构**：`{payload: snapshot()}`。两种通道共一套契约，少一处不一致的余地
  （2026-09-02 事故就是前端发裸快照、后端要 `{payload:...}` 导致进度永不合并且 200 全绿）。
- 收到信封 → `applyMerge(env.payload, {silent: true})`，只传内层 payload。
- 信令带 `client` 会话 id + `after` 游标；建连阶段不等定时器、先立刻拉一次，尽快收下对端 answer。
- 纯局域网场景 `{iceServers: []}`，不引 STUN。

**探针**：`tools/wb_rtc_connect_probe.mjs`，注入桩 `RTCPeerConnection`，钉 5 条契约（建 DataChannel +
createOffer / offer 发往**配对远端**中继且带配对 key / 对端 answer 与 candidate 被应用 / open 后发快照 /
收到信封走**静默**合并且传内层 payload）。

**RED 验证**：切片缺 `rtcConnect` → 探针红。**变异验证**：把 `applyMerge(env.payload, {silent:true})`
改回 `applyMerge(env.payload)` → 探针红（报「合并没有走静默模式」）——这正是 2026-09-03
「轮询弹窗切视图」事故的同形态回归，钉住了。

**说明**：Task 4 只提供能力，不接管启动流程；`autoSync()` 编排（含重连与 HTTP 兜底）在 Task 5。

## Task 5 详情（M4 自动重连 + HTTP 兜底）—— 已完成

**改动**：`wbsync` 内新增 `rtcOnStateChange` / `rtcScheduleRetry` / `rtcDegraded` / `autoSync`；
`rtcConnect` 改为幂等（已建连返回 true）并挂 `onconnectionstatechange`；`boot()` 末尾调用
`autoSync()`（HTTP 轮询先跑起来兜底，再试着升级到 WebRTC）。

**两个刻意的取舍**：
- **去抖而非立即重建**：`RTC_RETRY_MS = 3000`，且同一断线只排一次重建（`_rtcRetryTimer` 守卫）。
  ICE 抖动时若每次状态回调都重建，会变成疯狂建连打服务端。
- **失败有上限**：连续失败 > `RTC_MAX_FAILS`(3) 即置 `_rtcDegraded` 并停手。降级不是「再也不试」，
  而是「不再空转」——Stage A 的 HTTP 轮询始终在线，保证「至少可达」。

**探针**：`tools/wb_rtc_reconnect_probe.mjs` 跑**两个 vm 场景**：A 注入桩 `RTCPeerConnection`
（模拟 `connectionState="failed"` → 断言去抖重建；连续失败到上限 → 断言 degraded 且**不再**建连）；
B 不注入 `RTCPeerConnection`（断言 `autoSync()` 返回 false、直接降级，且 boot 的 HTTP 拉取照常发生）。
`setTimeout` 桩只记录回调、由探针手动推进，不去抖真实时间。

**变异验证**：删掉失败上限降级分支（即无限重试）→ 探针红（报「没有进入降级，会无限重试」）。

## Task 6 详情（回归 + 文档回填）—— 已完成

- 回归：9 个 wbsync 探针全 PASS；`test_german_workbench` + `test_frontend_module_graph` +
  `test_server` 定向（wb/rtc/sync/cors/lan_info）**40 passed**。
- `AGENTS.md`：路由表补 `POST /api/wb/state/key`、`POST|GET /api/wb/rtc/signal`，并标注
  sync 两端点现须 `X-WB-Key`；模块表补 `routes_rtc.py`；新增「Stage B（自动化 WebRTC）」小节。
- `FEATURES.md`：§十三 新增「自动化 WebRTC 静默同步（Stage B）」一行。
- `docs/specs/2026-09-03-lan-silent-sync-design.md`：§6 Stage B 勾选已落地，注明实现要点与范围偏差。

**注**：全量 pytest 未跑（本环境全量会触发 safe-delete 守卫、需用户批准），按定向子集 + 探针覆盖，
与 Stage A 收尾做法一致。

## 真机验证清单（APP 项待下次发版）

- [ ] 桌面 到 桌面浏览器：配对一次后刷新页面仍自动同步（无需重输码）
- [ ] 桌面 到 桌面浏览器：撤销配对后旧 key 立即 403，两端均需重新配对
- [ ] 桌面 到 Android APP：等下次发版（旧版 APK 未内嵌 Stage A+B 代码）
