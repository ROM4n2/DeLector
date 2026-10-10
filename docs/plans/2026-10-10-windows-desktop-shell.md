# Windows 桌面壳 Implementation Plan

> **Goal**: 按 ADR-0020 的 A 顺序交付三步 —— ① 把便携版数据从"程序目录"救到 `%LOCALAPPDATA%\DeLector`；② 让**已存在但不可发现**的手动"检查更新"入口变得可见可点；③ 交付 `pywebview` + `pystray` 桌面壳（含退出收尸 / 启动反馈 / WebView2 检测 / 日志弹窗四个必须前置）。
> **Tech Stack**: Python 3.11 / FastAPI + uvicorn / 原生 JS 前端 / PyInstaller `--onedir` / Windows；GUI 侧新增 `pywebview`（系统 Edge WebView2）+ `pystray`。
> **Spec Reference**: [ADR-0020](../../Obsidian/Coding/08-Projects/DeLector/01-ADR/0020-windows-desktop-shell-pywebview.md)（仓内副本：`docs/adr/2026-10-10-adr-0020-windows-desktop-shell-pywebview.md`）、[ADR-0019](docs/adr/2026-10-10-adr-0019-windows-desktop-pwa-first-and-data-dir-externalization.md)、ADR-0017（更新可见性边界）、ADR-0018（首启数字 / 换主体永久否决）。
> **Global Constraints**:
> - **不改 HTTP 主体**：Python + FastAPI 仍是服务端（`delector/server.py`），桌面壳只是前端宿主 ⇒ 不得触碰 ADR-0018 的否决边界。
> - **禁新增静默失败**：任何"看不到反馈"的改动（无 splash、无日志、退不干净）都算不合格。
> - **迁移幂等 + 单事务**：数据迁移 MUST 可重入、失败可回滚到"旧位置仍在"，且 **MUST 处理 WAL**（`-wal`/`-shm`）。
> - **禁类型检查豁免**（`# type: ignore` / `# noqa` / `# mypy: disable-error-code`）；注释写"为什么"；最大缩进 2 层。
> - 每个任务独立分支提交前跑：半 A `python -m pytest tests/ --ignore=tests/test_server.py -q`、半 B `python -m pytest tests/test_server.py -q`、`mypy --follow-imports=skip tests`、`mypy --strict delector tools`、`ruff check .`。

---

## 🏛️ Decisions So Far

- **ADR-0019**：不做安装器、不开机自启、不做应用内安装更新、不改技术栈；数据目录外置 + 便携开关（Q2-A / Q3-B）。
- **ADR-0019 §8**：用户试用 PWA 后判定"独立窗口不够用" ⇒ Q1 前提被推翻 ⇒ 外壳转由 ADR-0020 承接（§3.1 对 webview 的否决理由**仍成立**，ADR-0020 是在接受代价并配齐前置的前提下做的决定）。
- **ADR-0020**：采纳 `pywebview` + `pystray`；按 A 顺序 ①→②→③；四个必须前置；YAGNI（Tauri/Electron、CEF、安装器、自启、应用内安装更新、多窗口）。
- **本轮核实的现状（改变计划形态）**：
  - **数据外置不会撞坏那颗钉子**：`tests/test_backend_package_layout.py:40-41` 在显式设了 `DELECTOR_DATA_DIR` 时 **skip** ⇒ 它只钉"默认值"；`start.py` 里设 env 不影响该测试。
  - **手动"检查更新"入口已存在**：`static/js/update.js:104-107` 把 `topbar-system` 的 click 接到 `runCheck(true)`，会显示"已是最新"或人话错误 ⇒ **缺的是可发现性**（`static/index.html:34-36` 的 `#topbar-system` 既无 `title` 也无 `cursor:pointer`，用户不可能知道能点）。⇒ Task 2 是"让它可被发现"，不是新建功能。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: 数据目录解析与一次性迁移 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `delector/core/data_dir_bootstrap.py`
- Modify: `start.py`（在 `import uvicorn` / `from delector.server import app` **之前**调用 bootstrap）
- Test: `tests/test_desktop_data_dir_bootstrap.py`

