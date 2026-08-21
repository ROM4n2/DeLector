# v4.0.0 写作台 IDE 化开山之作：git 版本管理完善 + 内联 IDE 编辑器

## Context

v3.12.0 已发版（AI 逐 hunk 审查 + 类 git 版本快照）。用户反馈两个问题：
1. **版本管理噪音**：查看/浏览版本只能用「恢复」，每次对不同版本恢复就自动存检查点（`恢复到版本 N 之前`），浏览历史留下一堆垃圾记录，且**删不掉**。
2. **写作台还不是真 IDE**：textarea + 独立 diff 弹窗，没有行内可编辑的编辑器体验。

v4.0.0 = **git 完善**（预览只读 + 删除版本）+ **IDE 内联编辑器**（开山之作，一起上阵）。

## 已锁定的决策（grilling 结论，不回头改）

| # | 决策 | 值 |
|---|---|---|
| 1 | git 完善·查看 | 新增**只读预览**（`GET /api/essays/{id}/versions/{version_id}` 返回内容+分析，不写库）；版本列表加「查看」→ 预览弹窗。**浏览不再产生检查点** |
| 2 | git 完善·删除 | 新增 `DELETE /api/essays/{id}/versions/{version_id}` + 前端删除按钮（confirm）。删快照不影响 essays 表当前内容 |
| 3 | git 完善·恢复 | **保留恢复检查点**（可逆安全网）；浏览改用预览后，检查点只在明确恢复时出现，且可删 |
| 4 | 版本 | v4.0.0（versionCode 40000），bump `?v=` / CACHE_NAME |
| 5 | IDE 编辑器 | **contenteditable**（原生零依赖，可编辑层插 span 标错）；**防抖 400ms 实时重分析**（本地规则免费）；**完整交互**（点击波浪线 → 侧栏详情 + 一键修正 corrected_form + 存卡 + hover 气泡 + 句子导航点句子滚动定位） |

## 现状（已核实）

- `restore_essay_version`（server.py:2658）：不同版本 → 自动存检查点 + 更新 essay。无删除端点。
- `list_essay_versions`（2629）：返回版本列表（含 message/error_count）。
- 前端 `restoreEssayVersion`（writer.js:909）是唯一查看方式；版本项有「↩ 恢复」按钮，无查看/删除。
- v3.11 的 span 数据（`{text, spans:[{error_type,corrected_form,explanation_zh,start,end}]}`）+ v3.12 diff 机制在。

## 实现方案（Plan agent 设计）

### 1. Git 完善 —— 后端端点（server.py，`list_essay_versions` :2629 之后）

- **`GET /api/essays/{id}/versions/{version_id}`**（只读预览）：404 守卫（essay/version 缺失）；纯 SELECT 返回 `{id, message, created_at, content, analysis_json, error_count}`。**无 INSERT、无检查点、无重分析**。
- **`DELETE /api/essays/{id}/versions/{version_id}`**：404 守卫；`DELETE FROM essay_versions WHERE id=? AND essay_id=?` —— **只动 essay_versions，不碰 essays.content**。返回 `{status, deleted_version_id}`。
- **`restore_essay_version` 不改**（检查点保留，现在可删）。
- `list_essay_versions` 不需改。
- **测试**（test_server.py，仿现有 fixtures）：`test_essay_version_preview_read_only`（预览后版本数不变、essay 内容不变、404 守卫）、`test_essay_version_delete`（删后列表缺该项、essay 内容不变、重复删 404、删版本不删 essay）。恢复检查点由现有测试守住。

### 2. IDE 编辑器 —— contenteditable

**DOM（index.html 替换 `#writer-text`）**：`<div id="ide-editor" class="ide-editor" contenteditable="true" data-placeholder="..." oninput="analyzeWriterText()">` + `<div id="ide-error-tooltip">`。块结构：每句一个 `<div class="ide-sent-block" data-sent-idx>`，句内错误为 `<mark class="writer-err-underline err-{type}" data-sent data-span>`（**复用现有 `.err-*` 颜色 + 波浪线，不新增错误色**）。块只含句子文本 + 标记（无序号前缀，保证 `innerText` 往返一致）。

**核心助手（writer.js）**：
- `editorText()` = `editor.innerText.replace(/\s+/g,' ').trim()`（与发送给 `/analyze` 的字符串一致）；`setEditorText(text)` = `editor.textContent = text`。
- `renderEditor(text, analysis, restoreCaretOffset)`：按 `analysis.sentences` 建块（复用 `buildSentenceHighlightedText`，加 `{clickable, markCls, useTitle}` 选项）；处理 `[:2000]` 截断尾部；重渲染 + 恢复光标 + 恢复滚动。
- `updateAnalysisPanels(a)`：状态 pill + CEFR + 新句子导航列表。

**防抖实时循环（重写 `analyzeWriterText`）**：oninput → `text=editorText()` → **同步 captureCaret()** → 清 timer → 400ms 后 `POST /api/writing/analyze {text}` → `renderEditor(text, a, caretOffset)`。打字取消 timer 并重新捕获，保证 text 与 caret 一致。

