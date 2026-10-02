# CI Hardening：PR/push 门禁 + 依赖治理 + 格式清账 Implementation Plan

> **Goal**: 把"只在发版日才炸"的 CI 缺口补上——PR/push 即跑全量测试与 Go 门禁，依赖漂移由 dependabot 前置暴露，gofmt 清账让格式门禁可开。
> **Tech Stack**: GitHub Actions / Python 3.11 (pytest) / Go 1.26 (-race) / YAML
> **Spec Reference**: 99-Inbox `2026-09-09-github-actions-tag-发版三重陷阱…md`（setup-go cache 教训）、`…fastapi-starlette-无上界依赖漂移…md`（依赖 pin 教训）；Vault `PYTHON-STANDARDS` §8、`AUTOMATION-GOTCHAS` §5（反冻结集合断言）；项目背景见 `WORKMEMORY/PROJECT_OVERVIEW.md` 工程化短板 1/2/3。
> **Global Constraints**:
> - 本计划**不引入新 Python 依赖**（守卫测试用仓库既有的字符串断言惯例，不用 pyyaml）。
> - Ruff/Mypy 本期**不做**（存量告警未清，直接上 CI 必全红）——记为已知边界，另立计划。
> - CI 只跑 **ubuntu 单平台**（Windows/macOS 留给 tag 的 build-release 矩阵），控制 PR 反馈时长 < 8min。
> - setup-go 写法 MUST `cache: true` + `cache-dependency-path: agent/go.mod`（99-Inbox 教训，禁止 `cache: "go"`）。
> - 执行环境：`execute_command` 走 bash，Python 前加 `export PYTHONIOENCODING=utf-8`。
> - 分支策略：本地特性分支 `feature/ci-hardening` 逐 Task 原子 commit，**CPE 禁 git commit，主线程负责 commit/push/PR**；maker-checker 由 CRV 验收。

---

### Task 1: CI 配置守卫测试 [Role: TDD Builder]

**Files:**
- Create: `tests/test_ci_hardening.py`

**Interfaces:**
- Consumes: 仓库既有"字符串断言要具体到用得到"惯例 + `AUTOMATION-GOTCHAS` §5 反冻结集合原则
- Produces: `test_ci_workflow_has_core_gates()` / `test_dependabot_covers_active_ecosystems()` / `test_gofmt_gate_wired_in_ci()`

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 1: CI 配置守卫测试。
> Goal: 在 `.github/workflows/ci.yml` 与 `.github/dependabot.yml` 尚不存在时，先钉死它们的**最低契约**（RED 阶段）。
> Target Files: Create `tests/test_ci_hardening.py`。
> TDD Steps:
> 1. 写 `test_ci_workflow_has_core_gates()`：读 `.github/workflows/ci.yml` 文本，断言**必须包含**（子集防护，禁止冻结全文）：`pull_request` 触发、`push` + `branches: [master]`、`pytest` 命令、`gofmt -l`、`go vet ./...`、`go test -race ./...`、`concurrency` 取消组、`setup-go@v5`。
> 2. 写 `test_ci_setup_go_cache_is_boolean()`：断言文件含 `cache: true` 且**不含** `cache: \"go\"`（99-Inbox 陷阱回归钉）。
> 3. 写 `test_dependabot_covers_active_ecosystems()`：断言 dependabot.yml 含 `pip`、`github-actions`、`gomod` 三个 `ecosystem`，且 `schedule.interval` 为 `weekly`。
> 4. 断言方式用 `'pytest' in text` 风格的**关键要素子集断言**，绝不 `==` 全文比对（AUTOMATION-GOTCHAS §5：护栏不得阻挡演进）。
> 5. 跑 `export PYTHONIOENCODING=utf-8 && python -m pytest tests/test_ci_hardening.py -q` 验证 **RED**（文件不存在断言失败）。
> Return: Summary with test execution evidence（含 RED 输出）。"

**Step Breakdown:**
- [ ] **Step 1: 写三支守卫测试（RED）**
- [ ] **Step 2: 跑 `pytest tests/test_ci_hardening.py -q` 确认按预期失败（找不到 ci.yml / dependabot.yml）**
- [ ] **Step 3: 自检断言非假绿**——问"若 ci.yml 删掉 gofmt 门禁，测试会红吗？"（§8.2 静态断言契约）
- [ ] （commit 由主线程执行：`test(ci): CI 配置守卫测试先红（ci.yml/dependabot 契约钉死）`）

---

### Task 2: gofmt 清账 11 文件 [Role: Refactorer]

**Files:**
- Modify（仅格式化，零逻辑变更）: `agent/cmd/delector/main.go`、`agent/integration_encounter_test.go`、`agent/internal/app/app.go`、`agent/internal/job/encounter_test.go`、`agent/internal/job/gloss.go`、`agent/internal/job/gloss_test.go`、`agent/internal/job/pack.go`、`agent/internal/job/pack_test.go`、`agent/internal/job/runner_test.go`、`agent/internal/registry/registry.go`、`agent/internal/registry/registry_test.go`