**Interfaces:**
- Consumes: `os.environ`（`DELECTOR_DATA_DIR`、`DELECTOR_PORTABLE`、`LOCALAPPDATA`）、`delector.core.database.DATA_DIR` 的既有语义
- Produces:
  - `def resolve_data_dir(env: Mapping[str, str]) -> str`
    —— 优先级：**① 已显式设 `DELECTOR_DATA_DIR` 则原样采用**（Android/测试注入不受影响）→ **② `DELECTOR_PORTABLE=1` 则回退到程序目录**（便携/U 盘场景）→ **③ 否则 `%LOCALAPPDATA%\DeLector`**（Windows）；非 Windows 落到 `~/.local/share/DeLector`。
  - `def migrate_legacy_data_dir(legacy_dir: str, target_dir: str) -> bool`
    —— 仅当 `target` 为空**且** `legacy` 有库文件时搬；**先备份**（`*.bak-<ts>`）再搬，**必须带上 `-wal` / `-shm`**（或先 `PRAGMA wal_checkpoint(TRUNCATE)`）；任何异常 ⇒ 返回 `False` 且**保留旧位置不动**（fail-safe，绝不半搬）。

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: No-Silent-Failure]`：迁移失败必须写日志并让上层可见（不允许 `except: pass` 吞掉）。
- [ ] `[Instinct: Idempotent-Migration]`：连续调用两次结果一致；用"迁移→新写入→重启"三段时序回归断言。
- [ ] `[Instinct: Guard-Clause]`：扁平化，最大缩进 2 层。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 数据目录解析与一次性迁移.
> Mode: AFK | Role: TDD Builder
> Goal: 便携版数据不再落程序目录（升级/删目录即丢），改为默认 `%LOCALAPPDATA%\DeLector`，并保留便携开关.
> Target Files: Create `delector/core/data_dir_bootstrap.py`, Modify `start.py`, Test `tests/test_desktop_data_dir_bootstrap.py`.
> Hard constraints: (1) `start.py` MUST 在 import server 之前调用 bootstrap（否则 `database.py:35` 已按仓库根落定）；(2) `resolve_data_dir` 优先级：显式 `DELECTOR_DATA_DIR` > `DELECTOR_PORTABLE=1`(程序目录) > `%LOCALAPPDATA%\DeLector`；(3) `migrate_legacy_data_dir` MUST 处理 WAL（`-wal`/`-shm` 或先 checkpoint），先备份，异常时**保留旧位置不动**并 return False；(4) 幂等：跑两次结果一致.
> Injected Instincts: No-Silent-Failure / Idempotent-Migration / Guard-Clause
> TDD Steps:
> 1. 写失败测试 `tests/test_desktop_data_dir_bootstrap.py`（覆盖：优先级三分支、幂等、WAL 一起搬、异常不半搬）（RED）.
> 2. `python -m pytest tests/test_desktop_data_dir_bootstrap.py -q` 验证失败.
> 3. 实现 `resolve_data_dir` / `migrate_legacy_data_dir`（GREEN）.
> 4. 在 `start.py` 顶部接线（**在 import server 之前**）.
> 5. 跑全量门禁（半 A/半 B/mypy/ruff）.
> Return: Summary with MANDATORY Physical Execution Receipt (exit code + passed 计数 + git diff --stat)."

**Step Breakdown:**
- [ ] **Step 1: Write the failing test (RED)**
- [ ] **Step 2: Run test and verify it fails with expected message**
- [ ] **Step 3: Implement minimal production code (GREEN)**
- [ ] **Step 4: Run tests and verify all green**
- [ ] **Step 5: Refactor & Flatten with guard clauses (REFACTOR)**
- [ ] **Step 6: Physical Evidence Gate**: 原始终端回执（命令 + exit code + passed 计数 + `git diff --stat`）
- [ ] **Step 7: Git atomic commit**

---

### Task 2: 让已存在的手动「检查更新」入口可被发现 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `static/index.html:34-36`（`#topbar-system` 加 `title`、`role="button"`、`tabindex="0"`）
- Modify: `static/style.css`（`/style.css` 对应的主样式表；加 `cursor:pointer` 与 hover 提示）
- Modify: `static/js/update.js`（补键盘可达：Enter/Space 触发；`title` 文案随状态更新）
- Test: `tests/test_update_chip_ui.py`（既有文件，按需要新增断言）
- Probe: `tools/wb_update_chip_probe.mjs`（既有 11 场景；新增 `manual_entry_is_discoverable` 场景）

