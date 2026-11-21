# 基础设施加固 Implementation Plan

> **Goal**: 把 2026-11-21 软著执行中暴露的基础设施缺口转化为机械闸或可复核规则，防止同一模式第三次换马甲复发；**严格区分归属**——DeLector 仓库改动走本计划分支/PR，上游 skill 真值改动只落 skill 文件态、不入库、不在仓库文档里写本机绝对路径。
> **Tech Stack**: Python 3.11（门禁脚本 / pytest）、Bash（本机钩子）、GitHub Actions（CI 接线）、Git（分支/PR/merge）
> **Spec Reference**: 知识库 `01-Rules/GIT-CONVENTIONS.md`（流程规矩配机械闸 / 上下文切换重判前置条件）、`01-Rules/CODING-UNIVERSAL.md` §9（数据棘轮 vs 实现契约）、`01-Rules/TESTING-PATTERNS.md`（死测防御 / 变异自证）、`01-Rules/AUTOMATION-VERIFICATION-THREE-PROOFS.md`（自动化接线三证）；`WORKMEMORY/PROTOCOL.md` §1.3/§1.6/§5.1；上游 skill `dfs-bootstrap/SKILL.md` Phase 1b（gate 版本管理 / doctor）；复盘见 `WORKMEMORY/work.log` 2026-11-21。
> **Global Constraints**: ① **归属分离**：上游 skill 真值（`<skill-root>/templates/**`、`scripts/dfs_bootstrap/**`、skill 测试）只改本机知识库文件态，**不写进仓库、不在仓库计划/脚本/文档里出现其绝对路径字面量**——统一用 `<skill-root>` 占位；仓库侧只放项目特有文件。② 数字/基线来自自测，不抄旧值、不手改棘轮上限。③ 新增判据必须配变异自证（撤掉接线点测试 MUST 红，防 dead-green）。④ 数据棘轮与实现契约分开标注。⑤ 本机隐私信息用 `<repo>` / `<user>` / `<skill-root>` 占位，不写绝对路径字面量。⑥ 一 Task 一分支一 PR，禁直推 master；**上游 skill 任务无仓库 commit**，只有文件态变更 + 测试回执。⑦ 全程只对点测试，不跑 DeLector 全量 pytest（2026-11-13 裁决）。⑧ 改了哪个文件就跑覆盖它的每档门禁。⑨ UTF-8 输出，禁用 head/tail 截断核验。
> **Branch**: 仓库任务各自从 `master` 切 `<type>/<slug>` 分支、独立 PR 落地。上游 skill 任务（Task A/B）不在仓库开分支、无 commit。本轮**不声明** `release` / `bookkeeping` 例外——Task 1/3 含门禁源码与 CI 定义，必须走 PR。

---

## [NOTE] Decisions So Far

- **归属三分**（本计划的核心修正）：
  - **仓库内**（DeLector，走分支/PR）：`docs/agents/ops.md`（用法说明）、`WORKMEMORY/PROTOCOL.md`（本项目簿记协议）、`tests/*`（项目测试）、`scripts/check_pr_no_regression.py` + `.github/workflows/ci.yml`（项目特有工作流）。
  - **上游 skill 真值**（`<skill-root>`，文件态、不入库）：`templates/local-gates/fingerprint-gate.sh`、`SKILL.md`、`tests/test_template_quality.py`。
  - **项目自有的 installed copy**：`scripts/check_repo_hygiene.py` 与上游模板 sha256 不同（实测 `3060e…` vs `abe89…`，diff 1126 行）、头部**无** `# dfs-bootstrap-gate-version:` marker——按 SKILL.md Phase 1b，这是受保护的 *project-owned copy*，上游不会覆盖。它不是"漂移"，不得强行同步（同步会丢项目定制）。
