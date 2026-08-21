# v4.2.0 写作台 Problems 面板：全篇错误清单 + severity 分级

## Context

v4.1.1 已发布（Inlay Hints 语法内联提示）。写作台现有：contenteditable IDE 编辑器、实时波浪线诊断、inlay hints、一键修正、hover 气泡、句子导航、存 Anki、AI 逐 hunk 审查、git 版本快照/预览/删除/恢复。用户想继续借鉴 VSCode/JetBrains。经 grilling 访谈，v4.2.0 选定 **Problems 面板**（全篇错误清单 + severity 分级）—— 写作台从"逐句诊断工具"升级为"全局错误视图"（VSCode 的灵魂）。本文件是实现方案。

## 已锁定的决策（grilling 结论，不回头改）

| # | 决策 | 值 |
|---|---|---|
| 1 | 方向 | **Problems 面板**（VSCode 式全篇错误清单） |
| 2 | severity 三级 | `error`（高置信错误）/ `warning`（双格介词方向不确定）/ `info`（inlay hints） |
| 3 | 面板范围 | 面板**只列 error + warning**；info（inlay hints）已就地展示，不进面板（太噪） |
| 4 | warning 来源 | **双格介词方向不确定**（in/an/auf/über…）→ 提醒"这里 Dat/Akk 皆可，看方向"。非错误，是提醒 |
| 5 | 排序 | **按 severity 分组，error 最前**，组内按句序 |
| 6 | severity 计算 | **后端 `analyze_essay_text` 算**（集中、可测）；span 加 severity + 新增双格介词 warning 检测 |
| 7 | 跳转 | 点问题 → 复用现有 `jumpToSentence(sentIdx)` 滚动定位 + 高亮错误标记 |
| 8 | 面板位置 | 写作侧栏**加「问题」tab**（现有 诊断/版本历史 tab 旁） |
| 9 | 版本 | v4.2.0（versionCode 40200），bump `?v=` / CACHE_NAME |

## v4.1 现状（已核实，直接复用）

- `writing_rules.py`：`analyze_essay_text(text, nlp=None)` → `{version,cefr,error_count,sentences:[{text, spans:[{error_type,corrected_form,explanation_zh,start,end}], hints:[{type,start,end,label}]}]}`。`_TWO_WAY_PREPS` 集合、`_prep_expected_case(tok)`（返回 `(case|None, source)`，source ∈ {collocation,twoway,fixed,none}）已有。错误 span 全 FP-guarded（高置信）。
- `writer.js`：侧栏 tab（`switchWriterPanelTab`）、`renderEditor`、`updateAnalysisPanels`、`jumpToSentence`、`currentAnalysis`、错误 mark `<mark class="writer-err-underline err-{type}" data-sent data-span>`。
- `static/index.html`：`#view-writer`、`#writer-panel`。
- 158 测试绿。

## 实现方案（Plan agent 设计）

### 1. 后端 `writing_rules.py`

**数据模型：Option a —— 保留 `spans` 形状 + 加 severity + 新增 `warnings[]`**（不合并成 problems[]）。理由：`spans` 被 renderEditor/selectWriterSpan/fixSelectedSpan/存卡 sugar 按索引引用，合并会破坏索引重映射。warning 无 corrected_form、无一键修正、无存卡，结构不同，合并会带 null 字段。

`analyze_essay_text` 新输出：
```python
{"version": "4.2.0", "cefr": {...}, "error_count": N,   # N = span 数（essays.error_count 语义不变）
 "warning_count": M, "problem_count": N+M,               # 新增
 "sentences": [{"text", "spans": [{"error_type","corrected_form","explanation_zh","start","end","severity":"error"}],
                "hints": [...],                          # 不变（info 级，就地展示）
                "warnings": [{"severity":"warning","error_type":"twoway","label":"注意：in [Dat/Akk]",
                              "explanation_zh":"「in」是静动态双格介词：这里 Dat/Akk 皆可，请根据动作方向判断。",
                              "start","end"}]}]}
```
- `error_count` 保持 span 派生（essays 表列语义不变，无 schema 迁移）。
- `test_hints_key_present` 的精确键断言需更新。

**warning 检测器** `_collect_prep_warnings(tokens, base)`：每个 `ADP` → `_prep_expected_case(tok)`；`source=="twoway"` → emit warning。复用现有 `_TWO_WAY_PREPS` + `_prep_expected_case`（零新介词数据）。label 格式 `注意：{tok.text} [Dat/Akk]`（镜像 hint 的 label）。句循环里 wire 进 `warnings` + 顶层 `warning_count`。**无需 FP 守卫**——是提醒不是错误。

### 2. 后端测试 `test_writing_rules.py`

