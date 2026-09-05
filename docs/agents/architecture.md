# DeLector 架构细节（Agent 深读文档）

> 2026-09-05 从 `AGENTS.md` 拆出：AGENTS.md 只保留入门快照与红线速查，本文件承载架构与实现细节。
> 维护约定：就地修改、不追加副本；与代码/测试冲突时以代码与测试为准，并回写 AGENTS.md 红线（若有）。

---

## 技术栈速览

| 层               | 技术                                                       | 关键文件                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ---------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 后端             | Python 3.10+, FastAPI, spaCy, genanki                      | `server.py`（挂载路由与静态资源）, `routes_a1.py`（A1 考纲路由）, `routes_sync.py`（WebRTC 同步路由）, `routes_rtc.py`（WebRTC 信令中继）                                                                                                                                                                                                                                                                                                                                                                                             |
| 词法/形态学      | 556+ 不规则动词三态表 + 复合词递归拆解                     | `linguistics.py`（1236 行）                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| 离线核心词库     | 歌德 A1–B2，0ms 查词                                       | `core_dict.py`（516 行），`a1_dict.py`（A1 702 词与口语卡），`a1_writing_dict.py`（A1 写作题库）                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| 介词搭配数据集   | 动词/形容词 + 固定介词 + 格                                | `prep_dict.py`（生成物），入口 `lookup_prep_collocations()`，源 `tools/build_prep.py`                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| 写作润色规则引擎 | 冠词/格位一致 + 介词支配格 + A1 填表与短电邮诊断           | `writing_rules.py`，入口 `analyze_essay_text()`, `analyze_a1_email()`, `check_a1_formular_answer()`                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| 拓扑句法         | VF/LK/MF/RK/NF 五场域 + 从句 AST                           | `syntax_tree.py`（1238 行）                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| 启动器           | 端口探测、局域网 IP、平台判定                              | `start.py`（86 行）                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| 前端             | 原生 ES Modules（无框架、零构建），PWA                     | `static/index.html`, `static/js/`（10 个模块：`core`, `main`, `reader`, `cards`, `a1_cards`, `writer`, `a1_writer`, `player`, `folio`, `companion`, `cloze`）, `static/style.css`                                                                                                                                                                                                                                                                                                                                                     |
| 数据库           | SQLite × 2                                                 | `delector.db`（主库）, `progress.db`（学习进度）                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| 音频缓存         | 本地 `.cache/audio/` MP3                                   | Edge Neural TTS（桌面 edge-tts；Android 无 wheel 时走 stdlib 版 `edge_tts_mini.py`）+ 有道/百度兜底                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| 桌面打包         | PyInstaller                                                | `package_windows.py`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| 移动打包         | Chaquopy + Gradle                                          | `android/`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| CI/CD            | GitHub Actions                                             | `.github/workflows/build-release.yml`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| 部署             | Docker Compose 可选                                        | `Dockerfile`, `docker-compose.yml`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| 测试             | pytest                                                     | `test_server.py`（180）, `test_writing_rules.py`（31）, `test_writer_mobile.py`（28）, `test_german_workbench.py`（19）, `test_syntax_tree.py`（15）, `test_essay_diff.py`（13）, `test_prep_matrix.py`（12）, `test_dict_pipeline.py`（10）, `test_edge_tts_mini.py`（10）, `test_goethe_a1.py`（9）, `test_goethe_a1_writing.py`（8）, `test_core_dict_ext.py`（5）, `test_frontend_security.py`（4）, `test_start.py`（4）, `test_source_hygiene.py`（2）, `test_frontend_module_graph.py`（2）— 共 **352**（2026-08-29 实测全绿） |
| 提交守卫         | pre-commit 密钥扫描（文件名+内容+编码 keystore）           | `.githooks/pre-commit`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| 环境变量         | `.env`（已 gitignore）                                     | `.env.example` 有字段说明                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| PWA              | Service Worker + Web Manifest                              | `static/sw.js`, `static/manifest.json`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| CI 限制          | 无 Android SDK 时本地不伪称构建通过；CI 负责 Gradle 与验签 | `.github/workflows/build-release.yml`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |

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

