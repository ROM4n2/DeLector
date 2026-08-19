# DeLector · 德语欧标沉浸精读与考点剖析工作台

<p align="center">
  <img src="https://img.shields.io/badge/Release-v3.5.0-blue?style=flat-square" alt="Release Version" />
  <img src="https://img.shields.io/badge/Python-3.10%20%7C%203.11-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python Version" />
  <img src="https://img.shields.io/badge/FastAPI-0.110+-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/spaCy-German%20NLP-09A3D5?style=flat-square&logo=spacy&logoColor=white" alt="spaCy" />
  <img src="https://img.shields.io/badge/CEFR-A1~C1%20Goethe-E63946?style=flat-square" alt="CEFR Ladder" />
  <img src="https://img.shields.io/badge/AI%20Model-deepseek--v4--flash-brightgreen?style=flat-square" alt="AI Model" />
  <img src="https://img.shields.io/badge/Tests-64%2F64%20Passed-2EA44F?style=flat-square" alt="Pytest" />
  <img src="https://img.shields.io/badge/License-MIT-gray?style=flat-square" alt="License" />
</p>

<p align="center">
  <b>专为德语学习者与歌德（A1–C1）/ 德福（TestDaF）/ DSH 备考打造的下一代学术级伴读与句法剖析系统。</b><br/>
  融合<b>德语经典拓扑五场域</b>、<b>AST 从句抽象语法树</b>、<b>556+ 不规则三态表</b>、<b>3D 拟真物理卡盒</b>与<b>SM-2 间隔复习</b>。
</p>

---

## 📦 快速下载发布包 (Downloads)

