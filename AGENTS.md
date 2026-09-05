# AGENTS.md — DeLector 项目 AI Agent 交接文档

> **每次开新 agent 对话时，第一步必须读这个文件。**
> 这是机器可读的项目快照，用于最短时间内重建完整 context。
> **本文件只承载入门与快照**（同 CLAUDE.md 定位）：架构与实现细节在 `docs/agents/architecture.md`，
> 安全守卫与本机环境在 `docs/agents/ops.md`，版本历史在 `README.md` Roadmap。
>
> 维护约定：本文件**只保留一份**内容。历史上曾出现整份文档被追加两遍、
> 后半段是过时副本的情况，新 agent 读到会拿到自相矛盾的项目认知。
> 更新时请就地修改，不要在文件末尾追加新版本。

## 共享工作记忆 (WORKMEMORY)

- 进入会话先读 `WORKMEMORY/INDEX.md` → `WORKMEMORY/PROJECT_OVERVIEW.md` → `work.log` 尾部 50 行；发现未闭合 WORK_START 先询问用户。
- 工作中：决策/踩坑/交接 MUST 以 ≤4KB 事件追加 `WORKMEMORY/work.log`（schema 见 `WORKMEMORY/PROTOCOL.md`）。
- 语义知识检索：调用 `search_vault` MCP 或 `python d:\Obsidian\Coding\scripts\search-vault.py "<关键词>"`；成熟知识沉淀走 `/vault-save`。

---

### 交接快照

> 更新时间：2026-09-05

| 项              | 值                                                                                                                                                                                                                                                                                                     |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 当前分支 / HEAD | `master`（tag `v5.3.0`：背词工作台 Editorial 全域重塑 ADR-0006 + Grammatik-Radar 精读语法雷达 ADR-0007 + A2 词汇全域贯通；其前 v5.2.0 = ADR-0005 备考域重布局 + exam catalog 目录化 + 成绩表泛化 exam_trials，v5.1.1 = M1-M5 审计修复 + M4 性能缓存，v5.1.0 = 局域网静默同步 Stage B WebRTC 自动化）。 |
| 测试            | **v5.3.0 全量 582 全绿**（2026-09-05 实测，基线 559 → 582 +23）；10/10 tools/\*.mjs 探针全绿（新增 ia_dom_mount_probe）。                                                                                                                                                                              |
| 桌面端          | 正常，`python start.py` → `http://localhost:8000`（敏感设置与删除操作仅回环可写，局域网返回 403）                                                                                                                                                                                                      |
| Android APK     | **v5.3.0** 版本号同步（versionName 5.3.0, versionCode 50300，CI 从 git tag 自动推导）；**APK 待打包，GitHub Releases 资产待补**。                                                                                                                                                                      |
| 对外发布        | 正式版 **v5.3.0**（背词工作台 Editorial 重塑 + Grammatik-Radar 语法雷达 + A2 词汇全域贯通）；v5.2.0 备考域重布局 + catalog 目录化；v5.1.1 bugfix 收口；v5.1.0 局域网静默同步 Stage B。                                                                                                                                                                                              |
| 未完成的事      | 见文末「已知问题 / 待办」                                                                                                                                                                                                                                                                              |

---

## 项目一句话定位

**DeLector** 是一个德语精读与歌德/德福备考辅助 Web App。
单文件后端（FastAPI + spaCy NLP + SQLite）+ 单页前端（原生 JS ES Modules），
本机以 `python start.py` 或 `start.bat` 启动，访问 `http://localhost:8000`。
详见产品特性全览清单：[`FEATURES.md`](FEATURES.md)。

三种运行形态共用同一份后端代码：**桌面 Python**、**Windows 绿色便携版**（PyInstaller）、
**Android 独立单机版**（Chaquopy 把 CPython 嵌进 APK）。

---

## 文档路由（按任务深入，本文件只留入门与快照）