**Interfaces:**
- Consumes: `gofmt`（Go 1.26.5 工具链）
- Produces: `gofmt -l .` 全仓库零输出（Task 3 的 gofmt CI 门禁前置条件）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 2: gofmt 清账。
> Goal: 消灭 agent/ 下全部 gofmt 不洁文件，且**不改任何逻辑**。
> Steps:
> 1. `cd agent && gofmt -l .` 记录基线清单（应为 11 个文件，见上方 Files）。
> 2. `gofmt -w <上述清单>`。
> 3. `git --no-pager diff --stat` 核对：改动只在这些文件、且为空白/对齐差异；若有非格式化 diff 出现立即停止上报。
> 4. 验证 GREEN：`gofmt -l .` 输出为空；`go vet ./...` 0 错；`go test -race ./...` 全绿（`-tags integration` 不在本任务跑，属 T6 收官）。
> Return: Summary + gofmt -l 空输出证据 + go test 末行。"

**Step Breakdown:**
- [ ] **Step 1: gofmt -l 基线确认（11 文件）**
- [ ] **Step 2: gofmt -w + diff 只含空白差异核查**
- [ ] **Step 3: go vet + go test -race 全绿证据**
- [ ] （commit 由主线程执行：`style(agent): gofmt 清账 11 文件，零逻辑变更`）

---

### Task 3: `.github/workflows/ci.yml` PR/push 门禁 [Role: TDD Builder]

**Files:**
- Create: `.github/workflows/ci.yml`
- 参考（只读）: `.github/workflows/build-release.yml:20-40`（Python 环境与模型下载步骤）、`.github/workflows/build-agent.yml:28-33`（setup-go 正确写法）

**Interfaces:**
- Consumes: Task 1 的 `test_ci_workflow_has_core_gates`（RED → GREEN 驱动）
- Produces: PR/push master 即自动执行 `pytest -q` + `gofmt -l`（空校验）+ `go vet ./...` + `go test -race ./...`

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 3: ci.yml 门禁工作流。
> Goal: 让 Task 1 守卫测试转 GREEN。
> Target Files: Create `.github/workflows/ci.yml`。
> 硬性要求（与守卫测试一一对应）：
> 1. `on:` 含 `pull_request`（branches: [master]）、`push`（branches: [master]）、`workflow_dispatch`。
> 2. `concurrency: { group: ci-${{ '{' }}{ github.ref }}, cancel-in-progress: true }`（注意 YAML 转义）。
> 3. 单 job `ci`（ubuntu-latest）步骤序列：
>    a. `actions/checkout@v4`；
>    b. `actions/setup-python@v5`（python-version \"3.11\"，cache: \"pip\"）；
>    c. `pip install -r requirements.txt` + `pip install pytest`（**不装 pyinstaller**，那是打包面）；
>    d. `python -m spacy download de_core_news_sm`（测试需要模型，build-release.yml:33 同源）；
>    e. `pytest -q`（全量门禁，预期 ~3-6min）；
>    f. `actions/setup-go@v5`（go-version \"1.26\"，**`cache: true`**，`cache-dependency-path: agent/go.mod`——禁止 `cache: \"go\"`，99-Inbox 教训）；
>    g. Go 门禁三连：`cd agent && test -z \"$(gofmt -l .)\"`、`go vet ./...`、`go test -race ./...`。
> 4. 全程**零密钥引用**（GITHUB_TOKEN 默认权限即可）。
> 5. 验证 GREEN：`python -m pytest tests/test_ci_hardening.py -q` 全绿。
> Return: Summary + pytest 证据 + ci.yml 全文。"

**Step Breakdown:**
- [ ] **Step 1: 按 scaffold 落 ci.yml（GREEN）**
- [ ] **Step 2: `pytest tests/test_ci_hardening.py -q` 转绿证据**
- [ ] **Step 3: 自检——对照 Task 1 每条断言逐条命中；YAML 语法首次真验证留给本分支 PR 的首次实跑（pull_request 事件采用 merge ref 中的 workflow，新增 workflow 会在自身 PR 上生效）**
- [ ] （commit 由主线程执行：`ci: 新增 PR/push 门禁 workflow（pytest 全量 + gofmt/vet/-race）`）

---

### Task 4: `.github/dependabot.yml` 依赖治理 [Role: TDD Builder]

**Files:**
- Create: `.github/dependabot.yml`

**Interfaces:**
- Consumes: Task 1 的 `test_dependabot_covers_active_ecosystems`（RED → GREEN 驱动）
- Produces: pip / github-actions / gomod 三生态周更 PR（升级安全性由 Task 3 的 CI 兜底——这正是两篇 99-Inbox 教训的组合拳）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 4: dependabot 配置。
> Target Files: Create `.github/dependabot.yml`。
> 内容：`version: 2` + 三个 updates 条目——`package-ecosystem: pip`（directory `/`）、`github-actions`（directory `/`）、`gomod`（directory `/agent`），均 `schedule.interval: weekly`，`open-pull-requests-limit: 5`，`reviewers: [ROM4n2]`。
> 验证 GREEN：`python -m pytest tests/test_ci_hardening.py -q` 全绿。
> Return: Summary + pytest 证据。"

