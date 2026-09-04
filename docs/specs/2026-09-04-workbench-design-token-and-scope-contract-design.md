# 背词工作台视觉 Token 归一与考纲词表契约设计

> **状态**：设计稿 v1（/vault-spark 产出，经 Dual-Lens 权衡，用户确认优先级：先路线 B，再路线 C，路线 A 延后）。
> **关联**：`d:/Obsidian/Coding/08-Projects/DeLector/01-ADR/0005-navigation-exam-domain-and-level-scalability.md`（§4.5 背词工作台形态与词表契约）、`docs/specs/2026-09-03-lan-silent-sync-design.md`、`static/german/workbench.html`、`static/style.css`。
> **范围**：背词工作台视觉重构（Academic Modern Editorial 暖纸墨水风）、共享 CSS Token 架构抽取、CEFR 考纲词库契约与范围选择器扩展。
> **不在此范围**：取消 iframe 将工作台并入主站 SPA（维持 iframe 隔离防样式污染）、重写 FSRS-6 数学算法、引入非考纲生僻词。

---

## 1. 问题陈述与用户价值 (Problem Statement & User Value)

### 1.1 现状痛点

1. **视觉割裂（The Visual Dissonance）**：
   - DeLector 主站已全面升级为 **Academic Modern Editorial（学术现代期刊）** 设计风格，主调为米白暖纸底色（`#FAF8F5`）、深碳墨水文本（`#15140f`）、陶土赤红主色（`#C14A2B`）与 1.5px 书本装订墨线（`#D8D0C2`），排印采用 Playfair Display 与 Inter 衬线组合。
   - 相比之下，嵌入在 `view-german` 的背词工作台（`static/german/workbench.html`）依然保留着历史版本典型的「冷灰偏蓝 SaaS」界面：冷白灰底（`#F2F4F8`）、浓艳冷蓝（`#3565B0`）、系统无衬线字体。
   - 用户在从精读台或卡盒切到背词台时，产生强烈的跳脱感与断层感，破坏了沉浸式阅读与学习的仪式感。
2. **考纲词库能力受限（Scope & Level Rigidity）**：
   - 目前背词工作台内部硬编码了 A1 阶段的 682 个核心种子词（`SEED_WORDS`），顶栏分段控件仅能在「核心词」与「全部」之间切换。
   - 备考域已建立 `A1`、`A2`、`B1` 阶梯规划，但背词工作台尚未接入按 CEFR 等级筛选的词表契约，无法按等级定制复习队列。

### 1.2 目标场景与用户价值

- **目标场景**：用户无论在主站阅读长难句、查阅语法雷达，还是进入工作台专注刷词，整个 Web App 呈现出一致、典雅的暖调学术工坊视觉体验。
- **用户价值**：
  - **审美与体验**：消除界面割裂，阅读舒适不刺眼，复习反馈色彩保持高对比度与认知科学性。
  - **效率与聚焦**：工作台与考纲等级对齐，用户可针对目标考试（如 A1/B1）快速切出专属刷词流，减少无关词汇干扰。

---

## 2. 用户旅程与核心流程 (User Journey & Core Flow)

```
[用户点击导航「德语背词」]
        │
        ▼
[加载 Editorial 暖纸风 Workbench (iframe 隔离)]
   - 暖纸底色 (--paper) + 墨线卡片 (--rule) + 典雅衬线标题
   - 顶栏清晰展示当前词库范围 (A1 核心 / 考纲分级)
        │
        ▼
[复习交互与反馈 (FSRS 刷词)]
   - 3D 纸质翻牌保留丝滑触感与弹簧阻尼
   - 评分按钮：Again(樱桃红)、Hard(琥珀黄)、Good(苔藓绿)、Easy(墨绿)
        │
        ▼
[词库范围与考纲自由切换 (Scope Switcher)]
   - 顶栏分段控件无缝扩展：[ A1 核心 | 考纲全级 | 我的生词 ]
   - 切换范围时复习队列自适应过滤，进度实时同步回主站服务端
```