| 需要什么 | 去哪 |
| --- | --- |
| 架构细节：技术栈 / NLP 降级 / Android 互锁 / DB schema / API 全览 / 前端拓扑 / LAN 同步 / FSRS / 完形 / 切句 | `docs/agents/architecture.md` |
| 安全与提交守卫 / 本机开发环境 / Git 推送通道 | `docs/agents/ops.md` |
| 版本历史与发布记录 | `README.md` Roadmap（changelog）+ git tag |
| 产品特性全览 | `FEATURES.md` |
| 设计文档 / 实施计划与台账 | `docs/specs/`、`docs/plans/` |
| 跨会话工作记忆 | `WORKMEMORY/`（INDEX → PROJECT_OVERVIEW → work.log） |

---

## 红线速查（每条详情见对应文档）

1. **NLP 降级是静默的**：改标注逻辑前先看 `nlp_engine` 字段——降级路径给出的语法标注是**错**的，不是精度低。
2. **`app.mount("/", StaticFiles(...))` 必须是 `server.py` 最后一个路由**，否则所有 API 返回 405。
3. **Android 五项互锁**（py3.10 / minSdk24 / spacy3.8.7 / CI spaCy pin / arm64-only）动一个查全部；
   `spacy.load("名称")` 在 Android 必炸，要用 `importlib.import_module(名称).load()`。
4. **versionCode = major*10000+minor*100+patch**；发版先跑「版本面五件套」（sw.js / index.html / build.gradle / README / AGENTS），
   由 `test_writer_mobile.py` 两条测试锁死；tag 必须打在含 bump 的 commit 上。
5. **`?v=` 查询串已退役**：缓存闸 = 服务端 `Cache-Control: no-cache` + 安卓 `static.version` 重解包。
6. **敏感设置与删除操作仅 127.0.0.1 可写**（`_require_localhost`），局域网 403；新端点遵守该闸。
7. **pre-commit 密钥扫描必须启用，禁 `--no-verify`**。
8. **import 期不得联网、不得抛异常**（Android 启动卡死的历史根因）。
9. **切句只有 `syntax_tree.split_sentences_pure_python()` 一处实现**，别造第二份。
10. **跨边界契约（前端 body ↔ 后端模型）必须行为探针验证**，字符串存在断言是死测（2026-09-02 事故）。

---

## Agent 工作惯例

1. **先验证再断言**：声称"已修复/已完成"前先跑验证并给出证据（复现脚本、测试输出、
   拆包核对）。本项目的失败模式大量是**静默降级**，"看代码觉得对"经常是错的。
2. **改 Android 相关代码前**：先读 `docs/agents/architecture.md` 的「Android 独立单机版」一节。那里每一条都有代价，
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
8. **每次 git 推送必须同步更新 README.md（MUST）**：发版/修复涉及版本号、特性、测试数、
   目录结构、路线图任一变化时，README 的对应落点要同一提交内更新到位（Release badge、
   下载表版本与 release 链接、Tests badge、核心特性节、技术栈测试数、目录结构 js 模块与
   测试文件清单、Roadmap 版本条目）。不要等发布后再补——README 是仓库门面，滞后会让
   用户/协作者看到与代码不一致的版本。
9. **大改动后**：更新本文件的「交接快照」「已知问题 / 待办」两节；发布类变更同步 README Roadmap changelog 与 `WORKMEMORY/PROJECT_OVERVIEW.md`。
10. **缓存问题**：**不要再用 `?v=X.X.X` 查询串给 CSS/JS 打版本号**（v4.4.5 已退役）。
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

## 已知问题 / 待办（仅开放项）

> 已完结事项的根因与教训沉淀在 `README.md` Roadmap（changelog）、git 历史与 Coding Vault；
> 本节只追踪未完成项。更新时间：2026-09-05

- [ ] **v5.3.0 打包资产**：Windows/macOS/Linux 便携包与 Android APK 待打包、GitHub Release 资产待补录
      （README 下载表已标注「源码版·打包中」）。
- [ ] **新功能候选**：多模态听力微训 或 语料长难句强化 立项（见 `WORKMEMORY/PROJECT_OVERVIEW.md`）。
---

_此文件由 agent 维护，人工可随时追加注释。请保持全文唯一，不要追加重复副本。_
