# Windows 无控制台后的反馈缺口 Implementation Plan

> **Goal**: 修掉 `/dfs-team` 三席审计（2026-10-14，怀疑者复核后）开出的 7 条发现——核心是"**无控制台之后，用户在失败与等待时还能不能得到人话反馈**"：一条零线索的静默崩溃路径、两处不对称的失败出口、一段没有任何可见反馈的冷启动，以及一道判据瞄错了对象的闸。
> **Tech Stack**: Python 3.11 / pywebview(EdgeChromium) / pystray / PyInstaller(`--windowed`) / pytest / ctypes(Win32)。
> **Spec Reference**: `/dfs-team` 评估报告（2026-10-14，靶子 = 提交 `0f7b80f..b05a367`「Windows 去控制台 + 桌面化观感」）；上一轮计划 `docs/plans/2026-10-13-windows-no-console-desktop-polish.md`。
> **Global Constraints**:
> - **零新依赖**：只用既有设施（`_message_box` / `write_crash` / `_append_log` / `ensure_streams`）。
> - **启动顺序改动 MUST 先写死锁回归再动码**：`desktop.py` 有 P0 先例——`evaluate_js`/`load_url` 在 `webview.start()` 之前调用 ⇒ 窗口永不出现（永久等待，不报错）。任何把工作搬进/搬出事件循环的改动，先有一条测试钉住"循环启动前不碰窗口"。
> - **失败必须可见（本批存在的理由）**：任何失败分支 MUST 落到 `launch.log` + 原生弹窗 + 托盘三处中的至少两处；禁止"静默退出、零字节线索"。
> - **门禁不削弱**：`ruff check .` / mypy 四档 / `pytest` 全绿；既有断言只扩不减。
> - **分支纪律（2026-10-14 新增的规矩）**：本计划与其执行同走一个分支 `fix/no-console-feedback-gaps`，最后**一个 PR** 合入 master（实现任务不直推 master）。
> - **每任务物理证据**（原始命令 + 退出码 + 计数 + diff stat）；Tier 1 也不例外。

---

## 🏛️ Decisions So Far

- **怀疑者推翻的两条（直接影响修法，先记住）**：
  1. **CPython 的 `print()` 在 `sys.stdout is None` 时是静默 no-op，不会崩**（builtin print 显式 `if file is None: return`）。⇒ 上一轮写在 `tools/verify_windows_portable.py:38` 与 `:586` 的"裸 print 即崩"是**错误前提**；真会崩的是 `None.write`（即本次 P1-1 的 argparse 路径）。所以 no-console 闸扫 traceback 抓不到那类回归不是"不够严"，是**判据从一开始就瞄错对象**。
  2. **桌面路径的 `lan-address.txt` 是安全的**：`_check_port_or_fail`（调用点 `desktop.py:874`，函数体 :833-867）在 `write_lan_address`（`:890`）**之前** ⇒ 端口被占时直接 `return 3`，走不到写地址。只有 `--server-only` 路径（`:999` 写 → `start.py:136` 才查端口）真会留下错误地址。
