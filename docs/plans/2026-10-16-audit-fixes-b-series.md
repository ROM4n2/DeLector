# B 系列未决项实施计划（审计修正批次 3）

> **Goal**: 落地 `docs/reviews/2026-10-16-open-items-backlog.md` **B 档**：B1 分支纪律机械闸 · B2 `.gitattributes` CRLF 契约 · B3 `design-system.md` 补入口 + 过时内容更新 · B5 实验 harness 工程前置。**B4（`database.py` 切分）单独开分支与 PR**（2809 行结构重构混进 bugfix PR 会让评审无法进行）。
> **Tech Stack**: Python 3.11 / pytest / GitHub Actions（ubuntu + self-hosted Windows）/ 原生 JS（零构建）/ git hooks
> **Spec Reference**: `docs/reviews/2026-10-16-commit-rhythm-and-git-management-audit.md`（B1=P1-1、B2=P2-7）· `docs/reviews/2026-10-16-repo-structure-and-docs-audit.md`（B3=P2-4/P2-1）· ADR-0024「已知未决」（B5）· `docs/plans/2026-10-15-judge-gaming-experiment.md`（harness 正本）
> **Global Constraints**:
> - **B1 改 CI 定义 ⇒ 合并走 SSH 本地 `--no-ff`**（`gh` token 无 `workflow` scope；#136/#137 已演示该路径）。⚠️ 机械闸 MUST **fail-loud 且可解释**（报出违规 sha + 文件 + 为什么被拒），**MUST NOT** 出现"拦不住真实情况却让人以为拦住了"。
> - **B2 改的是跨平台行为**：`.gitattributes` 里 `* text=auto eol=crlf` MUST 置于既有 `*.go text eol=lf` **之前**（具体规则覆盖通用规则），且加完后 MUST 用 `git ls-files --eol` 抽查 3 处（`.py`/`.md`/`.js`）确认工作区口径未反转、blob 未被动。
> - **B3 是文档**：补入口（`AGENTS.md` 路由表 + `README` 导航）+ **逐条比对现测**，过时即改；每个被改的数字 MUST 来自本次实测；改完在文首加"同步日期 + 口径来源"。
> - **B5 不改实验结论**：只补工程前置；**MUST NOT** 触发任何真跑（无用户确认不得发真实 API 调用）；`temperature` 钉定与 `usage` 透出是**最低两件**。
> - 零新依赖 / CRLF / `ruff check .` 零告警 / `mypy --strict delector`（脚本按所在档）/ 中文注释。
> - **进程纪律（本会话血泪）**：任何新增测试 MUST NOT 起无界子进程链；`subprocess` 调用 MUST 有超时 + 递归哨兵（参见 `tests/test_get_endpoints_with_writes.py` 的两道防线范式）。
> - **负载纪律**：本地只跑定向文件；**全量交 CI**。
> **Branch**: `fix/audit-a-series`（延续 #143；B4 另开 `refactor/database-split`）

---

### Task 1: B1 —— master 直推范围的机械闸 [Tier: 3-Critical] [Mode: HITL] [Role: TDD Builder]

**Files:** Create `tools/check_master_commit_scope.py`（可测的判定器）· Create `.githooks/pre-push` · Modify 一份 workflow（新增 job，触发条件 `push` 到 `master`）· Test `tests/test_ci_hardening.py`

**Interfaces:**
- Consumes: `git rev-list`/`git show --name-only`（只读）· 推送范围 `${{ github.event.before }}..${{ github.sha }}`（CI）/ pre-push stdin 的 `local_ref local_sha remote_ref remote_sha`
- Produces: `def check_scope(changed_files: Sequence[str], *, subject: str) -> list[str]`（返回违规原因列表，空 = 通过）+ CLI `python tools/check_master_commit_scope.py --range <from>..<to>`（退出码 `0=通过 / 1=有违规 / 2=环境不可用`，照 `tools/bench_judge_fp.py` 惯例）· 白名单常量 `MASTER_DIRECT_ALLOWLIST`：`WORKMEMORY/` · `docs/` · `README.md` · `CHANGELOG.md` · `static/index.html` · `static/sw.js` · `android/app/build.gradle` · `delector/core/version.py`

