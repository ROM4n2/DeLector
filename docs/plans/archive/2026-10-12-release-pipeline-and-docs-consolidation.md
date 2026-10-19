# 发布链路护栏 + 文档口径收口 Implementation Plan

> **Goal**: 把 `/dfs-team` 三席评估（2026-10-12）出的 7 条发现收敛为可执行任务：补齐发布链路的超时/测试护栏，收口文档里的重复副本与口径错，并让"真实用户反馈"这个开闸门槛从不可启动变为可启动。
> **Tech Stack**: GitHub Actions YAML / Python 3.11（`package_windows.py`）/ pytest 守卫（`tests/test_ci_hardening.py`）/ Markdown 文档治理。
> **Spec Reference**: `/dfs-team` 评估报告（seats: code-reviewer / sre-resilience / product-ux + skeptic 复核）；`WORKMEMORY/work.log:596` 的 2026-10-12 DECISION（宣传延后 + 四条开闸门槛）；Vault `08-Projects/DeLector/POST-MORTEM-V5.4.0-GITHUB-ACTIONS-TRIPLE-TRAP.md`（dispatch/移 tag 的历史实证）。
> **Global Constraints**:
> - **零新依赖**：只用现有工具链（gh CLI / pytest / yaml）。
> - **门禁不许削弱**：`ruff check .` / `mypy --strict delector tools` / `mypy --follow-imports=skip tests` / `mypy --platform win32 --strict --follow-imports=skip desktop.py package_windows.py conftest.py start.py` / `pytest -q` 全绿；`test_ci_hardening.py` 的既有断言**只扩不缩**（超时上界、打包面清单、闸顺序）。
> - **版本面零改动**：本计划不触碰 `delector/core/version.py` / `static/sw.js` / `static/index.html` / `android/app/build.gradle` / README 的 badge 与下载表版本单元格（由 `tests/test_writer_mobile.py` 守卫，误动即红）。
> - **每任务物理证据**：原始命令 + 退出码 + 计数 + `git diff --stat`；Tier 1 也不例外。
> - **文档治理**：任何"第二份副本"一律改成指针（`FEATURES.md:7` 自陈 + `docs/agents/ops.md` DOC-GOVERNANCE）。
> - **work.log 只追加**：不回改历史事件（超长事件的外置不在本计划范围，见 🚫 Out of Scope）。

---

## 🏛️ Decisions So Far

- **孤儿 tag `v5.1.1` 的处置 = 删 tag + 记账，不补发**：该 tag 从未产生 Release（`gh release view v5.1.1` → not found），版本已过期一个月；**补发一个过期版本的 Release 会让用户看到陈旧产物**。删 tag 后把事故模式记入 work.log。真正要修的是"再生产它"的结构（Task 1/2），不是补发这一个。（若你反对，改为补发：见人工前置动作 B。）
- **补发路径存在文档冲突，按"两路候选 + 清单判据"处理**：Vault v5.4.0 复盘实证「dispatch 到**分支** ⇒ publish 被静默跳过」，其修法是**移 tag**；怀疑者据 `gh workflow run --help`（`--ref` 接受 branch **or tag**）推断 dispatch 到 **tag** 可满足 `if: startsWith(github.ref,'refs/tags/v')`。后者在本仓**从未实证** ⇒ 按复盘铁律「**是否已发布的唯一判据是 release 清单/资产列表，永远不是 run 状态**」，执行后必须 `gh release list && gh release view <tag> --json assets` 复核；不成立则回落移 tag 路径（`git tag -f` + force-push，需用户批准）。
- **Smoke 闸选"加 pytest"而非"删安装"**：`ci.yml:240` 已装 pytest 却从不调用（死安装）⇒ 在 Build **之前**插入 `pytest -q`（测试红就别再花 10 分钟构建）；`timeout-minutes: 30` 现值容得下（构建约 10min + 全量测试约 7.5min + 验包）。覆盖面诚实边界见 Fog of War。
- **Tier 判定**：Task 1/2 改 CI 定义与闸守卫 ⇒ **Tier 2**（按 dfs-exec 硬升级触发器："core test-gate or CI definition files ⇒ MUST escalate"）；Task 3–6 纯文档/元数据 ⇒ **Tier 1-Light**，合并为一个 Batch 原子提交。

