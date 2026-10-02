# v3.12.0 写作台 IDE 化：AI 润色逐条审查 + 类 git 版本管理

## Context

v3.11.0 已发布（写作台：本地规则诊断 + 错误→Anki 卡 + AI 润色全文按钮）。用户反馈：AI 润色现在是**整篇替换**，不可逐条选择；写作台没有版本概念。v3.12 把写作台做成"真的 IDE"：AI 润色像 AI agent 那样**逐 hunk 接受/拒绝**（Claude Code / GitHub PR review 式），加**类 git 版本管理**（快照历史 + 提交信息 + 可逆恢复）。经 grilling 访谈，设计树闭合（见下）。本文件是实现方案。

## 已锁定的决策（grilling 结论，不回头改）

| # | 决策 | 值 |
|---|---|---|
| 1 | 范围 | AI 逐条审查 + 版本管理**一起做**（共享 difflib 基础设施，体验闭环） |
| 2 | AI 粒度 | AI 返回整篇改写 → 服务端 `difflib` 句子级 diff → 逐 hunk 并排审查（健壮，防 AI 偏移） |
| 3 | 版本深度 | 快照历史（content + analysis_json + 提交信息 + 时间）。**版本间 diff、分支推迟** |
| 4 | 审查交互 | 并排 diff（左原文 \| 右 AI 改写），逐 hunk 接受/拒绝 + 全部接受/全部拒绝 |
| 5 | 提交耦合 | 显式提交，提交信息自动预填（`AI 润色 · 接受 X/Y 处`）可改 |
| 6 | 提交触发 | 手动「保存版本」+ **AI 润色应用后自动存一个版本**（防丢稿） |
| 7 | 历史 UI | 写作侧栏加「版本历史」tab（列表 + 恢复按钮） |
| 8 | 恢复可逆 | 恢复前自动把当前草稿存成版本（`恢复到版本 N 之前`），误点不丢稿 |
| 9 | AI 不缓存 | 沿用 v3.11：AI 润色是显式付费按钮，无缓存 |
| 10 | 版本 | v3.12.0（versionCode 31200），bump `?v=` / CACHE_NAME |

## v3.11 现状（已核实，直接复用）

- `POST /api/writing/ai-polish` → `{result:{corrected_text, notes_zh, error_count}}`，前端整体替换 textarea
- `essays` 表：id/title/content/analysis_json/cefr_level/error_count/sentence_count/created_at/updated_at，CRUD `/api/essays*`
- `writing_rules.analyze_essay_text(text, nlp=None)` → analysis_json（`{version,cefr,error_count,sentences:[{text,spans:[{error_type,corrected_form,explanation_zh,start,end}]}]}`）
- 前端 `static/js/writer.js`（`renderHighlightedText`、`#writer-panel` 侧栏、`aiPolishEssay()`）、`#view-writer`、`.writer-*`/`.err-*` CSS
- 129 测试绿；无 JS 构建步（vanilla ESM）；Python stdlib `difflib` 可用

## 实现方案

### 1. Schema + 迁移（server.py `init_db` :133-250）

**新表 `essay_versions`**（仿现有 `CREATE TABLE IF NOT EXISTS` + 幂等迁移）：
```sql
CREATE TABLE IF NOT EXISTS essay_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    essay_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    analysis_json TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_essay_versions_essay_id ON essay_versions(essay_id, id DESC);
```
- **不用 FK**（sqlite 未开 foreign_keys）—— 在 `delete_essay` 里显式 `DELETE FROM essay_versions WHERE essay_id=?`。
- **seed v1**：`init_db` 末尾幂等 INSERT，把无版本的既有 essay 补一条 `message='初始快照'` 快照（否则老 essay 的"恢复"死掉）：
```sql
INSERT INTO essay_versions (essay_id, content, analysis_json, message)
SELECT id, content, analysis_json, '初始快照' FROM essays
WHERE id NOT IN (SELECT DISTINCT essay_id FROM essay_versions);
```

### 2. 新模块 `essay_diff.py`（纯 stdlib，无 spaCy，可独立测试）

```python
def split_sentences(text) -> List[str]:      # 委托 syntax_tree.split_sentences_pure_python（确定性、保标点）
def diff_sentences(original, corrected) -> List[dict]:
    # difflib.SequenceMatcher 按句子；跳过 equal，每段连续不等 = 一个 hunk {"old":[..],"new":[..]}（任一侧可空=纯增删）
def merge_sentences(original, corrected, accepted: List[bool]) -> str:
    # 重走 opcodes：equal→原句；hunk i accepted→改句，否则原句；单空格重接
def join_sentences(sents) -> str: ...
```

### 3. 后端端点（server.py，都放在 ai-polish 之后）

- **重构 `_ai_polish_call(text)`**：抽出现有 ai-polish 的 LLM 调用（一次性、无缓存、无 key→stub）。旧 `POST /api/writing/ai-polish` 契约不变（内部改用 helper），老测试不受影响。
- **`POST /api/writing/ai-polish/diff`** `{text}`→`{result:{original, corrected, hunks:[{old,new,accepted}], notes_zh, error_count}}`。默认 `accepted:true`（UI 从全接受开始）。stub 时 corrected==original → hunks=[]。
- **`POST /api/writing/apply`** `{essay_id, original_text, corrected_text, accepted_indices:[]}`→`{content, analysis_json, error_count, version_id}`。
  1. 服务端用回传的原文/改文**重算 diff**（同 splitter，保证索引与 UI 显示一致）→ 校验 indices（越界 400）→ `merge_sentences`。
  2. merged != 当前 content 才写库 + 重分析 + **自动提交**（`message=f"AI 润色 · 接受 {sum(accepted)}/{len(hunks)} 处"`）；全拒则返回原 content、`version_id: None`（**不存垃圾快照**）。
  3. essay_id 必填；前端草稿先自动建 essay（仿 `saveWriterErrorAsCard`）。
