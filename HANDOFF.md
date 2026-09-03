# 🤝 Agent Handoff & Continuation Card

> Generated 2026-09-02 after a `/vault-handoff` cycle.
> Anchor reads for the next session: this file, `AGENTS.md` (head 3-30 行), `README.md` (路线图 359-361 行), `.vault-exec-ledger.json`, `docs/plans/workbench-scope-control-and-live-settings.md` (Task 6 裁决)。

---

## 1. 📍 Current Breakpoint & Git State

| 项 | 值 |
| --- | --- |
| Branch | `master` |
| HEAD | `f9ec8c5 fix(release): align index.html v5.0.1 indicator and relax DeLector.spec test for CI` |
| Tags on remote | `v5.0.1` → `f9ec8c5`, `v5.0.0` → `3edc40a` |
| Working tree | ⚠️ **脏** — `M test_server.py`（+3 行 / 0 删除，详见 §4 语义解读） |
| Unpushed commits | 0（origin/master = HEAD） |
| Test baseline | ✅ **451 / 451**（per `AGENTS.md` 头部 + `.agent-context.md:4`，2026-09-01 实测） |
| Pre-commit scan | 启用中（`.githooks/pre-commit`，`PYTHONIOENCODING=utf-8`） |

---

## 2. 📋 完成与待办

### 2.1 本会话实际交付（ADR-0002 + v5.0.0 发布）
所有 7 个任务在 `.vault-exec-ledger.json` 已 `completed` / `active_task_id: null`：

| Task | 标题 | 提交 |
| --- | --- | --- |
| Task-1 | 顶栏分段控件 + 徽标模式前缀 | `7c86a78` |
| Task-2 | scope 收敛为单一写入口，删除 `#wScope` | `b22859a` |
| Task-3 | 搜索旁路 scope | `7c150b4` |
| Task-4 | `renormalizeQueueTail()` —— dailyNew 即时生效（含手动追加豁免） | `181e64c` |
| Task-5 | newOrder 即时生效 + 文案更正 | `581398c` |
| Task-6 | 行为级动态探针 `tools/wb_queue_probe.mjs` | `15612b9` |
| Task-7 | 全量回归与发布面同步 | `45eafc3` → annotated tag `v5.0.0` 已推送 |

`tools/wb_queue_probe.mjs`（31136 B）含 7 个场景、13 个 slice guard，**被 release 工程视为 v5.0.0 行为级合同**。变更需重跑 `--json` 全场景并对比基线。

### 2.2 用户在 `v5.0.0` 之后做的事（v5.0.1 patch）
你亲口说"v5.0.1 是我进行的修复 bug 的小版本更新"。从 git/AGENTS/README 读出的真实定位：

- **HEAD 表面的"小修补"措辞与实际变更面不一致**：25 文件 +1458/-598（其中 `static/js/reader.js` 单一文件 +1063/-几百行）——这是「多领域专家审计」合并，不是单点 hotfix。AGENTS.md:21 的整段说明是真实定位。
- **canonical release notes**：
  - `AGENTS.md:21` — "v5.0.1 专家审计缺陷修复：RestoreReq 补全 A1 记录防止还原数据丢失、FSRS elapsed_days 遗忘动力学修复、局域网敏感 DELETE 端点回环拦截、past tense 动词反查碰撞修复、从句拓扑介词边界识别、euer/entlang 变格修复、a1_hoeren 词汇卡 XSS 加固、main.js 显式导出 A1 命名空间"。
  - `README.md:361` — 4 大块「① 存储与 FSRS / ② 安全与可靠性 / ③ 语言学与句法 / ④ 前端加固」详细版，测试 **451 全绿**。
- **两次提交**（author = `Haoyu Xi <beianderen@gmail.com>`，2026-09-01 18:50 / 18:54 北京时间，提交正文皆为空）：
  - `a182d53` — "fix(release): v5.0.1 multi-expert audit hardening and bug fixes"（24 文件，1455/-597，含 `test_audit_regressions.py` 新建 89 行）
  - `f9ec8c5` — "fix(release): align index.html v5.0.1 indicator and relax DeLector.spec test for CI"（2 文件，6/-4）
- **新测试文件** `test_audit_regressions.py` 是 v5.0.1 期间为防回归而建的，需要 next agent 看清覆盖范围。

