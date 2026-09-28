# 🏛️ Multi-Expert Swarm Audit Report: DeLector（current master 全量）

**Date**: 2026-09-28
**Target Scope**: 整个 master（Python/FastAPI 后端 + Go agent + 原生 JS PWA 前端 + Android/Chaquopy 打包面）
**Seats Dispatched**: `product-ux` · `frontend-architect` · `dba-optimizer` · `perf-profiler` · `code-reviewer` · `sre-resilience`
**Seats Skipped (why)**: `codebase-researcher`（范围明确为整个 master，编排者先做结构 recon 即可）· `codegraph-explorer`（本轮未出现"谁调用 X / 改 W 会断什么"的链路问题）

> 编排者已对全部 P0/P1 做 **Phase 1.5 独立对抗复核**（读真实代码/实跑），标签见每条。

---

## 🚨 Critical Findings（P0 / P1）

**P0：无。** 6 个 seat 一致认为常规运行无数据损坏 / 死锁 / 越权 / 核心流断裂。契约守卫层（路由守卫、JS↔Python 双向同步守卫、测试库隔离）是本仓库强项。

**P1（6 条）**：

- **[sre-resilience] CONFIRMED** — `Dockerfile:18` `CMD ["uvicorn","server:app",...]` 指向**不存在的模块**。
  - 仓库根无 `server.py`；真实入口是 `delector.server:app`（`delector/server.py:356` 模块级 `app = create_app()`；`start.py:88` 亦用 `delector.server`）。
  - *Impact*: `docker compose up` → `ModuleNotFoundError: No module named 'server'`，容器启动即死。Docker 部署路径完全不可用（桌面主分发走 `start.py`/PyInstaller，故非日常阻断，但提交态即坏）。
  - *Verification Status*: CONFIRMED — 实读 `Dockerfile` + 确认根目录无 `server.py`。

- **[dba-optimizer] + [sre-resilience] CONFIRMED** — SQLite **未启用 WAL**（`delector/core/database.py:53-60`，仅 `busy_timeout=5000` + `synchronous=NORMAL`）。
  - 默认 rollback-journal ⇒ 写期间阻塞读者、写写串行化；并发读写叠加易触发 `database is locked`。
  - *Impact*: 本地多标签/多设备并发（尤其 `save_wb_state` 整份 JSON 重写 + 轮询 GET）可读性差、崩溃恢复弱于 WAL。项目自家的扫描器 `tools/vault-proactive-scan.py:209-213` **已把自家代码标红**。
  - *Verification Status*: CONFIRMED — 实读 `_configure_sqlite_conn`。

- **[product-ux ①] CONFIRMED** — i+1「已知词池」与主流背词路径**完全隔离**。
  - `buildKnownSet`（`static/js/deck-bridge.js:148-159`）只读 `wb.words/cards` 的 localStorage；主阅读流 `saveVocab()` 写后端 `/api/cards/vocab`（`static/js/reader.js:598`），KARTEI 也只读 `/api/cards`。两条数据流从不相交、无同步。
  - *Impact*: 用户在主阅读存了几十张词卡后进遇见区，仍看到引导"先在背词工作台背一些词"——旗舰功能对多数用户**静默失效**（`static/js/encounter.js:218`）。
  - *Verification Status*: CONFIRMED — 实读两处调用链，确认池源不同。

- **[product-ux ②] CONFIRMED** — 两套并列"词库"界面：`KARTEI / 卡盒`（`/api/cards`）与 `VOKABELN / 德语背词`（iframe 工作台、`wb.*` 本地存储），**全站无任何文案说明区别或同步**。
  - *Impact*: 初学者面对两个背词入口，认知断裂（与①叠加放大"我明明背了"的错觉）。

- **[perf-profiler] CONFIRMED（规模触发）** — `delector/routes/syntax_hard.py:132-175`（`source=all`）每次请求 `SELECT id, raw_text FROM articles` **全量物化进内存** + 每篇跑 spaCy `rank_sentences`（实测 ~2.1 ms/句）+ 跨材料聚合排序。
  - per-material 有 300s TTL 缓存（`:40-41, 82-86`），但 `source=all` 的跨材料聚合与排序**不缓存**。
  - *Impact*: 语料到数百篇时单次请求数秒 CPU + 数十 MB 瞬时内存，挤占 NLP 线程池。实测单价外推，非臆测。

