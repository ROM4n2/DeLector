# Workbench 背词进度存到电脑 server（真·自动同步）实施计划

> **Goal**: 让 workbench 的背词进度 `{words, cards, log, wrong, settings}` 从「只存浏览器 localStorage/IndexedDB」迁移为「本地 + server 双读双写」，实现手机/电脑浏览器连同一台 server 时自动同步、任一端刷新看到另一端所背。
> **Tech Stack**: Python 3.11 / FastAPI / SQLite（后端）＋ 原生 ES Modules `static/german/workbench.html`（前端）。
> **Spec Reference**: `docs/plans/workbench-progress-server-sync.md`（本文件）；ADR-0003 `08-Projects/_template/01-ADR/0003-lan-sync-short-code.md`；`DELECTOR-DEV-RULES §2.1 本地优先与离线首选`。
> **执行模式**: 每个 Task 是独立、原子、可单独交给一个 subagent 的提交。TDD：先写测试（RED）→ 跑出失败 → 实现（GREEN）→ 跑绿 → refactor → `git commit`。
> **Global Constraints**: 测试用 `$env:PYTHONIOENCODING="utf-8"; pytest <file> -k <expr> -v`；JSON 序列化 `ensure_ascii=False`；前端 `fetch` 加 `cache:"no-store"`；**不删 localStorage/IDB**（本地优先）；单用户、无账号体系；不用 `DEEPSEEK_API_KEY` 混作同步密钥；不改 FSRS 引擎。

---

## 0. 背景与现状（执行前必读）

### 数据在哪、存成什么
`static/german/workbench.html` 的背词进度全部是**浏览器本地**数据，不落 server：

| 数据 | 变量 | localStorage 键 | 写入函数 |
|---|---|---|---|
| 词表（含 FSRS-6 每词状态） | `S.words` | `K.words = "wb.words.v1"` | `saveWords()`（`workbench.html:1049`） |
| 每词卡状态 `{s,d,due,last,reps,lapses}` | `S.cards` | `K.cards = "wb.cards.v1"` | `saveCards()`（`:1050`） |
| 每日复习统计 `{rv,good,hard,again,nw,qz,qzOk}` | `S.log` | `K.log = "wb.log.v1"` | `saveLog()`（`:1051`） |
| 错题本 `{n,t,m}` | `S.wrong` | `K.wrong = "wb.wrong.v1"` | `saveWrong()`（`:1052`） |
| 设置 `{retention,dailyNew,newOrder,planDate,theme,tts}` | `S.settings` | `K.set = "wb.settings.v1"` | `saveSettings()`（`:1053`） |

- 每个 `saveXxx()` 都是 **`localStorage.setItem(...)` ＋ `idbPut(...)`** 双写。`IndexedDB` 是本地镜像 + 快照备份（≤7 条），同样是每浏览器/Origin 本地。
- 启动流程 `loadAll()`（`:962`，调用点 `:3505`）从 localStorage 读 `S`，空词表用 `SEED_WORDS` 等硬编码数组兜底。
- **`applyMerge(data)`**（`:3366`）是已有的合并函数，可复用：每卡按 `last`（最近复习时间）取新、日志每字段取 `Math.max`、错题本取次数多者、单词按 id＋归一词头双索引。**不要新写合并逻辑，直接用这个。**

### 后端现状（无现成可复用的）
- `vocab_cards`/`grammar_cards`（`database.py`）是**文章派生卡**（带 `article_id`/`lemma`/`sentence_context`），与 workbench 词库**模型不同、不能用**。
- `/api/wb/backup/*`（`server.py:1387` `WbBackupReq`）只是**内存下载中转**（token 指定内存 payload，不落盘）。
- `/api/wb/sync/*`（`routes_sync.py`）只是 WebRTC SDP 信令。
- 结论：**后端需要新表 + 新端点**，无现成可复用。

