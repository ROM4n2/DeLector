# ADR-0033 S1 测量切片：应用 origin 静态拦截 + 不等就绪导航

- **日期**：2026-11-10
- **状态**：已测；**已合入 master**（PR #331，merge `67a2924`）
- **上游**：ADR-0033(../adr/2026-11-10-adr-0033-python-out-of-first-screen-completely.md) §10 S1
- **基线**：ADR-0032 阶段一安卓侧（PR #330，merge `6d38ddf`）

---

## 1. 范围（严格限定）

1. `MainActivity` 增加 `shouldInterceptRequest`：只在 `http://127.0.0.1:8000/` 这个应用自身 origin 上，把
   `/`、`/index.html`、`/style.css`、`/js/*` 从 APK 的 `assets/static/` 直接返回；
   **`/api/*` 与其余请求一律不拦**，走真实网络。
2. 解除「等就绪再 `loadUrl`」的 gate：`onCreate` 里立刻加载 `http://127.0.0.1:8000/`，Python 在后台并行启动。
3. 不动的：后端、构建脚本、桌面、前端 JS/CSS、SW 注册、API 契约。

### 1.1 Service Worker 风险（动手前结论）

**结论：不会把旧资产钉死。** `static/sw.js` 的 fetch 是 **network-first**（`cache:"no-cache"`），只有网络失败才回落 Cache Storage；拦截层返回的是同源 200，SW 会当最新值覆盖旧缓存。`/sw.js` 本身不在拦截白名单，Python 未就绪时注册失败、旧 SW 继续 network-first，也不会遮蔽。拦截响应统一加 `Cache-Control: no-cache`；测量每次 `pm clear` 会清掉 SW 存储。若未来出现旧资产，再按版本串跳过（不在本切片）。

---

## 2. 实现（未提交）

| 文件 | 改动 |
| --- | --- |
| `android/app/src/main/java/org/delector/app/MainActivity.java` | 新增 `APP_PORT=8000` / `APP_ORIGIN`；新增 `maybeServeAppStatic()`（只认 `/`、`/index.html`、`/style.css`、`/js/*`，MIME 映射，`Cache-Control: no-cache`，缺失则返回 null 交给真实网络）；`onCreate` 立即 `loadUrl(APP_ORIGIN)`；`onPageCommitVisible` 在应用 origin 首帧（commit + 1 动画帧）撤 splash 并记 `content_frame`；就绪轮询在 `readyPort == 8000` 时不再导航（记 `skip_reload`），端口顺延才二次导航；超时分支同理不再重载 8000 |

不新增依赖、不改 `build.gradle`、不改同步脚本、不改前端。

---

## 3. 测量协议

- 设备：`Medium_Phone_API_37.0`（x86_64 模拟器）。**arm64 真机未覆盖**（`adb devices` 无真机）。
- 每次冷启：`am force-stop` → `pm clear`（清 WebView/SW/应用数据）→ `logcat -c` → `am start -W`。
- 每轮 5 次，共两轮（C / D）；另 A / B 两轮作试点，因**未采集 uvicorn 监听时点、接管零点无法对齐**而整轮弃用（数字仅用于确认重试曲线一致，不计入结论）。
- 安装后首次启动（TTFD 1574ms）作 warm-up 弃跑，理由：ART/dex 首次预热，与后续冷启不同分布。
- 零点：
  - **进程零点**：`Process.getStartElapsedRealtime()`（与 `TTFD_FIRST_ARTICLE_MS` 同源）。
  - **导航零点**：`StartupProbe.navZero()`（`loadUrl(APP_ORIGIN)` 时）。
- 指标：
  - **M1 首个内容帧** = `onPageCommitVisible(应用 origin)` + 1 动画帧（`content_frame`）。与 #330 壳页 M1（3 次 rAF）**仪器不同，不可比**。
  - **TTFD** = `StartupProbe` 的 `ttfd`（首条 `.article-row` 首次绘制，双 rAF 后回报）。
  - **接管** = 页面 `articles-data-ready` mark（相对 navigationStart）换算到进程零点；另报相对 uvicorn 监听时刻的延迟。
- 采集：logcat（`DeLectorProbe` / `DeLector` / `python.stderr` 的 `Uvicorn running on`）+ WebView CDP（`performance` marks、`/api/articles` resource 条目、`.article-row` 数量、同步 chip、重试按钮）。

---

## 4. 结果（官方两轮，各 5 次，0 弃跑）

### 4.1 逐轮

| 轮 | M1 进程零点 | M1 导航零点 | TTFD 进程零点 | TTFD 导航零点 | 接管 进程零点 | 接管 导航零点 | uvicorn 监听（进程零点） |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C（5 次） | 中位 **853ms**（833–967） | 中位 **375ms**（336–388） | 中位 **1105ms**（1068–1232） | 中位 **609ms**（571–647） | 中位 **4335ms**（4266–4406） | 中位 **3838ms**（3808–3851） | 中位 **2898ms**（2871–2936） |
| D（5 次） | 中位 **841ms**（803–861） | 中位 **361ms**（334–379） | 中位 **1062ms**（1053–1104） | 中位 **591ms**（558–617） | 中位 **4229ms**（4210–4284） | 中位 **3779ms**（3724–3780） | 中位 **2853ms**（2829–2863） |