- **[sre-resilience] PLAUSIBLE（潜伏性）** — Android 面 `fastapi<0.100.0` / `pydantic<2.0.0`（`android/app/build.gradle:84-94`）与桌面 `fastapi 0.141.1` / `pydantic v2` **不同源且无 CI 守护**。
  - 编排者实搜 `delector/**` 的 pydantic 用法：**当前仅用 `BaseModel`/`Field` 跨版本兼容写法**（无 `model_config`/`ConfigDict`），故今天不崩。
  - *Impact*: 一旦有人引入 v2-only 语法，CI 全绿、APK 在 import 阶段直接炸 —— 最危险的"CI 绿、APK 崩"盲区。
  - *Verification Status*: PLAUSIBLE — 不一致本身 CONFIRMED，但其"炸 APK"后果是**条件性**的（当前不触发），故不单独驱动阻塞判定。

---

## ⚠️ Improvements & Suggestions（P2）

| Seat | 发现 | 位置 |
|---|---|---|
| **frontend-architect** | `openText` 无重入守卫/AbortController，快速点两卡"最后响应者胜" | `static/js/encounter.js:501-525` |
| **frontend-architect** | `addCardToDeck` 去重不去冠词，与 `buildKnownSet` 口径不对称 → 带冠词名词生成重复词（缺测试） | `static/js/deck-bridge.js:341` vs `:158` |
| **frontend-architect** | `api()` 单次超时即抛，镜像同步无重试/离线队列 | `static/js/core.js:97-123` |
| **frontend-architect** | 遇见区卡片 `<div role=button>` 键盘/读屏不可激活 | `static/js/encounter.js:259` |
| **frontend-architect** | `reader.js` 给每个可分动词 token 单独绑 `mouseenter/leave`（无泄漏，仅首屏开销） | `static/js/reader.js:259-276` |
| **dba-optimizer** | `exam_trials` 缺 `(level,module,id DESC)` 索引 → 历史查询全表扫（**本地 EXPLAIN 已验证 SCAN→SEARCH**） | `delector/core/database.py:1612` |
| **dba-optimizer** | `/api/cards` 整库无分页 + `SELECT *` + 全排序 | `delector/routes/main.py:685-704` |
| **dba-optimizer** | SRS 到期队列 `ORDER BY` 走临时 B-tree（EXPLAIN 验证） | `delector/routes/main.py:1652,1660` |
| **dba-optimizer** | `DATA_DIR` import 时冻结，env 决定库路径（与近期"测试串扰"同类脆弱设计） | `delector/core/database.py:31-46` |
| **dba-optimizer** | `get_db` 不自动建表，与 `get_progress_db` 不对称 | `delector/core/database.py:63-65` |
| **perf-profiler** | `_RANK_CACHE` 无上限/无 LRU，长期运行内存只增不减 | `delector/routes/syntax_hard.py:40` |
| **perf-profiler** | 每次 TTS 全目录扫描 `os.listdir`+`getmtime`+`sort` | `delector/core/database.py:1099-1114` |
| **perf-profiler** | 共享 `nlp` 单例 + `get_spacy_nlp` 懒加载 TOCTOU 双加载竞态（低概率，非损坏） | `delector/nlp_engine/processor.py:71` / `syntax_tree.py:48-64` |
| **perf-profiler** | 冷启动词库合并实测 1607.7 ms / 8.4 MB（每 worker 一次） | `delector/core/lexicon.py:95` |
| **code-reviewer** | `test_encounter_addcard.py:393` 松散 OR 断言，第二支是死分支（删 TTS 端点仍绿） | 测试 |
| **code-reviewer** | 德语冠词归一化在 **4 处散落**（database/build_dict/i1 测试/listen），无共享工具（**复用阶梯违规**） | 多处 |
| **code-reviewer** | 路由守卫 docstring 夸大"免疫实现漂移"（实际只免疫端点对象身份；GET 的 HEAD 仍耦合两套表示） | `tests/test_server.py:4439-4496` |
| **code-reviewer** | Go `supervisor_test.go` 收尾 goroutine 建议补 `-race + cancel 超时` 用例 | `agent/internal/pythonsvc/supervisor_test.go:403,423` |
| **sre-resilience** | Go `app.Run` 不读 `Supervisor.Failures()` → Python 耗尽重启配额后 agent 成"僵尸" | `agent/internal/app/app.go:107` |
| **sre-resilience** | `/api/audio/tts` 全仓**无速率限制/并发上限**（Edge TTS 公网 IP 易被限流） | `delector/routes/main.py:1085` |
| **sre-resilience** | Go agent 无顶层 `recover()`（panic 即整进程崩，概率低） | `agent/cmd/delector/main.go` |
| **sre-resilience** | 健康检查探针过浅（不反映 DB/LLM/外部依赖） | `delector/routes/tools.py:29` |
| **sre-resilience** | CI `pytest`/`go test -race` **无超时护栏**，挂起测试拖垮流水线 | `.github/workflows/ci.yml:87` |
| **sre-resilience** | Android `install "uvicorn"` 未锁版本；`spacy` 桌面/Android 口径不一 | `android/app/build.gradle:94` |
| **sre-resilience** | Android TTS 回退 `ssl._create_unverified_context()`（关证书校验，仅 Android 证书缺失路径） | `delector/services/tts.py:131` |