**光标保留（关键，TreeWalker char-offset）**：
- `captureCaret()`：TreeWalker(SHOW_TEXT) 累加 textContent 长度直到 startContainer → 绝对 char offset。
- `restoreCaret(offset)`：重建 DOM 后 TreeWalker 走文本节点，offset ≤ nodeLen 时 setStart + collapse。
- 标记是零长度内联包裹，char offset 在重渲染间稳定（因为从同一捕获 text 渲染）。

**完整错误交互**：
- 点击标记 → `selectWriterSpan(sentIdx, spanIdx)` → 侧栏详情 + **「一键修正」**（新 `fixSelectedSpan()`：`mark.textContent = corrected_form` → 重分析 → 重渲染 → `selectMarkAndCaret` 定位）+ 现有「存 Anki」。
- **hover 气泡**：`#ide-editor` 委托 mouseenter/leave，从 `currentAnalysis` 读 `error_type`+`explanation_zh`（data-sent/span 索引，不塞进属性），`position:fixed` 定位。编辑器内标记去掉原生 title。
- **句子导航**：侧栏 `#writer-sent-nav` 列表（句号 + 截断文本 + 错误徽章），`jumpToSentence(i)` → `block.scrollIntoView({behavior:'smooth'})` + 闪烁类。

**迁移现有 `#writer-text` 读取点**（writer.js）：openWriterEssay/clearWriterForm/saveWriterErrorAsCard/saveWriterEssay/aiPolishEssay/applyPolishChanges/restoreEssayVersion 全部改走 `editorText()`/`renderEditor()`。`renderWriterReport` 拆成 `renderEditor` + `updateAnalysisPanels`。

### 3. 版本 UI + 预览弹窗

- 版本列表每项加「查看」（→ `previewEssayVersion(id)` 只读预览弹窗，含「恢复到此处」按钮复用 restore）+「删除」（confirm → DELETE → reload）。
- 新 `#version-preview-overlay`：只读渲染版本内容 + 错误标记（`buildSentenceHighlightedText` 的 `clickable:false` 模式，保留原生 title）。
- 新导出：`previewEssayVersion/closeVersionPreview/deleteEssayVersion/jumpToSentence/fixSelectedSpan`，注册进 main.js window 全局。

### 4. CSS（style.css）

`.ide-editor`（min-height/衬线/placeholder:empty:before）、`.ide-sent-block`、`.ide-sent-flash`、`.ide-error-tooltip`（fixed 高 z-index）、`.writer-sent-nav*`、`.version-preview-box`。**复用** `.writer-err-underline`/`.err-*`/`.writer-status-pill`/`.version-item*`。

### 5. 版本 bump v4.0.0

build.gradle `versionCode 40000`/`versionName "4.0.0"`（测试 :1796 要求 `>391`，通过）；`writing_rules.py:262` version → "4.0.0"（+ test_writing_rules 两处断言）；index.html `?v=4.0.0`（:13/:22/:1128）；sw.js CACHE_NAME + writer.js `?v=4.0.0`。

### 6. PR 切片

1. **Git 后端**：preview + delete 端点 + 3 测试（独立可发）。
2. **版本 UI + bump**：预览弹窗 + 查看/删除按钮 + 版本字段 bump 4.0.0。
3. **IDE 编辑器**：contenteditable + 光标保留 + 防抖 + fixSelectedSpan + 气泡 + 句子导航 + 全迁移 + CSS（最险，留最后，前面切片已可发版）。

### 7. 风险

1. **contenteditable 光标/标记脆弱**：重渲染丢光标、标记边界输入继承 `<mark>` 格式。缓解：char-offset 光标 + 防抖归一 + `selectMarkAndCaret`；失败钳到末尾不崩。
2. **防抖重渲染重置光标/滚动**：同步捕获（caret + scrollY）→ 渲染后恢复；每次输入取消 timer 保证一致性。
3. **移动端 contenteditable 怪癖**（Android WebView）：`innerText` 归一差异、选区 API 缺口、软键盘跳动。缓解：保留手动「⚡实时诊断」按钮；若真机标记错乱，用 `matchMedia('(hover:hover)')` 门控自动重渲染，移动端退化为纯编辑 + 手动诊断。

## 验证方式

1. `pytest` 全绿（147 现有 + 新增 ~5，预计 ~152）。
2. 手动：写作台 → 粘含错作文 → **编辑器内**错误波浪线实时出现（打字停顿 400ms 重渲染不丢光标）→ 点击错误 → 侧栏「一键修正」→ 编辑器内文本替换 + 重新标注 → hover 出气泡 → 侧栏句子导航点击跳转 → 存卡。
3. **git 完善**：版本列表「查看」→ 只读预览不产生新版本；「删除」→ 快照消失、当前内容不变；恢复仍产生检查点但可删。
4. AI 润色弹窗照常（读写编辑器文本）→ 应用 → 自动存版本。
5. Android：CI 打 APK 真机 → 编辑器可用；移动端标记若错乱走手动诊断兜底。发布后不验 APK。
