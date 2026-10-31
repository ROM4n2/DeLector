# 桌面单实例与端口顺延 Implementation Plan

> **Goal**: 让「同一台机器上只能跑一个 DeLector 实例」成为 OS 级事实（文件锁），并把端口占用从「启动失败」变成「顺延到 8002–8010」。
> **Tech Stack**: Python 3.11 / FastAPI / uvicorn / pytest；Windows（`msvcrt`）+ POSIX（`fcntl`）。
> **Spec Reference**: `docs/specs/2026-10-21-desktop-single-instance-design.md`（APPROVED）；上游 ADR-0019 §6.4、ADR-0020 P0-1。
> **Global Constraints**:
> - 代码改动 MUST 走分支 + PR（`docs/agents/ops.md` 第 12 条）；本计划分支见下。
> - `delector/core/instance_lock.py` **不得**在模块级 import `database` / FastAPI。
> - 不得新增裸 `except: pass`（`tools/check_silent_degradation.py`）。
> - 面向用户的文案禁含堆栈与数据目录绝对路径以外的内部标识；`data_dir` **绝不**进任何 HTTP 响应（红线⑦同类）。
> - 验证一律 `PYTHONIOENCODING=utf-8`，tests 单进程串行（并行会争数据目录守卫造成假红）。
> **Branch**: `feat/desktop-single-instance`（从 `master@85fb029` 开，经 PR 合入）。
> **Repo Invariants Pointer**: `WORKMEMORY/PROJECT_OVERVIEW.md`（§红线速查）+ `docs/agents/ops.md`（第 12/13 条）。每个 subagent brief 引用这两个路径，**不重述**。

---

## ☑️ Decisions So Far

