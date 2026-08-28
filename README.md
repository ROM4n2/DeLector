# DeLector · 德语欧标沉浸精读与考点剖析工作台

<p align="center">
  <img src="https://img.shields.io/badge/Release-v4.6.5-blue?style=flat-square" alt="Release Version" />
  <img src="https://img.shields.io/badge/Python-3.10%20%7C%203.11-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python Version" />
  <img src="https://img.shields.io/badge/FastAPI-0.110+-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/spaCy-German%20NLP-09A3D5?style=flat-square&logo=spacy&logoColor=white" alt="spaCy" />
  <img src="https://img.shields.io/badge/CEFR-A1~C1%20Goethe-E63946?style=flat-square" alt="CEFR Ladder" />
  <img src="https://img.shields.io/badge/AI%20Model-deepseek--v4--flash-brightgreen?style=flat-square" alt="AI Model" />
  <img src="https://img.shields.io/badge/Tests-322%2F322%20Passed-2EA44F?style=flat-square" alt="Pytest" />
  <img src="https://img.shields.io/badge/License-MIT-gray?style=flat-square" alt="License" />
</p>

<p align="center">
  <b>专为德语学习者与歌德（A1–C1）/ 德福（TestDaF）/ DSH 备考打造的下一代学术级伴读与句法剖析系统。</b><br/>
  融合<b>德语伴读宠物（Eule & 伙伴）</b>、<b>Atelier 落地页画册台账</b>、<b>拓扑五场域</b>、<b>AST 从句语法树</b>、<b>内联 IDE 写作工坊</b>与<b>FSRS 现代认知记忆排程</b>。
</p>

---

## 📦 多平台下载发布包 (Downloads)

