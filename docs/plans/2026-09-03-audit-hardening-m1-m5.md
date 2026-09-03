# DeLector 全仓库审计修复实施计划（M1–M5）

> **Goal**: 修复 2026-09-03 vault-team 全仓库审计（多域并行只读侦察）产出的 P1/P2 问题：安全止血 → 数据库索引与连接 → 前端竞态与 UX → NLP 热路径 → 测试与健壮性收口。M1 安全优先，其余按里程碑顺序推进，每个 Task 原子提交。
> **Tech Stack**: Python 3.10+ / FastAPI / sqlite3 / 原生 ES Modules（零构建）/ node:vm 探针
> **Spec Reference**: 2026-09-03 vault-team 审计合成报告（会话内交付）；既有 stage-a/b 文档 `docs/plans/2026-09-03-lan-silent-sync-stage-a(-ledger).md`、`-stage-b(-ledger).md`；ADR-0004（stage-b，proposed）
> **Global Constraints**:
> - 测试命令须 `cd d:/Code/DeLector && export PYTHONIOENCODING=utf-8`；**禁止裸跑全量 pytest**（safe-delete 守卫会累积 >500 文件删除触发审批；超长命令易被跳过）。用 `python -m pytest <file> -k <case> -q` 定向子集。真实服务冒烟走 `TestClient(app, client=("127.0.0.1", 54321))`（默认 host 是 `testclient`，会被 `_require_localhost` 拒；局域网侧用 `client=("192.168.1.x", …)`）。
> - 新 DB 连接**必须确定性关闭**：用 `database.py` 现有 `_close_db_conn`（finally），或新增 `closing` contextmanager；禁止依赖 `with get_db() as conn` 的 GC 自动 close（引用环，Windows 句柄不释放）。
> - 任何测试模块 `import server` 前必须先设 `os.environ["DATABASE_PATH"]`，否则 import 副作用 `init_db()`+`seed_preset_articles()` 写真实 `delector.db`。
> - 字符串断言必须「具体到用得到」；禁止死断言。改函数签名/内联结构时同步更新 `test_german_workbench.py` 等用首出现 `.split(marker)` 定位的特征串。
> - 提交信息 `fix(scope): 中文描述`，每 Task 一个原子 commit；不做 `--amend`。
> - 新增可被还原/编辑/用户注入的文本进 HTML 模板前一律 `html.escape`。
> - 前端契约优先用 node:vm 动态探针（见 `tools/wb_sync_probe.mjs` 模式）；纯静态 UI 修复以结构测试 + 人工冒烟补位，并在 task 内如实标注验证方式。

---

## 执行模式说明（本环境降级声明，写入 ledger 时原样保留）

本环境**无写码子代理**（task 仅只读 `code-explorer`），vault-exec 类多代理编排降级为「编排者主线程直写 + TDD 纪律（RED→GREEN→REFACTOR）+ 每 Task 原子提交」，不在任何交付物中伪造子代理执行记录。规划期（本文件）已由 5 路并行只读侦察完成多域覆盖；执行期逐 Task 由主线程完成。

---

# Milestone M1 — 安全止血（先做）

## Task M1-1: 还原备份不再导入 API_BASE_URL / API_MODEL（防 API Key 外泄） [Role: TDD Builder]

**Files:**
- Modify: `d:/Code/DeLector/database.py:592-597`（白名单常量区）
- Modify: `d:/Code/DeLector/server.py:1565-1604`（`restore_database_backup` 内导入过滤）
- Test: `d:/Code/DeLector/test_audit_hardening.py`（新建，见 M5 隔离约定：顶部设 `DATABASE_PATH` 后 import）

**Interfaces:**
- Consumes: `BACKUP_SETTINGS_WHITELIST`（现用于导出 build_backup_payload 与还原导入）
- Produces: `BACKUP_SETTINGS_EXPORT_WHITELIST`（导出仍含 API_BASE_URL/API_MODEL，无敏感）+ `BACKUP_SETTINGS_IMPORT_WHITELIST = ("TTS_VOICE","TTS_RATE")`（还原只允许导入这俩）

**子代理 scaffold（vault-exec 降级版：由主线程执行以下步骤）:**
> Task M1-1: 还原备份设置白名单拆分。
> 在 `database.py` 白名单区：保留旧名 `BACKUP_SETTINGS_WHITELIST`（避免 build_backup_payload 等其它引用碎裂）但**仅**用于导出；新增 `BACKUP_SETTINGS_EXPORT_WHITELIST`（内容同旧值）与 `BACKUP_SETTINGS_IMPORT_WHITELIST`（只含 TTS_VOICE/TTS_RATE），并更新注释说明「API_BASE_URL/API_MODEL 导出无害（非机密），但还原导入会把真实 `DEEPSEEK_API_KEY` 的下一次 AI 调用指向攻击者基址 → 还原一律不导入」。
> `server.py:1584-1593` 还原块改用 `BACKUP_SETTINGS_IMPORT_WHITELIST`。
> TDD: 先写失败测试（RED）：备份 payload 含恶意 `API_BASE_URL="http://evil.example/"`、`API_MODEL="x"` 与 `TTS_VOICE="de-DE-ConradNeural"` → 调用还原端点（TestClient，127.0.0.1）→ 断言 `get_setting("API_BASE_URL")` 不变、`get_setting("API_MODEL")` 不变、`TTS_VOICE` 已导入、且 `DEEPSEEK_API_KEY` 表内仍存在。跑通后实现（GREEN），最后全绿 + 原子提交。

