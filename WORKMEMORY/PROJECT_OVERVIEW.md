# PROJECT_OVERVIEW — DeLector（60 秒 primer）

> 首次生成：2026-09-04（bootstrap 会话从 AGENTS.md / README / ADR-0005 提炼）。
> 维护约定：交接或重大里程碑后由当前 agent 就地更新，不追加副本；细节下沉 `WORKMEMORY/cold/digest-YYYY-MM.md`。

## 一句话定位

**DeLector** = 德语精读 + 歌德/德福备考 Web App。FastAPI + spaCy + SQLite 单文件后端，原生 JS ES Modules 单页前端，
`python start.py` → `http://localhost:8000`。
三种形态共用同一后端：桌面 Python / Windows 便携版（PyInstaller）/ Android（Chaquopy）。技术栈细节与跨端互锁见 `docs/agents/architecture.md`。

## 必读锚点（按需深入）

- `AGENTS.md`（项目根）：**纯路由入口**（~30 行）——只有 WORKMEMORY 约定与文档路由，勿往它回填内容。
- `docs/README.md`：**docs 目录约定的正主**（分层与归档规则）。架构在 `docs/agents/architecture.md`，安全 / 环境 / 工作惯例在 `docs/agents/ops.md`。
- `FEATURES.md`：产品特性全览。
- `CHANGELOG.md`：**版本历史正主**（每次发版追加条目）。
- `docs/plans/`：在途实施计划；已交付的进 `docs/plans/archive/`（含 `-ledger.md` 执行台账）。
- `docs/specs/`：设计稿（`<日期>-<主题>-design.md`）；`docs/adr/`：仓内 ADR 副本（正式件在 vault `08-Projects/DeLector/01-ADR/`）。
- `WORKMEMORY/archive/handoff_audit-fixes-a-b.md`：**最近一份交接包**（closed 2026-10-17，含 12 条风险与坑 + 2026-10-17 进展补充）—— 新 agent 接手先看它。
- `WORKMEMORY/cold/`：COLD 层月度蒸馏（**当前 `digest-2026-10.md`**，覆盖 2026-10-02~10-16；另有 `digest-2026-09.md`）；WARM 层 `archive/` 按 INDEX 主题索引按需加载；超限事件正文在 `notes/`。
- `.vault-exec-ledger.json`：/dfs-exec 任务台账。

## 当前状态

- **最新发布 v5.20.2（2026-11-01）** —— **自然段排版重塑 + CEFR 视力透视胶囊 + 句法抽屉实时联动同步与 CI 极限加速**。
  - 阅读排版：正文 `<p>` 彻底移除块级预埋节点，根除长文逐句碎行；五场域拓扑分析完全收敛至右侧抽屉。
  - 词阶降噪与透视胶囊：默认沉浸模式清零 A1/A2 实心背景，保留 C1 考点点缀，新增「沉浸/考点/热力」三档视力透视与 `localStorage` 记忆。
  - 句法联动同步修复：点击单词或切句自动同步句法拓扑，保持「🌳 句法」Tab 聚焦不强跳；伴读播放器切句时句法同步步进。
  - CI 极限加速：Windows 烟测耗时由 14.5m 降至 2.5m，167 个测试文件拆为 6 路并行矩阵，整条流水线在 1.5 ~ 2 分钟内收敛。
- **历史里程碑归档**：v5.20.1（Android 拖拽与 Apache 2.0）、v5.20.0（伴学 Agent 运行时）、v5.19.0 及更早版本演进详见 `CHANGELOG.md` 与 `WORKMEMORY/cold/digest-2026-10.md`。

## 红线速查（详情见 `docs/agents/architecture.md` / `ops.md`）

1. NLP 降级路径**静默**切到纯 Python 时语法标注会**给错**（不是精度低，是错）——改标注逻辑前看 `nlp_engine` 字段。
2. `app.mount("/", StaticFiles(...))` 必须是 `server.py` 最后一个路由，否则全 API 405。
3. Android 五项互锁（py3.10 / minSdk24 / spacy3.8.7 / CI spaCy pin / arm64-only）动一个查全部；`spacy.load("名称")` 在 Android 必炸，要用 `importlib.import_module(名称).load()`；`extractPackages` 三包缺一不可。
4. versionCode 编码 `major*10000+minor*100+patch`，有测试守卫；keystore 只从环境变量读，丢失即包名报废。
5. 发版先跑「版本面五件套」（sw.js / index.html / build.gradle / README / 本文件当前状态），`test_writer_mobile.py` 两条测试锁死；tag 必须打在含 bump 的 commit 上。
6. `?v=` 查询串已退役：缓存闸 = 服务端 `Cache-Control: no-cache` + 安卓 `static.version` 重解包。
7. 敏感设置与删除操作仅 127.0.0.1 可写（`_require_localhost`），局域网 403；新端点遵守该闸。
8. pre-commit 密钥扫描必须启用，禁 `--no-verify`。
9. import 期不得联网、不得抛异常（Android 启动卡死的历史根因）。
10. 切句只有 `syntax_tree.split_sentences_pure_python()` 一处实现，别造第二份。
11. 跨边界契约（前端 body ↔ 后端模型）必须行为探针验证，字符串存在断言是死测（2026-09-02 事故）。
12. 「上游 → 本地词表/精读生词」同步 MUST 只增 + 只补空 + 幂等，闸门按「能力」判定（MUST NOT 按历史来源标记）；补字段 MUST NOT 跨语义来源混用（生词原句 vs 官方例句）。详情见 `docs/agents/ops.md`「存量富字段回填规范」+ Coding Vault `01-Rules/STORED-DATA-BACKFILL`。
13. **探针 / 守卫的「锚点 + 括号配平」切片有两型静默失效**，形态都是**判据看着在跑、实际恒真**：① 锚点只到函数名 ⇒ 切片里没有函数体（`ia_dom_mount_probe` 曾有 4 条守卫如此死了很久，与任何重构无关）；② 用 `[^{]*`「吃掉参数表」的写法遇解构参数 `f({a}={})` 会停在参数的花括号上 ⇒ 同样切出无体片段（修好①后曾以为解决，实测仍死）。MUST 配平到 `)` 之后**要求下一个字符是 `{`**，任一步失败 MUST 具名报错、MUST NOT 返回短切片；注入式变异的锚点同理 MUST `assert == 1`。另两条同源纪律：静态层已红 MUST NOT 再跑 `node:vm`（空源撞出的 `ReferenceError` 会埋掉真实问题）；沙箱 MUST NOT 同时留手写桩与真实源码切片两个真相源。详情见 `docs/agents/architecture.md`「前端模块分层契约」。

