# AGENTS.md — DeLector 项目 AI Agent 交接文档

> **每次开新 agent 对话时，第一步必须读这个文件。**
> 这是机器可读的项目快照，用于最短时间内重建完整 context。
>
> 维护约定：本文件**只保留一份**内容。历史上曾出现整份文档被追加两遍、
> 后半段是过时副本的情况，新 agent 读到会拿到自相矛盾的项目认知。
> 更新时请就地修改，不要在文件末尾追加新版本。

---

## 交接快照

> 更新时间：2026-08-24

| 项 | 值 |
|---|---|
| 当前分支 / HEAD | `master`（v4.4.7：桌面端写作台侧栏几何收口 + 三行触屏按压反馈） |
| 测试 | **242 / 242 全绿**（v4.4.7 新增：桌面侧栏内部可滚断言、三行 `:active` 按压契约、未定义 CSS 变量棘轮；v4.4.6 新增：顶栏版本标签纳入版本自洽断言、移动端 sheet 几何稳定性） |
| 桌面端 | 正常，`python start.py` → `http://localhost:8000`（敏感设置仅回环可写，局域网返回 403） |
| Android APK | **真机验证通过**，内嵌 spaCy + 德语模型 + Android 原生离线 TextToSpeech 桥接 + 多源在线 TTS 兜底 |
| 对外发布 | 已发布至 **v4.4.6**（四平台产物齐、CI 验签闸过）；**v4.4.7 待发布**（版本号 40407，仅 arm64-v8a）。⚠️ Java 仍未经本机编译（无 Android SDK），运行时行为只能真机验收；**v4.4.6 与 v4.4.7 的真机验收合并做一次**（装 v4.4.6 → 覆盖装 v4.4.7），要点见「已知问题 / 待办」 |
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
| 介词搭配数据集 | 动词/形容词 + 固定介词 + 格 | `prep_dict.py`（生成物），入口 `lookup_prep_collocations()`，源 `tools/build_prep.py` |
| 写作润色规则引擎 | 冠词/格位一致 + 介词支配格，零误报准则 | `writing_rules.py`，入口 `analyze_essay_text()`（nlp=None 降级零错误），测试 `test_writing_rules.py` |
| 拓扑句法 | VF/LK/MF/RK/NF 五场域 + 从句 AST | `syntax_tree.py`（1238 行） |
| 启动器 | 端口探测、局域网 IP、平台判定 | `start.py`（86 行） |
| 前端 | 原生 ES Modules（无框架、零构建），PWA | `static/index.html`, `static/js/*.js`（8 个模块）, `static/style.css` |
| 数据库 | SQLite × 2 | `delector.db`（主库）, `progress.db`（学习进度） |
| 音频缓存 | 本地 `.cache/audio/` MP3 | Edge Neural TTS（桌面 edge-tts；Android 无 wheel 时走 stdlib 版 `edge_tts_mini.py`）+ 有道/百度兜底 |
| 桌面打包 | PyInstaller | `package_windows.py` |
| 移动打包 | Chaquopy + Gradle | `android/` |
| CI/CD | GitHub Actions | `.github/workflows/build-release.yml` |
| 部署 | Docker Compose 可选 | `Dockerfile`, `docker-compose.yml` |
| 测试 | pytest | `test_server.py`（~130）, `test_syntax_tree.py`（15）, `test_core_dict_ext.py`（5）, `test_edge_tts_mini.py`（10）, `test_writing_rules.py`（19）, `test_start.py`（4）— 共 230 |
| 提交守卫 | pre-commit 密钥扫描（文件名+内容+编码 keystore） | `.githooks/pre-commit` |
| 环境变量 | `.env`（已 gitignore） | `.env.example` 有字段说明 |
| PWA | Service Worker + Web Manifest | `static/sw.js`, `static/manifest.json` |
| CI 限制 | 无 Android SDK 时本地不伪称构建通过；CI 负责 Gradle 与验签 | `.github/workflows/build-release.yml` |

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
  `.example`/`.sample`/`.template` 放过）+ **PKCS12/JKS/JCEKS 编码 keystore 拦截**
  （文件名 `*.p12/*.pfx/*.jks/*.b64` + 内容中 PKCS12/JKS/JCEKS base64 特征，`.example`/`.sample` 放过）。
  扫的是**暂存文件全文**而非 diff 新增行，
  因为按行 diff 会漏掉"把含密钥的行挪到另一个文件"。
  误报走行内 `delector:allow-secret` 注释（豁免留在 diff 里可被审阅）；
  **不要用 `git commit --no-verify` 跳过**。
