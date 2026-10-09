# ADR-0020: Windows 桌面壳 —— pywebview + 托盘，Python 仍是 HTTP 主体

> **正式件:** `08-Projects/DeLector/01-ADR/0020-windows-desktop-shell-pywebview.md`（vault）。本文件是仓内副本，内容与正式件同源（机械重新生成，未手抄）。
> **决策者:** Haoyu Xi ｜ **产出方式:** `/dfs-grill` 续轮（sre-resilience 可行性/代价评估）+ 用户拍板（Q5-A / Q6-A）。
> **要点:** 采纳 `pywebview` + `pystray` 桌面壳（Python 仍是 HTTP 主体，**不违反 ADR-0018**）；按 A 顺序：数据外置 → 手动更新入口 → 桌面壳；四个必须前置：退出收尸 / 启动反馈 / WebView2 检测 / 日志弹窗。

- **状态**: Accepted（2026-10-10）
- **实施**: **待执行**。按 **A 顺序**推进：① 数据目录外置（ADR-0019 Q2-A，强制前置）→ ② 手动「检查更新」入口（Q5-A）→ ③ 桌面壳本体（窗口 + 托盘 + 退出收尸 + splash + WebView2 检测）。
- **日期**: 2026-10-10
- **领域**: 桌面形态 / 进程生命周期 / 打包分发
- **决策者**: Haoyu Xi
- **上游**: **ADR-0017**（更新可见性：检查 + 提示，不做应用内安装）、**ADR-0018**（换 HTTP 主体永久否决；首启 2.6s 其中模型加载 1.47s）、**ADR-0019**（Windows 桌面端：不换壳、不做安装包、数据外置）、DEV-RULES §2.4（四端打包同步守卫）
- **本 ADR 的定位**: ADR-0019 判定"外壳是过度设计"，其**前提是"现成 PWA 的独立窗口够用"**。用户实测后判定**不够用** ⇒ 该前提被推翻 ⇒ 外壳议题独立成篇。**数据外置（ADR-0019 Q2-A）与更新入口（Q5-A）不受影响，且是本篇的前置。**

---

## 1. Context

### 1.1 触发

用户试用现成 PWA 的独立窗口后：**"独立窗口不够用。我还希望要有检查更新。"**

⇒ 两点：① ADR-0019 Q1 的前提（"独立窗口能满足桌面感"）**被实测推翻**；② 追加"检查更新"诉求（详见 §1.3）。

### 1.2 现状（已核实）

- `start.py:86-102` 仅 `server.run()`，**无退出控制**；`:61-67` 端口 8000 被占用则"复用"（**不校验对方是不是 DeLector**）。
- 打包：`package_windows.py` → `PyInstaller --onedir --console`，产物 **75MB**；CI 见 `build-release.yml:28-45`。
- 数据：`database.py:24-35` 桌面端无 `DELECTOR_DATA_DIR` 兜底 ⇒ 数据落程序目录；SQLite 用 WAL（`:147-155`）。
- 首启（ADR-0018 §7.3）：`health_200` **2.6s**，其中 spaCy 模型加载 **1.47s（58%）**；**首屏渲染未实测**。
- 更新检查：`GET /api/update/check` 已存在（`delector/routes/update.py`），顶栏 chip（`static/js/update.js`、`static/index.html:40`），**仅 `has_update === true` 时可见** ⇒ 用户当前是最新版 ⇒ **永远看不到**（这是"感觉没有更新检查"的真正原因，不是功能缺失）。

### 1.3 "检查更新"到底缺什么（已澄清）

| 层 | 现状 | 本 ADR |
| --- | --- | --- |
| 自动检查 + chip | ✅ 已有（3s 延迟 + 6h/60s TTL） | 不动 |
| **手动入口 + 人话反馈** | ❌ 缺（无新版/失败时零可见变化） | **Q5-A：做**（纯前端小改动） |
| 一键下载新便携包 | ❌ 缺 | 可选第二步（**不在本轮**） |
| 应用内安装/自动替换 | ❌ 缺，**ADR-0017 明确否决** | **不做**（日后推进需另开 ADR 翻案） |

---

## 2. Decision Drivers

- **不违反 ADR-0018**：桌面壳只是**换前端宿主**，Python + FastAPI 仍是 HTTP 主体 —— ADR-0018 否决的是"把主体重写成 Go/Rust"。
- **生命周期必须先修**：当前退不干净 ⇒ "以为升级了其实跑旧进程"是**静默失败**，比"没有桌面窗口"严重得多。
- **打包位点是最贵的一项**：DEV-RULES §2.4 已因漏同步出过白屏 APK ⇒ 任何新增依赖都要算上它的维护税。
- **可观测性优先**：任何"看不到反馈"的窗口（无 splash、无失败提示）都是静默失败。

---

## 3. Considered Options

### 3.1 Option B1：`pywebview` + `pystray`（✅ 采纳）

