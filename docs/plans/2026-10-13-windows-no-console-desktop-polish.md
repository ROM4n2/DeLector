# Windows 去控制台 + 桌面化观感 Implementation Plan

> **Goal**: 去掉双击 `DeLector.exe` 时那个黑色控制台窗口，并把"失败/信息在看不见控制台时怎么给到人"收口成三重出口（`launch.log` + 原生弹窗 + 托盘与数据目录里的地址文件），顺带钉住独立图标与任务栏身份，让它**看起来像个桌面应用**而不是 Python 程序。
> **Tech Stack**: Python 3.11 / PyInstaller（Windows 子系统）/ pywebview(EdgeChromium WebView2) / pystray / Pillow(已是依赖) / ctypes(Win32) / pytest。
> **Spec Reference**: `/dfs-grill` Track 1 共识（2026-10-13，Q1=B / Q2=B / Q3=C / Q4=A）；`docs/adr/2026-10-10-adr-0019-windows-desktop-pwa-first-and-data-dir-externalization.md` §3.2（`--windowed` ⏸ 的前置条件）；`docs/adr/2026-10-10-adr-0020-windows-desktop-shell-pywebview.md`（外壳与"不新增第 5 个产物位点"）。
> **Global Constraints**:
> - **零新依赖**：图标光栅化用既有 `pillow==12.3.0`（`requirements-desktop.txt:22`，pystray 已在用）。
> - **不新增第 5 个产物位点**（ADR-0020）：只有一个 Windows 产物；调试控制台只能是**运行时开关**，不产出第二个 exe。
> - **失败必须可见**：`--windowed` 下 `sys.stdout/sys.stderr` 为 `None` ⇒ **禁止任何裸 `print()`**（v5.17.0 真启闸抓到的 `--server-only` `UnicodeEncodeError` 就是同族死法）；所有可观测信息必须有落点（日志 / 弹窗 / 托盘 / 数据目录文件）。
> - **门禁不削弱**：`ruff check .` / mypy 四档 / `pytest` 全绿；`tools/verify_windows_portable.py`（真启产物闸）只加断言不减。
> - **每任务物理证据**（原始命令 + 退出码 + 计数 + diff stat）；Tier 1 也不例外。
> - **平台安全（MUST）**：Win32 API 调用必须 `sys.platform` 守卫 + **绝不抛**（CI 是 ubuntu，`ctypes.windll` 在 Linux 不存在）。

---

## 🏛️ Decisions So Far

- **黑框根因已核实**：`package_windows.py:319` 的 `"--console",  # Keep console so user sees service logs & IP addresses`。**不是**多开了 PowerShell——`desktop.py` 的 HTTP 服务是**同进程非 daemon 线程**，托盘是 daemon 线程，无子进程。
- **ADR-0019 §3.2 的前置已配齐**（当初标 ⏸ 的理由只剩"静默失败"）：分阶段 `launch.log` 已落地、托盘已落地、`desktop.py:237` 已有原生失败弹窗 `MessageBoxW(…, 0x10)`。⇒ 本次是**执行那条既定的 contingency**，不是推翻 ADR。
- **Q1=B**：`--windowed`（不分配控制台）＋ 出口收口成三重 ＋ **CI 断言**（无控制台语境真跑一次 `--server-only` 且退出 0）。只做"最小重定向"（A）不做——那等于把事故风险换个地方；C（`FreeConsole` 隐藏）不选——仍挂控制台句柄且慢机器会闪。
- **Q2=B / Q4=A**：去黑框 ＋ 独立图标。图标**复用 `static/manifest.json:12` 里那段内联 SVG 品牌**（圆角 `rx=20`、底 `#1a1714`、衬线粗体 "De" `#c84b31`），生成 16/32/48/256 多尺寸 `.ico` ——不引入新设计，且与 PWA 安装图标同源。
- **Q3=C**：`--server-only` 的局域网地址 = 日志 ＋ 托盘菜单项 ＋ **数据目录落一份 `lan-address.txt`**（能双击打开、能复制、随时再看）。弹一次原生窗（B）作为**可选叠加**不在本计划强制项。
- **调试开关（本轮拍板，可被你否决）**：加 `--debug-console`（默认关）——需要排障时按需挂回控制台；按 ADR-0020 不产出第二个 exe。
- **任务栏身份**：`desktop.py` 当前**没有** AppUserModelID ⇒ 窗口可能按宿主（Python）分组。本次钉为 `ROM4n2.DeLector`。