- 真实 key 走环境变量或 `.env`（已 gitignore），绝不硬编码。
- `POST /api/settings` **仅回环可写**（v4.4.0）：`GET /api/settings` 保持可读；敏感字段写入与
  `POST /api/settings/test-key`、备份相关 ` /api/backup/*` 均要求 `127.0.0.1`/`::1`
  （含 IPv4-mapped 回环），局域网返回 403。这是 Android 只绑回环的延续；桌面端仍绑 `0.0.0.0`
  保持同 Wi-Fi 阅读能力，但局域网不得修改敏感设置。

---

## 本机开发环境

```text
启动命令:  python start.py   或   start.bat
地址:      http://localhost:8000（桌面端同时绑 0.0.0.0，同 Wi-Fi 设备可访问；敏感设置仅回环可写）
数据库:    D:\Code\DeLector\delector.db（主库）
           D:\Code\DeLector\progress.db（进度）
NLP 模型:  优先 de_core_news_md，缺失则 de_core_news_sm（本机装的是 sm）
测试:      pytest            （230 个，全绿）
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
| **v3.9.0 `2026-08-19`** | **feat(dict & lookup)**: 离线词库 443→4300 词（`tools/build_dict.py` 用 DeepSeek 对歌德 A1-B2 词表批量生成中文释义，落地 `core_dict_ext.py` Python 模块，Chaquopy/PyInstaller 可直接打包）；查词链修复——前端带 spaCy lemma + 服务端 lemma 优先（`geht→gehen`/`Häuser→Haus` 命中）、接线 `LINGUISTICS_VOCAB_EXT`、现在时强动词反查表（`ist→sein`）、UX 诚实显示（空释义不再谎称"AI 已预填"，标 `暂无离线释义`） |
| **v3.9.1 `2026-08-19`** | **fix(android & mobile)**: 修复三个真机 bug——① **安卓 TTS 无声**：edge-tts 及其依赖无 Android wheel，APK 内 `import edge_tts` 必挂；新增 `edge_tts_mini.py`（纯 stdlib 复刻 Edge TTS WebSocket+Sec-MS-GEC 协议，零依赖，Chaquopy 可用），server 合成链改为 `edge_tts → edge_tts_mini → 有道/百度兜底`；player.js 兜底不再忽略原生 TTS 返回值静默推进，三层全败时显示 `⚠ 语音引擎不可用`；MainActivity 原生 TTS 增加德语 voice 遍历兜底。② **手机端点不到倍速**：播放器原单行 flex 横向溢出把倍速挤出屏外，移动端改三行布局（transport / 声音+模式 / 倍速独占整行均分，全部 ≥40px 触控）。③ **抽屉白色遮挡**：底部 sheet 从 72vh 降到 55vh、移动端复位阅读区全宽（桌面右抽屉收缩规则在手机上算成负值）、backdrop 0.35→0.22。CI cp 列表加入 `edge_tts_mini.py` |
| **v3.10.0 `2026-08-20`** | **feat(android & data)**: Android 钉死签名 keystore + CI 验签闸（支持升级覆盖）+ 介词搭配数据集 `prep_dict.py` 扩充至 531 词条/660 条搭配 |
| **v3.11.0 `2026-08-21`** | **feat(writer)**: 德语写作润色台首发：本地规则引擎（冠词/格位一致 + 介词支配格，零误报准则）+ 行内波浪下划线 + 侧栏详解 + 错误一键存 Anki 语法卡 + essays 草稿库 + 显式全文 AI 润色 |
| **v3.12.0 `2026-08-21`** | **feat(writer & ide)**: 德语写作台 IDE 化：句子级 `essay_diff.py` 引擎 + AI 润色逐 hunk 并排审查（左原句 \| 右改写，单条接受/拒绝与一键全选）+ `essay_versions` 类 git 快照管理（手动保存、AI 润色应用自动快照、可逆恢复检查点 `恢复到版本 N 之前`）+ 侧栏诊断/历史双 Tab 联动 |
| **v4.0.0 `2026-08-21`** | **feat(writer & ide)**: 德语写作台内联 IDE 编辑器（contenteditable 零依赖行内实时波浪线诊断 + TreeWalker 光标记忆 + 防抖 400ms 规则诊断 + 悬浮提示气泡 + 一键修正替换 + 句子导航）+ Git 版本管理完善（只读预览不产生检查点 + 版本快照单项删除）+ 动词固定介词搭配规则优先匹配（如 `warten auf + Akk`） |
| **v4.1.0 `2026-08-21`** | **feat(writer & hints)**: 德语写作台 Inlay Hints 语法内联提示（介词支配格 `mit [Dat]` / `in [Dat/Akk]` + 名词短语实际性数格 `[Neut·Dat]` 独立 `#ide-hint-layer` 覆盖层装饰渲染、`pointer-events: none` 绝不抢光标、工具栏全局开关 `toggleInlayHints()`、与波浪线错误并存呈现矛盾教学高光） |
| **v4.1.1 `2026-08-21`** | **fix(writer & hints)**: 德语写作台 Inlay Hints 架构升级为 VSCode 级真实 Inline 布局：CSS `::before` 伪元素（DOM 无 text node）+ `contenteditable="false"` 内联排版，打字时后续文本自然平移推开绝不遮挡，TreeWalker 提取纯净正文 0 字符污染，光标自然跃迁 |
| **v4.2.0 `2026-08-21`** | **feat(writer & problems)**: 德语写作台 Problems 问题清单面板（全篇错误/提醒清单 + severity 分级 + error 错误优先与双格介词 warning 提醒 + 联动滚动定位/波浪线高亮/一键修正） |
| **v4.3.0 `2026-08-22`** | **feat(writer & mobile & security)**: Android/移动端写作台适配（写作主屏、Problems bottom-sheet、触屏错误详情与一键修正、版本/diff 移动回退、Android 默认关闭 Inlay Hints）+ **安全加固**：前端存储型 XSS 全量修复（新增 `core.js#jsAttr`，卡片词/文章标题/RSS 条目等 9 处「esc 进 JS 字符串字面量」注入点全部换核；reader.js 朴素反斜杠转义删除）、SSRF 加固（重定向逐跳请求前校验 + getaddrinfo 全地址族检查）、TTS 长度闸 1000 字符、TTS 端点 HTTPException 不再被吞成 500 |
| **v4.4.0 `2026-08-22`** | **fix(security & reliability)**: 可靠性与安全收口——敏感设置与备份接口仅回环可写（局域网 403，含 IPv4-mapped 回环校验）、pre-commit 编码 keystore 拦截补齐（PKCS12/JKS/JCEKS，文件名+base64 特征，示例不误报）、CI 真 Gradle 构建与 APK 内容/签名双重验签闸（`keytool -printcert -jarfile` + 定值指纹）、写作规则零误报加固（零冠词/双格介词/词典缺性别/spaCy 缺席降级反例全绿）、备份/AI 失败路径回归（非本机备份隔离、Android spaCy 真模型加载契约、AI 402/超时不吞错）；词库缺口盘点 110 词（2 连字符 + 57 长复合词，30 条缓存待合入，80 条 AI 未返回，API 401 暂缓）；测试 230 全绿，仅保留 14 条 linguistics 重复键既有告警 |
| v4.4.1–v4.4.4 `2026-08-22` | **fix(mobile/sw/android)**: 写作台移动端面板交互（阻止冒泡 + 自动切 Tab）、SW 强制刷新所有页面、版本号自动从 tag 推导、写作台面板被 dock 遮挡（z-index 120→1100） |
| **v4.4.5 `2026-08-23`** | **fix(android & writer)**: ① **升级后前端不更新**根治：`MainActivity.syncStaticAssets()` 按 `BuildConfig.VERSION_CODE` 与 `filesDir/static.version` 标记比对，不一致就删整个 `static/` 重解包（`copyAssetFile` 见文件已存在即跳过 + 覆盖安装不清 `filesDir` = 旧文件永不被覆盖，而新增文件照常拷入，设备停在**新旧混合**状态；用户此前只能卸载重装）。配套 `server.py` 新增 `add_frontend_no_cache_headers` 中间件发 `Cache-Control: no-cache`（裸 `StaticFiles` 一个缓存头都不发，浏览器走启发式新鲜度），**退役 `?v=` 查询串**（挡不住磁盘旧文件，且从未覆盖 `main.js` 的裸路径 module import），删除 `sw.js` 里从未执行过的 `STATIC_ASSETS` 死清单。② **写作台三 Tab 交互统一**：整行点击 = 定位/预览（版本快照行补齐，删掉 👁️ 查看按钮，行内破坏性按钮 `stopPropagation`），结果落在编辑器的点击自动收起移动端 bottom sheet，`openWriterProblem` 仅 error 分支切到 diag（warning 切过去只会露出陈旧错误卡），`toggleWriterMobilePanel` 真正可开可关且不再覆盖用户选定的 Tab，删除文件头部无效的兄弟节点 `stopPropagation`（顺带恢复 `'use strict'` 为有效指令）。测试 238 全绿 |
| **v4.4.6 `2026-08-23`** | **fix(release)**: 顶栏版本指示灯与发布版本对齐。v4.4.5 bump 了 `sw.js` 的 `CACHE_NAME` 和 `build.gradle` 的 fallback，唯独漏了 `index.html` 顶栏 `System · v4.4.4 Online` —— 而它是用户判断「前端刷新了没有」的唯一肉眼指标，于是修好的升级链路被指示灯报成"没生效"，且该现象与"缓存闸失效"无法从外部区分。拆 v4.4.5 的 APK 确认包内 `assets/static/` 全是新前端（`sw.js`=v4.4.5、`writer.js` 含 toggle 修复、`index.html` 无 `?v=`）、`classes3.dex` 含 `syncStaticAssets`/`static.version`、manifest `versionName=4.4.5` —— 打包与代码都对，只有那一句字面量是旧的。`test_version_is_consistent_across_release_surfaces` 新增该标签断言（已用故意改回旧值验证会红），版本号三处落点由测试锁死。② **移动端写作台面板位移 / 底部滚不到**根治：`.writer-sidebar` 在 ≤860px 是 `position: fixed` + `bottom` 锚点 + **只有 `max-height`、没有 `top` 也没有 `height`**，高度跟内容走而盒子锚在底边 = 只能向上长，于是切 tab（诊断 3 卡 ↔ 清单 1 卡 ↔ 快照 2 卡）、点诊断行填错误卡、问题清单从"暂无"变 N 条，每一次都把顶边挪到新位置 —— 三个 Tab 都在眼前跳，用户最早报的"诊断分析点了像收起了"就是跳得最狠的那个。改用 `height: min(76vh, 680px)` 把几何固定成同一矩形（代价：内容少时下方留白，换可预期的几何，标准 bottom sheet 也是固定 detent）。配套两件必需品：内层 `.writer-sent-nav-list` / `.writer-problem-list` / `.writer-version-list` 在移动端 `max-height: none; overflow-y: visible`（原本 220/460/320px 各自开滚动区，几乎占满 600px 的 sheet，手指落下去就被内层吃掉、外层没地方可抓 = 底部永远滚不到），以及 `.writer-pane` 补 `flex-shrink: 0`（父容器高度一确定，flex 子项默认会被压缩到塞得下为止、然后自己的内容再溢出去，结果是内容挤成一团而父容器没有可滚动的溢出 —— 少这一行，固定高度反而让 sheet 更滚不动）。测试 239 全绿 |
| **v4.4.7 `2026-08-24`** | **fix(writer)**: ① **桌面端侧栏几何收口**（v4.4.6 移动端修复的同族另一半）：`.writer-sidebar` 基规则是 `position: sticky; top: 4.5rem`，在 `align-items: start` 的 grid 列里高度跟内容走，**没有 `max-height` 也没有 `overflow-y`** —— 内容一旦高过视口，超出的下半截就永远停在视口外，因为 sticky 只在自己的 grid 行内平移，页面滚到底也带不出来。补 `max-height: calc(100dvh - 4.5rem - 1rem)` + `overflow-y: auto`（用 `max-height` 而非 `height`：sticky 列必须高度自适应，写死会在内容少时撑出空白），并把内层三个列表的 `max-height`（220/460/320px）+ `overflow-y` **从基规则整体删除** —— 滚动只归 sidebar 一个人管，与移动端同构；随之移动端媒体块里那条 `max-height: none` 并集覆盖成为冗余，一并删掉。`.writer-panel-tabs` 的 `position: sticky; top: 0` 从移动端块**上提到基规则**，桌面/移动共用（滚动容器内 tab 吸顶，切 tab 不必先滚回去）。移动端 sheet 显式补 `max-height: none` 解掉新继承来的基规则帽子 —— 不解也不出错（有 `height` 在，几何仍是定值），但留着就意味着读那条规则的人看不出还有另一处在影响高度。② **三行触屏按压反馈**（v4.4.5 遗留）：`.writer-nav-item` / `.writer-problem-row` / `.version-item` 此前只有 `:hover`，而触屏上 `:hover` 不触发或点完粘住，等于按下去毫无反馈。补 `:active` 背景压暗（problem/version → `--paper-deep`，nav → ink alpha 0.12）+ 并集规则清零 `-webkit-tap-highlight-color`（否则安卓 WebView 自带灰块与自定义按压色叠着闪）。**不加 transform**：hover 的 `translateX(2px)` 留给鼠标，整行 flex 容器做位移会带来 1px 文字抖动。`.version-item:active` **必须排在 `.version-item.version-checkpoint` 之后** —— 两者特异性同为两个类的量级，同分时源序决定胜负，写前面则 checkpoint 行（最常被点的一批）没有任何按压反馈；测试直接断言这个源序。③ 修 `.writer-problems-stat-pill` 的 `color: var(--ink-secondary)` —— 该变量从未在 `:root` 定义过，文字色静默回退，改用 `--ink-mute`；新增未定义 CSS 变量棘轮测试（`KNOWN_LEGACY_UNDEFINED` 显式列出 5 个历史欠账让它们可见，新增的会变红）。④ 顺带把 `test_version_row_hover_matches_other_rows` 从 `split(".version-item {")` 换成按括号深度取规则体的 `_rule_body()` —— 新增的并集规则也以 `.version-item {` 结尾且更靠前，`split` 会抓错规则。**8 条变异全部验证会红**（去掉帽子/改成 height/列表回退自带滚动/tab 取消吸顶/删 `:active`/删 tap-highlight/`:active` 移到 checkpoint 前/变量名改回去）。测试 242 全绿 |

