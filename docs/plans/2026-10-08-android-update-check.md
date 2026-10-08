# 更新可见性（版本检查 + 提示）Implementation Plan

> **Goal**: 新增 `GET /api/update/check`（后端代查 GitHub Releases）+ 建立应用级版本单一真相源 + 顶栏落后提示 chip，消灭"不知道有新版"的盲区（**不做**应用内下载/安装）。
> **Tech Stack**: Python 3.11（FastAPI + httpx，Android 侧 Chaquopy py3.10/pydantic<2/fastapi<0.100）/ 原生 JS ES Modules / node 行为探针
> **Spec Reference**: [ADR-0017](../../docs/adr/2026-10-08-adr-0017-android-update-check-notifier.md)（vault 正式件：`08-Projects/DeLector/01-ADR/0017-android-update-check-notifier.md`）
> **Global Constraints**:
> - 出网**只准** `httpx`（`requirements.txt:12` + `android/app/build.gradle:95 install "httpx"` 已打包）——**禁**引入 `requests`/`aiohttp`（Android 无 wheel，见 `delector/services/tts.py:4`）。
> - 出网超时 **3s**；TTL 缓存：成功 **6h** / 失败 **60s**（失败长缓存会把"网络已恢复"锁死 6 小时）。
> - **红线 9**：`import` 期不得联网 —— 出网只发生在端点被调用时。
> - **红线 11**：跨边界契约（后端 JSON ↔ 前端渲染）必须**行为探针**验证；字符串存在断言视为死测。
> - **端点内禁出现版本号字面量**（`current` 必须来自 `APP_VERSION`）——v5.16.0 的 `PROCESSED_JSON_VERSION` 判据写死事故不得重演。
> - 单元测试**不得真联网**（注入 fetcher）；新探针 `--json` 必须精确 `{failures,total,cases}` 三键且有 `tests/test_*.py` wrapper。
> - 提交禁 `--no-verify`。

---

## 🏛️ Decisions So Far

- **ADR-0017**（accepted 2026-10-08）：Q1-A 只做检查+提示；Q2-A GitHub Releases 为唯一真相源，失败**不得伪装成"已是最新"**；Q3-A 后端端点代查（非前端直连）；Q4-A 启动后延迟自动检查、仅落后时显示 chip、无新版与失败均静默。
- **D1 版本单一真相源 = `delector/core/version.py: APP_VERSION`**（无 `v` 前缀，与 `build.gradle:8` 口径一致）。静态面（`sw.js` / `index.html` / `build.gradle` / `README`）因无法 import Python 而**保留字面量**，但既有守卫的判据从"三面互等"升级为"**每面都必须等于 `APP_VERSION`**"——这样新端点直接引用常量，不新增硬编码点。
- **D2 ⚠️ 对 ADR 附带默认的收窄**：ADR 写"顶栏改为真实版本 + 真实检查结果"，但 `tests/test_writer_mobile.py:75-79` 记录了该静态串是**"用户判断前端刷新了没有的唯一肉眼指标"**（v4.4.5 漏 bump 出过事故）。若改成由 `/api/version` 动态渲染，该指标立刻失效（服务端版本反映的是**后端代码**，证明不了**前端资源**是否刷新）。⇒ 裁决：**静态 `System · vX.Y.Z` 保留**并由守卫继续钉死等于 `APP_VERSION`；只把误导性的 `Online`（只绑回环的单机下字面撒谎）换成中性静态词；动态更新状态**只**由新 chip 承载。
- **D3 出网与判据分离**：`_fetch_latest_release(timeout)` 负责真实 httpx 调用（不含测试）；`check_for_update(fetcher=..., now=...)` 承载缓存 + 规约 + 版本比较（**纯逻辑、可注入、可测**）。
- **D4 缓存**：模块级 `_CACHE` + `_CACHE_AT` + `threading.Lock`；成功缓存 6h、失败缓存 60s；命中缓存时 `cached: true` 且**零出网**（测试用计数器钉死）。
- **D5 判定用 versionCode 语义**（`major*10000+minor*100+patch`，红线 4），不得字符串比较；GitHub 侧不可解析（404 / 坏 tag）统一归 `error_reason: "not_found"`，限流归 `"rate_limited"`，超时归 `"timeout"`，其余网络异常归 `"network"`（枚举**不扩张**，同 ADR）。
- **D6 不做 `?force=1`**：手动检查也走 TTL（失败只有 60s，用户再点即可重试）。避免为"绕过缓存"新增一套闸门语义。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: 应用级版本单一真相源 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `delector/core/version.py`
- Test: `tests/test_app_version_source.py`