### 关键既有工具（Task 直接用）
- `database.py:149 init_db()` —— 建表（幂等，`CREATE TABLE IF NOT EXISTS`）。
- `database.py:297 get_setting(key, default)` / `:308 set_setting(key, value)` —— `app_settings` kv 读写，存同步密钥用。
- `server.py:43 from database import (...)` —— 已 import 的 database 函数集合（新增函数需加进 import 列表）。
- `server.py:12 from fastapi import FastAPI, HTTPException, Request` —— `Request` 已导入，`_require_localhost` 已 import（server.py:71）。
- `test_server.py` 的 `client`（`TestClient(app, client=("127.0.0.1", 54321))`，本机地址）与 `lan_client`（`client=("192.168.1.77", 54321)`，模拟局域网）两个 fixture；`clean_db` autouse 清理并 `init_db`。**用 `lan_client` 测「局域网能否访问/写」，用 `client` 测「仅本机能拿 key」。**

### 执行顺序与依赖
Task 1 → Task 2 → Task 3 → Task 4。Task 1/2 独立完成即可跑测试；Task 3 依赖 Task 2 的端点；Task 4 是收口锁定 + 全量回归 + 手动验证。

---

## Task 1: SQLite `wb_state` 表 + 读写辅助

**Files:**
- Modify: `database.py`（`init_db()` 内 `~:254-260` app_settings 建表区之后新增建表；新增 2 个函数）
- Test: `test_server.py`（新增）

**Interfaces:**
- Consumes: `get_db()`、`json`、`datetime`
- Produces: `get_wb_state() -> dict`、`save_wb_state(payload: dict) -> None`

**Subagent Prompt Scaffold:**
> Implement Task 1: SQLite wb_state 表 + 读写辅助函数。
> Goal: 在 `database.py` 建单行表 `wb_state(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL, updated_at TEXT NOT NULL)`，并新增两个函数：
>   - `get_wb_state() -> dict`：`get_db()` 读 `id=1` 的 `payload`，`json.loads`；无则返回 `{}`；解析异常返回 `{}`。
>   - `save_wb_state(payload: dict) -> None`：`json.dumps(payload, ensure_ascii=False)` + `datetime.now().isoformat()`，用单行 upsert：`INSERT INTO wb_state(id,payload,updated_at) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at`。
> Target Files: Modify `database.py`，Test `test_server.py`。
> TDD Steps:
> 1. 在 `test_server.py` 写 `test_wb_state_roundtrip()`：先 `save_wb_state({"words":[]})`；再 `assert get_wb_state() == {"words":[]}`；再 `save_wb_state({"words":[1]})` 覆盖；`assert get_wb_state() == {"words":[1]}`；`get_wb_state()` 空态（新 DB）返回 `{}`。写一个 `test_wb_state_empty_returns_empty_dict()` 断言空 DB 返回 `{}`。
> 2. 跑 `$env:PYTHONIOENCODING="utf-8"; pytest test_server.py -k wb_state -v`，验证因函数不存在而 RED（NameError / ImportError）。
> 3. 在 `database.py`：`init_db()` 内（app_settings 建表后）加 `conn.execute("""CREATE TABLE IF NOT EXISTS wb_state (...)""")`；在文件加 `get_wb_state()` / `save_wb_state()` 两个函数（放 `init_db` 附近）。若 `database.py` 有 `__all__` 列表，把两个函数加进去。
> 4. 跑同测试，确认 GREEN。
> 5. Refactor：`get_wb_state` 用 Guard Clause（`if not row: return {}`、`try/except json 解析 → return {}`）；`datetime.now()` 只调一次存变量。
> 6. `git add database.py test_server.py && git commit -m "feat(wb): wb_state 表 + get/save_wb_state 辅助"`。
> Return: 测试执行证据（`pytest ... -k wb_state` 的 pass 输出）。