**Interfaces:**
- Consumes: `initUpdateCheck()` 已有的 `runCheck(true)` 手动路径与 `showNotice()`（`static/js/update.js`）
- Produces:
  - `static/index.html` 中 `#topbar-system` 具备可点击语义（`title` / `role` / `tabindex`）
  - `static/js/update.js` 导出 `const MANUAL_HINT = "点击检查更新"` 供探针与 `title` 复用

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: Human-Readable-Failure]`：失败文案必须是人话（沿用 `humanize()` 的既有映射），禁止回显原始 HTTP/fetch 串。
- [ ] `[Instinct: Contract-Test]`：探针断言必须钉 `title`/`role`/键盘触发三条，不能只查"元素存在"。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: 让已存在的手动检查更新入口可被发现.
> Mode: AFK | Role: TDD Builder
> Goal: `static/js/update.js` 已把 `#topbar-system` 的 click 接到 `runCheck(true)`，但用户在 UI 上完全看不出来能点 ⇒ 补可发现性与键盘可达.
> Target Files: Modify `static/index.html`, `static/style.css`（`/style.css` 对应的实际样式表，先确认路径）, `static/js/update.js`; Test `tests/test_update_chip_ui.py`; Probe `tools/wb_update_chip_probe.mjs`.
> Hard constraints: (1) **不要**改动 `has_update===true` 才显示 chip 的既有可见性红线（ADR-0017 设计）；(2) 手动路径的文案继续走 `humanize()`，不得回显原始错误串；(3) 探针新增一个 `manual_entry_is_discoverable` 场景，断言 title/role/键盘触发.
> Injected Instincts: Human-Readable-Failure / Contract-Test
> TDD Steps: 1) 探针与测试先红；2) 验证红；3) 改 HTML/CSS/JS 至绿；4) 跑探针与全量门禁.
> Return: Summary with MANDATORY Physical Execution Receipt."

**Step Breakdown:**
- [ ] **Step 1: Write the failing probe/test (RED)**
- [ ] **Step 2: Run and verify it fails**
- [ ] **Step 3: Implement minimal production code (GREEN)**
- [ ] **Step 4: Run tests/probes and verify all green**
- [ ] **Step 5: Refactor (REFACTOR)**
- [ ] **Step 6: Physical Evidence Gate**
- [ ] **Step 7: Git atomic commit**

---

### Task 3: uvicorn 生命周期可控化 + 端口复用身份校验 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `start.py:86-106`（`server.run()` 改为可控生命周期）+ `:21-23`（`is_port_in_use`）
- Create: `delector/core/server_lifecycle.py`
- Test: `tests/test_start_lifecycle.py`