- 指纹闸 PATTERN 已于 2026-11-21 收紧（本机 + 上游模板一致，sha256 同为 `570707…`）。缺口 2 剩余两项：① 把"禁列裸目录名"从注释升级为可被变异自证打破的测试（Task B）；② 让**新项目初始化时自动装好本机 gate**（Task A）——实测 bootstrap 目前只手工复制模板（SKILL.md "Copy it by hand"）、doctor 在 DeLector 零接线、pre-push 只覆盖已装项目；正确触发点是 bootstrap 初始化那一次，不进 AGENTS.md（每次读 = 噪声）。
- ratchet 算法本身正确（scope-granular + `--emit-baseline`/`--ratchet-guard` 成对）；问题是"轮转改变计数"这一状态属性无声明、冲突无裁决顺序。
- PR #411 事故根因是分支依赖只存在人脑；用"合并前净 diff 机械校验"最小闸兜底，不引入依赖解析框架。
- 上游 skill 目录不是 git 仓库；其改动只有文件态 + 测试回执，无 commit hash。
- **ledger 只登记仓库任务**（`Task 1/2/3`）——`vault_exec_state.py` 仅识别数字编号；`Task A/B` 属上游 skill 文件态、无 commit hash，按本计划顺序**先手动执行**（A→B），再 `/dfs-exec` 跑台账里的 1/2/3。执行 A/B 时把测试回执（exit code + stdout）贴入工作日志即可，不写 commit。

---

## [NOTE] Active Frontier (Unblocked Tasks)

> 排序说明：上游 skill 任务（Task A/B）先做——它们是后续仓库任务的真值源；仓库任务（Task 1/2/3）后做。编号沿用"上游 A/B + 仓库 1/2/3"以保留讨论对应关系。

### Task A: bootstrap 初始化时幂等安装/升级本机 gate [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]
*(对应复盘缺口 2；**方向再修正**：doctor 没人跑（实测零接线）、pre-push 自检只覆盖"已安装"的项目——两者都解决不了"新项目压根没装"。本机 gate 属项目初始化职责 ⇒ 归 dfs-bootstrap；触发点 = agent 执行 bootstrap 那一刻，**不进 AGENTS.md**（每次会话都读 = 噪声）)*

**Files (全部在 `<skill-root>`，不在仓库):**
- Modify: `scripts/dfs_bootstrap/gates.py`（仿照 `install_gates` 增 `install_local_gate(target, dry_run)`：把 `templates/local-gates/fingerprint-gate.sh` 幂等复制到 `.git/local-gates/`，用 `hook.py` 的 `installed_version`/`_install_or_upgrade` 版本范式；**只写 `.git/` 私有态、绝不进仓库跟踪树**；不覆盖用户已有的 `fingerprints.txt`）
- Modify: `scripts/dfs_bootstrap/cli.py`（bootstrap 主流程调用 `install_local_gate`，受 `--no-gates` 控制、支持 `--dry-run`）
- Modify: `SKILL.md` Phase 1b（写明 local-gate 由 bootstrap 安装到 `.git/`、本机私有不入库；保留"模板自身无本机标识"的既有说明）
- Test: `tests/test_bootstrap_script.py` + `tests/test_template_quality.py`（新增：bootstrap 跑后 `.git/local-gates/fingerprint-gate.sh` 存在、重复跑幂等、版本升级、fingerprints.txt 不被覆盖、repo 跟踪树零命中；删安装调用则红）

**Interfaces:**
- Consumes: `templates/local-gates/fingerprint-gate.sh`（`<skill-root>` 模板）；`hook.installed_version` / `_install_or_upgrade`（`hook.py:31/126` 已核对）
- Produces: `def install_local_gate(target: Path, dry_run: bool) -> bool`；bootstrap 后 `<target>/.git/local-gates/fingerprint-gate.sh` 存在且带版本标记、`<target>` 的 `git ls-files` 不含它

**SSOT Effect:** —（无数字入报告）

**关键约束（来自既有测试 `test_is_not_installed_into_a_target_tree`）:**
- 该测试禁的是"把 local-gate 复制进**仓库跟踪树**"（`templates/repo/**` 才进跟踪树）——不是禁装到 `.git/local-gates/`。本 Task 只写 `.git/` 私有态，与之不冲突；实现后该测试仍须绿。

