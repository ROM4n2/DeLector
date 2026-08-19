# AGENTS.md — DeLector 项目 AI Agent 交接文档

> **每次开新 agent 对话时，第一步必须读这个文件。**
> 这是机器可读的项目快照，用于最短时间内重建完整 context。
>
> 维护约定：本文件**只保留一份**内容。历史上曾出现整份文档被追加两遍、
> 后半段是过时副本的情况，新 agent 读到会拿到自相矛盾的项目认知。
> 更新时请就地修改，不要在文件末尾追加新版本。

---

## 交接快照

> 更新时间：2026-08-19

| 项 | 值 |
|---|---|
| 当前分支 / HEAD | `master`（含 v3.8.0 FSRS 认知自适应记忆排程器升级：DSR 状态机原生零依赖数学模型、`next_intervals` 4级预估字典与前端动态绑定），工作区干净 |
| 测试 | **67 / 67 全绿**（`test_server.py` 52 + `test_syntax_tree.py` 15） |
| 桌面端 | 正常，`python start.py` → `http://localhost:8000` |
| Android APK | **真机验证通过**，内嵌 spaCy + 德语模型 + Android 原生离线 TextToSpeech 桥接 + 多源在线 TTS 兜底 |
| 对外发布 | **v3.8.0**（2026-08-19）：FSRS 现代自适应记忆排程器升级（DSR 状态机原生数学模型、消除 Ease Hell、4 级下一轮间隔预计算字典、向下兼容 SM-2 包装） |
| 未完成的事 | 见文末「已知问题 / 待办」 |