- **`POST /api/essays/{id}/versions`** 手动保存版本（`message` 可空，默认"手动保存"）→ `{version_id, message, created_at}`。
- **`GET /api/essays/{id}/versions`** → `[{id, message, created_at, error_count}]`（`json_extract(analysis_json,'$.error_count')`）新→旧。
- **`POST /api/essays/{id}/restore`** `{version_id}`：
  1. 目标版本 content != 当前 content → **先自动存当前草稿**（`message=f"恢复到版本 {version_id} 之前"`，相同则跳过）。
  2. 重分析目标 content → 写库 → 返回 `{content, analysis_json, error_count, checkpoint_version_id}`。

### 4. AI 提示词微调

`SYSTEM_WRITING_POLISH_PROMPT`（server.py:2384）加一行："请尽量逐句润色，保持句子的结构与出现顺序，不要合并或拆分句子，除非确实必要。"（让 hunks 干净，无测试钉此文案，安全。）

### 5. 前端（writer.js + index.html + style.css）

- **侧栏加 tab**：`#writer-panel` 顶部 `wtab-diag`（诊断，现有内容）+ `wtab-versions`（版本历史：保存版本卡 + 版本列表）。仿 `switchDrawerTab` 模式写 `switchWriterPanelTab`。
- **润色审查弹窗** `#polish-overlay`（仿 `#settings-overlay` hidden 模式）：工具栏（摘要 + 全部接受/全部拒绝）+ `#polish-diff`（hunks）+ 备注 + 底部「应用所选更改/取消」。
- **`writer.js`**：`polishState={original,corrected,hunks,accepted}`；`aiPolishEssay()` 改为调 `/diff` + 开弹窗渲染；`renderPolishReview()` 每 hunk 并排 `.diff-grid`（左 `.diff-old` 原句 | 右 `.diff-new` 改句）+ ✓/✕ 按钮；接受→改句高亮、拒绝→原句高亮；`applyPolishChanges()` 调 `/apply` → 写回 textarea + `renderWriterReport` + 重载版本列表 + `Companion.celebrate('polish_apply')`；`saveEssayVersion/restoreEssayVersion/loadEssayVersions`。
- **CSS**：`.writer-panel-tabs/-tab/-pane`、`.diff-hunk/-grid/-old/-new/-sent`、`.hunk-accepted/-rejected`、`.version-item`、`.polish-*`。窄屏 `.diff-grid` 纵排（桌面并排、移动堆叠）。
- **版本 bump 3.12.0**：`writing_rules.py:262` `"version"` → "3.12.0"（+ test_writing_rules 两处断言）、index.html `?v=`、sw.js CACHE_NAME、android versionCode 31200 / versionName "3.12.0"。

### 6. 测试

- **新 `test_essay_diff.py`**（纯模块）：相同→[]、单句改动→1 hunk、多句改动保序、连续改动并成 1 hunk（锁粒度契约）、纯增/纯删、接受一个拒一个的 merge、全拒 roundtrip、插入位置、切句保标点。
- **test_server.py 增**：essay_versions 建表、seed v1、保存+列表（新→旧）、不存在 essay 404、**恢复可逆**（v1→存 A→改 v2→存 B→恢复 A→版本列表含"恢复到版本 A 之前"检查点）、恢复相同跳过检查点、**ai-polish/diff**（无 key stub + monkeypatch httpx 断言 2 hunks）、**apply 写回+自动提交**（message 含"接受 1/2 处"）、全拒无版本（version_id None、版本数不变）、越界 400、删除 essay 连带删版本。

### 7. PR 切片

1. **Diff 引擎 + 审查端点**（无版本）：`essay_diff.py` + 测试 + `_ai_polish_call` 重构 + 提示词微调 + `/ai-polish/diff`。
2. **版本后端 + apply**：`essay_versions` 表 + seed + 删除级联 + 4 版本端点 + `/apply` + version 字段 bump 3.12.0。
3. **前端 + 文档**：tab + 弹窗 + writer.js + CSS + main.js 接线 + AGENTS/FEATURES/README。

### 8. 风险

1. **difflib 对大量重写的对齐质量**：整段重排会塌成几个大 hunk（粒度粗但 merge 仍正确，因为走 opcodes 不靠偏移）。提示词保序缓解。
2. **essay_versions 表增长**：全量快照 × (每次 AI 应用 + 手动保存 + 恢复检查点)。全拒/相同跳过已缓解；"保留最近 N" 后置（YAGNI）。
3. **移动端并排 diff 挤**：窄屏 `.diff-grid` 纵排兜底。
4. **merge 用单空格重接**：被拒 hunk 的段落空行会折叠。textarea 草稿可接受，标注为有意为之。

## 验证方式

1. `pytest` 全绿（129 现有 + 新增 ~20，预计 ~150）。
2. 手动：写作台 → 粘含错作文 → 点 AI 润色 → 弹窗并排 diff 逐 hunk 接受/拒绝 → 应用 → 侧栏版本历史出现"AI 润色 · 接受 X/Y 处"→ 手动存版本 → 改内容 → 恢复旧版本 → 版本列表出现"恢复到版本 N 之前"检查点 → 撤销恢复。
3. **反向**：全拒 → 无新版本、内容不变。无 key → 弹窗显示配置提示而非空审查。
4. 老 essay（无版本）升级后 → 版本历史自动有"初始快照"。
5. Android：CI 打 APK 真机装 → 写作台可用（sm 模型不崩）；验签闸沿用 v3.10/v3.11 流程。发布后不验 APK（已记偏好）。
