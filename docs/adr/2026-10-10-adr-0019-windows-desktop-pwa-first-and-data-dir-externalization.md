# ADR-0019: Windows 桌面端 —— 不换壳、不做安装包，先零代码验证 PWA 并把数据目录救出来

> **正式件:** `08-Projects/DeLector/01-ADR/0019-windows-desktop-pwa-first-and-data-dir-externalization.md`（vault）。本文件是仓内副本，内容与正式件同源（机械重新生成，未手抄）。
> **决策者:** Haoyu Xi ｜ **产出方式:** `/dfs-grill` 双镜拷问（product-ux + sre-resilience + vault 梯子检索）+ 用户拍板（Q1-A / Q2-A / Q3-B）。
> **要点:** 不换壳、不做安装包；先用现成 PWA 零代码验证「独立窗口」；本轮真做的是把数据目录外置（唯一真会丢数据的项）。

- **状态**: Accepted（2026-10-10）
- **实施**: **待执行**。本 ADR 的第一动作是**零代码验证**（试用现成 PWA）+ **数据目录外置**（唯一真会丢数据的项）；**明确不做**原生窗口壳、安装器、开机自启、`--windowed`。
- **日期**: 2026-10-10
- **领域**: 桌面形态 / 打包分发 / 数据完整性 / 用户体验边界
- **决策者**: Haoyu Xi
- **上游**: **ADR-0017**（更新可见性：检查 + 提示，不做应用内安装）、**ADR-0018**（性能结论 O0；"换 HTTP 主体"永久否决；桌面首启 2.6s 其中 spaCy 模型加载占 58%）、DEV-RULES §2.4（四端打包同步守卫）
- **本 ADR 的定位**: 回答"要不要做个 Windows 桌面端"。结论是**要的"桌面感"几乎已经免费存在**，而真正该花钱的是**数据会在升级时消失** —— 后者与"桌面端"外观无关，却比外观重要得多。

---

## 1. Context

### 1.1 提案原文

> 重拾之前的想法，能不能做个 Windows 桌面端？

（更早的原话：*先暂缓安卓。做好标记，能不能实现 Windows 桌面端的封装成 desktop？什么技术栈来实现？*）

⇒ 两层诉求：① 形态上"像个桌面应用"；② 若需要，**用什么技术栈**。

### 1.2 现状（已核实，非推测）

- **Windows 便携版已经存在**：`package_windows.py` 用 `PyInstaller --onedir --console`，发布产物 `DeLector-v5.16.0-Windows-x64-Portable.zip` = **75MB**（Linux 118MB / macOS 57MB / Android 58MB）。
- **当前启动旅程**：解压 zip → 跑 `DeLector.exe` → **弹出黑色控制台** → `start.py` 自动 `webbrowser.open` 打开默认浏览器 `http://127.0.0.1:8000` → 用户在**浏览器标签页**里使用 → Ctrl+C / 关黑框停服务。
- **⭐ PWA 已具备（Ladder L1 命中）**：`static/manifest.json` 有 `"display": "standalone"` + 图标，`static/js/main.js:1138-1140` 已注册 `/sw.js`，`static/sw.js` 存在 ⇒ **"独立窗口 + 任务栏图标 + 无标签页"零代码即可获得**（Edge/Chrome「安装此站点为应用」）。
  ⚠️ 唯一不确定：图标是**内联 SVG**（`sizes: "192x192 512x512"`，type `image/svg+xml`），Chrome/Edge 通常要求 PNG 才给安装提示 ⇒ 若装不上，第一步就是补两个 PNG（极便宜）。