---

## 已知问题 / 待办

> 更新时间：2026-08-24（v4.4.7 打点）

- [x] ~~**安卓升级后前端永远是旧的，只有卸载重装才好**~~ — v4.4.5 已修。根因是两件事叠加：
      `copyAssetFile()` 见目标文件已存在且非空就 `return`（原意是省冷启动 I/O），而
      **APK 覆盖安装不清空 `getFilesDir()`**（只有卸载才清）。于是旧 HTML/CSS/JS 永不被覆盖，
      但**新增**文件仍会照常拷入 —— 设备停在「新旧混合」状态，比全旧更难排查，
      因为版本自洽性没了。`?v=` 查询串对此完全无效（磁盘上那份就是旧的，URL 与内容自洽），
      而且它连覆盖面都不全（`main.js` 的 module import 全是裸路径）。
      修法：`syncStaticAssets()` 用 `BuildConfig.VERSION_CODE` 对 `filesDir/static.version`
      标记做闸门，不一致就删整个 `static/` 重解包；版本一致时保留跳过快路径。
      **删除范围硬编码在 `filesDir/static` 并二次校验身份** —— 同级躺着 `delector.db`
      与 `progress.db`，装着用户全部学习数据，删错一级不可恢复。
      标记只在 `index.html` 确实解包出来后才写（`copyAssetFolder` 把 IOException 咽进
      `printStackTrace`，返回值不可信），宁可下次启动重试也不把半途失败记成"已最新"。
      ⚠️ **本机无 Android SDK，Java 改动未经编译**，但 **v4.4.5 的 APK 已拆包验证落包**：
      `assets/static/` 内 `sw.js`=`delector-static-v4.4.5`、`writer.js` 含 v4.4.5 的 toggle 修复、
      `index.html` 已无 `?v=`（v4.4.4 里有），`classes3.dex` 含 `syncStaticAssets` /
      `static.version` / `deleteStaticDir`（`minifyEnabled false`，符号未混淆），
      manifest `versionName=4.4.5`，且无 `assets/static/static/` 嵌套。
      打包与代码都对，剩下的只有运行时。真机验收清单：
      ① 装 v4.4.6 → 覆盖安装 v4.4.7（**不要卸载**）→ 顶栏应显示 `System · v4.4.7 Online`；
      ② 同时确认文稿/词卡/复习进度**全部存活**（验证删除范围没越界）；
      ③ `buildFeatures { buildConfig true }` 已显式打开（AGP 8 各版本默认值不同，
      关掉的话报 `cannot find symbol BuildConfig`，且只在 CI 编译时才炸）。
