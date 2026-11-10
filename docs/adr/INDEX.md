# ADR 状态索引

> 本索引只反映**仓内副本**的状态，正式件在 Vault（`08-Projects/DeLector/01-ADR/`）。
> 状态词表固定为四态：`Proposed` / `Accepted` / `Superseded by ADR-00XX` / `Deprecated`。
> 原文写成 `stable` / `active` / `draft` / `ACCEPTED` 等变体的，本表**归一为四态**，并在「原写法」列保留原文，不修改 ADR 正文。
> 新增 / 取代 / 废弃 ADR 时，同一 PR 更新本表（ADR-0029 §12.2 规则 3）。

| 编号 | 标题 | 状态 | 原写法 | 取代/被取代 | 日期 | 文件 |
|---|---|---|---|---|---|---|
| ADR-0001 | Workbench 核心词模式（Core Words Mode） | Accepted | stable | — | 2026-08-31 | [2026-08-31-adr-0001-workbench-core-words-mode.md](2026-08-31-adr-0001-workbench-core-words-mode.md) |
| ADR-0002 | Workbench 范围切换控件前置与设置即时生效 | Accepted | stable | — | 2026-09-01 | [2026-09-01-adr-0002-workbench-scope-control-and-live-settings.md](2026-09-01-adr-0002-workbench-scope-control-and-live-settings.md) |
| ADR-0003 | 局域网同步 SDP 传递采用 6 位短码 | Accepted | stable | — | 2026-08-29 | [2026-08-29-adr-0003-lan-sync-short-code.md](2026-08-29-adr-0003-lan-sync-short-code.md) |
| ADR-0004 | 局域网静默同步 Stage B——自动化 WebRTC + 持久配对凭证 | Accepted | active | — | 2026-09-03 | [2026-09-03-adr-0004-lan-sync-webrtc-stage-b.md](2026-09-03-adr-0004-lan-sync-webrtc-stage-b.md) |
| ADR-0005 | 导航重布局与多等级可扩展（备考域 + 渐进泛化） | Proposed | draft | — | 2026-09-04 | [2026-09-04-adr-0005-navigation-exam-domain-and-level-scalability.md](2026-09-04-adr-0005-navigation-exam-domain-and-level-scalability.md) |
| ADR-0006 | 背词工作台实体学术卡片箱（Zettelkasten）与心流优先重塑 | Accepted | accepted | — | 2026-09-04 | [2026-09-04-adr-0006-workbench-zettelkasten-editorial-redesign.md](2026-09-04-adr-0006-workbench-zettelkasten-editorial-redesign.md) |
| ADR-0007 | 精读句法拓扑行内幽灵微胶囊主动触发与心流保护架构 | Accepted | Accepted | — | 2026-09-05 | [2026-09-05-adr-0007-reader-syntax-ghost-pill-explicit-trigger.md](2026-09-05-adr-0007-reader-syntax-ghost-pill-explicit-trigger.md) |
| ADR-0008 | Go Agent Runtime + Python NLP Engine 混合架构 | Accepted | Accepted | 边界由 ADR-0018 / ADR-0021 澄清，未推翻 | 2026-09-06 | [2026-09-06-adr-0008-go-agent-runtime-architecture.md](2026-09-06-adr-0008-go-agent-runtime-architecture.md) |
| ADR-0009 | Python 包内重构落点的 Deletion Test 修正与 Agent 工具契约语义 | Accepted | stable | — | 2026-09-06 | [2026-09-06-adr-0009-python-package-restructure-deletion-test-and-tool-contract.md](2026-09-06-adr-0009-python-package-restructure-deletion-test-and-tool-contract.md) |
| ADR-0010 | 遇见区 i+1 阅读桥——分层架构，Go Agent 批量内容生产引擎 | Accepted | stable | — | 2026-09-07 | [2026-09-07-adr-0010-encounter-zone-layered-go-agent-producer.md](2026-09-07-adr-0010-encounter-zone-layered-go-agent-producer.md) |
| ADR-0011 | 词库单一真相化与等级判定数据驱动 | Accepted | stable | — | 2026-09-15 | [2026-09-15-adr-0011-workbench-vocab-single-source-and-scope-predicate.md](2026-09-15-adr-0011-workbench-vocab-single-source-and-scope-predicate.md) |
| ADR-0012 | 词汇主干分层与来源优先级 | Accepted | stable | — | 2026-09-15 | [2026-09-15-adr-0012-vocabulary-backbone-and-source-priority.md](2026-09-15-adr-0012-vocabulary-backbone-and-source-priority.md) |
| ADR-0013 | 词汇富字段输出契约扩展（A2/B1 音标与例句下发） | Accepted | stable | — | 2026-09-16 | [2026-09-16-adr-0013-rich-vocab-fields-output-contract.md](2026-09-16-adr-0013-rich-vocab-fields-output-contract.md) |
| ADR-0014 | 词表存储边界与 A1 取数统一 | Accepted | stable | 边界由 ADR-0016 收窄 | 2026-09-16 | [2026-09-16-adr-0014-vocabulary-storage-boundary-and-a1-server-fetch.md](2026-09-16-adr-0014-vocabulary-storage-boundary-and-a1-server-fetch.md) |
| ADR-0015 | A1 富结构收敛——成员集 side-car + FRAGMENTS 单源 + 字段级优先级 | Accepted | active | — | 2026-09-21 | [2026-09-21-adr-0015-a1-rich-convergence-membership-sidecars-and-field-priority.md](2026-09-21-adr-0015-a1-rich-convergence-membership-sidecars-and-field-priority.md) |
| ADR-0016 | 统一词库（单一权威池）架构 | Accepted | Accepted | 收窄 ADR-0014 边界 | 2026-09-29 | [2026-09-29-adr-0016-unified-vocab-pool-architecture.md](2026-09-29-adr-0016-unified-vocab-pool-architecture.md) |
| ADR-0017 | Android 更新可见性（检查 + 提示，不做应用内安装） | Accepted | Accepted | — | 2026-10-08 | [2026-10-08-adr-0017-android-update-check-notifier.md](2026-10-08-adr-0017-android-update-check-notifier.md) |
| ADR-0018 | 性能前提先测量，Python 主体不换（热点下沉策略） | Accepted | Accepted | — | 2026-10-09 | [2026-10-09-adr-0018-performance-measurement-before-runtime-swap.md](2026-10-09-adr-0018-performance-measurement-before-runtime-swap.md) |
| ADR-0019 | Windows 桌面端——不换壳、不做安装包，先零代码验证 PWA 并把数据目录救出来 | Accepted | Accepted | Q1 外壳议题部分由 ADR-0020 承接；数据外置与手动更新入口仍有效 | 2026-10-10 | [2026-10-10-adr-0019-windows-desktop-pwa-first-and-data-dir-externalization.md](2026-10-10-adr-0019-windows-desktop-pwa-first-and-data-dir-externalization.md) |
| ADR-0020 | Windows 桌面壳——pywebview + 托盘，Python 仍是 HTTP 主体 | Accepted | Accepted | 承接 ADR-0019 的 Q1 | 2026-10-10 | [2026-10-10-adr-0020-windows-desktop-shell-pywebview.md](2026-10-10-adr-0020-windows-desktop-shell-pywebview.md) |
| ADR-0021 | 继续走 Python——语言选择以运行时/交付为判据 | Accepted | Accepted | — | 2026-10-10 | [2026-10-10-adr-0021-stay-on-python-language-choice-criteria.md](2026-10-10-adr-0021-stay-on-python-language-choice-criteria.md) |
| ADR-0022 | v5.17.0 发版门与搁置边界 | Accepted | 已决策并落地前置项 | 发版本身待执行 | 2026-10-11 | [2026-10-11-adr-0022-release-gate-v5.17.0.md](2026-10-11-adr-0022-release-gate-v5.17.0.md) |
| ADR-0023 | 交互层引入「验证驱动 agent 循环」 | Accepted | accepted | — | 2026-10-14 | [2026-10-14-adr-0023-interactive-layer-verification-driven-agent-loop.md](2026-10-14-adr-0023-interactive-layer-verification-driven-agent-loop.md) |
| ADR-0024 | 第 8 条对照实验的判决量与结论边界 | Accepted | 已接受 | — | 2026-10-16 | [2026-10-16-adr-0024-gaming-control-experiment-verdict-metric.md](2026-10-16-adr-0024-gaming-control-experiment-verdict-metric.md) |
| ADR-0025 | 伴学 Agent 演进为原生 Tool Calling 与真流式双通道架构 | Accepted | ACCEPTED | — | 2026-10-31 | [2026-10-31-adr-0025-companion-agent-native-tool-calling-and-streaming.md](2026-10-31-adr-0025-companion-agent-native-tool-calling-and-streaming.md) |
| ADR-0026 | 沉浸式学术精读排版重塑与 CEFR 词阶分级视觉降噪 | Accepted | ACCEPTED | — | 2026-11-01 | [2026-11-01-adr-0026-reader-immersive-editorial-continuous-flow-and-cefr-noise-reduction.md](2026-11-01-adr-0026-reader-immersive-editorial-continuous-flow-and-cefr-noise-reduction.md) |
| ADR-0027 | NLP 模型档位定案为 `de_core_news_sm` | Accepted | ACCEPTED | — | 2026-11-04 | [2026-11-04-adr-0027-nlp-model-sm-only.md](2026-11-04-adr-0027-nlp-model-sm-only.md) |
| ADR-0028 | Android 主分析路径使用 spaCy 惰性加载 | Accepted | ACCEPTED | 2026-11-06 修订加载时机（正文内留痕） | 2026-11-06 | [2026-11-06-adr-0028-android-main-path-spacy-lazy-load.md](2026-11-06-adr-0028-android-main-path-spacy-lazy-load.md) |
| ADR-0029 | 前端去 Emoji 与编辑节奏重构——分层替换、垂直切片先行 | Accepted | Accepted | 2026-11-07 追加 §16 落地与失效条款（T1–T9；3 条数值口径失效）；动效系统由 ADR-0030 补充 | 2026-11-06 | [2026-11-06-adr-0029-frontend-de-emoji-and-editorial-rhythm.md](2026-11-06-adr-0029-frontend-de-emoji-and-editorial-rhythm.md) |
| ADR-0030 | 前端动效系统——5 个 token、三件套类与 reduce 降级 | Accepted | Accepted | 补充 ADR-0029 §3.5 决策 5，不取代 | 2026-11-07 | [2026-11-07-adr-0030-frontend-motion-system.md](2026-11-07-adr-0030-frontend-motion-system.md) |
| ADR-0031 | Python import 迁移——削减启动期重依赖并保住红线 1 判定 | Deprecated | 未实施（判负） | 方案 A 双指标判负；由 ADR-0032 承接后续方向 | 2026-11-09 | [2026-11-09-adr-0031-python-import-migration.md](2026-11-09-adr-0031-python-import-migration.md) |
| ADR-0032 | 把 Python 撤出首屏关键路径——缓存优先、契约收敛，NLP 留在 Python | Accepted | Accepted | 承接 ADR-0018 / ADR-0021；ADR-0031 判负后的方向定案；2026-11-10 阶段一安卓侧落地（PR #330）：首帧 4053→1361.5ms，TTFD +196ms（x86_64 模拟器，真机未覆盖） | 2026-11-09 | [2026-11-09-adr-0032-python-off-first-screen-path.md](2026-11-09-adr-0032-python-off-first-screen-path.md) |
| ADR-0033 | 把 Python 从首屏关键路径上彻底拿掉——宿主原生静态承载 + 快照首屏、后端只做数据接管 | Proposed | — | 叠加 ADR-0032（不替代）；安卓 S1 测量切片已测（2026-11-10）：TTFD 中位 1065ms、M1 835.5ms、接管全自动 navCount=1；S2 同构建 A/B 正式判定（2026-11-10）：TTFD 3410.5→1034ms（改善 2385/2368ms，噪声下限 391ms）、接管中位 80.5ms 且 navCount=1；S1/S2 均未合并；桌面 B2 待基线测量 | 2026-11-10 | [2026-11-10-adr-0033-python-out-of-first-screen-completely.md](2026-11-10-adr-0033-python-out-of-first-screen-completely.md) |