---

## 🧑‍🔧 人工前置 / 收尾动作（[Mode: HITL]）

- **真机验收（只能你做）**：用本批产物双击一次，确认 ① 无黑框 ② 任务栏图标是 DeLector 品牌图标（不是 Python 默认）③ 冷启动 splash 正常 ④ 故意制造一次启动失败（如占用端口）时**有弹窗而不是"点了没反应"**。
- 若真机发现任务栏仍归到 Python 组 ⇒ 回来把 Task 4 的 AppUserModelID 生效时机改到 `webview.create_window` 之前（可能需要在建窗线程里调用）。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: 生成品牌图标资源 `assets/DeLector.ico`（16/32/48/256）[Tier: 1-Light] [Mode: AFK] [Role: Builder]

**Files:**
- Create: `assets/DeLector.ico`（产物，提交入库）
- Create: `tools/gen_app_icon.py`（可复跑的一次性生成器；不进打包、不进 requirements）

**Interfaces:**
- Consumes: `PIL.Image` / `PIL.ImageDraw` / `PIL.ImageFont`（pillow 已是依赖）
- Produces: `assets/DeLector.ico`，内含 16/32/48/256 四个尺寸；视觉与 `static/manifest.json:12` 的品牌一致（圆角深色底 + 衬线红字 "De"）；`Image.save(..., sizes=[(16,16),(32,32),(48,48),(256,256)])`

**Injected Instincts:**
- [ ] `[Instinct: 零新依赖]`：只用 pillow；字体回退要 fail-soft（找不到衬线字体时用默认字体，不许抛）。
- [ ] `[Instinct: 可复跑]`：生成器重复运行产出**同一份字节**（或至少同一视觉），便于将来换品牌只改一处。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 生成 `assets/DeLector.ico`。Mode: AFK | Role: Builder
> Steps: ① 写 `tools/gen_app_icon.py`——用 pillow 画 1024×1024 品牌图（圆角矩形底 `#1a1714`、居中衬线粗体 'De' 前景 `#c84b31`），再 `save(..., sizes=[16,32,48,256])` 输出 ico；字体获取必须 fail-soft。② 运行并确认 ico 可被 `PIL.Image.open` 读出四个尺寸。③ 回报物理收据（命令 + 退出码 + `ls -la assets/`）。不要改 `package_windows.py`（那是 Task 2）。"

**Step Breakdown:**
- [ ] Step 1: 写生成器并运行（GREEN 直接可验证，无 TDD 红绿需求）
- [ ] Step 2: `python -c "from PIL import Image; im=Image.open('assets/DeLector.ico'); print(im.sizes if hasattr(im,'sizes') else im.size)"` 确认多尺寸
- [ ] Step 3: 物理证据（命令 + 退出码 + 文件大小）

---

### Task 2: 打包切 `--windowed` 并挂图标 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `package_windows.py:319`（`--console` → `--windowed`；新增 `--icon=assets/DeLector.ico`）
- Test: `tests/test_server.py`（打包面断言族：与既有 `--hidden-import=…==2` 同类写法）

**Interfaces:**
- Consumes: `pyinstaller_cmd` 列表（现有）
- Produces: 命令里出现 `"--windowed"` 且**不再**出现 `"--console"`；出现 `f"--icon={...assets/DeLector.ico}"`；且 `--add-data` 需包含 `assets`（若 Task 1 的 ico 需随源码树存在即可，不必进产物）

**Injected Instincts:**
- [ ] `[Instinct: No-Silent-Failure]`：切 `--windowed` 后 console 消失 ⇒ 若此时还有裸 print 就是启动即崩（同族事故在案），**必须**先完成 Task 3 或在同批内一起验；两任务顺序上 Task 3 可在前。
- [ ] `[Instinct: 只扩不缩]`：既有打包面断言（hidden-import 计数、add-data）不得放松。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: 打包切 `--windowed` + 挂图标。Mode: AFK | Role: TDD Builder
> Steps: ① 在 `tests/test_server.py` 写失败测试：断言 `package_windows.py` 的 pyinstaller 命令含 `--windowed`、不含 `--console`、含 `--icon=` 指向 `assets/DeLector.ico`。② 确认 RED。③ 改 `package_windows.py:319`（并补 `--icon`）。④ 跑 `python -m pytest tests/test_server.py -q` 与相关门禁。⑤ 回报物理收据。注意：不要在本任务里改 stdout 收口（Task 3 负责）。"

