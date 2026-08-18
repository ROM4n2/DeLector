# DeLector · 德语欧标沉浸精读与考点剖析工作台

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%20%7C%203.11-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python Version" />
  <img src="https://img.shields.io/badge/FastAPI-0.110+-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/spaCy-German%20NLP-09A3D5?style=flat-square&logo=spacy&logoColor=white" alt="spaCy" />
  <img src="https://img.shields.io/badge/CEFR-A1~C1%20Goethe-E63946?style=flat-square" alt="CEFR Ladder" />
  <img src="https://img.shields.io/badge/Edge%20Neural-TTS%20Voice-4A7C59?style=flat-square" alt="Edge TTS" />
  <img src="https://img.shields.io/badge/Anki-APKG%20Export-3A86FF?style=flat-square" alt="Anki Export" />
  <img src="https://img.shields.io/badge/Tests-20%2F20%20Passed-2EA44F?style=flat-square" alt="Pytest" />
  <img src="https://img.shields.io/badge/License-MIT-gray?style=flat-square" alt="License" />
</p>

<p align="center">
  <b>专为德语学习者与歌德 / 德福 / DSH 备考打造的下一代学术级精读与考点记忆系统。</b><br/>
  融合<b>古腾堡印刷社论排版</b>、<b>本地高精德语 NLP 句法分词</b>、<b>真实 3D 物理扑克卡盒</b>与<b>三折风琴学术台账</b>。
</p>

---

## 🌟 核心特性 (Features)

### 📰 1. 古腾堡学术报刊排版与欧标难度谱系 (Gutenberg Broadsheet Reader)
- **德国古典报刊视觉**：暖白纸张基底（`#faf8f5`）、`DM Serif Display` 铸字衬线大标题与严谨的版面网格，告别千篇一律的 AI 模板。
- **CEFR 欧标难度谱系分析**：自动统计全文字数、预估阅读耗时，并以彩色光谱条呈现 `A1` 到 `C1` 词汇梯度分布。
- **全阶梯样文库**：内置 A1~C1 歌德真题标准范文，支持开箱即读。
- **防 SSRF 网页安全抓取**：输入任意德语新闻或网页 URL，一键提取纯净正文并自动完成 NLP 分词剖析。

### 🔍 2. 本地高精德语 NLP 语法引擎 (spaCy German NLP Engine)
- **零外部 API 依赖**：基于本地 `de_core_news_md` 模型秒级处理长文。
- **词法全维解构**：悬停或点击任意单词，即时查看词形原型（Lemma）、词性（POS）、冠词性数格（Gender & Case）及中文释义。
- **7 大歌德核心语法框架高亮**：
  - 被动态（Passiv）
  - 第二虚拟式（Konjunktiv II）
  - 复杂从句连词（Nebensätze）
  - 分词作前置定语（Partizipialattribute）
  - 关系从句（Relativsätze）
  - 带 zu 不定式（Infinitiv mit zu）
  - 情态动词情态用法（Modalverben）

### 🎙️ 3. 神经原声伴读与跟读器 (Edge Neural TTS Shadowing Player)
- **微软 Edge Neural 神经语音**：内置德语纯正发音人（Katja 严谨沉稳 / Killian 纯正自然）。
- **专业影子跟读播放器**：支持 `0.5x ~ 1.5x` 语速微调、单句独立循环精听、上下句快捷切歌。
- **本地 MP3 智能去重缓存**：生成过的句子/单词离线秒播，兼顾极速响应与流量节省。

### 🎴 4. 真实 3D 物理翻牌盒与卡片库 (3D Tactile Poker Deck Stage)
- **真实 3D 物理翻牌**：正面看德语词汇与考点，按 **空格键（Space）** 或点击卡片触发 **`rotateY(180deg)` 3D 翻转**，平滑呈现背面中文释义、语法公式与长句例句。
- **叠层抽牌手感**：底层显露 3 层错落的底牌阴影，支持 `A / ←`（上一张）、`D / →`（下一张）飞牌切换及触屏/鼠标物理拖拽滑动。
- **双模式切换**：支持「🎴 3D 扑克牌盒」与「📑 全景目录索引」一键无缝切换。
- **科学掌握机制**：误触物理删除带 3 秒撤回 Toast；掌握卡片可一键「✓ 斩」并归档隔离至已掌握区。

