### 2026-10-05 00:30 | codebuddy | DONE(debt-clear-round) + RELEASE(v5.14.0)

> 本文件是 `WORKMEMORY/work.log` 中该事件的**正文**（原事件 4424 B，超 `PROTOCOL.md` §4 的 4096 B 上限）。
> 拆分时间：2026-10-14；正文逐行无损搬运，未删改任何内容。

Caps: filesystem-read, filesystem-write, shell-exec
事件：清债轮三组并行完工并全部合入 master（`4aed9fa`），随后发版 **v5.14.0**（tag 已打，触发三平台 Release 流水线）。
- **A 组 #99**（`static/js/cards.js`）：目录/网格视图 `renderCatalogGrid` 两处硬编码 `correct_count/wrong_count` 改用 `cardStatsTag`——此前**同一条词卡面说「📚 工作台 · s=25」、目录说「0 正 / 0 误」**。核实「换用后不丢 `due_date`」：`cardStatsTag` 非工作台词分支自带 `⏳ 到期:`。语法卡一并换用，论据 `grammar_cards` 表**无任何 `fsrs_*` 列**（建表 `database.py:341-361` 无 + 迁移 `:478-511` 的 `fsrs_*` 补列显式包在 `if tbl == "vocab_cards"` 内）。「去工作台」改 `preventDefault` + `window.show('german')` 留主站壳内，`href` 逐字保留供新标签页；**关键事实**：`show` 定义在 `main.js:167`，靠 `main.js:943-946` 的 `Object.assign(window,{show})` 显式挂载才可从 inline `onclick` 取到（顶层 `function` 不会自动挂 `window`）。
- **B 组 #100**（`static/js/encounter.js`）：`fetchKnownLemmas` 加 in-flight 去重（原一次会话读 N 篇打 N+1 次后端）。**刻意不做 TTL 缓存**——串行重复是「每篇刷新一次」的正常语义，TTL 会让「刚背的词在 TTL 内不出现」。覆盖率行**标注降级来源**（离线/镜像失败原本静默显示 0/312，用户无法分辨「真没背」与「拉取失败」）⇒ `⚠ … · 数据不完整` + `title` 并列原因。核实两路降级**只压低分子不动分母**（`total` 来自 annotate 端点的 token 流，非 `resolveDeck`）。**越界自报**：改了既有 `enc_open_race_probe.mjs` 35 行——场景 B 原用「两次 `known-lemmas` 错开」制造时序，而那正是本次要消灭的重复，**逻辑上不可能两立**；改由 `resolveDeck` 的 `/api/wb/state`（无去重）承担，4 条原契约断言语义逐条未动；编排者独立复验判别力：删 `encounter.js:642` 内部 seq 守门 ⇒ 场景 B 必红。
- **C 组 #101/#102**（`tests/`+`.github/`）：复核**推翻两条编排者前提**——①漏项是 **8 个不是 7 个**（含 #98 刚建的 `cards_workbench_no_review_probe`，**守白复习 P0 的守卫从未进过 CI**）；②这批探针**都不返回** `failures/total/cases`（24 个 `.mjs` 仅 4 个标准契约）⇒ 未改任何 `tools/*.mjs`，改断言 `ok is True`（因「problems 非空即 exit 1」，与 `failures==0` 等价且更紧）。`ci.yml` **显式装 Node 20**——此前 wrapper 靠 `ubuntu-latest` 预装，属隐式依赖：镜像一换版本探针走 `shutil.which` **静默 skip**，测试全绿而探针没跑，**比红更坏**。
- **编排者实测出并修掉一个假绿漏洞**：`test_probe_wiring_guard.py` 的 corpus 拼入全部 `.py`，而共享 helper `probe_runner.py` 的**文档字符串点名了真实探针** ⇒ 移走真 wrapper 守卫**仍绿**。复现：`mv tests/test_cards_count_probe.py` 后守卫 `1 passed`。三管齐下修复：corpus 收窄到 `rglob("test_*.py")`（pytest 收集规则如此，不参与收集的文件本来就不可能是 wrapper）+ helper 文档举例去实名化 + 新增守卫钉住收窄。复验：`1 failed` / 还原 `5 passed`。
- **守卫立刻抓出存量漏接线**：#102 合并前，半 A 跑出 `1 failed, 1015 passed`——三个并行分支各自新建的探针无 wrapper，防漏接线守卫当场把 **3 个**顶出来，补齐后 `1025 passed` 零 failed。**这正是「先立守卫 → 立刻把存量漏接线顶出来 → 按红补齐」的顺序价值**。
⚠️ 编排者本轮失误：用 `grep … | head -8` 截断守卫输出 ⇒ 只看到 3 个漏接线里的 2 个，给 maker 的任务书写错数字；**maker 停下上报而未擅自扩大范围**，才没造成二次返工。教训：提取失败项/统计行**禁用 head/tail 截断**；管道还会吃掉上游退出码（同 `if git push | tail -1` 误报成功那次）。
**门禁（v5.14.0 基线）**：`1289 passed + 1 skipped`（半 A `1025` + `test_server` `264`）/ 全 `tools/*.mjs` 探针 **27/27** / `ruff` 0 / `mypy` 两道（`delector`+`tools` 70 files、`tests` 88 files）0 error / `test_writer_mobile.py`（发版守护）`30` / 防漏接线守卫 `5`。