**Step Breakdown:**
- [ ] 写失败测试（还原恶意基址 payload，断言 API_BASE_URL 不被覆盖）
- [ ] `python -m pytest test_audit_hardening.py -k restore -q` 验证 RED
- [ ] `database.py` 白名单拆分 + `server.py` 还原块改 import 白名单
- [ ] 复跑 GREEN；`git commit -m "fix(backup): 还原不导入 API_BASE_URL/API_MODEL，防真实 API Key 外泄"`

**Verification:** 上述定向 pytest；全量还原相关旧用例（`test_server.py -k restore`）仍绿。

---

## Task M1-2: X-WB-Key 三处鉴权改恒定时间比较 + 抽共享 helper [Role: TDD Builder]

**Files:**
- Modify: `d:/Code/DeLector/database.py`（在 `get_wb_sync_key` 附近新增 helper）
- Modify: `d:/Code/DeLector/server.py:1439-1444`（`wb_put_state`）
- Modify: `d:/Code/DeLector/routes_sync.py:30-37`、`d:/Code/DeLector/routes_rtc.py:32-34`（各自 `_verify_wb_key`）
- Test: `d:/Code/DeLector/test_audit_hardening.py`

**Interfaces:**
- Produces: `def verify_wb_key(provided: str, db_path=None) -> bool`（内部 `secrets.compare_digest(str(provided or ""), get_wb_sync_key(db_path=db_path))`）
- Consumes: 现有三处 `request.headers.get("X-WB-Key", "") != get_wb_sync_key()` 全部改为调用 helper

**子代理 scaffold:**
> Task M1-2: X-WB-Key 恒定时间比较。
> `database.py` 已 `import secrets`：新增 `verify_wb_key`。三处调用点（server.py wb_put_state、routes_sync.py `_verify_wb_key`、routes_rtc.py `_verify_wb_key`）改用它。注意 routes_rtc 的 `_mailbox_id` 仍要原始 header 值做 sha256，不要动。
> TDD: RED 测试「正确 key 200 / 错 key 403 / 缺失 key 403」在三个端点上（sync store、rtc signal、wb state）→ 实现 helper → GREEN。附加恒定时间冒烟：`verify_wb_key` 内部必须调用 `compare_digest`（可 `unittest.mock` patch `secrets.compare_digest` 断言被调，防止回退成 `!=`）。

**Step Breakdown:**
- [ ] RED：三端点 key 鉴权行为测试 + `compare_digest` 被调断言
- [ ] 实现 `database.verify_wb_key` 并替换三处
- [ ] 复跑 GREEN；`git commit -m "fix(auth): X-WB-Key 统一走 secrets.compare_digest，消除时序侧信道"`

**Verification:** 定向 pytest + 既有 wb 探针（`test_german_workbench.py -k wbsync`，node:vm）保持绿。

---

## Task M1-3: `delete_article_note` 补 `_require_localhost` 闸 [Role: TDD Builder]

**Files:**
- Modify: `d:/Code/DeLector/server.py:1161-1165`（`delete_article_note` 加 `request: Request` 参数并 `_require_localhost(request)`）
- Test: `d:/Code/DeLector/test_audit_hardening.py` + 既有 `test_server.py` 中调用该端点的用例（需传 `client=("127.0.0.1", …)`）

**Interfaces:** 端点签名变化 `(note_id: int)` → `(note_id: int, request: Request)`。Android WebView 自身 localhost 后端不受影响（`request.client.host == "127.0.0.1"` 通过）。

**子代理 scaffold:**
> Task M1-3: 批注删除补本机闸。
> 仿 `delete_article`(server.py:414-416) 与 `delete_card` 的写法。先 grep `test_server.py` 里所有 `DELETE /api/notes` / `delete_article_note` 相关测试，若用 TestClient 默认 client（host=`testclient`）会因此新闸 403——测试需改为 `TestClient(app, client=("127.0.0.1", 54321))`。RED 测试：LAN 侧 client 调删除 → 403；127.0.0.1 → 200。GREEN 后补跑受影响的旧用例。

**Step Breakdown:**
- [ ] grep 受影响旧用例，预迁到 127.0.0.1 client
- [ ] RED：LAN client 删除 403
- [ ] 实现闸；复跑受影响用例 GREEN
- [ ] `git commit -m "fix(auth): 批注删除纳入本机写闸，防局域网任意删"`

**Verification:** 定向 pytest（含迁移后的旧用例）。

---

## Task M1-4: TTS 错误收敛 + voice 白名单 + 模型输入长度上限 [Role: TDD Builder]