### 📰 5. 三折风琴学术台账档案 (Leporello Folio Dossier)
- **告别垂直滚轮疲劳**：采用德式学术风琴折页（Leporello Folio）横向展开，一屏尽览：
  - **`SEITE 01 · 研读总纲`**：文豪德语每日格言 + 6 列一体化等宽特大数字指标栏（连续研读天数、词汇斩获量、语法考点、精读篇数、测验准确率、总研读学时）。
  - **`SEITE 02 · 轨迹与谱系`**：近 30 天卡片新增与掌握墨线折线图 + CEFR 欧标水平阶梯构成。
  - **`SEITE 03 · 印章与错题`**：集邮式学术成就印章（Philatelic Stamps）+ 重点易错词专项分析。

### ⚔ 6. 三大多维考验引擎与全量 Anki 导出
- **三大自测模式**：🎴 闪卡自测 · ✍️ 德语拼写默写 · 🎯 四选一词义快答。
- **智能错题权重队列**：优先轮询高频易错词，自测结束自动生成准确率分析与德语鼓励格言。
- **一键导出 Anki APKG**：无缝同步至移动端/桌面端 Anki，包含词性、例句、释义与音频。

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

## 🏗️ 技术栈架构 (Tech Stack)

| 领域 | 核心技术 | 说明 |
| :--- | :--- | :--- |
| **后端框架** | `FastAPI` + `Uvicorn` | 异步高性能 REST API |
| **自然语言处理** | `spaCy` (`de_core_news_md`) | 本地高精德语分词、词性标注、形态分析与句法依存 |
| **持久化存储** | `SQLite 3` (`delector.db` + `progress.db`) | 核心文库与时序台账双库解耦存储 |
| **语音合成** | `Edge-TTS` (Microsoft Neural Voice) | 神经级纯正德语离线本地缓存 |
| **前端架构** | `Vanilla HTML5 / Modern CSS / Vanilla JS` | 零 Node 构建依赖、轻量极速、原生 3D CSS 渲染 |
| **记忆同步** | `genanki` | 离线生成标准 `.apkg` 记忆库 |
| **自动化测试** | `pytest` + `httpx` | 20+ 单元与集成测试用例保障 |

---

## 📁 目录结构 (Project Layout)

```
DeLector/
├── docs/                   # 设计规范、发布日志与演进规划
│   ├── design-system.md    # Gutenberg Broadsheet 设计系统规范
│   └── release-v2.1.md     # v2.1 版本发布日志
├── static/                 # 前端纯静态资源 (Vanilla Web)
│   ├── index.html          # 单页应用骨架 (含 3D 卡盒与折页台账)
│   ├── style.css           # 德式报刊与 3D 翻转样式
│   └── app.js              # 交互路由、卡片引擎与台账渲染
├── server.py               # FastAPI 后端服务与核心 NLP/API 路由
├── start.py                # 跨平台智能启动脚本
├── start.bat               # Windows 一键启动脚本
├── Dockerfile              # Docker 镜像构建文件
├── docker-compose.yml      # Docker Compose 编排文件
├── requirements.txt        # Python 依赖清单
└── test_server.py          # Pytest 自动化测试套件
```

---

## 🗺️ 路线图 (Roadmap)

- [x] **v1.0**：德语文章分词、欧标高亮与词汇卡片库
- [x] **v2.0**：Gutenberg Broadsheet 学术社论设计系统重构与 Edge TTS 神经伴读
- [x] **v2.1**：3D 物理扑克卡盒、Leporello Folio 三折风琴学术台账、三大考验自测模式
- [ ] **v3.0 (In Progress)**：
  - [ ] 智能完形填空实战引擎 (Lückentext / C-Test)
  - [ ] SuperMemo SM-2 艾宾浩斯智能排程与今日到期分流
  - [ ] 长难句语法成分结构树 (Satzglieder / Syntax Tree) 可视化图解展示
  - [ ] 歌德官方 A1~C1 核心词书与主题词汇库
  - [ ] 原版 PDF / EPUB 德语电子书精读导入

---

## 📄 许可证 (License)

本项目采用 [MIT License](LICENSE) 开源许可证。欢迎提 PR 或 Issue 参与共建！
