# AGENTS.md — DeLector 项目 AI Agent 交接文档

> **每次开新 agent 对话时，第一步必须读这个文件。**
> 这是机器可读的项目快照，用于最短时间内重建完整 context。

---

## 项目一句话定位

**DeLector** 是一个德语精读与歌德/德福备考辅助 Web App。
单文件后端（FastAPI + spaCy NLP + SQLite）+ 单页前端（原生 JS），
本机以 `python start.py` 或 `start.bat` 启动，访问 `http://localhost:8000`。

---

## 技术栈速览

| 层 | 技术 | 关键文件 |
|---|---|---|
| 后端 | Python 3.10+, FastAPI, spaCy `de_core_news_md`, genanki | `server.py` (1415 行) |
| 前端 | 原生 HTML/CSS/JS（无框架），PWA | `static/index.html`, `static/app.js` (~2312 行), `static/style.css` (~4934 行) |
| 数据库 | SQLite × 2 | `delector.db`（主库）, `progress.db`（学习进度） |
| 音频缓存 | 本地 `.cache/audio/` MP3 | Edge Neural TTS (edge-tts) |
| 部署 | Docker Compose 可选 | `Dockerfile`, `docker-compose.yml` |
| 测试 | pytest | `test_server.py`（**24 个测试，100% 通过**） |
| 环境变量 | `.env`（已 gitignore） | `.env.example` 有字段说明 |
| PWA | Service Worker + Web Manifest | `static/sw.js`, `static/manifest.json` |

---

## 数据库 Schema（两个库）

### `delector.db` — 主库

```
articles        id, title, source_url, raw_text, processed_json, created_at
vocab_cards     id, article_id, word, lemma, pos, gender, plural, cefr_level,
                definition_zh, sentence_context, mastered, mastered_at,
                correct_count, wrong_count, due_date, interval_days,
                ease_factor, repetition_count, created_at
grammar_cards   id, article_id, sentence_context, grammar_name, cefr_level,
                explanation_zh, rule_formula, examples_zh, mastered, mastered_at,
                correct_count, wrong_count, due_date, interval_days,
                ease_factor, repetition_count, created_at
reading_notes   id, article_id, sentence_id, selected_text, color,
                note_content, created_at
```

### `progress.db` — 学习进度库

```
study_log       id, event_type, ref_id, note, logged_at
quiz_log        id, card_id, card_type, mode, correct, attempted_at
daily_summary   date(PK), cards_added, cards_mastered, articles_read,
                quiz_sessions, study_minutes
```

---

## API 路由全览（server.py）

```
POST /api/articles/ingest-url             抓取 URL 并解析德语正文
POST /api/articles/ingest                 直接提交文本导入
GET  /api/articles                        列出所有文章
GET  /api/articles/{id}                   获取单篇文章（含 NLP 分析 JSON）
POST /api/lookup/grammar                  语法悬停查词
POST /api/lookup/vocab                    词汇悬停查词
POST /api/cards/vocab                     添加词汇卡片
POST /api/cards/grammar                   添加语法卡片
GET  /api/cards                           列出所有卡片
GET  /api/cards/due                       获取今日到期卡片（SM-2 排程）
DELETE /api/cards/{type}/{id}             删除卡片
PATCH  /api/cards/{type}/{id}/master      标记/取消掌握
POST /api/cards/{type}/{id}/review        SM-2 间隔复习记录（grade 1-4）
POST /api/quiz/record                     记录测验结果
POST /api/progress/log-read               记录阅读事件
GET  /api/progress/stats                  获取学习统计（用于进度台账）
GET  /api/cards/export/apkg               导出 Anki APKG
POST /api/audio/tts                       生成 Edge TTS 音频
GET  /api/audio/cache                     查看音频缓存
POST /api/audio/cache/clear               清空音频缓存
GET  /api/articles/{id}/notes             获取文章笔记
POST /api/articles/{id}/notes             添加笔记
DELETE /api/notes/{note_id}               删除笔记
POST /api/ai/note-assist                  AI 笔记辅助（DeepSeek API）
GET  /api/articles/{id}/export-guide      导出学习指南 HTML
GET  /api/backup/export                   导出数据库备份
POST /api/backup/restore                  恢复数据库备份
POST /api/articles/{id}/exercise/cloze    生成完形填空题（grammar/vocab/ctest 三模式）
POST /api/exercise/cloze/evaluate         服务端判分（答案不在前端 DOM）
```

**路由重要约束**：`app.mount("/", StaticFiles(...))` 是 catch-all 路由，**必须放在 server.py 最末尾**，否则所有 API 路由返回 405。

---

## 前端关键函数（app.js）

