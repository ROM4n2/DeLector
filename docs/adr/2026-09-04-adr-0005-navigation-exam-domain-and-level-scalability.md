---
title: "ADR-0005: 导航重布局与多等级可扩展（备考域 + 渐进泛化）"
created: 2026-09-04
updated: 2026-09-04
type: project
tags:
  - project/delector
  - topic/adr
  - topic/architecture
  - topic/frontend
  - topic/navigation
status: draft
audience: both
authority: synthetic
claim_risk: medium
review_status: unreviewed
---

# ADR-0005: 导航重布局与多等级可扩展（备考域 + 渐进泛化）

## 1. Context and Problem Statement

DeLector 主前端 `static/index.html` 是单文件 SPA，全部 view 由同文件承载，主导航为 5 个「场景工具」入口（德语文库 / 每日台账 / 写作润色 / 复习卡片 / 德语背词），桌面顶栏（index.html:41-89）与移动 dock（:2647）均硬编码 `onclick show(...)`，非数据驱动。德语背词 = `static/german/workbench.html`（独立单文件应用：自有 CSS token、localStorage 数据、自带词表），经 iframe 嵌入 `view-german`（:2637）。

功能物理归属错乱（用户可感知的杂乱）：
- 歌德 A1 **写作**题宿主于「写作润色」`view-writer`（index:972-1123）——工具容器混入考纲素材；
- A1 **听力/阅读/口语问答**散于「复习卡片」`view-cards`（index:402-415）——复习工具混入考试题。

等级（A1）已硬编码为「前缀族」，未来 A2/B1 缺乏落位：
- 前端 `a1_cards/hoeren/lesen/writer.js`；服务端 `routes_a1*`、`a1_dict`；
- 成绩表 `a1_hoeren_records` / `a1_lesen_records`（database.py:94/105）及 record/get 历史/anki 导出函数均带 a1 前缀；
- 测试族 `test_goethe_a1*`。

按现状，准备 A2 意味着复制整套 a1_* 族并新建 `a2_*_records` 表——与「持久维护性」「逐个准备 A2、B1…」的长期目标冲突。

尚存的泛化面：`vocab_cards.cefr_level`、`articles/essays` 无等级绑定、FSRS/复习通道与 wb-sync（applyMerge）本与等级无关。

## 2. Decision Drivers

- **场景与考纲分离 (MUST)**：主导航是「此刻我要读/写/背」的场景工具，考纲素材（带等级维度的练习/考题）不得再塞入工具容器；工具视图回归纯工具语义。
- **新增等级收敛为增量 (MUST)**：准备 A2/B1 的成本应是「插数据 + 注册目录」，而不是复制一套 a1_* 代码族与成绩表。
- **不做一次性豪赌重构 (SHOULD)**：A1 判分/交互逻辑已成熟，逐步提取，避免一次重写引入回归面。
- **视觉统一与工程隔离并存 (SHOULD)**：背词工作台与主站的「风格割裂」必须消除，但保留其独立工程边界（iframe），不并入主站 SPA。
- **数据不双账本 (MUST)**：同一词/同一练习在背词工作台与主站之间不得出现两份独立进度；同步走既有权威通道。
- **导航可扩展 (SHOULD)**：导航（桌面 nav + 移动 dock）数据化，新等级/新模块不靠手改 HTML。

## 3. Considered Options

### Q1 主导航心智模型
- **A. 场景导航 + 独立「备考（Prüfung）」域**（采纳）：保留场景工具，新增备考顶层入口；A1 听说读写全部收拢域内；域内未来 A2/B1 选级。贴合现有工作流与既有 ADR-0001/0002 的「工具 + 词库等级」模式。
- B. 等级主导导航：顶部 A1/A2/B1，工具下沉为某级子项——扭曲不考试时的日常工具流。
- C. 打补丁（各场景内折叠 A1 内容）：保留碎片结构，与长远目标冲突。

### Q2 新等级扩展机制
- **A′. 渐进泛化**（采纳）：先泛化「目录 + 成绩」两层（新表带 `level` 列、考试路由参数化、题库 `{level}_{module}` 命名归位）；判分/内容组件按模块逐步提取（先听/读，写作判分成熟区暂缓）。
- A. 全量表驱动（一次迁移全部数据 + 重写组件）：面大、回归风险高，作为远期完成态而非首刀。
- B. 延续每级代码族：每级恒定复制成本，N 份交互逻辑长期膨胀。

### Q3 备考域内部形状
- **A. 等级页签在顶层、模块为等级页内入口**（采纳）：「备考」→ `A1|A2|B1…`（由 exam catalog 自动生成）→ 等级页内按模块排卡片。加级 = 目录插一行，导航零代码。贴合「A1→A2→B1 逐个准备」的备考旅程。
- B. 模块页签顶层 + 模块内等级选择器：各级题型不同构时产生空态页签；各模块都要维护等级态。
- C. 等级做成整站全局上下文：把等级重新注入场景工具，倒退回 Q1 要消除的混乱。