**Subagent Prompt Scaffold (for /dfs-exec):**
> "给本仓唯一'已实发过事故'的纪律缺口加机械闸（`docs/reviews/2026-10-16-commit-rhythm-and-git-management-audit.md` P1-1：2026-10-09~14 有 25 个 feat/fix/ci/test/perf 提交直推 master，已实发 `f49d359` 推红事故）。做成**可测的判定器 + 两道接线**：① `tools/check_master_commit_scope.py`（纯函数 `check_scope(files, subject)` + CLI，退出码 0/1/2）；② `.githooks/pre-push`（读 stdin 的 ref 行，对推往 `refs/heads/master` 的范围调用它；不适用时**明确打印跳过原因**，不许静默通过）；③ 一份 workflow 新增 job（仅 `push` 到 `master` 触发，用 before..sha 范围）。判定规则：**非 merge 提交**（`git rev-list --no-merges`）的改动面 MUST ⊆ 白名单，否则退出 1 并打印「违规 sha + 文件 + 命中规则」。**必须有豁免出口**：仓库最初的提交 / `--bootstrap` 模式（否则历史回溯会全红）与"范围不可判定"（首次推送）时**打印明确警告后通过**，并把两条豁免都写进用例。"

**Step Breakdown:**
- [ ] Step 1: RED（判定器纯函数用例：白名单内通过 / 出界文件红 / merge 提交豁免 / bootstrap 豁免 / 范围不可判定时 warn-through）
- [ ] Step 2: 记录预期失败原文
- [ ] Step 3: 实现判定器 + pre-push + workflow job（GREEN）
- [ ] Step 4: 变异自证（把白名单放宽到 `**` ⇒ 出界用例红；把 merge 豁免删掉 ⇒ 合并提交用例红）
- [ ] Step 5: 用真实历史范围跑一次（贴"通过/违规"原始输出）+ ruff + mypy + CRLF + 原子提交

---

### Task 2: B2 —— `.gitattributes` 把 CRLF 从"本机副作用"升级为仓库契约 [Tier: 2-Standard] [Mode: AFK] [Role: Orchestrator 直执行]

**Files:** Modify `.gitattributes`

**Interfaces:**
- Consumes: 既有 4 组规则（`agent/**/*.go` → `text eol=lf` 等，实测生效）· 本机 `core.autocrlf=true`（**系统级**，不可入库）· `git ls-files --eol` 抽查口径
- Produces: 新增 `* text=auto eol=crlf`（**置于 `*.go text eol=lf` 之前**）+ 注释写明"与 `ops.md` 的行尾纪律一致；具体规则覆盖通用规则"

**Step Breakdown:**
- [ ] Step 1: 加规则（一行 + 注释）
- [ ] Step 2: `git ls-files --eol` 抽查 `.py`/`.md`/`.js`/`.go` 四类，确认：通用规则未反转 go 的 `eol=lf`、blob 未被重写
- [ ] Step 3: 提交（Tier 1/2 边界：单行配置改动，编排者直执行 + 物理取证）

---

### Task 3: B3 —— `design-system.md` 补入口 + 过时内容更新 [Tier: 1-Light→2] [Mode: AFK] [Role: TDD Builder]

**Files:** Modify `docs/design-system.md` · Modify `docs/README.md`（若分层表需要）· Modify `AGENTS.md`（路由表补行）· Modify `README.md`（文档导航补行）

**Interfaces:**
- Consumes: `docs/README.md:16`（把它列为**顶层常青规范**却全仓零入口）· 审计实测：`--bone`/`--ink-blue`/`--paper-dark`/`--paper-dark-box`/`--rule-dashed`/`--shadow-exhibit`/`--reveal-delay` 七个 token 与 `#F7F1DE`/`#DDD2B6`/`#15140F`/`#2A528A`/`#C8BFA9` 五个色值在 `static/style.css`、`static/css/tokens.css`、`static/german/` **逐个 grep 零命中**
- Produces: ① 三处入口（AGENTS 路由表 + README 导航 + 必要时 docs/README 分层表）；② `docs/design-system.md` 文首加「状态行：现行 / 历史稿 + 同步日期 + 口径来源（`static/css/tokens.css` 等）」；③ **逐条过时修正**：token 表按 `static/css/tokens.css` 现值重写（或标注"历史稿，现值为 X"）、失效的组件/路径/版本声明逐条更正；④ 无法判定是否过时的条目**如实标注**（不许静默保留）

**Subagent Prompt Scaffold (for /dfs-exec):**
> "`docs/design-system.md`（606 行）被 `docs/README.md:16` 列为顶层常青规范，但 `AGENTS.md` 路由表与 `README` 导航**都没有它** ⇒ 全仓零入口；且 §4 的 token 表与 CSS 脱节（7 token + 5 色值逐个 grep 零命中）。本任务两件事：① **补入口**（AGENTS.md 路由表加一行；README 的文档导航加一行；必要时同步 docs/README 分层表措辞）；② **过时审查**：以 `static/css/tokens.css` + `static/style.css` + `static/german/` 的**实际值为准**逐条比对文档里的 token 名/色值/组件名/文件路径/版本声明，**过时即改并记录改了什么**；确实找不到对应实现的条目改成「历史稿」标注而不是删掉（历史价值保留）。文首加状态行（现行/历史 + 同步日期 + 口径来源）。⚠️ 所有新数字与色值 MUST 从 CSS 现读（贴 grep 证据），**禁止凭印象填**。"

