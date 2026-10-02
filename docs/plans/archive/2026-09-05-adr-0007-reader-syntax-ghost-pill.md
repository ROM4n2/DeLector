# ADR-0007 实施计划：精读句法拓扑行内幽灵微胶囊主动触发改造

> **Goal**: 废除光标停留 600ms 被动弹出抽屉的设计，替换为「行内幽灵微胶囊按钮 (Quiet Ghost Pill on Hover) + 显式点击打开句法抽屉」，保护阅读心流与生词查词状态。
> **Tech Stack**: 原生 ES Modules JS + 原生 CSS tokens
> **Spec Reference**: `docs/specs/2026-09-05-adr-0007-reader-syntax-ghost-pill-explicit-trigger.md` / `D:/Obsidian/Coding/08-Projects/DeLector/01-ADR/0007-reader-syntax-ghost-pill-explicit-trigger.md`
> **Global Constraints**: 574+ pytest 不退, 10/10 Node 探针不退, 零主线程代码篡改，全流程通过 Subagent 执行并落实 Maker-Checker。

---

## 任务拆解与执行清单

### Task 1: 契约测试更新 (TDD RED)
- **文件**: `test_grammatik_radar.py`, `test_frontend_security.py`
- **内容**:
  - `test_grammatik_radar.py`: 更新 `test_reader_compute_article_syntax_stats_and_hover_binding` 为 `test_reader_syntax_ghost_pill_explicit_trigger`:
    - 断言 `_syntaxHoverTimer` 不再存在于 `static/js/reader.js`。
    - 断言 `sentWrapper` 中包含 `<button class="sent-syntax-btn" onclick="event.stopPropagation(); openSyntaxDrawerForSentence(${Number(sent.id)})"`。
    - 断言 `openSyntaxDrawerForSentence` 保留使用 `Number(sent.id)`。
  - `test_frontend_security.py`: 确认包含 `openSyntaxDrawerForSentence(${Number(sentId)})` 与安全参数检验。

### Task 2: 前端代码实现与样式细化 (TDD GREEN)
- **文件**: `static/js/reader.js`, `static/style.css`
- **内容**:
  - `static/js/reader.js`:
    - 移除 `_syntaxHoverTimer` 变量及相关的 `mouseenter`/`mouseleave` 防抖代码。
    - 在 `sentWrapper` 中恢复胶囊按钮：`<button class="sent-syntax-btn" onclick="event.stopPropagation(); openSyntaxDrawerForSentence(${Number(sent.id)})" title="展开德语拓扑五场域、从句树与句法雷达">🌳 句法</button>`。
  - `static/style.css`:
    - 改造 `.sent-syntax-btn`:
      ```css
      .sent-syntax-btn {
        display: inline-flex;
        align-items: center;
        gap: 2px;
        font-size: 0.65rem;
        font-family: var(--sans, sans-serif);
        padding: 1px 6px;
        margin-left: 6px;
        border-radius: 999px;
        border: 1px solid var(--rule-light, #ebe5da);
        background: var(--paper-warm, #f7f4ec);
        color: var(--pencil, #5c554b);
        cursor: pointer;
        opacity: 0;
        pointer-events: none;
        vertical-align: middle;
        user-select: none;
        transition: opacity 0.2s cubic-bezier(0.22, 1, 0.36, 1), background 0.15s, border-color 0.15s, color 0.15s;
      }
      .reader-sent-unit:hover .sent-syntax-btn {
        opacity: 0.75;
        pointer-events: auto;
      }
      .sent-syntax-btn:hover {
        opacity: 1;
        background: var(--paper-card, #ffffff);
        color: var(--accent, #c14a2b);
        border-color: var(--accent, #c14a2b);
        box-shadow: 0 1px 4px rgba(21, 20, 15, 0.08);
      }
      ```

### Task 3: 独立代码审查与全量回归闭环
- **文件**: 全量工程
- **内容**:
  - 派发 Code Reviewer 审查 XSS 防护、事件穿透防护（`event.stopPropagation()`）、Token 规范性。
  - 运行 `python -m pytest -q` 确保 574+ 测试全绿。
  - 运行 `Get-ChildItem tools/*.mjs | ForEach-Object { node $_.FullName }` 确保 10/10 行为探针全绿。
  - 归档提交与台账更新。