- **⭐ 数据落在程序目录里（真正的风险）**：`database.py:35` 桌面端 `DATA_DIR` 无 `DELECTOR_DATA_DIR` 兜底 ⇒ 数据落在解压目录（onedir 下在 `_internal` 一带）；`:36-40` 立即 `makedirs(.cache/audio)` 且 `except: pass` 静默吞异常。
- **⭐ 数据目录迁移闸对桌面场景永不触发**：`preflight_data_dir()` 的条件④（`database.py:107`）在桌面端**恒等**（`data_dir == repo_root`）⇒ 该闸**永远不会拦**"解压新版本覆盖旧目录 / 删掉旧目录"这条路径 ⇒ **学习记录全空且零提示**。
- `start.py:61-67`：`port = 8000` 硬编码，被占用则"复用已有服务"——**只探能否连上，不校验对方是不是 DeLector**。
- `start.py:43-48`：`get_bind_host()` 桌面端返回 `0.0.0.0`（**"同 Wi-Fi 手机/平板可访问"是有意特性**），且该面**无鉴权**。
- **没有**：安装器、开始菜单/桌面快捷方式、托盘、开机自启、**桌面端自动更新**（Android 侧 ADR-0017 有检查提示，桌面端无）。
- **用户画像**：作者本人是**唯一用户**；历史上常一天一版；Android 端已 ⏸ 暂缓；性能线（ADR-0018 D1）已闭环无待办。

### 1.3 证据表

| 证据 | 位置 | 强度 |
| --- | --- | --- |
| PWA 独立窗口已具备 | `static/manifest.json`（`display: standalone`）、`static/js/main.js:1138-1140`、`static/sw.js` | ✅ 可复跑验证（打开浏览器看有没有"安装"） |
| 数据在程序目录内 | `delector/core/database.py:35-40` | ✅ 已核实（含 `except: pass` 静默） |
| 迁移闸桌面端永不触发 | `delector/core/database.py:107`（条件④ 恒等） | ✅ 已核实 |
| 端口复用不校验身份 | `start.py:61-67` | ✅ 已核实 |
| LAN 无鉴权且是有意特性 | `start.py:43-48` | ✅ 已核实（注释明说） |
| 四端打包同步守卫（曾漏同步 → 白屏 APK） | `DELECTOR-DEV-RULES.md §2.4` | ⚠️ 教训型（新增打包位点有历史成本） |
| **提权安装器 + OWNER RIGHTS ACL 致普通权限全线失守**（另一项目 Hermes） | `08-Projects/Hermes/02-Post-mortem/POST-MORTEM-ELEVATED-INSTALLER-ACL-LOCKOUT.md` | ⚠️ 教训型（与本提议同构） |
| 性能结论 O0、换主体永久否决 | ADR-0018 §3.2 / §4 / §7.2 | ✅ 已定案 |
| "Go 二进制 + Python venv = ~50MB vs PyInstaller 300MB+" | `06-Sources/Articles/GO-PYTHON-HYBRID-ARCHITECTURE.md §5` | 参考（本仓实测便携版 zip 仅 75MB，未到 300MB） |

---

## 2. Decision Drivers

**用户与产品体验层**
- 真痛点 vs 伪需求：每天必现的摩擦才值得花钱（"必经浏览器标签页"＝高；"黑框"＝特性而非痛点；"无图标/自启"＝中低）。
- 沉浸式精读的定位：与"混在几十个标签页里、可能被误关"直接冲突。
- 唯一用户 + 一天一版 ⇒ 任何"每次都要重装"的方案都是负价值。

**技术与工程实现层**
- 数据完整性优先于外观：**唯一真会丢东西的路径必须先堵**。
- 失败模式可观测：任何"看不到日志/静默失败"的改动（如裸 `--windowed`）都不可接受。
- Ladder of Reuse：先用现成能力（PWA / 已有 flag），不轻易引入新依赖（webview）或新栈。
- 与既有 ADR 不冲突：不得触碰 ADR-0018 的"换 HTTP 主体永久否决"。

---

## 3. Considered Options

### 3.1 Option A：原生窗口壳（webview：pywebview / CEF / WebView2）—— ❌ 否决

- ✅ 真正的独立窗口、独立图标/任务栏身份、可有托盘。
- ❌ **会失去**：多标签对照、F12 DevTools（webview 需额外开远程调试）、浏览器扩展、复制 URL、多实例。
- ❌ **退出不保证 uvicorn 子进程收尸** ⇒ 下次 `start.py:63` 静默"复用已有服务"，**用户以为升级了其实跑的是昨天的进程**（静默失败且不提示版本）。
- ❌ 新增依赖 ⇒ 给四端同步守卫加**第 5 个打包位点**，而该守卫已因漏同步出过白屏事故；叠加 PyInstaller 被 Defender 误报的历史风险（被隔离即连数据库一起消失）。
- ❌ 冷启动叠加：服务 2.6s + webview 初始化与常驻内存。

