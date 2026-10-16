# 🏛️ Multi-Expert Swarm Audit Report: DeLector「非在途面」全量评估

**Date**: 2026-10-15
**Target Scope**: 仓库**除在途改动面之外**的全部代码（分支 `chore/swarm-audit-master` @ `9d6ce78`）
**Seats Dispatched**: `dba-optimizer`（数据库与存储）· `sre-resilience`（SRE 与可用性）· `code-reviewer`（代码质量与密钥）
**Seats Skipped（artifact 证据，不是"不相关"）**:
- `frontend-architect`：本轮目标里唯一有在途改动的前端（`static/js/writer.js` 与 ai-polish 契约）已被显式排除，剩余静态前端在 master 上无改动窗口；3 席位上限内优先持久层与可用性面。
- `perf-profiler`：目标内无新增热路径 / 内存池 / 锁级并发改动；`asyncio.to_thread` 与信号量由 sre 与 dba（锁范围）覆盖。
- `product-ux`：目标内无用户旅程 / CLI 变更面（在途旅程改动全在 ai-polish，已排除）。

**Findings**: **16** 条（合并后）← 原始 **35** 条（dba 15 / sre 13 / code-reviewer 7）—— 16 < 35，Collapse 成立
**Read scope**: 见文末「读过的面」；席位的越界发现一律点名移交，未私自判决。

---

## 🚨 Critical Findings (P0)

### P0-1 · `/api/backup/restore` 静默清空听力与长难句训练记录（**丢数据 + 零提示**）
- **[dba-optimizer]** [CONFIRMED]：失败场景 = 用户导出备份（数据在文件里）→ 还原 → `listen_trials` 与 `hard_sentence_trials` **永久归零**，接口仍返回 `{"status":"ok"}`、UI 弹「备份还原成功」。
- 机制（质疑席复核确认）：`_BACKUP_TABLES` 现读为 **10 张表**（含 `database.py:1573` `listen_trials`、`:1598` `hard_sentence_trials`），而 `RestoreReq`（`routes/main.py:1747-1768`）只声明 **8 张主库表**字段；全仓 0 处 `ConfigDict` ⇒ pydantic v2 默认 `extra=ignore` ⇒ 前端整份 POST 的这两键被丢弃；`_replace_tables`（`database.py:1895-1909`）对清单里**每张表无条件 `DELETE FROM`**（`database.py:1901`），随后 `payload.get(name) or []` 为空 ⇒ `continue` ⇒ **删光零回灌**。全仓这两张表只有 record/list 两处写入者，**无第二回灌路径**。席位已用真实 `_replace_tables` 在临时库复现（还原前 1/1 → 还原后 0/0）。
- *Impact*：任何一次还原（换机、误操作回滚）都不可逆抹掉训练记录；与 `database.py:1492-1496` 修过的「清单外 ⇒ 往返静默打回默认」是**同一类 bug 第二次发生** ⇒ 缺的是「清单 ↔ 还原模型」一致性守卫。
- *Verification*：CONFIRMED（质疑席逐环读码 + 复现）。
- 最小修法（两处都要）：① `RestoreReq` 补 `listen_trials` / `hard_sentence_trials` 两字段；② `_replace_tables` 加前向兼容闸 `if name not in payload: continue`，让"新增备份表忘了加字段"退化成"原样保留"而非"清空"；③ 契约测试断言 `set(_BACKUP_TABLES) - set(RestoreReq.model_fields) == set()`。

