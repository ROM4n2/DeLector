---
title: "ADR-0003: 局域网同步 SDP 传递采用 6 位短码"
created: 2026-08-29
updated: 2026-08-29
type: notes
tags:
  - category/project
  - topic/adr
  - project/delector
status: stable
audience: both
authority: synthetic
claim_risk: medium
review_status: unreviewed
---

# ADR-0003: 局域网同步 SDP 传递采用 6 位短码

## 1. 背景与问题陈述

DeLector 德语背词工作台的局域网同步基于 WebRTC P2P（`RTCPeerConnection` + `RTCDataChannel`），无需中央服务器存数据。但 WebRTC 建立连接前需要交换 SDP（Session Description Protocol）信令，原始实现要求用户在两台设备间复制粘贴 2-3KB 的 SDP 文本。在手机上操作尤其痛苦——选中长文本、跨设备粘贴极易出错。

v4.6.5 之前的方案：两端各有一个 textarea，A 生成 offer 后复制粘贴给 B，B 生成 answer 后再复制粘贴回 A。两次复制粘贴，每次 2-3KB 文本。

## 2. 决策考量因素

- **移动端体验**：手机是主要使用场景之一，操作步骤必须最少、输入量最小
- **实现成本**：不能引入 QR 扫描库或额外依赖，DeLector 是纯 FastAPI + 原生 JS 栈
- **安全**：SDP 含 IP 地址候选，不能长期留存，必须一次性消费 + 短 TTL
- **零行为变化**：WebRTC P2P 数据传输逻辑不变，只改信令传递方式
- **可用约束**：两端必须都能访问同一台 DeLector 服务端（局域网内同一台机器）

## 3. 决议方案

采用 **6 位短码中转**：服务端新增两个临时端点，A 端把 SDP POST 上去换一个 6 位大写字母数字码（如 `K7M2X9`），B 端输入这个码 GET 取出 SDP。answer 同理反向一次。全程 5 分钟 TTL，取一次即销毁。

| 端点 | 方法 | 作用 |
|---|---|---|
| `/api/wb/sync/store` | POST | 存 SDP，返回 6 位码 |
| `/api/wb/sync/fetch/{code}` | GET | 取 SDP（一次性，取后即删） |

实现细节：
- 短码用 `secrets.token_urlsafe(4)[:6].upper()` 生成，大小写不敏感输入
- 内存 dict 缓存，不落盘，每次调用清理过期条目（5 分钟 TTL）
- `_require_localhost` 守卫，仅限本机/局域网访问
- WebRTC P2P 数据通道逻辑完全不变，只改信令交换的 UI 和 API 调用

被拒绝的方案：
- **维持复制粘贴**：手机上操作成本太高，2-3KB 文本选中和粘贴极易出错
- **QR 码**：SDP 有 2-3KB，普通 QR 码（版本 10 约 2KB 数据容量）放不下，需要高版本 QR 码且手机摄像头远距离识别率差；还需引入 QR 生成 + 扫描库，增加依赖和包体积
- **服务端全权同步**：所有数据走服务端中转，失去 P2P 的隐私优势和大文件传输能力，服务端内存压力也增大
- **手动输入完整 SDP**：绝不可能，2-3KB 纯手动输入完全不现实

## 4. 积极后果与消极妥协

- **正面收益**：手机端只需输入 6 个字符，操作成本从"痛苦"降到"无感"；不引入任何新依赖；SDP 一次性消费 + 短 TTL，安全风险可控；WebRTC 逻辑零改动，风险低
- **妥协风险**：两端必须连同一台 DeLector 服务端（本来就是局域网同步的前提，无额外限制）；6 位码约 32^6 ≈ 10 亿种组合，暴力枚举理论上可行，但 5 分钟 TTL + 一次性消费 + 仅局域网可达，实际可忽略；短码生成用 `token_urlsafe` 截取 6 位，熵比纯 32 进制略高（base64-url 字符集），安全性充足
