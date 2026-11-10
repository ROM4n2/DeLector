# ADR-0033 B2 桌面生产基线测量（只测不改）

- **状态**：已完成（2026-11-10）——基线测出 ≥300ms；随后提交 A（快照持久化）与提交 B（提前加载）落地，同构建交替 A/B 判定通过（见 §13）
- **日期**：2026-11-10
- **关联 ADR**：[ADR-0033](../adr/2026-11-10-adr-0033-python-out-of-first-screen-completely.md)（§15 为正式记录）
- **关联计划**：[S1 静态拦截](2026-11-10-adr-0033-s1-static-intercept.md)、[S2 就绪信号与 A/B](2026-11-10-adr-0033-s2-ready-signal-and-ab.md)
- **本轮边界**：未改产品代码、未改桌面壳、未开 PR、未碰安卓；测量脚本只在 `%TEMP%`，测后删除

---

## 1. 要回答的问题

ADR-0033 把桌面 B2 设为条件阶段：生产桌面壳基线测出「页面提前加载」的剩余收益 **≥300ms** 才做，否则写「桌面由 ADR-0032 缓存层覆盖」。上一轮 615ms 是独立 gateway 条件，**不能当生产首帧**；安卓 2376ms 也不能直接套到桌面。本计划只做测量与判定。

## 2. 口径（先定后跑）

| 项 | 取法 | 分辨率 / 说明 |
| --- | --- | --- |
| 入口 | `.venv\Scripts\python.exe desktop.py` | `package_windows.py::DEFAULT_ENTRY = "desktop.py"`，即打包 `DeLector.exe` 的同一入口；`start.py` 是浏览器启动器，不是桌面壳入口。冻结 exe 未测。 |
| 零点 | OS 进程创建时刻（`GetProcessTimes` → FILETIME → Unix epoch ms） | 与 `desktop._ms_since_process_create` 同源；不用 harness 的 spawn 时刻。 |
| 终点（主） | 主文档 `first-contentful-paint`（`PerformancePaintTiming`，`startTime + timeOrigin`） | 浏览器记录的绘制时间戳，亚毫秒；不是窗口出现，也不是 `load_url` 返回。 |
| 终点（辅） | 首条 `.article-row` 的第二次 `requestAnimationFrame` 时刻 | ≤1 帧（≈16.7ms）；回调在绘制前，最多早 1 帧。 |
| 观测 | WebView2 CDP：`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=<port>` + `Page.addScriptToEvaluateOnNewDocument` 注入只读计时 | 仅测量期环境变量/注入；仓库零改动。 |
| 为什么不拿现成信号 | `loaded` 事件在 NavigationCompleted 后触发，早于 `/api/articles` 与行绘制；`launch.log` 只有秒级时间戳 | 二者都无法分辨 300ms，故不拿来冒充首帧。 |
| 样本 | 2 轮 × 5 次；每次新进程 + 全新 `DELECTOR_DATA_DIR`；跑完 `taskkill /T /F`；每次前确认 8000 空闲 | 10/10 有效，0 弃跑。 |

**不可测/边界声明**：B2 尚未实现，因此「页面提前加载」的真实路径**不能直接测**；本轮测生产壳现状（`await_ready` 后才 `load_url`），并用同一 run 内的「最早可承载文档时刻 E」构造反事实。反事实是**估算**，不是同构建 A/B。

## 3. 环境

- Win11 build 26200
- AMD Ryzen 9 8945HX（16C/32T）
- Python 3.11.8（`.venv`）
- pywebview 6.2.1
- WebView2 Runtime 157.0.4341.42（Chromium 157）
- 每次全新数据目录；8000 端口空闲；未使用代理

## 4. 逐样本原始数据（单位 ms，均为进程零点）

| 样本 | E（最早可承载文档） | 服务就绪 | 页面导航 | FCP | 首行 rAF | 导航→FCP | 导航→首行 | nav−E |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| r1-1 | 3372.1 | 5657.3 | 5684.4 | 6336.4 | 6516.0 | 652.0 | 831.6 | 2312.3 |
| r1-2 | 3382.2 | 5434.7 | 5552.3 | 6116.3 | 6429.9 | 564.0 | 877.6 | 2170.1 |
| r1-3 | 3363.9 | 5419.1 | 5560.6 | 6112.6 | 6398.3 | 552.0 | 837.7 | 2196.7 |
| r1-4 | 3311.7 | 5441.1 | 5591.5 | 6143.5 | 6446.1 | 552.0 | 854.6 | 2279.8 |
| r1-5 | 3358.2 | 5405.3 | 5505.0 | 6065.0 | 6463.3 | 560.0 | 958.3 | 2146.8 |
| r2-1 | 3396.0 | 5456.3 | 5605.1 | 6161.1 | 6475.2 | 556.0 | 870.1 | 2209.1 |
| r2-2 | 3375.9 | 5471.1 | 5542.5 | 6090.5 | 6462.0 | 548.0 | 919.5 | 2166.6 |
| r2-3 | 3371.0 | 5430.5 | 5587.8 | 6135.8 | 6406.5 | 548.0 | 818.7 | 2216.8 |
| r2-4 | 3285.1 | 5644.6 | 5656.8 | 6324.8 | 6541.7 | 668.0 | 884.9 | 2371.7 |
| r2-5 | 3349.8 | 5364.4 | 5477.6 | 6025.6 | 6413.4 | 548.0 | 935.8 | 2127.8 |

