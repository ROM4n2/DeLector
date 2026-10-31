---
title: "ADR-0004: 局域网静默同步 Stage B —— 自动化 WebRTC + 持久配对凭证"
created: 2026-09-03
updated: 2026-09-03
type: project
tags:
  - category/project
  - topic/adr
  - topic/architecture
  - topic/lan-sync
status: active
audience: both
authority: synthetic
claim_risk: medium
review_status: unreviewed
---

# ADR-0004: 局域网静默同步 Stage B —— 自动化 WebRTC + 持久配对凭证

> 关联：设计稿 `docs/specs/2026-09-03-lan-silent-sync-design.md`（§3.6 路线 B / §6 实施分期）；
> Stage A 实施计划与 ledger：`docs/plans/2026-09-03-lan-silent-sync-stage-a(-ledger).md`；
> 前置 ADR：`0003-lan-sync-short-code`（F5 6 位短码 P2P）。
> 本 ADR 为「写 plan 前的范围/架构锁定」，不替代后续 TDD 任务拆分。

## 1. Context and Problem Statement

Stage A 已落地「配对密钥 + HTTP 轮询」镜像同步：手机浏览器 / APP（次发版后）每 5s 带
`X-WB-Key` 静默 `GET/PUT /api/wb/state` 双向对账，复用 `applyMerge(...,{silent:true})`。
它解决了「跨设备进度可见」，但仍有两块未满足：

- **明文 HTTP**：同 Wi-Fi 可嗅探镜像内容（密钥防伪造不防窃听）。
- **手动/半自动**：每次会话仍需配对；重连需重新走流程；APP WebView 跨域 fetch 桌面 IP
  依赖服务端 CORS 中间件反射，且依赖轮询拉取，不是「随时静默」。

目标路线 B 是设计稿确认的方向：用 **WebRTC DataChannel** 把「配对一次」升级为
「持久化凭证 + 自动建连/重连 + 加密双向传输」，让同步真正无感。

本 ADR 须确定：B 的信任模型、与 Stage A 的关系（是否并存/替换）、信令如何鉴权、
凭证生命周期，以及测试可达性边界。

## 2. Decision Drivers

- **隐私**：镜像含学习进度，同 Wi-Fi 明文可被嗅探，需传输层加密（DTLS）。
- **免 CORS 坑**：数据通道不受浏览器同源策略限制，APP WebView（Chromium）原生支持 WebRTC。
- **无感体验**：配对一次后断网/休眠/切换网络能自动重建，不弹阻断式提示。
- **最小改动 / 复用**：合并权威 `applyMerge`、差分 `wbsync.pull`、信令 `routes_sync.py` 均已有，不得重写。
- **单用户约束**：无账号体系、无公网、无多租户；newer-wins 足够，不引入 CRDT。
- **可测性现实**：本环境无真机/双浏览器跑 WebRTC 的能力，E2E 只能靠桩模拟 DataChannel + 真机手动验证；设计不得依赖「能自动化 E2E」才能交付。

## 3. Considered Options

- **Option 1：仅把 Stage A 的密钥持久化 + 自动重连轮询（不引入 WebRTC）**
  - 👍 Pros：改动最小，完全复用现有 HTTP 端点与 `applyMerge`；本环境可单元/集成测试；APP 只需新版 APK 即可用。
  - 👎 Cons：明文 HTTP 嗅探风险未解；仍受 CORS/轮询节奏限制；没达到「加密 + 真无感」目标，路线 B 名不副实。

- **Option 2：自动化 WebRTC DataChannel（持久配对凭证 + 自动建连/重连）** ✅ 选定
  - 👍 Pros：DTLS 默认加密（防同 Wi-Fi 嗅探）；数据通道不受 CORS 限制；APP WebView 原生支持；
    凭证缓存后自动重连，用户零操作；与设计稿目标路线 B 一致。
  - 👎 Cons：实现/调试复杂度高；本环境无法真跑 E2E（靠桩 + 真机手动验证兜底）；
    APP 端须等下次发版内嵌新代码；信令端点需补 `X-WB-Key` 鉴权。

- **Option 3：保留 F5 6 位短码手动流程，不推进自动化**
  - 👍 Pros：现状已可用，零新增风险。
  - 👎 Cons：与「随时静默」用户价值相悖；Stage A 已证明手动短码是摩擦点，不解决根因。

## 4. Decision Outcome