**Files:**
- Modify: `d:/Code/DeLector/server.py`
  - `:1028-1031` `TTSReq`、`:280-282` `IngestReq`、`:1140-1144` `ReadingNoteReq`、`:1176-1178` `NoteAssistReq` 加 `Field(max_length=…)`
  - `:1085`、`:1103` TTS 异常改「服务端 log 原始错误 + 返回固定文案」
  - `:1091` 附近加 voice 格式/白名单校验，`_serve_tts` 里校验
  - `:1203` note-assist 送 LLM 前截断（仿 `writing/analyze` 已 `[:2000]`）
- Test: `d:/Code/DeLector/test_audit_hardening.py`

**Interfaces:** 保留既有默认 voice `de-DE-KatjaNeural`；voice 校验用白名单（取值来源：`static/index.html` 设置里 `setTtsEngine` 下拉可选项 ∪ 代码中引用过的 voice）或等价格式正则。TTS 失败时 `detail` 不得含内部异常文本。

**子代理 scaffold:**
> Task M1-4: TTS 与输入面收敛。
> ① 先列出全部 voice 允许值（读 index.html 设置下拉 + grep `Neural`）。② pydantic 字段上限：`IngestReq.raw_text` 建议 50_000；`ReadingNoteReq.selected_text/note_content` 5_000；`NoteAssistReq.sentence/selected_text` 送 LLM 前截断 2_000；`TTSReq.text` 沿用既有 TTS 上限。③ `generate_edge_tts_audio` 末尾（:1085）与 `_serve_tts`（:1103）的 `HTTPException(500, f"...{str(e)}")` 改为 `raise HTTPException(500, "语音合成失败，请稍后重试")`，原始异常 `logger/print` 落服务端。
> TDD: RED「超长 raw_text → 422 / 恶意 voice → 400 / 桩掉合成抛异常 → 500 响应体不含内部路径或 repr」→ GREEN。

**Step Breakdown:**
- [ ] RED 三组失败用例
- [ ] 字段上限 + voice 校验 + 错误文案收敛 + LLM 截断
- [ ] 复跑既有 TTS 用例（`test_server.py -k tts`）防回归
- [ ] `git commit -m "fix(api): TTS 错误收敛/voice 白名单/输入长度上限"`

**Verification:** 定向 pytest。

---

## Task M1-5: Anki 导出 HTML 转义（防 .apkg 存储型 XSS） [Role: TDD Builder]

**Files:**
- Modify: `d:/Code/DeLector/database.py`（`export_anki_deck` :471-487、`export_a1_anki_deck` :511-553）
- Test: `d:/Code/DeLector/test_audit_hardening.py`（仅测 database 层，不 import server）

**Interfaces:**
- Produces: `def _anki_esc(value) -> str`（`html.escape(str(value or ""), quote=True)`）
- 约束：vocab/grammar/a1 三套 note 的**用户可注入字段**（word/sentence_context/definition_zh/explanation_zh/example_* 等）先转义再拼入 fields；我们自己生成的 `<b style=…>`、`<span style=…>` 高亮用**转义后**的词去 `.replace` 拼接。

**子代理 scaffold:**
> Task M1-5: Anki 字段转义。
> vocab 的 `styled_front`（:479）与 grammar（:484）、a1（:535-549）所有来自用户/可编辑数据的字段统一 `_anki_esc`。注意顺序：先 escape sentence 与 word，再在 escaped sentence 里用 escaped word 做高亮替换，避免转义破坏 `<b>` 结构。
> TDD: RED「构造 word=`<img src=x onerror=alert(1)>`、sentence 含 `<script>` 的卡 → 导出 note 字段含 `&lt;img`/`&lt;script` 而非裸标签」。把两个 export 函数收口为可测的内部 builder（返回 notes 列表）后断言。

**Step Breakdown:**
- [ ] RED：恶意 HTML 用例字段含实体
- [ ] `html.escape` + builder 抽取；genanki Package 写入路径不动
- [ ] 复跑既有 anki/备份相关用例（`test_server.py -k anki`、`test_dict_pipeline.py`）
- [ ] `git commit -m "fix(export): Anki 卡片字段 HTML 转义，防存储型 XSS"`

**Verification:** 定向 pytest；`test_frontend_security.py` 全绿。

---

# Milestone M2 — 数据库索引与连接生命周期

## Task M2-1: 索引迁移（主库 5 + 进度库 2） [Role: TDD Builder]

**Files:**
- Modify: `d:/Code/DeLector/database.py`
  - `init_db` 迁移区（:271-300 后）：`CREATE INDEX IF NOT EXISTS` 五条 —— `vocab_cards(mastered, due_date)`、`grammar_cards(mastered, due_date)`、`vocab_cards(article_id)`、`grammar_cards(article_id)`、`reading_notes(article_id)`
  - `init_progress_db`（:67-123 块内尾部）：`quiz_log(card_id)`、`study_log(logged_at)`
- Test: `d:/Code/DeLector/test_audit_hardening.py`

**Interfaces:** 纯迁移，无行为变化；`CREATE INDEX IF NOT EXISTS` 幂等，旧库启动自动补。

