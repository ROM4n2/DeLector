# v4.1.0 写作台 Inlay Hints：语法内联提示

> **保存位置**：批准后复制到 `docs/superpowers/plans/2026-08-21-writing-desk-v410.md`（与 v3.11/v3.12/v4.0 计划同目录）。

## Context

v4.0.0 已发布（contenteditable IDE 编辑器 + git 版本预览/删除 + AI 逐 hunk 审查）。用户想把写作台做得更像 VSCode / JetBrains IDE。经 grilling 访谈，v4.1.0 选定 **Inlay Hints 做深**（AI 内联建议/ghost text 留二期副驾驶），借鉴 VSCode 的 inlay hints 思想翻译成德语语法教学。本文件是 v4.1.0 实现方案。

## 已锁定的决策（grilling 结论，不回头改）

| # | 决策 | 值 |
|---|---|---|
| 1 | 方向 | **Inlay Hints 做深**（AI ghost text 留二期副驾驶） |
| 2 | 内容 | **介词支配格 + 名词短语实际格**组合：介词旁标 `mit [Dat]`，名词旁标 `[Masc·Nom]`，让学习者**看出介词要求 vs 名词实际的不一致** |
| 3 | 显示 | 默认全开 + 工具栏一个全局开关 `toggleInlayHints()` |
| 4 | 交互 | 纯信息展示，**不点击**（点击 hint 会抢光标，动作由现有错误标记+侧栏兜底） |
| 5 | 错误共存 | **并存**：错误波浪线标"错了" + hint 标"应该是 X 格"，矛盾揭示 = 教学高光，**不抑制错误处的 hint** |
| 6 | 双格介词 | 标 `[Dat/Akk]`（in/an/auf/über 等），是学习点不是误判 |
| 7 | 技术约束 | hints 是**装饰不可编辑**，用**独立覆盖层** `#ide-hint-layer` 渲染（CodeMirror 式装饰层），**绝不混进 contenteditable 文本** —— 保住 v4.0 的 `editorText()` 往返与光标计算 |
| 8 | 数据源 | 介词格/名词格 hint 与错误规则**同一数据源**（`_PREP_CASE`/`prep_dict`/spaCy morph），不两处漂移 |
| 9 | 版本 | v4.1.0（versionCode 40100），bump `?v=` / CACHE_NAME |

## v4.0 现状（已核实，直接复用）

- `writing_rules.py`：`analyze_essay_text(text, nlp=None)` → `{version,cefr,error_count,sentences:[{text, spans:[{error_type,corrected_form,explanation_zh,start,end}]}]}`（span 是句内 char offset）。`_PREP_CASE` 固定格表 + `_TWO_WAY_PREPS` 双格集合已有。
- `writer.js`：`renderEditor(text, analysis, restoreCaretOffset)`、`buildSentenceHighlightedText`、`updateAnalysisPanels`、`analyzeWriterText`（防抖）、光标 TreeWalker 助手。
- `static/index.html`：`#ide-editor` contenteditable + `#ide-error-tooltip`。
- **硬约束**：`editorText() = editor.innerText.replace(/\s+/g,' ').trim()` 必须等于发给 `/analyze` 的字符串（否则光标/定位全乱）。所以 hint 不能用文本/内联 span 混进块（innerText 会包含 → 往返破）。

## 实现方案（Plan agent 设计）

### 1. 后端 `writing_rules.py`

**1a. 共享格判定重构**（保证 hint 与错误规则同源）：抽出 `_prep_expected_case(tok) -> (expected_case|None, source)`，source ∈ {collocation, twoway, fixed, none}，顺序：搭配 > 双格 > 单格（与 `detect_preposition_case` 完全一致）。`detect_preposition_case` 改调它（twoway/None 跳过，行为不变）。

**1b. 新增 hint 收集器**：
- `_collect_prep_hints(tokens, base)`：每个 ADP → `_prep_expected_case`；twoway 标 `[Dat/Akk]`，expected 有标 `[Dat]`/`[Akk]`，否则跳过。label 如 `mit [Dat]`。**无需介宾存在**（教学性比误报守卫宽松）。
- `_collect_np_hints(tokens, base)`：每个 NOUN → case 取 morph（名词优先，det 兜底）、gender 取 **core_dict 权威优先** → noun morph → det morph。label 如 `[Neut·Dat]`（有 gender 才带）。
- 注意：`error_count` 只数 spans，hints 不掺入。

**1c. 签名**：`analyze_essay_text` 每句加 `"hints": [{type:"prep_case"|"np_case", start, end, label}]`（句内 char offset，与 spans 对齐）。`"version"` → `"4.1.0"`。`nlp=None` 不变（sentences=[] 无 hints）。server 各端点透传 analysis_json 无需改；旧 essay 无 hints 键 → 前端默认 `[]`。

### 2. 后端测试 `test_writing_rules.py`

**改 3 处版本断言**：`test_no_spacy_returns_empty`(:63)、`test_multi_sentence_analysis`(:82)、`test_analyze_essay_pure_python_fallback`(:92) 的 `"4.0.0"` → `"4.1.0"`。

