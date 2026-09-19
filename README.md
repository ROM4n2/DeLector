# DeLector · 德语欧标沉浸精读与考点剖析工作台

<p align="center">
  <img src="https://img.shields.io/badge/Release-v5.9.3-blue?style=flat-square" alt="Release Version" />
  <img src="https://img.shields.io/badge/Python-3.10%20%7C%203.11-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python Version" />
  <img src="https://img.shields.io/badge/FastAPI-0.110+-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/spaCy-German%20NLP-09A3D5?style=flat-square&logo=spacy&logoColor=white" alt="spaCy" />
  <img src="https://img.shields.io/badge/CEFR-A1~C1%20Goethe-E63946?style=flat-square" alt="CEFR Ladder" />
  <img src="https://img.shields.io/badge/AI%20Model-deepseek-brightgreen?style=flat-square" alt="AI Model" />
  <img src="https://img.shields.io/badge/Tests-987%2F988%20Passed-2EA44F?style=flat-square" alt="Pytest" />
  <img src="https://img.shields.io/badge/License-MIT-gray?style=flat-square" alt="License" />
</p>

<p align="center">
  <b>专为德语学习者与歌德（A1–C1）/ 德福（TestDaF）/ DSH 备考打造的下一代学术级伴读与句法剖析系统。</b><br/>
  融合<b>歌德 A1 全真听说读写考场工坊</b>、<b>德语伴读宠物（Eule & 伙伴）</b>、<b>Atelier 落地页画册台账</b>、<b>拓扑五场域</b>、<b>AST 从句语法树</b>、<b>内联 IDE 写作工坊</b>与<b>FSRS 现代认知记忆排程</b>。
</p>

---

## 📦 多平台下载发布包 (Downloads)

> ✅ **v5.9.3 类型门禁全仓 `--strict` 清账 + CI 门禁升级 + 工具链修复（2026-09-18）**：mypy `--strict` 全仓 250→0（含 `tools/` 108→0），CI 门禁升级为双轨 strict（`delector`+`tools` strict、`tests` skip）；修 `vault-proactive-scan` 两缺陷 + `check_security` 排除 `node_modules`（消 WASM base64 误报）。**纯工程治理、无用户可见变更**；测试基线 987 passed + 1 skipped（本次无 `static/` 改动，桌面端即时生效）。
> ✅ **v5.9.2 A1 取数统一（ADR-0014）+ 词表富字段回填修复（2026-09-17）**：A1 首装改走服务端 API（API 优先 + 内联降级为 `file://` 离线 fallback + 本地缓存），输出契约 11→12 字段（+`letter`）；A2/B1 词库同步由 append-only 升级为「只增 + 只补空字段」，根治「只有部分词有例句」（进 A2/B1 档即自愈）；**A1 早退闸修复**——已以 `server` 落盘的设备每次启动重新合并 A1 富字段，修「anbieten/allein 等存量 A1 条目无例句无音标」。测试基线 987 passed + 1 skipped；Android 需覆盖安装生效（改动含 static）。
> ✅ **v5.9.1 词库等级标签补齐 + 入口文档瘦身（2026-09-16）**：工作台词库补 A1 等级标签 `a1`（此前只有 `core`，词库「全部标签」筛不出 A1）；修 `reader` 谓词的 `custom` 兜底（22 条补缺词误入精读生词档）；README 瘦身 433→131 行，版本历史迁出为 `CHANGELOG.md`。测试基线 973 passed + 1 skipped；Android 需覆盖安装生效（改动含 static）。
>
> 📱 **Android 用户注意**：改动含 `static/` 的版本（如 v5.8.0 / v5.9.0）需**覆盖安装**才生效。
> 📜 完整版本历史见 [CHANGELOG.md](CHANGELOG.md)。

| 平台               | 版本                   | 说明                                                                                                                                                                                                                                                       | 下载通道                                                                                    |
| ------------------ | ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| 🪟 **Windows x64** | `v5.9.3` | 免安装 Python / 零环境依赖，解压双击 `DeLector.exe` 即可秒开                                                                                                                                                                        | [下载 ZIP 包 (GitHub Releases)](https://github.com/ROM4n2/DeLector/releases/tag/v5.9.3)     |
| 🍎 **macOS**       | `v5.9.3` | 解压运行 `start` 脚本，全自动启动服务与默认浏览器                                                                                                                                                                                   | [下载 TAR.GZ 包 (GitHub Releases)](https://github.com/ROM4n2/DeLector/releases/tag/v5.9.3)  |
| 🐧 **Linux x64**   | `v5.9.3` | 全发行版通用，解压运行 `start` 即可使用                                                                                                                                                                                             | [下载 TAR.GZ 包 (GitHub Releases)](https://github.com/ROM4n2/DeLector/releases/tag/v5.9.3)  |
| 📱 **Android**     | `v5.9.3` | 内嵌 Python 运行时与 spaCy 离线模型，单机独立运行；**支持 arm64-v8a**，CI 钉死签名 keystore 并验签（可覆盖升级）。（CI 自动构建 APK；**v4.9.0 新增背词台核心词模式（235 词 / 704 词一键切换）与导入按归一词头去重，老设备幂等回填、FSRS 进度零丢失。**） | [下载 APK 安装包 (GitHub Releases)](https://github.com/ROM4n2/DeLector/releases/tag/v5.9.3) |

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

- **v5.9.3（2026-09-18）**：类型门禁全仓 `--strict` 清账（250→0，含 tools 108→0）+ CI 门禁双轨升级 + 工具链修复（vault-proactive-scan / check_security node_modules）。纯工程治理，无用户可见变更。测试 987 passed + 1 skipped。
- **v5.9.2（2026-09-17）**：A1 取数统一（ADR-0014：首装 API 化 + 内联降级为离线 fallback + 契约 11→12 字段 `+letter`）+ A2/B1 富字段回填（修「只有部分词有例句」）+ A1 早退闸修复（已 server 落盘设备每启动重新合并富字段，修存量 A1 裸条目无例句无音标）。测试 987 passed + 1 skipped。
- **v5.9.1（2026-09-16）**：词库等级标签补齐（A1 补 `a1`、修 `reader` 谓词 custom 兜底）+ 入口文档瘦身（README 433→131 行，版本历史迁出为 `CHANGELOG.md`）。测试 973 passed + 1 skipped。

> 📜 完整版本历史（含全部 70+ 版本）见 [CHANGELOG.md](CHANGELOG.md)。

---

## 📄 许可证 (License)

本项目采用 [MIT License](LICENSE) 开源许可证。欢迎提 PR 或 Issue 参与共建！