- **其余三条 P1 经怀疑者 CONFIRMED**（参数解析早于收口 / 失败出口不统一 / splash 未覆盖冷启动前段 4~6.5s），最小修法与怀疑者给的一致。
- **`--server-only` 地址弹窗（产品席建议"成功时弹一次可复制地址"）暂不做**：属新增行为而非修缺陷，留 Fog of War 待你拍板。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: 入口序列改成「先收口后解析」（P1：唯一零线索崩溃路径）[Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `desktop.py:1005-1007`（`__main__`）、`start.py:219-222`（`__main__`）
- Test: `tests/test_desktop_shell.py`（入口序列的 None 注入回归，风格对齐该文件既有 `_RecordingCtypes` / `_run_with_missing_streams` 设施）

**Interfaces:**
- Consumes: `ensure_streams(log_path: str, debug_console: bool = False)`（既有，`:365-368` 只补 `None` 流、有终端不接管）、`resolve_log_path(env)`（既有）
- Produces: 两个入口都变成"**先 `ensure_streams`，后 `_parse_args`**" ⇒ `sys.stdout/stderr is None` 时 argparse 的 `file.write` 不再 `AttributeError`；`--help` 与错参文本落 `launch.log`，退出码保持 argparse 既有语义（错参仍非零）

**Injected Instincts:**
- [ ] `[Instinct: 先 RED 后 GREEN]`：先用 `sys.stdout=sys.stderr=None` + `_parse_args(["--help"])` / `["--bogus"]` 造 RED（当前必炸），再改入口顺序。
- [ ] `[Instinct: 只补 None]`：`ensure_streams` 不得接管 pytest 捕获流/真实终端（既有语义，不许改）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 入口先收口后解析。Mode: AFK | Role: TDD Builder
> Steps: ① 在 `tests/test_desktop_shell.py` 写失败测试：monkeypatch `sys.stdout/sys.stderr=None`，直接调两个模块的 `_parse_args(["--help"])` 与 `_parse_args(["--bogus"])`，断言**不抛**且 help/错误文本进了临时 `launch.log`（当前会 `AttributeError` ⇒ RED）。② 改 `desktop.py` / `start.py` 的 `__main__`：把 `ensure_streams(resolve_log_path(os.environ), "--debug-console" in sys.argv[1:])` 提到 `_parse_args` 之前。③ 确认 GREEN。④ 回报物理收据（含 RED 原文）。"

**Step Breakdown:**（RED → 期望报错 → GREEN → 门禁 → Reviewer → 证据 → 提交）

---

### Task 2: 失败出口统一（P1：切主窗异常静默 vs 外层原样弹 traceback）[Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `desktop.py:766-770`（`_after_start` 异常分支）、`desktop.py:933-935`（`write_crash` 调用点的 detail 文案）
- Test: `tests/test_desktop_shell.py`（两条失败出口各一条：弹窗必须出现、日志必须含堆栈）

**Interfaces:**
- Consumes: `write_crash(title, detail, log_path)`（既有，`:406` = `_append_log` + `_message_box`）
- Produces:
  - `_after_start` 异常分支改为 `write_crash("DeLector 启动失败", traceback.format_exc(), log_path)`（日志全栈 + 弹窗），再走既有 `_abort_windows`；
  - 外层 `:933-935` 的弹窗 detail 从"完整 traceback"改为"**启动失败，详情见 `launch.log`（路径一并给出）**"，traceback 只落盘；
  - 两条出口最终行为一致：**日志全栈 + 弹窗一句话**

**Injected Instincts:**
- [ ] `[Instinct: 不造第三种出口]`：统一复用 `write_crash`，不新增弹窗封装。
- [ ] `[Instinct: 弹窗不许吐栈]`：面向用户的文案禁止包含 traceback（排障信息只在 `launch.log`）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: 统一失败出口。Mode: AFK | Role: TDD Builder
> Steps: ① 写失败测试（monkeypatch 让 `_after_start` 内的窗口调用抛异常）：断言 `_message_box` 被调用且 `launch.log` 含 `Traceback`；再写一条断言外层失败的弹窗文案**不含** `Traceback` 但日志含。② 改 `desktop.py:766-770` 走 `write_crash`、`:933-935` 改文案。③ 确认 GREEN。④ 物理收据。"

**Step Breakdown:**（同上结构）

---

### Task 3: splash 覆盖冷启动前段（P1：首次双击 4~6.5s 零反馈）[Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `desktop.py`（`_run_desktop_inner` 约 `:874-900` 的阶段顺序与 `_after_start`）
- Test: `tests/test_desktop_shell.py`（**先写死锁回归** + 阶段顺序断言）

**Interfaces:**
- Consumes: `_show_window` / `_after_start` / `webview.start()` / `_check_port_or_fail` / `write_lan_address` / `build_server` / `serve_in_thread`
- Produces: 把 `:892-897`（`from delector.server import app` / `build_server` / `serve_in_thread`）**搬进 `_after_start`**（即 `webview.start()` 调度的事件循环之内、splash 已可见之后）⇒ 用户可见反馈的起点从"重活全干完"提前到"splash 出现"；端口校验（`:874`）与 WebView2 检测（`:878`）留在循环外（它们快且有弹窗）
- **硬约束**：`webview.start()` 之前**不得**调用任何窗口 API（既有 P0 死锁，`desktop.py:727` 一带的注释是判据）；搬进去的代码不得在循环内抛未接异常

**Injected Instincts:**
- [ ] `[Instinct: P0-死锁回归先行]`：先加一条"循环启动前不碰窗口/不调 `evaluate_js`"的结构或行为断言（RED→GREEN），再动顺序；若既有测试已覆盖则点名复用它，不许"我觉得不会死锁"。
- [ ] `[Instinct: 提前 create_window 无效]`：窗口由 `webview.start()` 才建 ⇒ 不许用"把 `create_window` 提前"充数。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: splash 提前覆盖冷启动前段。Mode: AFK | Role: TDD Builder
> Steps: ① 先写/点名死锁回归（循环启动前碰窗口 ⇒ 红）。② 写阶段顺序断言（`build_server` 的调用点在 `_after_start` 内 / 或等价可测性质）。③ 把 `:892-897` 搬进 `_after_start`。④ 跑 `tests/test_desktop_shell.py` + 全量。⑤ 物理收据（含 RED 原文）。"

**Step Breakdown:**（同上结构）

---

### Task 4: no-console 闸判据改 AST 结构守卫 + 修正两处错误注释（P2）[Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `tests/test_ci_hardening.py` 或 `tests/test_desktop_shell.py`（新增 AST 守卫）、`tools/verify_windows_portable.py:38` 与 `:586`（注释）
- Test: 同文件（变异自证：在 `ensure_streams` 之前插一个无 `file=` 的 `print` ⇒ 守卫必须红）

**Interfaces:**
- Consumes: `desktop.py` / `start.py` 的 AST（既有 AST 守卫先例：`tests/test_ci_hardening.py` 的 `ast` 用法、`test_desktop_shell.py` 的 `_parse_desktop`）
- Produces:
  - 守卫：`desktop.py` 与 `start.py` 中，位于 `ensure_streams` 调用点**之前**的模块级/函数级代码里，不得出现无 `file=` 关键字参数的 `print(...)` 或 `sys.stdout.write(...)`；
  - `tools/verify_windows_portable.py:38`、`:586` 的注释改写为事实：**Py3 的 `print()` 对 `None` stdout 是静默 no-op；真会崩的是 `None.write`（argparse 的 `file.write` 路径）**，并说明这道闸为何扫不到那类回归（子进程 stdout 被重定向 ⇒ 标准流并非 `None`）

**Injected Instincts:**
- [ ] `[Instinct: 注释即契约]`：错误注释比没有注释更糟（它会成为后人的"依据"）；改写必须给出事实与出处（CPython builtin print 行为）。
- [ ] `[Instinct: 变异自证必做]`：临时在被保护位置插一个裸 `print` ⇒ 守卫必须转红，复原后转绿（仓库外备份 + md5 复核）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 4: AST 结构守卫 + 修错误注释。Mode: AFK | Role: TDD Builder
> Steps: ① 写 AST 守卫（先 RED：当前没有守卫 ⇒ 用'临时插入裸 print'的方式证明它该红）。② 改 `verify_windows_portable.py:38`、`:586` 两处注释为事实陈述。③ 变异自证（插入 ⇒ 红；复原 ⇒ 绿）。④ 门禁 + 物理收据。"

**Step Breakdown:**（同上结构）

---

### Task 5: `--server-only` 的 `lan-address.txt` 写入时机 + 闸校验内容（P2）[Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `desktop.py:997-1002`（`dispatch` 的 server-only 分支）、`tools/verify_windows_portable.py`（`lan_address_state` 约 `:601` 的判据）
- Test: `tests/test_desktop_shell.py`（端口被占 ⇒ 不留地址文件）、`tests/test_verify_windows_portable.py`（判据升级）

**Interfaces:**
- Consumes: `run_server_only` / `start.main` / `is_port_in_use`、`lan_address_state(data_dir, log_text)`
- Produces:
  - `--server-only` 路径的地址写入**挪到服务真正持有端口之后**（由 `start.main()` 在 `build_server` 成功后回调写，或等价机制）；端口被占 / 退出时**删除**已写文件；
  - 桌面路径（`:890`）不变（已被证明安全：`:874` 端口校验在前）；
  - 闸判据从"文件存在"升级为"内容匹配 `^http://<IPv4>:<port>$`"（空文件/垃圾内容 ⇒ 红）

**Injected Instincts:**
- [ ] `[Instinct: 不许把写入提前到所有权之前]`：对外可见的"地址/端口"类文件，MUST 在本进程确认持有该端口后写。
- [ ] `[Instinct: 闸要校验内容不只是存在]`：`is_file()` 类判据对"空文件/错内容"零判别力。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 5: 地址写入时机 + 闸判据。Mode: AFK | Role: TDD Builder
> Steps: ① RED：端口被占时 `--server-only` 仍写地址文件（现在就会）；闸对空文件判 PASS。② 实现：写入移到端口持有之后 + 失败删除；闸判据改内容匹配。③ GREEN + 变异自证（把文件清空 ⇒ 闸必须红）。④ 物理收据。"

**Step Breakdown:**（同上结构）

---

### Task 6: 测试卫生（P2：三条污染真实数据目录 + 一条恒绿）[Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `tests/test_desktop_shell.py`（约 `:1222` / `:1241` / `:1262` 三条 dispatch 用例；`:1700-1704` 恒绿用例）

**Interfaces:**
- Consumes: 既有 `tmp_path` / `monkeypatch.setenv("DELECTOR_DATA_DIR", ...)` 惯例（同文件 :1289/:1335/:1437 已在用）、`_RecordingCtypes`（同文件 :1730 一带）
- Produces:
  - 三条 dispatch 用例全部隔离到 `tmp_path`（或加 autouse fixture 全局钉住，防后续新增再漏）；
  - `test_ms_since_process_create_returns_none_off_windows` 改用记录型假 `ctypes`：`sys.platform="linux"` 下断言 `touched == []`（删掉 `desktop.py` 的平台守卫必须转红）

**Injected Instincts:**
- [ ] `[Instinct: 测试不许碰真实落点]`：凡会写数据目录的路径，MUST 用 `DELECTOR_DATA_DIR` 指向 `tmp_path`。
- [ ] `[Instinct: 自证过承诺的用例=恒绿]`：声称"不许碰 X"就必须能在"碰了 X"时转红。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 6: 测试卫生。Mode: AFK | Role: TDD Builder
> Steps: ① RED：恒绿用例在'删掉平台守卫'的临时变异下必须转红（先证明它现在不红）。② 修三条隔离 + 改恒绿用例。③ GREEN + 变异自证（守卫删掉 ⇒ 红；复原 ⇒ 绿）。④ 物理收据。"

**Step Breakdown:**（同上结构）

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Unknown 1]**：Task 3 的 splash 方案**真实收益需真机验证**（HITL：双击后多久出现 splash）；PyInstaller 原生 `--splash` 资源是另一条路（可覆盖解释器启动段），未评估、未立项。
- **[Unknown 2]**：no-console 闸在 CI 上能否**真的**造出 `sys.stdout is None`（`Popen(stdout=None)` 时子进程继承父进程句柄 ⇒ 未必为 None，怀疑者标 UNVERIFIED）⇒ 需实测后才能决定"是否还要改闸的重定向方式"；在此之前只做 Task 4 的 AST 守卫（不依赖该机制）。
- **[Unknown 3]**：`--server-only` 成功时"弹一次可复制地址"的信息窗（产品席建议）——属新增行为，待你拍板；本计划只修"错文件 + 闸判据"。

## 🚫 Out of Scope

- **Android 真机覆盖安装点检**、**发版（v5.18.0）**、PyInstaller `--splash` 资源。
- `lan-address.txt` 落点从"数据目录"改"程序目录"（便携态）——需你拍板，当前维持数据目录。
- 上一批 10-13 的 9 个提交本身**不回滚**（CI 全绿、已推送；重写收益低风险高）。

## ✅ 验收（本批完成的定义）

1. `pytest` 全绿（当前基线 **1814 passed + 2 skipped**，新增用例逐条计数对得上）+ `ruff check .` + mypy 四档；
2. 每条 P1 都有"用户不再看到静默失败"的可验证判据（弹窗断言 / 顺序断言 / 阶段断言）；
3. Task 4 / 5 / 6 各带**变异自证**（临时破坏 ⇒ 红；复原 ⇒ 绿，仓库外备份 + md5）；
4. **一个 PR**（`fix/no-console-feedback-gaps` → `master`）合入，CI 全绿后合并（合并 MUST 等 CI 绿）；
5. no-console 步在真实 Windows 产物上的首次执行结果（run `38433233079`）已核对，并作为 Task 4/5 的输入。