| 平台 | 版本 | 说明 | 下载通道 |
|---|---|---|---|
| 🪟 **Windows x64** | `v3.5.0` 绿色便携版 | 免安装 Python / 零环境依赖，解压双击 `DeLector.exe` 即可使用 | [下载 ZIP 包 (GitHub Releases)](https://github.com/ROM4n2/DeLector/releases/tag/v3.5.0) |
| 📱 **Android** | `v3.5.0` 独立单机版 | 内嵌 Python 运行时与 spaCy 离线模型（`de_core_news_sm`），单机独立运行；**仅支持 64 位 ARM（arm64-v8a）**，32 位机型与模拟器装不上 | [下载 APK 安装包 (GitHub Releases)](https://github.com/ROM4n2/DeLector/releases/tag/v3.5.0) |

---

## 🌟 核心特性 (Features)

### 🌳 1. 德语拓扑五场域与 AST 从句树句法引擎 (Topological Felder-Modell & Syntax Tree)
- **经典拓扑五场域色谱条**：精准切分 **前场 (VF)**、**左框 (LK)**、**中场 (MF)**、**右框 (RK)** 与 **后场 (NF)**，点击句末 `🌳 句法` 即可就地平滑展开。
- **5 大核心从句抽象语法树 (AST)**：自动识别并分类 **状语从句**（原因/让步/条件/时间/目的/结果）、**关系从句**（关系代词/介词+关系词）、**带 zu 不定式**（um/ohne/anstatt...zu）、**被动与虚拟式框形**及 **主句核心干**。
- **双向联动与一键制卡**：抽屉内点击从句节点即可触发正文脉冲光圈聚焦高亮，支持一键将从句规则公式保存至 Anki 语法卡。

### ⚡ 2. 深度德语形态学与词法引擎 (Morphology & Lexicon)
- **556+ 强变化动词三态表**：无论是动词变位词干（`ging`）还是过去分词（`genommen`），$O(1)$ 秒级反查原形、过去时、分词与助动词（`haben/ist`）。
- **复合词递归智能拆解**：自动拆解长复合名词并精准剥离 `-s-`, `-es-`, `-en-`, `-n-`, `-er-`, `-e-` 等连接词素。
- **框形可分动词双向高亮**：将跨句变位动词与句末前缀（如 `steigt ... ein`）双向绑定并同步微光高亮。

### 📰 3. 德语权威外刊 RSS 一键订阅 (Curated RSS Feeds)
- 一键解析并抓取 **Tagesschau**、**Deutsche Welle (DW)**、**Deutschlandfunk (DLF)**、**Der Spiegel**、**Die Zeit** 最新德语外刊与原声音频，正文自动去噪清洗入库。

### ⚙️ 4. 全局应用内设置面板 (In-App Settings & Connectivity Tester)
- **零代码 Key 配置**：在界面右上角或移动端导航点击 `⚙️ 设置` 即可直接填入 API Key；
- **现代大模型支持**：默认集成 **`deepseek-v4-flash`**（极速低延迟）与 `https://api.deepseek.com` 官方直连；
- **毫秒级连通性测试**：一键检测 API 连接状态与响应延迟。

### 🎴 5. 3D 物理拟真卡盒与 SuperMemo SM-2 排程 (3D Flashcard Deck & SM-2)
- **3D 拟真物理翻转**：空格键或点击卡片触发 `rotateY(180deg)` 3D 翻牌，支持左右飞牌手势；
- **SM-2 科学排程**：艾宾浩斯间隔复习，今日到期自动提醒，支持一键导出标准 Anki `.apkg` 牌组。

### ✍️ 6. 歌德完形填空 & 德福 C-Test 实战引擎 (Cloze & C-Test Engine)
- 提供 **语法考点完形**、**高频词汇完形** 与 **标准德福 C-Test** 三大实战模式，答案仅在服务端保留并防作弊智能判分。

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

| 领域 | 核心技术 | 说明 |
| :--- | :--- | :--- |
| **后端框架** | `FastAPI` + `Uvicorn` | 异步高性能 REST API |
| **自然语言处理** | `spaCy` (`de_core_news_md` / `sm`) | 本地高精德语分词、词性标注、形态分析与五场域句法依存 |
| **形态学引擎** | `linguistics.py` | 556+ 不规则动词三态表 + 复合词动态规划递归拆解 |
| **拓扑句法树** | `syntax_tree.py` | Vorfeld/LK/MF/RK/NF 五场域切分 + 5 大从句 AST 抽象语法树 |
| **持久化存储** | `SQLite 3` (`delector.db` + `progress.db`) | 核心文库与时序台账双库解耦存储 |
| **语音合成** | `Edge-TTS` (Microsoft Neural Voice) | 神经级纯正德语离线本地缓存与 Web Speech 回退 |
| **前端架构** | `ES Modules / Modern CSS / Vanilla JS` | 零 Node 构建依赖、模块化架构、原生 3D CSS 渲染 |
| **记忆同步** | `genanki` | 离线生成标准 `.apkg` 记忆库 |
| **自动化测试** | `pytest` + `httpx` | 64 单元与集成测试用例保障 (100% Green) |

---

## 📁 目录结构 (Project Layout)

```
DeLector/
├── android/                # Android 独立离线单机版工程 (Chaquopy + Gradle)
├── static/                 # 前端纯静态 ES 模块化资源 (Zero-Build ESM)
│   ├── index.html          # 单页应用骨架 (含 3D 卡盒、句法拓扑与台账)
│   ├── style.css           # 德式报刊风格与 3D 翻转样式 (90KB+)
│   └── js/                 # 7 大独立原生 ES 模块
│       ├── core.js         # API 请求与全局状态
│       ├── main.js         # 路由调度、设置弹窗与 RSS 订阅
│       ├── reader.js       # 文本渲染、五场域拓扑条与 AST 树抽屉
│       ├── cards.js        # 3D 卡牌翻转盒与 SM-2 算法
│       ├── folio.js        # Leporello 三折页台账与墨线图
│       ├── cloze.js        # 完形填空 & 德福 C-Test 考试
│       └── player.js       # 神经影子跟读与 TTS 播放器
├── .githooks/              # 提交前密钥扫描钩子 (pre-commit)
├── linguistics.py          # 556+ 不规则动词三态表与复合词拆解引擎
├── core_dict.py            # 歌德 A1-B2 离线核心词库 (0ms 查词)
├── syntax_tree.py          # 拓扑五场域与 AST 从句树句法引擎
├── server.py               # FastAPI 后端服务与核心 NLP/API 路由
├── start.py                # 跨平台智能启动脚本
├── package_windows.py      # Windows 绿色免安装便携版打包脚本
├── Dockerfile              # Docker 镜像构建文件
├── docker-compose.yml      # Docker Compose 编排文件
├── requirements.txt        # Python 依赖清单
├── test_server.py          # Pytest 自动化测试套件 (49 用例)
└── test_syntax_tree.py     # Pytest 句法引擎测试套件 (15 用例)
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
- [ ] **v3.6 (Next)**：智能介词搭配图谱 (Präpositionen-Matrix: 动词/形容词+固定介词格)
- [ ] **v3.7**：德语写作与长难句 AI 润色台 (Schreibwerkstatt)

---

## 📄 许可证 (License)

本项目采用 [MIT License](LICENSE) 开源许可证。欢迎提 PR 或 Issue 参与共建！