**Interfaces:**
- Consumes: 无（叶模块，**不得** import 任何 `delector.*`，避免循环依赖）
- Produces: `APP_VERSION: str = "5.16.0"`（无 `v` 前缀）；`def version_code(version: str = APP_VERSION) -> int`（`major*10000 + minor*100 + patch`）

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: Cross-Platform]`: 纯 stdlib，`mypy --strict` 干净（`delector` 在 `--strict` 门禁内）。
- [ ] `[Instinct: Falsifiable]`: `version_code` 对 `"3.10.0"` / `"4.0.0"` 必须给出**不同**值（历史撞车点），对 `"5.16.0"` 必须为 `51600`。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 应用级版本单一真相源。
> Mode: AFK | Role: TDD Builder
> Goal: 建立 `delector/core/version.py`，导出 `APP_VERSION` 与 `version_code()`，作为全仓唯一可读版本真相源。
> Target Files: Create `delector/core/version.py`；Test `tests/test_app_version_source.py`。
> Injected Instincts: 纯 stdlib；`version_code` 必须能区分 3.10.0 与 4.0.0（旧 `major*100+minor*10+patch` 在此撞车）。
> TDD Steps:
> 1. Write failing test in `tests/test_app_version_source.py` (RED)：`APP_VERSION` 匹配 `^\d+\.\d+\.\d+$`；`version_code("5.16.0") == 51600`；`version_code("3.10.0") != version_code("4.0.0")`；非法输入抛 `ValueError`。
> 2. Run `python -m pytest tests/test_app_version_source.py -q` and verify it fails (module 不存在)。
> 3. Implement minimal code in `delector/core/version.py` (GREEN)。
> 4. Run `python -m pytest tests/test_app_version_source.py -q` and `mypy --strict delector/core/version.py`。
> 5. Flatten with Guard Clauses (max 2 levels)。
> Return: Summary with MANDATORY Physical Execution Receipt (exit code + stdout snippet + `git diff --stat`)。"

**Step Breakdown:**
- [ ] **Step 1: Write the failing test (RED)**
- [ ] **Step 2: Run test and verify it fails with expected message**
- [ ] **Step 3: Implement minimal production code (GREEN)**
- [ ] **Step 4: Run tests and verify all green**
- [ ] **Step 5: Refactor & Flatten with guard clauses (REFACTOR)**
- [ ] **Step 6: Physical Evidence Gate**（Command + Exit code: 0 + pass count + `git diff --stat`）
- [ ] **Step 7: Git atomic commit**

---

### Task 2: 四个版本面归一到常量 + 守卫判据升级 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `tests/test_writer_mobile.py:59-140`（两条守卫的**基准**从 `build.gradle` 改为 `APP_VERSION`）
- Modify: `static/index.html:35`（`System · v5.16.0 Online` → 去掉 `Online`，保留版本字面量；见 D2）
- Modify: `tools/vault-proactive-scan.py:250`（同步新的顶栏正则）
- Modify: `tools/vault-proactive-scan.py:260,267`（**顺带修 bug**：该正则用 `,` 分隔，而 `build.gradle:8` 实际是 `?:` ⇒ 探测脚本的版本一致性判定实际只覆盖 index.html + sw.js 两端，`len(versions) < 2` 阈值恰好躲过 WARN）
- Test: 上述两条既有守卫（改造后必须仍然绿）+ `tests/test_server.py:2382-2384` 不得受影响

**Interfaces:**
- Consumes: `from delector.core.version import APP_VERSION`
- Produces: 无新符号（改造既有测试与既有文件）

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: Guard-Don't-Write-Literals]`: 守卫必须断言"**与 `APP_VERSION` 相等**"，不得改成断言某个字面量（`test_writer_mobile.py:63-65` 已明令）。
- [ ] `[Instinct: Multi-Surface Sync]`: 改 `index.html` 顶栏串必须**同时**改 `tests/test_writer_mobile.py:78` 与 `tools/vault-proactive-scan.py:250` 的正则，否则一处红一处静默。
- [ ] `[Instinct: Doc-Edit-Safety]`: 改 `README.md` **不**在本任务范围内（本计划不发版，README 的下载表在发版时才 bump）。
- [ ] `[Instinct: No-Break-Docs]`: 改动后跑行数 + 最长连续单字符行段检测（历史事故：README 被逐字符打散）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: 四个版本面归一到 `APP_VERSION`，并升级守卫判据。
> Mode: AFK | Role: TDD Builder
> Goal: 让 `sw.js` / `index.html` / `build.gradle` / `README` 的版本落点由既有守卫强制等于 `delector/core/version.py: APP_VERSION`；同时把顶栏的误导词 `Online` 去掉（保留 `System · vX.Y.Z` 静态自证语义）。
> Target Files: Modify `tests/test_writer_mobile.py`（两条守卫的基准改为 `APP_VERSION`）、`static/index.html:35`、`tools/vault-proactive-scan.py:250,260,267`。
> Injected Instincts: 守卫断言"与 `APP_VERSION` 相等"而非字面量；改顶栏串必须同时改两处正则；文档改动后跑破坏检测。
> TDD Steps:
> 1. 先把守卫基准改成 `APP_VERSION` 并跑 `python -m pytest tests/test_writer_mobile.py -q`：预期**红**（因为 `APP_VERSION` 与各面虽然相等，但顶栏正则 `System · v(\d+\.\d+\.\d+) Online` 会因去掉 `Online` 而失配）——记录真实失败输出。
> 2. 同步改 `index.html:35`（去掉 `Online`）、`tools/vault-proactive-scan.py` 的三处正则。
> 3. 跑 `python -m pytest tests/test_writer_mobile.py tests/test_server.py -q` 全绿（`test_server.py` 必须一并跑：它也有 gradle 版本正则）。
> 4. 跑 `python tools/vault-proactive-scan.py`（或等价入口）确认**无 WARN**、且 build.gradle 现已被正确解析。
> Return: MANDATORY Physical Execution Receipt（exit code + pass counts + `git diff --stat`）。"