---

## 🧑‍🔧 人工前置动作（非代码任务，[Mode: HITL]）

- **A1（需批准，破坏性）**：`git push origin :refs/tags/v5.1.1` 删除孤儿 tag，并在 `WORKMEMORY/work.log` 追加 NOTE 记账（事故模式：红平台 ⇒ Publish 跳过 ⇒ 孤儿 tag 无人恢复；v5.17.0 首次 tag 已复现一次，由重打 tag 恢复）。
- **A2（仅当你反对"删"时）**：补发 v5.1.1 —— 按 Decisions 的两路候选执行，并以 release 资产清单复核。
- **A3（计划批准）**：本计划 Task 1/2 为 Tier 2（Maker-Checker），Batch 1 为 Tier 1（Solo Fast-Path）；是否初始化 `.vault-exec-ledger.json` 台账由你定（本仓近期实践用 worktree + 手工台账，非必需）。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: 发布链路超时护栏（build-release 五 job + PyInstaller 子进程）[Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]
*(Tier: 2 = Full TDD Red-Green-Refactor + 独立 Reviewer 子代理 Maker-Checker)*

**Files:**
- Modify: `.github/workflows/build-release.yml`（5 个 job 头：`:13 build-windows` / `:74 build-linux` / `:168 build-macos` / `:262 build-android` / `:510 publish-github-release`）
- Modify: `package_windows.py:386-392`（PyInstaller `subprocess.run`）
- Test: `tests/test_ci_hardening.py`（复用 `:879 _job_block(workflow, job_name)` 与 `:863 BUILD_RELEASE_WORKFLOW`，扩展现有 `:556 test_ci_job_has_bounded_timeout` 家族）

**Interfaces:**
- Consumes: `subprocess.run(pyinstaller_cmd, cwd=root_dir)`（现有，无 timeout）
- Produces:
  - `build-release.yml` 中每个 job 的 `timeout-minutes` 键（建议值：windows 30 / linux 20 / macos 20 / android 30 / publish 10）
  - `package_windows.py` 内 PyInstaller 调用带 `timeout=1800`，捕获 `subprocess.TimeoutExpired` 后打印可操作错误并 `sys.exit(1)`（**绝不**静默继续）

**Injected Instincts:**
- [ ] `[Instinct: No-Silent-Failure]`：超时/异常一律非零退出 + 人话错误，禁止退化为"看起来成功"。
- [ ] `[Instinct: 闸只扩不缩]`：既有 `test_ci_hardening.py` 断言（上界、打包面清单、顺序）不得放松；新断言只加不减。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 发布链路超时护栏。Mode: AFK | Role: TDD Builder
> Steps: ① 在 `tests/test_ci_hardening.py` 写失败测试——遍历 `build-release.yml` 的 5 个 job，断言每个都有 `timeout-minutes` 且值 ≤ 各自上界（复用 `_job_block`）；再写一条：monkeypatch `subprocess.run` 抛 `TimeoutExpired`，断言 `package_windows` 的打包路径 `SystemExit(1)`。② 运行 `python -m pytest tests/test_ci_hardening.py -q` 确认 RED。③ 给 5 个 job 加 `timeout-minutes`、给 `package_windows.py:389` 加 `timeout=1800` + `TimeoutExpired` 处理（GREEN）。④ 跑 `python -m pytest tests/test_ci_hardening.py tests/test_writer_mobile.py -q` 与 `yaml.safe_load` 校验。⑤ 回报物理收据（退出码 + 计数 + diff stat）。"