**code-reviewer 专项结论**：**红牌 0 张**；dead-green 排查**未发现**（路由守卫枚举真实 `router.routes`、i+1 守卫双向锚定、seed 变异表逐条钉值、测试隔离修复未削弱任何断言 —— 作者在点名规避死绿反模式）。

---

## 💡 Consensus Action Plan & Patches（按 ROI 排序）

1. **【P1·最高性价比·本地可测】修 Docker 部署入口** — `Dockerfile:18` 改 `CMD ["uvicorn","delector.server:app","--host","0.0.0.0","--port","8000"]`，并本地 `docker compose up` 验证。
2. **【P1·最高性价比·本地可测】启用 SQLite WAL** — `delector/core/database.py:53` 加 `PRAGMA journal_mode=WAL`（与现有 `synchronous=NORMAL` 是官方推荐组合）；Docker 侧改挂 `./data` 目录（`DELECTOR_DATA_DIR=/app/data`），使 `-wal`/`-shm` 旁文件随目录持久化。
3. **【P1·潜伏时弹】为 Android Python 契约加 CI 护栏** — 新增 PR 级 job，在 `pydantic<2.0.0` + `fastapi<0.100.0` 约束下对 `delector` 做导入/路由注册冒烟（`import delector.server`），把"桌面/Android 同源不一致"在合并前而非 tag 构建时暴露。
4. **【P1·产品信任】打通 i+1 已知词池与主流背词路径**（或显式合并且说明）— 要么让 `/api/cards` 也喂 i+1 覆盖率，要么在 i+1 引导里点名"卡盒里存的词不计入这里"并给一键迁移；同时用一句话（设置页/首次进入）说明 `KARTEI` 与 `VOKABELN` 的关系，收敛双词库心智。
5. **【P1·性能】给长难句 `source=all` 加聚合层缓存 + keyset 分页** — 把跨材料聚合结果纳入（或独立于）`_RANK_CACHE`，避免每次全语料 O(N句) NLP + 全表内存物化。
6. **【P2·顺手】** `exam_trials` 补索引、`_RANK_CACHE` 加容量上限 + 锁、`addCardToDeck` 去重对齐 `stripGermanArticle` 并补非对称测试、`test_encounter_addcard.py:393` 拆 OR、路由守卫比对前 `methods - {"HEAD","OPTIONS"}` 归一。
7. **【P2·复用阶梯】抽 `delector/core/german_norm.py::strip_leading_article`** 共享工具，让 `database._normalize_a1_headword` 与 `build_dict._normalize_b1_line` 共用同一冠词表（JS 副本继续用现有双向守卫锁死）。

---

## ♻️ Reuse Ladder Check

- **[提案] 抽 `german_norm.strip_leading_article`**：article-strip 当前在 4 处各维护一套。Ladder：stdlib `re` 已足够，**无需新依赖**；应复用为单一 in-repo 模块，database/build_dict 共用，JS 副本保持双向守卫。→ **Prefer reuse（合并散落，非新增依赖）**。
- 其余 P2 多为"加索引/加缓存/加超时"等就地改进，**不引入新依赖**，符合复用阶梯。

---

## 附：本报告的两条 P1 修复

- `Dockerfile:18` 入口模块名修正（`server:app` → `delector.server:app`）+ `tests/test_ci_hardening.py` 增加入口守卫。
- `delector/core/database.py::_configure_sqlite_conn` 增加 `PRAGMA journal_mode=WAL` + `docker-compose.yml` 改目录挂载 + `tests/test_server.py::test_db_busy_timeout_and_concurrency_guard` 增加 WAL 断言。