**Injected Instincts:**
- [ ] `[Instinct: Right-Trigger]`: 安装归 bootstrap（项目初始化那一次），**不写进 AGENTS.md**（每次读 = 噪声），不假手 doctor（没人跑）。
- [ ] `[Instinct: Local-Only]`: 只写 `.git/local-gates/`，不进跟踪树、不接 CI（云端无 `.git/local-gates/`）。
- [ ] `[Instinct: No-Rationalization]`: skill 代码/测试/文档不得出现本机绝对路径字面量；模板路径运行期从 skill 根解析。
- [ ] `[Instinct: Idempotent]`: 重复 bootstrap 不重复写、不覆盖用户本机 `fingerprints.txt` / `fingerprint-allow.txt`。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task A: bootstrap 初始化时幂等安装/升级本机 gate。Mode: AFK | Role: TDD Builder。Goal: 让每个经 bootstrap 初始化的项目都自动装好本机指纹闸（.git/local-gates/，不入库），解决'新项目压根没装'。Files 在 `<skill-root>`（禁止绝对路径进仓库）。TDD: 在 `tests/test_bootstrap_script.py` 写失败测试（RED：bootstrap 后 .git/local-gates/ 无 gate）→ 对点跑 → 在 gates.py 加 install_local_gate + cli.py 接线 + SKILL.md 说明（GREEN）→ 对点跑 + skill 全量确认基线不回退 → 变异自证（删 cli.py 安装调用 → RED；把 gate 复制进跟踪树 → test_is_not_installed_into_a_target_tree 须红）→ 校验幂等（跑两次 hash 不变、fingerprints.txt 保留）→ 物理回执。**无仓库 commit**。Return: exit code + stdout + 相对路径 diff。"

**Step Breakdown:**
- [ ] Step 1: 写失败测试（bootstrap 安装 / 幂等 / 不进跟踪树）RED
- [ ] Step 2: 对点跑 pytest 确认 RED
- [ ] Step 3: gates.py + cli.py + SKILL.md 实现（GREEN）
- [ ] Step 4: 对点跑 + skill 全量确认基线不回退（含 `test_is_not_installed_into_a_target_tree` 仍绿）
- [ ] Step 5: 变异自证（删安装调用 → 红；gate 误入跟踪树 → 红）
- [ ] Step 6: 幂等实测（两次 bootstrap hash 不变、fingerprints.txt 保留）+ 物理证据闸
- [ ] Step 7: 无仓库 commit；记录文件态变更

---

### Task B: 上游指纹闸禁列裸目录名实现契约 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]
*(对应复盘缺口 1；纯上游 skill 文件态，原计划 Task 2 保留但路径改写为占位)*

**Files (全部在 `<skill-root>`，不在仓库):**
- Modify: `tests/test_template_quality.py`（把 `test_guides_fingerprints_to_identity_bearing_paths_only` 补强为"删 SKILL.md 禁列行 → MUST 红"的变异自证）
- Modify: `templates/local-gates/fingerprint-gate.sh`（注释补"pattern 示例须含身份，不得列裸目录名"——保持无盘符字面量，现有 `test_carries_no_machine_identifier_of_its_own` 守卫不许削弱）

**Interfaces:**
- Consumes: `templates/local-gates/fingerprint-gate.sh`、`SKILL.md`（均在 `<skill-root>`，物理已核对）
- Produces: 上述测试对"删除 SKILL.md 中 `Do NOT list generic tool dir names` 行"敏感

**SSOT Effect:** —（无数字）

**Injected Instincts:**
- [ ] `[Instinct: No-Rationalization]`: 不得通过削弱 `test_carries_no_machine_identifier_of_its_own` 来修绿。
- [ ] `[Instinct: Dead-Test Guard]`: 新增断言必须能被"删禁列说明"变异打破；只加文案不加断言 = dead-green。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task B: 上游指纹闸禁列裸目录名实现契约。Mode: AFK | Role: TDD Builder。Files 在 `<skill-root>`，不得写进仓库。Goal: 把『pattern 只列含身份绝对路径』从注释升级为变异自证测试。TDD: 强化测试（RED）→ 对点跑 → 补注释（GREEN）→ 变异自证（删 SKILL.md 禁列行 → 红 → 恢复）→ 物理回执。无仓库 commit。"

