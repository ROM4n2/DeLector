# DeLector 统一智能体启动器实施计划 (Unified Agent Launcher)

> **Goal**: 让用户在终端仅需执行 `python start.py` 即可自动拉起并全生命周期托管 Go 伴学 Agent (端口 8002)，并在主服务退出时优雅收尸，杜绝孤儿进程与端口冲突。
> **Tech Stack**: Python 3.11+, Go 1.24+ / 1.26, subprocess, httpx
> **Spec Reference**: `docs/adr/2026-10-31-adr-0025-companion-agent-native-tool-calling-and-streaming.md` · `hybrid-agent-runtime`
> **Global Constraints**: Zero innerHTML, 测试绝不出网（100% Mock / httptest 隔离）, 四道机械门禁 100% 全绿，优雅退出收尸超时上限 5s。
> **Branch**: `feat/unified-agent-launcher`

---

## [NOTE] Decisions So Far
- [ADR-0020 / ADR-0025](docs/adr/2026-10-31-adr-0025-companion-agent-native-tool-calling-and-streaming.md): Go 伴学 Agent 独立监听 8002 端口，FastAPI 作为反代网关。
- [P0-2 退出路径收口规范](docs/reviews/2026-10-16-open-items-backlog.md): 子进程与线程退出必须带显式有界超时与收尸保障，严禁遗留孤儿进程。

---

## [NOTE] Active Frontier (Unblocked Tasks)

### Task 1: GoAgentSupervisor 核心托管器与单元测试 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `delector/core/go_agent_supervisor.py`
- Test: `tests/test_go_agent_supervisor.py`

**Interfaces:**
- Produces: 
  - `class GoAgentSupervisor`:
    - `find_agent_command() -> Optional[List[str]]` (探测 precompiled `agent/delector.exe` 或 `go run ./cmd/delector agent`)
    - `start() -> bool` (异步/子进程拉起，轮询 `/api/companion/health` 并在 5s 宽限期内探活)
    - `stop() -> None` (向子进程发送 SIGTERM / terminate，并在 5s 内回收收尸)
    - `is_running() -> bool`
    - `is_healthy() -> bool`

**Injected Instincts:**
- [ ] `[Instinct: Process Supervision]`: 捕获子进程 PID；优雅退出时先 terminate 后有界 wait，超时则强制 kill；严禁僵尸进程。
- [ ] `[Instinct: Android Safety]`: 在 Android Chaquopy 或未装 Go 的机器上，静默安全返回 False，不抛未捕获异常。

**Subagent Prompt Scaffold:**
> "Implement Task 1: GoAgentSupervisor in delector/core/go_agent_supervisor.py.
> Mode: AFK | Role: TDD Builder
> Goal: Manage the lifecycle of the Go companion agent child process with bounded health checks and reliable termination.
> Target Files: Create delector/core/go_agent_supervisor.py, Test tests/test_go_agent_supervisor.py.
> TDD Steps:
> 1. Write failing tests covering command discovery, health polling, and stop cleanup in tests/test_go_agent_supervisor.py (RED).
> 2. Implement minimal GoAgentSupervisor in delector/core/go_agent_supervisor.py (GREEN).
> 3. Verify exit 0 with pytest tests/test_go_agent_supervisor.py.
> Return: Summary with Physical Execution Receipt."

**Step Breakdown:**
- [ ] **Step 1: Write failing test in `tests/test_go_agent_supervisor.py` (RED)**
- [ ] **Step 2: Run test and verify failure**
- [ ] **Step 3: Implement `delector/core/go_agent_supervisor.py` (GREEN)**
- [ ] **Step 4: Run tests and verify all green**
- [ ] **Step 5: Physical Evidence Gate**: `pytest tests/test_go_agent_supervisor.py -v` 退出码 0。
- [ ] **Step 6: Git atomic commit**

---

### Task 2: 集成入 `start.py` 启动器与生命周期收尾 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `start.py:530-590`
- Test: `tests/test_start_agent_integration.py`

**Interfaces:**
- Consumes: `GoAgentSupervisor`
- Produces: 
  - 在 `start.py` 的 `main()` 中，非 Android 且未传入 `--no-agent` 时拉起 `supervisor.start()`；
  - 打印友好提示：`[伴学] Go Agent 伴学服务已自动托管启动 (http://127.0.0.1:8002)` 或 `[伴学] 未检测到 Go 环境，伴学功能由 Python 内核自适应兜底`；
  - 在退出 `finally` 块中加入 `supervisor.stop()`，主服务 Ctrl+C 退出时自动干净收尸。

**Injected Instincts:**
- [ ] `[Instinct: Clean Exit Chain]`: 退出链注入在 `finally` 中，保证无论正常停止还是异常崩溃，Go 子进程均被安全终止。

**Subagent Prompt Scaffold:**
> "Implement Task 2: Integrate GoAgentSupervisor into start.py.
> Mode: AFK | Role: TDD Builder
> Goal: Wire supervisor into start.py main() lifecycle, add --no-agent argument, and ensure child process termination in finally block.
> Target Files: Modify start.py, Test tests/test_start_agent_integration.py.
> TDD Steps:
> 1. Write failing integration test in tests/test_start_agent_integration.py (RED).
> 2. Modify start.py to initialize, start, and stop GoAgentSupervisor (GREEN).
> 3. Verify exit 0 with pytest tests/test_start_agent_integration.py.
> Return: Summary with Physical Execution Receipt."

**Step Breakdown:**
- [ ] **Step 1: Write test in `tests/test_start_agent_integration.py` (RED)**
- [ ] **Step 2: Run test and verify failure**
- [ ] **Step 3: Patch `start.py` (GREEN)**
- [ ] **Step 4: Run tests and verify all green**
- [ ] **Step 5: Physical Evidence Gate**: `pytest tests/test_start_agent_integration.py -v` 退出码 0。
- [ ] **Step 6: Git atomic commit**

---

### Task 3: 双语全景门禁与综合回归验证 [Tier: 1-Light] [Mode: AFK] [Role: Gatekeeper]

**Files:**
- Verify: 全量回归与四道机械门禁

**Step Breakdown:**
- [ ] **Step 1: Go 单测 `cd agent && go test ./...` 100% PASS**
- [ ] **Step 2: Python 核心与伴学单测 100% PASS**
- [ ] **Step 3: 四道机械门禁验证 (`check_frontend_layers.py` 等) 100% PASS**
- [ ] **Step 4: `mypy --strict` & `ruff check` 100% PASS**
- [ ] **Step 5: 追加 `WORKMEMORY/work.log` 记录启动器一体化事件**

---

## [NOTE] Out of Scope
- 修改 Android APK 的 Java/Chaquopy 打包脚本（Android 继续走原生 Python 兜底）。
- 更改现有 Go CLI 命令参数。