### P0-2 · 退出路径挂死 + 假成功日志 ⇒ 端口被占、下次启动连到旧实例
- **[sre-resilience]** [CONFIRMED，**机制经质疑席纠正**]：席位原报的根因是 `Server.shutdown()` 里 `wait_for(timeout=None)` 无限等 —— 质疑席核实：本仓 `server_lifecycle.py:65-76` 的 `shutdown()` **根本没调** `Server.shutdown()`，它是 `should_exit=True` + `thread.join(5.0)`，**有界且如实返回 False**。真正的挂死在 `start.py`：
  1. `start.py:180` `thread.join()` **无超时**；
  2. `server_lifecycle.py:60` 起的 uvicorn 线程是 **`daemon=False`**（属实）；
  3. `start.py:186` **丢弃** `shutdown()` 返回值，`:187` 却无条件 `print("[提示] 服务已停止。")`；
  4. `start.py:232` 裸调 `main()`、**无 `SystemExit`** ⇒ 解释器退出时 `threading._shutdown()` 再 join 那个非 daemon 线程 ⇒ **「已停止」已打印、进程仍挂、端口 8000 仍占**。下次启动 `start.py:204 _handle_existing_port` 经 `probe_identity` 命中旧实例 → 打印「DeLector 已在运行」并打开**旧实例**（与本仓历史「孤儿 uvicorn 让门禁假绿」同形）。
  ⚠️ `server_lifecycle.py:50` 未设 `timeout_graceful_shutdown` 属实（uvicorn 默认语义无法在本工作区核实 site-packages，但结论不依赖它）。
- *Impact*：静默残留 + 假成功 + 下次连到旧实例；退出瞬间存在 >5s 在途请求即可触发（TTS 最坏 ~78s、`/api/backup/restore` 持写锁数秒~数十秒、抓取最多 6 跳 × 15s）。
- *Verification*：CONFIRMED（质疑席给了纠正后的机制与关键行）。
- 最小修法：① `build_server` 加 `timeout_graceful_shutdown=5`；② `start.py:186-187` 改成 `if not shutdown(server, thread): print("[错误] 服务未能干净退出…", file=sys.stderr); sys.exit(1)`；③ `start.py:180` 的 `thread.join()` 不许裸等。

---

## ⚠️ Critical Findings (P1)

### P1-1 · 备份 JSON 会带走 `wb.pair.v1`（长期同步密钥 + 内网地址），绕过后端白名单
- **[code-reviewer + dba-optimizer]**（**同一缺陷，已合并**）[CONFIRMED]
- 链路（两席各自读码、质疑席复核确认）：`database.py:806` `wb_sync_key` = `secrets.token_hex(16)`、**不轮换**，只有手动撤销才失效 → `static/german/workbench.html:1410-1419` 写进 `localStorage["wb.pair.v1"] = {host, key}`（`static/js/encounter.js:1295` 的 `if (p && p.host && p.key)` 反证该键**确含长期密钥**）→ `static/js/cards.js:1017` 按 `wb.` 前缀**全扫**且无 exclude（唯一的排除表 `BACKUP_LS_TRANSIENT` 只作用于 `delector_` 前缀）→ `main.py:1636` `payload["local_storage"] = req.local_storage or {}` **原样透传落盘**（`PrepareBackupReq` 是裸 `Dict[str, Any]`）→ 而 `database.py:1444` 的 `BACKUP_SETTINGS_WHITELIST` **明确排除** `wb_sync_key`，注释写明「备份 JSON 是用户会分享/上传网盘的文件」。还原侧 `cards.js:1075-1076` 还会把备份里的 `wb.pair.v1` **写回本机**（换机还原 = 密钥迁移，也可能被指向他人主机）。
- *Impact*：长期凭据外泄（拿到文件即可对 `http://<host>:8000` 发 `PUT /api/wb/state` 覆盖学习镜像、投 RTC 信令）；后端白名单设计再严也挡不住这条 localStorage 侧门。
- *Verification*：CONFIRMED。
- 最小修法（纵深两道）：① `cards.js` 的 `backupLocalStorageKeys()` 加 `BACKUP_LS_EXCLUDE = {"wb.pair.v1"}`，**导出与还原两侧都过滤**；② `main.py:1636` 后端按键名黑名单过滤（权威闸必须在后端，前端可被绕过）；③ 契约守卫：带 `wb.pair.v1` 打 `/api/backup/prepare` ⇒ 断言下载体不含该键且 `delector_voice` 仍在（**同时必须改 `tests/test_server.py:1031`，它把"原样透传"钉成了契约**）。

