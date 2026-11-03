# 沉浸式学术精读排版重塑与 CEFR 词阶分级视觉降噪实施计划

> **Goal**: 消除德语正文段落碎裂感与五彩斑斓底色视觉疲劳，恢复原生出版级段落流与三档词阶透视模式。
> **Tech Stack**: JavaScript (ES2022 Vanilla / No-Framework), CSS3 (Tokens System), Python 3.11 (Pytest Mechanical Gates).
> **Spec Reference**: `docs/adr/2026-11-01-adr-0026-reader-immersive-editorial-continuous-flow-and-cefr-noise-reduction.md` (ADR-0026)
> **Global Constraints**: 零 innerHTML 安全契约（DOM API / textContent / esc 过滤）；零框架原生架构；W3C HTML5 行内内容规范（`<p>` 内严禁包含 `<div>`）；所有测试物理执行验证。
> **Branch**: `feat/reader-immersive-continuous-flow-and-cefr-noise-reduction` — opened from `master`, landed via PR.

---

## [NOTE] Decisions So Far

- [ADR-0026](docs/adr/2026-11-01-adr-0026-reader-immersive-editorial-continuous-flow-and-cefr-noise-reduction.md): 采纳推荐方案 1A（正文 DOM 纯净化，移除内联拓扑 strip，拓扑分析收敛至右侧抽屉）与方案 2C（视觉基线清零法 + 沉浸/考点/热力三档视力透视模式）。
- [PR #189](https://github.com/ROM4n2/DeLector/pull/189): 闭合 `style.css` 历史悬空大括号，恢复伴学对话界面排版与隐去正文实体按钮。
- [PR #190](https://github.com/ROM4n2/DeLector/pull/190): 收敛 Windows 打包烟雾测试，将 Windows CI 耗时由 14.5 分钟降至 2.5 分钟。

---

## [NOTE] Active Frontier (Unblocked Tasks)

### Task 1: 正文段落 DOM 纯净化与连续文本流重构 [Tier: 2-Standard] [Mode: AFK] [Role: Frontend Core Engineer]

**Files:**
- Modify: `static/js/reader.js:235-265`
- Test: `tests/test_reader_continuous_flow.py` (新建契约测试)
- Test: `tests/test_frontend_security.py:90-100`

**Interfaces:**
- Consumes: `sentTokens: string`, `sent: SentenceObject`, `openSyntaxDrawerForSentence: (sentId: number) => void`
- Produces: 纯净短语行内段落结构 `<p class="reader-p"><span class="reader-sent-unit" id="sent-unit-${sent.id}" data-sent-id="${sent.id}"><span class="sent-text-wrap">${sentTokens}</span></span></p>`（零内部 `<div>`，根除 HTML5 强制闭合 `<p>` 的排版碎裂问题）。

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: Zero-innerHTML]`: 保持 `esc(t.text)` 与 `Number(sent.id)` 强制数值化，禁止非转义文本注入。
- [ ] `[Instinct: Layer Architecture]`: `reader.js` 属于 L1/L2 交互层，严禁破坏 `check_frontend_layers.py` 边界。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 正文段落 DOM 纯净化与连续文本流重构.
> Mode: AFK | Role: Frontend Core Engineer
> Goal: 从 `reader.js` 的 `renderReaderContent` 中彻底移除嵌套在 `<p class="reader-p">` 内的 `<div class="sentence-topology-strip">` 预埋节点，仅保留纯行内短语元素 `<span class="reader-sent-unit">`。
> Target Files: Modify `static/js/reader.js`, Modify `tests/test_frontend_security.py`, Create `tests/test_reader_continuous_flow.py`.
> TDD Steps:
> 1. 创建失败测试 `tests/test_reader_continuous_flow.py`，验证 `reader.js` 生成的正文 `<p class=\"reader-p\">` 内部不存在 `sentence-topology-strip` 且不包含任何块级 `<div>` 标签（RED）。
> 2. 运行测试并确认失败。
> 3. 修改 `static/js/reader.js`，将 `currentSentences.push` 的结构精简为仅包含 `<span class=\"reader-sent-unit\">`，完全移除非法内嵌的 `<div>`（GREEN）。
> 4. 同步调整 `tests/test_frontend_security.py` 的相关断言。
> 5. 运行 `pytest tests/test_reader_continuous_flow.py tests/test_frontend_security.py` 确认全绿。
> Return: Summary with MANDATORY Physical Execution Receipt (exit code + stdout snippet)."

**Step Breakdown:**
- [ ] **Step 1: Write the failing test (RED)**: 创建 `tests/test_reader_continuous_flow.py`。
- [ ] **Step 2: Run test and verify it fails with expected message**: `python3 -m pytest tests/test_reader_continuous_flow.py -q`
- [ ] **Step 3: Implement minimal production code (GREEN)**: 重构 `static/js/reader.js`。
- [ ] **Step 4: Run tests and verify all green**: 验证无块级元素打碎段落。
- [ ] **Step 5: Refactor & Flatten with guard clauses (REFACTOR)**
- [ ] **Step 6: Physical Evidence Gate**: 执行 pytest 与静态安全检查，记录真实退出码。
- [ ] **Step 7: Git atomic commit** on `feat/reader-immersive-continuous-flow-and-cefr-noise-reduction`.

---

### Task 2: 词阶视觉基线清零与三档视力透视模式 CSS Token 架构 [Tier: 1-Light] [Mode: AFK] [Role: Design System Engineer]

**Files:**
- Modify: `static/style.css`
- Modify: `static/css/tokens.css`
- Test: `tests/test_frontend_security.py`

**Interfaces:**
- Produces:
  - 默认/沉浸模式 `.cefr-mode-immersive`（或默认状态）：A1/A2 `background: transparent`；B1/B2 仅下沿弱底纹；C1 柔和淡紫底色。
  - 考点聚焦模式 `.cefr-mode-exam`：仅高亮 B2/C1 及考点。
  - 全量热力模式 `.cefr-mode-heatmap`：保留全量 CEFR 彩色图谱。
  - 悬停/划词选中高亮保持最高优先级（`.tok:hover`, `.tok.sel`）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: 词阶视觉基线清零与三档视力透视模式 CSS Token 架构.
> Mode: AFK | Role: Design System Engineer
> Goal: 重构 `static/style.css` 中 `.tok.A1` ~ `.tok.C1` 的背景规则，默认彻底清零 A1/A2 无谓色块；实现 `.cefr-mode-immersive`、`.cefr-mode-exam`、`.cefr-mode-heatmap` 三套阶梯样式。
> Target Files: Modify `static/style.css`, Modify `static/css/tokens.css`.
> TDD Steps:
> 1. 在 `static/css/tokens.css` 与 `static/style.css` 中定义基于透视模式的词阶样式。
> 2. 检查大括号配对并运行验证脚本，确保语法 100% 平衡。
> 3. 运行 `tests/test_frontend_security.py` 确保样式变更未破坏既有契约。
> Return: Summary with MANDATORY Physical Execution Receipt (exit code + stdout snippet)."

**Step Breakdown:**
- [ ] **Step 1: Write CSS rules in `tokens.css` and `style.css`**
- [ ] **Step 2: Run CSS brace and syntax checker**
- [ ] **Step 3: Run existing frontend test suite to ensure zero regressions**
- [ ] **Step 4: Physical Evidence Gate**: 确认样式编译与平衡。
- [ ] **Step 5: Git atomic commit** on `feat/reader-immersive-continuous-flow-and-cefr-noise-reduction`.

---

### Task 3: 阅读器视力透视胶囊切换器与状态持久化 [Tier: 2-Standard] [Mode: AFK] [Role: Frontend Interaction Engineer]

**Files:**
- Modify: `static/views/reader.html:60-70`
- Modify: `static/js/reader.js`
- Modify: `static/js/main.js`
- Test: `tests/test_reader_continuous_flow.py`
- Verify: `tools/build_index_html.py`, `tools/check_index_html_sync.py`

**Interfaces:**
- Consumes: `localStorage.getItem('delector_cefr_vision_mode')`
- Produces: `setCefrVisionMode(mode: 'immersive' | 'exam' | 'heatmap'): void`，操作容器 class 并持久化到客户端存储。

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: Index Sync Gate]`: 任何对 `static/views/reader.html` 的修改，必须执行 `tools/build_index_html.py` 并通过 `tools/check_index_html_sync.py`。
- [ ] `[Instinct: Pure State Flow]`: 模式切换仅变更容器 Class，严禁触发文章全量 DOM 重新渲染，保持当前阅读滚动位置不变。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: 阅读器视力透视胶囊切换器与状态持久化.
> Mode: AFK | Role: Frontend Interaction Engineer
> Goal: 在 `static/views/reader.html` 的控制条中新增三档切换胶囊组件（沉浸 / 考点 / 热力）；在 `reader.js` 中实现 `setCefrVisionMode` 并通过 `localStorage` 保持用户选择。
> Target Files: Modify `static/views/reader.html`, Modify `static/js/reader.js`, Update `static/index.html` via build tool.
> TDD Steps:
> 1. 在 `tests/test_reader_continuous_flow.py` 中增加对 `setCefrVisionMode`、透视胶囊 DOM 契约与持久化行为的静态测试（RED）。
> 2. 修改 `static/views/reader.html`，追加 `.cefr-mode-pill` 模板。
> 3. 运行 `python3 tools/build_index_html.py` 同步主模板。
> 4. 在 `static/js/reader.js` 中实现 `setCefrVisionMode`，在阅读器初始化时读取并应用缓存模式。
> 5. 运行 `python3 tools/check_index_html_sync.py` 与 pytest suite 确认全绿（GREEN）。
> Return: Summary with MANDATORY Physical Execution Receipt (exit code + stdout snippet)."

**Step Breakdown:**
- [ ] **Step 1: Write tests for vision mode controller (RED)**
- [ ] **Step 2: Add vision mode UI pill to `static/views/reader.html`**
- [ ] **Step 3: Rebuild `static/index.html` via `tools/build_index_html.py`**
- [ ] **Step 4: Implement `setCefrVisionMode` in `static/js/reader.js` (GREEN)**
- [ ] **Step 5: Run `tools/check_index_html_sync.py` and test suite**
- [ ] **Step 6: Physical Evidence Gate**: 捕获运行日志与退出码。
- [ ] **Step 7: Git atomic commit** on `feat/reader-immersive-continuous-flow-and-cefr-noise-reduction`.

---

### Task 4: 静态架构与全量机械门禁回归验证 [Tier: 1-Light] [Mode: AFK] [Role: Quality & Compliance Engineer]

**Files:**
- Test: `tools/check_frontend_layers.py`
- Test: `tools/check_frontend_api_contract.py`
- Test: `tools/check_companion_contract.py`
- Test: `tools/check_index_html_sync.py`
- Test: `tests/test_ci_hardening.py`
- Test: `tests/test_reader_continuous_flow.py`

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 4: 静态架构与全量机械门禁回归验证.
> Mode: AFK | Role: Quality & Compliance Engineer
> Goal: 串联执行项目全部静态门禁脚本与单测集，确保重构满足零 InnerHTML 漏洞、分层合规、模板绝对同步与 Ruff/Mypy 规范。
> Execution Command:
> `python3 tools/check_frontend_layers.py && python3 tools/check_frontend_api_contract.py && python3 tools/check_companion_contract.py && python3 tools/check_index_html_sync.py && ruff check . && python3 -m pytest tests/test_reader_continuous_flow.py tests/test_ci_hardening.py tests/test_frontend_security.py -q`
> Return: Summary with MANDATORY Physical Execution Receipt (exit code + stdout snippet)."

**Step Breakdown:**
- [ ] **Step 1: Execute full static check chain**
- [ ] **Step 2: Execute focused pytest suite**
- [ ] **Step 3: Capture full passing evidence receipt**
- [ ] **Step 4: Create PR and verify GitHub Actions CI**

---

## [NOTE] Deferred Gap Register

| gap | why deferred | trigger that forces revisiting | owner |
|---|---|---|---|
| 移动端自适应视力胶囊折叠 | 移动端顶部空间较为有限，本期先保证桌面端与平板端平铺展示 | 移动端在 <360px 屏宽出现顶栏换行溢出用户反馈 | UI Team |
| 动词配对高光自定义色系 | 既有 `.is-separable` 橙色虚线下划线经实测对比度良好 | 用户提出对可分离前缀下划线样式的个性化诉求 | Design System |

---

## [NOTE] Fog of War (Not Yet Specified)

- 目前无未决阻塞项（所有依赖的 DOM 结构与 CSS Token 体系均已完成物理探测与溯源）。

---

## [NOTE] Out of Scope

- 变更后端分词与 CEFR 难度评估算法（服务端分词及难度元数据保持不变）。
- 重构词汇背词工作台（Zettelkasten 背词卡片已有成熟 Editorial 规范，不在本次阅读器改动范围）。