### 极简操作链路（≤3 步）

1. **进入工作台**：点击顶栏「德语背词」，界面瞬间呈现米白纸质展台，顶部即时指示今日待复习量与掌握度。
2. **一键切换等级**：若正在备考特定等级，点击顶栏分段器直接切换范围，卡片队列零延迟重构。
3. **沉浸复习**：键盘空格翻转、`1/2/3/4` 评分，体验如同翻阅高质量实体词汇索引卡。

---

## 3. 架构设计与技术方案 (Architecture & Technical Strategy)

### 3.1 核心原则：共享 Token 注入 + 严格工程隔离 (The Injected Token Isolation)

不把 `workbench.html` 代码强行合并进主站 SPA，而是采用 **「共享 CSS Token 注入」** 方案：

- **为什么不合并到 SPA**：`workbench.html` 拥有 4000+ 行极其精炼的单文件体系，包含专属的 3D CSS Transform、触屏手势识别与 FSRS 队列内存状态机。强行揉进主站会导致主站 CSS 作用域污染，且破坏工作台独立离线保存单文件的能力。
- **方案实现**：
  1. 建立全局设计变量层：新建 `static/css/tokens.css`。
  2. 主站 `style.css` 在顶部 `@import "css/tokens.css";`（向后兼容）。
  3. `workbench.html` 引入 `tokens.css`，将其 `:root` 的 `--bg`, `--accent`, `--line` 等变量无缝重定向到统一的设计系统 Token。

### 3.2 变量映射矩阵 (Token Mapping Matrix)

| 语义角色              | 原 Workbench 变量            | 映射至 Editorial Design System Token         | 暖色数值 / 表现                      |
| :-------------------- | :--------------------------- | :------------------------------------------- | :----------------------------------- |
| **画布底色**          | `--bg: #f2f4f8`              | `var(--paper)`                               | `#FAF8F5`（暖白羊皮纸质感）          |
| **主展台/卡片**       | `--panel: #ffffff`           | `var(--paper-card)`                          | `#FFFFFF`（高挺纯白纸面）            |
| **次级背景**          | `--card: #ffffff`            | `var(--paper-warm)`                          | `#F7F4EC`（微暖衬底）                |
| **主墨水文字**        | `--text: #1f2430`            | `var(--ink)`                                 | `#15140F`（深炭黑，高对比不刺眼）    |
| **次级文字/铅笔**     | `--muted: #68707d`           | `var(--pencil)` / `var(--ink-mute)`          | `#5C554B`                            |
| **规则边框/分割线**   | `--line: #e2e6ec`            | `var(--rule)`                                | `#D8D0C2`（1.5px 印刷装订线）        |
| **品牌强调色**        | `--accent: #3565b0`          | `var(--accent)`                              | `#C14A2B`（陶土赤红 / 墨印朱红）     |
| **强调浅色背景**      | `--accent-soft: #e8effa`     | `var(--paper-tint)`                          | `#F2ECE1`（淡米黄底）                |
| **次级重点色**        | `--accent2: #5a8ad0`         | `var(--coral)`                               | `#ED6F5C`                            |
| **复习-良好 (Good)**  | `--good: #2e9e5b`            | `var(--moss)`                                | `#3B6E3F`（苔藓墨绿，温润沉稳）      |
| **复习-困难 (Hard)**  | `--hard: #d99113`            | `var(--mustard)` / `var(--amber)`            | `#D9771C`（琥珀芥末）                |
| **复习-重来 (Again)** | `--again: #d2504a`           | `var(--cherry)`                              | `#B03030`（深樱桃红，警示且雅致）    |
| **圆角与投影**        | `--radius: 12px`, `--shadow` | `var(--shadow-sm)`                           | 浅淡纸张边缘投影                     |
| **字体族 (Fonts)**    | 微软黑体                     | `var(--sans)`, `var(--serif)`, `var(--mono)` | 英文/德语走 Inter + Playfair Display |

