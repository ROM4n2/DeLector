# C2 补证报告：swarm audit P1-2 ~ P1-5 与部分 P2（2026-10-17）

> 触发：`docs/reviews/2026-10-16-open-items-backlog.md` 的 C2 行 ——「P1-3~P1-5 三条均 UNVERIFIED …… **需按报告给的精确命令补证后再定级，不得据此下阻塞结论**」。
> 上游报告：`docs/reviews/2026-10-15-swarm-audit-master.md`（sre-resilience 席位自报三条 + dba-optimizer / code-reviewer 的 P2 若干）。
> 方法：代码精读（逐条 `file:line`）+ 隧道实测（`go test` 两个包）+ 反例搜索（grep 证否）。
> 纪律：**本报告不改任何代码**；结论只由可复跑证据支撑；改判项显式标注。
> 基线：master `d79fdc7`；Go `go1.26.5 windows/amd64`；Python 侧为静态精读（未真跑服务）。

## 结论速览

| 项 | 原判 | 本轮结论 | 建议定级（待你拍板） |
| --- | --- | --- | --- |
| **P1-2** 备份不是跨表一致快照 | CONFIRMED（报告） | 独立复核**成立** | 维持低危（窗口毫秒级） |
| **P1-3** 抓取无总截止 + 错误口径不一致 | UNVERIFIED | **成立**（两半均确证） | P2 |
| **P1-4** Go supervisor 无累积重启上界 | UNVERIFIED | **成立**（实现与文档注释不符） | P2 |
| **P1-5** DeepSeek 退避无 jitter | UNVERIFIED | **成立**（最坏 483.5s 复核一致） | P2 ~ P3 |

P2 抽样补证见 §5（7 项：6 项确证、1 项结案、其中 1 项细化）；本轮未覆盖项见 §6。

## 1. P1-2 备份不是跨表一致快照 —— 独立复核成立

- 证据：`delector/core/db/backup.py:326-357` `build_backup_payload()` 逐表裸 `SELECT *`（`:330` 列表推导），主库连接（`:328 get_db()`）与进度库连接（`:342 get_progress_db()`）**顺序、独立**读取，两段 `try/finally` 之间无 `BEGIN`、全模块无事务包裹。
- 自证冲突：同模块 `:402-437`（`_backup_db_file` / `_restore_db_file`）明确以「文件级拷贝会拿到不一致快照」为理由改用 SQLite backup API —— JSON 这条用户真在用的路径没有同等保证。
- 修法（与上游报告一致）：`build_backup_payload` 内 `BEGIN DEFERRED` → 读完 `COMMIT`；并在注释写明**两库之间仍不可能原子**（不要假装解决）。

## 2. P1-3 抓取无总截止 + 错误口径不一致 —— 成立

（a）**无总截止**：`delector/core/security.py:177` 单一 `httpx.AsyncClient(timeout=15.0, follow_redirects=False)`；`:178` 循环上限 `MAX_REDIRECT_HOPS + 1 = 6`（`:160`）；正文流式读取只有 **2MB 字节闸**（`:196` / `:204-205`）而**没有时间闸** ⇒ 慢滴服务器可长期占住该请求。`timeout=15.0` 是 httpx 的 per-operation 语义（connect/read/write/pool 各自 15s），**不是**总截止。

（b）**错误口径不一致**：
- `security.py` 全程无 `except httpx.HTTPError`；`grep -rn "exception_handler" delector/` → **0 命中**（无全局兜底）。
- 调用点直接 `await`，无包裹：`delector/routes/main.py:229`（`POST /api/articles/ingest-url`）、`:254`（`GET /api/feed/items`）⇒ DNS/连接/读超时一律冒泡成**笼统 500**。
- 对照：性质相同的出站 GET 在 `delector/routes/encounter.py:378-389`（`_shelf_get`）有 **502 + 人话文案**（`except httpx.HTTPError` 与 `status != 200` 两条分支）⇒ 口径不一致成立。

（c）附带事实（原报告未提，供定级参考）：逐跳有 SSRF 闸（`:179 is_safe_public_url`，重定向前校验，防盲 SSRF）；2MB 大小闸有效。

修法建议：以 `asyncio.timeout(总截止)` 包住整段抓取 + 把 `httpx.HTTPError` 映射为 502（复用 encounter 的文案常量），并把 ingest / feed 两处调用点纳入同口径。

## 3. P1-4 Go supervisor 无累积重启上界 —— 成立（实现与文档不符）

