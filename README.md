# DeLector · 德语欧标沉浸精读与考点剖析工作台

<p align="center">
  <img src="https://img.shields.io/badge/Release-v5.17.0-blue?style=flat-square" alt="Release Version" />
  <img src="https://img.shields.io/badge/Python-3.10%20%7C%203.11-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python Version" />
  <img src="https://img.shields.io/badge/FastAPI-0.110+-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/spaCy-German%20NLP-09A3D5?style=flat-square&logo=spacy&logoColor=white" alt="spaCy" />
  <img src="https://img.shields.io/badge/CEFR-A1~C1%20Goethe-E63946?style=flat-square" alt="CEFR Ladder" />
  <img src="https://img.shields.io/badge/AI%20Model-deepseek-brightgreen?style=flat-square" alt="AI Model" />
  <img src="https://img.shields.io/badge/Tests-1768%2F1770%20Passed-2EA44F?style=flat-square" alt="Pytest" />
  <img src="https://img.shields.io/badge/License-MIT-gray?style=flat-square" alt="License" />
</p>

<p align="center">
  <b>专为德语学习者与歌德（A1–C1）/ 德福（TestDaF）/ DSH 备考打造的下一代学术级伴读与句法剖析系统。</b><br/>
  融合<b>歌德 A1 全真听说读写考场工坊</b>、<b>德语伴读宠物（Eule & 伙伴）</b>、<b>Atelier 落地页画册台账</b>、<b>拓扑五场域</b>、<b>AST 从句语法树</b>、<b>内联 IDE 写作工坊</b>与<b>FSRS 现代认知记忆排程</b>。
</p>

---

## 📦 多平台下载发布包 (Downloads)