**Step Breakdown:**
- [ ] **Step 1: 把守卫基准改为 `APP_VERSION`（RED，记录真实失败输出）**
- [ ] **Step 2: 同步改 `index.html:35` 顶栏串 + 两处正则**
- [ ] **Step 3: 修 `tools/vault-proactive-scan.py:260,267` 的 `,`/`?:` 正则 bug（顺带修，本任务显式包含，非"顺手优化"）**
- [ ] **Step 4: 跑 `test_writer_mobile.py` + `test_server.py` 全绿**
- [ ] **Step 5: 跑探测脚本确认零 WARN**
- [ ] **Step 6: 破坏检测（行数 + 最长连续单字符行段）+ Physical Evidence Gate**
- [ ] **Step 7: Git atomic commit**

---

### Task 3: `GET /api/update/check` 端点（缓存 + 规约 + 版本判定） [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `delector/routes/update.py`
- Modify: `delector/routes/__init__.py:20-61`（import 区按字母序加 `update`；`__all__` 加 `"update"`）
- Modify: `delector/routes/__init__.py:64-90`（`register_routes` 内 `app.include_router(update.router)`，放在 `main.router` **之前**——"分域路由在前、通用 handler 垫底"纪律）
- Test: `tests/test_update_check_endpoint.py`