- [x] ~~**修好了却看起来没修好：顶栏版本指示灯漏 bump**~~ — v4.4.6 已修。v4.4.5 把
      `sw.js` 的 `CACHE_NAME`、`build.gradle` 的 fallback 都 bump 了，却漏了
      `index.html` 顶栏那句 `System · v4.4.4 Online` —— 而它是用户判断
      「前端到底刷新了没有」的**唯一肉眼指标**。结果：升级链路确实修好了，
      指示灯却照旧报 v4.4.4，用户理所当然判定"修复没生效"，而这个结论
      与"缓存闸失效"在现象上完全无法区分，只能靠拆 APK 才分得开。
      **教训**：给用户看的状态指示器和它所指示的东西必须同源或被测试锁死，
      否则指示器自己会成为最难排查的一类 bug —— 它不会让任何测试变红，
      只会让所有人对着正确的系统查错。现在该标签与 `sw.js`、`build.gradle`
      三处由 `test_version_is_consistent_across_release_surfaces` 一起断言。
      **发版新增落点时先问一句：它有没有出现在那个测试里。**
- [x] ~~**工作流硬编码资产名**：已参数化为 `${{ github.ref_name }}`~~
- [x] ~~**写作台行的触屏按压反馈缺失**~~（v4.4.5 遗留）— v4.4.7 已修。`.writer-nav-item` /
      `.writer-problem-row` / `.version-item` 三者原先只有 `:hover` 规则、没有 `:active`。
      触屏上 `:hover` 不触发（或触发后粘住不放），等于点下去没有任何即时反馈 —— 用户报的
      "点击后行为看不懂"有一部分是这个。现补 `:active` 背景压暗 + 并集规则清零
      `-webkit-tap-highlight-color`，不加 transform（整行位移会有 1px 文字抖动）。
      **`.version-item:active` 必须写在 `.version-item.version-checkpoint` 之后**：
      两者特异性相同，同分靠源序，写前面则 checkpoint 行按下去毫无反馈。
      **注意**：诊断分析 pane 的高度会变是结构性的（中间那张错误详情卡在占位符 ↔ 错误卡
      之间切换），代码里**不存在任何折叠机制**，别去找不存在的 accordion。