> ✅ **v5.17.0 首个原生桌面壳 + 首次数据落点外置（2026-10-11）**：本版载荷**不是"几条小修"**。**①首发原生桌面窗口**——`pywebview`（走系统 Edge WebView2）+ `pystray` 托盘 + splash + 统一退出收尸（修掉"退出不干净 ⇒ 下次盲复用端口、以为升级了其实跑旧进程"）；`v5.16.0` 里 `desktop.py` **根本不存在**。同批修掉两个 P0：窗口永不出现的**时序死锁**（`evaluate_js`/`load_url` 在 `webview.start()` 之前调用）、真实 UI 被塞进 splash 小窗。**②数据落点外置**到 `%LOCALAPPDATA%\DeLector`（`start.py` 调 `bootstrap_data_dir` 由 **0 → 3** 次），修掉唯一真会丢东西的摩擦：**升级时解压覆盖 = 学习记录全空且零提示**（首迁留 `.bak`，保留便携开关可回退）。**③更新可见性上线**——顶栏落后 chip + `GET /api/update/check`（GitHub Releases 唯一真相源；成功 6h / 失败 60s TTL）。**④六条已装用户拿不到的修复随本版到达**（`static/` 内嵌在产物里）：错高亮命中对齐、列表成本 **918ms → 8.9ms**、静态首屏少 **383.4 KB**（工作台 iframe 惰性化）、四条 P0（建服前端口/身份校验、`get_setting` 不再吞异常、`openReader` 失败可见、评分防连点）、"列表 A2 → 点进去 A1"的**难度跳变**经构建期预生成 `preset_processed.json` 消灭（未命中给可见 WARNING，不许静默降级）。**⑤spaCy 模型惰性加载**——冷启动 `health_200` **3123 → 2128ms（−32%）**。**⑥CI 加固**——**真启产物闸**（构建后先真启一次产物，坏包不许进 zip；**上线即抓出两个产品真 bug**：`--server-only` 在 stdout 重定向时 `UnicodeEncodeError` 启动即崩、PR 语境版本号把产物嵌套成目录）、前端跨边界契约闸、桌面入口 mypy 门禁、以及**发版门守卫**（tag 必须等于 `v`+`APP_VERSION`，堵"漏 bump 就推 tag ⇒ 更新提示永远落后"）。门禁 **1768 passed + 2 skipped**、探针 **29/29**、`ruff` 0、mypy **87 + 121 + 4** files 零错误。⚠️ 含 `static/` 改动 ⇒ **Android 需覆盖安装生效**；**Win10 用户需先装 WebView2 运行时**（Win11 自带，Win10 缺运行时会提示安装后退出、不白屏）。
> ✅ **v5.16.0 修掉长期潜伏的性能缺陷 + 三处守卫加固（2026-10-06）**：Fog 1~4 全部收口。**① 每次 GET 文章都重跑完整 spaCy（用户可感知）**——追 Fog 2 根因发现惰性迁移判据写死 `"3.4.0"` 而写入端两条路径都写 `"3.5.0"`，判据恒真 ⇒「惰性迁移」退化成「每次迁移」；列表路径早已优化掉这个 N+1，单篇 GET 却一直全量重算，**惰性迁移从未真正生效**。修法＝导出 `PROCESSED_JSON_VERSION` 单一真相源，惰性迁移语义完整保留。**② CI 必需运行时清单显式化**，并钉住两条否定结论：`rm` 全仓不存在、`bash` 判为平台相关，**都不进清单**，防将来误升级为 fail。**③ localhost 守卫加固**——关掉三个「将来会漏」的洞：只认字面 `router`（实有 14 个 router）、prefix 只从单个取（一模块双 router 时键失真且恰好蒙对）、闸调用名漏 `import ... as` 别名；allowlist 20 条逐字未动。**④ 安全 posture 已裁决：内网可信**（不加固 LAN 写端点；不可逆毁数据能力全在闸内 + 128-bit `X-WB-Key` + 加固不会断手机同步）。Fog 3 的 16 处形式统一经裁决**不做**（其收益论证已被实测推翻）。门禁 **1317 passed + 1 skipped**、探针 **28/28**、mypy 93+70 files 零错误。**无 `static/` 改动 ⇒ 桌面端刷新即生效。**
> ✅ **v5.15.0 登记项收口第二轮（2026-10-05）**：把 v5.14.0 遗下的 5 项技术债以「立守卫防漂移」的方式收口。**三条新守卫**——① localhost 受保护路由集合（注释里的「16 处」已漂移，AST 实测 **20 个**；判据用**精确 allowlist** 而非「GET 不该挂闸」，因为有 4 个受保护的敏感 GET）；② **CI 下 node 缺失必须红**（29 处 `shutil.which` skip 会让 CI **全绿而 28 个探针根本没跑**，比红更坏）；③ 探针 `--json` 契约**冻结**（28 个探针 5 种形态，存量 23 条登记过渡 + 「清单不得增长」守卫；判**实跑输出**不是源码文本）。**两处代码修复**——④ **降级标记并发串味**（用户可见：`showView` 与详情的 `resolveDeck()` 以相反结果交错结束时，详情拿到成功 deck 却显示「deck 降级」；改为状态与本次调用绑定，不破坏同源契约）；⑤ 工作台来源判据**单点化**（消除双真相源，E1 从「两份雷同」改为「复用且禁止双写」）。**安全 posture 裁决：内网可信**（用户裁定）——盘点 LAN 暴露面 28 个写端点后确认不可逆毁数据能力全在闸内、`PUT /wb/state` 由 128-bit `X-WB-Key` 保护且 key 无法经 HTTP 从 LAN 取得，且**加固不会断手机同步**；已知代价：LAN 第二台设备保存按钮会 403、AI 端点无配额、写入无审计。测试基线 **1299 passed + 1 skipped**、探针 **28/28**、mypy 70+92 files 零错误；本轮防漏接线守卫**第三次当场抓出漏接线**。⚠️ 含 `static/` 改动 ⇒ **Android 需覆盖安装生效**。
> 
> 📱 **Android 用户注意**：改动含 `static/` 的版本（如 v5.8.0 / v5.9.0）需**覆盖安装**才生效。
> 📜 完整版本历史见 [CHANGELOG.md](CHANGELOG.md)。