- 每样本首条行均为 **4 条 seed 行**（`.article-row--seed`）。
- 弃跑 0；未挑样本。

## 5. 统计

| 指标 | 中位 | 范围 | 极差 | 两轮中位 |
| --- | --- | --- | --- | --- |
| E | 3367.4 | 3285.1–3396.0 | 110.9 | 3363.9 / 3371.0 |
| 服务就绪 | 5437.9 | 5364.4–5657.3 | 292.9 | 5434.7 / 5456.3 |
| 页面导航 | 5574.2 | 5477.6–5684.4 | 206.8 | 5560.6 / 5587.8 |
| FCP | **6126.0** | 6025.6–6336.4 | 310.8 | 6116.3 / 6135.8 |
| 首条 `.article-row` | **6454.0** | 6398.3–6541.7 | 143.3 | 6446.1 / 6462.0 |
| 导航→FCP | 554.0 | 548–668 | 120.0 | — |
| 导航→首行 | 873.9 | 818.7–958.3 | 139.6 | — |
| **nav−E** | **2202.9** | 2127.8–2371.7 | 243.9 | 2196.7 / 2209.1 |

- 噪声下限（同条件极差）：首行 **143.3ms**（两轮 117.7 / 135.2）；FCP **310.8ms**（两轮 271.4 / 299.1）；判 300ms 时取 **300ms**。
- 两轮中位数差：首行 15.9ms、FCP 19.5ms，方向一致（无跨轮反向）。

## 6. 归因与排除

### 6.1 首帧是 seed 行，不是用户真实行

10 次首条行都是 4 条 `.article-row--seed`。原因：桌面 `webview.start` 未传 `private_mode`，pywebview 默认 `private_mode=True`，每次进程使用临时 WebView2 数据目录 ⇒ `localStorage` 不跨启动保留。ADR-0032 的「上次列表快照」在桌面实际退化为 4 篇内置预置。

附加 5 次诊断（不同批次，不并入统计）：`articles-cache-first-paint` / `articles-data-ready` 中位 **6232 / 6253ms**，与 seed 首行几乎同刻（差 ≤10ms）。因为现状页面在服务就绪后才加载，API 很快返回；seed 行与真实行在这批里无法拉开。

### 6.2 试跑离群（不纳入统计）

本轮第一次（仪器验证跑、长时间空闲后首个进程）：FCP **8393.6ms** / 首行 **8389.4ms**，比正式批中位高约 2.5s；冷 OS 文件缓存 + 首启 WebView2。按「协议定稿前 + 非同一批」单列；不当中位数，也不据此判负。

### 6.3 暖数据目录诊断（不纳入统计）

复用已初始化数据目录：ready **5137.0ms**、首行 **5978.8ms**、nav−E **1889.5ms**。说明 ~5s 的 ready 主要来自 **WebView2 启动与 import 并发**，不是 DB 初始化；fresh/warm 结论同向。

## 7. 反事实与收益估算

设 E = 最早可承载文档时刻，nav = 现状页面导航起点，R = 导航 → 首行。若 B2 让页面在 E 时刻开始加载且页段 R 不变：

```
收益 = 现状首行 − 估算首行 = (nav + R) − (E + R) = nav − E
     = 2202.9ms（中位；范围 2127.8–2371.7）
```

- FCP 口径：估算 FCP = 3367.4 + 554.0 = **3921.4ms**，现状 6126.0ms ⇒ 收益 **2204.6ms**。
- 若并发 import 让页段膨胀 Δ，收益 = 2202.9 − Δ；300ms 门槛在 Δ < **1902.9ms**（页段 < 2776.8ms，约 3.2× 基线）时仍成立。Δ 本轮未测。
- 真实用户行：现状 `articles-data-ready` 中位 6253ms（诊断批）。B2 下需桌面就绪钩子，估算接管 ≈ 5437.9 + API 往返（未测，按本机量级 <200ms）≈ **5.5–5.7s**，收益约 **0.6–0.8s**；不加钩子时退避可能推到 ~6.8s 以上，收益可能归零或为负。
- **首内容帧收益（≈2.2s）≠ 真实数据收益（≈0.7s 估算）**。
- 本估算来自桌面自身配对测量，**未套用安卓 2376ms**；数值接近是巧合。