Chosen option: **Option 2（自动化 WebRTC + 持久配对凭证）**，因为隐私（DTLS 加密）与无感体验
（自动重连、APP 原生支持）是 Stage A 明确未覆盖且用户价值最高的两块，且可完全复用既有
`applyMerge` / `wbsync.pull` / `routes_sync.py` 信令，不重写合并逻辑。

配套架构约定（锁定范围）：
- **信任模型不变**：`GET /api/wb/state` 仍对局域网开放（拉取免 key）；`PUT /api/wb/state` 仍须
  `X-WB-Key`；`GET /api/wb/state/key` 仍仅本机 127.0.0.1。
- **信令端点补鉴权**：`POST /api/wb/sync/store`、`GET /api/wb/sync/fetch/{code}` 加 `X-WB-Key`
  （替代原 `_require_localhost`，因信令需在 LAN 上中继 SDP）；保留 `routes_sync.py` 已有的
  `test_sync_sdp_lan_accessible` 守护，并新增「缺 key → 403」测试。
- **持久配对凭证**：生成 `secrets.token_hex(32)` 存 `app_settings`（与 Stage A 的 `get_wb_sync_key`
  同一来源，避免双密钥），支持「撤销/重新生成」使旧密钥即时失效；凭证缓存于两端，建连无需重新输码。
- **传输**：WebRTC DataChannel 收发 `SyncEnvelope`（`snapshot()` 同构信封）；ICE 断线后凭缓存
  凭证重建通道，无需重新配对。
- **Stage A HTTP 轮询保留为兜底通道**：WebRTC 不可达（如企业网禁 UDP/ICE）时回退 Stage A 的
  5s 轮询，保证「至少可达」；两条通道不并行写，以 WebRTC 优先、轮询兜底。
- **合并权威唯一**：所有到达的 `SyncEnvelope` 一律 `applyMerge(envelope,{silent:true})`，不新写合并逻辑。

## 5. Consequences and Trade-offs

- 🟢 **Positive**：
  - 传输层 DTLS 加密，同 Wi-Fi 抓包不可读内容（解决 Stage A 明文局限）。
  - 数据通道无 CORS 约束，APP WebView 直连更稳；自动重连带来真正无感同步。
  - 完全复用 `applyMerge` / `wbsync` 差分 / `routes_sync` 信令，改动面可控。

- 🔴 **Negative / 缓解**：
  - 实现与调试复杂；本环境无法真跑 WebRTC E2E。
    → 缓解：信令/凭证/建连流程以 node:vm 行为探针 + 变异验证钉契约；DataChannel 收发用测试桩
    模拟两端；真机（双浏览器 + Android APP 次发版后）手动验证兜底（同 Stage A ledger 做法）。
  - APP 路径须等下次发版内嵌 Stage A+B 代码才能验证。
    → 缓解：M1–M4 先在桌面端推进与单测；APP 项挂到发版后，沿用 Stage A 已建立的「待新版验证」状态。
  - 密钥撤销/轮换需端上清理配对状态，否则可能卡死在旧密钥。
    → 缓解：「撤销配对 / 重新生成密钥」端点使旧 key 即时 403，前端清 `wb.pair.v1` 并重置连接。

- 🛡️ **Compliance Guardrail**：
  - 密钥/凭证仅落 `app_settings` + localStorage，**绝不进 Git**（pre-commit 密钥扫描 + 本地存储）。
  - 端点仅绑 LAN 接口、拒绝非 RFC1918 源；密钥错误即 403（沿用 Stage A 已实现）。
  - 合并仍走唯一权威 `applyMerge(silent)`；新增测试必须含「退回旧实现必红」的变异验证（继承
    `tools/wb_pair_push_probe.mjs` 等探针范式）。
  - 信令改动不得破坏 Stage A：`/api/wb/sync/info` 仍开放、wb CORS 反射不变，回归 `test_server`
    的 wb/cors 组 + `test_german_workbench` + `test_frontend_module_graph`。

## 里程碑（供后续 plan 拆分，非正式承诺）

- **M1 信令鉴权**：`/store`+`/fetch` 加 `X-WB-Key`；回归 Stage A 行为。
- **M2 持久配对凭证**：生成/存储/撤销；前端从「每次输短码」切到「配对一次」。
- **M3 WebRTC 建连**：offer→answer→ICE→DataChannel open；复用现有 SDP 中转（TTL/一次性消费）。
- **M4 自动重连 + 静默对账**：断线重建、去抖、复用 `applyMerge`。
- **M5 真机验证**：桌面↔桌面浏览器（可先于 APP）；桌面↔Android APP（等下次发版新 APK）。
- **回退**：WebRTC 不可达时自动降级 Stage A HTTP 轮询。