- [x] ~~**桌面端写作台侧栏下半截滚不到**~~ — v4.4.7 已修（移动端同族问题 v4.4.6 已修）。
      `.writer-sidebar` 基规则是 `position: sticky; top: 4.5rem`，处在 `align-items: start`
      的 grid 列里、高度跟内容走，却**既无 `max-height` 也无 `overflow-y`**。sticky 元素
      比视口高时，超出部分永远停在视口外 —— sticky 只在自己的 grid 行内平移，页面滚到底
      也带不出来。修法与移动端同构：加 `max-height: calc(100dvh - 4.5rem - 1rem)` +
      `overflow-y: auto`，并把内层三个列表的高度帽从基规则删除，**滚动只归 sidebar 一个人管**。
      用 `max-height` 而不是 `height`：sticky 列必须高度自适应，写死会在内容少时撑出空白。
- [x] ~~**移动端面板整块位移 / 底部永远滚不到**~~ — v4.4.6 已修。三个缺陷叠在一起：
      ① `.writer-sidebar` 在 ≤860px 是 `position: fixed` + `bottom` 锚点，却**只有
      `max-height`、既没 `top` 也没 `height`** —— 高度跟内容走 + 锚在底边 = 只能向上长，
      于是每次切 tab / 填错误卡 / 清单从空变 N 条都把顶边挪到新位置。改用
      `height: min(76vh, 680px)` 固定几何。
      ② 内层三个列表各自 `max-height` + `overflow-y: auto`（220/460/320px），
      在约 600px 的 sheet 里几乎占满可见区域，手指落下去被内层吃掉、
      外层没有可抓的地方 = sheet 自己的底部永远滚不到。移动端一律
      `max-height: none; overflow-y: visible`，**滚动只归 sheet 一个人管**。
      ③ `.writer-pane` 必须 `flex-shrink: 0`。父容器高度一确定，flex 子项默认
      被压缩到塞得下为止、然后自己的内容再溢出去 —— 结果内容挤成一团而
      父容器没有可滚动的溢出。**少这一行，①的固定高度会让 sheet 更滚不动**，
      看起来像修复让问题变严重了。
      **教训**：高度和滚动的归属只能有一个主人。外层容器和每个内层列表都想管，
      就会出现"谁都在管、谁都没管好"——而症状（跳动 / 滚不到）看起来像两个
      互不相关的 bug，实际是同一个根因的两面。