## 8. 判定

**≥300ms → 建议做 B2。** 首内容帧剩余收益中位 **2202.9ms**（扣噪声后仍 ≥1900ms），远超 300ms。但 B2 的产品价值有两个前置条件：

1. **桌面快照持久化**：`private_mode=True` 使 `localStorage` 不跨启动；需改为持久化存储路径或提供非 localStorage 快照，否则返回用户首帧仍是预置 4 行。
2. **桌面就绪钩子**：`await_ready` 后触发一次 `retryIfWaiting()`（复用 S2 同一机制，不加第二套重试；不缩短退避）。没有它，真实行接管可能晚于现状。

## 9. B2 改动轮廓（只写轮廓，不实施）

1. **先修快照持久化**（前置）：`webview.start(..., private_mode=False)` + 稳定 `storage_path`（落在数据目录），保持端口/origin；或改为可持久化的非 localStorage 快照。用 3 次冷启验证「第二次启动能读到上次列表」。
2. **静态服务先起**：`_after_start` import `delector.server` 之前，用 stdlib 在同一端口起最小静态服务器，只服务白名单（`/`、`/style.css`、`/js/*`、`/manifest.json`、静态资源）；`/api/*` 不服务。
3. **页面早导航**：主窗口创建后立即 `load_url`（或 `create_window` 直接给 url），并立刻显示主窗口；splash 只作兜底/首帧前反馈。
4. **后端接管**：(a) 同一监听 socket 交给 uvicorn（`Server.run(sockets=[sock])`，保持 origin；验证 SSE/下载/大请求体）；或 (b) stdlib 反代 `/api/*` 到内部端口（简单但单点）。先 spike 定 (a)/(b)。
5. **就绪钩子**：`await_ready` 成功后调用现有 `retryIfWaiting()` 一次；退避序列不变，不新建 cycle，不动在途请求。
6. **同构建 A/B 门槛**：同 commit 两构建（旧/新），2 轮 × 5 次冷启、全新数据目录；首内容帧/首 seed 行/首真实行/ready 全记；首内容改善 ≥300ms 且首次交互（点词/分析/编辑）回退不触发 ADR §6 的 >50ms 且 >5%；若页段膨胀 Δ >1902.9ms，判负并回退。
7. **测试面**：静态白名单 MIME/缓存头；`/api/*` 不拦截；SW 与静态层不打架（沿用 S1 结论）；端口顺延（8000 被占）回落；单实例锁；退出收尸。

## 10. 未测项（如实）

- B2 未实现：2.2s 是反事实估算，不是同构建 A/B；页段在并发 import 下的膨胀 Δ 未测。
- 冻结 `DeLector.exe`（PyInstaller）未测；本轮只测源入口 `python desktop.py`。
- 静态服务器启动/HTTP 开销未测；反代/socket 交接、SSE、下载、大请求体未测。
- 8000 被占用后的端口顺延未构造（本轮每次确认 8000 空闲）。
- 低核 CPU、节能模式、机械盘、杀软扫描未测；本轮为 16C/32T。
- 首次点词/首次分析/首次编辑的回退账未测（ADR §6 要求；本轮只测打开首页）。
- 真实用户文章未测：fresh DB 只有 4 篇预置，seed 行与真实行同刻；返回用户的多行列表与快照命中未覆盖。
- macOS/Linux 桌面未测（ADR-0020 的 Windows 壳边界）。
- CDP 观测开销未做无观测对照；理论上只加调试端口与只读注入，且收益用 `nav − E` 配对口径时页段开销近似抵消。
- `loaded` 事件未作为终点；它与 FCP 的差值未单独标定。
- arm64/安卓与桌面 B2 无关，本轮不碰。

## 11. 复现方法（脚本已删除，仅留口径）

1. 每次创建全新数据目录，设置 `DELECTOR_DATA_DIR`。
2. 设置 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=<空闲端口>`。
3. `spawn .venv\Scripts\python.exe desktop.py`，用 `GetProcessTimes` 取 OS 进程创建时刻为零点。
4. 轮询 `http://127.0.0.1:<cdp>/json/list`，对 page target 连接 CDP；`Page.enable` + `Runtime.enable` + `Page.addScriptToEvaluateOnNewDocument` 注入只读脚本：
   - `PerformanceObserver({type:'paint', buffered:true})` 记 `first-contentful-paint`；
   - `MutationObserver` 等 `.article-row`，双 `requestAnimationFrame` 记首行；
   - `performance.timeOrigin` 记导航起点；
   - `PerformanceObserver({type:'mark', buffered:true})` 记 `articles-cache-first-paint` / `articles-data-ready`（诊断用）。