| 平台               | 版本                   | 说明                                                                                                                                                                                                                                                       | 下载通道                                                                                    |
| ------------------ | ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| 🪟 **Windows x64** | `v5.17.0` | 原生桌面窗口 + 系统托盘，免装 Python，解压双击 `DeLector.exe`；**需 Win10+ 与 WebView2 运行时**（Win11 自带；Win10 装不上时的表现见「已知限制」）；首次启动把数据放到 `%LOCALAPPDATA%\DeLector`                                                                                                                                                                        | [下载 ZIP 包 (GitHub Releases)](https://github.com/ROM4n2/DeLector/releases/tag/v5.17.0)     |
| 🍎 **macOS**       | `v5.17.0` | 解压运行 `start` 脚本，全自动启动服务与默认浏览器                                                                                                                                                                                   | [下载 TAR.GZ 包 (GitHub Releases)](https://github.com/ROM4n2/DeLector/releases/tag/v5.17.0)  |
| 🐧 **Linux x64**   | `v5.17.0` | 全发行版通用，解压运行 `start` 即可使用                                                                                                                                                                                             | [下载 TAR.GZ 包 (GitHub Releases)](https://github.com/ROM4n2/DeLector/releases/tag/v5.17.0)  |
| 📱 **Android**     | `v5.17.0` | 内嵌 Python 运行时与 spaCy 离线模型，单机独立运行；**支持 arm64-v8a**，CI 钉死签名 keystore 并验签（可覆盖升级）。 | [下载 APK 安装包 (GitHub Releases)](https://github.com/ROM4n2/DeLector/releases/tag/v5.17.0) |

---

## 🧭 文档导航 (Docs Map)

| 需要什么 | 去哪 |
| --- | --- |
| 项目状态 / 红线 / 待办 | `WORKMEMORY/PROJECT_OVERVIEW.md` |
| AI Agent 入口（纯路由） | `AGENTS.md` |
| 产品特性全览 | `FEATURES.md` |
| 架构细节（技术栈 / NLP / DB / API / 前端拓扑） | `docs/agents/architecture.md` |
| 安全守卫 / 本机环境 / 打包 / 工作惯例 | `docs/agents/ops.md` |
| 设计与实施计划 | `docs/specs/`、`docs/plans/` |
| 版本历史 | `CHANGELOG.md` |
| 架构决策记录（ADR） | `docs/adr/` |

---

## 🌟 核心特性 (Features)

- **德语精读工作台**：CEFR 词阶热力图 + 0ms 歌德离线词库 + 荧光便签、AI 导读与打印级《精读指南》导出。
- **句法拓扑与 AST**：经典五场域（VF/LK/MF/RK/NF）色谱条切分 + 5 大从句抽象语法树 + 一键制 Anki 语法卡。
- **FSRS 卡盒与背词工作台**：3D 拟真翻牌 + FSRS 现代自适应排程（消解 Ease Hell）；A1/A2/B1 多档背词台（`VOKABELN`）与介词矩阵视图。
- **备考域 A1–B1**：歌德全真听说读写考场工坊（写作 / 听力 / 阅读 / 口语 / 词表）+ 德福 C-Test + 听力微训 / 长难句精读工坊。
- **遇见区分级阅读**：i+1 阅读桥 + 逐词注解 + 生词一键进卡，配套桌面→手机局域网 P2P 静默同步。
- **内联 IDE 写作工坊 & 伴读宠物**：行内实时语法诊断 + VSCode 级 Inlay Hints；Eule & 伙伴混合双模伴读。

> 完整功能清单见 [FEATURES.md](FEATURES.md)。

> 💬 **用着顺手或别扭，都欢迎说一声**：[开一条零门槛反馈](https://github.com/ROM4n2/DeLector/issues/new?template=feedback.md)——**不用懂技术、不用建分支、不用写 `bug(scope):` 前缀**，三道判断题点一下就行，想吐槽什么随手写（留空也完全 OK）。你的反馈直接决定下一个版本做什么。

---

## 🏗️ 技术栈架构 (Tech Stack)

| 领域             | 核心技术                                   | 说明                                                                                |
| :--------------- | :----------------------------------------- | :---------------------------------------------------------------------------------- |
| **后端框架**     | `FastAPI` + `Uvicorn`                      | 异步高性能 REST API                                                                 |
| **自然语言处理** | `spaCy` (`de_core_news_md` / `sm`)         | 本地高精德语分词、词性标注、形态分析与五场域句法依存                                |
| **形态学引擎**   | `delector/nlp_engine/linguistics.py`                  | 556+ 不规则动词三态表 + 复合词动态规划递归拆解                                      |
| **拓扑句法树**   | `delector/nlp_engine/syntax_tree.py`                  | Vorfeld/LK/MF/RK/NF 五场域切分 + 5 大从句 AST 抽象语法树                            |
| **持久化存储**   | `SQLite 3` (`delector.db` + `progress.db`) | 核心文库与时序台账双库解耦存储                                                      |
| **语音合成**     | `Edge-TTS` (Microsoft Neural Voice)        | 神经级纯正德语离线本地缓存与 Web Speech 回退                                        |
| **前端架构**     | `ES Modules / Modern CSS / Vanilla JS`     | 零 Node 构建依赖、模块化架构、原生 3D CSS 渲染                                      |
| **记忆同步**     | `genanki`                                  | 离线生成标准 `.apkg` 记忆库                                                         |
| **自动化测试**   | `pytest` + `httpx`                         | 全套单元与集成测试用例（数量见顶部 Tests 徽章，100% Green），CI 覆盖 md 加载路径与 Android 构建验签 |

---

## 🚀 快速启动指南 (Quick Start)

```bash
pip install -r requirements.txt          # 安装 Python 依赖
python -m spacy download de_core_news_md # 下载德语 NLP 模型
python start.py                          # 或 Windows 双击 start.bat —— 一键启动并打开浏览器
python desktop.py                        # Windows 桌面壳（原生窗口 + 托盘 + 启动 splash）
docker compose up -d --build             # 或 Docker 容器化一键部署
```

> 开发者首次启用提交前密钥扫描（每个克隆都要做一次）：`git config core.hooksPath .githooks`
>
> 📖 Windows 分支 / Docker 细节 / 环境变量 / 打包 / 安全守卫等完整说明见 [docs/agents/ops.md](docs/agents/ops.md)。

### 📦 数据目录与旧版迁移（桌面端 / Docker 均必读）

**桌面端默认把数据放在用户目录、不随程序目录**：Windows 为 `%LOCALAPPDATA%\DeLector`，
macOS / Linux 为 `~/.local/share/DeLector`；文件是 `delector.db` 与 `progress.db`。两个开关：

- `DELECTOR_PORTABLE=1` ⇒ 数据回到程序目录（U 盘 / 多机场景）；
- `DELECTOR_DATA_DIR=<目录>` ⇒ 显式指定落点（优先级最高）。

**首次从「数据随程序目录」的旧版升级**时会自动搬一次：新位置复制成功后，旧文件改名为
`delector.db.bak-<时间戳>`（**永不删除**，确认无误后可自行清理）。

**Docker 部署的数据落在 `./data` 目录**（`DELECTOR_DATA_DIR=/app/data`）。挂目录而非单文件，
是因为 WAL 会在库旁生成 `-wal`/`-shm`，单文件挂载会在 `docker compose down` 后丢尾写。

⚠️ **从旧版单文件挂载（`./delector.db:/app/delector.db`）升级的用户**：直接
`docker compose up -d --build` 会得到一个**功能正常但数据全空**的应用——旧库还在仓库根，
而容器现在去读 `./data`。**数据文件没有被删除**，只差一次复制：

```bash
mkdir -p data && cp delector.db data/delector.db   # progress.db 同理
```

为杜绝「静默空库」（空库一旦建出，用户的诊断直觉是「数据丢了」，进而可能做不可逆的
恢复出厂操作），应用启动时会自检：**新位置无库 + 旧位置有非空库 ⇒ 拒绝启动**，并在日志里
打印两个绝对路径和一条可直接复制的 `cp` 命令。照做后重启即可。（日志里的 `cp` 给的是
**容器内**路径，要在容器里执行，或用 `docker compose cp`。）

同一条迁移规则对**桌面端手工设 `DELECTOR_DATA_DIR`** 同样适用：把 `DELECTOR_DATA_DIR`
指向一个新目录、而旧位置的 `delector.db` 还在仓库根时，闸会以同样理由拒绝启动，直到你把
库复制到新目录为止。

---

## 📁 目录结构 (Project Layout)

```
DeLector/
├── delector/          # 后端包：server.py(app 工厂) + core/(DB·安全) + nlp_engine/(spaCy·拓扑·AST) + routes/ + services/ + tools/(Agent 工具) + data/
├── static/            # 前端零构建 ES 模块（index.html + js/ 23 模块 + german/ 背词台 + css/ tokens）—— 模块数以 ls static/js/*.js 为准
├── android/           # Android 独立离线单机版工程 (Chaquopy + Gradle)
├── agent/             # Phase 2 Go Agent Runtime（CLI + DAG + 工具注册，预览通道）—— 与 AI agent 规范（AGENTS.md）无关，勿混
├── tests/             # 测试模块（pytest）：以 ls tests/test_*.py 为准（2026-10-16 实测 125 个）+ 迁移哨兵
├── docs/              # 文档：agents/(架构·运维) · specs/(设计) · plans/(实施计划) · adr/(仓内 ADR 副本) · reviews/(评审与评估报告)
├── start.py           # 跨平台智能启动脚本（Android 回环 / 桌面 0.0.0.0）
├── package_windows.py # Windows 绿色免安装便携版打包脚本
├── Dockerfile         # 容器化构建
├── docker-compose.yml # Compose 编排
└── requirements.txt   # Python 依赖清单
```

> 📖 逐目录 / 逐模块详情（含 js 模块清单、后端子包分层）见 [docs/agents/architecture.md](docs/agents/architecture.md)。

---

## 🗺️ 版本历史 (Version History)

最近 3 版的摘要见上方「多平台下载发布包」一节；**完整版本历史的正主是 [CHANGELOG.md](CHANGELOG.md)**（此处不再复制第二份）。

## ⚠️ 已知限制 (Known Limits)

- **Win10 需先装 WebView2 运行时**（Win11 自带）：缺运行时双击 `DeLector.exe` 会提示安装后退出，不会白屏。
- **冷启动的数字必须带「路径 × 冷/暖」两个标签**（同一个包能测出两个数，差 ≈0.67s）：**源码路径**（`python desktop.py`）暖 ≈ 5.4s / 冷 ≈ 6s；**便携产物**（你下载的 ZIP 里的 `DeLector.exe`）实测**冷 ≈ 8.5s / 暖 ≈ 6.9s**。其中约 2s 是「建服前的端口/身份校验」（防旧进程冒充新构建）——它是**新引入的显式校验，不是提速指标**；数据面已优化（文章列表 918ms → 8.9ms）。
- **`launch.log` 有已知的整行丢失**（Windows 上多个句柄并发追加同一文件，实测约 3% 的行整行消失、**不是半行**）：排查启动问题时若日志缺行，先按此排除；`tools/first_screen_from_log.py` 报退出码 3/5（缺锚行）**不必然**等于日志损坏。
- **Android 覆盖安装才生效**：含 `static/` 改动的版本必须覆盖安装（应用按 `versionCode` 判定重解包）。
- **Android 端「检查更新」暂未验证**：桌面端可用；Android 上两条假设（Chaquopy 能否完成到公网的 HTTPS、WebView 点外链是否交给系统浏览器）从未验证 ⇒ **手机上请以本页/Releases 的版本号为准**。
- **Android 装不回旧版**：`versionCode` 只升不降 ⇒ 装错版本只能卸载重装（会清应用私有数据，请先导出备份）。

---

## 📄 许可证 (License)

本项目采用 [MIT License](LICENSE) 开源许可证。欢迎提 PR 或 Issue 参与共建！