**Step Breakdown:**
- [ ] Step 1: 强化测试（RED）
- [ ] Step 2: 对点跑 pytest 确认 RED
- [ ] Step 3: 补注释（GREEN）
- [ ] Step 4: 对点跑 + skill 全量确认基线不回退
- [ ] Step 5: 变异自证（删禁列行 → 红 → 恢复）
- [ ] Step 6: 物理证据闸
- [ ] Step 7: 无仓库 commit；记录文件态变更

---

### Task 1: 棘轮状态函数声明 + 协议裁决顺序（仓库侧） [Tier: 2-Standard] [Mode: HITL] [Role: TDD Builder + docs-writer]
*(对应复盘缺口 3；注意：`check_repo_hygiene.py` 是 project-owned copy，本任务只改仓库版，不改上游模板)*

**Files (仓库内):**
- Modify: `WORKMEMORY/PROTOCOL.md`（§1.3 追加裁决顺序；§5.1 追加"轮转后必跑 hygiene 双闸、计数漂移不得靠抬基线修"）
- Modify: `scripts/check_repo_hygiene.py`（`ratchet_guard` docstring 与 `--emit-baseline` 输出提示加"状态函数 / 禁止为容纳新增路径而重测"——项目自有 copy，不向上游回写）
- Test: `tests/test_ci_hardening_core.py`（新增测：docstring 含状态函数标注，删标注则红——变异自证）

**Interfaces:**
- Consumes: `data/repo_hygiene.json#ratchet["ABS_PATH|WORKMEMORY"] = 58`（物理核对过）
- Produces: PROTOCOL 新裁决条款（可直接引用）；`ratchet_guard.__doc__` 含状态函数标注

**SSOT Effect:** —（基线 58 保持，禁止抬到 59）

**Injected Instincts:**
- [ ] `[Instinct: No-Baseline-Raise]`: 不得为修绿抬 ratchet 桶上限；新增路径一律占位化。
- [ ] `[Instinct: Project-Owned-Copy]`: 改仓库版 gate 不触发上游同步；不改 marker、不向上游回写。
- [ ] `[Instinct: HITL-Protocol]`: 裁决顺序改动须过 Confirmation Gate。

**Confirmation Gate (HITL):** 执行前发出并等明确同意：
> "当历史事件含本机绝对路径：①占位化为 `<repo>`/`<user>`；②追加 NOTE 留痕（NOTE 自身不复述字面量）；③不改基线、不改事件结论。当轮转致棘轮计数漂移：④不抬基线，靠占位化压回；⑤轮转后必跑 `--all` 与 `--ratchet-guard`。"

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 棘轮状态函数声明 + 协议裁决顺序（仓库侧）。Mode: HITL（先过 Confirmation Gate）| Role: TDD Builder + docs-writer。Target: `WORKMEMORY/PROTOCOL.md` §1.3/§5.1、`scripts/check_repo_hygiene.py` docstring、`tests/test_ci_hardening_core.py`。**STOP at Confirmation Gate**。通过后：RED → 对点跑 → 改 docstring + 协议（GREEN）→ hygiene 双闸确认 58/58 → 变异自证（删 docstring 标注 → 红 → 恢复）→ 物理回执 → 原子 commit（独立分支）。"

**Step Breakdown:**
- [ ] Step 0: **HITL Confirmation Gate**
- [ ] Step 1: 写失败测试（RED）
- [ ] Step 2: 对点跑确认 RED
- [ ] Step 3: 改 docstring + PROTOCOL（GREEN）
- [ ] Step 4: 对点跑 + hygiene 双闸确认基线未动
- [ ] Step 5: 变异自证
- [ ] Step 6: 物理证据闸
- [ ] Step 7: 原子 commit

---

### Task 2: 推送认证 fallback 标准化（仓库文档） [Tier: 1-Light] [Mode: AFK] [Role: docs-writer]
*(对应复盘缺口 4)*