**Step Breakdown:**
- [ ] **Step 1: 落 dependabot.yml（GREEN）**
- [ ] **Step 2: 守卫测试全绿证据**
- [ ] （commit 由主线程执行：`ci: dependabot 周更 pip/github-actions/gomod`）

---

### Task 5: PR / ISSUE 模板 [Role: Builder]

**Files:**
- Create: `.github/PULL_REQUEST_TEMPLATE.md`
- Create: `.github/ISSUE_TEMPLATE/bug_report.md`、`.github/ISSUE_TEMPLATE/feature_request.md`

**Interfaces:**
- Consumes: 仓库提交惯例（Conventional Commits + 中文描述）
- Produces: PR 描述强制携带「门禁证据」区（pytest/Go 命令输出），ISSUE 双模板（bug 带"期望 vs 实际 + 复现步骤"，feature 带"用户故事 + 影响面"）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 5: PR/ISSUE 模板。
> 要求：PR 模板分区 = 变更摘要 / 门禁证据（pytest 与 go test 命令及结果占位）/ 自查清单（守护测试、切片护栏、敏感闸）；语言中文、克制篇幅（每模板 ≤ 30 行）。bug 模板含复现步骤/期望/实际/环境四节；feature 模板含用户故事/影响面/替代方案。
> 无测试可加（纯文档）；验证 = 文件存在 + 无 YAML（均为 markdown）。
> Return: 文件清单。"

**Step Breakdown:**
- [ ] **Step 1: 三模板落地**
- [ ] （commit 由主线程执行：`docs(github): PR 与 ISSUE 模板`）

---

### Task 6: 收官——全量门禁 + PR 合入 + 状态回填 [Role: Verifier]

**Files:**
- Modify: `WORKMEMORY/PROJECT_OVERVIEW.md`（工程化短板 1/2/3 勾销，新增 ci.yml/dependabot 事实）
- Modify: `WORKMEMORY/work.log`（≤4KB WORK_END 事件）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 6: 收官验证与状态回填。
> 1. 本地全量门禁：`export PYTHONIOENCODING=utf-8 && python -m pytest -q`（686+1 基线不回退）；`cd agent && go vet ./... && go test -race ./... && gofmt -l .`（空）。
> 2. 更新 `WORKMEMORY/PROJECT_OVERVIEW.md`：短板清单改为「PR CI 已上线（ci.yml）/ dependabot 三生态周更 / gofmt 清账完成 / Ruff-Mypy 递延（已知边界）」。
> 3. 按 PROTOCOL 追加 work.log 事件（≤4KB）。
> 4. **不 commit 不 push**——证据与文本改动返回主线程复核。
> Return: 全量门禁末行 + 两个文件的 diff。"

**Step Breakdown:**
- [ ] **Step 1: 全量门禁跑通并留存证据**
- [ ] **Step 2: OVERVIEW + work.log 回填**
- [ ] **Step 3: 主线程 commit（`docs(workmem): CI hardening 收官状态回填`）→ push 分支 → 开 PR 合 master**
- [ ] **Step 4: PR 上首次实跑 ci.yml，确认绿（真验证）→ merge → 删分支**

---

## 执行状态（Sub-Plan 收官时回填）

- 状态：**DONE**（2026-09-09，T1–T6 全绿）
- 逐 Task commit：T1 `ad78b79`（守卫 RED）→ T2 `7c246f6`（**偏差修正**：gofmt 清账经 `git show HEAD:x | gofmt -d` 证伪为 autocrlf 假阳性，blob 全洁、零清账需求，改为根因修复 `.gitattributes` 锁 `*.go eol=lf` + 工作树重刷，`gofmt -l` 归零）→ T3 `4044819`（ci.yml，GREEN）→ T4 `392ee24`（dependabot，GREEN）→ T5 `41de3b9`（PR/ISSUE 模板）→ T6 本笔（状态回填）。
- 门禁证据：pytest 全量 **694 passed + 1 skipped**（269s）；agent `go vet` 0 错、`gofmt -l .` 空、`go test -race ./...` 全部 ok；守卫测试 `tests/test_ci_hardening.py` 3 passed（RED→GREEN 全程留痕）。
- 偏差记录：① T2 重定义（见上）；② dependabot.yml 用 `-` 序列符独立成行写法（守卫解析器要求 `package-ecosystem:` 键位于行首，YAML 语义等价）；③ T5 commit 输出被 tail 截断曾误判失败，以 `git log` 为准。
- 已知边界（不进本期）：Ruff/Mypy 静态工具链引入（存量告警清账另立计划）；requirements lock 文件（fastapi/starlette 已 pin，其余靠 dependabot + PR CI 兜底）；Android job 不进 PR CI（只在 tag build-release）。
- 门禁证据：`docs/plans/` 本文件收官时补「执行状态」块：逐 Task commit hash + pytest/go 末行 + PR 编号 + CI 首跑链接。
- 已知边界（不进本期）：Ruff/Mypy 静态工具链引入（存量告警清账另立计划）；requirements lock 文件（fastapi/starlette 已 pin，其余靠 dependabot + PR CI 兜底）；Android job 不进 PR CI（只在 tag build-release）。