**Interfaces:**
- Consumes: `from delector.core.version import APP_VERSION, version_code`；`httpx`；`threading`
- Produces:
  - `router = APIRouter(prefix="/api/update", tags=["update"])`
  - `def _fetch_latest_release(timeout: float) -> dict[str, Any]`（真实出网；返回 `{"tag_name": str, "html_url": str}`，异常向上抛）
  - `def check_for_update(*, fetcher: Callable[[float], dict[str, Any]] | None = None, now: float | None = None) -> dict[str, Any]`（纯逻辑：缓存 + 规约 + 判定）
  - `@router.get("/check")` → `def api_update_check() -> Dict[str, Any]`
  - 响应契约：`{"current", "latest", "has_update", "page_url", "checked_at", "cached", "error_reason"}`

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: Failure-Not-Masked]`: 检查失败 `has_update` 必须是 `None`（**绝不为 `False`**）且 `error_reason` 非空 —— 不变式双向成立。
- [ ] `[Instinct: No-Hardcoded-Version]`: 源码内**不得**出现任何 `\d+\.\d+\.\d+` 版本字面量。
- [ ] `[Instinct: No-Import-Time-Network]`: 模块顶层不得调用 `_fetch_latest_release`（红线 9）。
- [ ] `[Instinct: Cache-Bounds]`: 成功 6h / 失败 60s；`cached` 命中时**零出网**。
- [ ] `[Instinct: Cross-Platform]`: 只用 `httpx` + stdlib；不得用 `requests`/`aiohttp`（Android 打包清单只有 httpx）。
- [ ] `[Instinct: Concurrency]`: `threading.Lock` 保护缓存读写，避免并发重复出网。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: 新增 `GET /api/update/check`。
> Mode: AFK | Role: TDD Builder
> Goal: 后端代查 GitHub Releases 并规约成契约；失败**不得**伪装成最新。
> Target Files: Create `delector/routes/update.py`；Modify `delector/routes/__init__.py`（import + `__all__` + `register_routes` 在 `main.router` 前 include）。
> Injected Instincts: 出网只用 httpx、3s 超时；`has_update is None ⇔ error_reason is not None`；成功缓存 6h/失败 60s；import 期不联网；源码无版本字面量。
> TDD Steps:
> 1. Write failing tests in `tests/test_update_check_endpoint.py` (RED)，用 `TestClient` + `monkeypatch.setattr(update, "_fetch_latest_release", ...)` 注入假 fetcher，**绝不真联网**。
> 2. Run `python -m pytest tests/test_update_check_endpoint.py -q` and verify it fails (404 / 无模块)。
> 3. Implement minimal code in `delector/routes/update.py` + 挂载 (GREEN)。
> 4. Run the test file + `mypy --follow-imports=skip tests` + `mypy --strict delector tools`。
> Return: MANDATORY Physical Execution Receipt。"

**Step Breakdown:**
- [ ] **Step 1: Write the failing tests (RED)**：①有新版 → `has_update is True`；②同版 → `False`；③`error_reason="network"` → `None` 且**不是** `False`；④超时 → `"timeout"`；⑤403+`X-RateLimit-Remaining: 0` → `"rate_limited"`；⑥坏 tag → `"not_found"`；⑦TTL 命中 → `cached is True` 且 fetcher 调用计数**仍为 1**；⑧失败后 60s 内不重试、61s 后重试
- [ ] **Step 2: Run and verify it fails with expected message**
- [ ] **Step 3: Implement minimal production code (GREEN)**
- [ ] **Step 4: Run tests + 两道 mypy 全绿**
- [ ] **Step 5: Refactor & Flatten with guard clauses (REFACTOR)**
- [ ] **Step 6: Physical Evidence Gate**
- [ ] **Step 7: Git atomic commit**

---

### Task 4: 端点契约守卫（不变式双向 + 无硬编码版本 + 不写 DB） [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `tests/test_update_check_endpoint.py`（追加守卫函数，与 Task 3 同文件，避免测试文件爆炸）
- Test: 同上

**Interfaces:**
- Consumes: `delector.routes.update` 模块源码文本 + `check_for_update()`
- Produces: 无新生产符号（纯测试）

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: Falsifiable]`: 每条守卫必须能在**真实回退实现**下变红（自证：临时把实现改回"失败也返回 False"，守卫必须红）。
- [ ] `[Instinct: Behavior-Over-Strings]`: "不写 DB"用**行为**证（端点不打开 DB / 无写动词），不用字符串断言凑。
- [ ] `[Instinct: Guard-The-Guard]`: 守卫自身要有"目标存在"断言（防扫描器空转恒绿）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 4: 为 `/api/update/check` 加契约守卫。
> Mode: AFK | Role: TDD Builder
> Goal: 把 ADR-0017 §4.2 的四条 MUST 不变式钉成红灯。
> Target Files: Modify `tests/test_update_check_endpoint.py`。
> Injected Instincts: 守卫必须能在回退实现下变红（真做一次回退自证并记录）；防扫描器空转。
> TDD Steps:
> 1. 写守卫：(a) `has_update is None ⇔ error_reason is not None` 双向（遍历 4 种 error_reason + 两种成功场景）；(b) `delector/routes/update.py` 源码内 `re.search(r'\d+\.\d+\.\d+', src)` 必须**无命中**；(c) 模块 import 期不触发 fetcher（`import` 前后计数器为 0）；(d) 端点不产生写 SQL（复用 `test_get_endpoints_with_writes.py` 的 `_write_verbs_in` 思路或直接断言该文件白名单未变）。
> 2. 跑测试确认绿；然后**故意**把实现改成"失败返回 `has_update=False`"，确认 (a) 变红，记录输出后再改回。
> Return: MANDATORY Physical Execution Receipt（含回退自证的原始输出）。"

