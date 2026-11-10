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
- `WORKMEMORY/cold/`：COLD 层月度蒸馏（**当前 `digest-2026-11.md`**，覆盖 2026-10-31~11-08 / v5.20.0~v5.22.0；历史另有 `digest-2026-10.md`（10 月全月）、`digest-2026-09.md`）；WARM 层 `archive/` 按 INDEX 主题索引按需加载；超限事件正文在 `notes/`。
- `.vault-exec-ledger.json`：/dfs-exec 任务台账。

## 当前状态

- **最新发布 v5.23.2（2026-11-10）** —— **修复 v5.23.1 的全平台白屏（前端模块图解析期崩溃）**。
  - 根因：`static/js/article-store.js` 同时用 `export const/function` 与底部 `export { ... }` 导出同一批符号 ⇒ `SyntaxError: Duplicate export`，`main.js` 整张图不执行，页面只剩静态骨架文字（Android 表现为「退出重进后只剩文字方框」）。
  - 修法：声明处去 `export`，公开面只在底部 `export { ... }` 列一次。
  - 新守卫：`tests/test_frontend_module_graph.py` 加「结构化重复导出检查」+「node 真 import 全部模块」，两条均做过变异自证。
  - 教训：`node --check`、桩模块探针、set 化导出收集三层都抓不到重复导出 —— 判据必须是「真链接整张图」。
- **上一版 v5.23.1（2026-11-10，不可用）** —— **阅读页「未就绪显示成加载错误」修复（Android 真机点验）**。
  - 体验层：文章详情不再在请求内同步等 spaCy 分词——有旧分词结果先返回并标 `processed_stale`，无旧结果且后台预热在加载时回 `503 nlp_loading` + `Retry-After`，前端显示「正在准备德语分词模型」并按有限退避重试；预算耗尽才降级为带「重试」按钮的常驻提示。快速切换文章不串台（占位标题在 `finally` 按令牌复原）。
  - 内部：`model_loader.get_nlp_readiness()` 零副作用探针；`/api/health` 两分支同挂 `nlp` 字段；快退只在 `prewarm_started` 为真时生效（否则保留 single-flight 同步迁移通道）。
  - 验证：本地全量 pytest 3036 passed / 3043 collected（1 failed 为本机 GBK 控制台解码问题，master 同样红，与 CI 无关）；`check_release_docs` / `check_index_html_sync` / `check_css_sync` 通过；ruff + 两档 mypy 零错；进入本版的 PR #340 全部 CI 检查通过。
  - **项目状态：2026-11-10 起阶段性暂停**，短期内不再推进。接手先读 [`handoff_2026-11-10-project-pause.md`](handoff_2026-11-10-project-pause.md)。
- **上一版 v5.23.0**：词卡写入幂等修复链收口 + Android 冷启动静态壳 + 桌面 B2 提前加载 + App 内已知限制。
- **历史里程碑归档**：v5.22.1（文章响应体去重 / Android TTFD 口径）、v5.22.0（视觉材质、桌宠 P1–P4、复习台账、存量重算 3.6.0）、v5.21.1（伴学 SSE 跨 chunk 分帧修复）、v5.21.0（伴学页面级能力与 HITL 闭环）、v5.20.2（阅读排版与 CEFR 透视）、v5.20.1（Android 拖拽与 Apache 2.0）、v5.20.0（伴学 Agent 运行时）、v5.19.0 及更早版本演进详见 `CHANGELOG.md` 与 `WORKMEMORY/cold/digest-2026-10.md`。

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
3. **README 首屏改造**（宣传线，**门槛③已交付，2026-11-03**）：首屏为「一句话价值 + 实拍双图 + 30 秒上手（普通用户双击运行 vs 开发者三步启动）」；真机截图已入库（`docs/images/readme-home-hero.jpg` 文稿库 hero、`readme-reader-b1.jpg` B1 沉浸阅读器：CEFR 光谱 + 考点高亮 + 影读播放条），存在性守卫 `test_readme_first_screen_images_exist` 红灯防裂图；Tests 徽章同步至 2962/2967（2026-11-08 v5.22.0 发布提交全量实测 2962 passed / 4 skipped / 1 xfailed，2967 collected）。WebView2 前置已在下载表注明。
4. **预置包 LLM gloss 富化**：阻塞于 `DEEPSEEK_API_KEY` 缺失；`import_encounter_pack` 按 `pack_id` 幂等**不更新**既有行。
5. **C 档已交付（2026-10-19 回填）**：`docs/reviews/2026-10-16-open-items-backlog.md` 的 C1~C9 均已交付（PR #143~#160，含 C9 终审与 mock 漂移闸 #150）；**C4 Android 真机点检仍暂缓**（见第 2 条，非交付缺口）。⚠️ ADR-0024 资产折旧：回灌（C1，PR #147，2026-10-17）已落地 ⇒ §4.3 实验（N=20 报告）的阈值与结论**只对"准入式裁判 + 无回灌"历史形态有效**。**已明确分域**（2026-11-03：`docs/reviews/2026-10-16-judge-gaming-control-experiment.md` 顶部适用域声明）；ADR-0024 D-2 四件工程前置**已于 2026-11-03 落地**（commit `c385ea7`：逐篇落盘+续跑 / temperature 钉定 / --real 连通预检 / 成本硬闸，均带测试）；重跑当前**仅阻塞于 `DEEPSEEK_API_KEY` 缺失**（未跑，重跑前报告仅作历史形态基线）。
6. **递延项（未立项）**：tests `--strict`；`tools/vault-proactive-scan.py` 三条版本正则**已于 tests/test_app_version_source.py 补齐自动化守卫**；PWA 安装提示验证 / 192-512 PNG 图标（**图标已于 2026-11-03 补齐**：`static/icon-192.png`、`static/icon-512.png` + manifest 位图条目 + 尺寸守卫测试；安装提示仍待真机验证）；**桌面单实例与端口顺延已于 2026-10-22 交付**（见「当前状态」，勿再当待办）；发布链路 runbook（Publish 被跳过 / 孤儿 tag 的恢复路径：Vault v5.4.0 复盘 + **v5.1.1 孤儿 tag 在案**；`gh workflow run --ref <tag>` 理论可补发但**本仓未实证**，判据只能是 release 资产清单）。


7. **项目阶段性暂停（2026-11-10）**：v5.23.0 发版后短期内不再推进。接手入口 = [`handoff_2026-11-10-project-pause.md`](handoff_2026-11-10-project-pause.md)（含已完成证据、下一步、风险与坑）。热层 `work.log` 53 事件 < 阈值 75，未轮转；COLD digest 已增补至 v5.23.0。

## 工作方式

- 提交 Conventional Commits；禁止 `--no-verify`。
- 语义知识检索：`search_vault` MCP 或 `python \"$WIKI_PATH/scripts/search-vault.py\"`。
- 会话事件按 `PROTOCOL.md` 记入本目录 `work.log`。