## 开放待办（活项）

> 已接受 / 已推翻的历史裁决（ADR-0018~0021、登记项 1A~5A、红 master 事故、冷启动 2.0s 口径、性能路线 O0 结论等）已整体下沉至 [`cold/2026-10-12-settled-todos.md`](cold/2026-10-12-settled-todos.md)，此处只留活项。

1. **真实用户试用 + 宣传开闸门槛（2026-10-12 DECISION，`/dfs-grill` Track 1 收敛、不落 ADR）**：产品种草帖**延后**到四条门槛全绿 —— ① **≥5 份真实三问反馈**（入口已随 2026-10-12 批次落地：`.github/ISSUE_TEMPLATE/feedback.md` + README 下载表下直达链接；零门槛：不强制 `bug(scope):` 前缀、三道判断题、可选吐槽）② 新手「下载 → 打开 → 读到第一篇短文」连续无协助成功 ③ README 首屏含截图/GIF 与 Win10 WebView2 前置（见第 3 条）④ Android 真机点检通过（见第 2 条）。**内容先行不受限**：备考方法论 / 开发理念类帖子现在就能发；**产品演示类冻结至门槛绿**。宣传载体已定：**独立薄壳站点**（独立仓库 + 零构建纯静态 + `github.io`，版本运行时取 GitHub Releases API、不复述功能清单），域名后置。
2. **Android 真机点检**：凡含 `static/` 改动的版本需覆盖安装验证（清单见 `docs/agents/ops.md`）；同时验证 Android 更新 chip 的两条假设（Chaquopy 能否完成公网 HTTPS、WebView 点外链是否交系统浏览器）——即门槛④。**未验证前不得把「代码已合并」记成「双端已验证」**。
3. **README 首屏改造**（宣传线，门槛③已部分交付）：首屏已重构为「一句话价值 + 30 秒上手（普通用户双击运行 vs 开发者三步启动）」，待后续根据真实截图进一步美化。
4. **预置包 LLM gloss 富化**：阻塞于 `DEEPSEEK_API_KEY` 缺失；`import_encounter_pack` 按 `pack_id` 幂等**不更新**既有行。
5. **C 档 8 项（当前唯一待办入口）**：`docs/reviews/2026-10-16-open-items-backlog.md`。其中 **C1「裁判结论回灌（verifier-in-the-loop）」为无条件下一步**（ADR-0024 四条硬依赖：① ~~裁判 FP 先修完~~ 已确认基线完成 ② 回灌内容 MUST 过同一道适用性闸与双限截断 ③ 定三角一致性（循环裁判带 nlp / `writing_check` **不带** nlp / 回灌源）④ 阴性对照 MUST 在动产品之前先跑成基线）。⚠️ 回灌落地后，§4.3 实验的阈值与结论**只对"准入式裁判"有效** ⇒ 必须重跑或明确分域（ADR-0024 已登记资产折旧，不留给下一任发现）。
6. **递延项（未立项）**：tests `--strict`；`tools/vault-proactive-scan.py` 三条版本正则**已于 tests/test_app_version_source.py 补齐自动化守卫**；PWA 安装提示验证 / 192-512 PNG 图标；**桌面单实例与端口顺延已于 2026-10-22 交付**（见「当前状态」，勿再当待办）；发布链路 runbook（Publish 被跳过 / 孤儿 tag 的恢复路径：Vault v5.4.0 复盘 + **v5.1.1 孤儿 tag 在案**；`gh workflow run --ref <tag>` 理论可补发但**本仓未实证**，判据只能是 release 资产清单）。


## 工作方式

- 提交 Conventional Commits；禁止 `--no-verify`。
- 语义知识检索：`search_vault` MCP 或 `python d:\Obsidian\Coding\scripts\search-vault.py`。
- 会话事件按 `PROTOCOL.md` 记入本目录 `work.log`。