**Step Breakdown:**
- [ ] Step 1: 写失败测试（RED）
- [ ] Step 2: 确认 RED 的期望报错
- [ ] Step 3: 改 `--console → --windowed` + `--icon`（GREEN）
- [ ] Step 4: `python -m pytest tests/test_server.py -q` + `ruff` + `mypy --platform win32 --strict --follow-imports=skip package_windows.py`
- [ ] Step 5: 独立 Reviewer 复核（Maker-Checker）
- [ ] Step 6: 物理证据 + 原子提交

---

### Task 3: stdout/stderr 收口（无控制台语境下不许崩）+ `--debug-console` 开关 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `desktop.py`（`:243` 的 `print(..., file=sys.stderr)`、`:772` 的 print；入口处加流收口）
- Modify: `start.py`（`:97 print_banner` / `:127` / `:178` / `:182`；入口处加流收口）
- Test: `tests/test_desktop_shell.py` 或 `tests/` 新增（造 `sys.stdout/sys.stderr = None` 语境）

**Interfaces:**
- Consumes: `sys.stdout` / `sys.stderr`（可能为 `None`）
- Produces: `def ensure_streams(log_path: str) -> None`（或等价）——当任一标准流为 `None` 时，把 `sys.stdout`/`sys.stderr` 绑定到一个**写 `launch.log`** 的流（不是 devnull：排障要有痕）；`--debug-console` 为真时不收口、按需 `AllocConsole()` 挂回；**绝不抛**

**Injected Instincts:**
- [ ] `[Instinct: No-Silent-Failure]`：收口失败也不能让进程起不来；收口本身 try/except 兜底。
- [ ] `[Instinct: 平台守卫]`：涉及 `AllocConsole`/`FreeConsole` 一律 `sys.platform == "win32"` 守卫。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: 无控制台语境的 stdout/stderr 收口。Mode: AFK | Role: TDD Builder
> Steps: ① 写失败测试：monkeypatch `sys.stdout=None`/`sys.stderr=None`，调用 `start.py` 的 banner/提示/报错打印路径与 `desktop.py` 的日志打印路径，断言**不抛**且内容落到 `launch.log`（当前会 UnicodeEncodeError/AttributeError ⇒ RED）。② 实现收口 + `--debug-console` 开关。③ 确认 GREEN 并跑门禁。④ 回报物理收据（含 RED 报错原文）。"

**Step Breakdown:**
- [ ] Step 1: 写失败测试（RED）
- [ ] Step 2: 确认 RED 期望报错（应复现 `sys.stdout is None` 一族）
- [ ] Step 3: 实现收口 + 调试开关（GREEN）
- [ ] Step 4: 门禁（pytest / ruff / mypy 四档）
- [ ] Step 5: 独立 Reviewer 复核
- [ ] Step 6: 物理证据 + 原子提交

---

### Task 4: 无控制台下的信息出口（局域网地址三重 + 任务栏身份）[Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `desktop.py`（`TRAY_MENU_SPEC` 约 `:464` 增「显示局域网地址」项 + handler；托盘 tooltip/菜单显端口与版本；建窗前设 AppUserModelID）
- Modify: `start.py`（`--server-only` 落 `lan-address.txt` 到数据目录）
- Test: `tests/test_desktop_shell.py` / `tests/`（托盘菜单规格、地址文件、AppUserModelID 的 fail-soft）

**Interfaces:**
- Consumes: `TRAY_MENU_SPEC`（(label, action) 列表）、数据目录（`bootstrap_data_dir` 的结果）
- Produces:
  - `<数据目录>/lan-address.txt`（含 `http://<LAN_IP>:<port>`；每次启动覆盖；`--server-only` 与 LAN 面可用时写）
  - 托盘菜单项「显示局域网地址」→ 点击后弹原生窗显示地址（可 Ctrl+C 复制）+ 打开所在目录？至少显示地址
  - AppUserModelID：`ROM4n2.DeLector`，通过 `ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID`，**仅 win32、fail-soft、写 `launch.log`**