### 3.3 夜间模式 (Dark/Night Reading Mode)

在 `[data-theme="dark"]` 下：

- `--bg` 映射到 `--stage`（`#181512` 深古铜炭灰，而非生硬纯黑）
- `--panel` 映射到 `#221E1A`
- `--text` 映射到 `#E6E1D8`
- `--rule` 映射到 `rgba(216, 208, 194, 0.15)`
- 保持低眩光、沉浸式夜间学术研读体验。

---

## 4. 考纲词表契约与范围扩展 (CEFR Level & Scope Contract)

### 4.1 词表接口设计 (`/api/cards/vocab/levels`)

在现有 `/api/wb/state` 权威同步通道之外，扩展词库只读发现端点：

- **请求**：`GET /api/cards/vocab?cefr={A1|A2|B1|ALL}&scope={core|all}`
- **契约响应**：

```json
{
  "cefr": "A1",
  "scope": "core",
  "total": 213,
  "words": [
    {
      "id": "a1-0001",
      "hw": "ab",
      "pos": "prep",
      "de": "Der Zug fährt ab Hamburg.",
      "zh": "从……起；离开",
      "core": true,
      "cefr": "A1"
    }
  ]
}
```

### 4.2 Workbench 范围切换状态机

1. 顶栏分段器（Scope Segment）扩展：
   - 保持紧凑药丸胶囊风格，融入顶栏同一行。
   - 模式选项：`A1核心`（默认） / `A1全量` / `精读生词`。
2. 筛选策略：
   - 切换范围时，调用 `refilterReviewQueueForScope()`，保证已有复习进度的卡片不会重复出题。
   - 严格守护已有的 13 条切片护栏（`tools/wb_queue_probe.mjs`），杜绝队列洗牌回退。

---

## 5. 边缘异常与防护机制 (Edge Cases & Resilience)

1. **单机与离线网络波动 (Offline Fallback)**：
   - `workbench.html` 内部依然内联保留原版的精简种子词汇数据（`SEED_WORDS`）。
   - 若向后端请求各等级词库失败（离线/网络错误），系统静默降级到内置种子词，确保 100% 离线单机可用，不抛致命未捕获异常。
2. **探针切片防漂移保护 (Probe Slice Preservation)**：
   - `tools/wb_queue_probe.mjs` 会直接读取 `workbench.html` 源代码并切片运行（如 `pad2`, `todayStr`, `buildReviewQueue` 等）。
   - **红线**：修改 `workbench.html` 时，**绝对不得破坏探针依赖的代码切片边界与函数签名**，改动后必须运行 `node tools/wb_queue_probe.mjs` 验证 13 项护栏全绿。
3. **跨域与 iframe 嵌入通信 (Iframe Message Security)**：
   - Workbench 与父页面通信走既有的 `postMessage` 模式，增加 `origin` 校验，防止非法父窗口注入恶意脚本。

---

## 6. 测试与验证策略 (Test Strategy)

1. **探针自动化回归（核心护栏）**：
   - 运行全部 10 个 Node.js 探针：`tools/*.mjs`，特别是 `wb_queue_probe.mjs`、`wb_sync_probe.mjs`、`wb_pair_persist_probe.mjs`，断言切片字节数与逻辑不变。
2. **Token 与样式自动化测试**：
   - 新增 `test_workbench_tokens.py`：
     - 断言 `static/css/tokens.css` 导出完整的 Editorial 变量。
     - 断言 `workbench.html` 声明并有效引入了设计 Token。
     - 断言无未解析的悬空 CSS 变量。
3. **全量回归保障**：
   - 运行全量 `pytest -q`，确保现有 559 项单测与跨端打包测试保持 100% 全绿。