**Files:**
- Modify: `docs/agents/ops.md`（"本机环境"段新增"推送认证 fallback"：SSH passphrase 卡住时用 `gh auth token` 经 HTTPS one-shot push，不改 config、不落盘凭据、不含真实 token 字面量）

**Interfaces:**
- Consumes: `git remote -v` 输出形态（公开 URL，非本机绝对路径）
- Produces: ops.md 小节（可复制命令序列，token 仅以变量形式出现）

**SSOT Effect:** —（无数字）

**Injected Instincts:**
- [ ] `[Instinct: No-Credential-Leak]`: 文档不含真实 token、不含本机绝对路径。
- [ ] `[Instinct: No-Config-Mutation]`: 明确"一次性 URL 推送，不改 remote / 不改 git config"。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: 推送认证 fallback 标准化。Mode: AFK | Role: docs-writer。Tier 1 用 grep 物理验证：新增小节含 `gh auth token`、无裸 token、无本机绝对路径字面量、含"不改 config"；跑 `tools/check_release_docs.py` exit 0 + docs 布局闸对点。Return 回执。"

**Step Breakdown:**
- [ ] Step 1: 写 ops.md 小节
- [ ] Step 2: grep 物理验证（命令形态 + 无裸 token + 无路径字面量）
- [ ] Step 3: 发布文档闸 + docs 布局对点
- [ ] Step 4: 物理证据闸
- [ ] Step 5: 原子 commit

---

### Task 3: 合并前净 diff 防回退机械闸 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]
*(对应复盘缺口 5)*

**Files:**
- Create: `scripts/check_pr_no_regression.py`
- Modify: `.github/workflows/ci.yml`（PR 事件新增一步，调用上述脚本；接线由测试钉死）
- Test: `tests/test_ci_hardening_workflow_wiring.py`（新文件；删 CI 步或脚本调用测试 MUST 红——三证纪律）

**Interfaces:**
- Consumes: `git diff --name-status <base>..<head>`（subprocess，encoding='utf-8'）
- Produces: `def find_deleted_paths(base: str, head: str, root: Path) -> list[str]`；CLI `python scripts/check_pr_no_regression.py --base <ref> --head <ref>`（exit 1 + 打印完整删除路径列表）

**SSOT Effect:** —（路径列表判定，无数字）

**Injected Instincts:**
- [ ] `[Instinct: Automation-Three-Proofs]`: 接线 + 执行 + 验证三证齐全，缺任一 = dead-green。
- [ ] `[Instinct: Evidence-No-Truncation]`: 输出完整删除路径，不用 head/tail 截断。
- [ ] `[Instinct: Minimal-Gate]`: 只拦"删除 base 已跟踪文件"的明确回退信号，不做语义推测。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: 合并前净 diff 防回退机械闸。Mode: AFK | Role: TDD Builder。Target: Create `scripts/check_pr_no_regression.py`, Modify `.github/workflows/ci.yml`, Test `tests/test_ci_hardening_workflow_wiring.py`。TDD: 失败测试（RED）→ 对点跑 → 脚本 + CI 接线（GREEN）→ 对点跑全绿 + workflow 语法自检 → 变异自证（删 CI 步 → wiring 红；造删除分支 → 脚本 exit 1 并打印路径）→ 物理回执 → 原子 commit。含 CI 定义，禁直推。"

**Step Breakdown:**
- [ ] Step 1: 写失败测试（RED）
- [ ] Step 2: 对点跑确认 RED
- [ ] Step 3: 实现脚本 + CI 接线（GREEN）
- [ ] Step 4: 对点跑 + workflow 语法自检
- [ ] Step 5: 变异自证（删 CI 步 → 红；造删除分支 → exit 1）
- [ ] Step 6: 物理证据闸
- [ ] Step 7: 原子 commit

---

## [NOTE] Fog of War (Not Yet Specified)

