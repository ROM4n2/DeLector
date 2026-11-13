# docs/reviews/ 评审与审计索引

> 本目录是 **DeLector 项目的架构审计、对照实验、缺陷排查与交付验收归宿**。
> 区别于 `docs/research/` 的可复用技术调研，本目录记录的是**阶段性一次性核验、实验基准、守卫逃逸留痕与验收账本**。
>
> 💡 **专项技术调研已独立建立资产目录：详见 [docs/research/](../research/README.md)**（含去 Emoji、外部 UI 实测参考库、动效生机、移动端布局、全站换皮等 12 份调研与原型）。

---

## 目录分层与速查总览

| 类别 | 职责范围 | 典型产物 |
|---|---|---|
| **一、架构巡检与代码审计** | 集群专家全量审计、仓库拓扑治理、提交纪律与单体解耦分析 | `*-swarm-audit-master.md` · `*-refactor-candidates.md` · `*-open-items-backlog.md` |
| **二、对照实验与评测基准** | 智能体循环收益、裁判对抗检测、Token 消耗与分布回测 | `*-control-experiment.md` · `*-pilot.md` · `*-backtest-report.md` |
| **三、缺陷排查与守卫逃逸复盘** | 语言学 NLP 标注异常、类型系统或静态门禁逃逸复盘 | `*-guard-escape.md` · `*-mislabeled-*.md` |
| **四、交付验收与收口总结** | 复杂批次（C 档、全站换皮等）完成后的正式验收与数据对账 | `*-delivery.md` · `*-closeout.md` · `*-verification.md` |
| **五、专项技术调研 (导引)** | 可复用设计经验、外部产品对标、交互动效与排版实测 | 详见 👉 **[docs/research/ 调研目录](../research/README.md)** |

---

## 一、 架构巡检与代码审计（Audits & Reviews）

聚焦于系统稳定性、分层依赖合规、安全漏洞与技术债务清查。

- [2026-09-28 Swarm Audit Master](2026-09-28-swarm-audit-master.md)
  - **内容**：首轮 6 席位集群全量审计；梳理 Docker 部署空库风险、WAL 机制、Android 契约守卫、i+1 词池打通等 6 项 P1。
- [2026-10-03 Swarm Audit Master](2026-10-03-swarm-audit-master.md)
  - **内容**：第二次 7 席位集群全量审计；揭露存量升级丢数据 (P0)、密钥外泄 (P0)、双排程冲突 (P0) 以及词表单一真相化路径。
- [2026-10-15 Swarm Audit Master](2026-10-15-swarm-audit-master.md)
  - **内容**：非在途面 5 席专家评估；输出 2 项 P0、5 项 P1、10 项 P2，奠定 A/B/C 三档未决项修复序列。
- [2026-10-15 Refactor Candidates](2026-10-15-refactor-candidates.md)
  - **内容**：单体巨石解耦候选清单；分析 `core/database.py`（2809 行）拆解切分轴与路由抽离前置契约。
- [2026-10-16 仓库结构与文档漂移审计](2026-10-16-repo-structure-and-docs-audit.md)
  - **内容**：排查根目录测试库残留、文档行数/测试用例虚增、版本面未同步等 4 项 P1 与 9 项 P2。
- [2026-10-16 提交节奏与 Git 分支管理审计](2026-10-16-commit-rhythm-and-git-management-audit.md)
  - **内容**：复盘直推 master 流程缺陷（25 个实现提交未走 PR）；提出并推动落地分支纪律机械闸 `check_master_commit_scope.py`。
- [2026-10-16 Open Items Backlog (未决项总台账)](2026-10-16-open-items-backlog.md)
  - **内容**：全仓唯一待办总账，追踪 A 档（P0/P1 修复）、B 档（工程规矩治理）、C 档（C1~C9 深度解耦与实验回灌）；当前已全量闭环交付。
- [2026-11-13 仓库整体健康度群体审计](2026-11-13-repo-health-swarm-audit.md)
  - **内容**：6 席位全量只读审计 + 2 席独立反证；56 条原始 finding 折叠为 20 条（4 条 CONFIRMED P1 / 1 条 PLAUSIBLE / 15 条 P2），覆盖数据安全、SW 缓存、交付链护栏、门禁自证与活文档漂移；配套实施计划 `docs/plans/2026-11-13-repo-health-remediation.md`。

---

## 二、 对照实验与评测基准（Experiments & Benchmarks）

通过物理证据验证假设，杜绝主观臆测与未经检验的模型行为。