- [ ] **5 个 CSS 变量从未定义**（v4.4.7 盘点，全部是历史欠账）：`--border`、`--font-sans`、
      `--note-blue`、`--paper-accent`、`--paper-warm`。变量未定义不会报错，只会让那条属性
      静默回退（颜色变成继承色、字体落到默认栈），肉眼几乎看不出，但设计意图丢了。
      已确认 `--note-blue` 是真缺口：兄弟 `--note-green/pink/yellow` 都在 `:root` 里，
      只有 blue 没有，于是 `.memo-card:nth-child(3n)` 拿不到背景色。
      这 5 个已被 `test_no_undefined_css_variables_in_writer_surfaces` 的
      `KNOWN_LEGACY_UNDEFINED` 显式列出（**棘轮**：新增未定义变量会让测试变红，
      修好后要把条目从集合里删掉，否则它会慢慢变成一张永久豁免名单）。
- [ ] **写作台版本行的按钮尺寸/危险色缺失**（v4.4.7 划出的单独事项）：`.btn-xs` 与
      `.btn-del` 两个类**在 CSS 里从未定义**，于是版本快照行的「恢复/删除」按钮走 `.btn`
      的 `min-height: 36px`、在紧凑行里显得过大，且删除按钮没有任何危险色提示。
      没顺手改是因为按钮配色要和全站危险按钮约定一起定（不能只在写作台拍一个红色），
      夹在几何修复里会模糊版本边界。
- [ ] **Grep 工具会把 `/*` 渲染成 `\*`**（v4.4.7 踩坑，工具产物而非代码问题）：
      用 Grep 读 CSS 注释行时输出形如 `\* 说明文字`，看着像把注释开头写坏了
      （曾据此误判 style.css:339/341 与 6996 三处"注释畸形会吞掉后续规则"）。
      用 Read 或 Python 读原始字节确认过：文件里是正确的 `/*`。
      **结论：怀疑源码有畸形字符时，别用 Grep 输出当证据，去读原始字节。**