- **[Fog 1] skill 真身迁址**: Task A 的上游路径由 `<skill-root>` 占位、运行期推导；历史上 skill 根位置迁移过一次。触发条件：bootstrap 安装时报模板 MISSING 且确认为迁址而非误删，才开专项设计根定位。
- **[Fog 2] 依赖分支自动 rebase**: Task 3 只拦"删除文件"型回退，不解析 PR 依赖。触发条件：再出现"PR base 选错"且 Task 3 未拦住，才开专项。
- **[Fog 3] gh 写操作稳定性**: Task 2 只标准化 fallback，不修根因。触发条件：fallback 连续两次也失败，才开凭据管理专项。

---

## [NOTE] Out of Scope

- 不把 `scripts/check_repo_hygiene.py` 与上游模板强制同步——它是 project-owned copy（无 marker、diff 1126 行），同步会丢项目定制。
- 不在仓库建 `check_local_gate_drift.sh`、不写 AGENTS.md 检查段——本机 gate 的安装归 dfs-bootstrap 初始化（Task A），不进每次会话必读的入口文档。
- 不重做 ratchet 算法、不改 PROTOCOL §1.3 本体原则（Task 1 只加冲突裁决顺序）。
- 不生成软著申报 Word/DOCX、不更新 README 徽章数字、不写私有库/本机路径到公开仓。
- 不跑 DeLector 全量 pytest（2026-11-13 裁决）。

---

## [NOTE] Deferred Gap Register

| gap | why deferred | trigger that forces revisiting | owner |
|---|---|---|---|
| skill 真身迁址后 bootstrap 模板定位失效 | 历史迁址过一次，当前路径稳定 | Task A bootstrap 报模板 MISSING 且确认为迁址 | skill 维护者（开 Fog 1 专项） |
| PR 依赖只靠人脑，Task 3 只拦删除型回退 | graphql 本机偶发 EOF，自动依赖解析需另立方案 | 再次"PR base 选错"且 Task 3 未拦住 | TDD Builder（开 Fog 2 专项） |
| SSH passphrase / gh graphql 写不稳 | 本机环境，非仓库可完全修复 | fallback 连续两次失败 | ops 维护者（开 Fog 3 专项） |
| work.log 预算靠人工轮转 | 守恒对账复杂，自动化易错 | 单次执行追加 >3 条事件致 BUDGET 红 | docs-writer |

---

## [NOTE] Deviation Table (post-execution, filled before merge)

| plan text | what was actually built | why |
|---|---|---|
| `check_repo_hygiene.py` 是 project-owned copy（无 marker、diff 1126 行），Task 1 只改仓库版不回写上游 | 仓库版头部**实有** `# dfs-bootstrap-gate-version: 4`，与上游模板同版本 marker（sha256 不同、内容 diff 大）；Task 1 严守"不加/不删/不同步 marker"，docstring 改动落在带 marker 的仓库版 | 计划阶段读 diff 时把上游模板的删除行 `-# dfs-bootstrap-gate-version: 4` 误读成"仓库版无 marker"；不影响 Task 1 产出，但"project-owned copy"的定性应为"带 marker 的同版本重定制副本" |
| Task A 最初写"扩展上游 doctor 覆盖漂移检测"，后改"pre-push 自检"，最终为"bootstrap 初始化安装" | bootstrap 初始化时幂等安装本机 gate 到 `.git/local-gates/`（不入库），触发点=项目初始化；不进 AGENTS.md、不靠 doctor/CI | 三次实测修正：doctor 在 DeLector 零接线（没人跑）；pre-push 只覆盖已装项目；新项目"压根没装"只能由 bootstrap 解决。AGENTS.md 每次读=噪声 |
| Task A 原要求"删模板自检测试红"，实施时因既有 `test_is_not_installed_into_a_target_tree` 禁止 `.py` 出现 `local-gates` 字面量 | 该测试改为语义检查 `_local_gate_tracked_tree_copies`（只拦装进跟踪树，放行 `.git/` 私有态），并加变异测试证明装进跟踪树仍红 | 旧的字符串禁令会与新 install 逻辑冲突；改成语义判据既保留原意（不进跟踪树）又不 vacuous |