**Injected Instincts:**
- [ ] `[Instinct: 平台安全]`：Win32 调用必须 `sys.platform` 守卫 + 绝不抛（CI 是 ubuntu）。
- [ ] `[Instinct: No-Silent-Failure]`：托盘项失败要写日志，不能静默丢菜单项。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 4: 无控制台下的信息出口 + 任务栏身份。Mode: AFK | Role: TDD Builder
> Steps: ① 写失败测试：(a) `TRAY_MENU_SPEC` 含「显示局域网地址」且 handler 可解析；(b) `--server-only` 会在数据目录写 `lan-address.txt` 且含 `http://`；(c) AppUserModelID 在 win32 下被调用、非 win32 下不抛。② 确认 RED。③ 实现。④ 门禁 + 物理收据。"

**Step Breakdown:**（同前：RED → GREEN → 门禁 → Reviewer → 证据 → 提交）

---

### Task 5: 真启闸加「无控制台语境」断言 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `tools/verify_windows_portable.py`（`:343 launch_server_only` / `:364 _creation_flags` 附近新增一个 mode）
- Test: 该脚本自身的回归测试（若有；否则以脚本退出码为收据）

**Interfaces:**
- Consumes: `launch_server_only(exe, log_path, env, mode)`、`_creation_flags(mode)`、`wait_until_ready`
- Produces: 新增 `mode == "no-console"`：以 `CREATE_NO_WINDOW`（0x08000000）启动 `--server-only`，断言 ① `/api/health` 就绪 ② 干净退出（或可终止）③ 数据目录生成 `lan-address.txt` ④ **日志里没有 traceback**（抓裸 print / stdout 崩溃）

**Injected Instincts:**
- [ ] `[Instinct: 闸只扩不缩]`：既有验包项（`.env` 闸、构建指纹、WebView2Loader.dll、commit 比对）不得放松。
- [ ] `[Instinct: 判据是产物不是 run 绿灯]`：以日志/traceback 断言为准。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 5: 真启闸加无控制台语境断言。Mode: AFK | Role: TDD Builder
> Steps: ① 先写失败断言（当前无此 mode ⇒ RED 或 NotImplemented）。② 在 `tools/verify_windows_portable.py` 增加 `no-console` 模式（CREATE_NO_WINDOW 启动 `--server-only`）+ 上述四项断言。③ 本地能跑的部分跑通；CI 专属部分确保 skip 语义正确（非 Windows 跳过而非假绿）。④ 门禁 + 物理收据。"

**Step Breakdown:**（同前）

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Unknown 1]**：`--windowed` 下**第三方库**（uvicorn / webview / spaCy）是否还有写 stdout 的路径 —— 由 Task 5 的"日志无 traceback"真跑断言兜底；若抓到，再补收口（不在本计划内预写）。
- **[Unknown 2]**：任务栏图标/分组的**实际观感**只能真机验证（HITL）；若仍归到 Python 组，需调整 AppUserModelID 的调用时机。
- **[Unknown 3]**：`lan-address.txt` 落点是"数据目录"还是"程序目录（便携态）"——当前按数据目录（可预测、与数据在一起）；若便携模式用户期望"就在 exe 旁边"，需你拍板后改一行。

## 🚫 Out of Scope

- **安装器 / 开始菜单 / 桌面快捷方式 / 开机自启** —— ADR-0019 已明确否决（卸载器会连 `_internal` 删走数据；LAN 面无鉴权时不该常驻）。
- **第二个 exe（debug 版控制台产物）** —— ADR-0020「不新增第 5 个产物位点」。
- **换 HTTP 主体** / 换语言 —— ADR-0018 / ADR-0021 已永久否决。
- 图标"重新设计品牌"（本次只把既有 manifest 品牌光栅化成 .ico，不新设计）。

## ✅ 验收（本批完成的定义）

1. `pytest` 全绿 + `ruff` + mypy 四档 + 前端契约闸；
2. 真启闸（含新增的 no-console 模式）在 CI 上绿；
3. **产物体积与构建时长重测**（`--windowed` + `.ico` 之后必须重测，不沿用 v5.17.0 的 85.8MB / 3–4min 旧数）；
4. 你真机双击确认：无黑框 + 品牌图标 + 失败有弹窗。