### P1-2 · 备份不是跨表一致快照
- **[dba-optimizer]** [CONFIRMED]：`build_backup_payload`（`database.py:1734-1765`）是裸 `conn.execute("SELECT * …")` 循环；`database.py:163/174` 的 `sqlite3.connect(path)` 未传 `isolation_level`（默认 legacy `""`），全模块 **0 处 `BEGIN`** ⇒ 每条 SELECT 各自读"执行瞬间的最新提交"；主库与 progress 库还是两个独立连接。与 `database.py:1811-1817` 自己写下的「文件拷贝会拿到不一致快照，故用 backup API」标准**直接冲突**——JSON 这条用户真在用的路径没有同等保证。
- *Impact*：极端情况下导出/还原得到跨表时间不一致的混合体；无外键约束 ⇒ 孤儿行会原样往返。质疑席补充：**窗口是毫秒级、严重性低**。
- 最小修法：`build_backup_payload` 内 `BEGIN DEFERRED` → 读完 `COMMIT`（每库内一致；**两库之间仍不可能原子**，这点应写进注释而非假装解决）。

### P1-3 ~ P1-5 · sre 席位自报的三条（**未做对抗复核，标记 UNVERIFIED**）
> 协议要求 P1 必须过质疑席；本轮质疑预算只覆盖了 5 条（A–E），以下三条**未验证**，不得据此下阻塞结论，但需尽快补证：
- **[sre-resilience]** [UNVERIFIED] **P1-3**：`core/security.py:177-237` 出网抓取全程**无 `try/except httpx.HTTPError`**，且 `delector/` 全树 **0 处 `exception_handler`** ⇒ DNS/连接/超时一律笼统 500（`routes/encounter.py:380-389` 有 502 人话，两处口径不一致）；`timeout=15` 是**每操作**而非总截止 ⇒ 最多 6 跳 ≈ 90s，慢滴服务器可让请求无限期存活。
- **[sre-resilience]** [UNVERIFIED] **P1-4**：`agent/internal/pythonsvc/supervisor.go:245-267` + `:279` —— `MaxRestarts=5` 是**单次 episode** 配额，`supervise` 每轮崩溃后 `tries` 归零 ⇒ **重启次数无累积上界**、跨 episode **零退避** ⇒ crash-loop 以最快速度反复拉起 uvicorn，且 `Failures()` 永不上报（静默）。
- **[sre-resilience]** [UNVERIFIED] **P1-5**：`agent/internal/llm/deepseek.go:76 + :160 + :96-106` —— 单条 `Complete` 最坏 `4×120s + 退避 ≈ 483s`；退避是**纯确定性** `500ms<<attempt`、无 jitter ⇒ 429 时多 worker **同步重试**形成放大尖峰。

### ⬇️ 降级的原 P1
- **[sre-resilience]** 原 **P1-1（桌面壳 `os._exit(1)`）** → **质疑席推翻**：`desktop.py:524-528` **只有** `shutdown()` 返回 False（5s 宽限未停干净）才走 `exit_fn(1)`，干净退出走 `:525 return True` ⇒ 退出码 0 ⇒「正常退出也报 exit 1」**不成立**；截断只发生在超时分支（sqlite 逐请求提交 + WAL ⇒ 只丢在途那一笔）。**降级为 P2-9**，按设计取舍（"宁可硬杀也不留残留"）处理。

---

