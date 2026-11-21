---
title: "ADR-0026: 多页面 Agent 来源契约（view / contextSource / scopeKey）"
created: 2026-11-03
updated: 2026-11-03
type: project
tags:
  - project/delector
  - category/project
  - topic/architecture
  - topic/agent
  - topic/context-contract
status: accepted
audience:
  - architect
deciders: 用户
supersedes: none
related: [08-Projects/DeLector/01-ADR/0025-companion-study-agent-viewport-context-and-floating-capsule.md, 01-Rules/AGENT-CONTEXT-STANDARDS.md, 08-Projects/DeLector/DELECTOR-DEV-RULES.md]
verified: 2026-11-03
description: "当 Agent 从单页扩展到多页面/多视图时读此条：没有来源契约，跨页就会把上一页的残留状态当成当前上下文。"
---

# ADR-0026：多页面 Agent 来源契约

> 来源：`99-Inbox/2026-11-03-多页面-agent-必须先有来源契约-view-contextSource-scopeKey.md` | 晋升日期：2026-11-03

## Status

已接受（2026-11-03）。验证证据：全量 pytest + 前端探针，含非阅读器不泄漏旧句的行为断言。

## Context

多页面 Agent 的每一次请求都必须携带 `view`（当前页面）、`contextSource`（上下文从哪来）、`scopeKey`（会话归属哪个作用域）。三者缺一个，后端与前端都无法区分「实时选区 / 页面残留状态 / 其它页面内容」，跨页串味只是时间问题。

适用场景：

- Agent 从阅读器扩到卡盒、写作台、进度页等多个视图。
- 需要按页面或按文章隔离会话，或页面间切换后还要接得上原会话。

触发信号：

- 用户在 A 页选中过内容，切到 B 页后 Agent 仍能引用到 A 页的句子。
- 切换器只查当前 scope，用户以为历史会话「丢了」。

## Decision

1. **上下文采集只认当前 view**：实时选区（live-selection）各页通用；页面状态（reader-state / writer-draft / card-current）只允许属于该 view 的来源。非本 view 的残留字段一律返回空。
2. **scopeKey 单一判据**：阅读器用 `article:<id>`，其它页面用 `view:<name>`；取/建会话、列会话、恢复会话都走同一判据。
3. **切页清理两写**：清空 activeContext，同时丢弃旧会话指针，让后端按新 scope 取/建。
4. **缺省降级而非编造**：无可用上下文时快捷入口隐藏或给出明确提示，不让模型凭空补上下文。
5. **历史入口与恢复分离**：全局历史可以分组展示，但跨 scope 选中时必须重置当前上下文并显式提示，历史文本不等于当前语境。

## Consequences

必须防范以下退化：

- 只带 `view` 不带 `contextSource`：知道在卡盒，却分不清是刚选的词还是上一篇的句子。
- 只带 `scopeKey` 不做切页清理：新页面仍抱着旧 scope 的会话与旧上下文。
- 把「会话还在」当「上下文还在」：数据没丢，但语义已经错了。

验收判据：

- 探针驱动真实源码：A 页有残留句子时切到 B 页，断言 `selectedText` 为空、`contextSource='none'`、文章元数据不跟随。
- 同 view 连续请求命中同一 scope；不同 view 不共享会话；切回原 view 后原 session id 与消息数不变。
- 跨 scope 选中历史后，断言上下文被重置且出现显式提示，而不是静默沿用旧句。

视口单页上下文的上游决策见 [[08-Projects/DeLector/01-ADR/0025-companion-study-agent-viewport-context-and-floating-capsule]]；本 ADR 扩展的是跨页面来源与作用域，不取代其选区还原文本算法。