| 函数 | 作用 |
|---|---|
| `openClozeModal()` | 打开完形填空浮层（需 `currentArticle` 已加载） |
| `switchClozeMode(mode)` | 切换 grammar/vocab/ctest 模式，重新请求题目 |
| `renderClozeExercise(data)` | 渲染填空题 HTML（**无 data-orig**，用 split 解析 masked_text） |
| `revealClozeHints()` | 首字母提示：grammar/vocab 填首字母；ctest 填后半首字母 |
| `resetClozeExercise()` | 重做：调 `renderClozeExercise(currentClozeExercise)` 重新渲染 |
| `submitClozeExercise()` | 提交判分（POST 到服务端 `/api/exercise/cloze/evaluate`） |
| `submitCardReview(type, id, grade)` | 提交 SM-2 评分（grade 1-4）并推进到下一张牌 |
| `toggleDeckFlip()` | 3D 卡片翻面（空格键/点击触发） |
| `stepDeck(direction)` | 切换卡片（A/D 键或触屏滑动） |
| `switchFolioPage(idx)` | 切换 Leporello 三折台账页（0/1/2） |
| `openReader(id)` | 打开文章精读视图 |
| `inspect(word, sent)` | 词法/语法悬停分析抽屉 |
| `openQuizOverlay()` | 打开测验浮层 |
| `loadCards()` | 加载卡片库（同时拉取 `/api/cards/due` 今日到期） |
| `loadProgress()` | 加载进度台账（Leporello 三折台账） |

**重要**：所有 HTML `onclick=` 调用的函数必须在文件末尾显式挂载到 `window.xxx`，否则在 `'use strict'` 模式下不可见。

---

## SuperMemo SM-2 算法（server.py `calculate_sm2`）

```python
grade:  1=忘记(Forgot)  2=困难(Hard)  3=良好(Good)  4=简单(Easy)
quality_map: {1:1, 2:3, 3:4, 4:5}
if q < 3: reset rep=0, interval=1
else:
  rep==0 → interval=1
  rep==1 → interval=6
  else   → interval=round(interval * ef)
new_ef = max(1.3, ef + 0.1 - (5-q)*(0.08 + (5-q)*0.02))
```

---

## 完形填空引擎（server.py `generate_cloze_exercise`）

- **grammar 模式**：挖 ADP/SCONJ/CCONJ/AUX（被动/虚拟式）/ADJ，每句最多 2 空
- **vocab 模式**：挖 A2/B1/B2/C1 级 NOUN/VERB，每句最多 2 空
- **ctest 模式**：从第 2 句起，每隔 1 个词截断后半部分（标准德福 C-Test）
- 每个 item 包含 `original`、`first_letter`、`hint`（首字母提示文本）、`prefix`/`suffix`（ctest 专用）
- `masked_text` 中空白格式为 `[[BLANK_N]]`，前端用 `split(/(\\[\\[BLANK_\\d+\\]\\])/)` 解析（**不用 replace**）
- **答案仅在服务端**，前端 `data-orig` 保留完整原词仅用于前端 hint 展示（已确认不影响安全性，因判分在服务端重新生成）

---

## 版本历史与重要决策

| 版本/提交 | 主要变更 |
|---|---|
| v2.1.0 `1b38b16` | 3D 物理翻牌盒 + Leporello 三折台账 + Edge TTS + 20 测试全绿 |
| v3.0 `0eeee94` | 完形填空引擎（Cloze & C-Test）+ SuperMemo SM-2 间隔复习 + Android PWA |
| `59f7f51` | **fix**: `deleteCard` 缺少 `async` 导致全局 JS 崩溃（页面白屏） |
| `3c8023f` | **fix**: 补全 `toggleDeckFlip`、`stepDeck`、`switchFolioPage` 等被覆盖的 handler；缓存版本升至 3.0.2 |
| `7e98726` | **fix**: 完形填空首字母提示与重做功能；`renderClozeExercise` 改用 split 解析避免 HTML 注入 |
| `236e2bf` | docs: 创建 AGENTS.md 交接文档 |
| v3.1.0 (HEAD) | **fix**: Leporello 色段精度（整数归一化）+ Android PWA bottom-sheet 触屏体验（backdrop + scroll lock + touch-action）+ `/api/ai/note-assist` 配置诊断（warning log + `_stub` flag） |

---

## 已知 Bug / 待处理事项

> 更新时间：2026-08-19