**更新**：`test_no_spacy_returns_empty`(:59)、`test_multi_sentence_analysis`(:79)、`test_analyze_essay_pure_python_fallback`(:89) 的 version → `"4.2.0"`（+ 断言 `warning_count==0`）；`test_hints_key_present`(:135) 精确键 → `{version,cefr,error_count,warning_count,problem_count,sentences}`。

**新增 4 测**：
- `test_two_way_prep_emits_warning_not_span`：`in der Stadt.` → spans==[] **且** warnings 非空；warnings[0] severity=warning、error_type=twoway、label 含"注意"+"in"、explanation 含 Dat/Akk。（现有 `test_two_case_preposition_skipped` 守住 spans 侧）
- `test_span_has_severity_error`：`der Mann.` → spans[0].severity==error
- `test_warning_and_error_counts`：`in der Stadt. der Mann.` → error_count==1、warning_count==1、problem_count==2、len(sentences)==2
- `test_warning_positions_are_char_offsets`：warning start<end、start>=0、end<=len(text)

`test_server.py` 不受影响（只断言 sentences[0].spans 存在）。`test_android_version_code_encoding` 自动验证 gradle bump。

### 3. 前端（index.html + writer.js + main.js + style.css）

- **index.html**：`.writer-panel-tabs`(:482) 加 `<button id="wtab-btn-problems" onclick="switchWriterPanelTab('problems')">📋 问题清单</button>`；`wpane-diag`(:516) 后加 `wpane-problems`（摘要卡 + `#writer-problem-list`）。
- **writer.js**：
  - `switchWriterPanelTab` 重构为 `WRITER_TABS` 泛化 map（diag/problems/versions，含 onShow 回调）——保版本 tab "onShow 才加载"行为。
  - `renderProblemsPanel(a)`：flatten spans(error)→{sentence_idx,span_idx,...} + warnings(warning)→{sentence_idx,warning_idx,...}；sort severity error 前→warning，tiebreak 句序→start；渲染按 severity 分组 + 每行 badge/label/句位置/句 snippet。防御性 `a?.sentences||[]`。
  - `openWriterProblem(sentenceIdx, kind, idx)`：`jumpToSentence(sentenceIdx)`（滚动+flash）；kind=error 时再 `selectWriterSpan(sentenceIdx, idx, null)`（高亮 mark + 侧栏详情 + selectedSpanRef，可一键修正/存卡）。warning 无行内 mark，句子 flash 即提示。
  - hook：`updateAnalysisPanels` 末尾 `renderProblemsPanel(a)`（每次 renderEditor 同步）；tab onShow 兜底。`openWriterProblem` 加进 export + main.js import + window 全局。
- **style.css**：`.writer-problem-list`（flex column，max-height ~320px 溢出滚动，镜像 `.writer-version-list`）、`.writer-problem-row`（card 式 hover）、`.writer-problem-badge.sev-error`(cherry)/`.sev-warning`(amber)、`.writer-problem-group-header`、`.writer-problem-pos/-preview`。空态复用 `.writer-empty-tip`。复用现有 `.writer-pane`/`.writer-pane.hidden`。

### 4. 版本 bump v4.2.0 / 40200

`writing_rules.py:358` version→"4.2.0"；`android/app/build.gradle` versionCode 40200 / versionName "4.2.0"（4*10000+2*100+0，编码自动验证）；`sw.js` CACHE_NAME `delector-static-v4.2.0` + `?v=4.1.1`→`4.2.0`（3 个资产）；`index.html:13/:22/:1155` `?v=` + "System · v4.1.1 Online"→v4.2.0。Release 文档（FEATURES/README/AGENTS）加 v4.2.0 行。

### 5. PR 切片

1. **后端**（独立可合）：writing_rules + 测试（4 新 + 3 更新）。前端无依赖（Slice 2 前面板渲染空）。
2. **前端面板 + cache bust**：index.html + writer.js + main.js + style.css + sw.js bump。对旧 analysis_json 防御（`warnings||[]`）。
3. **发版加固**：gradle bump + 手动测试（双格+错误文本→面板 error 在前、点 error→滚动+高亮+可修正、点 warning→句子 flash、空态、切换版本 tab 仍加载）+ 文档。

## 验证方式

1. `pytest` 全绿（158 现有 + 4 新，预计 ~162）。
2. 手动：写 "Ich gehe in der Stadt. Ich sehe der Mann." → 侧栏「问题清单」tab → 面板 error（der Mann）在前 + warning（in [Dat/Akk]）在后 → 点 error → 编辑器滚动到句 + 高亮 mark + 侧栏可一键修正/存卡 → 点 warning → 句子 flash → 空文本 → 空态 → 切「版本快照」tab 仍加载。
3. 反向：写纯双格句 "in der Stadt." → 面板只有 warning 无 error；"mit dem Auto."（正确）→ 面板空。
4. Android：CI 打 APK 真机 → 编辑器 + 问题面板可用；移动端异常走手动诊断兜底。发布后不验 APK。
