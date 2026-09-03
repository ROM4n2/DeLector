# 局域网随时静默同步设计（含手机 APP）

> **状态**：设计稿 v1（已通过双透镜权衡，用户确认方向：B 为目标、A 作阶段性验证）。**Stage A 已落地 2026-09-03**（镜像配对 HTTP 版本，见 §6 勾选与 `docs/plans/2026-09-03-lan-silent-sync-stage-a.md` + `-ledger.md`）；Stage B（WebRTC 自动化）待 A 真机验证通过后单独立项。
> **关联**：`docs/plans/workbench-progress-server-sync.md`（F3 浏览器镜像，已落地）、`08-Projects/_template/01-ADR/0003-lan-sync-short-code.md`（F5 WebRTC 短码）、`GIT-CONVENTIONS.md`（Zero-Leakage）
> **范围**：单用户、无账号体系、局域网内多设备（桌面 server + 手机浏览器 + 手机 APP）背词进度自动静默同步。
> **不在此范围**：公网同步、多用户/多租户、云端账户、冲突自由合并 CRDT（单人 newer-wins 足够）。

---

## 0. 结论摘要

- **可行性**：可行。两条路线均基于标准库 + 现有代码实现。
- **目标路线 B**：自动化 WebRTC 数据通道。把 F5 手动 6 位短码换成**持久化配对凭证**，配对后两端在同一局域网自动建连、静默双向同步。优势：DTLS 默认加密（防嗅探）、数据通道不受 CORS 限制、APP WebView（Chromium）原生支持 WebRTC。
- **阶段性验证 A**：在已落地的 F3 镜像上扩展。用**配对密钥**替换 `localhost` 门，手机（浏览器或 APP 原生层）带密钥静默轮询 `GET` / 带 `X-WB-Key` 推送 `PUT`。复用 `wbsync` + `applyMerge`，改动最小，用于先验证「静默双向」再推进 B。
- **核心改造只有一件**：把 `_require_localhost` 门换成「配对密钥」门，并让桌面 server 暴露配对后的局域网同步端点（+ CORS）。

---

## 1. 问题陈述与用户价值

**Why**：用户在桌面与手机间轮替学习德语，期望任一端背的词、做的复习、错的题，在另一端打开即可见、且无需手动操作。现状痛点：

- 桌面浏览器 ↔ 桌面 server 的 F3 镜像已修通；但**手机浏览器/APP 看不到进度**（根因：`/api/wb/state/key` 被 `_require_localhost` 限制，远端设备永远 403 → 推送被禁、且旧逻辑会把 `_enabled` 整体关掉）。
- 现有 F5 WebRTC 短码能传，但**每次都要手动输 6 位码**，不是「随时静默」。
- 手机 **APP 是独立实例**（`MainActivity.java` 用 Chaquopy 在手机本地 `127.0.0.1:8000` 起完整服务 + 自带 `delector.db/progress.db`），不是桌面瘦客户端。因此「APP 同步」本质是**两台 server（桌面 + 手机）对等同步**，不是「手机拉桌面镜像」。

**目标场景**：用户在地铁用手机 APP 背了 20 个词；回家打开桌面浏览器（或反过来），进度已在、无需任何操作。

**用户价值**：跨设备无缝续接，零手动同步成本；不牺牲单设备离线可用性（本地优先不变）。

---

## 2. 用户旅程与核心流程

**一次性配对（≤3 步）**
1. 桌面端「局域网同步」面板点「生成配对码/二维码」→ 展示 `delector://pair?host=<lan-ip>&port=8000&token=<secret>`。
2. 手机端（浏览器或 APP 内「配对」入口）扫码或输入配对 token。
3. 两端各自本地持久化配对密钥 → 配对完成（仅此一次）。

**之后（静默、零操作）**
- 两端检测到处于同一局域网且已配对 → 自动建立同步通道。
- 任一端进度变化 → 去抖后自动推送给对端 / 或对端周期拉取 → `applyMerge` 合并 → 本地落盘 + UI 刷新（静默，不打断当前视图）。
- 用户无感知；离线时各自本地累积，重新联网自动对账。