| 项                          | 值                                   | 为什么不能随便改                                                                                                     |
| --------------------------- | ------------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| `python { version "3.10" }` | cp310                                | Chaquopy 仓库里 spaCy 原生栈只有 cp310 的 wheel                                                                      |
| `minSdk 24`                 | android_24                           | 同上，wheel 的平台标签是 android_24                                                                                  |
| `spacy==3.8.7`              | 来自 `https://chaquo.com/pypi-13.1/` | Chaquopy 自己的 native 仓库，连带 thinc 8.3.4 / blis 1.2.1 / numpy 1.26.2 / cymem / preshed / srsly / murmurhash     |
| CI 宿主机 spaCy             | pin `>=3.8,<3.9`                     | `de_core_news_sm` 声明 `>=3.8.0,<3.9.0`，宿主机版本漂了会**构建成功但真机加载失败**（CI 里已有 assert 拦）           |
| `abiFilters "arm64-v8a"`    | 仅 64 位 ARM                         | spaCy 原生栈按 ABI 各占 21–29MB；三 ABI 是 106.3MB，只保 arm64 是 56.7MB。放弃 armeabi-v7a 与 x86_64（模拟器装不上） |

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
- **签名 keystore 是钉死的，且只从环境变量读**（v3.10.0）：`signingConfigs.debug`
  在 `DELECTOR_KEYSTORE_PATH` 指向的文件**存在**时生效，否则整段跳过、回落到 AGP
  自动生成的 debug keystore —— 本地和 fork 照常能构建。CI 从 4 个 secret
  （`ANDROID_DEBUG_KEYSTORE_B64` / `ANDROID_KEYSTORE_PASSWORD` /
  `ANDROID_KEY_ALIAS` / `ANDROID_KEY_PASSWORD`）解码到 **`$RUNNER_TEMP`**，
  keystore 永不进入工作树。构建后 `keytool -printcert -jarfile` 比对 APK 与 keystore
  的证书指纹，不一致就红 —— 这道闸拦的是「secret 缺失 → 静默回落到随机签名 →
  产出一个看起来正常、装到手机上却签名不一致的 APK」。
  用 `keytool` 而不是 `apksigner`：本 job 显式装了 JDK 17，`keytool` 路径确定；
  `apksigner` 属 build-tools，路径含版本号段且不在 PATH 上，AGP 换版本时那道闸会**静默失效**。
- **versionCode 编码规则：`major*10000 + minor*100 + patch`**（v3.10.0 起）。
  旧规则 `major*100 + minor*10 + patch` 在 minor 到 10 时溢出撞车（`3.10.0` 与 `4.0.0`
  都算出 400），而 versionCode 必须严格单调递增，撞车 = 新版本无法覆盖安装。
  有测试读 `build.gradle` 守这条规则（`test_android_version_code_encoding`）。
- **keystore 丢失 = `org.delector.app` 这个包名永远无法再推送升级**，只能改包名重来
  （用户数据全丢）。keystore 与口令必须离线备份在仓库之外的至少两处。
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
                ease_factor, repetition_count, created_at,
                corrected_form, error_type      -- v3.11 写作台：修正形式 + 错误分类(artikel/kasus/praeposition/andere)
reading_notes   id, article_id, sentence_id, selected_text, color,
                note_content, created_at
prep_saved      lemma, praep, kasus, saved_at
                -- v4.6.4 介词矩阵已存搭配持久化；主键 (lemma, praep, kasus)
essays          id, title, content, analysis_json, cefr_level,
                error_count, sentence_count, created_at, updated_at
                -- v3.11 写作台草稿库；analysis_json = {"version","cefr","error_count",
                -- "sentences":[{text, spans:[{error_type,corrected_form,explanation_zh,start,end}]}]}
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
POST   /api/lookup/vocab                        词汇悬停查词（形态学四层：stammformen /
                                                komposita / separable / praepositionen）
GET    /api/prep/matrix                          Präpositionen-Matrix：整套介词搭配反转
                                                索引（linguistics.build_prep_matrix 纯函数 +
                                                 CEFR 注入 + 进程缓存；只读，无鉴权）