**子代理 scaffold:**
> Task M2-1: 补索引。
> RED：对临时空库跑 `init_db`/`init_progress_db` 后断言 `PRAGMA index_list(<table>)` 含上述索引（写死期望集合，防止漏建）。GREEN：在 DDL 后追加 `conn.execute("CREATE INDEX IF NOT EXISTS …")`（主库与进度库各自 init 函数内）。跑既有全部 db 相关用例确认无回归。注意 `PRAGMA index_list` 返回的 name 是生成名（`sqlite_autoindex…` 或我们命名的 `idx_…`），断言按表内索引**列**而非名字更稳。

**Step Breakdown:**
- [ ] RED：index_list 断言失败
- [ ] 补 7 条索引 DDL
- [ ] 复跑（`test_server.py`、`test_dict_pipeline.py`、`test_goethe_a1*` 定向）
- [ ] `git commit -m "perf(db): 补 SRS/关联/日志查询缺失索引"`

**Verification:** 定向 pytest。

---

## Task M2-2: `/api/progress/stats` 与 streak 改单次扫描（语义等价） [Role: TDD Builder]

**Files:**
- Modify: `d:/Code/DeLector/server.py`
  - `get_progress_stats` :911-939（6+ 次全表聚合 → 条件聚合）
  - 趋势 :950-961（30 次往返 → 1 次范围查 + Python 补零）
  - streak :963-974（365×`WHERE date(logged_at)=?` → 1 次 `SELECT DISTINCT substr(logged_at,1,10) FROM study_log WHERE logged_at >= ?` 后 Python 回溯）
- Test: `d:/Code/DeLector/test_audit_hardening.py`（含行为等价探针：先旧算法采样、后新算法断言一致）

**Interfaces:** 响应 JSON 形状**零变化**。streak 语义必须保持现状：today 有记录才开始累计，today 无则 0（即使昨天连续）——**不得顺手改成标准打卡口径**，除非独立 feature。

**子代理 scaffold:**
> Task M2-2: stats 单扫重构。
> RED：构造「连续 N 天记录 + 中间断档 + today 空」等数据 → 按**现状语义**写行为断言；构造 stats 汇总期望值。GREEN：用条件聚合（`COUNT(*), SUM(mastered=1), COALESCE(SUM(correct_count),0)…`）+ Python 补零 + set 回溯 streak。确认响应字段与旧完全一致（逐 key diff 一把真实进度库的响应作为基准快照，比对新响应）。

**Step Breakdown:**
- [ ] RED：行为等价用例（含断档、today 空、大跨度）
- [ ] 实现聚合合并 + 单次 range 查 + streak set
- [ ] 基准快照 diff 验证无形状漂移；GREEN
- [ ] `git commit -m "perf(db): progress stats/趋势/streak 由 N 次全扫降为常数次"`

**Verification:** 定向 pytest（`test_server.py -k progress/stats`、`test_audit_hardening.py`）。

---

## Task M2-3: `list_articles` 减载 + `review_card_sm2` 去回查 [Role: TDD Builder]

**Files:**
- Modify: `d:/Code/DeLector/server.py` `list_articles` :379-395、`review_card_sm2` :1654
- Test: `d:/Code/DeLector/test_audit_hardening.py`

**Interfaces:** `GET /api/articles` 响应 item 字段 `{id,title,created_at,char_count,stats}` 不变；`GET` 不再对缺失 stats 的行做**逐行重算+UPDATE**（N+1 副作用），改为只读返回 stats 缺失时空 stats；重算迁移挪到 `ingest`/启动期或 `GET /api/articles/{id}`（:408-410 已做惰性迁移，list 只读即可）。`POST /api/cards/{type}/{id}/review` 返回值不变，但去掉 UPDATE 后整行 `SELECT *`（用内存 row + FSRS 结果 + 计数自增拼装）。

**子代理 scaffold:**
> Task M2-3: list 减载 + review 去回查。
> RED：① 注入一篇 `processed_json` 无 stats 的文章 → 桩 `process_german_text` 抛异常也应能正常列文章（证明 list 不再调用重算）；断言 list 期间该行未被 UPDATE（对比 mtime/次数计数桩）。② review 用 patch 断言 UPDATE 后无第二条 `SELECT *`。GREEN：改两处实现。

**Step Breakdown:**
- [ ] RED 两用例
- [ ] 实现；确认 `GET /api/articles/{id}` 仍做惰性迁移（读路径唯一入口保留）
- [ ] 复跑既有 article/review 用例
- [ ] `git commit -m "perf(api): 文章列表只读免重算；复习接口免二次回查"`

**Verification:** 定向 pytest。

---

## Task M2-4: closing contextmanager 全局替换泄漏连接 [Role: TDD Builder]（改动面大，拆两步 commit）

**Files:**
- Modify: `d:/Code/DeLector/database.py`（新增 contextmanager；替换 `database.py` 内部 ~11 处：:129 log_study_event、:308 get_setting、:318 set_setting、:435/443 seed/ingest、:809/816/828/845/857/872 等）
- Modify: `d:/Code/DeLector/server.py`（~40 处 `with get_db()/get_progress_db() as conn`）
- Test: `d:/Code/DeLector/test_audit_hardening.py`（连接计数探针：桩 sqlite3.connect 计数，断言请求结束后 connect-open−close==0）

