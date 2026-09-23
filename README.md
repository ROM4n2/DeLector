# DeLector · 德语欧标沉浸精读与考点剖析工作台

<p align="center">
  <img src="https://img.shields.io/badge/Release-v5.11.0-blue?style=flat-square" alt="Release Version" />
  <img src="https://img.shields.io/badge/Python-3.10%20%7C%203.11-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python Version" />
  <img src="https://img.shields.io/badge/FastAPI-0.110+-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/spaCy-German%20NLP-09A3D5?style=flat-square&logo=spacy&logoColor=white" alt="spaCy" />
  <img src="https://img.shields.io/badge/CEFR-A1~C1%20Goethe-E63946?style=flat-square" alt="CEFR Ladder" />
  <img src="https://img.shields.io/badge/AI%20Model-deepseek-brightgreen?style=flat-square" alt="AI Model" />
  <img src="https://img.shields.io/badge/Tests-1109%2F1110%20Passed-2EA44F?style=flat-square" alt="Pytest" />
  <img src="https://img.shields.io/badge/License-MIT-gray?style=flat-square" alt="License" />
</p>

<p align="center">
  <b>专为德语学习者与歌德（A1–C1）/ 德福（TestDaF）/ DSH 备考打造的下一代学术级伴读与句法剖析系统。</b><br/>
  融合<b>歌德 A1 全真听说读写考场工坊</b>、<b>德语伴读宠物（Eule & 伙伴）</b>、<b>Atelier 落地页画册台账</b>、<b>拓扑五场域</b>、<b>AST 从句语法树</b>、<b>内联 IDE 写作工坊</b>与<b>FSRS 现代认知记忆排程</b>。
</p>

---

## 📦 多平台下载发布包 (Downloads)

> ✅ **v5.11.0 遇见区 i+1 补齐（内容放量 + 就近选材）（2026-09-23）**：预置分级短文 **4 → 7 篇**（A1×2/A2×2/B1×3，复用仓库既有分级语料）+ 每包**预计算** annotate 口径 `lemma_seq`；预置补装由空库守卫升级为**版本闸 + 只增 + 只补空**（存量设备零操作补装、旧行只补空 `lemma_seq`、不覆盖用户内容）；新增只读 `GET /api/encounter/texts/index`（零 spaCy、不挂本机闸）+ 遇见区列表**覆盖率分组排序与「👉 建议先读」推荐条**（索引失败完全降级回原列表、未背词显示引导）。硬不变量 I-1 = 索引词序列与 annotate 逐 token **全序列逐元素相等**（列表徽章覆盖率 ≡ 阅读页覆盖率）。测试基线 1109 passed + 1 skipped；Android 需覆盖安装生效（改动含 static）。
> ✅ **v5.10.0 A1 富结构收敛（FRAGMENTS 单源 + membership side-car）（2026-09-21）**：ADR-0015——成员清单 + 共享字段单源、字段级优先级、专有词进 FRAGMENTS、考纲 A1 露出 IPA；seed∩GOETHE 仅 ~391、同形异义按 id 带 ipa/ex、GOETHE plural 不入 5 元组后缀位。测试基线 1081 passed + 1 skipped；Android 需覆盖安装生效（改动含 static）。
> ✅ **v5.9.5 例句 / 搭配 / 语料 全文检索（2026-09-21）**：新增「🔍 检索」——内存扫描覆盖 词条 4762 + 例句 2722 + 介词搭配 691 + **语料全文**（文章/分级短文），四组结果；德语变音折叠（`schon↔schön`）+ **中文两字词子串**可命中；顶栏 + **移动 dock** 入口；高亮**先 `esc()` 再 `<mark>`**（XSS 安全）；**`truncated` 仅表语料 hard cap**，`limit` 每组限量由 `groups_total` 表达。**不做 FTS5**（Spike：中文分词硬伤 + Android 不确定 + 规模用不上）。测试基线 1071 passed + 1 skipped；Android 需覆盖安装生效（改动含 static）。
> ✅ **v5.9.4 精读生词（reader 档）富字段回填 + 原句优先（2026-09-20）**：reader 生词卡补 `ipa` + 例句 + `gender`/`plural`（服务端归一查表 + 不规则动词兜底，**命中才补、不编造**）；`de` 原句优先（保留生词原句，有原句时不补官方中文，避免文不对题）；前端同步升级为「只增 + 只补空」，进「生词」档即自愈。测试基线 993 passed + 1 skipped；Android 需覆盖安装生效（改动含 static）。
> 
> 📱 **Android 用户注意**：改动含 `static/` 的版本（如 v5.8.0 / v5.9.0）需**覆盖安装**才生效。
> 📜 完整版本历史见 [CHANGELOG.md](CHANGELOG.md)。