## 🔧 Improvements & Suggestions (P2)（合并后，按主题归并；dba 的 P2 多带"规模阈值"结论，当前不建议动）
1. **[code-reviewer]** [UNVERIFIED] `main.py:1478-1497`：`GET /api/settings` **无** `_require_localhost`（同文件 POST 有闸），同 Wi-Fi 可拿到 `api_key_masked`（首尾各 4 位）/ `api_base_url` / `api_model`。修法**不是**直接加 localhost 闸（手机经 LAN 打开会 403），而是**非回环来源剔除 `api_key_masked`**。
2. **[code-reviewer]** [UNVERIFIED] `main.py:1543-1544`：上游响应体前 100 字符原样回显客户端（若 `API_BASE_URL` 指向回显请求头的代理，Bearer 可能出现）。建议只留状态码 + 固定文案，细节进日志（**由 code-reviewer 终判**）。
3. **[sre-resilience + code-reviewer]** [UNVERIFIED] TTS 三连：`services/tts.py:270/313-316` 任意异常一律重试一次且零退避、连接超时 30s 偏长；`:128-131` **静默**退回 `ssl._create_unverified_context()`（证书校验被悄悄关掉，**静默失败**）；`main.py:1250` 兜底 provider 失败原因**零痕迹**。
4. **[sre-resilience]** [UNVERIFIED] `main.py:1304-1306` TTS 并发闸 TOCTOU：`if sem.locked(): raise 429` 与 `await acquire()` 非原子 ⇒ 后到者会**静默排队最长 ~78s**，与「MUST NOT 排队」自述纪律相悖。改 `wait_for(acquire(), timeout=0)`。
5. **[sre-resilience]** [UNVERIFIED] `routes/encounter.py:381/384-385`：抽屉抓取响应体**无大小上界**且真实状态码被丢弃 ⇒ 404（pack 不在货架）被误诊成"检查 WiFi/防火墙"。
6. **[code-reviewer]** [UNVERIFIED] 静默吞错两处：`main.py:1368-1373` `clear_audio_cache` 的 `except Exception: pass` 且 `freed_mb` 用**清理前**的 `info`（UI 报的数与实际不符）；`core/security.py:351-352` `parse_rss_feed` 整体 `except Exception: pass`。
7. **[code-reviewer]** [UNVERIFIED] **CI 无密钥扫描**：三份 workflow 全无 secret-scan 步骤；本地 `.githooks/pre-commit` 装了但**网页端编辑 / 新机器 = 零拦截**。建议复用现成脚本加一步（不引新依赖）。
8. **[code-reviewer]** [UNVERIFIED] 两处测试问题：`tests/test_desktop_shell.py:2109` `assert sys.stdout is not None` 在 pytest 下**恒真**（零判别力）；`tests/test_server.py:1031` 把"local_storage 原样透传"钉成契约（**是 P1-1 修法的对撞点**，必须同批改）。
9. **[dba-optimizer]** [UNVERIFIED] 持久层一组（**全部带阈值，当前规模不建议动，只为防复制该模式**）：`_pending_backup/_pending_wb` 全局槽**无锁**（并发 prepare 可能串号）；`database.py:148-159` 三条 PRAGMA 共用 `try/except: pass`（WAL 切换失败 ⇒ 后两条静默不生效）；`stats_json` 不在 `_BACKUP_TABLES["articles"]` 列元组 ⇒ 还原后永久 NULL 且不自愈；`data_dir_bootstrap.py:219-241` 两库**非原子**复制 ⇒ progress.db 可能停在半迁移（`preflight_data_dir` 只守主库）；`progress.db` **没有** ALTER 迁移路径（旧库缺列 ⇒ 每次 INSERT 失败且只 `print` 一行）；`api/cards/due` 的 `id ASC` 吃掉排序索引（20k 卡差 ~6ms）；`api/cards/known-lemmas` 三列 OR 全表扫（20k 卡 21.7ms）；`essays` 无 `updated_at` 索引（>1000 篇才值）；`import_encounter_pack` 的 SELECT-then-INSERT 竞态；`/api/search` 全表扫（>1000 篇才值）。
10. **[sre-resilience]** [UNVERIFIED] 其它：`workbench.html` 轮询无 jitter、`_pollTimer` 从不 `clearInterval`、fetch 无 `AbortSignal.timeout`；`GET /api/wb/state` 无大小闸（与 rtc/sync 的 32KB 不一致）；`supervisor.go:390-399` kill 后 `<-done` **无第二超时**；`cmd.Stdout` 直连父 stdout **无轮转**；长写事务期间 `/api/health` 会因 `busy_timeout=5000` 误报 503（Go 探针会据此判启动失败）。