**Interfaces:**
- Produces:
```python
@contextmanager
def db_conn(db_path=None):
    conn = get_db(db_path)
    try:
        yield conn
    except BaseException:
        conn.rollback(); raise
    else:
        conn.commit()
    finally:
        _close_db_conn(conn)
# 及 db_progress_conn(...) 同构
```
- 语义：`with db_conn() as conn:` 行为 == `with get_db() as conn:`（成功 commit、异常 rollback）+ finally 确定性 close。**单文件 step 内逐段替换并同步跑受影响的用例**；先替 database.py（commit 1），再替 server.py（commit 2）。

**子代理 scaffold:**
> Task M2-4a: database.py 内部连接确定性关闭。
> RED：连接探针（每次 `get_db` 造 conn 计数、`close` 减计）——调用 `get_setting`/`set_setting`/`ingest_article` 等后断言 open==closed。GREEN：新增 `db_conn`/`db_progress_conn`，替换 database.py 内部所有 `with get_db(...)`；注意 `get_wb_state`/`save_wb_state`/`build_backup_payload` 已手动 finally close，可顺手统一到新 ctx（等值替换）。跑 `test_server.py` 全定向、`test_audit_hardening.py`。
> Task M2-4b: server.py 端点批量替换（机械转换）。
> 逐路由 `with get_db() as conn:` → `with db_conn() as conn:`（get_progress_db → db_progress_conn）。凡已有显式 `conn.close()` 或 `finally _close_db_conn` 的保留（别双 close）。之后跑受影响 server 定向测试 + `-k wb|sync|rtc` 确认无回归。

**Step Breakdown:**
- [ ] 探针 RED
- [ ] 4a database.py 替换 + commit `fix(db): 连接确定性关闭(database 层)`
- [ ] 4b server.py 替换 + commit `fix(db): 连接确定性关闭(server 层)`
- [ ] 回归（定向全集 + workbench node 探针）

**Verification:** `python -m pytest test_server.py -k 'not ' ` 不可全跑；用**逐影响面**定向：`test_server.py`（按路由分组 3~4 次 `-k`）+ `test_german_workbench.py -k wbsync`。全绿后记录「连接探针 0 泄漏」证据。

---

# Milestone M3 — 前端竞态与 UX

## Task M3-1: core.js 增加 `notify()` 与 `api()` 超时/signal；关键路径 alert 换非阻断带 [Role: TDD Builder]

**Files:**
- Modify: `d:/Code/DeLector/static/js/core.js`（新增 `export function notify(msg, type)` 通知带；`api()` 支持 `opts.signal` 与默认超时）
- Modify: `static/index.html`（通知带宿主元素）
- Modify: 首批替换 `static/js/reader.js`、`writer.js`、`player.js` 里读路径的 `alert(...)`（audit 点位：reader.js :572/:618/:701 等）
- Test: `d:/Code/DeLector/test_audit_hardening.py`（结构断言：index.html 存在通知带宿主 + core.js 导出 notify；避免新增会撞 `test_german_workbench.py` 字符串标记的记号——新增用具名函数）

**Interfaces:** `api(path, {signal, timeoutMs=15000, ...})`；`notify(text, type="info"|"success"|"error")` 3s 自消失、不阻塞。

**子代理 scaffold:**
> Task M3-1: notify 体系 + api 超时。
> 参考 `workbench.html:963` 已有的非阻断 `toast()` 交互范式，在 index.html SPA 加轻量通知带。RED：写 core.js 结构契约测试（ESM 具名导出存在 + api 在 fetch 桩下支持 signal/超时 abort）。GREEN 实现。随后把 reader/writer 的 `alert("…: " + e.message)` 替换为 `notify("操作失败，请稍后重试","error")` + `console.error(e)`，原始 error 不再上屏。本轮**只覆盖读/核心路径**，其余 40 处放 M5 收口批。

**Step Breakdown:**
- [ ] RED：core 契约 + index.html 宿主结构断言
- [ ] 实现 notify/api 超时；替换 reader/writer/player 读路径 alert
- [ ] 跑前端结构测试（`test_frontend_module_graph.py`、`test_frontend_security.py`）
- [ ] `git commit -m "feat(ui): 非阻断通知带与 api 超时，收敛读路径原始错误弹窗"`

**Verification:** 定向 pytest；手工冒烟（npm 无，`python start.py` 后浏览器）记录说明。

---

## Task M3-2: 阅读/写作/卡片陈旧响应守卫 [Role: TDD Builder]

**Files:**
- Modify: `static/js/reader.js` `openReader` :184-246（请求后 `if (!a || a.id !== id) return;`，`state.currentArticle` 用本地变量）
- Modify: `static/js/writer.js` 分析 :591-603（`const token = ++_analyzeToken`；返回后 `if (token !== _analyzeToken) return;`；传 signal）
- Modify: `static/js/cards.js` `loadPrepMatrix` :1065-1068（渲染前加 `#view-cards` 仍在 active 的守卫/请求令牌）
- Test: `test_audit_hardening.py`（结构 + 语义探针：对可单测的 token 守卫用 node:vm 桩 fetch 时序）

