# 首屏缓存优先 + 前端 store/契约收敛 Implementation Plan

> **Goal**: 按 ADR-0032 落地阶段一 + 阶段二的最小切片：先建立薄 store 与唯一前端数据入口（adapter），再把文章列表改成「缓存先渲染 → 真实请求 → 静默替换」。首帧不再等待 `/api/articles`，旧数据在屏时带 I1 形状/图标痕迹。
> **Tech Stack**: 原生 ES Modules（无 bundler）+ FastAPI 后端（本切片不改）；Node `--check` 语法门 + pytest 静态/契约守卫 + 浏览器实测。
> **Spec Reference**: `docs/adr/2026-11-09-adr-0032-python-off-first-screen-path.md`（§4.1 / §4.2 / §5）；`docs/adr/2026-11-09-adr-0031-python-import-migration.md`（已 Deprecated）。
> **Global Constraints**:
> - **顺序固定：先 store，后缓存**。缓存读写落点在 store，分两次做会返工。
> - 不引入框架、不加构建步骤（无 bundler）。
> - 不改后端 API 形状；`tests/test_articles_list_contract.py` 锁定的 5 键不得增删。
> - 「收敛」不是「重写」：保留现有渲染函数，只在数据源处插入 store。
> - 写操作一律不走缓存；旧数据在屏必须有 I1 形状/图标（不能只靠颜色）。
> - 不碰 `start.py` / `server.py` / Android 测量线；不占用模拟器；不碰 `D:/Code/DeLector-adr0031` 及其 `perf/adr-0031-plan-b` 分支。
> - 分支从 `origin/master` 开：`feat/first-screen-store-and-cache`；不 force push、不改历史。

---

## [NOTE] 目标架构（本切片结束时的形状）

```
UI (reader.js / cards.js / main.js ...)
        │  只订阅 / 只调用 action
        ▼
article-store.js  ── 唯一缓存读写点（localStorage + 内置快照）
        │
        ▼
client/adapter 层 ── 唯一知道后端存在的地方（路径/方法/载荷）
        ├── data-client.js  主站域：菜单/设置/订阅源/导入/卡片/测验/音频缓存/备份/备考
        └── rd-api.js       阅读器域：文章详情/句法/查词/生词卡等（本切片保留）
        │
        ▼
core.js api()    ── 唯一 fetch()
```

- **契约单一来源**：`static/js/api-types.js`。文章列表 5 键保持不变；只补注释与 store 状态类型。
- **扩展性判据**：client/adapter 层（`data-client.js` + `rd-api.js`）之外的模块不得 import `api`、不得拼 `/api/` 路径；将来换实现只换这一层。

---

## [NOTE] 不变量

| # | 不变量 | 怎么保证 |
|---|---|---|
| I1 | 旧数据在屏必须有形状/图标痕迹 | 同步 chip 同时含 `svg.ui-ico` 与文字；CSS 不用「仅颜色变化」表达状态 |
| I2 | 列表契约 5 键不变 | 复用 `tests/test_articles_list_contract.py`；快照写入前按同一键集校验 |
| I3 | 写操作不走缓存 | 缓存只由「成功的文章列表 GET」写入；删除/导入后走重新请求 |
| I4 | 首帧不被请求阻塞 | `loadArticles()` 先同步渲染缓存/内置快照，再发请求 |
| I5 | 首装也有内容 | 内置快照覆盖无 localStorage 的情况；内置行在同步完成前不可点 |
| I6 | 分层门不破 | `data-client.js` 进入 L2 规格；零顶层 `let/var`；route parity 通过 |
| I7 | 新增 pytest 登记 CI 分片 | 如新增测试文件，同步 `tools/ci_shards.py` |

---

## Task 1（阶段二）：store 基座 + 契约类型

**Files**
- `static/js/article-store.js`（新增，薄 store + 缓存）
- `static/js/article-seed.js`（新增，内置静态快照；数据取自 `delector/core/db/content.py` 的 `PRESET_ARTICLES` 与 `delector/data/preset_processed.json`）
- `static/js/api-types.js`（补 `ArticleListStoreState` 类型注释；列表字段不变）

