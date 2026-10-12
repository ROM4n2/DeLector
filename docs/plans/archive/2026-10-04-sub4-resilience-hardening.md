# 子计划 4/5 · 韧性四项 Implementation Plan

> **Goal**: 修四个"系统坏了但没人知道"的缺陷：① Go agent 在 Python 子进程崩溃且重启配额耗尽后**静默存活**（所有调用打到已死的端口）；② 备份还原的**回滚失败被 `except Exception: pass` 吞掉**（用户收到 500，以为没发生，库已半残）；③ `/api/audio/tts` **无并发上限**（局域网多设备可把线程池打满、请求无界排队，最坏单请求约 76s）；④ **无真正健康检查端点**（agent 拿 `GET /api/tools/` 当探针，而它不碰 DB ⇒ 200 不代表库可用）＋ `ci.yml` 无 `timeout-minutes`。
> **Tech Stack**: Go 1.26.5（agent）· Python 3.11 / FastAPI（后端）· GitHub Actions
> **Spec Reference**: `docs/reviews/2026-10-03-swarm-audit-master.md`（sre-resilience 座 P1 四条 + code-reviewer 红牌）
> **Global Constraints**:
> - **零 `static/` 改动 ⇒ 零发版**。
> - **不引新依赖**：信号量用 `asyncio.Semaphore`（stdlib）；Go 用 stdlib `log`/`os`。
> - Go 改动 MUST 过 `go test -race ./...`（既有 8 包全绿基线）。
> - 门禁：`ruff` ＋ 两道 mypy ＋ 分半 pytest ＋ 探针 ＋ `go test -race ./...` ＋ `gofmt -l` ＋ `go vet ./...`。

---

## 🏛️ Decisions So Far

- **agent 的退避/封顶本身做得很扎实**（指数退避 500ms×2^n 封顶 8s、`ProbeTimeout` 10s 针对 spaCy 冷启动、两段式强杀）—— 问题**纯粹出在错误没有出口**：`Failures()` 定义了（`agent/internal/pythonsvc/supervisor.go:183`）但 `app/internal/app/app.go:55-58` 的 `supervisor` 接口**只声明 `Start`/`Stop`**，生产路径零消费（仅 `supervisor_test.go:348` 消费）。
- **回滚吞错**（`delector/core/database.py:1666-1673`）：`except BaseException` 里逐个 `_restore_db_file`，**失败即 `pass`**。这正是该 guard 存在理由（`:1667` 注释「半个还原比不还原更糟」）被静默打破。⇒ 回滚失败是 **P0 级事件**，必须留"库可能已损坏 + 快照仍在哪"的救命线索。
- **快照写在 `tempfile.mkdtemp()`（系统 temp，非 `DATA_DIR`）** ⇒ `DATA_DIR` 满盘时快照本身仍能成功；日志里必须打印该路径，否则用户/运维找不到回滚素材。
- **TTS 输入侧防护已到位**（`MAX_TTS_TEXT_LEN=1000`、voice 白名单、rate 正则）—— 缺的**只是并发/速率侧**。出站超时**已全覆盖**（LLM 30/15/20/10/30s、SSRF 15s、TTS 兜底 6s）。
- **只读 GET 一律不挂本机闸**是仓库惯例（16 处 `_require_localhost` 全是写/密钥/备份类）⇒ 新健康端点沿用同一惯例。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: Go agent 给 Python 崩溃一个出口 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `agent/internal/app/app.go:55-58`（`supervisor` 接口）、`:93-101`（`Run`）
- Test: `agent/internal/app/app_test.go`（或既有 `supervisor_test.go` 邻近）

**Interfaces:**
- Consumes: `pythonsvc.Supervisor.Failures() <-chan error`（`supervisor.go:183`，**已存在**）
- Produces: `app` 侧的 `supervisor` 接口**新增** `Failures() <-chan error`；`Run` 起一个 goroutine 消费它，收到错误时：① `log`/`fmt.Fprintf(os.Stderr, ...)` 打出完整错误链 ② **触发非零退出**（cancel 上层 ctx 或 `os.Exit(1)`，选与既有退出路径一致者）
- MUST NOT 改 `supervisor.go` 的退避/封顶/强杀逻辑