### 3.2 Option B：只改分发与外壳（`--windowed` + 安装器 + 托盘 + 自启 + 单实例）—— ⚠️ 部分采纳（本轮只采纳"不动"之外的零碎，安装器/自启否决）

- **安装器 ❌ 否决**：DeLector 在 **import 期就写盘**（`database.py:35-40`）⇒ 装进 Program Files 会"管理员能跑、普通用户不能跑"且**静默失败**；卸载器还会连 `_internal` 一起删走数据 —— 与 Vault 里 Hermes 的提权安装器 ACL 事故**同构**。
- **开机自启 ❌ 否决且有反作用**：沉浸阅读是主动进入的场景；且桌面端绑 `0.0.0.0` 无鉴权 ⇒ 常驻 = 长期暴露面。
- **`--windowed` ⏸ 延后**：它依赖打包改造，且**裸切可否决** —— 隐藏后 UVicorn traceback / 端口占用提示 / 模型缺失全部消失，用户视角是"双击无反应"。必须先配齐可观测三件套（见 §6.3）。
- **单实例/端口顺延** 📌 登记（见 §6.4），不在本轮。

### 3.3 Option C：换栈重写（Tauri / Electron + Rust/Go 主体）—— ❌ 否决

- ❌ 直接违反 **ADR-0018 §3.2「换 HTTP 主体永久否决」**（三条依据 + 三条翻盘条件）。
- ❌ 引入全新工具链与前端重写成本，与"个人自用、一天一版"的迭代节奏冲突。

### 3.4 Option D（**采纳**）：不换壳 —— PWA 零代码验证 + 数据目录外置

- ✅ **Ladder L1**：要的"独立窗口"**已经免费存在**（PWA），先零成本验证需求真伪再决定是否动打包。
- ✅ **Ladder L1/L2**：数据目录外置复用已有的 `DELECTOR_DATA_DIR` 机制（Android 侧就在用），**不是新机制**。
- ✅ 不动打包 ⇒ 不触发四端同步守卫的新位点、不引入新依赖、不触碰 ADR-0018。

---

## 4. Decision Outcome

| 前沿问题 | 拍板 | 含义 |
| --- | --- | --- |
| **Q1 需求真伪**（先验证还是先动工） | **A：先用现成 PWA 零代码试用** | 本轮**不动打包**；若试用后仍不够（如一周内仍因误关标签丢内容），再议外壳 |
| **Q2 数据落点**（是否外置） | **A：外置到 `%LOCALAPPDATA%\DeLector`** | 堵住"解压覆盖/删目录 = 数据全空"；**迁移闸首次在桌面端生效** |
| **Q3 便携性**（外置后还能不能拷走） | **B：默认外置 + 保留便携开关** | 保留一个开关（如 `DELECTOR_PORTABLE=1`）可覆盖回"数据随程序目录"，U 盘/多机场景仍可用 |

**技术栈结论（回答原问题的第二层）**：**不改技术栈**。仍是 FastAPI + uvicorn + 原生 JS；不引入 webview、不换 Rust/Go 主体、不加 Electron/Tauri。"桌面感"由**浏览器已有的 PWA 安装能力**提供（零代码）。

---

## 5. Consequences

**正面**
- 数据不再随解压目录消失（唯一真会丢东西的路径被堵）。
- 迁移闸在桌面端**首次真正生效**（此前条件④恒等 ⇒ 永不触发）。
- "独立窗口/任务栏图标"若 PWA 可用 ⇒ **零代码**获得，无需任何打包改造。

**负面 / 代价**
- 数据落点从"随目录"变为"默认固定" ⇒ 引入一个环境变量分支（**可接受**：`DELECTOR_DATA_DIR` 已存在，Android 侧在用）。
- 首次切换时若新位置为空、旧位置有 db ⇒ **必须自动迁移**（先备份再搬，并写进启动日志）；否则迁移闸 fail-loud 会让用户"升级后打不开且不知道为什么"。
- 便携模式下数据仍随目录 ⇒ **该模式下丢数据风险依旧存在**，需在开关处明写提示。

