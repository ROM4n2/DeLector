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