**Injected Instincts:**
- [ ] `[Instinct: Error-Must-Reach-Operator]`: MUST 有**非零退出码**（让 `restart: unless-stopped` / systemd 接管）⇒ 绝不只打日志后继续存活。
- [ ] `[Instinct: Race-Free]`: 消费 goroutine MUST 正确处理 channel 关闭（MUST NOT 无限阻塞或 panic）。
- [ ] `[Instinct: No-Silent-Drop]`: 错误 MUST 打出**完整错误链**（`%v` + 包装），MUST NOT 只打 "failed"。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: Go agent 的 `Failures()` 出口。
> Mode: AFK | Role: TDD Builder
> Goal: Python 子进程崩溃且重启配额耗尽后，agent MUST 非零退出，而不是静默存活。
> Target Files: Modify `agent/internal/app/app.go`；Test `agent/internal/app/*_test.go`。
> Interfaces: Produces `app` 侧 `supervisor` 接口新增 `Failures() <-chan error`；`Run` 消费它 ⇒ 打错误链 + 非零退出。
> Injected Instincts: Error-Must-Reach-Operator / Race-Free / No-Silent-Drop。
> TDD Steps:
> 1. 先跑 `go test -race ./...` 记录**基线全绿**。
> 2. 写测试（RED）：用**假 supervisor**（实现 `Start`/`Stop`/`Failures`，后者返回一个带错误的 channel）⇒ 断言 `Run` 以**非零**结束 / 取消 ctx。
> 3. 贴红输出。4. 改 `app.go`（GREEN）。5. `go test -race ./...` + `gofmt -l` + `go vet ./...` 全绿。
> 6. 变异验证：把消费 goroutine 删掉 ⇒ 测试必红。
> Return: Summary + 三条 Go 门禁原始输出。"

**Step Breakdown:**
- [ ] **Step 1: 记录 Go 基线** → **Step 2: 写测试（RED）** → **Step 3: 确认红** → **Step 4: 改 `app.go`（GREEN）** → **Step 5: Go 三门禁** → **Step 6: 变异验证** → **Step 7: Physical Evidence Gate** → **Step 8: commit**

---

### Task 2: 回滚失败必须留痕 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/core/database.py:1666-1673`（`_db_snapshot_guard` 的 `except BaseException` 块）
- Test: `tests/test_audit_hardening.py`（备份/还原用例邻近）

**Interfaces:**
- Consumes: `_restore_db_file(snapshot_path, dst_path)`（`:1627`）
- Produces: 回滚失败时 `logging.getLogger("delector").error(...)`，消息 MUST 含：失败的库路径、快照路径、`repr(exc)`、`exc_info=True`；MUST NOT 吞异常（原始 `raise` 保持不变）
- Produces: 快照目录路径 MUST 出现在消息里（用户据此手工捞回）

**Injected Instincts:**
- [ ] `[Instinct: Never-Swallow-Recovery]`: 回滚失败 MUST 留**可操作**日志（路径 + 错误链 + `exc_info`），MUST NOT 只 `pass`。
- [ ] `[Instinct: Original-Exception-Wins]`: MUST 保持原始异常继续上抛（回滚失败**附加**信息，MUST NOT 替换主异常）。
- [ ] `[Instinct: Multi-Table-DB]`: `snapshots` 有多张表（主库 + progress 库）⇒ MUST 逐个记录，某一失败不影响其余回滚。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: `_db_snapshot_guard` 回滚失败留痕。
> Mode: AFK | Role: TDD Builder
> Goal: 回滚失败是 P0 级事件（库可能半残），MUST 在服务端日志留下「哪张库、快照在哪、为什么失败」。
> Target Files: Modify `delector/core/database.py:1666-1673`；Test `tests/test_audit_hardening.py`。
> Interfaces: Produces `logging.error(..., exc_info=True)` 含库路径/快照路径/错误链；原始异常仍上抛。
> Injected Instincts: Never-Swallow-Recovery / Original-Exception-Wins / Multi-Table-DB。
> TDD Steps:
> 1. 写测试（RED）：monkeypatch `_restore_db_file` 恒抛 ⇒ 触发 guard 回滚 ⇒ 用 `caplog` 断言**日志里出现快照路径与错误链**，且原始异常仍上抛。
> 2. 确认红。3. 改代码。4. 确认绿。
> 5. 变异验证：把 `logging.error` 那行删掉 ⇒ 测试必红。
> 6. 门禁：`tests/test_audit_hardening.py -q` + ruff + 两道 mypy。
> Return: Summary + 回执。"