**子代理 scaffold:**
> Task M3-2: 陈旧响应守卫。
> 三处都是同一模式：异步竞态 → 加「请求身份」判别。RED（workbench 之外无现成动态桩的先以结构断言锁定关键行存在性 + 新写 node:vm 桩（仿 `tools/wb_sync_probe.mjs`）：桩 fetch 用可控 Promise 顺序，验证 reader 慢响应被丢）。GREEN 实现三处。凡改函数签名/结构，grep `test_german_workbench.py`/`test_writer_mobile.py` 是否用字符串切片钉住旧结构，同步更新。

**Step Breakdown:**
- [ ] 探针/结构断言先行
- [ ] 实现三处守卫
- [ ] 跑前端相关测试防字符串标记碎裂
- [ ] `git commit -m "fix(reader): 文章/写作/卡片加载加陈旧响应守卫"`

**Verification:** 定向 pytest + 说明人工冒烟。

---

## Task M3-3: player.js blob URL 生命周期 + 请求令牌 [Role: TDD Builder]

**Files:**
- Modify: `static/js/player.js`（:38-41 单句、:213-224 循环：存 `_curUrl`，`pause()`/切句/兜底分支统一 `URL.revokeObjectURL`；用单调 `_reqToken` 替代仅 `isPlaying` 判陈旧）
- Test: `test_audit_hardening.py`（静态审计式断言：模块内出现 revoke 与令牌比较，防回退）

**子代理 scaffold:**
> Task M3-3: blob URL 防泄漏。
> 现 URL 仅在 `onended` 撤销；暂停/切句/异常兜底泄漏。改为 `_curUrl` 保存 + 所有出口统一 revoke；fetch 返回后 `if (this._reqToken !== myToken) return` 再赋值 src。RED：结构断言（模块文本含 `revokeObjectURL` 出现在 pause/兜底路径；`_reqToken` 比较）。GREEN：改实现。

**Step Breakdown:**
- [ ] 结构断言（防回退到仅 onended revoke）
- [ ] 实现
- [ ] `git commit -m "fix(tts): blob URL 统一撤销 + 播放请求令牌防错句覆盖"`

**Verification:** 定向 pytest + 冒烟说明。

---

## Task M3-4: PWA 版本更新不再强制刷新标签页 [Role: TDD Builder]

**Files:**
- Modify: `static/sw.js` :27-30（`activate` 里 `client.navigate(client.url)` 全窗硬刷 → 改为只 `clients.claim()`；向活跃 window `postMessage({type:"delector-update"})`；页面侧监听后提示「新版本已就绪，点击刷新」）
- Test: `test_audit_hardening.py`（结构断言：sw.js 不再含 `client.navigate(` 直刷；含 `postMessage` 更新提示）

**子代理 scaffold:**
> Task M3-4: PWA 温和更新。
> RED：断言 sw.js 不再无条件 navigate 所有窗口。GREEN：`activate` 仅 `self.clients.claim()`；广播更新消息；在 index.html 主脚本监听并弹 `notify()` 级提示，用户点「刷新」才 `location.reload()`。防与 M3-1 通知带耦合：直接用既有机制或自包含 banner。

**Step Breakdown:**
- [ ] 结构断言 RED
- [ ] sw.js + 页面监听改造
- [ ] `git commit -m "fix(pwa): 版本更新改为提示刷新，不丢未保存状态"`

**Verification:** 定向 pytest + 冒烟（改 CACHE 版本号触发一次更新观察）。

---

# Milestone M4 — NLP 热路径提效（零行为风险优先）

## Task M4-1: 每次调用重建的静态表/常量提升到模块级 [Role: TDD Builder]

**Files:**
- Modify: `writing_rules.py`（`decline_determiner` 4 张表 :61-105；函数内 `import re`/`MONTH_MAP`/问候/署名/专名列表 :457/481/513/536/573/590；`date_pat` 预编译 :487；`import` 提前 :150）
- Modify: `linguistics.py`（`plural_stems` :1110-1129、`prefixes` :818-824）
- Modify: `nlp.py`（`get_cefr_level` 后缀元组 :160）
- Modify: `syntax_tree.py`（`_ABBR_PATTERN` :1189 提到模块级）
- Test: `test_audit_hardening.py`（模块级常量已缓存语义探针：对 `decline_determiner`/`_get_element_info` 抽样断言输出与旧一致）

**Interfaces:** 纯常量/编译提升，**零返回值变化**。凡函数内含 `import x` 提到模块顶部。

**子代理 scaffold:**
> Task M4-1: 常量提升。
> RED：为每个改动函数写「代表性输入 → 期望输出」抽样快照（从既有 `test_writing_rules.py`/`test_syntax_tree.py` 抽取典型 case 固化），保证提升后行为不变。GREEN：批量提升。之后全量跑 `test_writing_rules.py`、`test_syntax_tree.py`、`test_prep_matrix.py` 等纯规则模块（这些不 import server，可整文件跑）。

**Step Breakdown:**
- [ ] 抽样快照 RED
- [ ] 批量提升
- [ ] 纯规则模块整文件全绿
- [ ] `git commit -m "perf(nlp): 每次调用重建的词形表/正则提升为模块级常量"`

**Verification:** 整文件跑 `test_writing_rules.py test_syntax_tree.py test_prep_matrix.py test_dict_pipeline.py`。