### 2.3 待办（next agent 必须明确处理）
- ⏳ **脏 `test_server.py` 3 行 → 提交**（语义见 §4）。**这是本卡唯一剩留工作**，按习惯应与 `docs:`/ `test:` 标的新 commit 一起落地。
- ⏸️ **v5.0.1 后继意图**（用户原始关注点）—— 等用户指令。
- ⏸️ **真机 APK 验签** —— `f9ec8c5` 提交说明里"真机验收作废"留过旧线；本地无 Android SDK，需 CI 验签（按 [no-apk-verification](no-apk-verification.md) 信任 CI 链路）。

---

## 3. 🧪 v5.0.1 关键变更面（按领域，给 next agent 当 anchor）

| 领域 | 文件 | 净变化 | AGENTS/README 措辞 |
| --- | --- | --- | --- |
| 存储 / FSRS | `database.py`(未列) / `server.py` | +92 / -几 | RestoreReq A1 还原补全、`review_card_sm2` 动态 `elapsed_days` |
| 安全 / 可靠性 | `security.py` `routes_sync.py` `package_windows.py` | +76/+20/+2 | DELETE 端点 `_require_localhost`、2MB 流式拦截、合法端口限制、Edge TTS stdlib 降级链、corpus_dict 打包补齐 |
| 语言学 / 句法 | `linguistics.py` `syntax_tree.py` `writing_rules.py` `routes_a1.py` | +49/+82/+55/+8 | 过去时反查碰撞（`standen`→`stehen` / `gingen`→`gehen`）、介词从句后场边界、`euer`/`entlang` 变格 |
| 前端加固 | `static/js/reader.js` `static/js/main.js` `static/js/a1_hoeren.js` `static/js/a1_lesen.js` | +1063 / +14 / +21 / +21 | `jsAttr()` 防 XSS、main.js 显式 A1 命名空间 + 切页停止模考 |
| 测试 | `test_audit_regressions.py`(新) `test_server.py` `test_writing_rules.py` `test_frontend_security.py` `test_frontend_module_graph.py` | +89/+269/+63/+18/+17 | 451 cases |
| 元数据 | `AGENTS.md` `FEATURES.md` `README.md` `.agent-context.md` `static/index.html` `static/sw.js` `android/app/build.gradle` `.github/workflows/build-release.yml` | docs + docs + docs | release 标注同步 |

> 注：`static/js/reader.js` 净增 1063 行是异常值——多半是含 `euer`/`entlang` 等变格测试 fixture 或行内扩注释；具体语义需 next agent 抽样审计。

---

## 4. ⚠️ 脏 `test_server.py` 3 行的精确语义

`f9ec8c5` 把两条 `assert "'corpus_dict'" in spec` / `assert "'routes_corpus'" in spec` 放在 `if os.path.exists(spec_path):` 内（提交说明 "relax ... for CI"，CI 干净 checkout 无 `DeLector.spec` 则跳过）。

你的脏改动把这两条 assert **前移至 guard 之前**，效果相反：

```python
# 你加的（行 3661-3663，未提交）
spec = open(os.path.join(root, "DeLector.spec"), encoding="utf-8").read()
assert "'corpus_dict'" in spec
assert "'routes_corpus'" in spec
# f9ec8c5 已有的（行 3664-3668，已提交）
spec_path = os.path.join(root, "DeLector.spec")
if os.path.exists(spec_path):
    spec = open(spec_path, encoding="utf-8").read()
    assert "'corpus_dict'" in spec
    assert "'routes_corpus'" in spec
```

**这是有意识的"un-relax"**：永远要求 `DeLector.spec` 存在且含 `corpus_dict` / `routes_corpus`（防止 CI 漏配），而非 CI 友好地跳过。本地 `pytest test_server.py -k test_task1_corpus_dict_*` 实测 **1 passed**（`DeLector.spec` 当前确实在仓库里且含目标模块，见 §3 列出的 `DeLector.spec:1710` 9 月 1 日 18:36 写入）。

**建议 commit 标**：`test(workbench): harden corpus_dict / routes_corpus spec assertion (un-relax from f9ec8c5)`。提交前用 `git diff test_server.py` 二次确认无别的意外编辑，并跑一次全量 `pytest test_server.py -k "test_task1_corpus_dict_registered_in_all_packaging_targets"` 留证。

---

## 5. 🧠 Karpathy Ingestion 状态（已沉淀，无新动作）