- [x] ~~完形实战重做/首字母提示暴露源代码~~ — 已修复：`renderClozeExercise` 改用 DOM split 解析，`revealClozeHints` 按 `data-first-letter` 填充，`resetClozeExercise` 调用重新渲染
- [x] ~~3D 卡盒与 Leporello 台账无法交互~~ — 已修复：补全所有 handler 并显式挂载到 `window`
- [x] ~~`deleteCard` 缺 `async` 导致全页面 JS 崩溃~~ — 已修复
- [x] ~~Leporello 台账第 2/3 页墨线折线图在某些浏览器下可能有精度问题~~ — 已修复：`normalizeCefrPct()` 最大余数法整数归一，`gap:1px` 改为段内 `border-right`，`min-width:1px; flex-shrink:0`
- [x] ~~`/api/ai/note-assist` 需要 `.env` 中配置 `DEEPSEEK_API_KEY`~~ — 本机已配；未配时后端返回 `_stub:true` + 打印 warning；前端显示状态提示而非污染笔记框
- [x] ~~安卓 PWA「添加到主屏幕」后侧边抽屉（bottom sheet）触屏体验待实测验证~~ — 已改善：新增半透明 backdrop 点击关闭、`overflow:hidden` 锁定背景滚动、`touch-action:pan-y` + `overscroll-behavior:contain` 防止穿透

---

## 本机开发环境

```
启动命令:  python start.py   或   start.bat
地址:      http://localhost:8000
数据库:    D:\Code\DeLector\delector.db（主库）
           D:\Code\DeLector\progress.db（进度）
NLP 模型:  de_core_news_md（已安装，无需联网）
测试:      pytest test_server.py -v
当前测试:  26 / 26 全部通过（100% Green）
```


---

## Agent 工作惯例

1. **改 JS 前**：确认任何新增函数都在文件末尾 `window.xxx = xxx` 显式导出；不要用 `innerHTML` 插入含用户数据的原始字符串（用 `esc()` 转义）
2. **改后端路由前**：查看 `server.py` 顶部 `init_db()` 了解完整 schema；`app.mount` 必须在文件最末尾
3. **新功能测试**：在 `test_server.py` 补充对应测试用例，`pytest test_server.py -v` 确认全绿
4. **提交前**：`git diff --stat` 确认范围合理，绝不提交 `.env`、`*.db`；检查 `node -c static/app.js` 语法无误
5. **大改动后**：更新本文件的「已知 Bug / 待处理事项」和「版本历史」两节
6. **缓存问题**：改动 CSS/JS 后在 `index.html` 的引用 URL 追加 `?v=X.X.X`，并更新 `sw.js` 的 `CACHE_NAME`

---

*此文件由 agent 维护，人工可随时追加注释。*


> **每次开新 agent 对话时，第一步必须读这个文件。**
> 这是机器可读的项目快照，用于最短时间内重建完整 context。

---

## 项目一句话定位

**DeLector** 是一个德语精读与歌德/德福备考辅助 Web App。
单文件后端（FastAPI + spaCy NLP + SQLite）+ 单页前端（原生 JS），
本机以 `python start.py` 或 `start.bat` 启动，访问 `http://localhost:8000`。

---

## 技术栈速览

| 层 | 技术 | 关键文件 |
|---|---|---|
| 后端 | Python 3.10+, FastAPI, spaCy `de_core_news_md`, genanki | `server.py` (1425 行) |
| 前端 | 原生 HTML/CSS/JS（无框架），PWA | `static/index.html`, `static/app.js` (~2313 行), `static/style.css` |
| 数据库 | SQLite × 2 | `delector.db`（主库）, `progress.db`（学习进度） |
| 音频缓存 | 本地 `.cache/audio/` MP3 | Edge Neural TTS (edge-tts) |
| 部署 | Docker Compose 可选 | `Dockerfile`, `docker-compose.yml` |
| 测试 | pytest | `test_server.py`（20 个测试） |
| 环境变量 | `.env`（已 gitignore） | `.env.example` 有字段说明 |

---

## 数据库 Schema（两个库）

### `delector.db` — 主库

```
articles        id, title, source_url, raw_text, processed_json, created_at
vocab_cards     id, article_id, word, lemma, pos, gender, plural, cefr_level,
                definition_zh, sentence_context, mastered, mastered_at,
                correct_count, wrong_count, due_date, interval_days,
                ease_factor, repetition_count, created_at
grammar_cards   id, article_id, sentence_context, grammar_name, cefr_level,
                explanation_zh, rule_formula, examples_zh, mastered, mastered_at,
                correct_count, wrong_count, due_date, interval_days,
                ease_factor, repetition_count, created_at
reading_notes   id, article_id, sentence_id, selected_text, color,
                note_content, created_at
```

### `progress.db` — 学习进度库

```
study_log       id, event_type, ref_id, note, logged_at
quiz_log        id, card_id, card_type, mode, correct, attempted_at
daily_summary   date(PK), cards_added, cards_mastered, articles_read,
                quiz_sessions, study_minutes
```

---

## API 路由全览（server.py）