**新增 6 测**（offset 已对真实 sm 模型核实）：
- `test_prep_hint_fixed_case`："mit der Auto." 含 `{"type":"prep_case","label":"mit [Dat]","start":10,"end":13}`
- `test_prep_hint_two_way`："in der Stadt." 含 `label=="in [Dat/Akk]"`（hint 与无错误并存 = spec #4）
- `test_prep_hint_verb_collocation`："wartet auf dem Bus." 含 `label=="auf [Akk]"`（warten auf），错误 span 仍 `praeposition`
- `test_np_hint_gender_case_label`："mit der Auto." 含 `{"type":"np_case","label":"[Neut·Dat]","start":18,"end":22}`
- `test_hints_coexist_with_error_spans`：同一句 `len(spans)>=1` **且** 有 prep_case hint（documents spec #3）
- `test_hints_key_present`：每句有 `hints` list；顶层键恰为 `{version, cefr, error_count, sentences}`

### 3. 前端 HTML

- `#ide-error-tooltip`(:867) 后加 `<div id="ide-hint-layer" class="ide-hint-layer hidden"></div>`（**body 直接子级**，不进 `#ide-editor`，text 节点永不进 innerText）。
- `.writer-tools-right`(:460) 加全局开关 `<button id="writer-inlay-toggle" onclick="toggleInlayHints()">💡 格提示 ON</button>`。

### 4. 前端 JS `writer.js`

- 模块状态 `inlayEnabled=true`、`inlayRafId=0`。
- `toggleInlayHints()`：翻转 + 更新按钮文案 + position/clear。
- **`positionInlayHints()`**（覆盖层算法）：
  - `#ide-hint-layer` 是 body 直接子级 → offsetParent=html，用**文档坐标**（`getClientRects` 视口坐标 + `window.scrollX/Y`）。页面滚动 layer 与文本同移（与 tooltip 同约定）。
  - 逐句 `currentAnalysis.sentences`，`.ide-sent-block[data-sent-idx]` 内 `findCharRange(block, h.start, h.end)` → `getClientRects()` 取**最底一行** rect（处理换行）→ 在词尾 + GAP(5) 处放 badge（`transform: translateY(-50%)` 垂直居中）。`textContent` 渲染 label。
- **`findCharRange(block, start, end)`**（风险点，TreeWalker）：单次 SHOW_TEXT TreeWalker 累计 `startOffsets`；`e > off` 的终点规则让 end 落在节点边界时解析到前一节点全长度（`[start,end)` = 完整词）；`getClientRects()` 返回已含 `#ide-editor` 内部 `scrollTop` 的视口坐标，加 `window.scroll` 转文档坐标。
- **刷新触发**：`renderEditor` 每分支末尾 `positionInlayHints()`（scrollTop 设定后）；`analyzeWriterText` 顶部 `clearInlayHints()`（防陈旧 badge）；`clearWriterForm` 加 `clearInlayHints()`；`setupEditorListeners` 加 editor scroll(节流 rAF) + `ResizeObserver` + window resize。
- **不加 window.scroll 监听**：layer 用文档坐标，页面滚动自动跟随。只覆盖 editor 内部滚动 + 重排（上述已含）。
- `main.js` 把 `toggleInlayHints` 加进 writer import + window 全局。

### 5. 前端 CSS

`.ide-hint-layer`（absolute、z-index:50 低于 modal 100/tooltip 1200、`pointer-events:none` 防抢光标）+ `.hidden{display:none}`；`.inlay-hint`（mono 小字、badge、`translateY(-50%)`）；`.inlay-prep`（琥珀）+ `.inlay-np`（蓝）。**不嵌套进 `.writer-card-box`**（其 `position:relative` 会成为包含块、文档坐标算崩）。

### 6. PR 切片

1. **后端 hints**（独立可合）：`writing_rules.py` + 测试 3 改 6 新。
2. **前端覆盖层**：index.html + writer.js + main.js + style.css。147 后端测试全绿。
3. **文档**：FEATURES v4.1.0 行、README、`?v=4.1.0`。

### 7. 风险

1. **np-hint case 是 spaCy 解析格**：主语位置名词可能标 `Nom` 即使句意要别的格（"Ich sehe der Mann."→`[Masc·Nom]`）——这是"实际格"教学信号，FEATURES 注明。
2. `esc()` 保持只转实体（core.js:25），`block.textContent===s.text` 映射依赖它。
3. **勿嵌套** hint-layer 进任何 transformed/positioned 包裹元素。

## 验证方式

1. `pytest` 全绿（147 现有 + 6 新，预计 ~153）。
2. 手动：写 "Ich fahre mit der Auto." → `mit [Dat]` + `[Neut·Dat]` badge + "der Auto" 波浪线 + hover 不变 → 开关按钮隐藏/显示 → 滚动 editor/页面/resize badge 跟踪 → 点 badge 不抢光标（落到词上）→ DevTools 比 `/analyze` 请求体与 `innerText.trim()` 一致（往返不变式）→ 打字时 badge 消失再回来。
3. 反向：写 "Ich gehe in der Stadt." → `in [Dat/Akk]` 无波浪线；"Er wartet auf dem Bus." → `auf [Akk]` + `[Masc·Dat]` + 波浪线（矛盾揭示）。
4. Android：CI 打 APK 真机 → 编辑器 + 覆盖层可用；移动端异常走手动诊断兜底。发布后不验 APK。