| 平台               | 版本                   | 说明                                                                                                                                                                                                                                                       | 下载通道                                                                                    |
| ------------------ | ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| 🪟 **Windows x64** | `v5.11.0` | 免安装 Python / 零环境依赖，解压双击 `DeLector.exe` 即可秒开                                                                                                                                                                        | [下载 ZIP 包 (GitHub Releases)](https://github.com/ROM4n2/DeLector/releases/tag/v5.11.0)     |
| 🍎 **macOS**       | `v5.11.0` | 解压运行 `start` 脚本，全自动启动服务与默认浏览器                                                                                                                                                                                   | [下载 TAR.GZ 包 (GitHub Releases)](https://github.com/ROM4n2/DeLector/releases/tag/v5.11.0)  |
| 🐧 **Linux x64**   | `v5.11.0` | 全发行版通用，解压运行 `start` 即可使用                                                                                                                                                                                             | [下载 TAR.GZ 包 (GitHub Releases)](https://github.com/ROM4n2/DeLector/releases/tag/v5.11.0)  |
| 📱 **Android**     | `v5.11.0` | 内嵌 Python 运行时与 spaCy 离线模型，单机独立运行；**支持 arm64-v8a**，CI 钉死签名 keystore 并验签（可覆盖升级）。（CI 自动构建 APK；**v4.9.0 新增背词台核心词模式（235 词 / 704 词一键切换）与导入按归一词头去重，老设备幂等回填、FSRS 进度零丢失。**） | [下载 APK 安装包 (GitHub Releases)](https://github.com/ROM4n2/DeLector/releases/tag/v5.11.0) |

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
| 架构决策记录（ADR） | Obsidian Vault `08-Projects/DeLector/01-ADR/` |

---

## 🌟 核心特性 (Features)

- **德语精读工作台**：CEFR 词阶热力图 + 0ms 歌德离线词库 + 荧光便签、AI 导读与打印级《精读指南》导出。
- **句法拓扑与 AST**：经典五场域（VF/LK/MF/RK/NF）色谱条切分 + 5 大从句抽象语法树 + 一键制 Anki 语法卡。
- **FSRS 卡盒与背词工作台**：3D 拟真翻牌 + FSRS 现代自适应排程（消解 Ease Hell）；A1/A2/B1 多档背词台（`VOKABELN`）与介词矩阵视图。
- **备考域 A1–B1**：歌德全真听说读写考场工坊（写作 / 听力 / 阅读 / 口语 / 词表）+ 德福 C-Test + 听力微训 / 长难句精读工坊。
- **遇见区分级阅读**：i+1 阅读桥 + 逐词注解 + 生词一键进卡，配套桌面→手机局域网 P2P 静默同步。
- **内联 IDE 写作工坊 & 伴读宠物**：行内实时语法诊断 + VSCode 级 Inlay Hints；Eule & 伙伴混合双模伴读。

> 完整功能清单见 [FEATURES.md](FEATURES.md)。

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
docker compose up -d --build             # 或 Docker 容器化一键部署
```

> 开发者首次启用提交前密钥扫描（每个克隆都要做一次）：`git config core.hooksPath .githooks`
>
> 📖 Windows 分支 / Docker 细节 / 环境变量 / 打包 / 安全守卫等完整说明见 [docs/agents/ops.md](docs/agents/ops.md)。

---

## 📁 目录结构 (Project Layout)

```
DeLector/
├── delector/          # 后端包：server.py(app 工厂) + core/(DB·安全) + nlp_engine/(spaCy·拓扑·AST) + routes/ + services/ + data/
├── static/            # 前端零构建 ES 模块（index.html + js/ 11 模块 + german/ 背词台 + css/ tokens）
├── android/           # Android 独立离线单机版工程 (Chaquopy + Gradle)
├── agent/             # Phase 2 Go Agent Runtime（CLI + DAG + 工具注册，预览通道）
├── tests/             # 60+ 测试模块 + 迁移哨兵（pytest）
├── docs/              # 文档：agents/(架构·运维) · specs/(设计) · plans/(实施计划)
├── start.py           # 跨平台智能启动脚本（Android 回环 / 桌面 0.0.0.0）
├── package_windows.py # Windows 绿色免安装便携版打包脚本
├── Dockerfile         # 容器化构建
├── docker-compose.yml # Compose 编排
└── requirements.txt   # Python 依赖清单
```

> 📖 逐目录 / 逐模块详情（含 js 模块清单、后端子包分层）见 [docs/agents/architecture.md](docs/agents/architecture.md)。

---

## 🗺️ 版本历史 (Version History)

- **v5.10.0（2026-09-21）**：A1 富结构收敛（ADR-0015）——FRAGMENTS 单源 + membership side-car；字段级优先级；考纲 A1 露出 IPA；同形异义按 id 带 ipa/ex。测试 1081 passed + 1 skipped。
- **v5.9.5（2026-09-21）**：例句/搭配/语料全文检索（内存扫描）——词条 4762 + 例句 2722 + 搭配 691 + 语料全文；变音折叠 + 中文子串；顶栏 + 移动 dock；高亮 esc 优先；性能守卫 21.7ms；truncated 语义拆分。测试 1071 passed + 1 skipped。
- **v5.9.4（2026-09-20）**：精读生词（reader 档）富字段回填——生词卡补 ipa + 例句 + gender/plural（服务端归一查表 + 不规则动词兜底，命中才补、不编造）；de 原句优先（保留生词原句，有原句时不补官方中文）；前端同步升级「只增 + 只补空」，进生词档即自愈。测试 993 passed + 1 skipped。
- **v5.9.3（2026-09-18）**：类型门禁全仓 `--strict` 清账（250→0，含 tools 108→0）+ CI 门禁双轨升级 + 工具链修复（vault-proactive-scan / check_security node_modules）。纯工程治理，无用户可见变更。测试 987 passed + 1 skipped。
> 📜 完整版本历史（含全部 70+ 版本）见 [CHANGELOG.md](CHANGELOG.md)。

---

## 📄 许可证 (License)

本项目采用 [MIT License](LICENSE) 开源许可证。欢迎提 PR 或 Issue 参与共建！