GET    /api/prep/saved                          获取当前用户已入卡的介词搭配 key 列表
POST   /api/prep/saved                          记录一条搭配已入卡（幂等写入）
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
GET    /api/audio/tts                           GET 版（query 参数）：供背词工作台
                                                <audio src> 直接用，与 POST 共享缓存池；
                                                rate 须为 +0%/-10% 形式，否则 400
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
GET    /api/backup/export                       导出数据库备份（v2；仅 127.0.0.1）
POST   /api/backup/prepare                      提交 localStorage 换一次性下载 token（仅 127.0.0.1）
GET    /api/backup/download/{token}             attachment 下载（单次有效；Android 唯一可行路径）
POST   /api/backup/restore                      **整体覆盖**还原，失败按文件快照回滚（仅 127.0.0.1）
POST   /api/cards/{card_type}/{card_id}/review  FSRS 自适应间隔复习记录（grade 1-4）
GET    /api/cards/due                           获取今日到期卡片（FSRS 排程）
POST   /api/articles/{article_id}/exercise/cloze 生成完形填空题（grammar/vocab/ctest）
POST   /api/exercise/cloze/evaluate             服务端判分（答案不在前端 DOM）
POST   /api/syntax/analyze                      拓扑五场域与从句 AST 分析
POST   /api/writing/analyze                     写作台文本实时规则诊断（冠词/格位/介词搭配）
POST   /api/essays                              新建作文草稿
GET    /api/essays                              获取作文草稿列表
GET    /api/essays/{essay_id}                   获取指定作文详情与分析
PUT    /api/essays/{essay_id}                   更新作文内容与重新分析
DELETE /api/essays/{essay_id}                   删除作文草稿及关联版本快照
POST   /api/essays/{essay_id}/versions          创建作文版本快照
GET    /api/essays/{essay_id}/versions          列出作文的所有版本快照
GET    /api/essays/{essay_id}/versions/{v_id}   只读预览指定快照内容与分析（不写库）
DELETE /api/essays/{essay_id}/versions/{v_id}   删除指定版本快照（不影响当前草稿）
POST   /api/essays/{essay_id}/restore           恢复作文至指定快照（自动生成前置检查点）
POST   /api/writing/cards                       将写作错误一键保存为 Anki 语法卡
POST   /api/writing/ai-polish/diff              AI 全文润色与逐 hunk 差异对比生成
POST   /api/writing/apply                       应用所选 AI 润色 hunk 并自动保存版本
POST   /api/wb/sync/store                       背词工作台：暂存 WebRTC SDP 并生成 6 位短码（须 X-WB-Key）
GET    /api/wb/sync/fetch/{code}                背词工作台：凭 6 位短码获取 SDP（一次性消费，5分钟有效；须 X-WB-Key）
GET    /api/wb/state                            wb 镜像读：对局域网开放（拉取免 key）；回环/私有 Origin 反射 ACAO
PUT    /api/wb/state                            wb 镜像写：须 X-WB-Key（32 位 hex，存 app_settings，不进 Git），错/缺 403
GET    /api/wb/state/key                        取配对密钥：仅本机 127.0.0.1（_require_localhost），幂等
POST   /api/wb/state/key                        重新生成配对密钥（= 撤销配对）：旧 key 立即 403；仅本机
POST   /api/wb/rtc/signal                       WebRTC 信令中继：按配对密钥建邮箱，投递 SDP/ICE（须 X-WB-Key）
GET    /api/wb/rtc/signal                       拉取对端信令：?client=<本端id>&after=<游标>，只回「别人发的」
GET    /api/wb/lan-info                         {hostname, port, lan_ip, instance_id}：配对 UI 提示填 IP（局域网可读）
```

**路由重要约束**：`app.mount("/", StaticFiles(...))` 是 catch-all 路由，
**必须放在 `server.py` 最末尾**，否则所有 API 路由返回 405。

---

## 前端核心模块拓扑（`static/js/*.js`）

| 模块           | 关键函数 / 职责                                                                                                   |
| -------------- | ----------------------------------------------------------------------------------------------------------------- |
| `main.js`      | 路由调度 `show()`, 导入模态窗, RSS 订阅 `selectFeedSource` / `ingestFeedItem`, 设置弹窗, 全局热键与 `window` 导出 |
| `core.js`      | `api()` 请求封装, `esc()`, `normalizeCefrPct()` 整数归一化, `state` 全局共享状态                                  |
| `player.js`    | `ShadowPlayer` 影子跟读与控制板, Edge Neural TTS + Web Speech 离线发音回退                                        |
| `companion.js` | 德语伴读宠物（Eule & 伙伴）引擎 `Companion`, 4 款矢量 SVG 角色, A1–B1 地道短语库, 8s 冷却语音发声与情绪动效       |
| `reader.js`    | 文章渲染 `openReader()`, 词法悬停抽屉 `inspect()`, CEFR 热力条与聚焦, 便签增删 `aiNoteAssist()`                   |
| `cards.js`     | 3D 拟真卡片翻转盒 `renderDeckStage()`, FSRS 认知间隔复习 `submitCardReview()`, Quiz 测验引擎                      |
| `folio.js`     | Leporello 三折页台账 `loadProgress()`, 30 天留存墨线折线图, 歌德箴言轮播                                          |
| `cloze.js`     | 完形填空 & 德福 C-Test 考试 `openClozeModal()`, 首字母提示 `revealClozeHints()`, 服务端判分                       |

---

## 局域网静默同步（镜像配对 · Stage A）

- 目标：手机浏览器 / Android APP 访问桌面 `http://<桌面IP>:8000`，在背词工作台「设置 → LAN
  同步 → 镜像配对」输入一次 `host + 32 位密钥`，之后 wbsync 每 5s 带 `X-WB-Key` 静默
  `GET`/`PUT /api/wb/state` 双向对账：远端拉取免 key、推送必须 key，`applyMerge(...,{silent:true})`
  静默合并（不弹 toast、不打断视图）。
- 配对密钥 `secrets.token_hex(32)` 持久化在 `app_settings`（`get_wb_sync_key`），**不进 Git**；
  仅本机端点 `GET /api/wb/state/key`（`_require_localhost`）可取。清除配对后：远端推送 403、只读拉取不破。
- wb 端点 CORS 中间件（`_wb_sync_cors`）：只对「回环 / 私有网段」Origin 反射
  `Access-Control-Allow-Origin` 并放行 `OPTIONS` 预检；公共 Origin 预检显式 403、普通请求
  不加 ACAO（浏览器按跨域失败拦截）；无 Origin 头的本机/同源/存量流量行为零变化。
- 前端：`wbsync.pair.set/clear/info` + 配对面板宿主/远端二态渲染。设计与验证详见
  `docs/specs/2026-09-03-lan-silent-sync-design.md`（§6 Stage A 已勾选）与
  `docs/plans/2026-09-03-lan-silent-sync-stage-a(-ledger).md`。

## 局域网静默同步 Stage B（自动化 WebRTC · 2026-09-03 落地）

在 Stage A「配对一次 + HTTP 轮询」之上，用 WebRTC DataChannel 达成「加密 + 真无感」：

- **信令鉴权**：`/api/wb/sync/store` 与 `/fetch/{code}` 补 `X-WB-Key`（SDP 要在 LAN 上中继，
  不能用 `_require_localhost`，否则手机永远进不来）；`/info` 保持开放。CORS 预检放行方法补 `POST`
  （原先只有 `GET, PUT, OPTIONS`，跨域浏览器会在预检阶段被拒、信令永远发不出去）。
- **持久配对凭证 + 撤销**：`POST /api/wb/state/key` 重新生成密钥（仅本机）→ 旧 key 立即 403。
  前端 `wbsync.pair.revoke()` 撤销后**必须换用服务端下发的新 key**：否则主机会被自己作废的 key
  卡死（`pushNow` 开头 `if (!_key) return` 短路，连本机都推不动）。
- **信令中继** `routes_rtc.py`：`POST/GET /api/wb/rtc/signal`，邮箱 id 取配对密钥的 sha256 摘要
  （不用短码、也不留密钥明文）；带 `sender` 隔离回声、带 `after` 游标防重放。
- **前端** `wbsync.rtc`：角色由「是否已配对」决定（已配对侧发 offer、宿主侧应答，免协商、不打架）；
  信封沿用 HTTP PUT 的 `{payload:...}` 形状——两种通道一套契约，少一处不一致的余地；
  收到信封一律 `applyMerge(payload,{silent:true})`。
- **重连与兜底**：`connectionState` 失败/断开 → 去抖重建；连续失败超上限即降级，
  Stage A 的 HTTP 轮询始终在线兜底（保证「至少可达」）。
- 详见 `docs/plans/2026-09-03-lan-silent-sync-stage-b(-ledger).md` 与 ADR-0004
  （`d:/Obsidian/Coding/08-Projects/DeLector/01-ADR/0004-lan-sync-webrtc-stage-b.md`）。
  **真机验证**：桌面↔桌面浏览器可验；Android APP 须等下次发版（旧版 APK 未内嵌 Stage A+B 代码）。

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