- 锁位置 = **全局** `%LOCALAPPDATA%\DeLector\`（ADR-0019 §6.4）；否决 per-data-dir（spec §0/§6）。
- 端口顺延 = **8000, 8002–8010**（跳过 8001：`agent/internal/pythonsvc/doc.go:9-10`）。
- 身份探测降为「锁不可用」时的第二腿；锁是唯一判据。
- **锁与元数据分两个文件**（plan 阶段发现的 POSIX 硬约束，已回写 spec §3.1）：
  `instance.lock` 只做 flock 目标、永不替换；`instance.json` 走临时文件 + `os.replace`。
  理由：`os.replace` 会把 fd 锁指向已 unlink 的旧 inode ⇒ 下一个进程能抢到锁，**锁静默失效**。
- `--port` 显式给定时**不顺延**（显式意图优先，最小惊讶）；自动模式才顺延。
- `--server-only` 复用 `start.main()` ⇒ 自动继承锁，无需单独接线。
- `lan-info` 端口来源改为 `app.state.server_port`，默认 8000（TestClient/Android 行为不变）；**不用** `request.url.port`（可被 `Host` 伪造）。

---

## ☑️ Active Frontier (Unblocked Tasks)

> **File-Occupancy**: 本计划**串行单分支执行**，无多 subagent 并发 ⇒ 每个任务对下表文件拥有独占窗口，任务结束时释放。禁止把两个任务派给并发 subagent。

| 文件 | 独占任务 |
| --- | --- |
| `delector/core/instance_lock.py`（新） | Task 1, 2 |
| `tests/test_instance_lock.py`（新） | Task 1, 2, 3 |
| `start.py` | Task 4, 6 |
| `tests/test_start.py` | Task 4, 6 |
| `tests/test_desktop_data_dir_bootstrap.py` | Task 5 |
| `desktop.py` / `tests/test_desktop_port_guard.py` | Task 7 |
| `delector/core/server_lifecycle.py` / `delector/routes/backup.py` / `tests/test_server_lan.py` | Task 8 |
| `docs/**`、`WORKMEMORY/**` | Task 9 |

---

### Task 1: 锁记录与元数据原子读写 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `delector/core/instance_lock.py`
- Test: `tests/test_instance_lock.py`

**Interfaces:**
- Consumes: `delector.core.data_dir_bootstrap`（仅用于对齐 env 读取风格，不调用）；`pathlib`、`json`、`os`。
- Produces:
  ```python
  @dataclass(frozen=True) class LockRecord: pid:int; version:str; port:int; data_dir:str; acquired_at:str
  @dataclass(frozen=True) class LockPaths:
      lock: str; meta: str
      @staticmethod
      def for_platform(env: Mapping[str,str]) -> "LockPaths"
  def read_record(paths: LockPaths) -> Optional[LockRecord]      # 缺失/半截/非 JSON ⇒ None
  def write_record(handle: "LockHandle", record: LockRecord) -> None   # 临时文件 + os.replace
  ```

**Injected Instincts:**
- [ ] `[Instinct: Atomic IO]`: 写 meta MUST 用 `tempfile.NamedTemporaryFile(dir=同目录, delete=False)` + `os.replace`；失败分支 `finally` 删临时文件。
- [ ] `[Instinct: Import Boundary]`: 模块顶层只允许 stdlib；**禁止** `delector.database`（Freeze DATA_DIR 风险）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 锁记录与元数据原子读写. Mode: AFK | Role: TDD Builder.
> Target: Create `delector/core/instance_lock.py`, Test `tests/test_instance_lock.py`.
> RED: 写 3 条测试 — (a) `write_record` 后 `read_record` 往返等值；(b) meta 是半截 JSON / 不存在 ⇒ `None`（不抛）；(c) `for_platform` 在 Windows env(`LOCALAPPDATA=C:\Users\x\AppData\Local`) / POSIX env(`HOME=/home/x`) 下返回 `<dir>/instance.lock` 与 `<dir>/instance.json`，且 **锁文件名永不等于 meta 文件名**。
> GREEN: 最小实现（dataclass + json + os.replace）。Refactor: guard clause 压平，最多 2 层缩进。
> Return: 摘要 + 强制物理回执（命令 + exit code + passed count）。"

**Step Breakdown:**
- [ ] Step 1: 写 `tests/test_instance_lock.py` 三条 RED
- [ ] Step 2: `python -m pytest tests/test_instance_lock.py -q` 确认失败（ModuleNotFoundError）
- [ ] Step 3: 最小实现（GREEN）
- [ ] Step 4: 重跑，全绿
- [ ] Step 5: REFACTOR（压平、去重复）
- [ ] Step 6: 物理回执（命令 + exit code + passed 数 + `git diff --stat`）
- [ ] Step 7: 原子提交到 `feat/desktop-single-instance`

---

### Task 2: 跨进程互斥原语 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/core/instance_lock.py`
- Test: `tests/test_instance_lock.py`

**Interfaces:**
- Consumes: Task 1 的 `LockPaths` / `LockRecord` / `read_record`。
- Produces:
  ```python
  @dataclass class LockHandle: paths: LockPaths; record: LockRecord; def release(self) -> None
  def try_acquire(paths: LockPaths, record: LockRecord) -> LockHandle | LockRecord
  ```
  语义：拿到锁 ⇒ `LockHandle`；被持有 ⇒ 对方 `LockRecord`（读不到 ⇒ `LockRecord(pid=0, version="unknown", port=0, data_dir="", acquired_at="")`）。

**Injected Instincts:**
- [ ] `[Instinct: OS Lock Semantics]`: Windows `msvcrt.locking(fd, LK_NBLCK, 1)` 前 MUST `seek(0)`；POSIX `fcntl.flock(fd, LOCK_EX|LOCK_NB)`。锁 fd 全程保持打开，`release()` 幂等。
- [ ] `[Instinct: Loud Degradation]`: 两种原语都不可用 ⇒ 仍返回 `LockHandle`，但 `logging.warning` 一次（文案含「本次不是真互斥」），**不静默**。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: 跨进程互斥原语. Mode: AFK | Role: TDD Builder.
> RED 4 条：(a) 两个独立 fd 顺序 `try_acquire` ⇒ 第二次返回第一条的 `LockRecord`（pid/version 一致）；(b) `release()` 后可再取，且重复 `release()` 不抛；(c) meta 被删/损坏但锁被持有 ⇒ 返回 unknown 记录且 pid==0；(d) `write_record` 后再 `try_acquire`（另一 fd）仍失败 —— 证明回写**没有**破坏锁（防 os.replace 失效回归）。
> GREEN: 实现 `try_acquire`/`release`/降级 warning。禁止 `except: pass`。
> Return: 回执（exit code + passed 数）。"

**Step Breakdown:**
- [ ] Step 1: 4 条 RED 测试
- [ ] Step 2: 验证失败
- [ ] Step 3: GREEN
- [ ] Step 4: 全绿
- [ ] Step 5: REFACTOR
- [ ] Step 6: 物理回执
- [ ] Step 7: 提交

---

### Task 3: 真子进程互斥验证 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Test: `tests/test_instance_lock.py`（追加一节 `# ── 跨进程（真 fork/spawn）──`）

**Interfaces:**
- Consumes: `subprocess.run([sys.executable, "-c", SCRIPT], env=...)`；`sys.executable`。
- Produces: 仅测试，无生产接口。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: 真子进程互斥验证. Mode: AFK | Role: TDD Builder.
> 测试内容：父进程用 `subprocess.Popen` 起一段内联脚本（`python -c`），子进程 `try_acquire` 后打印 `HELD <pid>` 并 `time.sleep(30)`；父进程等 `HELD` 读到后 `try_acquire` 必须失败且 pid 匹配；随后 `terminate()` 子进程、`wait()`，再试必须成功。
> 约束：超时上界 10s（`communicate(timeout=...)`），失败信息含子进程 stdout/stderr；不得使用裸 `sleep` 轮询超过 10 次。
> 理由：现有 desktop 测试全是 monkeypatch，盖不住真锁语义。Return: 回执。"

**Step Breakdown:**
- [ ] Step 1: 写测试（此时 Task 2 已实现 ⇒ 首跑即绿，**属预期**；本条不是 TDD 红灯，是「真进程语义」验证）
- [ ] Step 2: **变异自证**：临时把 `try_acquire` 改成直接返回 `LockHandle`（跳过 OS 锁），确认该用例**转红**；还原后复绿。回执需含两次 exit code
- [ ] Step 3: 记录耗时（应 < 5s）
- [ ] Step 4: 物理回执
- [ ] Step 5: 提交

---

### Task 4: `start.claim_instance` 单一判定点 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `start.py`（新增 `claim_instance` / `Ready` / `AlreadyRunning` / `PORT_CANDIDATES`；`is_port_in_use` 保持不动）
- Test: `tests/test_start.py`（新增用例类）

**Interfaces:**
- Consumes: `instance_lock.LockPaths.for_platform` / `try_acquire`；`data_dir_bootstrap.resolve_data_dir`；`version.APP_VERSION`；`start.is_port_in_use`。
- Produces:
  ```python
  PORT_CANDIDATES: tuple[int, ...] = (8000, 8002, 8003, 8004, 8005, 8006, 8007, 8008, 8009, 8010)
  @dataclass(frozen=True) class Ready: port: int; lock: instance_lock.LockHandle
  @dataclass(frozen=True) class AlreadyRunning:
      record: instance_lock.LockRecord; reason: str   # "unknown" | "version_mismatch" | "data_dir_mismatch" | "same"
  def claim_instance(env: Mapping[str,str], requested_port: Optional[int] = None) -> Ready | AlreadyRunning
  ```
  判定优先级：`unknown` > `version_mismatch` > `data_dir_mismatch` > `same`。
  `requested_port` 给定时**只试它**（占用 ⇒ 返回 `AlreadyRunning(record=unknown, reason="port_busy")` 的新 reason 值）。

**Injected Instincts:**
- [ ] `[Instinct: No Silent Fallback]`: 顺延必须写一条日志（`print` 到 stderr 或 logging），文案含「8000 被占用，改用 800X」。
- [ ] `[Instinct: Purity]`: 端口探测通过注入的 `probe` 参数（默认 `start.is_port_in_use`）以便测试，**不要** patch 全局。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 4: `start.claim_instance`. Mode: AFK | Role: TDD Builder.
> RED 6 条（monkeypatch `is_port_in_use` 与 `LockPaths.for_platform` 指向 tmp_path）：
> 1) 8000 空闲 ⇒ Ready(8000)。
> 2) 8000 占、8001 占、8002 空闲 ⇒ Ready(8002)（哨兵：**永不**选 8001）。
> 3) 8000–8010 全占 ⇒ AlreadyRunning(reason='no_free_port')。
> 4) 锁被持有且 version 不同 ⇒ reason='version_mismatch'，record 带对方版本。
> 5) 锁被持有且 data_dir 不同 ⇒ reason='data_dir_mismatch'。
> 6) `requested_port=9000` 且占用 ⇒ reason='port_busy'，**不**落到 9001。
> GREEN: 实现（顺序：resolve_data_dir → try_acquire → 选端口）。注意 target 端口在拿到锁之后才探测。
> Return: 回执（exit code + 6 passed）。"

**Step Breakdown:**
- [ ] Step 1: 6 条 RED
- [ ] Step 2: 验证失败
- [ ] Step 3: GREEN
- [ ] Step 4: 全绿（单测文件 < 3s）
- [ ] Step 5: REFACTOR（端口选择抽成 `_pick_port(probe, requested)`）
- [ ] Step 6: 物理回执
- [ ] Step 7: 提交

---

### Task 5: 启动顺序守卫放行 + 窄守卫 [Tier: 2-Standard] [Mode: HITL] [Role: Guard Editor]

> HITL：这条任务修改的是**既有安全闸**，需人工过目 diff 后再继续。

**Files:**
- Modify: `tests/test_desktop_data_dir_bootstrap.py:402-409`（`_is_delector_import` 白名单加 `delector.core.instance_lock`）
- Modify: `tests/test_desktop_data_dir_bootstrap.py`（新增 `test_instance_lock_module_does_not_import_database`）

**Interfaces:**
- Consumes: 现有 `_delector_imports` / `test_bootstrap_module_does_not_import_database_at_module_level`（:478）的断言写法。
- Produces: 无生产接口。

**注（必须写进测试注释）**：`test_start_py_bootstrap_precedes_every_delector_import` 取的是**全模块最小行号**，
而 `start.py:39` 的 `data_dir_bootstrap` 导入永远是最小值 ⇒ 新加的 `instance_lock` 导入**不会**让它变红。
加白名单是为了「意图显式」：下一个人看到 `instance_lock` 在 bootstrap 之前被导入，能查到这是批准过的例外。
**不要**把这条守卫改成「逐行比较」（会连带要求把 `probe_identity` 的惰性导入挪位置，超出本计划）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 5. Mode: HITL | Role: Guard Editor.
> 1) 在 `_is_delector_import` 的白名单里加 `delector.core.instance_lock`，注释写清「不 import database，可先于 bootstrap」。
> 2) 新增 `test_instance_lock_module_does_not_import_database`：读 `delector/core/instance_lock.py` 源码，断言模块级无 `import delector.database` / `from delector.database` / `from delector import database`。
> 3) 断言既有两条守卫仍绿：`python -m pytest tests/test_desktop_data_dir_bootstrap.py -q`。
> Return: 回执（命令 + exit code）。"

**Step Breakdown:**
- [ ] Step 1: 写新守卫测试（此时 `instance_lock.py` 已存在 ⇒ 首跑即绿，**属预期**）
- [ ] Step 2: **变异自证**：临时给 `instance_lock.py` 顶层加一行 `import delector.database`，确认新守卫**转红**；删掉后复绿（回执含两次 exit code）
- [ ] Step 3: 白名单 + 注释
- [ ] Step 4: 全文件绿（含原有 2 条顺序守卫）
- [ ] Step 5: HITL：把 diff 交给用户过目
- [ ] Step 6: 提交

---

### Task 6: `start.main()` 接线 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `start.py`（`main()` 内：`claim_instance` → 端口 → `bootstrap_data_dir` → serve；`finally` 释放锁）
- Test: `tests/test_start.py`

**Interfaces:**
- Consumes: `claim_instance`（Task 4）、`bootstrap_data_dir(env)`、`on_serving` 回调（既有）。
- Produces: `main(argv: Optional[list[str]] = None, on_serving: Optional[Callable[[int], None]] = None) -> None`（签名不变）。

**Injected Instincts:**
- [ ] `[Instinct: In-Process Lock Leak]`: 测试在**同进程**里调 `main()` ⇒ MUST 在 `finally` 调 `lock.release()`，否则后续用例全被误判为「已在运行」（假红）。
- [ ] `[Instinct: Ordering]`: `claim_instance` 调用 MUST 出现在 `bootstrap_data_dir` **之前**；`from delector.server import app` 保持现状位置（更晚）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 6. Mode: AFK | Role: TDD Builder.
> RED 3 条：(a) `main()` 在锁被持有（version 不同）时不 import `delector.server`、退出码 1、stderr 含双方版本；(b) 8000 被无关程序占 ⇒ `on_serving` 收到 8002（用 monkeypatch 注入 claim 结果的替代：patch `start.claim_instance`）；(c) `main()` 正常结束（KeyboardInterrupt）后同进程可再次 `try_acquire`（证明 finally 释放）。
> GREEN: 接线。AlreadyRunning 文案：`same` ⇒ 「DeLector 已在运行（v{ver}，pid {pid}），端口 {port}」+ 打开浏览器；其余 ⇒ 说明差异并 exit 1。
> 约束：不新增裸 except；类型注解齐全（mypy --strict 覆盖 start.py）。
> Return: 回执。"

**Step Breakdown:**
- [ ] Step 1: 3 条 RED
- [ ] Step 2: 验证失败
- [ ] Step 3: GREEN
- [ ] Step 4: `python -m pytest tests/test_start.py tests/test_start_lifecycle.py -q` 全绿
- [ ] Step 5: `python -m mypy --strict start.py`
- [ ] Step 6: 物理回执
- [ ] Step 7: 提交

---

### Task 7: 桌面壳接线 [Tier: 3-Critical] [Mode: HITL] [Role: TDD Builder]

> Critical：改动 pywebview 启动主链与退出码契约，需人工确认「弹窗文案 + 退出码 + 锁释放」三件事。

**Files:**
- Modify: `desktop.py`（`_parse_args` 默认 `None`；`run_desktop(port: Optional[int] = None, ...)`；`_run_desktop_inner(port, log_path)` 首步 claim；`dispatch` 的 `--server-only` 警告条件；`_check_port_or_fail` 移除或改为薄包装）
- Test: `tests/test_desktop_port_guard.py`

**Interfaces:**
- Consumes: `start.claim_instance`（惰性 import，沿用 `desktop.py:887` 既有注释的理由）、`write_crash`、`_append_log`。
- Produces: `run_desktop(port: Optional[int] = None, debug_console: bool = False) -> int`；`_run_desktop_inner(port: Optional[int], log_path: str) -> int`。
  端口语义：`None` = 自动（8000 起顺延）；整数 = 用户显式指定（不顺延）。
  退出码不变：0 正常 / 1 就绪超时或异常 / 2 缺 WebView2 / 3 端口或实例冲突。

**Injected Instincts:**
- [ ] `[Instinct: Backward Compat]`: 既有测试以 `_run_desktop_inner(8000, log)` 位置参数调用 ⇒ 保持位置参数顺序不变；`run_desktop(port=8000)` 语义变为「显式 8000」，与这些用例的意图一致。
- [ ] `[Instinct: No Stack In UI]`: 弹窗只给人话（版本、pid、数据目录、日志路径），traceback 只进 launch.log。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 7. Mode: HITL | Role: TDD Builder.
> RED 5 条：(a) 锁被持有(reason='same') ⇒ 返回 3、弹窗文案含 pid 与版本、**不**调用 build_server；(b) reason='version_mismatch' ⇒ 返回 3、文案含双方版本；(c) 自动模式 8000 占 ⇒ build_server 收到 8002（patch claim 返回 Ready(8002)）；(d) 显式 `run_desktop(port=8000)` 且占用 ⇒ 返回 3（不顺延）；(e) `_run_desktop_inner` 所有返回路径后锁可用（同进程二次 try_acquire 成功）。
> GREEN: 接线，保留 `--server-only` 走 start.main 的既有路径（不要在 dispatch 里再加锁）。
> Refactor: 失败文案抽成一个 `_describe_holder(record, reason) -> str`，避免四处复制。
> Return: 回执（5 passed + mypy）。"

**Step Breakdown:**
- [ ] Step 1: 5 条 RED
- [ ] Step 2: 验证失败
- [ ] Step 3: GREEN
- [ ] Step 4: `python -m pytest tests/test_desktop_port_guard.py tests/test_desktop_shell.py tests/test_desktop_window_lifecycle.py tests/test_desktop_tray_exit.py -q`
- [ ] Step 5: `python -m mypy --strict desktop.py splendid`（按仓库既有 mypy 目标；若 desktop 不在目标内则跑全套 `--strict delector tools`）
- [ ] Step 6: HITL：呈交 3 条弹窗文案 + 退出码表给用户确认
- [ ] Step 7: 提交

---

### Task 8: `lan-info` 真实端口 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/core/server_lifecycle.py:55-71`（`build_server` 内 `app.state.server_port = port`，用 `getattr(app, "state", None)` 保护）
- Modify: `delector/routes/backup.py:179`（`"port": getattr(request.app.state, "server_port", 8000)`）
- Test: `tests/test_server_lan.py`

**Interfaces:**
- Consumes: `uvicorn.Config(app, ...)` 既有装配。
- Produces: `build_server(host, port, app) -> uvicorn.Server`（签名不变，副作用新增 `app.state.server_port`）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 8. Mode: AFK | Role: TDD Builder.
> RED 2 条：(a) `client.app.state.server_port = 8007` ⇒ `/api/wb/lan-info` 的 `port` 字段为 8007；(b) 不设 state ⇒ 仍为 8000（兼容 TestClient/Android）。
> GREEN: 两处各改一行。断言 `build_server` 也写入（用 `delector.server.app` 建 server 再读 state）。
> Return: 回执（2 passed）。"

**Step Breakdown:**
- [ ] Step 1: 2 条 RED
- [ ] Step 2: 验证失败
- [ ] Step 3: GREEN
- [ ] Step 4: `python -m pytest tests/test_server_lan.py tests/test_start_lifecycle.py -q`
- [ ] Step 5: 物理回执
- [ ] Step 6: 提交

---

### Task 9: 文档同步 [Tier: 1-Light] [Mode: AFK] [Role: Docs]

**Files:**
- Modify: `docs/agents/architecture.md`（新增「桌面单实例与端口」小节：锁路径、端口表 8000/8001/8002–8010、`--port` 不顺延）
- Modify: `docs/agents/ops.md`（本机环境：`%LOCALAPPDATA%\DeLector\instance.lock` 排障入口）
- Modify: `WORKMEMORY/PROJECT_OVERVIEW.md`（开放待办：删除该条 / 标已交付）+ `WORKMEMORY/work.log`（DECISION 事件）

**Interfaces:** Consumes: spec/plan 路径。Produces: 无。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 9. Mode: AFK | Role: Docs.
> 只改上述 4 个文件；`grep -c "8001"` 确认端口表把 8001 标为 supervisor 保留；`grep -n "instance.lock"` 三个文件都能命中。Return: grep 回执 + diff stat。"

**Step Breakdown:**
- [ ] Step 1: 四处文档编辑
- [ ] Step 2: grep 回执（非空）
- [ ] Step 3: 提交（纯文档，可直接进 PR 同一个 commit 序列）

---

### Task 10: 全闸验证与 PR [Tier: 2-Standard] [Mode: HITL] [Role: Integrator]

**Files:** 无代码改动（仅修红）。

**Interfaces:** Consumes: 全部前置任务。Produces: PR。

**Step Breakdown:**
- [ ] Step 1: `PYTHONIOENCODING=utf-8 python -m pytest tests/ -q`（期望：2517 + 新增 ≈ 23 passed / 0 failed）
- [ ] Step 2: `ruff check .`
- [ ] Step 3: `python -m mypy --strict delector tools` + `python -m mypy --follow-imports=skip tests`
- [ ] Step 4: 六道闸：`check_layer_invariants` / `check_mock_drift` / `check_silent_degradation` / `check_frontend_api_contract` / `check_frontend_layers` / `check_index_html_sync`
- [ ] Step 5: 真双启动手测（HITL）：桌面双击两次、`python start.py` 在桌面实例运行时、8000 被占时顺延、`--port 9000` 被占时报错
- [ ] Step 6: `gh pr create`（标题 `feat: desktop single-instance lock and port fallback`），body 引用 spec + 本计划
- [ ] Step 7: PR 由用户 review 后合入（**不**自行 merge）

---

## ☁️ Fog of War (Not Yet Specified)

无。spec §6 已把全部未知收敛为决定或明确不做；本计划无待上游毕业的条目。

---

## ☑️ Deferred Gap Register

| gap | why deferred | trigger that forces revisiting | owner |
| --- | --- | --- | --- |
| 已有实例时把窗口提到前台 | 需 Win32 `FindWindow`/`SetForegroundWindow` 与窗口标题契约，属另一能力线 | 用户反馈「双击没反应 / 窗口找不到」成为重复投诉 | 桌面壳后续立项 |
| Go supervisor（8001）不受锁保护 | 牵动崩溃退避与预算闸，本次不碰 | 出现「supervisor 与桌面实例同库并发导致数据损坏」的证据 | agent 服务线 |
| `is_port_in_use` 单次 ~2s | ADR-0018 Unknown 8 的独立议题 | 冷启动时延成为用户可感知投诉 | ADR-0018 计划 |
| per-data-dir 多实例（便携版+安装版并存） | YAGNI，会引入双窗口/双库/双托盘 | 用户明确要求两版并存 | 新 spec |
| `probe_identity` 只比 `app` 不比版本 | 既有契约，收紧会波及 `await_ready` 与桌面壳 | 出现「身份对但版本错」的真实误判 | ADR-0020 后续 |

---

## ☑️ Out of Scope

- 窗口激活 / 单例转发（见 gap 表）。
- Go supervisor 加锁、`pythonsvc` 端口改造。
- `is_port_in_use` 探测成本优化、spaCy 冷启动提速。
- Android（`bootstrap_data_dir` 返回空串时 `claim_instance` 直接 `Ready(8000)`，不取锁）。
- 前端任何改动。

---

## Deviation Table (fill before merge)

| plan text | what was actually built | why |
| --- | --- | --- |
| 执行顺序 Task 4 → Task 5 | **Task 5 先于 Task 4** | `test_start_py_bootstrap_precedes_every_delector_import` 取全模块最小行号：`start.py` 顶层一旦新增 `delector.core.instance_lock` 导入，最小值就从 `main()` 内的 309 掉到 ~44 ⇒ Task 4 必须先拿到 Task 5 的白名单放行，否则它的「全绿」验收物理上不可达。 |
| Task 6 Interfaces：`main(argv, on_serving)` | `main(debug_console, on_serving)`（**未改签名**） | 计划该行是笔误：仓库实际签名与全部调用方都是 `debug_console` 版本，按「签名不变」执行。 |
| Task 7「`_check_port_or_fail` 移除或改为薄包装」 | 保留函数名，改成 `claim_instance` 的薄封装（出参 dict 交出 port/lock） | 两处 AST 守卫以该函数名为锚（`test_desktop_window_lifecycle.py` 的阶段标记夹逼、`test_desktop_port_guard.py` 的跨函数顺序）。改名会让守卫**找不到锚点**，属"判据失效"而非"实现变更"。 |
| （未写）`APP_VERSION` 的取法 | `start.py::_app_version()` 惰性导入，且**定义在 `main()` 之后** | 同上那条顺序守卫：`delector.core.version` 不在 `_BOOTSTRAP_SAFE_IMPORTS` 白名单，模块级导入会让最小值下移。**已登记技术债**：把 `delector.core.version` 加进白名单，让该 helper 回到 `claim_instance` 旁边（当前规避手法依赖行号算术，脆弱）。 |
| Task 9 只提「四处文档编辑」 | 另改两个测试的文件形状（**不放宽断言**） | ① `tests/server_helpers.py` 新增 `stmts_through_try`：Task 7 用 `try/finally` 放锁后阶段标记下沉一层，且容器自身会因子树包含调用而误命中锚点；② `tests/test_desktop_shell.py` 两条用例原靠 patch `is_port_in_use` 拦启动，判定点换成锁后桩失效 ⇒ 真起服务**挂死**（实测 pytest 超时 124），改到 `claim_instance`。 |
| （未写）`check_mock_drift` | 3 处 `mock-drift-ok` 豁免 | 闸判据只看"目标模块内部是否还引用该符号"，而 `LockPaths.for_platform` 的消费方在 `start.py::claim_instance`（跨模块、调用期类属性查找）⇒ 属误报。豁免行逐行可审。 |

---

## Ledger

仓库内**没有** `scripts/vault_exec_state.py`（该脚本不在本仓）。交接方式：
`/dfs-exec` 按 `.vault-exec-ledger.json` 既有 schema（`version/plan_file/tasks[id,title,status,...]`）写入，
`plan_file` = `docs/plans/archive/2026-10-21-desktop-single-instance.md`，共 10 个任务。