**Step Breakdown:**
- [ ] Step 1: 写失败测试（RED：5 job 无 timeout / subprocess 无超时处理）
- [ ] Step 2: 运行并确认 RED 的期望报错
- [ ] Step 3: 加 `timeout-minutes` + `timeout=1800`/`TimeoutExpired`（GREEN）
- [ ] Step 4: 全量相关测试绿 + `python -c "import yaml;yaml.safe_load(open('.github/workflows/build-release.yml'))"`
- [ ] Step 5: 独立 Reviewer 子代理按 RFC 2119 复核 diff（Maker-Checker）
- [ ] Step 6: 物理证据（命令 + 退出码 + `git diff --stat`）
- [ ] Step 7: 原子提交 `ci(release): 发布链路补超时护栏（五 job + PyInstaller 子进程）`

---

### Task 2: Windows Smoke 闸自洽——Build 之前先跑 pytest [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `.github/workflows/ci.yml:236-243`（smoke job 的 Install 步之后、`Build Windows Portable` 之前插入 `Run pytest suite`）
- Test: `tests/test_ci_hardening.py`（新增/扩展：smoke job 必须含 pytest 步且顺序早于 Build；与既有"验包早于压缩"顺序守卫同族）

**Interfaces:**
- Consumes: smoke job 既有依赖安装步（`:236-242`，已含 `pip install pyinstaller pytest`）
- Produces:
  - smoke job 新增步 `- name: Run pytest suite` + `run: pytest -q`，位置**早于** `Build Windows Portable`
  - 守卫断言：smoke job 文本中 `pytest` 出现位置索引 < `Build Windows Portable` 索引

**Injected Instincts:**
- [ ] `[Instinct: 闸的覆盖面要写清]`：本闸从此覆盖"Windows 上的全量测试"，macOS/Linux 专属失败仍未提前覆盖（记入 Fog of War，不得假称已覆盖）。
- [ ] `[Instinct: fail-fast 省时]`：测试先于构建，红就别构建。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: Smoke 闸加 pytest。Mode: AFK | Role: TDD Builder
> Steps: ① 在 `tests/test_ci_hardening.py` 写失败测试：截取 `windows-portable-smoke` job 块，断言其中 `pytest` 首次出现的位置早于 `Build Windows Portable`。② 确认 RED。③ 在 `ci.yml` smoke job 的 Install 步后插入 `Run pytest suite`（`pytest -q`）。④ 确认 GREEN + `yaml.safe_load` 通过。⑤ 回报物理收据。"

**Step Breakdown:**
- [ ] Step 1: 写失败测试（RED：smoke job 无 pytest 步）
- [ ] Step 2: 确认 RED
- [ ] Step 3: 插入 pytest 步（GREEN）
- [ ] Step 4: 相关测试绿 + YAML 合法
- [ ] Step 5: 独立 Reviewer 复核（Maker-Checker）
- [ ] Step 6: 物理证据
- [ ] Step 7: 原子提交 `ci(smoke): Windows 冒烟闸在构建前先跑全量 pytest`

---

### Batch 1 [Tier: 1-Light]: Tasks 3-6（纯文档/元数据，Solo Fast-Path，一次原子提交）[Mode: AFK]
*(Tier: 1 = 单 agent 内联执行 + 物理收据，不派 Reviewer；本批四项互不依赖，合并为一次 `docs(...)` 提交)*

#### Task 3: FEATURES.md 去掉第二份「快速开始」并修正 Python 版本口径 [Tier: 1-Light]

**Files:** Modify `FEATURES.md`（`:292-313` 快速开始整节；`:296` 版本行）
**Produces（可伪证）:**
- `grep -c "快速开始" FEATURES.md` == 0，原位置为一行指针：`> 安装与启动见 [README.md](README.md)（唯一入口，避免两份漂移）。`
- `grep -n "3\.10+" FEATURES.md` == 0；`:296` 改为 `Python 3.11`（与 `Dockerfile:1` / `pyproject.toml:20` / CI 的 `3.11` 一致）
**Physical Receipt:** `grep -c` 两个计数 + `grep -n "Python 3.11" FEATURES.md`。

#### Task 4: 冷启动数字补口径标签 + 已知限制补 Android 两条 [Tier: 1-Light]