---

## 💡 Consensus Action Plan（有序）

1. **先修 P0-1（丢数据）**：`RestoreReq` 补两字段 + `_replace_tables` 前向兼容闸 + 契约测试。这是唯一"用户数据不可逆丢失且零提示"的缺陷，优先级最高。
2. **再修 P0-2（退出挂死）**：`timeout_graceful_shutdown=5` + `start.py` 尊重 `shutdown()` 返回值 + `thread.join()` 加超时。**注意按质疑席纠正的机制修，不要照席位原报的 `Server.shutdown()` 说法改。**
3. **P1-1（密钥进备份）**：前端 `wb.pair.v1` 双侧过滤 + 后端键名黑名单（权威闸）+ 契约守卫；**同时改 `tests/test_server.py:1031`**，否则新守卫与旧契约对撞。
4. **P1-2（快照一致性）**：`build_backup_payload` 内 `BEGIN DEFERRED`；注释写明"跨库仍非原子"。
5. **补证 P1-3~P1-5**（未验证的三条）：按席位给的精确命令实跑（抓取 500 vs 502、Go supervisor crash-loop、DeepSeek 退避 jitter），验证后决定是否升/降级。
6. **P2 批处理**：静默吞错（3 处）→ 密钥扫描进 CI → 两处测试问题 → 持久层那组按阈值"先登记、到规模再动"。

## ♻️ Reuse Ladder Check
- 全部修法均**不需新依赖、不需新模块**：复用 `database.py` 既有白名单常量位置与 `_BACKUP_TABLES` 清单、`cards.js` 既有的 `backupLocalStorageKeys()` 单一收集点、`test_audit_hardening.py` 既有契约测试文件、`core/security.py` 既有的 2MB 大小闸（给 encounter 抓取复用）、`asyncio.timeout`（3.11 stdlib）与 `secrets.compare_digest`（已在用）。
- 唯一"新增"是两处测试断言与一处常量集合，均为仓内既有模式的复制，非新抽象。

---

## 读过的面（席位自报，节选）
`core/database.py`（全文 + AST 取 `_BACKUP_TABLES` 键集）· `routes/main.py`（backup/restore/settings/TTS/health/wb 段）· `core/security.py`、`core/server_lifecycle.py`、`core/data_dir_bootstrap.py`、`core/vocab_pool.py`、`core/wb_auth.py` · `services/tts.py`、`services/search.py` · `routes/update.py`、`encounter.py`、`sync.py`、`rtc.py`、`search.py`、`listen.py`、`syntax_hard.py`（部分）· `desktop.py`、`start.py`、`server.py` · `static/js/cards.js`、`encounter.js`、`core.js` 及 `static/js/*.js` 全量检索 · `static/german/workbench.html`（wbsync/RTC/TTS/导入导出段）· `agent/internal/{llm/deepseek.go, job/runner.go, pythonsvc/supervisor.go}` · `.gitignore`、`.githooks/pre-commit`、`DeLector.spec`、`package_windows.py`、三份 workflow · 真实库 `delector.db`/`progress.db`（**只读 `EXPLAIN QUERY PLAN`**）+ 临时构造库（20k 卡 / 2k 篇）做规模测量。

**越界移交（未判）**：`services/tts.py` 的协议伪装（伪造 Chromium Cookie/Origin）→ security 席位；`WbStateReq.payload` 裸 `Dict` 导致的 `fsrs_s` 漏计 → data-correctness；`X-WB-Key` 明文过 LAN 的信任模型（现有设计注释自述为"单用户自用"取舍）→ 产品/安全决策。