- **Inbox 草稿**：`d:\Obsidian\Coding\99-Inbox\2026-09-01-inconsistent-fixture-fabricates-bugs.md`（3084 B）—— 本会话产出的跨项目教训，定义「恒假夹具 (inconsistent fixture)」并给出 4 条可复用检查。
- **项目 memory**：`workbench-probe-synthetic-fixture.md`（1479 B）—— 具体到本仓库：探针 `__setup` 假造完成态、`todayNw:0` 与 `ratedCount:23` 互斥、`reachableFinished` 才是真测。
- **全局 memory**：`github-push-via-ssh-443.md`（已按 2026-09-01 实测修订）—— 关键句「MSYS ssh 读不到 Windows ssh-agent；必须用 `C:\WINDOWS\System32\OpenSSH\ssh.exe` 经 `GIT_SSH_COMMAND=... ssh.exe -p 443`」。
- v5.0.1 未引入新可沉淀模式（multi-expert audit 模式是工程方法而非代码 invariant，不入 Inbox）；如 next agent 在 v5.0.1 代码里发现新踩坑，按 `01-Rules/AGENT-CONDUCT.md` 走 save_inbox_draft。

---

## 6. 📜 Codebase Snapshot (V5.0.1 surface)

```
HEAD         : f9ec8c5  v5.0.1
Last v5.0.0  : 3edc40a
ADR-0002 plan: docs/plans/workbench-scope-control-and-live-settings.md  (Task 6 裁决)
Probe        : tools/wb_queue_probe.mjs                                  (7 scenarios, 13 slice guards, 31136 B)
Ledger       : .vault-exec-ledger.json                                   (7/7 completed, active=null)
Context      : .agent-context.md                                         (v5.0.1, 451 tests, 2026-09-01)
Releases     : AGENTS.md:21-22, README.md:361                            (canonical release notes)
Test files   : 19 个 test_*.py 总计 451 断言
Worktree     : M test_server.py (+3)                                      ← 待提交
```

---

## 7. 🚀 1-Click Continuation Prompt

```
Resume `d:\Code\DeLector` at the **v5.0.1 post-release checkpoint**
(HEAD `f9ec8c5`, 451 tests green, annotated tag `v5.0.1` pushed).

**First three moves (顺序不可调换)**:
1. `cd d:\Code\DeLector && git status --short && git log --oneline -n 5`
   确认与本卡 §1 一致；预期 `M test_server.py`。
2. `git diff test_server.py`
   确认那 3 行是 §4 描述的「un-relax from f9ec8c5」，不是别处改动。
3. `export PYTHONIOENCODING=utf-8 && pytest test_server.py -k test_task1_corpus_dict_registered_in_all_packaging_targets -v`
   留 1 passed 证据后，按 §4 建议的 commit 标做一次提交并 `git push`。

**Anchors to read**:
- `AGENTS.md` 头部表 + `:21-22`（v5.0.1 release notes）
- `README.md:361`（v5.0.1 详细路线图条目）
- `.agent-context.md`（v5.0.1 baseline）
- `tools/wb_queue_probe.mjs`（v5.0.0 行为合同；v5.0.1 期间未触）
- `test_audit_regressions.py`（v5.0.1 新建的审计回归测试，需看清覆盖范围）

**Then ask the user**：
- 脏 `test_server.py` 是否按建议 commit？
- v5.0.1 后继是「接着修 v5.0.2」还是「新功能方向」？
- `static/js/reader.js` 净增 1063 行是否需独立审计？
```

---

## 8. 🧷 Cross-references

- 记忆索引：`C:\Users\Haoyu\.claude\projects\d--Code-DeLector\memory\MEMORY.md`
- 关键 memory：[github-push-via-ssh-443](github-push-via-ssh-443.md) / [workbench-probe-synthetic-fixture](workbench-probe-synthetic-fixture.md) / [dangling-identifier-kills-module-graph](dangling-identifier-kills-module-graph.md) / [readme-must-sync-on-push](readme-must-sync-on-push.md)
- 跨项目教训 inbox：`d:\Obsidian\Coding\99-Inbox\2026-09-01-inconsistent-fixture-fabricates-bugs.md`
- 知识库总路由：`d:\Obsidian\Coding\AGENTS.md` / 精准检索 `python d:\Obsidian\Coding\scripts\search-vault.py "<query>"`
- 仓库根：`.agent-context.md` / `.vault-exec-ledger.json` / `CLAUDE.md`

---

> **会期收口结论**：
> - ADR-0002 + v5.0.0 本会话交付完整（ledger 7/7 ✅，tag pushed）。
> - v5.0.1 是你亲自做的多领域审计修复（25 文件，但定位在 AGENTS.md:21-22 与 README.md:361 有清晰四分类说明）。
> - 唯一待办是 §4 的脏 `test_server.py` —— 一条 commit 的事。
> - 已知 release notes 已同步到 AGENTS/README/FEATURES/.agent-context 四个文档面，无遗漏。