**Steps**
1. RED：新增 node 探针 `tools/article_store_probe.mjs`，断言：
   - 无缓存时首帧状态来自内置快照，且 `fromCache=true`；
   - `loadArticles()` 在 fetch resolve 前已产生一次带 items 的通知；
   - 成功后写回缓存；失败且已有旧数据时保留旧数据并给出错误；
   - 写操作不触发缓存写入。
2. GREEN：实现 `createStore` + `articleStore`：
   - `getState()` / `subscribe(fn)` / `loadArticles()`；
   - 状态：`{ items, status, fromCache, builtin, error, empty, updatedAt }`；
   - `status ∈ idle | loading | stale | ready | error`；
   - 缓存键 `delector.articles.snapshot.v1`，值为 `{ savedAt, items }`；
   - 读取时校验「数组 + 每项 5 键」，损坏则丢弃并回落内置快照。
3. REFACTOR：确认 store 不碰 DOM；缓存异常全部静默降级（本地存储不可用时退化为纯请求）。

**Acceptance**：探针全绿；`node --check` 通过；store 内无 `document` / `innerHTML` / `querySelector`。

---

## Task 2（阶段二）：adapter 收敛 + 分层门

**Files**
- `static/js/data-client.js`（新增，L2；主站域 34 个端点：main.js 13 + cards.js 21）
- `static/js/rd-api.js`（**保留**为阅读器域 adapter；文章列表取数仍经它，只是不再被 `reader.js` 直接调用）
- `static/js/reader.js`（`fetchArticles` / `removeArticle` 不再直接调用；列表与删除都走 `articleStore` action）
- `static/js/main.js`（菜单/设置/导入/订阅源共 13 处 `api()` 迁入 `data-client.js`）
- `static/js/cards.js`（卡片/测验/音频缓存/备份/备考共 21 处 `api()` 迁入 `data-client.js`）
- `tools/check_frontend_layers.py`（`LAYER_SPEC` 增加 `data-client.js`；`_norm_path` 去 query/hash）
- `tests/test_reader_api_split.py`（不修改：`rd-api.js` 端点集合不变）

**Steps**
1. RED：扩展 `test_frontend_layers` 的注入用例，断言 `data-client.js` 违规调用 DOM/localStorage/计时器会红；断言 `main.js`、`cards.js`、`reader.js` 不再直接 import `api`。
2. GREEN：
   - `data-client.js` 一函数一端点，原样返回 `api()` Promise；
   - `main.js` / `cards.js` 删除 `api` import，改用命名函数；
   - `reader.js` 不再直接触网：文章列表与删除改由 `articleStore` 经 `rd-api.js` 执行；
   - 动态路径（`/api/cards/{type}/{id}/...`）保持单端点函数；
   - `feed/items` 的 query 在 adapter 内拼接，门禁路径归一化去掉 query。
3. REFACTOR：删除不再使用的 import；不做 UI 逻辑改动。

**Acceptance**：`python tools/check_frontend_layers.py` 通过；`tests/test_frontend_layers.py`、`test_reader_api_split.py` 全绿；`main.js` / `cards.js` / `reader.js` 三文件中 `api(` 与 `fetch(` 计数为 0。

---

## Task 3（阶段一）：缓存优先首屏 + I1 同步痕迹

**Files**
- `static/js/reader.js`（`loadArticles` 改为订阅 store；保留原行模板）
- `src/css/02-home-views.css` + `static/style.css`（新增 `.article-sync-chip`）
- `static/js/article-store.js`（缓存读写 + 静默替换）