**摩擦点**：局域网发现（桌面 IP 变动 / 企业网拦 mDNS）、首次配对引导、离线双向编辑后的字段级冲突（newer-wins 已覆盖单人场景）。

---

## 3. 架构与数据模型

### 3.1 现状事实（已核实）

| 项 | 事实 | 来源 |
|---|---|---|
| 手机 APP 网络模型 | 独立 Flask 实例 + WebView 加载自身 `127.0.0.1:8000`；自带 DB | `android/.../MainActivity.java:394` |
| APP 联网权限 | `INTERNET` + `usesCleartextTraffic=true` | `AndroidManifest.xml:4,20` |
| APP WebRTC | Chromium WebView 原生支持 `RTCPeerConnection` | 已知 |
| 端点网关 | `GET /api/wb/state` 对局域网开放无需 key；`PUT /api/wb/state`、`/api/wb/state/key`、`/api/wb/sync/*` 全部 `_require_localhost` | `server.py:1428-1443`、本文件核实 `routes_sync.py` |
| CORS | 服务端**无** CORS 中间件 → APP WebView（localhost 源）跨域 fetch 桌面 IP 被浏览器拦截 | `server.py` 全文 grep |
| 合并权威 | `applyMerge(data)`：卡片按 `last` 取新、日志按字段 `max`、错题本按次数、单词 `customWords‖words` 按 `up` 取新（双索引去重） | `workbench.html:3459` |
| 快照信封 | `snapshot()` = `{words,cards,log,wrong,settings}`；推送包成 `{payload: snapshot()}` | `workbench.html:1087,1097` |
| 现有测试夹具 | `test_server.py` 有 `client`(127.0.0.1) 与 `lan_client`(192.168.1.77) 两 fixture | `docs/plans/...` §0 |

### 3.2 统一同步信封（A、B 共用契约）

```
SyncEnvelope = {
  words:    Word[]            // 含内建核心词 + 自定义词（customWords 为历史别名，applyMerge 兼容）
  cards:    { [id]: Card }    // FSRS-6 每词状态 {s,d,due,last,reps,lapses,...}
  log:      { [date]: Counts }// {rv,good,hard,again,nw,qz,qzOk}
  wrong:    { [id]: {n,t,m} }
  settings: { retention,dailyNew,newOrder,planDate,theme,tts }
}
```
- `applyMerge(envelope, {silent:true})` 为唯一合并权威，A/B 均复用，**不新写合并逻辑**。
- `wbsync.pull()` 的 `stable()` 差分 + 静默合并逻辑复用。

### 3.3 配对模型（替换 localhost 门）

- 桌面生成 **配对密钥** `LAN_PAIR_SECRET`：`secrets.token_hex(32)`，存本地 `app_settings`（`set_setting("lan_pair_secret", ...)`）——**绝不进 Git**（Zero-Leakage）。
- 配对 token 经**带外**交换（二维码/一次性短码），不落盘、不出现在同步载荷。
- 配对后：
  - **写端点** `PUT /api/wb/state`：鉴权头 `X-WB-Key: <LAN_PAIR_SECRET>`；错/缺 → 403。
  - **信令端点** `POST /api/wb/sync/store`、`GET /api/wb/sync/fetch/{code}`：加 `X-WB-Key` 鉴权（替代原 `_require_localhost`，因信令需在 LAN 上中继 SDP）。
  - **读端点** `GET /api/wb/state`：仍对局域网开放（仅拉取不需 key，保持单设备离线可读），但写入必须密钥。
- 设备白名单（可选加固）：`app_settings` 存已配对设备指纹集合，仅列表内设备的中继/写入被接受。