**Step Breakdown:**
- [ ] **Step 1: 写四条守卫**
- [ ] **Step 2: 跑绿**
- [ ] **Step 3: 回退自证（改坏实现 → 守卫变红 → 恢复），留下原始输出**
- [ ] **Step 4: Physical Evidence Gate**
- [ ] **Step 5: Git atomic commit**

---

### Task 5: 前端 chip（探针驱动的单一 TDD 对：探针 RED → 实现 GREEN） [Mode: AFK] [Role: TDD Builder]

> **为什么探针与实现合成一个任务**：探针必须先写（RED）才能驱动 `update.js` 的实现（GREEN），拆成两个任务会让 maker/checker 出现"任务 A 依赖任务 B 的产物"的死锁。

**Files:**
- Modify: `static/index.html:34-36`（给 `<span class="right">` 加 `id="topbar-right"`；去掉 `Online`；新增 chip 锚点 `<a id="update-chip" class="hidden" ...>`）
- Create: `static/js/update.js`（`export function initUpdateCheck()`）
- Modify: `static/js/main.js`（import 区加 `import * as Update from "./update.js";`，按 `search.js` 同款；`DOMContentLoaded`（`:1176` 起）回调内调 `Update.initUpdateCheck()`）
- Create: `tools/wb_update_chip_probe.mjs`
- Create: `tests/test_update_chip_ui.py`（**必须**含子串 `wb_update_chip_probe`，否则防漏接线守卫红——`test_probe_wiring_guard.py:94-112`）