- ✅ Python 同栈，**复用现有 Windows 产物即可，不新增第 5 个打包位点**（前提：不另建 spec / 不产第二产物）。
- ✅ 用**系统自带的 Edge WebView2** ⇒ 体积只由 75MB 增至 **80–90MB**。
- ⚠️ 冻结需 `--collect-all=webview` + hidden-import（`webview.platforms.edgechromium/winforms`、`pystray._win32`）+ **验包 `WebView2Loader.dll`、`Microsoft.Web.WebView2*.dll`**（遗漏 ⇒ 白屏，与既有事故同款）。

### 3.2 Option B2：Tauri / Electron 壳 —— ❌ 否决

- 架构上与 B1 等价（内嵌 webview + 本地 HTTP 服务），但引入**全新工具链与构建流水线**，与"个人自用、一天一版"的节奏冲突；且同样要付打包位点成本。

### 3.3 Option C：只加托盘入口，不做真窗口 —— ❌ 否决

- 用户已明确"独立窗口不够用" ⇒ 托盘入口**不是真桌面窗口**，不满足诉求。

### 3.4 CEF —— ❌ 否决

- 体积额外 **+约 100MB**（vs 系统 WebView2 的 +5~15MB）。

---

## 4. Decision Outcome

**采纳 B1，按 A 顺序推进：**

| 步 | 内容 | 依赖 |
| --- | --- | --- |
| ① | **数据目录外置**到 `%LOCALAPPDATA%\DeLector` + 一次性自动迁移 + 便携开关（`DELECTOR_PORTABLE=1`） | ADR-0019 Q2-A/Q3-B；**也是 ③ 的强制前置** |
| ② | **手动「检查更新」入口** + 人话反馈（"已是最新 vX.Y.Z" / "连不上 GitHub，请稍后重试"） | Q5-A；纯前端，独立可交付 |
| ③ | **桌面壳**：`desktop.py`（pywebview 窗口 + pystray 托盘 + 统一退出 + splash + WebView2 运行时检测）；`start.py` 改为可控生命周期 | 必须在 ① 之后 |

### ③ 的四个**必须一起做**的前置（缺一不可，否则是静默失败）

1. **退出收尸**：webview 主线程 + **同进程非 daemon server 线程**；所有退出路径统一 `server.should_exit = True` + 5s graceful timeout + `join` + 超时硬退出；health 探测**必须校验 DeLector 身份与版本**（消除"复用旧进程"）。
2. **启动反馈**：原生 splash/loading，分阶段报告（加载模型 → 起服务 → 就绪）；health 轮询要有**单次超时 + 退避 + 总截止时间**（当前端口探测无显式超时，`start.py:21-23`）。
3. **WebView2 运行时检测**：Win11 通常自带、Win10 不保证 ⇒ 启动前检测，缺失则引导安装（否则打破"解压即用"）。
4. **日志与失败弹窗**：桌面形态下 stdout 不可见 ⇒ 写 `launch.log` + 顶层 `try/except` 弹窗。

### YAGNI（明确不做）

Tauri/Electron、CEF、安装器与卸载器、开机自启、应用内安装更新、多窗口。

---

## 5. Consequences

**正面**
- 真独立窗口 + 托盘入口 + 统一退出 ⇒ 消除"误关标签""跑旧进程"两类静默失败。
- "检查更新"变为可感知（手动入口 + 人话反馈）。
- 数据外置后，后续"下载新便携包替换"才不至于等于清空学习记录。

**负面 / 代价**
- **新增 2 个运行时依赖**（pywebview、pystray）与打包冻结项 ⇒ 打包守卫负担上升（虽不新增位点，但多了 `--collect-all` 与 DLL 验包）。
- **打破"零依赖"卖点**：Win10 上可能需要引导安装 WebView2 运行时。
- 冷启动由 2.6s 增至 **3.5–5s**（首次建档 5–8s）⇒ 必须靠 splash 补偿，否则体验更差。
- 体积 75MB → 80–90MB；Defender 误报风险**不降**（GUI/native DLL 可能增大启发式命中面）⇒ 发布产物需做 Defender 扫描。

---

## 6. Fog of War

- **[Unknown 1] Win10 上的 WebView2 覆盖率**：若目标机器无 Evergreen Runtime，是引导安装还是捆绑固定运行时（后者 +体积但保真离线便携）—— 未定，实施时按实测决定。
- **[Unknown 2] 首屏渲染时间未实测**：已知 `health_200` 2.6s，**首屏可用时间仍是代理口径**（与 ADR-0018 §8 Unknown 8 同源）⇒ 桌面壳落地后应补测一次真首屏。
- **[Unknown 3] 误报率变化**：加了 GUI/native DLL 后 Defender 命中率是否上升 —— 需发布后观测。
- **[Unknown 4] 托盘在 Windows 上的交互细节**：pystray 与 pywebview 的事件循环共存方式需实测（是否要各自线程）。

---

## 7. 关联

- **ADR-0017**（更新可见性边界：不做应用内安装）、**ADR-0018**（主体不换 / 首启数字）、**ADR-0019**（数据外置与"不换壳"的原始判定，其 Q1 前提已被本篇推翻）、DEV-RULES §2.4（四端打包同步守卫）
- `08-Projects/Hermes/02-Post-mortem/POST-MORTEM-ELEVATED-INSTALLER-ACL-LOCKOUT.md`（否决安装器的依据，本篇继续沿用）