### 3.4 端点表（目标态）

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/api/wb/state` | 开放（LAN） | 拉镜像，无需 key |
| PUT | `/api/wb/state` | `X-WB-Key` | 推镜像；body `{payload: SyncEnvelope}` |
| GET | `/api/wb/state/key` | 移除 localhost 限制 → 改为 `X-WB-Key` 或保留本机快捷 | 弃用/改配对 |
| GET | `/api/wb/lan-info` | 开放（LAN） | 返回 `{lan_ip, port, paired, instance_id}` 供二维码 |
| POST | `/api/wb/sync/store` | `X-WB-Key` | 存 SDP（B 路线信令） |
| GET | `/api/wb/sync/fetch/{code}` | `X-WB-Key` | 取 SDP |
| GET | `/api/wb/sync/info` | 开放 | 实例指纹（已有，`routes_sync.py:44`） |

> CORS：桌面 server 为上述端点增加 `Access-Control-Allow-Origin` 白名单（仅已配对设备 origin / 或 `*` 仅限 LAN 源）。这是 B 路线（及 A 的 APP WebView 直连）绕过浏览器跨域拦截的关键。

### 3.5 路线 A（阶段性验证）数据流

```
手机(浏览器/APP原生层)                   桌面 server
   │ 配对一次：存 LAN_PAIR_SECRET            │
   │ ─── GET /api/wb/lan-info ───────────► │ 返回 lan_ip/port
   │ ◄─────────────────────────────────────│
   │ 每 5s（去抖）：                         │
   │ ─── GET /api/wb/state ──────────────► │ 开放，返回对端信封
   │ ◄── SyncEnvelope ─────────────────────│
   │ applyMerge(remote,{silent})           │
   │ 本地变化：                             │
   │ ─── PUT /api/wb/state ──────────────► │ X-WB-Key 校验 → 存 payload
   │   {payload: snapshot()}               │
```
- APP 走**原生层**（`HttpURLConnection`，无 CORS）或依赖桌面加 CORS 后 WebView fetch。
- 明文 HTTP：同 Wi-Fi 可嗅探内容；密钥鉴权防伪造不防窃听（已知局限，B 解决）。

### 3.6 路线 B（目标）数据流

```
桌面                                    手机 APP/浏览器
 │ 配对一次（同 A）                         │
 │ 检测到同 LAN + 已配对：                  │
 │ ◄── POST /api/wb/sync/store (offer) ── │ 带 X-WB-Key
 │ 取 code，回显                           │
 │ ──────────────────────────────────────►│ GET /sync/fetch/{code} 取 offer
 │                                        │ setRemoteDescription → createAnswer
 │ ◄── POST /sync/store (answer) ──────── │ 带 X-WB-Key
 │ GET /sync/fetch/{code} 取 answer       │
 │ setRemoteDescription → DataChannel open│
 │ ◄══ DTLS 加密 DataChannel（双向）═════► │ applyMerge 静默合并
 │ 任一端变化 → 去抖 → 经 DataChannel 发 SyncEnvelope │