**Interfaces:**
- Consumes: `uvicorn.Config` / `uvicorn.Server`、`GET /api/health`（`delector/routes/main.py:2596`）
- Produces:
  - `def build_server(host: str, port: int) -> uvicorn.Server`
  - `def serve_in_thread(server: uvicorn.Server) -> threading.Thread` —— **非 daemon**，可被 join
  - `def shutdown(server: uvicorn.Server, thread: threading.Thread, grace_s: float = 5.0) -> bool`
    —— `server.should_exit = True` → `thread.join(grace_s)` → 超时返回 `False`（由调用方硬退出）
  - `def probe_identity(port: int, timeout_s: float = 3.0) -> bool`
    —— 探测 `/api/health` 且**校验响应带 DeLector 标识/版本**；不匹配 ⇒ `False`（消除"复用别人的服务/旧进程"）

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: Concurrency]`：线程创建者 MUST 负责销毁；MUST 提供确定的退出路径与超时兜底。
- [ ] `[Instinct: No-Silent-Failure]`：退出超时/失败必须可观测（日志 + 返回值），不得假装成功。
- [ ] `[Instinct: Timeout-Budget]`：探测 MUST 有显式超时且**对 spaCy 冷启动宽容**（参考 vault：`ProbeTimeout` 对冷启动偏紧，桌面端建议 ≥10s 的就绪等待窗口，单次探测 3s）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: uvicorn 生命周期可控化 + 端口复用身份校验.
> Mode: AFK | Role: TDD Builder
> Goal: 消除两类静默失败 —— (a) 壳退出后服务残留 ⇒ 下次 `start.py:61-67` 盲复用端口，用户以为升级了其实跑旧进程；(b) 端口被别的软件占用 ⇒ 打开无关页面.
> Target Files: Create `delector/core/server_lifecycle.py`, Modify `start.py`, Test `tests/test_start_lifecycle.py`.
> Hard constraints: (1) server 线程**非 daemon**，必须可 join；(2) `shutdown()` 用 `should_exit=True` + `join(5s)`，超时返回 False；(3) `probe_identity()` 必须校验 DeLector 身份/版本，**不能只探端口能否连上**；(4) 保留 Android 子线程里禁用 signal handler 的既有兼容（`start.py:98-102`）；(5) 单次探测 3s 超时，但就绪等待窗口要给足（spaCy 冷启动数秒）.
> Injected Instincts: Concurrency / No-Silent-Failure / Timeout-Budget
> TDD Steps: 1) 失败测试（真起服务→shutdown→断言线程已结束；假服务占端口→`probe_identity` 返回 False）；2) 验证红；3) 实现；4) 全量门禁.
> Return: Summary with MANDATORY Physical Execution Receipt."

**Step Breakdown:**
- [ ] **Step 1: Write the failing test (RED)**
- [ ] **Step 2: Run test and verify it fails with expected message**
- [ ] **Step 3: Implement minimal production code (GREEN)**
- [ ] **Step 4: Run tests and verify all green**
- [ ] **Step 5: Refactor & Flatten with guard clauses (REFACTOR)**
- [ ] **Step 6: Physical Evidence Gate**
- [ ] **Step 7: Git atomic commit**

---

### Task 4: 桌面壳 `desktop.py`（窗口 + 托盘 + splash + 退出编排 + WebView2 检测 + 日志弹窗） [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `desktop.py`（仓库根，与 `start.py` 并列）
- Test: `tests/test_desktop_shell.py`
- Modify: `requirements.txt`（新增 `pywebview`、`pystray`；写清 pin 与理由）

**Interfaces:**
- Consumes: `delector.core.server_lifecycle.build_server/serve_in_thread/shutdown/probe_identity`（Task 3 产物）、`delector.core.data_dir_bootstrap.resolve_data_dir`（Task 1 产物）
- Produces:
  - `def ensure_webview2_runtime() -> bool` —— 检测失败返回 `False`（由上层决定是否引导安装）
  - `def run_desktop(port: int = DEFAULT_PORT) -> int` —— 返回进程退出码；**所有退出路径** MUST 先 `shutdown(server, thread)` 再退出。
    > **实现漂移回填（Task 5 收口）**：计划原写 `run_desktop(port: int, log_path: str) -> int`，实际实现为
    > `run_desktop(port: int = DEFAULT_PORT) -> int`（`DEFAULT_PORT = 8000`）。`log_path` 由 `resolve_log_path(os.environ)`
    > **内部解析**（不作出参），`port` 给了默认值 —— 二者等价，且唯一消费者 `dispatch` 的调用方式不受影响。
  - splash：服务未 ready 前显示原生 loading 窗口，分阶段文案（加载模型 → 起服务 → 就绪）
  - 托盘菜单：`打开` / `检查更新`（打开 release 页 或 触发 `/api/update/check`） / `退出`
  - 日志：stdout/stderr 重定向到 `launch.log`；顶层 `try/except` 写 traceback 并弹 MessageBox

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: No-Silent-Failure]`：GUI 形态看不到 stdout ⇒ 日志与弹窗是**硬要求**，不是可选项。
- [ ] `[Instinct: Environment-Skip]`：GUI 无法在 CI 拉起 ⇒ 测试 MUST 用「零依赖纯逻辑」作主断言（路径解析/退出编排/运行时检测），GUI 部分 `pytest.skip` 带理由，**绝不假绿**。
- [ ] `[Instinct: Supply-Chain]`：新增依赖 MUST 记录 pin 理由与体积影响（见 ADR-0020 §5）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 4: 桌面壳 `desktop.py`.
> Mode: AFK | Role: TDD Builder
> Goal: 真桌面窗口 + 托盘，且退出时服务一定被收掉.
> Target Files: Create `desktop.py`, Test `tests/test_desktop_shell.py`, Modify `requirements.txt`.
> Hard constraints: (1) 复用 Task 3 的 `server_lifecycle`（**不要**自己再写一套 server 启停）；(2) webview 主线程 + server 非 daemon 线程；**所有**退出路径（关窗/托盘退出/异常）MUST 先 `shutdown()`；(3) ready 前显示 splash 并分阶段；(4) `ensure_webview2_runtime()` 检测缺失返回 False 并给引导提示；(5) 日志写 `launch.log`，顶层 try/except 弹窗；(6) 托盘含「检查更新」项.
> Injected Instincts: No-Silent-Failure / Environment-Skip / Supply-Chain
> TDD Steps: 1) 纯逻辑测试先红（退出编排、运行时检测、日志路径）；2) 验证红；3) 实现；4) GUI 部分用 skip 守卫；5) 全量门禁.
> Return: Summary with MANDATORY Physical Execution Receipt."