**中性 / 明确不做（写死以防悄悄重开）**
- ❌ 原生窗口壳（webview）；❌ 安装器与卸载器；❌ 开机自启；❌ `--windowed`（本轮）；❌ 换栈重写。
- ❌ 不改 LAN 默认绑定（见 §6.5）。

---

## 6. 落地（按顺序）

1. **PWA 零代码验证**：在 Edge/Chrome 打开 `http://127.0.0.1:8000`，看是否出现「安装此站点为应用」。
   - 若**没有**安装选项 ⇒ 先补 `192×192` / `512×512` 的 **PNG** 图标（当前是内联 SVG）并写进 manifest —— 这是最便宜的第一步。
   - 试用一周，判断"独立窗口"是否真的解决了标签页混杂/误关的痛点。
2. **数据目录外置（本轮真做）**：`start.py` 在 import server **之前**显式设 `DELECTOR_DATA_DIR=%LOCALAPPDATA%\DeLector`；首次启动做**一次性迁移**（旧位置有 db、新位置为空 ⇒ 备份后搬移，并记日志）；迁移闸保留 fail-loud 兜底。
3. **（PWA 验证后若仍不够，才轮到它）`--windowed` 的必备前置，缺一不可**：
   - stdout/stderr 重定向到 `launch.log`（`--windowed` 下 `sys.stdout` 为 `None`，须显式开句柄）；
   - `main` 全包 `try/except` → 写 traceback + 弹 MessageBox；
   - 托盘显示状态/端口/版本；health 就绪后再开窗。
4. **单实例与端口（登记，不在本轮）**：`%LOCALAPPDATA%\DeLector\instance.lock`（pid + 版本 + 数据目录）；探测改为验证 `/api/health` 带 DeLector 标识，不匹配则顺延 8001–8010 —— 单实例靠**文件锁**而非端口探测。
5. **LAN 绑定维持现状**：桌面端仍绑 `0.0.0.0`（"同 Wi-Fi 手机可访问"是有意特性）。**已知边界**：该面无鉴权，部分写端点不打 `_require_localhost` 闸 ⇒ **正因如此，开机自启被否决**；若将来要做常驻/自启，必须先把它改成默认 `127.0.0.1` + 显式开关。

---

## 7. Fog of War（本 ADR 未决）

- **[Unknown 1] PWA 安装提示会不会出现**：图标是内联 SVG（Chrome/Edge 通常要 PNG 才给安装选项）⇒ **一次性验证即可消除**；若不出现，补 PNG 即可。
- **[Unknown 2] 试用一周后"独立窗口"是否真解决痛点**：若仍出现"每周 ≥1 次因误关标签丢写作内容"，或工具要交给第二个人使用 ⇒ **Option A（真窗口）+ 安装器**立刻从过度设计升为真需求，需另开 ADR。
- **[Unknown 3] 自动迁移的边界情形**：旧位置同时存在 `delector.db` 与 `-wal`/`-shm` 时，只搬主库会丢最近写入 ⇒ 迁移必须带上 WAL 侧文件或先做 checkpoint。**实施前必须验证**。
- **[Unknown 4] 便携模式（`DELECTOR_PORTABLE=1`）下的提示**：该模式仍会随目录丢数据 ⇒ 需要什么形式的用户提示（启动横幅 / 托盘 / 日志）未定。

---

## 8. 关联

- **ADR-0017**（更新可见性）、**ADR-0018**（性能 O0 / 换主体否决）、**ADR-0008 / ADR-0010**（Go/Python 边界）、**ADR-0016**（统一词池）
- `DELECTOR-DEV-RULES.md §2.4`（四端打包同步守卫）
- `08-Projects/Hermes/02-Post-mortem/POST-MORTEM-ELEVATED-INSTALLER-ACL-LOCKOUT.md`（提权安装器事故，否决安装器的直接依据）
- `06-Sources/Articles/GO-PYTHON-HYBRID-ARCHITECTURE.md §5`（打包体积对比）