- **风险**：`init_db` 有缓存/幂等要求，建表必须 `CREATE TABLE IF NOT EXISTS`；`clean_db` autouse 会删重建，确保不依赖旧表。

**Step Breakdown:**
- [x] **Step 1: Write failing test `test_wb_state_roundtrip` (RED)**
- [x] **Step 2: Run `pytest test_server.py -k wb_state -v` verify red**
- [x] **Step 3: Implement table + 2 functions (GREEN)**
- [x] **Step 4: Run verify green**
- [x] **Step 5: Refactor with guard clauses**
- [x] **Step 6: Git atomic commit** → `82fcb9d`

---

## Task 2: `wb_sync_key` + `/api/wb/state` 三端点（鉴权）

**Files:**
- Modify: `database.py`（新增 `get_wb_sync_key()`）、`server.py`（新增 `WbStateReq` pydantic 模型 + 3 个端点 + `import secrets`）
- Test: `test_server.py`

**Interfaces:**
- Consumes: `get_wb_state()`、`save_wb_state()`、`get_wb_sync_key()`、`_require_localhost()`、`get_setting()`/`set_setting()`、`secrets`
- Produces:
  - `GET /api/wb/state` → 返回 `get_wb_state()`（**放行**，局域网可读）
  - `PUT /api/wb/state` → 校验 `request.headers.get("X-WB-Key")`，不符 `HTTPException(403)`，符则 `save_wb_state(req.payload)` 返回 `{"ok": True, "updated_at": ...}`
  - `GET /api/wb/state/key` → `_require_localhost(request)` 后返回 `{"key": get_wb_sync_key()}`（**仅本机**可取）

**Subagent Prompt Scaffold:**
> Implement Task 2: 同步密钥 + /api/wb/state 三个端点。
> Goal: (1) 在 `database.py` 加 `get_wb_sync_key() -> str`：用 `get_setting("wb_sync_key")` 读，为空则 `secrets.token_hex(16)` 生成并 `set_setting("wb_sync_key", key)` 持久化，返回 key。(2) 在 `server.py` 加 `import secrets`（若无）。加 pydantic 模型 `class WbStateReq(BaseModel): payload: Dict[str, Any] = {}`（挂在 `WbBackupReq` 附近，`:1387`，注意 `Dict`/`Any` 已导入）。加 3 个端点：`GET /api/wb/state`（返 `get_wb_state()`）、`PUT /api/wb/state`（校验 `X-WB-Key`）、`GET /api/wb/state/key`（`_require_localhost` 后返 key）。
> Target Files: Modify `server.py` / `database.py`，Test `test_server.py`。
> TDD Steps:
> 1. 写测试（用 `client`，本机）：
>    - `test_wb_sync_key_local_only()`：`client.get("/api/wb/state/key")` → 200 且 `"key"` 是 32 位 hex；`lan_client.get("/api/wb/state/key")` → 403（key 仅本机可取）。
>    - `test_wb_state_put_requires_key()`：`client.put("/api/wb/state", json={"payload":{"cards":{}}})`（无 header）→ 403；带错 header → 403；先 `GET /api/wb/state/key` 拿 `key`，带对 `X-WB-Key` PUT → 200，再 `GET /api/wb/state` 回读一致。
>    - `test_wb_state_cross_device_write()`：`lan_client`（模拟局域网另一设备）带对 key 也能 PUT 成功 → 200（跨设备写是需求核心），且 `client.get` 回读一致。
> 2. 跑 `pytest test_server.py -k wb_state -v`，验证 RED（端点 404 / 403）。
> 3. 实现：`database.py` 加 `get_wb_sync_key()`；`server.py` 加 `import secrets`、`WbStateReq`、3 端点。把 `get_wb_state`/`save_wb_state`/`get_wb_sync_key` 加进 `server.py:43` 的 `from database import (...)` 列表。
> 4. RUN GREEN。
> 5. Refactor：`PUT` 先拿 `key = get_wb_sync_key()`，再 `if request.headers.get("X-WB-Key") != key: raise HTTPException(403)`，早退；`get_wb_sync_key` 里先 `get_setting` 判空再生成。扁平化，不超过 2 层缩进。
> 6. `git commit -m "feat(wb): /api/wb/state 同步端点 + wb_sync_key 鉴权"`。
> Return: 测试执行证据（pass 输出）。注意：`lan_client` 的模拟局域网设备**应能写入**且本机可读出——这验证了「手机背词能存进电脑 server」。