```
- 信令复用现有 `routes_sync.py`（仅加 `X-WB-Key` 鉴权 + CORS）。
- 数据通道自动重连：ICE 断线后检测到对端可达即重建（配对凭证已缓存，无需重新输码）。
- APP WebView 内 WebRTC 直连，天然规避 CORS。

---

## 4. 边界与韧性

- **局域网发现失败**（桌面 IP 变动 / 企业网拦 mDNS）：回退到手动输入 `host:port` 或重新扫二维码；不阻断本地学习。
- **桌面离线/休眠**：同步暂停，两端各自本地累积（`localStorage`/IDB/APP 自身 DB 不变），重连自动对账。
- **APP 后台限流**：Android/iOS 节流后台网络。「随时静默」在 APP 前台可靠；后台用 `WorkManager` 周期任务做 best-effort 同步（耗电权衡，提供开关）。APP 自身 localhost server 仅 APP 打开时在跑——这是「APP 作对端」的固有前提。
- **离线双向编辑冲突**：`applyMerge` 字段级 newer-wins（卡片 `last`、日志 `max`、错题 `n`、单词 `up`）对单人足够；不引入 CRDT（避免过度设计）。
- **密钥泄露**：配对密钥等同「同处一个 Wi-Fi」的信任。提供「撤销配对 / 重新生成密钥」使旧密钥即时失效。端点仅绑 LAN 接口、拒绝非 RFC1918 源，密钥错误即 403。
- **跨实例「断码」警告**（`99-Inbox/2026-09-02-...`）：SDP 短码**不落盘、不引入共享后端**，保持「局域网 P2P」语义，避免多实例一致性风险。
- **CORS 误配**：白名单过宽（`*`）仅限 LAN 源；正式实现用已配对 origin 列表，非 `*`。

---

## 5. 测试策略

复用 `test_server.py` 的 `client`(本机) 与 `lan_client`(192.168.1.77 模拟局域网) 两 fixture。

**单元（现有 `applyMerge` 回归）**
- 卡片按 `last` 取新；日志字段 `max`；错题按 `n`；单词双索引去重 + `up` 取新、身份字段不污染。

**集成 — 路线 A**
- `lan_client` 配对后 `PUT /api/wb/state` 带 `X-WB-Key` → 200 且 `GET` 返回一致 payload。
- `lan_client` **未带/错带** `X-WB-Key` → 403。
- `lan_client` `GET /api/wb/state` 无需 key 可拉（保持只读开放）。
- 非 RFC1918 源（伪造 `X-Forwarded-For` 不在范围内）→ 拒绝（接口绑定校验）。
- `stable()` 差分：无差异时不触发 `applyMerge`、不打断视图（防反复空合并）。

**集成 — 路线 B**
- `lan_client` 持 `X-WB-Key` 完成 `store`→`fetch` 信令往返；缺密钥 → 403。
- CORS 预检：配对 origin 的 `OPTIONS` 预检通过；非白名单 origin 被拦。
- WebRTC 自动建连 + 静默 `applyMerge`：用测试桩模拟两端 DataChannel，验证信封收发与合并（端到端可在 CI 外用真机/双浏览器手动验证）。
- 重连：ICE 断线后重建通道，无需重新配对。

**安全**
- 同 Wi-Fi 嗅探（B）：DTLS 加密，抓包不可读内容。
- 密钥管理：不出现在任何同步载荷、不进 Git（pre-commit 扫描 + 本地 `app_settings` 存储）。
- 撤销配对：重新生成密钥后旧密钥 403。

---

## 6. 实施分期（落地顺序）

1. **Stage A（MVP）**：配对密钥生成/存储 + `X-WB-Key` 鉴权改造 `PUT /api/wb/state` 与信令端点 + 桌面 CORS + `lan-info` 端点 + 手机浏览器/APP 原生层轮询。验证「静默双向」。 **[x] 已落地 2026-09-03**（范围按实施计划微调：`PUT` 改 `X-WB-Key`、`GET` 仍局域网开放；`GET /api/wb/state/key` 保留 `_require_localhost` 本机快捷；CORS 覆盖 `/api/wb/state`、`/api/wb/state/key`、`/api/wb/sync/*`；配对 UI 宿主/远端二态）。信令端点的 `X-WB-Key` 鉴权归入 Stage B 一并落地。
2. **Stage B（目标）**：在 A 的配对之上自动化 WebRTC（缓存凭证、自动建连/重连、DataChannel 收发信封）。达成「加密 + 静默 + 含 APP」。
3. 每 Stage 独立 TDD（RED→GREEN→commit），不跨 Stage 合并。

---

## 7. 自检（Self-Review）

- [x] 无 TODO/TBD 占位：所有端点、契约、测试均给出具体形态。
- [x] 无自相矛盾：A 明文局限与 B DTLS 加密的边界已明确区分；`localhost` 门统一改为 `X-WB-Key` 门，未保留双重语义。
- [x] 无范围蔓延：不含公网/多租户/CRDT，符合单人场景。
- [x] 复用而非重构：合并权威 `applyMerge`、差分 `wbsync.pull`、信令 `routes_sync.py` 均复用。
- [x] 安全对齐：Zero-Leakage（密钥不进 Git）、仅绑 LAN、设备白名单、撤销机制齐备。