上一轮工作（PR [#2](https://github.com/ROM4n2/DeLector/pull/2)，5 个 commit）解决了安卓版启动卡死，
并把真正的 spaCy 移植进 APK。**动 Android 相关代码前必须先读下面的「Android 独立单机版」一节**，
那里的版本互锁与 Chaquopy 行为都是踩过坑换来的，改错任何一项都会静默失效（App 照常能跑，
只是语法标注悄悄退化）。

---

## 项目一句话定位

**DeLector** 是一个德语精读与歌德/德福备考辅助 Web App。
单文件后端（FastAPI + spaCy NLP + SQLite）+ 单页前端（原生 JS ES Modules），
本机以 `python start.py` 或 `start.bat` 启动，访问 `http://localhost:8000`。
详见产品特性全览清单：[`FEATURES.md`](FEATURES.md)。

三种运行形态共用同一份后端代码：**桌面 Python**、**Windows 绿色便携版**（PyInstaller）、
**Android 独立单机版**（Chaquopy 把 CPython 嵌进 APK）。

---

## 技术栈速览

| 层 | 技术 | 关键文件 |
|---|---|---|
| 后端 | Python 3.10+, FastAPI, spaCy, genanki | `server.py`（1966 行） |
| 词法/形态学 | 556+ 不规则动词三态表 + 复合词递归拆解 | `linguistics.py`（1236 行） |
| 离线核心词库 | 歌德 A1–B2，0ms 查词 | `core_dict.py`（516 行），入口 `lookup_core_vocab()` |
| 拓扑句法 | VF/LK/MF/RK/NF 五场域 + 从句 AST | `syntax_tree.py`（1238 行） |
| 启动器 | 端口探测、局域网 IP、平台判定 | `start.py`（86 行） |
| 前端 | 原生 ES Modules（无框架、零构建），PWA | `static/index.html`, `static/js/*.js`（7 个模块）, `static/style.css` |
| 数据库 | SQLite × 2 | `delector.db`（主库）, `progress.db`（学习进度） |
| 音频缓存 | 本地 `.cache/audio/` MP3 | Edge Neural TTS (edge-tts) + Web Speech 回退 |
| 桌面打包 | PyInstaller | `package_windows.py` |
| 移动打包 | Chaquopy + Gradle | `android/` |
| CI/CD | GitHub Actions | `.github/workflows/build-release.yml` |
| 部署 | Docker Compose 可选 | `Dockerfile`, `docker-compose.yml` |
| 测试 | pytest | `test_server.py`（49）, `test_syntax_tree.py`（15） |
| 提交守卫 | pre-commit 密钥扫描 | `.githooks/pre-commit` |
| 环境变量 | `.env`（已 gitignore） | `.env.example` 有字段说明 |
| PWA | Service Worker + Web Manifest | `static/sw.js`, `static/manifest.json` |

---

## NLP 引擎与降级路径（**改标注逻辑前必读**）

后端有两条完全不同的标注路径，**降级是静默的**：

1. **spaCy 路径**（正常）：分词、`doc.sents`、`lemma_`、`pos_`、`morph`（Gender/Case）、
   依存句法（`dep_`/`head`）。拓扑五场域、从句 AST、可分动词回连**全部依赖依存句法**。
2. **纯 Python 降级路径**（`_process_german_text_pure_python` 等）：只有正则切句 +
   `core_dict.py` 反查。**没有依存句法就没有五场域和 AST**，可分动词也回连不上
   （`steigt ... ein` 会按 `steigen` 判成 B1，而不是 `einsteigen` 的 A1）。
   也就是说降级路径不只是"精度低"，而是会给出**错误**的语法标注。

判断当前跑的是哪条：`GET /api/settings` 的 `nlp_engine`（`spacy` / `pure_python`）与
`nlp_engine_detail`，或启动时 stdout 的 `[DeLector] NLP 引擎: ...`（Android 上走 `adb logcat`）。

**模型加载顺序**：`SPACY_MODEL_CANDIDATES = ("de_core_news_md", "de_core_news_sm")`，
md 优先（带词向量、标注更准），sm 兜底。自动下载只在**非 Android** 且两个都加载失败时触发，
且只下 sm（md 约 45MB，首启动拉它太慢）。

`_load_spacy_model()` 有三级回退，缺一不可：`spacy.load(名称)` →
`importlib.import_module(名称).load()` → 按数据目录绝对路径加载。原因见 Android 一节。

---

## Android 独立单机版（Chaquopy）

**几个版本是互锁的，动任何一个都要同步检查其余**：

| 项 | 值 | 为什么不能随便改 |
|---|---|---|
| `python { version "3.10" }` | cp310 | Chaquopy 仓库里 spaCy 原生栈只有 cp310 的 wheel |
| `minSdk 24` | android_24 | 同上，wheel 的平台标签是 android_24 |
| `spacy==3.8.7` | 来自 `https://chaquo.com/pypi-13.1/` | Chaquopy 自己的 native 仓库，连带 thinc 8.3.4 / blis 1.2.1 / numpy 1.26.2 / cymem / preshed / srsly / murmurhash |
| CI 宿主机 spaCy | pin `>=3.8,<3.9` | `de_core_news_sm` 声明 `>=3.8.0,<3.9.0`，宿主机版本漂了会**构建成功但真机加载失败**（CI 里已有 assert 拦） |
| `abiFilters "arm64-v8a"` | 仅 64 位 ARM | spaCy 原生栈按 ABI 各占 21–29MB；三 ABI 是 106.3MB，只保 arm64 是 56.7MB。放弃 armeabi-v7a 与 x86_64（模拟器装不上） |

**两个 Chaquopy 行为坑（都会导致模型静默加载失败）**：

1. **`spacy.load("名称")` 在 Android 上必然报 `[E050] Can't find model`。**
   它走 `spacy.util.is_package()`，查的是 `importlib.metadata` 的 `.dist-info`；而 CI 是把模型目录
   直接 `cp -r` 进 Chaquopy 源码目录的，没有 dist-info。必须退到
   `importlib.import_module(名称).load()` —— 真机上实际生效的就是这条
   （`nlp_engine_detail` 会显示 `de_core_news_sm(module.load)`）。
2. **Chaquopy 默认不把包的数据文件解到文件系统**（APK 内 `assets/chaquopy/build.json` 的
   `extract_packages` 若为 `[]` 即是），Python 代码直接从 `.imy` 压缩包执行，任何
   `Path(__file__).parent / "x"` 的 `open()` 都会 `FileNotFoundError`。因此 build.gradle 必须声明：

   ```groovy
   extractPackages "spacy", "thinc", "de_core_news_sm"
   ```

   三个都要：`de_core_news_sm`（29 个模型文件）、`spacy`（`default_config.cfg`）、
   `thinc`（`backends/_custom_kernels.cu`，模块顶层 `read_text()` 且无 try 保护）。
   各包的 `*.dist-info/entry_points.txt` **不用**列——catalogue 走 `importlib.metadata`，
   Chaquopy 的 `ChaquopyPathFinder.find_distributions` 能直接读 zip。
   要查某个新依赖读了哪些数据文件，用 `sys.addaudithook` 拦 `open` 事件实测，别猜。

**其它 Android 约束**：

- **只绑回环**：`start.get_bind_host()` 在 Android 上返回 `127.0.0.1`。桌面端绑 `0.0.0.0`
  是有意的特性（同 Wi-Fi 设备可访问），但 Android 上绑 `0.0.0.0` 等于把**无鉴权的
  `POST /api/settings`（可改写 API Key 与 base_url）**暴露给整个局域网。
- **import 期不得联网**：`spacy.cli.download` 会起 pip 子进程，Chaquopy 里必然失败却会
  阻塞启动。已用 `is_android()` 门控，并有子进程探针测试守着。
- **不要在 import 期做可能抛异常的事**：`init_db()` 在 `server.py` 模块顶层就会 seed 预置文章、
  走到标注路径，所以标注链上任何异常都会让 `from server import app` 失败、服务永远起不来
  （这正是最初 APK 卡在启动页的原因）。
- **首次启动慢**：Chaquopy 要把那三个包解到内部存储（约 30MB 写盘），只发生在第一次；
  启动页轮询上限约 84 秒。应用内部存储占用因此增加约 30MB。
- **`android/app/src/main/python/` 与 `android/app/src/main/assets/static/` 是 CI 生成的**，
  不在版本控制里（见 `.gitignore`）。
- **验证 APK 内容要解 `.imy`**：Python 代码被打进 `assets/chaquopy/app.imy`（自己的 .py + 模型）
  与 `requirements-<abi>.imy`（原生包），直接在 apk 的 namelist 里 grep `server.py` 会误判成"缺失"。
  排查 Chaquopy 自身行为时，`bootstrap.imy` 里就是它的 importer 实现，比查文档快也更准。
- Java 侧（`MainActivity.java`）**本机无法编译验证**（没装 Android SDK），只能靠 CI。
  失败时 `reportFatal()` 会把错误留在启动页且可选中复制；重载上限 10 次；
  catch 必须用 `Throwable`（`Python.start()` 抛的是 `UnsatisfiedLinkError`）。

---

## 数据库 Schema（两个库）

### `delector.db` — 主库

```sql
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

```sql
study_log       id, event_type, ref_id, note, logged_at
quiz_log        id, card_id, card_type, mode, correct, attempted_at
daily_summary   date(PK), cards_added, cards_mastered, articles_read,
                quiz_sessions, study_minutes
```

---

## API 路由全览（`server.py`，按源码顺序）

```text
POST   /api/articles/ingest-url                 抓取 URL 并解析德语正文
GET    /api/feed/sources                        精选德语外刊与学习 RSS 订阅源
GET    /api/feed/items                          解析指定 RSS/Atom 源最新文章列表
POST   /api/articles/ingest                     直接提交文本导入
GET    /api/articles                            列出所有文章
GET    /api/articles/{article_id}               获取单篇文章（含 NLP 分析 JSON）
POST   /api/lookup/grammar                      语法悬停查词
POST   /api/lookup/vocab                        词汇悬停查词
POST   /api/cards/vocab                         添加词汇卡片
POST   /api/cards/grammar                       添加语法卡片
GET    /api/cards                               列出所有卡片
DELETE /api/cards/{card_type}/{card_id}         删除卡片
PATCH  /api/cards/{card_type}/{card_id}/master  标记/取消掌握
POST   /api/quiz/record                         记录测验结果
POST   /api/progress/log-read                   记录阅读事件
GET    /api/progress/stats                      获取学习统计（用于进度台账）
GET    /api/cards/export/apkg                   导出 Anki APKG
POST   /api/audio/tts                           生成 Edge TTS 音频
GET    /api/audio/cache                         查看音频缓存
POST   /api/audio/cache/clear                   清空音频缓存
GET    /api/articles/{article_id}/notes         获取文章笔记
POST   /api/articles/{article_id}/notes         添加笔记
DELETE /api/notes/{note_id}                     删除笔记
POST   /api/ai/note-assist                      AI 笔记辅助（DeepSeek API）
GET    /api/settings                            读取设置（含 nlp_engine 诊断字段）
POST   /api/settings                            写入设置（**无鉴权**，故 Android 只绑回环）
POST   /api/settings/test-key                   连通性与延迟测试
GET    /api/articles/{article_id}/export-guide  导出学习指南 HTML
GET    /api/backup/export                       导出数据库备份
POST   /api/backup/restore                      恢复数据库备份
POST   /api/cards/{card_type}/{card_id}/review  FSRS 自适应间隔复习记录（grade 1-4）
GET    /api/cards/due                           获取今日到期卡片（FSRS 排程）
POST   /api/articles/{article_id}/exercise/cloze 生成完形填空题（grammar/vocab/ctest）
POST   /api/exercise/cloze/evaluate             服务端判分（答案不在前端 DOM）
POST   /api/syntax/analyze                      拓扑五场域与从句 AST 分析
```

**路由重要约束**：`app.mount("/", StaticFiles(...))` 是 catch-all 路由，
**必须放在 `server.py` 最末尾**，否则所有 API 路由返回 405。

---

## 前端核心模块拓扑（`static/js/*.js`）

| 模块 | 关键函数 / 职责 |
|---|---|
| `main.js` | 路由调度 `show()`, 导入模态窗, RSS 订阅 `selectFeedSource` / `ingestFeedItem`, 设置弹窗, 全局热键与 `window` 导出 |
| `core.js` | `api()` 请求封装, `esc()`, `normalizeCefrPct()` 整数归一化, `state` 全局共享状态 |
| `player.js` | `ShadowPlayer` 影子跟读与控制板, Edge Neural TTS + Web Speech 离线发音回退 |
| `companion.js` | 德语伴读宠物（Eule & 伙伴）引擎 `Companion`, 4 款矢量 SVG 角色, A1–B1 地道短语库, 8s 冷却语音发声与情绪动效 |
| `reader.js` | 文章渲染 `openReader()`, 词法悬停抽屉 `inspect()`, CEFR 热力条与聚焦, 便签增删 `aiNoteAssist()` |
| `cards.js` | 3D 拟真卡片翻转盒 `renderDeckStage()`, FSRS 认知间隔复习 `submitCardReview()`, Quiz 测验引擎 |
| `folio.js` | Leporello 三折页台账 `loadProgress()`, 30 天留存墨线折线图, 歌德箴言轮播 |
| `cloze.js` | 完形填空 & 德福 C-Test 考试 `openClozeModal()`, 首字母提示 `revealClozeHints()`, 服务端判分 |

---

## FSRS 认知排程架构（`server.py` `calculate_fsrs` / `calculate_sm2`）

现代自适应记忆排程器基于 FSRS (Free Spaced Repetition Scheduler) DSR 认知状态机模型（纯 Python `math` 原生零依赖实现）：

```text
D (Difficulty 难度, [1.0, 10.0])
S (Stability 稳定性天数, 当 Retrievability 降至 R_target=0.90 时的耗时)
R(t, S) = (1 + (19/81) * (t / S))^(-0.5)

初次打分标定 (rep=0):
  S_0 = [0.5, 1.8, 3.6, 8.5] (对应 1重来/2困难/3良好/4简单)
  D_0(g) = clamp(8.0 - (g - 1) * 1.8, 1.0, 10.0)
  Interval = [1, 2, 4, 9] 天

后续复习 (rep>0):
  难度均值回归: D' = clamp(0.1 * 4.4 + 0.9 * (D - (g - 3) * 0.8), 1.0, 10.0)
  成功回忆 (g>=2): S' = S * (1 + e^1.0 * (11 - D') * S^(-0.2) * (e^((1-R)*0.9) - 1) * penalty(g))
    其中 penalty: Hard=0.6, Good=1.0, Easy=1.4
  遗忘重置 (g=1): S' = max(0.4, min(S, 0.6 * (D')^(-0.3) * (S + 1)^0.4)), rep 重置为 0
  排程天数: Interval(S') = max(1, round(S'))
```

- 接口 `GET /api/cards`、`GET /api/cards/due` 与 `POST /api/cards/{type}/{id}/review` 均返回预计算的 `next_intervals: {1: d_again, 2: d_hard, 3: d_good, 4: d_easy}` 字典；
- `calculate_sm2` 函数保留作为 4 元组封装别名，确保向后兼容。

---

## 完形填空引擎（`server.py` `generate_cloze_exercise`）

- **grammar 模式**：挖 ADP/SCONJ/CCONJ/AUX（被动/虚拟式）/ADJ，每句最多 2 空
- **vocab 模式**：挖 A2/B1/B2/C1 级 NOUN/VERB，每句最多 2 空
- **ctest 模式**：从第 2 句起，每隔 1 个词截断后半部分（标准德福 C-Test）
- 每个 item 含 `original`、`first_letter`、`hint`、`prefix`/`suffix`（ctest 专用）
- `masked_text` 中空白格式为 `[[BLANK_N]]`，前端用 `split(/(\[\[BLANK_\d+\]\])/)` 解析（**不用 replace**）
- **答案仅在服务端**，判分时服务端重新生成

---

## 切句：spaCy 缺席时的唯一实现

`syntax_tree.split_sentences_pure_python()` 是**唯一**的降级切句实现，`server.py` 从这里 import。

历史坑：曾有两份逐字相同的错误实现（`server.py` 与 `syntax_tree.py` 各一份），
`re.split(r'([.!?]+["\']?)', text)` 的捕获组带尾随空格（`". "`），后续过滤纯标点片段的正则
匹配不到，于是**每个句号都变成一个独立的"句子"**。要改切句逻辑请只改这一处。

---

## 安全与提交守卫

- **pre-commit 密钥扫描**：`.githooks/pre-commit`。**`core.hooksPath` 是本地配置，不随 clone 生效**，
  每个克隆都要手动开一次：

  ```bash
  git config core.hooksPath .githooks
  ```

  覆盖 8 个 key 家族（OpenAI/Anthropic、AWS、GitHub PAT ×2、Google、Slack、JWT、私钥 PEM）
  与密钥文件名（`.env`、`*.pem`、`*.secret`、`*credentials*`、`id_rsa*`、`id_ed25519*`；
  `.example`/`.sample`/`.template` 放过）。扫的是**暂存文件全文**而非 diff 新增行，
  因为按行 diff 会漏掉"把含密钥的行挪到另一个文件"。
  误报走行内 `delector:allow-secret` 注释（豁免留在 diff 里可被审阅）；
  **不要用 `git commit --no-verify` 跳过**。
- 真实 key 走环境变量或 `.env`（已 gitignore），绝不硬编码。
- `POST /api/settings` **无鉴权**，能改写 API Key 与 base_url。这是 Android 只绑回环的原因；
  桌面端绑 `0.0.0.0` 时同一局域网内任何人都能改，动这块要意识到影响面。

---

## 本机开发环境

```text
启动命令:  python start.py   或   start.bat
地址:      http://localhost:8000（桌面端同时绑 0.0.0.0，同 Wi-Fi 设备可访问）
数据库:    D:\Code\DeLector\delector.db（主库）
           D:\Code\DeLector\progress.db（进度）
NLP 模型:  优先 de_core_news_md，缺失则 de_core_news_sm（本机装的是 sm）
测试:      pytest            （64 个，全绿）
静态检查:  python -m pyflakes server.py syntax_tree.py start.py
```

**Git 推送通道**：这台机器上 HTTPS 连 fetch 都会失败（`schannel: failed to receive handshake`），
`origin` 已指向 `ssh://git@ssh.github.com:443/ROM4n2/DeLector.git`（22 端口时通时不通，443 稳定）。
`gh` CLI 走自己的 HTTPS API 认证，不受影响。

---

## 版本历史与重要决策

| 版本/提交 | 主要变更 |
|---|---|
| v2.1.0 `1b38b16` | 3D 物理翻牌盒 + Leporello 三折台账 + Edge TTS |
| v3.0 `0eeee94` | 完形填空引擎（Cloze & C-Test）+ SuperMemo SM-2 + Android PWA |
| `59f7f51` | **fix**: `deleteCard` 缺 `async` 导致全局 JS 崩溃（页面白屏） |
| `7e98726` | **fix**: 完形填空首字母提示与重做；`renderClozeExercise` 改用 split 解析避免 HTML 注入 |
| v3.1.0 `91de593` | **fix**: Leporello 色段精度（整数归一化）+ Android PWA bottom-sheet 触屏体验 |
| v3.2.0 `4bbea6c` | **feat & refactor**: 前端 ES Modules 拆分 + 歌德 A1-B2 离线核心词库 |
| v3.3.0 `7009841` | **feat**: 德语外刊 RSS 一键订阅（DW、Tagesschau、DLF、Spiegel、Zeit） |
| v3.4.0 | **feat**: 556+ 不规则动词三态表 + 复合词递归拆解 + 可分动词框形双向高亮 |
| v3.5.0 `0e0d8d8` | **feat**: 拓扑五场域与从句 AST 引擎（`syntax_tree.py`） |
| v3.5.0 | **feat & build**: 全局设置弹窗 + Windows 便携版与 Android 独立版 CI/CD |
| **PR #2 `c3de92f`** | **fix(android)**: 修复启动卡死（降级路径 `NameError`）+ 切句器去重 + Android 错误可见性与重载上限 + Android 只绑回环 + **移植真 spaCy 进 APK**（arm64-only 56.7MB）+ `extractPackages` 与模型三级加载回退 + 模型 md 优先 + **pre-commit 密钥扫描钩子**；真机验证 `nlp_engine == "spacy"` |
| **v3.5.0 Release `2026-08-19`（重发）** | 首版发布内容是 PR #2 之前的 `4ede08f`（三 ABI、无 spaCy、纯 Python 降级），已**删除重发**：tag 重建于 master，CI 产出 arm64-only 56.7 MiB APK（`extract_packages=['de_core_news_sm','spacy','thinc']` 拆包核对）+ Windows 75.4 MB。工作流 `vv` 命名 bug 已修（`name: DeLector ${{ github.ref_name }}`） |
| **v3.5.1 Release `2026-08-19`** | **fix(mobile & audio)**: 修复 6 大安卓交互（导入弹窗、台账/卡片响应式、DownloadManager 下载监听、物理返回键拦截、触感震动）+ 引入 Android Native TextToSpeech 原生离线发音桥接 + CI 流水线版本参数化 |
| **v3.5.2 Release `2026-08-19`** | **fix(mobile, audio & ui)**: 补齐 Android 11+ `<queries>` TTS 声明、接入有道/百度国内免翻墙在线音频兜底、扩大移动端底部 Dock 阈值至 1024px、重构台账三折页为 100% 独立 Tab 卡片规避滑轨错位 |
| **v3.6.0 `2026-08-19`** | **feat(folio & ui)**: Phase 1 台账重塑为现代连续杂志画册展台（Continuous Exhibition Folio）+ 6 核心环形指标徽章 + 谱系/轨迹双栏展台与 CEFR 阶梯矩阵 + 火漆印章微倾斜成就展台 |
| **v3.6.1 `2026-08-19`** | **feat(ui & design-system)**: Phase 2 全局设计系统深度同步升级：文稿库 `.articles-grid` 现代社论卡片质感（`1.5px` 墨线、`3px` 实体物理投影、等宽打字机徽章、经典衬线标题与朱砂珊瑚红悬停交互）+ 包豪斯实体工坊导入弹窗与德语外刊 RSS 展台卡片 + 36px 极薄元数据走字 Ticker + 温润纸感触控底部 Dock |
| **v3.6.2 `2026-08-19`** | **feat(folio & landing-page)**: 台账（Folio）重塑为 Atelier 呼吸感落地页：0.85:1.15 不对称 Hero 展台、歌德名言、6 核心 Ring Badges 大展盘（带四角标点 `+` 与 ECHTZEIT 脉冲标签）、双行反向 Wire Marquee 动态走字带（上行名言语录，下行实时战报数据）、欧标/走势与错题/勋章双面板紧凑并排网格 |
| **v3.7.0 `2026-08-19`** | **feat(companion & mascot)**: 德语伴读宠物（Companion Mascot）「Eule & 伙伴」混合双模系统全量落地：4 款内嵌矢量 SVG 角色（歌德猫头鹰、学者猫、灵动狐、包豪斯机甲）+ 研读工坊台账展台与全局悬浮伴读球双挂载点 + A1–B1 地道鼓励短语库 + 三层 TTS 语音发声与 8s 冷却 + 6 大物理/情绪 Keyframes 动画 + 生词卡/语法卡/SM-2 复习/完形填空/测验全链路事件接线 |
| **v3.7.1 `2026-08-19`** | **feat(companion & upload)**: 伴读宠物 Phase 2 角色工坊上线：支持用户上传任意自定义 `.svg` 矢量图形（$\le 64\text{KB}$）、严格 DOMParser 递归白名单消毒（过滤 `<script>`、`<foreignObject>`、`on*` 与非法协议）、`localStorage` 持久化注册并在研习工坊及全局浮层无缝切换 |
| **v3.8.0 `2026-08-19`** | **feat(fsrs & memory)**: 认知自适应记忆排程器升级为 FSRS 引擎：DSR 状态机原生零依赖数学模型（难度 $D$ 均值回归、稳定性 $S$ 幂律增长、可提取性 $R$ 遗忘衰减），消解「沉沦死锁 (Ease Hell)」；API 注入 4 级下一轮间隔预计算字典 `next_intervals`，前端 3D 翻牌盒精准动态绑定并保持向下兼容 |

---

## 已知问题 / 待办

> 更新时间：2026-08-19

- [x] ~~**工作流硬编码资产名**：已参数化为 `${{ github.ref_name }}`~~
- [ ] **已合并的分支未删**：`fix/android-startup-and-spacy`（本地与远端都还在）
- [ ] **已合并的分支未删**：`fix/android-startup-and-spacy`（本地与远端都还在）
- [ ] `de_core_news_md` 本机未安装，所以 md 优先这条路径**只验证了回退到 sm 的行为**，
      md 实际加载未在本机跑过
- [ ] `pyflakes` 在 `test_server.py` 有 3 条陈旧告警（2 个未用导入 + 1 个未用变量），先前就有
- [ ] Android 侧 Java 代码无法本机编译验证（本机无 Android SDK），只能靠 CI
- [ ] 首次启动因 `extractPackages` 解包约 30MB 而明显变慢，尚未在真机上实测耗时
- [x] ~~安卓版启动卡在「正在启动」页并超时~~ — PR #2 已修（根因：降级路径 `NameError`）
- [x] ~~安卓版语法标注错误（无五场域/AST，可分动词回连失败）~~ — PR #2 已移植真 spaCy，真机验证通过
- [x] ~~Android 上无鉴权 `POST /api/settings` 暴露给局域网~~ — PR #2 改为只绑 `127.0.0.1`
- [x] ~~Android 失败不可见 + WebView 无限重载~~ — PR #2 已修
- [x] ~~仓库无提交前密钥扫描~~ — PR #2 已加 `.githooks/pre-commit`
- [x] ~~README/Dockerfile 装 md 但代码只加载 sm~~ — PR #2 改为 md 优先、sm 兜底

---

## Agent 工作惯例

1. **先验证再断言**：声称"已修复/已完成"前先跑验证并给出证据（复现脚本、测试输出、
   拆包核对）。本项目的失败模式大量是**静默降级**，"看代码觉得对"经常是错的。
2. **改 Android 相关代码前**：先读本文件「Android 独立单机版」一节。那里每一条都有代价，
   `python version` / `minSdk` / spaCy 版本 / `extractPackages` 改错都不会报错，只会静默退化。
3. **改标注/切句逻辑前**：确认改的是 spaCy 路径还是纯 Python 降级路径，两条都要过。
   切句只有 `syntax_tree.split_sentences_pure_python()` 一处实现。
4. **改 JS 前**：新增函数要在文件末尾 `window.xxx = xxx` 显式导出；
   不要用 `innerHTML` 插入含用户数据的原始字符串（用 `esc()` 转义）；
   不要把答案或敏感数据写进 `data-*` 或 `localStorage`。
5. **改后端路由前**：查看 `server.py` 顶部 `init_db()` 了解完整 schema；
   `app.mount` 必须在文件最末尾；**不要在模块顶层加可能抛异常的逻辑**。
6. **新功能测试**：在 `test_server.py` / `test_syntax_tree.py` 补测试，`pytest` 全绿。
   配置类约束也可以写成测试（例：有个测试直接读 `build.gradle` 断言
   `extractPackages` 列了那三个包）。
7. **提交前**：`git diff --stat` 确认范围合理；绝不提交 `.env`、`*.db`、APK 等产物；
   pre-commit 钩子必须启用且不绕过。
8. **大改动后**：更新本文件的「交接快照」「版本历史」「已知问题 / 待办」三节。
9. **缓存问题**：改动 CSS/JS 后在 `index.html` 的引用 URL 追加 `?v=X.X.X`，
   并更新 `sw.js` 的 `CACHE_NAME`。

---

*此文件由 agent 维护，人工可随时追加注释。请保持全文唯一，不要追加重复副本。*