| 平台               | 版本                | 说明                                                                                                             | 下载通道                                                                                    |
| ------------------ | ------------------- | ---------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| 🪟 **Windows x64** | `v4.6.5` 绿色便携版 | 免安装 Python / 零环境依赖，解压双击 `DeLector.exe` 即可秒开                                                     | [下载 ZIP 包 (GitHub Releases)](https://github.com/ROM4n2/DeLector/releases/tag/v4.6.5)     |
| 🍎 **macOS**       | `v4.6.5` 免安装包   | 解压运行 `start` 脚本，全自动启动服务与默认浏览器                                                                | [下载 TAR.GZ 包 (GitHub Releases)](https://github.com/ROM4n2/DeLector/releases/tag/v4.6.5)  |
| 🐧 **Linux x64**   | `v4.6.5` 便携版     | 全发行版通用，解压运行 `start` 即可使用                                                                          | [下载 TAR.GZ 包 (GitHub Releases)](https://github.com/ROM4n2/DeLector/releases/tag/v4.6.5)  |
| 📱 **Android**     | `v4.6.5` 独立单机版 | 内嵌 Python 运行时与 spaCy 离线模型，单机独立运行；**支持 arm64-v8a**，CI 钉死签名 keystore 并验签（可覆盖升级） | [下载 APK 安装包 (GitHub Releases)](https://github.com/ROM4n2/DeLector/releases/tag/v4.6.5) |

---

## 🌟 核心特性 (Features)

### 🦉 1. 德语伴读宠物（Companion Mascot）「Eule & 伙伴」混合双模系统

- **4 大内置矢量角色 + 自定义 SVG 上传**：猫头鹰 Eule、学者猫 Katze、灵动狐 Fuchs、包豪斯机甲 Roboter，支持上传任意 $\le 64\text{KB}$ 自定义 SVG 矢量角色（内置严格 DOMParser XML 白名单消毒防 XSS）。
- **3 层离线/在线 TTS 发声**：原生离线发声桥接 + Edge Neural TTS 纯正德语母语发音，8s 防噪音冷却。
- **研读工坊与全局悬浮双挂载**：在台账首屏 Hero 嵌入研习大工坊，全局各处提供右下角轻量伴读气泡，在生词制卡、语法提炼、FSRS 间隔复习、完形填空 $\ge 80\%$ 与连续打卡时触发实时德语鼓励。

### 📊 2. Atelier 呼吸感落地页台账 (Continuous Exhibition Folio)

- **0.85:1.15 不对称 Hero 大展台**：融合德式名言箴言卡、6 核心 Ring Badges 环形指标大展盘与四角 `+` 定位标点。
- **双行反向 Wire Marquee 动态走字带**：硬件加速匀速滚动名家引文与实时战报脉冲，两端带纸面渐变羽化遮罩，悬停平滑暂停。
- **并排双面板紧凑罗盘**：A1–C1 掌握度阶梯矩阵、30 天墨线留存折线图、重点易错词汇攻坚账本与学术火漆印章展台。

### 🌳 3. 德语拓扑五场域与 AST 从句树句法引擎 (Topological Felder-Modell & Syntax Tree)

- **经典拓扑五场域色谱条**：精准切分 **前场 (VF)**、**左框 (LK)**、**中场 (MF)**、**右框 (RK)** 与 **后场 (NF)**，点击句末 `🌳 句法` 即可就地平滑展开。
- **5 大核心从句抽象语法树 (AST)**：自动识别并分类 **状语从句**（原因/让步/条件/时间/目的/结果）、**关系从句**（关系代词/介词+关系词）、**带 zu 不定式**（um/ohne/anstatt...zu）、**被动与虚拟式框形**及 **主句核心干**。
- **双向联动与一键制卡**：抽屉内点击从句节点即可触发正文脉冲光圈聚焦高亮，支持一键将从句规则公式保存至 Anki 语法卡。

### ⚡ 4. 深度德语形态学与词法引擎 (Morphology & Lexicon)

- **556+ 强变化动词三态表**：无论是动词变位词干（`ging`）还是过去分词（`genommen`），$O(1)$ 秒级反查原形、过去时、分词与助动词（`haben/ist`）。
- **复合词递归智能拆解**：自动拆解长复合名词并精准剥离 `-s-`, `-es-`, `-en-`, `-n-`, `-er-`, `-e-` 等连接词素。
- **框形可分动词双向高亮**：将跨句变位动词与句末前缀（如 `steigt ... ein`）双向绑定并同步微光高亮。
- **固定介词搭配（Präpositionen）**：动词/形容词 + 固定介词 + 支配的格，**552 词条 / 691 条搭配**（DeepSeek 批量生成 + 人工 seed 兜底），查词抽屉第四张卡片逐条展示并可直接存成词汇卡（`bestehen auf` 坚持 / `aus` 由…组成 / `in` 在于）。
- **Präpositionen-Matrix 介词矩阵视图 (v4.5.0)**：把同一份数据集**倒过来**按介词分组浏览（21 组，按搭配数降序）—— 想复习 `auf` 支配的全部搭配时不必逐词查。支持 Dat/Akk/Gen 过滤、即时子串搜索、CEFR 标签，逐条一键入 FSRS 卡盒；数据一次拉完后全本地过滤，切换零延迟。

### 📰 5. 德语外刊 RSS 一键订阅与文库管理 (Curated RSS & Library)

- 一键解析并抓取 **Tagesschau**、**Deutsche Welle (DW)**、**Deutschlandfunk (DLF)**、**Der Spiegel**、**Die Zeit** 最新德语外刊与原声音频，正文自动去噪清洗入库；支持文章一键安全删除与级联清理。

### ⚙️ 6. 全局应用内设置面板 (In-App Settings & Connectivity Tester)

- **零代码 Key 配置**：在界面右上角或移动端导航点击 `⚙️ 设置` 即可直接填入 API Key；
- **现代大模型支持**：默认集成 **`deepseek-v4-flash`**（极速低延迟）与 `https://api.deepseek.com` 官方直连；
- **毫秒级连通性测试**：一键检测 API 连接状态与响应延迟。

### 🎴 7. 3D 物理拟真卡盒与 FSRS 现代认知记忆排程 (3D Flashcard Deck & FSRS)

- **3D 拟真物理翻转**：空格键或点击卡片触发 `rotateY(180deg)` 3D 翻牌，支持左右飞牌手势；
- **FSRS 现代自适应排程**：基于 DSR 三维状态机科学排程，彻底消解「沉沦死锁 (Ease Hell)」，实时预计算 4 级下一轮间隔，支持一键导出标准 Anki `.apkg` 牌组。

### ✍️ 8. 歌德完形填空 & 德福 C-Test 实战引擎 (Cloze & C-Test Engine)

- 提供 **语法考点完形**、**高频词汇完形** 与 **标准德福 C-Test** 三大实战模式，答案仅在服务端保留并防作弊智能判分。

### 🖋️ 9. 德语内联 IDE 写作工坊 (Schreibwerkstatt)

- **行内 IDE 编辑器与实时规则诊断**：原生 `contenteditable` 零依赖，TreeWalker 字符偏移光标记忆，输入停顿 400ms 防抖实时重分析；本地规则引擎跑冠词/格位一致 + 介词支配格与动词固定搭配检测，行内彩色波浪线标出错误，**零误报准则**。
- **VSCode 级真实 Inline Inlay Hints**：介词支配格（如 `[Dat]` / `[Dat/Akk]`）与名词短语实际性数格（如 `[Neut·Dat]`）以 CSS `::before` 伪元素内联排版（DOM 无 text node），打字时光标与后续文本自然推开绝不遮挡，TreeWalker 提取纯净正文 0 字符污染，工具栏支持一键即时开关。
- **Problems 全篇问题清单面板 (v4.2.0)**：侧栏新增 VSCode 式问题面板，集中汇总全篇 `error`（高置信语法错误）与 `warning`（双格介词方向提醒）；按 severity 分组排列，点击任意问题即刻联动平滑滚动定位、高亮波浪线并呼出纠错建议。
- **悬浮气泡与一键替换修正**：鼠标悬停波浪线弹出诊断气泡；点击错误在侧栏查看成因详解与建议，支持「✨ 一键应用修正」直接替换编辑器内文本。
- **句子导航索引与 Anki 存卡**：侧栏句子列表点击平滑滚动并高亮闪烁目标句；一键将错误存成 Anki 语法卡 —— **你的错误变成你的复习卡**。
- **类 Git 完整版本快照管理**：支持手动保存快照与 AI 润色自动快照；提供**只读预览弹窗**（浏览历史不产生多余检查点）、单项快照删除与可逆恢复检查点（`恢复到版本 N 之前`）。
- **句子级 AI 润色审查**：DeepSeek 全文句子级 diff 改写，并排逐 hunk 审查采纳/拒绝。

---

### 📚 10. 德语背词工作台 (Vokabeltrainer, v4.6.0)

- **684 词独立背词台**：FSRS-6 排程 + 卡片复习 + 自测 + 学习统计 + 词库浏览，以 iframe 嵌入主应用（导航栏 `VOKABELN` / 移动端 `📚 背词`）。同源即共享 localStorage 与 `/api/`，零 CORS；同时与主应用的 CSS/JS/DOM 完全隔离。
- **攻克手机浏览器无声**：单文件 HTML 直接在 iOS/Android 上打开是**放不出声**的，两个根因叠在一起 —— `file://` 协议下 Web Speech 被禁，以及设备根本没装德语语音包。修法是把服务端 `GET /api/audio/tts`（edge-tts 神经语音）设为**最高优先级**音频源，设备本地 TTS 退成兜底，于是有网就一定有正宗德语发音。
- **进度纳入备份**：`wb.*` 学习进度键已并入 DeLector 的全量备份/还原链路，跨设备迁移不会静默丢掉背词进度。
- **类 Git 完整版本快照管理**：支持手动保存快照与 AI 润色自动快照；提供**只读预览弹窗**（浏览历史不产生多余检查点）、单项快照删除与可逆恢复检查点（`恢复到版本 N 之前`）。
- **句子级 AI 润色审查**：DeepSeek 全文句子级 diff 改写，并排逐 hunk 审查采纳/拒绝。

---

## 🚀 快速启动指南 (Quick Start)

### 方式一：本机 Python 运行（推荐）

#### 1. 克隆仓库

```bash
git clone https://github.com/your-username/DeLector.git
cd DeLector
```

#### 2. 安装依赖并下载德语 NLP 模型

```bash
pip install -r requirements.txt
python -m spacy download de_core_news_md
```

#### 3. 一键启动

```bash
# Windows
start.bat
# 或通用平台
python start.py
```

> 脚本将自动检测局域网 IP 与空闲端口，秒开默认浏览器访问 `http://localhost:8000`，同 Wi-Fi 局域网下的手机或平板亦可直接扫码/输入 IP 访问。

---

### 方式二：Docker 容器化一键部署

无需手动安装 Python 环境与 NLP 依赖：

```bash
docker compose up -d --build
```

容器启动后，直接在浏览器中打开 `http://localhost:8000` 即可使用。数据库与缓存将自动持久化至本地宿主机目录。

---

### 开发者：启用提交前密钥扫描（必做一次）

`core.hooksPath` 是本地配置，**不随 clone 生效**，每个克隆都要手动开一次：

```bash
git config core.hooksPath .githooks
```

启用后 [.githooks/pre-commit](.githooks/pre-commit) 会在每次提交前扫描暂存内容，拦下
OpenAI/AWS/GitHub/Google/Slack token、JWT 与私钥 PEM 块，以及 `.env`、`*.pem`、`*.secret`
这类文件名。占位符（`sk-xxx`、`test-key`）不会误报；确属误报时在该行加注释
`delector:allow-secret`，不要用 `git commit --no-verify` 整体跳过。

---

## 🏗️ 技术栈架构 (Tech Stack)

| 领域             | 核心技术                                   | 说明                                                                                |
| :--------------- | :----------------------------------------- | :---------------------------------------------------------------------------------- |
| **后端框架**     | `FastAPI` + `Uvicorn`                      | 异步高性能 REST API                                                                 |
| **自然语言处理** | `spaCy` (`de_core_news_md` / `sm`)         | 本地高精德语分词、词性标注、形态分析与五场域句法依存                                |
| **形态学引擎**   | `linguistics.py`                           | 556+ 不规则动词三态表 + 复合词动态规划递归拆解                                      |
| **拓扑句法树**   | `syntax_tree.py`                           | Vorfeld/LK/MF/RK/NF 五场域切分 + 5 大从句 AST 抽象语法树                            |
| **持久化存储**   | `SQLite 3` (`delector.db` + `progress.db`) | 核心文库与时序台账双库解耦存储                                                      |
| **语音合成**     | `Edge-TTS` (Microsoft Neural Voice)        | 神经级纯正德语离线本地缓存与 Web Speech 回退                                        |
| **前端架构**     | `ES Modules / Modern CSS / Vanilla JS`     | 零 Node 构建依赖、模块化架构、原生 3D CSS 渲染                                      |
| **记忆同步**     | `genanki`                                  | 离线生成标准 `.apkg` 记忆库                                                         |
| **自动化测试**   | `pytest` + `httpx`                         | **322** 单元与集成测试用例保障 (100% Green)，CI 覆盖 md 加载路径与 Android 构建验签 |

---

## 📁 目录结构 (Project Layout)

```
DeLector/
├── android/                # Android 独立离线单机版工程 (Chaquopy + Gradle)
├── static/                 # 前端纯静态 ES 模块化资源 (Zero-Build ESM)
│   ├── index.html          # 单页应用骨架 (含 3D 卡盒、句法拓扑与台账)
│   ├── german/             # 684 词背词工作台 (workbench.html，iframe 嵌入)
│   ├── style.css           # 德式报刊风格与 3D 翻转样式 (169KB)
│   └── js/                 # 9 大独立原生 ES 模块
│       ├── core.js         # API 请求与全局状态（含 XSS 防护 jsAttr）
│       ├── main.js         # 路由调度、设置弹窗与 RSS 订阅
│       ├── reader.js       # 文本渲染、五场域拓扑条与 AST 树抽屉
│       ├── cards.js        # 3D 卡牌翻转盒与 FSRS 自适应记忆排程算法
│       ├── folio.js        # Leporello 三折页台账与墨线图
│       ├── companion.js    # 伴读宠物状态机与自定义 SVG 角色工坊
│       ├── cloze.js        # 完形填空 & 德福 C-Test 考试
│       ├── player.js       # 神经影子跟读与 TTS 播放器
│       └── writer.js       # 写作润色台（行内标注 + Problems + 版本快照）
├── .githooks/              # 提交前密钥扫描钩子 (pre-commit，含编码 keystore)
├── linguistics.py          # 556+ 不规则动词三态表与复合词拆解引擎
├── core_dict.py            # 歌德 A1-B2 离线核心词库 (0ms 查词，4411 词)
├── core_dict_ext.py        # 3969 词库扩展（DeepSeek 批量生成中文释义，v4.4.8 起缺口 0）
├── prep_dict.py            # 固定介词搭配数据集 552 词 / 691 条（生成物，源在 tools/build_prep.py）
├── writing_rules.py        # 写作润色台本地规则引擎（冠词一致 + 介词格，零误报，含 Inlay Hints/Problems）
├── syntax_tree.py          # 拓扑五场域与 AST 从句树句法引擎
├── server.py               # FastAPI 后端服务与核心 NLP/API 路由（敏感设置仅回环可写）
├── start.py                # 跨平台智能启动脚本（Android 回环 / 桌面 0.0.0.0）
├── package_windows.py      # Windows 绿色免安装便携版打包脚本
├── Dockerfile              # Docker 镜像构建文件
├── docker-compose.yml      # Docker Compose 编排文件
├── requirements.txt        # Python 依赖清单（无新增运行时依赖）
├── tools/                  # 构建/生成工具（build_dict.py 词库 + build_prep.py 介词 + 缓存）
├── test_server.py          # 后端与安全/CI/备份/AI 回归 (169 用例)
├── test_writing_rules.py   # 写作规则引擎，含零误报反例 (31 用例)
├── test_writer_mobile.py   # 写作台移动端几何与触屏契约 (27 用例)
├── test_syntax_tree.py     # 拓扑五场域与 AST 从句树 (15 用例)
├── test_german_workbench.py # 背词工作台音频补丁与接入契约 (14 用例)
├── test_essay_diff.py      # 句子级 diff 引擎 (13 用例)
├── test_prep_matrix.py     # 介词矩阵纯函数/前端/端点 (12 用例)
├── test_dict_pipeline.py   # 词库生成流水线 (10 用例)
├── test_edge_tts_mini.py   # stdlib 版 TTS 兜底客户端 (10 用例)
├── test_core_dict_ext.py   # 词库扩展数据契约 (5 用例)
├── test_frontend_security.py # 前端 XSS 注入点棘轮 (4 用例)
├── test_start.py           # 启动器 Android/桌面绑定 (4 用例)
└── test_source_hygiene.py  # 源码卫生（重复键等）棘轮 (2 用例)
```

---

## 🗺️ 路线图 (Roadmap)

- [x] **v1.0**：德语文章分词、欧标高亮与词汇卡片库
- [x] **v2.0**：Gutenberg Broadsheet 学术社论设计系统重构与 Edge TTS 神经伴读
- [x] **v2.1**：3D 物理扑克卡盒、Leporello Folio 三折风琴学术台账、三大考验自测模式
- [x] **v3.0**：智能完形填空实战引擎 (Lückentext / C-Test) + SuperMemo SM-2 艾宾浩斯排程
- [x] **v3.2**：前端原生 ES Modules 模块化拆分 + 歌德 A1-B2 核心离线词库 (0ms 查词)
- [x] **v3.3**：权威德语外刊 RSS 一键订阅与正文提取 (Tagesschau, DW, DLF, Spiegel, Zeit)
- [x] **v3.4**：556+ 强变化三态表 + 复合词智能拆解 + 框形可分动词双向联动高亮
- [x] **v3.5**：德语拓扑五场域 (Felder-Modell) 与 5 大从句 AST 句法树引擎 + 全局设置面板 (deepseek-v4-flash)
- [x] **v3.7**：德语伴读宠物（Eule & 伙伴）+ 自定义 SVG 角色工坊 + 严格 DOMParser 递归消毒
- [x] **v3.8**：FSRS 现代自适应记忆排程器升级（DSR 三维认知模型，消除 Ease Hell，4 级下一轮间隔预计算）
- [x] **v3.9**：离线词库 443→4300 词（DeepSeek 批量生成中文释义）+ 查词链 lemma 优先 / 形态学接线 / 现在时反查 / UX 诚实显示
- [x] **v3.9.1**：安卓真机修复——TTS 无声（stdlib 版 Edge TTS 客户端 `edge_tts_mini`）、倍速按钮点不到（移动端三行布局）、单词抽屉白色遮挡（55vh + 阅读区全宽）
- [x] **v3.10**：固定介词搭配（Verben/Adjektive + Präposition + Kasus）——数据集 **531 词条 / 660 条搭配**（AI 批量生成 + 人工 seed 兜底），查词抽屉第四张卡片逐条展示并可直接存成词汇卡；**备份改全量真往返**，堵住三处静默丢数据（含 API Key 被吞）；**安卓签名迁移**——CI 钉死 keystore + keytool 验签闸（显式 v1 签名），versionCode 编码规则修正（`major*10000+minor*100+patch`，修 3.10.0 与 4.0.0 撞车）
- [x] **v3.11**：**德语写作润色台 (Schreibwerkstatt)**——本地规则引擎（spaCy 上冠词/格位一致 + 介词支配格，零误报准则），行内下划线 + 侧栏纠错，错误一键存 Anki 语法卡（你的错误变成你的复习卡），essays 作文草稿库，CEFR 词汇估测，显式 AI 润色全文按钮；「按介词浏览」的独立矩阵视图留待后续（数据集已就位，零成本增量）
- [x] **v3.12**：写作台 IDE 化：句子级 diff 引擎 + AI 润色逐 hunk 并排审查 + `essay_versions` 类 git 快照管理 + 侧栏诊断/历史双 Tab 联动
- [x] **v4.0**：内联 IDE 编辑器（contenteditable + TreeWalker 光标记忆 + 400ms 实时诊断 + 悬浮气泡 + 一键修正 + 句子导航）+ 版本管理完善（只读预览不产生检查点 + 单项删除）+ 动词固定介词优先
- [x] **v4.1.1**：VSCode 级真实 Inline Inlay Hints（CSS `::before` 伪元素无 text node + 随文本推开 + TreeWalker 纯净正文 0 污染）
- [x] **v4.2**：Problems 问题清单面板（severity 分级 + 双格介词 warning + 联动定位/高亮/修正）
- [x] **v4.3**：Android/移动端写作台适配（bottom-sheet、触屏纠错、Android 默认关闭 Inlay Hints）+ **安全加固**：存储型 XSS 全量修复（`jsAttr`）、SSRF 加固、TTS 长度闸
- [x] **v4.4**：**可靠性与安全收口**——敏感设置/备份仅回环可写（局域网 403）、pre-commit 编码 keystore 拦截、CI 真 Gradle 构建与验签闸、写作零误报加固、备份/AI 失败回归；测试 **230 全绿**，仅 14 条 linguistics 重复键既有告警；词库 110 词缺口盘点（30 缓存待合入，80 需 API，401 暂缓，不伪造）
- [x] **v4.4.5**：**安卓升级后前端不更新根治**——覆盖安装不清 `filesDir` 而解包逻辑见文件已存在即跳过，旧前端永不被覆盖、新增文件却照常拷入，设备停在「新旧混合」状态（此前只能卸载重装）；改为按 `versionCode` 比对标记文件决定是否整目录重解包，删除范围硬编码校验以确保用户学习数据不受影响。缓存闸移到服务端 `Cache-Control: no-cache`，退役从未真正生效的 `?v=` 查询串与 `sw.js` 死清单。**写作台三 Tab 交互统一**：整行点击 = 定位/预览，行内按钮 = 破坏性操作，结果落在编辑器时自动收起移动端面板；测试 **238 全绿**
- [x] **v4.4.6**：**修顶栏版本指示灯** + **移动端写作台面板位移/底部滚不到根治**——v4.4.5 漏 bump `index.html` 顶栏 `System · vX.Y.Z Online`，使修好的升级链路看起来像没生效（拆 APK 验证：包内 `sw.js`、`writer.js`、去掉 `?v=` 的 `index.html` 全是新的，只有那一句字面量是旧的），版本自洽测试纳入该标签；移动端 `.writer-sidebar` 用 `position: fixed` + `bottom` 锚点却只给 `max-height`、没 `top` 也没 `height`，高度跟内容走而盒子锚在底边只能向上长 —— 切 tab、填错误卡、清单从空变 N 条都把顶边挪到新位置（三个 Tab 都在跳，诊断分析跳得最狠），改用 `height: min(76vh, 680px)` 固定几何；内层三个列表（220/460/320px）原本各自开滚动区在 600px sheet 里几乎占满可见区域、吃掉外层滚动，统一 `max-height: none; overflow-y: visible` 归 sheet 一人管；`.writer-pane` 补 `flex-shrink: 0` 防父容器压扁。测试 **239 全绿**
- [x] **v4.4.7**：**桌面端侧栏几何收口 + 三行触屏按压反馈**——v4.4.6 移动端修复的同族另一半：`.writer-sidebar` 基规则 `position: sticky; top: 4.5rem` 在 `align-items: start` 的 grid 列里高度跟内容走，既无 `max-height` 也无 `overflow-y`，内容一长就整列溢出、底部永远滚不到；改为内部滚动 + tab 条吸顶。三种可点击行（错误卡/清单项/版本行）补 `:active` 按压反馈——触屏没有 hover，此前按下去毫无回馈。测试 **242 全绿**
- [x] **v4.4.8**：**离线词库补齐 + SSRF 闸判定修正**——① 两处「AI 始终不作答」其实**AI 每次都答了**：提示词要求反身动词 `wort` 不带 `sich`，匹配器却按 `lemma not in asked` 把返回值丢掉；单词请求会让模型「纠正」成词元（问 `zustände` 答 `Zustand`）而词库按表层形查，于是任何屈折形必然连丢 3 轮。改为把答案回映射到请求键：搭配 **531/660 → 552/691**（零 API 花费），词库尾缺口 **110 → 0**。刻意不做变音折叠——`drucken`/`drücken` 会互相领走搭配，**张冠李戴比漏检更糟**。② SSRF 闸拿**外层 IPv6 旗标**判定，而 IPv4-mapped/6to4/Teredo 的真实目的主机是**内嵌的 IPv4**：`2002:c0a8:0101::1` 外层 `is_global` 为真却路由到 `192.168.1.1`（旧写法一路放行），而 Teredo 落在 `2001::/23` 私有段清单里使开着隧道的 Windows 用户 URL 导入对所有站点全废。③ **首次打 tag 时 CI 红、Release 没发出去**：新加的那条断言在本机靠 `ipaddress` 私有段表一条粗粒度的 `2001::/23` 条目**顺手兜住**才绿，CI 的 Python 换成细粒度条目后 `2001:20::/28` 掉了出来 —— 同一个 3.11 大版本、判定相反。改法是自己钉住那些段，不是删断言。测试 **266 全绿**
- [x] **v4.4.9**：**按钮 token 体系补全 + 移动端 sheet 闭合态几何修正**——`.btn-xs` / `.btn-del` / `.btn-secondary` 三条规则**从未在 CSS 里定义过**而模板里到处在用，无声降级成裸 `.btn` 尺寸配色（删除类按钮和主按钮长得一样）；补齐并分出 `--danger` token。移动端 sheet 闭合几何 `bottom: 4.75rem` 抬起 76px 而位移只推走「自身高度 + 16px」，**差额 60px 的条带永远留在屏幕内**盖住底部 dock，改为 `bottom: 0` + `translateY(100%)` 与 reader drawer 同构。另加全仓库 dict 字面量重复键棘轮。测试 **280 全绿**
- [x] **v4.5.0**：**Präpositionen-Matrix 介词矩阵视图**——把 552 词 / 691 条搭配**倒过来**按介词分组（21 组，按搭配数降序），Dat/Akk/Gen 过滤 + 防抖子串搜索 + CEFR 标签 + 逐条一键入卡盒。分层上纯函数内核**不认识 CEFR**（会成循环导入），CEFR 注入与组排序留在服务端。⚠️ 本轮变异验证抓到**三条空转断言**：组内排序断言在数据本身有序时删掉 `sort` 也绿、payload 字段名在别处到处出现、端点测试两端读同一份缓存对象导致比较**恒真** —— 分别改为喂乱序输入 / 切进函数体逐字段断言 / 从数据集直接构造期望多重集。测试 **298 全绿**
- [x] **v4.6.0**：**德语背词工作台集成 + 手机端无声根治**——684 词单文件工作台（FSRS-6 / 卡片复习 / 自测 / 统计 / 词库）以 iframe 嵌入而非合并代码：同源共享 localStorage 与 `/api/`（零 CORS），同时与主应用 2449 行强耦合全局 JS 完全隔离。**移动端无声的两个根因**：`file://` 下 Web Speech 被协议禁掉 + 设备没装德语语音包；修法是新增 `GET /api/audio/tts`（服务端 edge-tts）并设为最高优先级音频源。⚠️ 两处 CSS 陷阱：`body` 的 `padding-bottom` **不在 `.view` 的 flex 高度链里**，fixed dock 会直接盖住填满视图的 iframe（移动端必须显式扣掉 nav + dock 高度）；裸 `#view-german { display: flex }`（特异性 1,0,0）会压过 `.view { display: none }`（0,1,0），显示规则**必须** `.active` 作用域。备份覆盖 `wb.*` 进度键。测试 **314 全绿**
- [x] **v4.6.1**：**背词台 TTS 修复：点一下不出声、再点一下读两遍**——两个独立成因叠在一起。① 入口清理在 `removeAttribute('src')` 之后多调了一次 `load()`，这会给 `<audio>` **排一个异步 error 事件**，它在当前同步块跑完后才派发，正好命中同一 tick 里刚装上的 `onerror` —— 首次点击被自己的清理判成失败而静默无声。② `_ttsAudio` 是两条链路共用的**全局单例**，per-attempt 的闭包标志管不住**上一次**尝试的回调：旧 timer 醒来会清掉新播放，旧 `onplaying` 又把新尝试判成已完成 —— 连点于是交叉干扰、重复出声；改为全局递增的 `_ttsAttemptId`，stale handler 自己认出该退出。**教训：共享媒体单例上，per-attempt 的闭包标志不足以做互斥，需要一个全局的 attempt 身份。** 测试 **316 全绿**
- [x] **v4.6.2**：**卡盒交互修复 + 伴读宠物 + 自测范围**——① 伴读宠物在背词台视图自动隐藏（不盖住设置按钮）；② 自测新增「复习不认识（评过 Again）」范围，`addWrong` 写入 `rv` 标记；③ 卡盒翻转 onclick 从容器移到正面，背面评分按钮加 `stopPropagation`，Android 3D 变换下不再误触翻转；④ `toggleDeckFlip` 加 200ms 防抖，阻断 Android 双击事件抖动导致的「翻了又翻回来」。测试 **316 全绿**

- [x] **v4.6.3**：**工作台导出 Android 修复 + 卡盒背面 swipe 拦截**——工作台用 `Blob + URL.createObjectURL + <a download>` 导出备份，但 Android WebView 的 DownloadListener 对 `blob:` URL **永不触发**（无报错，用户以为成功了）。改为走服务端下载通道：`download()` 先 POST 到 `/api/wb/backup/prepare` 换 token，再 `location.href` 到 `/api/wb/backup/download/{token}`（跟主应用备份同款机制），独立打开 HTML 时无 `/api/` 则走 blob 兜底。服务端新增 `/api/wb/backup/prepare` 和 `/api/wb/backup/download/{token}` 两个端点。② **卡盒背面评分按钮被 swipe 吞掉**：`attachDeckSwipeListener` 绑在整个卡片容器上，背面按钮的触摸也被捕获，手指轻抖就超 70px 阈值触发 `stepDeck`。改为 `deckFlipped` 时跳过 `onTouchMove` / `onTouchEnd`。测试 **316 全绿**
- [x] **v4.6.4**：**介词矩阵已入卡持久化**——新增 `prep_saved` 表（主键 `(lemma, praep, kasus)`）与 `GET/POST /api/prep/saved` 端点，前端 `_prepSavedKeys` 从服务端初始化（不再空 Set 起步），`savePrepCardFromMatrix` 成功后异步写入。备份/恢复带上该表。测试 **319 全绿**
- [x] **v4.6.5**：**局域网同步 6 位短码**——WebRTC P2P 同步的 SDP 传递从复制粘贴 2-3KB 文本改为 6 位短码：A 存 SDP 到服务端拿到 `K7M2X9` 大字码，B 输入取出 SDP，生成回执后同样拿到短码。`POST /api/wb/sync/store` + `GET /api/wb/sync/fetch/{code}`，内存缓存 5 分钟 TTL，一次性消费。测试 **322 全绿**

- [x] **`server.py` 拆分重构**（v4.6.4）：3053 行单文件拆为 `nlp.py`（NLP/CEFR/文本分析）、`database.py`（DB/CRUD/备份）、`security.py`（SSRF/URL 安全），`server.py` 保留路由骨架。依赖图无环，319 测试全绿。
- [x] **介词矩阵「已入卡」持久化**（v4.6.4）：新增 `prep_saved` 表 + `GET/POST /api/prep/saved`，前端 `_prepSavedKeys` 从服务端初始化，重进矩阵段按钮状态保持。
- [x] **局域网同步 6 位短码**（v4.6.5）：WebRTC P2P 同步的 SDP 传递从复制粘贴 2-3KB 改为 6 位短码中转（`POST /api/wb/sync/store` + `GET /api/wb/sync/fetch/{code}`），手机上只需输入 6 个字符。
- [ ] **真机累积验收 v4.4.6 → v4.6.5**：Java 层无法在本机编译（没装 Android SDK），运行时行为只能真机验收；计划一次装 v4.4.6 再覆盖安装最新版（中间不卸载），一并确认升级链路与这几轮的移动端修复。

---

## 📄 许可证 (License)

本项目采用 [MIT License](LICENSE) 开源许可证。欢迎提 PR 或 Issue 参与共建！