- [ ] **DeepSeek API Key 失效/余额耗尽（401/402）**：2026-08-20 新 key 曾报 402（余额耗尽），2026-08-22 复测 `.env` 与 DB 两处 key 均报 401（`Authentication Fails, api key invalid`）。影响全部 AI 功能（查词在线兜底、语法剖析、笔记辅助）和构建工具。**介词数据集已在充值后跑完（531 词条/660 搭配）**；词库 refill 受阻见下条。
- [x] ~~**介词搭配数据集只覆盖了一半词表**~~ — 2026-08-20 已跑完：1773 个动词/形容词
      问到 1729 词（97.5%），**531 词条 / 660 条搭配**（含 47 条人工 `SEED_COLLOCATIONS`
      floor）。中途发现第一版校验器把介词与冠词的缩合形式（an+dem=am、in+das=ins）
      当成幻觉，误杀 12 条正确搭配 —— 已修并重问全部批次，重放 0 误杀。
- [ ] **45 个词头 AI 始终不作答**（v3.10.0）：`sich-freuen`/`auf-jeden-fall` 这类
      多词与反身连字符键，以及 `eindeutige`/`hiesigen` 这类形容词屈折形。提示词按
      单个词元设计，处理不了这些形状；重问只是白花钱。注意连字符键**不都是**坏数据：
      `see-meer` / `see-teich`、`bank-geldinstitut` / `bank-sitzgelegenheit` 是词库
      刻意用来区分同形词的，`fertig-sein` 等 8 条也已拿到搭配 —— 不要一刀切按连字符过滤。
- [x] ~~**签名迁移只能靠 CI 验证**~~ — 2026-08-20 v3.10.0 tag 首跑已在真实 runner 验证：
      第一次跑死在验签闸 —— 不是签名错，是 `keytool -printcert -jarfile` 只认 v1 签名，
      而 AGP 在 minSdk≥24 时默认只出 v2/v3，闸读出空指纹分不清「真没签名」和「读不到」。
      修法：签名配置显式 `v1SigningEnabled true`（build.gradle 有注释，测试钉住）。
      重跑后闸读到了 APK 与 keystore 两个指纹，均等于期望值，四平台全绿、Release 已发布。
- [x] ~~**工作流里 `EXPECTED_SHA256` 仍为空**~~ — 2026-08-20 已填入
      `9A:8A:6D:…:57:9C`（公开信息）。两道断言都是无条件的：APK↔keystore 自比对拦
      「secret 缺失 → 回落随机签名」，定值比对拦「keystore 被换成另一份合法 keystore」。
      有测试断言该值是大写冒号分隔的 32 字节指纹，防止将来被清空导致闸静默退化。
- [x] ~~**pre-commit 的 keystore 防护缺口**~~ — v4.4.0 已补齐 PKCS12/JKS/JCEKS 编码 keystore 拦截（文件名 `*.p12/*.pfx/*.jks/*.b64` + 内容 JKS/JCEKS base64 magic + PKCS12 长串 base64 特征，`.example`/`.sample` 放过，`delector:allow-secret` 可豁免）。
      残留缺口仅剩：PKCS12 base64 存成不叫 `*.b64` 的纯文本且无 JKS/JCEKS magic 时，前缀 `MII` 太通用无法单独拦截（加了会把公开证书全误拦，见 `test_precommit_allow_sample`）。
- [ ] **旧安装无法升级到 v3.10.0**：v3.9.1 及更早的 APK 是用 CI 每次随机生成的
      debug keystore 签的，与钉死的证书不一致，必须**卸载重装**（数据全丢，
      且 v3.9.1 的安卓端备份导出本身是静默无操作，无法自救）。
- [ ] **`linguistics.py` 有 14 条 pyflakes 重复键告警**（`klima`/`schutz`/`bund` 等在
      `LINGUISTICS_VOCAB_EXT` 与另一张表里各出现一次，值不同）：先前就有，未在本次改动范围内，
      但确实意味着有一份定义被静默覆盖，值得单独查一次
- [ ] **离线词库尾缺口 110 词**（v4.4.0 盘点：词库 4301 词，候选源 4377，剔除 `linguistics` 后净缺口 110）：2 连字符（`ost-west-gefälle`、`ozg-onlinezugangsgesetz`）+ 57 长复合词（>10 字符，如 `aufklärungsdrohnen`/`erkenntnisgewinn`）+ 形容词屈折形（`aufwendige`/`fleischlastige`/`forschende` 等）。
      其中 30 条在 `tools/raw/batch_*.json` 已有原始响应缓存（待合入 `core_dict_ext.py`，如 `absender`/`dauer`/`drucker`），80 条 AI 从未返回（`abbiegen`/`abdanken`/`abenteuer`/`abfahrt` 等，含 B1/B2 派生词/低频词）。
      `python tools/build_dict.py --refill --parallel 8` 2026-08-22 复测因 API Key 401 暂缓（`.env` `sk-a1293…99a9` 与 DB `sk-c73dd…e9c6` 均 `invalid_request_error`）；已保留原始响应缓存，校验在读取时执行，不伪造条目，不提交空缓存。详见 v4.4 report。