**Steps**
1. RED：探针断言「fetcher 永不 resolve 时，首帧仍渲染缓存/内置行，且 DOM 出现 `.article-sync-chip` 与 `svg.ui-ico`」。
2. GREEN：
   - `loadArticles()`：同步 `renderArticleState(store.getState())` → `store.loadArticles()`；
   - 订阅一次，状态变化只重绘列表容器，不清空已有行；
   - `status=stale` 显示同步 chip（图标 `#ui-ico-refresh-cw` + 文案「同步中」）；
   - `status=ready` chip 消失；`status=error` 且无数据时显示统一错误出口；
   - `ready && items.length===0` 显示统一空态（含原有示例句入口）；
   - 内置快照行在 `builtin=true` 时不可点（`aria-disabled`），同步后恢复。
3. REFACTOR：把「加载中 / 错误 / 空态 / 列表」收敛到单个 `renderArticleState`，删除页面内重复判断。

**Acceptance**：`node --check`；CSS 构建同步门通过；实测两条账分别记录（见 Task 4）。

---

## Task 4：验证与证据

**自动**
- `python tools/check_frontend_layers.py`
- `python tools/check_css_sync.py`（若存在）
- `python -m pytest tests/test_frontend_layers.py tests/test_reader_api_split.py tests/test_articles_list_contract.py -q`
- `node --check` 覆盖改动过的 JS
- 新增探针 `node tools/article_store_probe.mjs`

**实测（桌面浏览器，不占模拟器）**
- 在 `reader.js` 加两个 `performance.mark`：`articles-cache-first-paint`、`articles-data-ready`（只做记录，不改行为）。
- 场景 A：缓存命中（第二次导航）——记录 **缓存首帧**；
- 场景 B：`localStorage` 清空（首装）——记录 **内置快照首帧**；
- 场景 C：真实数据就绪——记录请求发出到替换完成；
- 每场景 ≥5 次，报中位数；两条账分开，不互相替代。

**交付报告**
- 改动文件清单；
- 收敛的 fetch 点清单（main.js / cards.js / reader.js / rd-api.js）；
- 两条账的实测数字与测量脚本/命令；
- 分支、worktree、临时产物清理状态。

---

## 冷启动实测补充（后端未就绪，2026-11-10）

> 目的：证明「后端还没起来时首帧已有内容，真实数据随后接管」，而不是在 warm server 下比较两个 mark。

**方法**

- 独立 gateway 提供静态壳（`static/`）并代理 `/api/*`；首个 `/api/articles` 挂起不返回，其余 API 在后端健康前返回 503。
- 页面先用内置快照或 `localStorage` 快照渲染；确认 `articles-cache-first-paint` 后才启动后端。
- 后端每次使用新的 `DELECTOR_DATA_DIR`（复制只读源库以通过迁移守卫），`uvicorn delector.server:app` 冷启；`/api/health` 通过后 gateway 转发挂起请求。
- Edge headless + CDP，5 次/场景；冷启零点 = Edge 进程启动。首帧/接管均读既有 `performance.mark`，不改产品代码。

**结果（ms，中位数（范围））**

| 场景 | 快照首帧 | 真实数据接管 | 后端健康耗时 |
|---|---|---|---|
| 首装/无缓存（内置快照） | 721（626–738） | 3320（3306–3460） | 2503（2489–2667） |
| 缓存命中 | 736（643–760） | 3350（3323–3492） | 2512（2496–2661） |

以导航起点为 0：首装 353 / 2959ms，缓存命中 356 / 2965ms。首帧 detail 均为 `builtin/fromCache=true, rows=4`；接管 detail 均为 `builtin/fromCache=false, rows=4`；首帧 chip 为「同步中」（`svg #ui-ico-refresh-cw` + `role=status`）。

**限制（如实记录）**