- [2026-10-16 裁判对抗对照实验报告 (ADR-0024)](2026-10-16-judge-gaming-control-experiment.md) · [原始数据 JSON](2026-10-16-judge-gaming-control-experiment.raw.json)
  - **结论**：三臂配对（A1 基线 / A2 无方向 / A3 生产）60 局真跑，证明浅裁判未引起模型针对性利用（P1 奖励黑客无发生机制）。
- [2026-10-16 对照实验 Pilot 实测报告](2026-10-16-judge-gaming-pilot.md) · [原始数据 JSON](2026-10-16-judge-gaming-pilot.raw.json)
  - **结论**：主实验前置 N=5 小规模跑测，验证三臂采样管线与延迟基线。
- [2026-10-16 对照实验单篇试跑报告](2026-10-16-judge-gaming-trial-run.md) · [原始数据 JSON](2026-10-16-judge-gaming-trial-run.raw.json)
  - **结论**：首次全流程端到端连通性与 token 采集通道实测。
- [2026-10-17 真 Token 与轮次分布回测报告 (C3)](2026-10-17-c3-token-and-turn-backtest-report.md)
  - **结论**：基于 60 局真跑实测德语 A1 均值 1.50 chars/token，验证 `CHARS_PER_TOKEN_ESTIMATE = 3.0` 具备 100% 保守裕量，闭环 ADR-0023 Unknown B。

---

## 三、 缺陷排查与守卫逃逸复盘（Bug Investigations & Guard Escapes）

对逃逸至生产代码或测试用例未能捕获的隐蔽 Bug 做根因解剖与物理定性。

- [2026-10-20 rd-api 导出面守卫逃逸复现](2026-10-20-rd-api-export-guard-escape.md)
  - **根因**：静态测试仅断言「符号存在性」而未验证实际调用闭环，导致死别名未被拦截；立下「一次性缺陷复现留痕」先例。
- [2026-11-06 德语复数第四格误标主格排查复现](2026-11-06-german-plural-akkusativ-mislabeled-nominativ.md)
  - **根因**：spaCy `de_core_news_sm` 的 morphologizer 阶段将复数名词预标为 `Case=Nom`，parser 改 `dep=oa` 却不回写 Case，前端透传导致展示错标。推动落地 NP 词格仲裁机制。

---

## 四、 交付验收与收口总结（Delivery Verifications & Closeouts）

大型多任务里程碑交付后的正式收口凭据与全盘核验。

- [2026-10-17 C2 缺陷复测核验报告](2026-10-17-c2-verification.md)
  - **结论**：对 10-15 审计报告自报的 3 条 UNVERIFIED 缺陷逐一构造物理探针，确证成立与否，杜绝盲目改动。
- [2026-10-18 C8 P2 批次缺陷全量交付报告](2026-10-18-c8-delivery.md)
  - **结论**：7 项 CONFIRMED 缺陷闭环收工，附带交付静态扫描器 `tools/check_silent_degradation.py`。
- [2026-11-08 全站换皮 P2 五族收口总结报告](2026-11-08-full-site-visual-reskin-closeout.md)
  - **结论**：阅读器、词卡抽屉、卡盒闪卡、备考、设置、写作五大组件族视觉换皮全量对账，字面量与对比度闸门全绿。
- `2026-11-08-material-p3-images/`
  - **用途**：材质 P3 阶段全站截图与对照测试的静态图像存档。
- `2026-11-10-android-shell-s0-images/`
  - **用途**：安卓冷启静态壳 S0 的逐帧验收截图（`splash→壳` / `壳→应用` 两段），对应 `docs/plans/2026-11-10-android-local-shell.md` §8A。

---

## 五、 专项技术调研 (导引至 docs/research/)

技术调研属于跨模块、长期有效、可复用的设计经验与基准资产，已独立成专有资产目录：**[docs/research/ 调研目录](../research/README.md)**。

1. **前端排版与去字形**：去 Emoji 调研（第一轮/第二轮）、外部 UI 实测参考库（Raycast/Linear/Obsidian 等字阶与间距）；
2. **交互动效与伴学生机**：伴读桌宠气泡与避让、动效生机与 7 处白名单、卡盒「斩」中档触控反馈；
3. **界面布局重构**：备考页单列重构、播放器托盘断点字形、设置 IA 分段控件、移动端写作台 393px 布局；
4. **全站换皮与设计系统**：全站换皮调研与 CSS 量化、词卡抽屉复习状态 UI 调研；
5. **随附原型与代码模板**：去 Emoji vs 排版层级独立对比原型、动效模板样式与辅助函数。