**Step Breakdown:**
- [ ] Step 1: 现读 CSS 的 token/色值真值（贴 grep 原始输出）
- [ ] Step 2: 逐条比对 606 行，列出「过时 / 仍准确 / 无法判定」三类清单
- [ ] Step 3: 改文档 + 补三处入口（GREEN）
- [ ] Step 4: 物理取证（新值在 CSS 中逐个命中；旧值 grep 计数归零；三处入口 grep 可见）
- [ ] Step 5: ruff（若含代码块）+ CRLF + 原子提交

---

### Task 4: B5 —— 实验 harness 工程前置（7 件，**不触发真跑**） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:** Modify `tools/bench_judge_gaming.py` · Modify `tools/bench_judge_rater.py` · Modify `delector/services/llm_client.py`（仅**新增** `usage` 透出，不改既有返回形状）· Test `tests/test_bench_judge_gaming.py` · Test `tests/test_bench_judge_rater.py`

**Interfaces:**
- Consumes: `RunRecord`（现状只记 `model`）· `RealChat`（现状**不传** `temperature`、payload 里连 `seed` 都没有 ⇒「同输入同输出（无随机）」对 `--real` 是**假陈述**）· 成本现走 `ceil(len/3.0)` 且**只计 completion、不计 prompt**（系数登记 UNVERIFIED）· rater **零 `__main__`/argparse** 却写进交付物
- Produces（7 件）：① 逐篇**增量落盘** + `--resume`（已跑篇目跳过）· ② 有界重试（429/5xx/传输层，2 次 + 指数退避 + jitter）· ③ `temperature` **显式钉定并记入 `RunRecord`**（并记录模型名；无 `seed` 的事实写进输出头）· ④ `--real` **连通预检**（一次最小 chat，失败即退出 2）· ⑤ **成本硬闸**（token/估算上限 + 独立退出码）· ⑥ rater 补**可执行入口**（或在交付物清单里显式移除）· ⑦ `llm_client.chat` 新增 `usage` 透出（prompt/completion 分别记），`RunRecord` 记真值并保留估算为对照

**Subagent Prompt Scaffold (for /dfs-exec):**
> "补 §4.3 第 8 条实验 harness 的七件工程前置（ADR-0024「已知未决」）。**本任务 MUST NOT 发任何真实 API 调用**（无用户确认）；全部测试走 `--dry-run`/stub。① 逐篇增量落盘 + `--resume`：每篇三臂跑完即写一行 JSONL（含 `case_id`/`arm`/`RunRecord` 全字段），中断后重跑只补缺篇（否则一次瞬断即全损、连残值都拿不到）；② 有界重试：429/5xx/传输层错 2 次、指数退避 + jitter（chat 无副作用 ⇒ 幂等），超限即把该篇标记 failed 并继续；③ `temperature` 显式钉定（写进 payload）并记入 `RunRecord`，输出头记录模型名 + 「DeepSeek 无 seed ⇒ 同输入不同输出」的事实（现状 `RunRecord` 只有 `model`，全仓 `temperature` grep 零命中）；④ `--real` 前先发一次最小 chat 做连通预检（失败退出 2）；⑤ 成本硬闸：`--max-total-tokens` / `--max-est-cost`，触顶即停并退出独立码；⑥ rater 补 `__main__`/argparse（或从交付物清单移除）；⑦ `llm_client.chat` **只新增** usage 透出（不改既有返回形状），`RunRecord` 记真 prompt/completion token，估算值保留为对照。反挂死：所有 subprocess/网络调用 MUST 有超时；新增测试 MUST 有递归哨兵范式。"

**Step Breakdown:**
- [ ] Step 1: RED（续跑幂等 / 重试退避 / temperature 与模型名入记录 / 连通预检退出码 / 成本闸退出码 / rater 入口存在 / usage 真值入记录 —— 全部 stub，零真跑）
- [ ] Step 2: 记录预期失败原文
- [ ] Step 3: 实现七件（GREEN）
- [ ] Step 4: 变异自证（抽掉 `--resume` 去重 ⇒ 续跑用例红；把 temperature 删掉 ⇒ 记录用例红；把成本闸删掉 ⇒ 触顶用例红）
- [ ] Step 5: `--dry-run` 全链路跑一次 + ruff + mypy 档 + CRLF + 原子提交

---

## 🚫 Out of Scope

- **B4 `database.py` 切分** —— 另开 `refactor/database-split` 分支与 PR（先补契约测试再动骨架）；本计划不含。
- **C 档全部**（C1 回灌子计划 / C2 三条 UNVERIFIED / C3 真 token 回测 / C4 真机点检 / C5 Pi 重构 / C6~C8）。
- **不做任何真实 API 调用**（B5 只补前置）。