**Step Breakdown:**
- [ ] **Step 1: Write the failing test (RED)**
- [ ] **Step 2: Run test and verify it fails with expected message**
- [ ] **Step 3: Implement minimal production code (GREEN)**
- [ ] **Step 4: Run tests and verify all green**
- [ ] **Step 5: Refactor & Flatten with guard clauses (REFACTOR)**
- [ ] **Step 6: Physical Evidence Gate**
- [ ] **Step 7: Git atomic commit**

---

### Task 5: 打包冻结与四端同步守卫 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `package_windows.py`（新增 `--collect-all=webview` 与 `webview.platforms.edgechromium` / `webview.platforms.winforms` / `pystray._win32` 的 hidden-import；增加 `desktop.py` 入口）
- Modify: `.github/workflows/build-release.yml`（Windows 产物口径；**不新增第二产物/spec**）
- Modify: `.github/workflows/ci.yml`（**收口回填**：新增新入口裸露面的 mypy 门禁；见下"收口回填"）
- Test: `tests/test_server.py`（既有四端打包同步守卫 `:4559-4662`）+ 新增 **DLL 验包断言**

**Interfaces:**
- Consumes: `package_windows.py` 既有的 `--hidden-import` 列表结构
- Produces: 产物内 MUST 含 `WebView2Loader.dll`、`Microsoft.Web.WebView2*.dll`（缺失 ⇒ 白屏，与既有事故同款）；守卫测试断言该清单

**收口回填（2026-10-10 审查后，Task 5 收口轮）：**
- **① 新入口类型门禁**：CI 两条既有 mypy 门禁都**显式传目标**（`mypy --strict delector tools` / `mypy --follow-imports=skip tests`），
  故 `desktop.py` / `conftest.py` / `package_windows.py` / `start.py` **在 CI 里从不被检查**；`pyproject.toml` 的 `files`
  只影响"本地裸跑 `python -m mypy`"（且裸跑会因既有 **17 条**无关错误转红，故**不可**裸跑当门禁）。⇒ 在 `ci.yml` 新增：
  `mypy --strict --follow-imports=skip desktop.py package_windows.py conftest.py`。
  **后续（未纳入）**：`start.py` 因两处 `# type: ignore`（`server.install_signal_handlers` / `capture_signals`）在 skip 口径下
  变 `unused-ignore` 而卡住 —— 禁新增豁免，故本轮不纳入；待后续以签名/局部收窄替换那两处 ignore 后再并入本条门禁。