**Files:** Modify `README.md:158`、`FEATURES.md:244`
**Produces:**
- `README.md:158` 与 `FEATURES.md:244` 的冷启动数字必须同时带**两个标签**：路径（源码 `python desktop.py` vs 便携产物）与冷/暖；并写入便携产物实测 **冷 8.5s / 暖 6.9s**（源：`WORKMEMORY/work.log:542`）
- 两处已知限制各补：**Android 端更新提示能力未验证**（`PROJECT_OVERVIEW.md:56-57`，两条假设从未验证）与 **Android `versionCode` 只升不降**（`51700`）
**Physical Receipt:** `grep -n "8.5\|6.9\|versionCode\|未验证" README.md FEATURES.md` 命中行。

#### Task 5: 零门槛用户反馈入口（让开闸门槛①可启动）[Tier: 1-Light]

**Files:** Create `.github/ISSUE_TEMPLATE/feedback.md`；Modify `README.md`（下载表之后加直达链接；文档导航表加一行）
**Produces:**
- 新模板字段：标题自由（**不强制** `bug(scope):` 前缀）、`形态` 下拉（Windows 便携包 / macOS / Linux / Android）、三个必答判断题（分级是否合适 / 已背词高亮与一键进卡是否顺手 / 本地词典释义够不够用）、一个可选「想吐槽什么」
- `README.md` 下载表之后出现一句可直接点到反馈模板的引导（`<下载表位置 +4 行内`）
**Physical Receipt:** `ls .github/ISSUE_TEMPLATE/` 三文件 + `grep -n "feedback\|反馈" README.md | head`。

#### Task 6: 工作区文档整齐（归档已发版计划 + 收敛 PROJECT_OVERVIEW）[Tier: 1-Light]

**Files:** `git mv docs/plans/2026-10-10-windows-desktop-shell.md docs/plans/2026-10-08-android-update-check.md docs/plans/archive/`；Modify `WORKMEMORY/PROJECT_OVERVIEW.md:51-67`
**Produces:**
- 上述两份计划不在 `docs/plans/`（已入 `archive/`），与 `docs/README.md:20`「成果已发版」判据一致
- `PROJECT_OVERVIEW.md` 开放待办 ≤5 条活项；已接受/已推翻项（ADR-0018/0019/0020/0021、冷启动 2.0s 口径）整体下沉到 `WORKMEMORY/cold/`；首条活项写入 2026-10-12 的四条开闸门槛，并显式标注「反馈入口未立项 ⇒ 门槛①当前不可达（Task 5 落地后解除）」
**Physical Receipt:** `ls docs/plans/*.md | wc -l`（减少 2）+ `grep -c "^- " ` 开放待办段 ≤5 + `grep -n "开闸门槛\|落地页" WORKMEMORY/PROJECT_OVERVIEW.md`。

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Unknown 1]**: macOS / Linux 专属测试失败**仍需打 tag 后才暴露**（Task 2 只把覆盖面从"零"提到"Windows 全量"）。若要提前抓，需新增一个 `workflow_dispatch` 的跨平台预检 job（ubuntu + macos 跑 `pytest -q`）——成本与必要性待 Task 2 落地后评估，**不在本计划**。
- **[Unknown 2]**: 「≥5 份真实三问反馈」能否达到，取决于 Task 5 上线后的真实流量，**不可预规划**；若 4 周内 0 份，应先改入口位置/口径而非降低门槛。
- **[Unknown 3]**: 反馈数据的结构化统计（Issue 表单够不够 / 是否要应用内上报）——Task 5 只解决"可达"，统计口径待有真实反馈后再定。

## 🚫 Out of Scope

- **work.log 历史事件外置**（7 条 >4KB）：协议 §1.3 append-only，不回改历史；处置改为"未来事件 ≤4KB"，不进本计划。
- Android 端更新 chip 的真机验证、预置包 LLM gloss 富化（阻塞于 `DEEPSEEK_API_KEY`）——在册待办，另行立项。
- 站点仓库初始化 / README 首屏改造 / 小红书选题——属 2026-10-12 DECISION 的宣传线，本计划只做"让门槛①可启动"（Task 5）。
- `v5.1.1` 之外的历史孤儿 tag 清理（当前仅此一个）。