5. 同时轮询 `http://127.0.0.1:8000/api/health` 记服务就绪。
6. 取到首行后 `taskkill /PID <pid> /T /F`；确认 8000 释放后再跑下一次。
7. 统计：中位/范围/极差；配对 `nav − E`。

## 12. 变更与清理声明

- 仓库本轮**只有文档变更**（本计划、ADR-0033 §2.2/§9/§10/§11/§15、ADR INDEX、`WORKMEMORY/work.log`）。
- 未改产品代码、未改桌面壳、未开 PR、未合并、未碰安卓。
- `%TEMP%\del-b2` 下的测量脚本、数据目录与结果 JSON 已删除；8000/8002 已确认空闲；未残留 DeLector 进程。

## 13. 落地与同构建 A/B（2026-11-10 追加）

### 13.1 提交 A：快照持久化（前置修复）

- `desktop.py`：`webview.start(..., private_mode=False, storage_path=<DELECTOR_DATA_DIR>/webview)`；启动日志打印最终路径。
- 清理：删数据目录即一并删 `<data>/webview/EBWebView`；卸载/升级不动数据目录。
- 机械闸：`tests/test_desktop_window_lifecycle.py::test_webview_start_persists_storage_under_the_data_dir`。
- **独立验证**（同一构建、同一数据目录，连续冷启两次）：第 1 次 4 条 seed 行（`article-row--seed`，seed 4 / 真实 0）；第 2 次 4 条真实行（seed 0 / 真实 4，命中 `delector.articles.snapshot.v1`）；磁盘生成 `<data>\webview\EBWebView`。
- 老用户升级：首启仍无缓存（seed 4 行），第二次冷启起命中真实快照。

### 13.2 提交 B：提前加载

- 新增 `delector/core/early_static.py`（stdlib 静态层，同端口/origin，`/api/*` 503）。
- `early_static.hand_off()` 把**仍处于 listen 的 socket** 交给 `uvicorn.Server.run(sockets=[...])`；`server_lifecycle.serve_in_thread(server, sockets=None)` 新增可选参数（缺省行为不变）。
- `await_ready` 成功后调一次 `window.notifyServerReady()`；不再等就绪才导航。
- 修复前「stop → 重新 bind」有 ~1s ECONNREFUSED 空窗，导致 1/10 早加载样本页面 boot 中断；socket 交接后 25/25 样本正常出首条行。
- 测量开关 `DELECTOR_DESKTOP_EARLY_LOAD` 已从最终代码删除。

### 13.3 同构建交替 A/B（2 轮 × 5 对，逐样本交替，全新进程 + 全新数据目录）

| 指标 | A（等就绪） | B（提前加载） | B − A |
| --- | --- | --- | --- |
| FCP | 6231.9（6089.6–6404.0） | 4107.9（4079.2–4149.1） | **−2124.0** |
| 首条 seed 行 | 6483.9（6333.6–6567.2） | 4106.9（4082.2–4150.3） | −2377.0 |
| 首条真实行 | 6535.9（6487.6–6675.9） | 5949.1（5887.8–5988.1） | **−586.8** |
| health 首次 200 | 5530.8（5364.4–5717.4） | 5767.1（5733.4–5814.3） | +236.3 |
| 首次分析 | 347.9（249.5–436.2） | 34.6（32.6–37.3） | −313.3 |
| 首次点词 | 44.5（22.6–74.1） | 9.4（8.7–12.4） | −35.1 |
| 首次编辑 | 61.8（59.6–78.8） | 62.3（60.8–69.3） | +0.5 |

- 两轮方向一致（R1 FCP 6189.7→4111.0、真实行 6537.8→5957.4；R2 6274.2→4104.9、6520.2→5942.0）。
- 噪声下限（同条件极差）：FCP A 314.4 / B 69.9；真实行 A 188.3 / B 100.3；首次编辑 A 19.2 / B 8.5。
- 四项判负均未触发：FCP 改善 2124ms；交互最大回退 +0.5ms/0.8%；25/25 无白屏；真实行提前 587ms。**判定通过。**
- 未测：冻结 exe、低核 CPU、节能、机械盘、杀软、8000 顺延、macOS/Linux；交接窗口内 SSE/大下载未单独构造。