**Interfaces:**
- Consumes: `GET /api/update/check`（同源 fetch；Android 上 `127.0.0.1:8000` 同源无障碍）；`esc()` from `core.js:25`
- Produces:
  - `export function initUpdateCheck(): void`（延迟 ~3s 发起一次检查；仅 `has_update === true` 时显示 chip，文案含 `v<latest>`；无新版 / `has_update === null` / 请求异常**三种情况均静默**；点击跳 `page_url`）
  - 探针 `--json` 输出**精确三键** `{"failures": int, "total": int, "cases": [{"name": str, "ok": bool}]}`（`probe_json_contract.py:59 STANDARD_KEYS`；**禁走 legacy 清单**——`LEGACY_BASELINE_COUNT = 23` 只减不增）
  - 探针切片来源：`core.js: esc` / `update.js: initUpdateCheck` / `index.html` 顶栏片段，丢进 `node:vm` 真跑（**不得**重抄一份实现）

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: No-Noise]`: 无新版 / `has_update === null` / fetch 抛错 —— **三种情况都必须零可见变化**（不得出现空 chip、不得 toast）。负向场景要断言"零变化"，不只是"没崩"。
- [ ] `[Instinct: Human-Readable]`: 手动检查失败时的文案**不得**直出 `HTTP <code>` 或 `fetch failed`。
- [ ] `[Instinct: Esc-On-Output]`: 注入 DOM 的动态值（`latest`、`page_url`）必须经 `esc()`。
- [ ] `[Instinct: No-Polling]`: 用一次性 `setTimeout`，**禁** `setInterval`（主壳层无健康轮询通道，别新建常驻定时器）。
- [ ] `[Instinct: Static-Self-Check-Preserved]`: **不得**把静态 `System · vX.Y.Z` 改成由 API 渲染（D2：它是前端刷新自证指标）。
- [ ] `[Instinct: Real-Fixture-Shape]`: fake fetch 的响应形状必须取自**真实端点实跑输出**（vault `POST-MORTEM-V5.7.3-FIXTURE-SHAPE-MISMATCH`：形状不符 ⇒ 恒绿漏检）。落地：探针内断言其 fixture 键集 == 端点契约键集。
- [ ] `[Instinct: Contract-Frozen]`: 探针 `--json` 三键精确，多一键少一键都不行。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 5: 前端 chip（探针驱动的 TDD 对）。
> Mode: AFK | Role: TDD Builder
> Goal: 落后时顶栏显示可点 chip（点击进 GitHub Release 页）；无新版/无结果/报错一律静默。
> Target Files: Create `tools/wb_update_chip_probe.mjs`、`tests/test_update_chip_ui.py`、`static/js/update.js`；Modify `static/index.html:34-36`、`static/js/main.js`。
> Injected Instincts: 三种非"有新版"情况零可见变化；动态值过 `esc()`；一次性 setTimeout 禁 setInterval；保留静态版本自证串；fixture 键集 == 端点契约键集。
> TDD Steps:
> 1. 写探针（切片 + DOM 桩 + fake fetch 三场景 + 契约键集比对）+ wrapper，跑 `node tools/wb_update_chip_probe.mjs --json` 确认三键成立且场景**红** (RED)。
> 2. 实现 `static/js/update.js` + index.html 挂载点 + main.js 接线 (GREEN)。
> 3. 跑 `python -m pytest tests/test_update_chip_ui.py tests/test_probe_wiring_guard.py tests/test_probe_json_contract.py -q` 全绿；`python start.py` 手验三条路径（落后 / 最新 / 断网）。
> Return: MANDATORY Physical Execution Receipt（含探针 JSON 原文与手验输出）。"

**Step Breakdown:**
- [ ] **Step 1: 写探针 + wrapper（RED，记录真实失败输出）**
- [ ] **Step 2: index.html 挂载点（去掉 `Online`、加 `id`、加 chip 锚点）**
- [ ] **Step 3: 实现 `static/js/update.js`（GREEN）**
- [ ] **Step 4: main.js import + `DOMContentLoaded` 接线**
- [ ] **Step 5: 跑探针 + 三条守卫测试（接线 / 契约 / 本测试）全绿**
- [ ] **Step 6: `python start.py` 手验三条路径（落后 / 最新 / 断网）**
- [ ] **Step 7: Physical Evidence Gate**
- [ ] **Step 8: Git atomic commit**

---

### Task 6: 门禁收口 + 双端手验 + 文档回填 [Mode: HITL] [Role: Release Steward]

**Files:**
- Modify: `WORKMEMORY/work.log`（按 `PROTOCOL.md` 追加事件）
- Modify: `WORKMEMORY/PROJECT_OVERVIEW.md`（ADR-0017 待办条目状态更新）
- Modify: `docs/adr/2026-10-08-adr-0017-android-update-check-notifier.md`（若 D2 的收窄需回写 ADR 正文）

**Interfaces:**
- Consumes: 前 6 个任务的产物
- Produces: 门禁收据 + 真机结论 + 文档回填

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: Measurement-From-Own-Run]`: 测试数必须来自**本次最终 commit 的本人实跑**，不得抄 maker 报告（v5.16.0 的 1048 vs 1053 错误）。
- [ ] `[Instinct: No-Truncated-Verification]`: 核验输出**禁** `head`/`tail` 截断（漏看失败项 + 吃掉退出码）。
- [ ] `[Instinct: Real-Device-Gate]`: Android 侧两条**未验证假设**必须真机确认（见 Fog of War），不得只凭 CI 绿就宣布可用。