- **⑥ `--server-only` 下 `--port` 语义**：选 **(a)** —— 该路径复用 `start.main()`（固定端口），对显式传入的非默认 `--port`
  **发出显式警告**（不改 `start.main()` 签名，避免引入 port-identity / LAN 面回归）；**不再静默**。

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: Packaging-Sync]`：DEV-RULES §2.4 的四端同步守卫 —— 新增依赖 MUST 在所有相关位点注册（本 ADR 前提：**不新增第 5 个产物位点**，故只动 Windows 冻结项）。
- [ ] `[Instinct: Falsifiable-Gate]`：验包断言必须能被"故意删掉某个 DLL/hidden-import"打红（做一次变异自证）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 5: 打包冻结与四端同步守卫.
> Mode: AFK | Role: TDD Builder
> Goal: 桌面壳能在 PyInstaller `--onedir` 产物里真跑起来（不白屏），且守卫能抓住漏配.
> Target Files: Modify `package_windows.py`, `.github/workflows/build-release.yml`, Test `tests/test_server.py`.
> Hard constraints: (1) **不另建 spec / 不产第二产物**（否则会新增第 5 个打包位点）；(2) 冻结项至少含 `--collect-all=webview` 与 `webview.platforms.edgechromium`/`winforms`、`pystray._win32`；(3) 新增 DLL 验包断言，并做**变异自证**（临时删一项 ⇒ 必须红，然后恢复）；(4) 不要改 `--console`（本轮不启用 `--windowed`）.
> Injected Instincts: Packaging-Sync / Falsifiable-Gate
> TDD Steps: 1) 验包断言先红；2) 验证红；3) 改打包脚本至绿；4) 变异自证；5) 全量门禁.
> Return: Summary with MANDATORY Physical Execution Receipt."

**Step Breakdown:**
- [ ] **Step 1: Write the failing test (RED)**
- [ ] **Step 2: Run test and verify it fails**
- [ ] **Step 3: Implement minimal production code (GREEN)**
- [ ] **Step 4: Mutation self-proof (变异自证)**
- [ ] **Step 5: Run tests and verify all green**
- [ ] **Step 6: Physical Evidence Gate**
- [ ] **Step 7: Git atomic commit**

---

### Task 6: 实机验收与回填 [Mode: HITL] [Role: Human]

**Files:**
- Modify: ADR-0020 的 §6 实施记录（vault 正式件 + 仓内副本同步）、`WORKMEMORY/PROJECT_OVERVIEW.md`、`WORKMEMORY/work.log`

**Interfaces:**
- Consumes: Task 1–5 的产物与回执
- Produces: 实机双击的三项实测数字（首屏可用时间 / 退出后端口是否释放 / 托盘与菜单可用）

**Injected Instincts:**
- [ ] 发布产物做 **Defender 扫描**（ADR-0020 §5：GUI/native DLL 可能增大启发式命中面）
- [ ] 首屏可用时间**实测**（补掉 ADR-0018 §8 Unknown 8 的代理口径缺口）
- [ ] 退出后确认 `8000` 端口释放（消除"跑旧进程"）

**Step Breakdown:**
- [ ] **Step 1: 实机双击验证（首屏 / 托盘 / 退出收尸）**
- [ ] **Step 2: Defender 扫描**
- [ ] **Step 3: 回填 ADR-0020 实施记录 + PROJECT_OVERVIEW + work.log**
- [ ] **Step 4: 提交并合入 master（CI 绿后）**

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Unknown 1] Win10 上的 WebView2 Evergreen 覆盖率**：若目标机器无运行时，是"引导安装"还是"捆绑固定运行时"（后者 +体积但保真离线便携）—— 待 Task 4/6 实测后决定，未定前**不做**。
- **[Unknown 2] 首屏真实可用时间**：现只有 `health_200` 2.6s 的代理口径 ⇒ 待 Task 6 实测补上（与 ADR-0018 §8 Unknown 8 同源）。
- **[Unknown 3] `pystray` 与 `pywebview` 的事件循环共存方式**：是否需要各自线程 —— 待 Task 4 实测。
- **[Unknown 4] Defender 误报率变化**：待 Task 6 扫描后观测。
- **[Unknown 5] 一键下载新便携包（Q5-B）**：依赖 Task 1 数据外置完成后才安全；**不在本计划**。

---

## 🚫 Out of Scope

- Tauri / Electron 壳（B2，已否决）
- CEF（+约 100MB，已否决）
- 安装器与卸载器（Hermes 提权安装器 ACL 事故同构风险）
- 开机自启（LAN 面无鉴权）
- **应用内安装更新 / 自动替换**（ADR-0017 明确否决；日后推进需另开 ADR 翻案）
- 多窗口
- 任何改动 HTTP 主体的行为（ADR-0018）