### Q4 背词工作台形态
- **C. 混合**（采纳）：保持 iframe 工程边界；主站抽共享设计 token 层供 workbench 引用以统一视觉；词表/进度数据走既有权威同步通道（wb-sync/applyMerge、ADR-0001 核心词联动），词表来源契约 = `vocab_cards.cefr_level` 过滤——工作台成为通用 A1/A2/B1 词库视图。
- A. iframe + 主题适配壳：仅父壳统一 header/容器排版，工作台内样式对齐不足、数据隔阂仍在。
- B. 并入主站 SPA：视觉/数据彻底同源，但背上「上游词库工具更新须手动 merge」的债（Vault `_template/ADR-0004-workbench-iframe-embedding` 草稿已论证过该选项的样式污染/维护成本）。

## 4. Decision Outcome

1. 主导航结构演进为「**场景工具 + 独立备考域**」两带：新增「备考（Prüfung）」顶层入口；A1 写作题迁出 `view-writer`、A1 听/读/口语问答迁出 `view-cards`，收拢进备考域。工具视图回归纯工具语义。
2. 备考域内部采用**等级页签在顶层**的组织：`A1 | A2 | B1 …`，页签由 exam catalog（见 3）自动生成，等级页内按考试模块（写作/听力/阅读/口语…）列出入口卡片。
3. 扩展机制采用**渐进泛化 A′**，实施分刀：
   - 第一刀（目录 + 成绩层）：引入泛化目录结构（`exam_sets`：level/module/title/配置；`exam_items`：题干数据）与泛化成绩表（`exam_trials`：level/module/set_id/score…，兼容收编 `a1_hoeren_records`/`a1_lesen_records` 旧行）；考试路由参数化为 `/api/exams/{level}/{module}/...`；题库数据/常量按 `{level}_{module}` 归位。
   - 后续刀（组件按模块提取）：先抽听力/阅读组件为 level 参数化组件，写作判分成熟区暂缓，逐步拆解 `a1_*` 前端族。
4. **导航数据化**（伴随决策）：桌面 nav 与移动 dock 收敛为单一 nav config 渲染；备考域的等级页签 = catalog 数据驱动。新等级/新模块不手改 HTML。
5. 背词工作台维持 **iframe 工程边界**；视觉统一走「主站抽取共享设计 token（`:root` 字体/色板/间距变量源）→ workbench 引用」的路子；词表与进度经既有同步通道对齐，**禁止** localStorage 与 server 双账本漂移；工作台词表来源契约 = `vocab_cards.cefr_level` 过滤（A1 即由此演进，A2 复用同工作台仅切词表等级）。
6. 命名契约：新写模块一律**不带等级前缀的泛化命名**；既有 `a1_*` 名在组件提取完成前保留，提取后废弃。`test_goethe_a1*` 保留；新等级测试走泛化 fixture。

## 5. Consequences

**正面**
- 新增等级成本从「复制 N 文件 + 新成绩表」收敛为「插 catalog 数据 + 注册目录」；备考域与导航随目录自动生长。
- 工具容器语义纯净；备考旅程获得「先选级再选题」的清晰心智。
- 背词视觉割裂缓解，且工作台工程隔离（独立上游可维护）不损失。
- 导航单源配置，移动 dock 与桌面 nav 不再各改一份。

**负面 / 需管理**
- A1 既有 UI 与数据需迁移：`view-writer`/`view-cards` 内 a1 区块搬移会触碰 index.html 大单文件——**字符串断言测试（test_german_workbench 族、index 相关探针）有静默失配风险**，迁移须同步特征串并按 MEMORY「跨边界契约用行为探针」纪律补回归。
- 成绩表迁移（a1_*_records → exam_trials）需设计旧行兼容/映射，避免历史丢失；沿用 MEMORY sqlite 确定性关闭与 clean_db gc 经验。
- 共享 token 抽取会改动 `style.css` 与 workbench 样式引用点，属全局视觉回归面，需分步验证。

**待办（/vault-plan 输入）**
1. 备考域前端骨架（view-exam + 等级页签 + 模块卡片）与导航数据化单源。
2. A1 四功能（写/听/读/口语）从工具视图迁入备考域的迁移清单 + 字符串断言/探针同步。
3. exam catalog 数据结构与种子数据（A1 既有素材归位）；成绩表泛化与旧行迁移 SQL。
4. 路由参数化 `/api/exams/{level}/{module}`；`a1_dict` 等数据模块按 `{level}_{module}` 归位。
5. 组件提取刀（听/读先行）；写作判分延后。
6. 共享设计 token 抽取 + workbench 视觉对齐 + 词表契约（`vocab_cards.cefr_level` 过滤）。
7. 测试策略：迁移期回归基线 + 新等级泛化 fixture + 探针。

**非目标（本 ADR 范围外）**
- 不在此次一次性重写 A1 判分/交互逻辑（由后续提取刀覆盖）。
- 不做整站 hash router / 全面 UI 重构（如需另立 ADR）。
- 背词工作台并入主站 SPA 的选项已被否决并记录，不再回到该议题。

**关联**
- 前置：ADR-0001（工作台核心词模式）、ADR-0002（工作台 scope 控制）；同步：ADR-0004（LAN 同步 Stage B，与工作台数据通道复用 applyMerge）。
- Vault `_template/ADR-0004-workbench-iframe-embedding.md` 为「iframe 隔离」背景草稿（非 DeLector 已归档决策），本 ADR Q4 以其为参照而非重复立项。