- 上表测的是 gateway 挂起首个 `/api/articles` 的路径（请求等到后端可用），不代表「首次请求被快速拒绝」。
- **口径修正（2026-11-10）**：上表零点为 Edge 进程启动；同轮「导航起点=0」为 353 / 2959ms。补就绪重试后曾报「首帧 85ms」，该数**作废**：它既是导航起点零点，又是在同一个 Edge 进程里连续 3 次导航取的（81/85 两次为暖渲染，首轮 347），不是冷启口径。
- **补重试后同口径复测（2026-11-10，快速拒绝路径，5 次）**：每轮新 Edge 进程 + 新 profile；后端未起时反代立即 503，首帧后冷启 uvicorn。
  - 零点=Edge 进程启动：快照首帧 **615ms（610–709）**，真实数据接管 **4161ms（3738–4310）**。
  - 零点=导航开始：快照首帧 **223ms（215–328）**，真实数据接管 **3767ms（3346–3930）**。
- 与旧口径对照：进程启动零点 721ms（626–738）→ 615ms（610–709），同量级；导航起点零点 353ms → 223ms，差异来自请求路径与 harness 抖动。**85ms 与 721ms 口径不同，不可比**，不得混进同一「快照首帧」栏。
- 快速拒绝 + 重试的接管（4.2s）比挂起等后端（3.3s）晚约 0.8s：挂起请求在后端健康时立即放行，重试要等下一个退避窗口。收益不是更早接管，而是不用刷新/切页。
- 持续失败场景（冷进程，1 次）：首帧 222ms（导航零点）；6898ms（进程零点）进「未连接，显示本地快照」+ 重试按钮，首帧 4 行仍在；点重试后 6ms 接管，navCount=1。
- 桌面实测（安卓侧见下节）。

### 安卓侧双账（2026-11-10）

**结论先说**：安卓上「快照首帧 vs 真实数据」的提前量只有 **24.5ms（22–39）**，不是桌面那种秒级收益；「首帧 600ms 级」的缓存收益在安卓**不成立，属桌面专属**。原因见下：页面在 Python 服务就绪后才加载，首个 `/api/articles` 直接 200。

**冷启条件**：`org.delector.app.emulator`，`Medium_Phone_API_37.0`（x86_64 模拟器，**非真机，真机未测，不可外推**）；每轮 `force-stop` + `pm clear`（清 WebView/SW/应用数据），`am start -W`；2 轮 × 3 次，0 弃跑。

| 零点 | 快照首帧 | 真实数据接管 | 提前量 |
|---|---|---|---|
| 进程启动（与 TTFD 同源） | **3234.5ms（3137–3442）** | **3258.5ms（3161–3467）** | 24.5ms（22–39） |
| 导航开始 | **469ms（452–515）** | **499.5ms（476–539）** | 24.5ms（22–39） |

- 6 次冷启的 `/api/articles` 资源条目均为 **1 条、status=200**，`navCount` 均为 1：安卓冷启路径**天然不会触发**「后端未就绪」重试，因为 `MainActivity` 在 `loadUrl` 前轮询 `/api/settings`（[MainActivity.java](file:///d:/Code/DeLector/android/app/src/main/java/org/delector/app/MainActivity.java#L530-L540)），页面加载时服务已就绪。重试在安卓是防御性兜底，不是冷启收益来源。
- **噪声下限**：导航零点首帧 run-to-run 极差 63ms；小于 63ms 的差异在本模拟器上不可分辨。
- 重试 / 耗尽验证（**CDP 拦截 `/api/articles` 的人为场景，非冷启证据**）：拦截解除后经 4 次请求自动接管，`navCount=1`（瞬态「重试中」chip 未在 1.2s 采样点捕获）；持续拦截超预算后在 6 次请求时落「未连接，显示本地快照」+「重试」按钮（首帧 4 行仍在），解除拦截后点按钮接管。

---

## [NOTE] 本轮不做

1. 阶段三（搬只读无 NLP 路径）——未触发 ADR-0032 §4.3 任一条件。
2. 后端 API 形状调整、`start.py` / `server.py` 改动。
3. 框架引入、bundler、Tauri/Electron。
4. 其余视图域（encounter / listen-lab / search 等）的 `api()` 收敛——按同一 adapter 模式后续切片，不在本计划内顺手改。
5. 方案 B 的顺序重排（另一条线，不碰其分支/worktree/模拟器）。