**Step Breakdown:**
- [ ] **Step 1: 写测试（RED）** → **Step 2: 确认红** → **Step 3: 改代码（GREEN）** → **Step 4: 复跑** → **Step 5: 变异验证** → **Step 6: 门禁** → **Step 7: commit**

---

### Task 3: TTS 并发闸 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/routes/main.py`（`_serve_tts` 约 1180；`POST /api/audio/tts` 约 1199；`GET /api/audio/tts` 约 1204）
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `asyncio.Semaphore`（stdlib）
- Produces: 模块级 `asyncio.Semaphore(k)`（`k` 取 4~8，**写进常量并注释**）；两个入口在调用 `_serve_tts` 前 `async with` 获取；获取不到 ⇒ `HTTPException(429, ...)`
- MUST NOT 改变 `MAX_TTS_TEXT_LEN` / voice 白名单 / rate 正则（输入侧防护已到位）

**Injected Instincts:**
- [ ] `[Instinct: Bounded-Queue]`: MUST 把**无界排队**变成**有界拒绝**（429），MUST NOT 只是加个延时。
- [ ] `[Instinct: No-Client-Change]]: MUST NOT 让正常单用户请求开始失败（`k` ≥ 4，且局域网默认最多 1~2 台设备并发朗读）。
- [ ] `[Instinct: Semaphore-Lifetime]`: `Semaphore` MUST 是**模块级**（MUST NOT 每请求新建，否则限流失效）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: TTS 并发闸。
> Mode: AFK | Role: TDD Builder
> Goal: 把无界排队变有界拒绝（429），防止多设备把线程池打满。
> Target Files: Modify `delector/routes/main.py`（`_serve_tts` 与两个 tts 入口）；Test `tests/test_server.py`。
> Interfaces: Produces 模块级 `asyncio.Semaphore(k)` 包裹 `_serve_tts` 调用；拿不到 ⇒ `HTTPException(429, ...)`。
> Injected Instincts: Bounded-Queue / No-Client-Change / Semaphore-Lifetime。
> TDD Steps:
> 1. 写测试（RED）：并发发起 N+1 个 `/api/audio/tts`（桩 `_serve_tts` 阻塞）⇒ 断言第 N+1 个拿到 **429**（先跑确认红）。
> 2. 改代码。3. 确认绿。
> 4. 变异验证：把 `k` 调成 1_000_000 ⇒ 并发保护测试必红。
> 5. 门禁：`tests/test_server.py -q -k audio` + ruff + 两道 mypy。
> Return: Summary + 回执。"

**Step Breakdown:**
- [ ] **Step 1: 写测试（RED）** → **Step 2: 确认红** → **Step 3: 改代码（GREEN）** → **Step 4: 复跑** → **Step 5: 变异验证** → **Step 6: 门禁** → **Step 7: commit**

---

### Task 4: 真健康端点 + CI 超时护栏 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/routes/tools.py`（或 `main.py` 邻近既有只读 GET 处 —— 先读再定）；`agent/internal/pythonsvc/supervisor.go:39`（`defaultHealthURL`）；`.github/workflows/ci.yml:36-40`（`jobs.ci`）
- Test: `tests/test_ci_hardening.py`（已有 Dockerfile 守卫范式）+ `tests/test_server.py`（健康端点）