- 文档与实现冲突：`agent/internal/pythonsvc/supervisor.go:78` 的配置注释称 `MaxRestarts` 是「启动/崩溃重启的**总**尝试配额」；实现中 `:279`（`for tries := 0; tries < s.cfg.MaxRestarts; tries++`）的 `tries` 是**局部变量**，每次调用 `startWithRetry` 都重置。
- 无累积上界：`:245-267`（`supervise`）在每次 `p.wait()` 返回后直接 `startWithRetry` 重启，**无跨 episode 计数**；退避只在**同一 episode 内启动失败之间**生效（`:292-296`），**跨 episode 零退避** ⇒ 「启动成功 → 崩溃 → 再启动」的 crash-loop 以进程启动+探针耗时（uvicorn + spaCy 冷启动，秒级）为唯一自然下界 。
- 静默：`:258` 仅当整轮 episode 配额耗尽才 `report()`；`:401-407` `report()` 非阻塞、缓冲 1。⇒ 上述 crash-loop **永不 `Failures()` 上报**。
- 测试覆盖缺口（实证）：`agent/internal/pythonsvc/supervisor_test.go:90-390` 共 8 例，覆盖「单轮配额恰好 MaxRestarts 次」（`:176`）/「单次崩溃后重启」（`:277`）/「崩溃且重启启动失败 → Failures 上报」（`:328`），**没有 crash-loop（成功→崩溃→成功→崩溃…）用例**。
- 执行证据：`cd agent && go test ./internal/pythonsvc/ -count=1` → `ok github.com/ROM4n2/DeLector/agent/internal/pythonsvc  4.453s`（现状语义全绿，即缺口被测试固化而非暴露）。
- 修法建议：在 `supervise` 层加**累积**重启上限 + 跨 episode 退避（复用 `backoff()`），并补一条 crash-loop 单测（桩可完全复用现有 `newStubSupervisor` 的 script 机制）。若判定为「设计取舍」，则至少把 `:78` 的「总配额」措辞改成「每轮 episode 配额」。

## 4. P1-5 DeepSeek 退避无 jitter —— 成立

- 确定性退避：`agent/internal/llm/deepseek.go:96-106` `llmBackoffDefault(attempt)` = `500ms << attempt`（`:105`），`attempt > 4` 封顶 8s（`:102-104`）；注释自述「纯函数，无副作用」（`:94` 起）。反例搜索：`grep -rnE "rand\.|jitter|Float64" agent/internal/llm/` → **0 命中**。
- 最坏单次复核：`llmRetries = 3`（`:35`）、`defaultTimeout = 120s`（`:30`，`http.Client{Timeout: ...}`）、重试循环 `:160-180` ⇒ 最坏 `4 × 120s + (0.5s + 1s + 2s) = 483.5s` —— 与报告的「4×120s + 退避 ≈ 483s」**复算一致**。
- 放大尖峰：确定性退避 ⇒ 并发调用者会**同步重试**。`agent/internal/` 下有 `dag/`、`job/` 两个可能并发的执行包（`ls agent/internal/`），但**本轮未实测并发调用链**，此条按「待证」登记，不作为结论。
- 对照（建议修法来源）：实验 harness **已经有** jitter —— `tools/bench_judge_gaming.py:1087-1089` `_jitter(upper) = random.uniform(0.0, upper)`，退避为 `base * 2**n + jitter`（`:174`，B5 / ADR-0024 批次落地）⇒ 产品侧 Go 客户端与 harness 口径不一致，建议对齐。
- 执行证据：`cd agent && go test ./internal/llm/ -count=1` → `ok github.com/ROM4n2/DeLector/agent/internal/llm  1.259s`（8/8，含 `TestComplete_Retries429ThenSucceeds`、`TestComplete_500ExhaustsRetries` 两例重试语义）。

## 5. P2 抽样补证（本轮顺手，供定级）

