---
title: "ADR-0001: Workbench 核心词模式（Core Words Mode）"
created: 2026-08-31
updated: 2026-08-31
type: project
tags:
  - project/delector
  - topic/adr
  - topic/architecture
  - topic/workbench
status: stable
audience: both
authority: synthetic
claim_risk: medium
review_status: unreviewed
---

# ADR-0001: Workbench 核心词模式（Core Words Mode）

## 1. Context and Problem Statement

DeLector 的德语背词工作台（Workbench）内置 684 个 Goethe A1 种子词，配合 FSRS-6 调度器进行复习。用户在备考时间不足的场景下，希望聚焦于更高频的"核心词"子集，而不必在 684 个词中均匀分配精力。

用户提供了一份自定义词表（`delector_custom_words.json`，wb-sync 格式，237 个 `customWords`）作为"核心词"的候选。

核心问题：
- 这份词表只有 237 个，不是用户最初说的 300 个
- 其中 211 个已经存在于 684 个种子词中（归一化词头匹配），直接导入会产生重复卡片
- 24 个词在种子词中不存在，需要作为新词加入
- 模式切换时 FSRS 进度不能丢失或重复

## 2. Decision Drivers

- **进度一致性 (MUST)**：同一个词在任何模式下都只有一条 FSRS 进度记录，切换模式不产生重复、不丢失历史
- **实现简洁性 (SHOULD)**：优先复用现有架构（tag 过滤、队列构建），不引入新的数据层抽象
- **开箱即用 (SHOULD)**：核心词是面向所有用户的产品功能，不是个人导入工具
- **诚实命名 (MUST)**：功能名称和数字必须与实际数据一致，不编造"300 词"或"考纲核心"等没有数据支撑的说法
- **同步边界清晰 (SHOULD)**：明确哪些数据参与 wb-sync、哪些不参与，避免静默部分同步

## 3. Considered Options

### Option 1: 标记法（Tag on Existing Seed Words）

对 211 个匹配到的种子词打 `core` 标签；24 个未匹配词作为自定义词加入并打 `core` 标签。核心模式 = 过滤 `tag=core`（共 235 个：211 种子词 + 2 模糊匹配 + 22 真正新词，`aufmachen` 等假阳性排除后）。

- 👍 Pros：一词一进度，天然不重复不丢失；复用现有 tag 过滤基础设施；可与 topic/tag 自由组合
- 👎 Cons：24 个新词加入后"684 词"的硬编码数字失效；种子词的 tag 不参与 wb-sync 导出（导出只带 custom=true 的词）

### Option 2: 独立白名单（Separate Scope Allowlist）

684 种子词原样不动，核心模式用独立的 ID 白名单（`wb.scope.core.v1`）存储。24 个新词作为自定义词加入。

- 👍 Pros：684 词原封不动，所有现有计数不变；白名单可独立版本管理
- 👎 Cons：多了一个身份来源，词删除后白名单会有悬空 ID；需要额外处理备份恢复

### Option 3: 直接导入为自定义词

237 个词全当自定义新词导入，不做去重。

- 👍 Pros：最简单
- 👎 Cons：211 个重复词有两套独立 FSRS 进度，统计失真；不符合"不丢数据"的精神（数据反而翻倍了）

## 4. Decision Outcome

Chosen option: **Option 1（标记法）**，原因如下：

1. **进度一致性是第一原则**：一个词对应一条 FSRS 记录，这是 FSRS 系统的基本不变量。标记法天然满足，其他方案都需要额外处理才能接近这个效果。
2. **复用现有基础设施**：tag 过滤、队列构建、搜索叠加——这些 Workbench 已经有了。核心词模式本质上就是一个"内置的特殊 tag"。
3. **24 个新词的增加是诚实的**：用户确实提供了新词，加入词库是合理的。硬编码的"684"改为动态计算，顺便消除了一个脆弱点。
4. **种子词 tag 不同步是可接受的**：核心词表是内建常量（代码里写死），所有设备开箱就有，不需要同步。用户本地加减核心词（如果开放这个功能）是高级功能，明确标注"不同步"即可。

**具体匹配策略**：
- 归一化词头（去冠词、去复数后缀、去括号、小写）做精确匹配
- 2 个可靠模糊匹配（`der Partner`→`die Partnerin` 词性变体、`die Übernachtung`→`übernachten` 名动派生）人工确认后纳入
- `aufmachen`→`ausmachen` 假阳性排除（词义相反）
- 最终核心词数 = 211（精确） + 2（模糊人工确认） + 22（真正新词，去掉 `mit Karte` 这类短语）≈ **235**（最终数以代码实现时的人工 review 为准）
- 释义以种子词为准（自定义词的释义大多是简写，不是冲突）
- 词性冲突以种子词为准（7 处差异中自定义词标注有误，如 `geboren` 标为 V 实际是 Adj/Partizip）

## 5. Consequences and Trade-offs

### 🟢 Positive

- **进度零风险**：标记法下切换模式永远不会产生重复卡片或丢失进度，因为始终是同一个词同一条记录
- **实现成本低**：核心逻辑是"加一个 tag 过滤维度"，复用现有 `buildReviewQueue` 的过滤路径
- **可组合性强**：核心词 ∩ 饮食话题、核心词 ∩ 搜索结果、核心词 ∩ 错题集——所有现有过滤维度都可以和核心模式叠加
- **修复了硬编码计数的脆弱性**：684 改为动态计算后，以后加词不会再出现"数字漂移"问题

### 🔴 Negative

- **词库总量增长**：加入 22+ 个新词后，总词数从 684 变成 ~706。`test_german_workbench.py` 里对 684 的硬编码断言需要更新
- **核心词数量是 235，不是 300**：功能命名不能叫"核心 300 词"，要叫"核心词（235）"或类似诚实名称。如果以后要扩充到 300，需要再补充词源
- **种子词 tag 不参与 wb-sync**：如果用户在一台设备上手动增减了核心词成员，这个改动不会同步到其他设备。作为 MVP 先明确声明"内建核心词表，不支持自定义和同步"

### 🛡️ Compliance Guardrail

- **测试**：`test_german_workbench.py` 新增断言——核心词模式下复习队列只包含 core tag 的词；切换模式后 `S.cards` 对象数量不变（没有重复创建）
- **测试**：导入/合并路径下，已存在的种子词不会因为核心词表而产生重复 id 或重复卡片
- **测试**：总词数动态计算正确（种子词 + 自定义词，不是硬编码）
- **代码约定**：核心词 ID 列表作为常量 `CORE_WORD_IDS` 写在 `workbench.html` 顶部，和 `SEED_WORDS` 相邻，便于维护