- **风险**: `WbStateReq` 缺 `payload` 时须默认 `{}`；`lan_client` 用非 127.0.0.1 地址测鉴权，但本测试里 `lan_client` 带对 key 应能写（key 不在 IP 上限制，在 header）。`get_wb_sync_key` 要能被 `lan_client` 的请求携带——测试里先 `client.get key` 拿到 key 再传给 lan 设备，符合实际「电脑上生成，手机带过来」。

**Step Breakdown:**
- [x] **Step 1: Write failing auth tests (RED)**
- [x] **Step 2: Run verify red**
- [x] **Step 3: Implement endpoints + key (GREEN)**
- [x] **Step 4: Run verify green**
- [x] **Step 5: Refactor guard clauses**（key 校验早退）
- [x] **Step 6: Git atomic commit** → `7a7340f`

---

## Task 3: workbench 前端 `wbsync` 同步模块

**Files:**
- Modify: `static/german/workbench.html`
- Test: `test_frontend_module_graph.py`

**Interfaces:**
- Consumes: `S`、`saveWords/saveCards/saveLog/saveWrong/saveSettings`、`applyMerge(data)`（`:3366`）、`loadAll()`（`:962`）、`K`（storage keys）
- Produces: `window.__wbsync`（`init()` / `push()` / `pushNow()` / `flush()` / `pollStart()`）