### 4.2 合并（10 次）

| 指标 | 中位数 | 范围 | 极差 |
| --- | --- | --- | --- |
| M1（进程零点） | **835.5ms** | 803–967 | 164ms |
| M1（导航零点） | **350.5ms** | 334–388 | 54ms |
| TTFD（进程零点） | **1065ms** | 1053–1232 | **179ms** |
| TTFD（导航零点） | **588ms** | 558–647 | 89ms |
| 接管（进程零点） | **4238.5ms** | 4210–4406 | 196ms |
| 接管（导航零点） | **3769ms** | 3724–3851 | 127ms |
| 接管 − uvicorn 监听 | **1382.5ms** | 1368–1535 | 167ms |

**噪声下限**：本批 TTFD 进程零点 run-to-run 极差 **179ms**（导航零点 89ms、M1 导航零点 54ms）。小于 179ms 的差异在本次设备上不可分辨；本轮没有用「小于噪声下限」的差当作收益。

### 4.3 接管行为（决定性证据）

- 每次冷启 `/api/articles` 资源条目 **5 条**：首次在导航零点 ~432ms 发起、**4–29ms 内失败**（连接被拒），随后 4 次退避重试。
- 退避实测间隔（C-1，导航零点）：`432 → 688 → 1114 → 1920 → 3530`，间隔约 **256 / 426 / 806 / 1610ms**，与 200/400/800/1600 设计一致；最后一次 200，耗时 305ms，`articles-data-ready` = 3838ms。
- **`navCount == 1`**：Java 侧 `skip_reload` 每次 1 条、`loadurl` 后无第二条；无刷新、无切页。
- 接管后：`.article-row` = 4，同步 chip 为空，无重试按钮。

### 4.4 预算耗尽与手动重试（人为拦截，**非冷启证据**）

- 冷启后 CDP `Fetch.enable` 挂起 `/api/articles`，不 continue。
- **14s**：同步 chip = 「未连接，显示本地快照」+「重试」按钮；首帧 4 行仍在。
- 关闭拦截并点击重试：`articles-data-ready` = 16.0s，4 行仍在，无重新导航（marks 只有一条 cache-first-paint）。

### 4.5 白屏/露底核验

- 冷启连续 6 帧（设备 uptime 间隔约 0.33s）：系统启动图 → 原生 splash → 真实页，**未观察到空白/露底帧**。局限：采样间隔 ~0.33s，短于该间隔的闪帧无法排除。

### 4.6 解耦确认

导航在进程 ~450ms 开始，`python_start_begin` 在进程 ~950ms；页面先于 Python 启动，符合 S1 设计。

---

## 5. 判负核对

| 判负项 | 结论 |
| --- | --- |
| TTFD 改善不足 ADR 阈值（1000ms） | **未触发**：两轮中位数均低于通过线（基线 4301.5ms 为 #330 同零点同 bridge 的另一构建；本批两轮中位数 1105 / 1062ms）。按要求**不给出跨构建差值**。 |
| TTFD 劣化超过 50ms | **未触发**（两轮方向一致，无回退迹象） |
| 白屏/露底帧 | **未见**（6 帧采样，见 4.5 局限） |
| 接管需要用户干预（`navCount > 1` 或必须刷新） | **未触发**：5 次请求自动接管，`navCount == 1` |
| 预算耗尽 UI | **通过**（人为场景）：落「未连接，显示本地快照」+ 可点重试，首帧行仍在 |

**未闭合项（非本轮判负项）**：`接管 − uvicorn 监听` 中位 **1382.5ms**，高于 ADR 里写的候选通过线 1000ms，超出 382.5ms。原因可定位到退避序列末段：最后一次失败在导航 ~1920ms，下一次重试在 ~3530ms（1600ms 档），而 uvicorn 在 ~2870ms 已就绪，接管只能等这一档。**已在 S2 闭合**：就绪信号触发一次立即重试，同口径接管中位 80.5ms（见 `2026-11-10-adr-0033-s2-ready-signal-and-ab.md` 与 ADR-0033 §14.4）。

---

## 6. 未覆盖 / 不可比

- arm64 真机、低端机：未覆盖，不推断。
- 8000 被占用导致端口顺延：未构造；代码路径为二次导航（`loadurl`），该场景不计入 `navCount==1`。
- M1 与 #330 的壳页 M1（1361.5ms）**不可比**：一个是真实页 commit+1 帧，一个是壳页 3 次 rAF。
- 本批与 #330 的 TTFD 只做阈值判定，不给差值；不同零点不同栏，不取平均。
- 桌面：本切片未动、未测。

---

## 7. 回滚锚点

单文件回退 `MainActivity.java`（撤 `maybeServeAppStatic`、恢复 `loadShell()`/就绪后 `loadUrl` 的 gate），无数据迁移、无构建面变更。

## 8. 结论

- 安卓首屏内容从「等 Python 就绪后才有」变为「进程 ~1.0s 出现快照行」，TTFD 中位 **1065ms**；接管全自动且 `navCount == 1`。
- 待决策：退避末档导致的接管延迟（~1.38s after uvicorn）是否要在下一步优化；以及是否进入 S2（构建期快照单一来源）。