---

## Task M4-2: `split_komposita` lru_cache + `lookup_core_vocab` 返回缓存 [Role: TDD Builder]

**Files:**
- Modify: `linguistics.py` `split_komposita` :1201-1237（拆出纯函数 + `@functools.lru_cache`；保留对外签名与 `min_part_len` 参数化）
- Modify: `core_dict.py` `lookup_core_vocab` :482-506（命中返回与既有等价的**共享只读** dict/MappingProxy，避免每次新建）
- Test: `test_audit_hardening.py`（lru 命中计数探针 + 抽样等价）

**Interfaces:** 对外语义零变化。注意返回值若被调用方改写会污染共享缓存——先查调用方是否只读（grep `lookup_core_vocab(` 与 `split_komposita(` 调用点），只读才上共享/缓存，否则保留拷贝。

**子代理 scaffold:**
> Task M4-2: 缓存纯函数。
> RED：抽样等价 + 命中计数（调用两次同词断言缓存命中避免重算）。GREEN：实现。lru_cache 返回值是 `list` 时包一层 `tuple` 返回或内部 `_split_komposita_cached` + 外层转 list（保持类型）。

**Step Breakdown:**
- [ ] RED 抽样等价 + 缓存命中
- [ ] 实现（确认调用方只读后上共享）
- [ ] 跑 `test_server.py -k lookup|komposita`、纯词法模块整跑
- [ ] `git commit -m "perf(nlp): 复合词拆解与核心词查表加缓存"`

**Verification:** 定向 pytest。

---

## Task M4-3（可选/回归高风险）: `build_clause_tree` 复用句级 topology [Role: TDD Builder，建议独立评审]

**Files:**
- Modify: `nlp.py` :306-307 与 `syntax_tree.py` `build_clause_tree` :1143（每从句重算 `analyze_sentence_topology(sent)` → 复用整句一次计算结果下传）
- Test: `test_syntax_tree.py` + `test_server.py -k analyze|syntax` 全量定向（这是行为最敏感的改动）

**子代理 scaffold:**
> Task M4-3: 从句拓扑去重。
> 先做**契约快照**：对 test_syntax_tree / test_server 中所有 topology/语法树断言固化为 golden（现有测试已较全）。重构时保持函数签名稳定、内部把 tokens 预处理（`non_punct_tokens`/`zu_tokens`/verb 组）只算一次传入。若中途发现子句边界依赖每次重扫的行为（如局部修正），**立即停下报告**，不要强行去重——收益是读路径主开销，但正确性优先。若评估为「不可安全去重」，把结论与证据写进 commit message 并跳过本 task（标记 skipped + 理由）。

**Step Breakdown:**
- [ ] golden 快照确认覆盖充分
- [ ] 尝试去重；行为 diff 全绿才提交
- [ ] `git commit -m "perf(nlp): 从句 AST 复用整句拓扑，去除每从句重扫"`（或 `fix(nlp): 保留每从句重扫（理由见 message）`）
- [ ] 若跳过：在 ledger 记录决策与证据

**Verification:** `test_syntax_tree.py` 整跑 + `test_server.py -k 'syntax or analyze'` + `test_german_workbench.py -k 语法`。

---

# Milestone M5 — 测试与健壮性收口

## Task M5-1: 6 个测试模块隔离真实 DB [Role: TDD Builder]

**Files:**
- Modify: `test_goethe_a1.py`、`test_goethe_a1_lesen.py`、`test_goethe_a1_hoeren.py`、`test_goethe_a1_writing.py`、`test_corpus.py`、`test_audit_regressions.py`
- 对照模板：`test_server.py:12-13` 与 `clean_db` fixture（autouse + `gc.collect()` 后删临时库）
- Test: 上述文件自身（在 `import server` 前设 `DATABASE_PATH`）

**Interfaces:** 每个文件顶部、**任何 `import server` 之前**：`os.environ.setdefault("DATABASE_PATH", "test_delector_<module>.db")`（或用 conftest 统一）。现有 import 副作用若先建好才设 env 会失效——须按「先设后 import」顺序或把 import 移到 fixture。

**子代理 scaffold:**
> Task M5-1: 测试 DB 隔离。
> RED：临时把 DATABASE_PATH 指到只读副本路径跑一个用例 → 观察失败（证明污染路径）；更稳的做法是直接断言这些模块 import 后 `get_db_path()` 不含 `DATA_DIR/delector.db`。GREEN：顶部设 env + autouse clean fixture。跑五个 goethe + corpus + audit 全绿，并确认真实 `delector.db` mtime 未变。

**Step Breakdown:**
- [ ] 断言式 RED（隔离缺失即失败）
- [ ] 各文件加 env + 清理 fixture
- [ ] 定向全绿 + 真实库 mtime 校验
- [ ] `git commit -m "test: 补齐 6 个测试模块的临时库隔离，不再污染真实数据"`

**Verification:** 定向 pytest + mtime 证据。

---

## Task M5-2: `test_german_workbench.py` 裸 split 与相对路径加固 [Role: TDD Builder]