**Interfaces:**
- Consumes: `db_conn()`（探针 MUST 真碰 DB）、`defaultHealthURL`
- Produces: `GET /api/health`（**沿用只读 GET 不挂本机闸的仓库惯例**）⇒ 至少探 `SELECT 1`（或 `PRAGMA quick_check` 的轻量版）；DB 不可用 ⇒ 返回非 200
- Produces: `defaultHealthURL` 改指新端点
- Produces: `jobs.ci` 加 `timeout-minutes: 15`（注释自陈"PR 反馈预期 < 8min"，15 留足余量）

**Injected Instincts:**
- [ ] `[Instinct: Probe-Must-Touch-DB]`: 健康端点 MUST 真查 DB（当前 `GET /api/tools/` **不碰 DB** ⇒ 200 不代表库可用，这正是要修的病根）。
- [ ] `[Instinct: No-Sensitive-Leak]`: 失败响应 MUST NOT 泄露路径/异常栈（只回状态与一句人类可读原因）。
- [ ] `[Instinct: Convention-Follow]]: 只读 GET **MUST NOT** 挂 `_require_localhost`（与 16 处惯例一致）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 4: 真健康端点 + CI 超时护栏。
> Mode: AFK | Role: TDD Builder
> Goal: 让 agent 的健康探针真反映 DB 可用性；给 CI 加超时护栏。
> Target Files: Modify 健康端点路由、`agent/internal/pythonsvc/supervisor.go:39`、`.github/workflows/ci.yml`；Test `tests/test_server.py` + `tests/test_ci_hardening.py`。
> Interfaces: Produces `GET /api/health` 真查 DB（失败非 200，不泄露敏感）；`defaultHealthURL` 改指它；`jobs.ci` 加 `timeout-minutes: 15`。
> Injected Instincts: Probe-Must-Touch-DB / No-Sensitive-Leak / Convention-Follow。
> TDD Steps:
> 1. 写测试（RED）：健康端点在库正常时 200；monkeypatch DB 连接抛错时非 200（贴红）。
> 2. 实现端点（GREEN）。
> 3. 写 CI 守卫测试（RED）：断言 `ci.yml` 含 `timeout-minutes` ⇒ 改 `ci.yml` ⇒ 绿。
> 4. 改 `defaultHealthURL`；`go test -race ./...` + `gofmt -l` + `go vet` 全绿。
> 5. 变异验证：把健康端点的 DB 探测删掉（直接 return 200）⇒ 测试必红。
> 6. 门禁：全部门禁。
> Return: Summary + 回执。"

**Step Breakdown:**
- [ ] **Step 1: 写测试（RED）** → **Step 2: 确认红** → **Step 3: 实现（GREEN）** → **Step 4: 复跑** → **Step 5: 变异验证** → **Step 6: 门禁** → **Step 7: commit**

---

## 🌫️ Fog of War

- **[Fog 1] 回滚失败后是否要阻止服务继续服务**：现在是"回滚失败 + 上抛 500"（用户看到 500 但库已半残）。是否要进一步**标记库为不可用并拒绝后续读**？属更大设计，另立。
- **[Fog 2] TTS 并发闸的 `k` 取值**：取 4~8 需按真实并发量定；目前无遥测 ⇒ 先取 4 并在代码注释里写"如需调整看这里"。
- **[Fog 3] `ci.yml` 超时值**：15 是估的；真实 CI 耗时（PR #91 的 check）约 3m5s ⇒ 15 留 5 倍余量，合理。**不**先设成 8。
- **[Fog 4] 其余韧性项**（不在本子计划）：`_backend_pack` 存在但打包三处是否同步（历史早已修）；Android keystore `.gitignore` 已完整（审计确认）。

---

## 🚫 Out of Scope

- 不改 `static/`（零发版）
- 不改 supervisor 的退避/封顶/强杀（Task 1 只加出口）
- 不改 TTS 的输入侧校验与出站超时链（已到位）
- 不做 Fog 1（库不可用标记）