**Subagent Prompt Scaffold:**
> Implement Task 3: workbench.html 内联 `wbsync` 同步模块。
> 现状：`static/german/workbench.html` 纯前端，数据在 `S`（内存）+ localStorage/IDB（本地双写）。新增一个自包含 `wbsync` 对象，让进度在「连上 server」时自动上报 + 拉取，离线时静默。
> Goal: 在文件靠近存储层（`saveXxx` 定义 `:1049-1053` 之后）新增：
>   ```
>   const wbsync = {
>     _key: null, _timer: null, _seq: 0,
>     async init() {
>       try {
>         const kr = await fetch("/api/wb/state/key", { cache: "no-store" });
>         if (kr.ok) this._key = (await kr.json()).key;
>         const r = await fetch("/api/wb/state", { cache: "no-store" });
>         if (!r.ok) return;
>         const d = await r.json();
>         if (d && (d.cards || d.words)) { applyMerge(d); renderReview(); renderHeaderBadge(); }
>         this.pollStart();
>       } catch (e) { /* 离线静默 */ }
>     },
>     push() {
>       if (!this._key) return;
>       clearTimeout(this._timer);
>       this._timer = setTimeout(() => this.pushNow(), 800);
>     },
>     async pushNow() {
>       if (!this._key) return;
>       try {
>         await fetch("/api/wb/state", { method:"PUT", cache:"no-store",
>           headers:{ "Content-Type":"application/json", "X-WB-Key": this._key },
>           body: JSON.stringify({ payload: { words:S.words, cards:S.cards, log:S.log, wrong:S.wrong, settings:S.settings } }) });
>       } catch (e) { /* 静默 */ }
>     },
>     pollStart() { setInterval(async () => {
>         try { const r = await fetch("/api/wb/state", { cache:"no-store" });
>           if (!r.ok) return; const d = await r.json();
>           if (d && (d.cards || d.words)) { applyMerge(d); renderReview(); renderHeaderBadge(); } } catch (e) {}
>     }, 5000); },
>   };
>   ```
>   然后：
>   - 在 5 个 `saveXxx()`（`:1049-1053`）末尾各追加 `wbsync.push();`。
>   - 在启动块 `loadAll()`（`:3505`）之后的异步块里调 `wbsync.init();`。
>   - 注册 `window.addEventListener("beforeunload", () => wbsync.pushNow());` 与 `document.addEventListener("visibilitychange", () => { if (document.hidden) wbsync.pushNow(); });`。
>   - 在 `window.__wb` 调试出口（`:3545`）加 `wbsync` 便于手测。
> Target Files: Modify `static/german/workbench.html`，Test `test_frontend_module_graph.py`。
> TDD Steps:
> 1. 在 `test_frontend_module_graph.py` 加 `test_wbsync_module_present`:读 workbench.html 源码断言含 `const wbsync =`、5 个 `saveXxx()` 定义行内含 `wbsync.push()`、含 `wbsync.init()` 调用、含 `visibilitychange` 监听。（用源码字符串断言即可，参照该文件已有测试风格。）
> 2. 跑 `pytest test_frontend_module_graph.py -v` 验证 RED。
> 3. 实现 wbsync + 挂 hook。
> 4. GREEN。
> 5. Refactor：`applyMerge(d)` 前判断 `d && (d.cards || d.words)`；`pushNow` 前 `if (!this._key) return` 早退；所有 fetch 用 try/catch 静默；避免监听器重复（每次 init 只调一次，或加 guard）。
> 6. `git commit -m "feat(wb): workbench wbsync 同步模块(读取合并+保存推送+轮询)"`。
> Return: 测试执行证据 + 你实现的 `wbsync` 关键代码片段。
> 高危注意：`applyMerge` 是**同步函数**直接改 `S`，调后必须 `renderReview()`/`renderHeaderBadge()` 刷新 UI；`S` 是模块级，勿在 async 里 await applyMerge。`init()` 里 `applyMerge` 要在 `S` 已 loadAll 填充后才调。

- **风险**: 不要在 `init()` 的 fetch 前面丢 `_key` 未拿到的竞态；`applyMerge` 会合并 `S`，若 server 数据是空对象不要动本地；轮询 5s 若多次 merge 判断 `updated_at` 避免反复重排 UI（可选优化，不强求）。

**Step Breakdown:**
- [x] **Step 1: Write feature-presence test (RED)**
- [x] **Step 2: Run verify red**
- [x] **Step 3: Implement wbsync module + hooks (GREEN)**
- [x] **Step 4: Run verify green**
- [x] **Step 5: Refactor/guard**（key 缺失早退、fetch 静默、防重复监听）
- [x] **Step 6: Git atomic commit** → `b0b904f`（后补 `8947276`：GET fetch 加 `cache:"no-store"`）

---

## Task 4: 落盘锁定 + 全量回归 + 手动验证

**Files:**
- Test: `test_server.py`（增量：落盘重启锁定）

**Subagent Prompt Scaffold:**
> Implement Task 4: 落盘锁定测试（验证数据真存 disk 非内存）+ 全量回归。
> Goal: 补一条断言「`save_wb_state` 后，即使重新 `init_db`（模拟 server 进程重启）仍能 `get_wb_state` 回读」，证明落盘。生产代码 Task1-3 已完成，本任务只加锁定测试 + 全量回归。
> Target Files: Test `test_server.py`。
> TDD Steps:
> 1. 写 `test_wb_state_survives_reinit()`：用 `save_wb_state({"x":1})` 写 → `get_db 关闭` → 重新 `init_db(db_path)` → `get_wb_state()` 回读 `{"x":1}`。注意用与 test 一致的 `test_delector.db` 路径，`clean_db` 一次只建一次 DB，此测试内自行描述重开流程（可直接 `init_db()` 再读，SQLite 单文件本身持久，证明在 disk）。
> 2. `pytest test_server.py -k wb_state -v` GREEN。
> 3. 跑全量 `$env:PYTHONIOENCODING="utf-8"; pytest -q`，确认当前 454 全绿、`wb_state` 相关新测试数正确。
> 4. `git commit -m "test(wb): wb_state 落盘锁定 + 全量回归"`。
> 手动验证（如可运行）：`python start.py` → 浏览器打开 `http://localhost:8000/workbench.html` → 背词 → `sqlite3` 查 `wb_state.payload` 非空 → 另一标签刷新看到。kill 进程重开 server + 刷新浏览器，进度保留。此步为人工，不写入 pytest。
> Return: 全量 `pytest -q` 末尾输出（`X passed`）与落盘测试的 pass 输出。