**Subagent Prompt Scaffold (for /dfs-exec):**
> 本任务**不派 AFK 子代理**（HITL：需要真机与人工判断）。执行者按下列步骤操作并回报原始输出。

**Step Breakdown:**
- [ ] **Step 1: 全量门禁**：半 A（`pytest tests/ --ignore=tests/test_server.py`）+ 半 B（`tests/test_server.py`）+ 全部 `tools/*.mjs` 探针 + `ruff check .` + 两道 `mypy`
- [ ] **Step 2: 桌面端手验**：`python start.py` → 顶栏静态版本自证仍在；落后时 chip 出现且点击进 Release 页；断网时静默（无 chip、无 toast）
- [ ] **Step 3: Android 真机**（**阻塞项**，见 Fog of War）：①`/api/update/check` 在 Chaquopy 里真能完成 HTTPS 出网（TLS/CA）；②点击 chip 是否被交给系统浏览器（否则需改 `MainActivity` 的 URL 拦截——Java 本机无法编译，只能靠 CI）
- [ ] **Step 4: 文档回填**：work.log 事件 + `PROJECT_OVERVIEW` 待办勾销 + ADR 正文（D2 收窄）
- [ ] **Step 5: Physical Evidence Gate**（原始门禁收据 + 真机结论）
- [ ] **Step 6: Git atomic commit**（**不发版**——本计划不动发布面五件套中的 README，发版另行决定）

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Unknown 1] Android 上 httpx 能否完成到一个真实 HTTPS 外站（`api.github.com`）的请求（TLS/CA 链）。** 证据强度**不足**：`delector/routes/encounter.py:381` 的 `httpx.get(...)` 在手机上跑的是**手机→桌面的 LAN HTTP**（非 HTTPS），因此**不能**证明公网 TLS 可用。若真机失败 ⇒ 本功能的 Android 侧失效，需回 ADR 重议（可能重新打开被否决的 Option E「桌面端代查」）。**阻塞 Task 6 Step 3。**
- **[Unknown 2] Android WebView 点击外链（GitHub Release 页）是否被交给系统浏览器。** 未核 `MainActivity` 的 `shouldOverrideUrlLoading`。若在 WebView 内打开，体验降级但功能可用；若完全被吞，则需改 Java（本机无 Android SDK ⇒ 只能 CI 验证）。
- **[Unknown 3] 桌面包（PyInstaller 便携版）是否共用同一 chip 显示策略。** ADR 附带默认"两端共用"，但桌面端刷新即生效、更新价值较低；若造成噪音再定（需先有真实使用反馈）。
- **[Unknown 4] 提示疲劳的真实阈值。** ADR 已明确本轮**不做**"忽略此版本"；若一天一版下 chip 常驻造成困扰，届时另开决策（不得在本计划里悄悄加）。

---

## 🚫 Out of Scope

- 应用内下载 APK、唤起安装器、`REQUEST_INSTALL_PACKAGES`、FileProvider、`DownloadManager` 分流（ADR-0017 Option B / Q1-A 否决）
- 静默安装（Android 平台不允许，非取舍问题）
- 自建更新服务、差分更新、恢复三 ABI
- 前端直连 GitHub API（Q3-B）、热更新 `static/`（Option D）、LAN 桌面代理代查（Option E）
- "忽略此版本" / 更新日志弹窗 / 自动下载 / 遥测上报
- 本次**不发版**（不动 README 下载表与 badge；发布面五件套不在本计划范围）