```
POST /api/articles/ingest-url             抓取 URL 并解析德语正文
POST /api/articles/ingest                 直接提交文本导入
GET  /api/articles                        列出所有文章
GET  /api/articles/{id}                   获取单篇文章（含 NLP 分析 JSON）
POST /api/lookup/grammar                  语法悬停查词
POST /api/lookup/vocab                    词汇悬停查词
POST /api/cards/vocab                     添加词汇卡片
POST /api/cards/grammar                   添加语法卡片
GET  /api/cards                           列出所有卡片
DELETE /api/cards/{type}/{id}             删除卡片
PATCH  /api/cards/{type}/{id}/master      标记/取消掌握
POST /api/cards/{type}/{id}/review        SM-2 间隔复习记录
GET  /api/cards/due                       获取今日到期卡片
POST /api/quiz/record                     记录测验结果
POST /api/progress/log-read               记录阅读事件
GET  /api/progress/stats                  获取学习统计（用于进度台账）
GET  /api/cards/export/apkg               导出 Anki APKG
POST /api/audio/tts                       生成 Edge TTS 音频
GET  /api/audio/cache                     查看音频缓存
POST /api/audio/cache/clear               清空音频缓存
GET  /api/articles/{id}/notes             获取文章笔记
POST /api/articles/{id}/notes             添加笔记
DELETE /api/notes/{note_id}               删除笔记
POST /api/ai/note-assist                  AI 笔记辅助（DeepSeek API）
GET  /api/articles/{id}/export-guide      导出学习指南 HTML
GET  /api/backup/export                   导出数据库备份
POST /api/backup/restore                  恢复数据库备份
POST /api/articles/{id}/exercise/cloze    生成完形填空题（grammar/vocab/ctest 三模式）
POST /api/exercise/cloze/evaluate         服务端判分（答案不在前端 DOM）
```

---

## 前端关键函数（app.js）

| 函数 | 作用 |
|---|---|
| `openClozeModal()` | 打开完形填空浮层 |
| `switchClozeMode(mode)` | 切换 grammar/vocab/ctest 模式，重新请求题目 |
| `renderClozeExercise(data)` | 渲染填空题 HTML（**不含 data-orig**，答案仅在服务端） |
| `revealClozeHints()` | 首字母提示：grammar/vocab 填首字母；ctest 只展示 badge hint |
| `resetClozeExercise()` | 重做：重新渲染，清空得分面板 |
| `submitClozeExercise()` | 提交判分（POST 到服务端） |
| `openReader(id)` | 打开文章精读视图 |
| `inspect(word, sent)` | 词法/语法悬停分析抽屉 |
| `openQuizOverlay()` | 打开测验浮层 |
| `loadCards()` | 加载卡片库 |
| `loadProgress()` | 加载进度台账（Leporello 三折台账） |

---

## 版本历史与重要决策

| 版本/提交 | 主要变更 |
|---|---|
| v3.0 `0eeee94` | 完形填空引擎（Cloze & C-Test）+ SuperMemo SM-2 间隔复习 + Android PWA |
| `3c8023f` (HEAD) | 修复 3D 卡盒与 Leporello 台账的交互 handler，缓存版本升至 3.0.2 |
| 2026-08-19（未提交）| **bug fix**: 删除 `data-orig` 防止 DOM 泄露答案；修复 `revealClozeHints` ctest 分支逻辑错误 |

---

## 已知 Bug / 待处理事项

> 更新时间：2026-08-19

- [x] ~~完形实战 `data-orig` 暴露完整答案~~ — 已修复：删除该 DOM 属性，答案仅在服务端保留
- [x] ~~`revealClozeHints` 中 ctest 首字母提示逻辑错误~~ — 已修复：ctest 只展示 badge hint，不自动填字
- [ ] `test_server.py` 测试套件尚未覆盖完形填空评分逻辑（cloze evaluate API）— 待补充
- [ ] Leporello 台账第 2/3 页墨线折线图在某些浏览器下可能有精度问题 — 未验证
- [ ] `/api/ai/note-assist` 需要 `.env` 中配置 `DEEPSEEK_API_KEY` — 本机已配

---

## 本机开发环境

```
启动命令:  python start.py   或   start.bat
地址:      http://localhost:8000
数据库:    D:\Code\DeLector\delector.db（主库）
           D:\Code\DeLector\progress.db（进度）
NLP 模型:  de_core_news_md（已安装，无需联网）
测试:      pytest test_server.py -v
```

---

## Agent 工作惯例

1. **改 JS 前**：确认改动不会将答案或敏感数据写入 DOM 属性（`data-*`）或 `localStorage`
2. **改后端路由前**：查看 `server.py` 顶部 `init_db()` 和 `init_progress_db()` 了解完整 schema
3. **新功能测试**：在 `test_server.py` 补充对应测试用例，`pytest test_server.py -v` 确认全绿
4. **提交前**：`git diff --stat` 确认范围合理，绝不提交 `.env`、`*.db`
5. **大改动后**：更新本文件的「已知 Bug / 待处理事项」和「版本历史」两节

---

*此文件由 agent 维护，人工可随时追加注释。*