- **风险**: 若 `clean_db` autouse 在测试结束用 `os.remove` 删 DB，`test_wb_state_survives_reinit` 内部重新 `init_db` 可能因 DB 已被 remove 而重建——用与 fixture 一致的 `test_delector.db` 路径即可。

**Step Breakdown:**
- [x] **Step 1: Write persistence test (RED)**
- [x] **Step 2: Run verify red**
- [x] **Step 3: Confirm green (no prod change)**
- [ ] **Step 4: Full `pytest -q`**（执行期被跳过：运行超时/用户选择不等；任务已按定向回归 + 冒烟验证，全量请手动补跑）
- [x] **Step 5: Git atomic commit** → `50c839e`

---

## Verification（全部 Task 完成后）

1. `pytest test_server.py -k "wb_state"` —— ✅ 6 passed（Task1/2/4 后端测试；本计划新增 6 条）。
2. `pytest test_frontend_module_graph.py` —— ✅ 8 passed（含 Task3 新增 3 条）；`test_german_workbench.py` 73 passed（HTML 契约未破坏）。
3. 全量 `pytest -q` —— ⏳ 执行期被跳过（用户选择不等）；已补跑 `test_server.py`（199 passed）、前端/HTML 契约集（90 passed）、`test_goethe_a1 + test_writer_mobile + test_writing_rules + test_essay_diff + test_start`（91 passed）。全量请手动补跑确认（预计 454 基线 + 9 新测试）。
4. `git log --oneline` —— ✅ 5 个原子 commit：`82fcb9d` `7a7340f` `b0b904f` `50c839e` `8947276`。
5. 手动（人工）：✅ 冒烟完成（scratch DB + uvicorn 真实启动）：key 32hex / PUT 200 / GET 回读一致 / 无 key PUT 403；真实浏览器双端合并步留待人工。

## OOS（明确不做）

- 多用户/账号体系（单用户）。
- 改 FSRS-6 引擎（`workbench.html:1594+`，仍前端算，server 不重算）。
- WebSocket / SSE（轮询 + 保存推送足够）。
- 迁移 `vocab_cards`/`grammar_cards`（文章卡系统，独立，不复用）。
- 加密传输 / 鉴权升级（当前 API Key 明文 header 保护单用户自用足够）。

## Global Constraints Checklist

- [x] Python 测试环境变量 `PYTHONIOENCODING=utf-8`
- [x] JSON 序列化 `ensure_ascii=False`
- [x] SQLite 幂等建表（`IF NOT EXISTS`）
- [x] 前端 fetch `cache:"no-store"`（wbsync 两个 GET fetch 均已加）
- [x] 不删 localStorage/IDB（本地优先原则，`DELECTOR-DEV-RULES §2.1`）
- [x] 单用户无账号
- [x] 同步密钥独立于 `DEEPSEEK_API_KEY`
- [x] 复用 `applyMerge`，不重写合并逻辑

## 2026-09-02 事故补记（commit `df625c4`，vault-debug）

**症状**：上线后跨设备仍看不到词汇进度——服务端 wb_state 行永远 `{}`。