**Files:**
- Modify: `test_german_workbench.py`（前半段 ~20 处 `x.split(marker)[1].split(end)[0]` 与 `[:400]` 魔数窗 → 复用后半段已有的 `_fn_body`/`_slice_balanced`/`_sole_line`；点位 :33/:46/:52/:93/:110/:185/:495/:609/:745/:1243/:1250/:1257/:1264/:1433/:1469 等）
- Modify: `test_goethe_a1_writing.py:198/:206`（`open("static/...")` → `(Path(__file__).parent / "static" / ...).read_text(encoding="utf-8")`）
- Test: 修改自身即可验证

**子代理 scaffold:**
> Task M5-2: 测试解析加固。
> 逐个把裸 split 换成括号配平切片（`_slice_balanced` 会自动抛错而非静默切歪），`[:400]` 移除或改为断言函数体结束标记。每替换一处跑 `test_german_workbench.py -q` 一次确认绿。RED 概念：若标记被改动，护栏会**显式失败**而不是假绿——本任务验证方式即「替换后全量仍绿 + 故意改一个标记确认会红」的变异演练（完成后还原）。

**Step Breakdown:**
- [ ] 变异演练确认护栏有效（临时改标记→红→还原）
- [ ] 批量替换裸 split + 相对路径
- [ ] 全绿；`git commit -m "test: workbench/写作测试解析改括号配平护栏，消除假绿切片"`

**Verification:** `python -m pytest test_german_workbench.py test_goethe_a1_writing.py -q`。

---

## Task M5-3: 前端 P2 小修批 + 剩余 alert 收敛 [Role: TDD Builder]

**Files:**
- Modify: `static/german/workbench.html`：`pull()` 失败指数退避（:1344-1382，5s→30s cap）；`rtcOnStateChange` 仅 `failed/closed` 计 `_rtcFails`（:1293-1313）；LAN 同步按钮在途 disabled（:3352/:3373）
- Modify: `static/js/a1_lesen.js` `startLesenTimer` 开头 `clearInterval`（:101-116）
- Modify: 剩余 `alert(...)` 批量换 `notify()`（cards/main/a1_* 等 ~40 处）——若 M3-1 已建 notify
- Test: `test_german_workbench.py`（wbsync node 探针：`wb_rtc_*` 组、退避结构）；`test_audit_hardening.py`（`startLesenTimer` 防抖结构断言、alert 余量断言 `grep alert(` 数量上限）

**子代理 scaffold:**
> Task M5-3: 前端 P2 收口。
> 每项小而独立：① pull 失败指数退避（保 `_busy`/防抖不动）；② rtcOnStateChange 分类计数；③ 双按钮 disabled；④ a1_lesen 防抖；⑤ alert 收敛。凡动 workbench.html，改后必须跑 `test_german_workbench.py -q`（字符串标记敏感）。alert 收敛目标：`static/js` 内 `alert(` 残留 ≤ 5（结构断言防回潮）。

**Step Breakdown:**
- [ ] 逐项实现（每项跑对应定向测试）
- [ ] wbsync node 探针全绿；alert 余量断言
- [ ] `git commit -m "fix(ui): 同步退避/防降级/按钮防双击/计时器防叠，alert 批量收敛"`

**Verification:** `test_german_workbench.py -k 'wbsync or wb_rtc or lan' -q` + alert 计数断言。

---

## Task M5-4（可选收尾）: server.py `__all__` 过度再导出收口 [Role: Refactor]

**Files:** Modify `d:/Code/DeLector/server.py:152-…`（`__all__` 移除 nlp 透传符号 `spacy/nlp/NLP_ENGINE/...`）及对应 `from nlp import (...)`（:92-108 附近，仅删无消费者的透传名；确认 `test_server.py`/其它模块不 `from server import nlp` 之类）

**Interfaces:** 移除无消费者的公共再导出。grep `from server import` 全仓确认无引用后删；保留任何测试实际引用的名字。

**Step Breakdown:**
- [ ] grep 引用清单
- [ ] 删透传 + 全量 import server 的测试定向跑
- [ ] `git commit -m "refactor(server): __all__ 收口，剔除无消费者的 nlp 透传符号"`

**Verification:** 定向 pytest（所有 `import server` 的模块）。

---

## 汇总表

| Milestone | Tasks | 风险 | 验证主力 |
|---|---|---|---|
| M1 安全止血 | M1-1..M1-5 | 低-中（restore/鉴权行为） | test_audit_hardening + test_server 定向 |
| M2 DB/连接 | M2-1..M2-4 | 中（M2-4 机械大面替换） | 定向全集 + wbsync 探针 |
| M3 前端竞态/UX | M3-1..M3-4 | 中（字符串标记敏感） | 前端结构测试 + node:vm + 冒烟 |
| M4 NLP 热路径 | M4-1..M4-3 | 低（M4-3 高，允许跳过留证） | 纯规则模块整跑 |
| M5 收口 | M5-1..M5-4 | 低 | 定向 + 探针 + alert 计数 |

## 下游动作

Plan 已生成（含每 Task subagent prompt scaffold + TDD 步骤）。初始化 ledger `docs/plans/2026-09-03-audit-hardening-m1-m5-ledger.md` 后用 /vault-exec 执行？