- [ ] **安卓 TTS 依赖联网 Edge TTS 服务**（v3.9.1）：APK 内无离线 TTS 引擎，
      `edge_tts_mini` 直连 `speech.platform.bing.com`（与桌面端同一服务，本机/用户网络实测可达）。
      真机若连不上该域名（或离线），三层兜底全败时播放器显示 `⚠ 语音引擎不可用`（不再静默）。
      原生 TTS 仅当设备装有德语语音时才可用（国内机型多无 Google TTS 德语数据，已做 voice 遍历兜底）
- [x] ~~**已合并的分支未删**：`fix/android-startup-and-spacy`~~ — 2026-08-20 本地与远端都已删
- [ ] `de_core_news_md` 本机未安装，所以 md 优先这条路径**只验证了回退到 sm 的行为**，
      md 实际加载未在本机跑过（CI 覆盖可选加载路径）
- [ ] Android 侧 Java 代码无法本机编译验证（本机无 Android SDK），只能靠 CI
- [ ] 首次启动因 `extractPackages` 解包约 30MB 而明显变慢，尚未在真机上实测耗时
- [x] ~~安卓版启动卡在「正在启动」页并超时~~ — PR #2 已修（根因：降级路径 `NameError`）
- [x] ~~安卓版语法标注错误（无五场域/AST，可分动词回连失败）~~ — PR #2 已移植真 spaCy，真机验证通过
- [x] ~~Android 上无鉴权 `POST /api/settings` 暴露给局域网~~ — PR #2 改为只绑 `127.0.0.1`；v4.4.0 进一步收口桌面端：敏感设置与备份接口仅回环可写（`test_settings_from_non_loopback_blocked` 等 230 项全绿）
- [x] ~~Android 失败不可见 + WebView 无限重载~~ — PR #2 已修
- [x] ~~仓库无提交前密钥扫描~~ — PR #2 已加 `.githooks/pre-commit`；v4.4.0 补齐编码 keystore 拦截并加 `test_precommit_*` 契约
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
9. **缓存问题**：**不要再用 `?v=X.X.X` 查询串给 CSS/JS 打版本号**（v4.4.5 已退役）。
   它挡不住真正的问题，还制造了安全感：安卓覆盖安装后磁盘上那份文件本身就是旧的，
   请求 URL 与响应内容是一对自洽的旧配对；而 `main.js` 的 ES module import 全是裸路径
   （`./core.js` 等），从来就没被版本串覆盖过。现在两道真闸门是：
   - **服务端**：`server.py` 的 `add_frontend_no_cache_headers` 给 HTML/JS/CSS 发
     `Cache-Control: no-cache`（强制回源校验，靠 StaticFiles 已有的 ETag 命中 304；
     不用 `no-store`，那会禁掉全部缓存并削弱 PWA 离线能力）。
   - **安卓端**：`MainActivity.syncStaticAssets()` 按 `BuildConfig.VERSION_CODE` 比对
     `filesDir/static.version` 标记，不一致就删掉整个 `static/` 重解包。
   发版要 bump 的版本号有**三处**，`test_version_is_consistent_across_release_surfaces`
   会断言它们完全一致（改一处漏两处 = 测试红，不用靠记性）：
   - `static/sw.js` 的 `CACHE_NAME`（决定 activate 何时清旧缓存）
   - `android/app/build.gradle` 的 `DELECTOR_VERSION_NAME` / `..._CODE` fallback
     （`versionCode` = `major*10000 + minor*100 + patch`）
   - `static/index.html` 顶栏 `System · vX.Y.Z Online` —— **别把它当装饰**。
     它是用户唯一能肉眼判断「前端刷新了没有」的指示灯。v4.4.5 就漏了这一处：
     升级链路修好了，指示灯照旧报旧版本，于是"修复没生效"与"缓存闸失效"
     在现象上无法区分，最后只能靠拆 APK 才排查清楚。
     **指示器和它指示的东西必须被同一个断言绑住**，否则指示器本身会成为
     最贵的一类 bug —— 它不让任何测试变红，只让所有人对着正确的系统查错。

---

*此文件由 agent 维护，人工可随时追加注释。请保持全文唯一，不要追加重复副本。*