**根因**：`pushNow()` 发 `JSON.stringify(snapshot())` 裸快照，而 /api/wb/state 契约是
`WbStateReq{payload}`（server.py:1424）→ payload 取不到默认 `{}` → GET 永远空 →
进度永不合并。Task3 的存在性测试只断言字符串在不在（静态死测），抓不住契约断裂。

**修复**：body 改 `JSON.stringify({ payload: snapshot() })`。

**回归固化**：tools/wb_sync_probe.mjs（真 wbsync 源码 node:vm 切片 + 桩 fetch 抓实际
请求体，契约破坏 exit 1）+ `test_wbsync_put_body_wraps_payload`（变异验证已实跑：
退回裸快照 → 红；恢复 → 绿）。回归 74 + 8 + 6 全绿。

**教训**：前后端跨边界契约测试禁止只做单侧字符串存在断言；用「真源码抓实际请求体」
的行为探针把两端钉在一起。HTTP 冒烟用 curl/fetch，勿用 urllib（PUT body 解析怪异）。

## 2026-09-03 手机拉取事故补记（commit `d0f271e`，vault-debug）

**症状**：手机（远端 IP）经服务端镜像看不到背词进度。

**根因**：wbsync 把「拉取镜像」(GET /api/wb/state) 也锁在「先拿到 key」之上，而
`/api/wb/state/key` 是 `_require_localhost`（仅本机），手机永远 403 → `_enabled=false`
→ `pull()` 永不触发。这与 server.py:1419「GET 镜像放行局域网、手机拉取不需 key」矛盾。

**修复**：`boot()` 不再因 /key 失败而禁用；`pull()` 守卫去掉 `!_key`（GET 无需鉴权）；
`push/pushNow` 仍保留 `!_key`（只有能 push 的客户端才需密钥）。

**回归固化**：tools/wb_phone_pull_probe.mjs（模拟手机 /key=403 断言仍拉取并合并镜像进度）
+ `test_wbsync_phone_pulls_without_key`（变异验证已实跑：pull 守卫退回 `!_key` → 红；恢复 → 绿）。

**注意**：手机若以 file:// 加载 workbench.html（Android 打包资源），相对路径 fetch
`/api/wb/state` 会解析失败（与 WebRTC 同理被禁），此修复覆盖「LAN IP 经 http 访问」场景。
手机→桌面反向同步仍走 WebRTC 短码（F5），与本修复（F3 自动拉镜像）是两条独立通道。

## 2026-09-03 跟进：手机后台 pull 频繁弹通知（commit `b493acd`，vault-debug）

**症状**：手机能看到进度后，背词时每 5s 轮询都弹「合并导入完成」通知、还把视图踢到 review。

**根因**：wbsync.pull() 发现本机与镜像有差异就调 applyMerge，而 applyMerge 末尾无条件
`toast(...)` + `showView("review")`。后台轮询是镜像同步，不是「导入完成」，不该有阻断式弹窗
（也违背前端规范 FRONTEND-DESIGN-PATTERNS）。

**修复**：`applyMerge(data, opts)` 加 `silent` 选项；`pull()` 改 `applyMerge(remote, { silent: true })`
（仅跳过 toast+showView，仍合并/落盘/刷新徽标）；显式导入与 WebRTC 同步保留通知。

**回归固化**：tools/wb_phone_pull_silent_probe.mjs + `test_wbsync_background_pull_is_silent`
（变异验证：pull 退回非静合并 → 重弹通知 → 红）。

**关于「电脑端数据没变」**：手机是远端 IP 拿不到 localhost 专属 key，wbsync 推送被禁用（只有
localhost 能 push 镜像），故手机背的词不会自动回写桌面。手机→桌面反向同步走 WebRTC F5 六位
短码（手动），或 `adb reverse tcp:8000 tcp:8000` 让手机成 localhost 拿 key 后自动推送。