| # | 报告条目 | 结论 | 证据（file:line） |
| --- | --- | --- | --- |
| 1 | `GET /api/settings` 无本机闸、LAN 可读 `api_key_masked` / `api_base_url` / `api_model` | **确证** | `delector/routes/main.py:1478-1497`（同文件 POST 在 `:1500-1502` 有 `_require_localhost`）；掩码 = 首 4 + 尾 4（`:1483-1486`） |
| 2 | 上游错误体前 100 字符回显客户端 | **确证** | `main.py:1539-1544`（`f"连接失败: {e.raw}"` 与 `f"... ({e.status_code}) ({e.raw[:100]})"`） |
| 3 | TTS 三连：零退避重试 / 连接超时 30s / 静默禁用证书校验 | **确证（三点全中）** | `delector/services/tts.py:270`（`for attempt in range(2)`）+ `:313-316`（`except Exception: ... continue`，无 sleep）；`:124-126`（`timeout=30.0`）；`:127-132`（`ssl.create_default_context()` 失败即 `ssl._create_unverified_context()`，无日志） |
| 3b | 兜底 provider 失败「零痕迹」 | **确证并细化** | `main.py:1239-1251` 逐 provider `except Exception: continue` 吞掉原因；`:1252-1256` 唯一一条 `logging.warning(..., exc_info=True)` 位于 except 块**之外** ⇒ 取不到活动异常（空壳回溯） |
| 4 | `test_desktop_shell.py:2109` 恒真断言 | **确证** | `:2110` `assert sys.stdout is not None`（pytest 捕获下不可能为 None） |
| 5 | `_pending_backup` / `_pending_wb` 全局槽无锁 | **确证** | 定义在 `delector/core/db/backup.py:363/:366`；`grep -n "Lock\|threading" backup.py` → **0 命中**（缓解：端点受 `_require_localhost`、单用户桌面；报告已标「阈值型」） |
| 6 | `android/gradle/wrapper/gradle-wrapper.jar` 未入库（待确认 CI 是否依赖） | **结案：未入库且本机不存在；CI 不依赖** | `git ls-files android/gradle/` → 仅 `gradle-wrapper.properties`；`android/` 下**无 `gradlew` / `gradlew.bat`**；CI 走 `.github/workflows/build-release.yml:298`（`gradle/actions/setup-gradle@v6`，`:300` pin 8.6）+ `:395 gradle assembleDebug`，全仓无 `gradlew` 调用 ⇒ 本地 wrapper 路径不可用。建议二选一：补 jar + 脚本，或删属性文件（消除「半套 wrapper」） |
| 7 | `stats_json` 不在备份清单 ⇒ 还原后永久 NULL 且不自愈 | **确证** | 导出侧 `SELECT *`（`backup.py:330`）能带上它，但还原侧按固定列元组回填（`:487-511`，`_rows_to_tuples(rows, columns, defaults)`），`grep -n "stats_json" backup.py` → **0 命中** ⇒ 还原丢列；唯一回填是一次性迁移 `delector/core/db/schema.py:361-374`（`if "stats_json" not in article_cols` 分支内执行，列已存在即跳过）⇒ **确实不自愈**。与 `vocab_cards` 的 `source/fsrs_*` 前例同族（`backup.py:102-106` 有同类修复注释）。用户可见影响有限：列表查询有 COALESCE 兜底 |

### 5.1 仓库卫生（本轮顺带执行）

- `git gc`（默认参数，无 `--prune=now`）：松散对象 **7556 → 0**、`prune-packable` **836 → 0**、in-pack 4547 → 8505；耗时 38.5s；`git fsck` 仅报 4 个常规 `dangling blob`（未引用未过期对象，非损坏）。
- 「`gc.auto` 疑似未生效」**属实**：`git config --get gc.auto` 无输出（未配置，默认 6700），而清理前松散对象已达 7556 ⇒ 长期未触发自动 gc（成因未定；`gc.autoDetach` / 维护进程未查）。手动 gc 后阈值远低于触发线，短期无需再动。

## 6. 本轮未覆盖（留给下一轮）

- 上游报告 P2-#10 组：`static/german/workbench.html` 轮询无 jitter、`_pollTimer` 从不 `clearInterval`、fetch 无 `AbortSignal.timeout`；`GET /api/wb/state` 无大小闸；`supervisor.go:390-399` kill 后 `<-done` 无第二超时；`cmd.Stdout` 直连父 stdout 无轮转；长写事务期 `/api/health` 因 `busy_timeout=5000` 误报 503。
- 上游报告 P2-#9 其余：三条 PRAGMA 共用 `try/except: pass`；`data_dir_bootstrap` 两库非原子复制（`preflight_data_dir` 只守主库）；`progress.db` 无 ALTER 迁移路径；`/api/cards/due` 的 `id ASC` 吃排序索引。
- P1-2 ~ P1-5 的**修复**本身（本报告只补证；修复按仓库纪律走分支 + PR）。

## 附：执行记录（可复跑）

```text
cd agent && go test ./internal/pythonsvc/ -count=1      # ok github.com/ROM4n2/DeLector/agent/internal/pythonsvc  4.453s
cd agent && go test ./internal/llm/ -count=1              # ok github.com/ROM4n2/DeLector/agent/internal/llm         1.259s
git ls-files android/gradle/                              # 仅 gradle-wrapper.properties（jar 未入库）
grep -rn "exception_handler" delector/                    # 0 命中
grep -rnE "rand\.|jitter|Float64" agent/internal/llm/      # 0 命中
grep -n "Lock\|threading" delector/core/db/backup.py      # 0 命中
grep -n "stats_json" delector/core/db/backup.py           # 0 命中（不在任何备份列元组）
git count-objects -v   # gc 前：count 7556 / size 53037 / prune-packable 836；gc 后：count 0 / in-pack 8505
```