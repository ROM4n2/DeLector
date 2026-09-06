# Phase 2b: Agent 分发形态——`delector run` 组装 + Go 二进制 × Python venv 打包

> **Goal**: 把 2a 的 Runtime 变成可分发产品：`delector run` 真实现（supervisor+registry+DAG 组装）、打包为「Go 单二进制 + Python venv 目录」的绿色便携包、CI 自动构建三平台 artifact。
> **Tech Stack**: Go 1.26.5（现有 agent/ module）/ Python 3.11 venv / GitHub Actions（windows/ubuntu/macos）
> **Spec Reference**: ADR-0008 §打包策略（Go 二进制 + venv ~50MB）；Phase 2a 状态块（7 条偏差，2b 承接 #3 #4）
> **Global Constraints**:
> - **不碰现有发布面**：PyInstaller 桌面版 / Chaquopy Android / 既有四端 build-release.yml jobs **零改动**。agent 包是**新增独立 artifact**（`DeLector-Agent-<ver>-<OS>-<arch>.zip/tar.gz`），发布 `needs` 链不动（不打 tag 不触发 publish）。
> - **2a 承接**：supervisor Unix 优雅关闭（build tag：unix 发 SIGTERM / windows 保持 Kill）+ `ProbeTimeout` 默认 2s→10s（状态块偏差 #3 #4）。
> - **run 的产品语义**：`delector run` = 起 Python（supervisor）→ 挂 5 工具 registry → 暴露一个真实 DAG 预设（article-analysis：ingest→[analyze,tts]→writing_check→export 按 ADR-0008 4 层口径）→ 常驻直到 Ctrl+C。端口默认 8001，可 `--port` 覆盖。
> - **凭证纪律**：DEEPSEEK_API_KEY 仅环境变量；打包产物**绝不**内嵌 key 或模型权重（spaCy 模型随 venv 安装，属公共资源）。
> - **venv 自包含**：requirements.txt 装入 venv，`--python-option` 不用；产物结构 `delector-agent/{delector(.exe), python/（venv 拷贝）, delector-src/（包+static+start.py）, README.txt}`。Python 解释器按 OS 取 CI 预装（win: setup-python 3.11）。
> - 门禁：每 Task `cd agent && gofmt -l . && go vet ./... && go test -count=1 -race ./...` 全绿 + `-tags integration`（涉及 run/supervisor 的 Task）；打包 Task 以「产物目录冒烟：run 起服务 + 工具 200」为验收。
> - 提交：`feat|fix|test|ci|build(agent): 中文描述`，每 Task 原子提交并 push；maker-checker 流水线照旧（CPE→CRV→主线程核销提交）。

---

## 架构与文件边界

```
agent/
├── cmd/delector/main.go        ← T2 修改：run 子命令接线（组装层）
├── internal/app/               ← T2 新增：run 组装器（依赖注入 supervisor/registry/dag）
│   ├── app.go
│   └── app_test.go
├── internal/pythonsvc/
│   ├── supervisor.go           ← T1 修改：SIGTERM build tag + ProbeTimeout 默认 10s
│   ├── supervisor_unix.go      ← T1 新增（//go:build unix）
│   ├── supervisor_windows.go   ← T1 新增（//go:build windows）
│   └── supervisor_test.go
├── internal/dag/presets.go     ← T2 新增：article-analysis 预设工厂
└── scripts/package_agent.py    ← T3 新增：本地打包（venv + go build + 组装产物）
.github/workflows/build-agent.yml  ← T4 新增：三平台 CI（独立 workflow，不碰 build-release.yml）
docs/plans/2026-09-06-go-agent-runtime-phase2b.md  ← 本计划
```

依赖方向不变：cmd → app → {pythonsvc, registry, dag}。**Consumes**：2a 全部接口（零改动）；**Produces**：`app.Run(ctx, opts)`、`dag.ArticleAnalysisDAG(reg *registry.Registry)`、CI artifact。

---

### Task 1: supervisor 递延项——SIGTERM build tag + ProbeTimeout 默认上调 [Role: TDD Builder]

**Files:**
- Modify: `agent/internal/pythonsvc/supervisor.go`（ProbeTimeout 默认 2s→10s；关闭逻辑抽平台函数）
- Create: `agent/internal/pythonsvc/supervisor_unix.go`（`//go:build unix`：SIGTERM 优雅关闭）、`supervisor_windows.go`（`//go:build windows`：Kill 保持）
- Test: `supervisor_test.go`（跨平台单测用注入 seam 验证「优雅分支调 cancel 一次并等待；超时走强杀」——平台差异经 seam 断言，不在单测里发真信号）

**Interfaces:**
- Produces: `terminateProc(cmd *exec.Cmd) error`（平台私有，被 supervisor 调用）；`DefaultProbeTimeout = 10 * time.Second`

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 1: supervisor 递延项.
> Goal: ① ProbeTimeout 默认上调 10s（2a 偏差 #4，注释写明 spaCy 冷启动实测依据）；② 关闭语义按平台分治：unix 发 SIGTERM 等 StopTimeout 再 Kill，windows 保持 Kill（cmd.Cancel + WaitDelay 机制不动）。两平台逻辑抽到 build tag 文件，supervisor.go 只调统一入口。
> TDD: 先写失败测试（默认值断言 + terminate seam 行为断言），验红后实现；windows 上跑 GOOS=linux go vet ./... 交叉验证 build tag 文件编译。
> Gate: gofmt/vet/-race 全绿 + `GOOS=linux GOOS=darwin go build ./...` 编译通过。
> Return: JSON 报告含 test_evidence。"

**Step Breakdown:**
- [ ] Step 1: 失败测试（RED）：DefaultProbeTimeout==10s；terminateProc 平台 seam 行为
- [ ] Step 2: 验红 → Step 3: 实现（GREEN）：build tag 双文件 + supervisor.go 接线
- [ ] Step 4: 交叉编译验证（GOOS=linux/darwin/windows 三向 go build）
- [ ] Step 5: 全门禁 + 提交 `fix(agent): supervisor unix SIGTERM 优雅关闭与探针超时默认上调（Phase2b T1）`

---

### Task 2: `delector run` 真组装 [Role: TDD Builder]

**Files:**
- Create: `agent/internal/app/app.go` + `app_test.go`、`agent/internal/dag/presets.go`
- Modify: `agent/cmd/delector/main.go`（run 子命令从 not-implemented 占位接 app.Run；`--port`、`--data-dir` flag）

**Interfaces:**
- Consumes: `pythonsvc.NewSupervisor/NewClient`、`registry.DefaultRegistry`、`dag.NewDAG/AddStep`
- Produces: `app.Run(ctx context.Context, opts Options) error`（Options: Port int、DataDir string、PythonExtraEnv []string）；`dag.ArticleAnalysisDAG(tools *registry.Registry) (*dag.DAG, error)`（4 层口径：ingest→[analyze,tts]→writing_check→export，注释锚 ADR-0008 修订版）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 2: delector run 组装层.
> Goal: run 子命令真实现——supervisor 起 Python（ExtraEnv 注入 DataDir 的 DATABASE_PATH/DELECTOR_DATA_DIR）→ DefaultRegistry → article-analysis DAG 预设 → 常驻（<-ctx.Done() 优雅退出：Stop supervisor）。main.go 接线 + --port/--data-dir flags。
> TDD: app_test 用注入 seam（fake supervisor/registry）单测组装顺序与信号处理；presets_test 断言 DAG 拓扑结构（步骤集+依赖边，防漂移）。integration tag 下加 TestRunEndToEnd（真 Python，skip 契约同 2a T7）。
> Gate: 常规 -race 全绿 + -tags integration 冒烟。
> Return: JSON 报告含 test_evidence。"

**Step Breakdown:**
- [ ] Step 1: 失败测试（RED）：app 组装顺序（supervisor.Start→registry→DAG 构建→ctx.Done→Stop）、presets 拓扑边集
- [ ] Step 2: 验红 → Step 3: 实现（GREEN）
- [ ] Step 4: main.go run 接线 + flags；占位测试 TestRunCommandNotImplemented 相应改写（不许削弱，改为断言 run 启动失败路径）
- [ ] Step 5: `-tags integration` TestRunEndToEnd 真链路
- [ ] Step 6: 全门禁 + 提交 `feat(agent): delector run 组装层与 article-analysis 预设（Phase2b T2）`

---

### Task 3: 打包脚本 `scripts/package_agent.py` [Role: Builder]

**Files:**
- Create: `agent/scripts/package_agent.py`（本地打包：python venv → 装 requirements → 拷 delector 包/static/start.py → go build -trimpath -ldflags "-s -w" → 组装 `delector-agent/` → zip/tar）
- Test: 脚本纯 shell-out 编排，验收靠 T5 冒烟（不写单测——构建脚本测试是戏台，产物冒烟才是证据）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 3: agent 打包脚本.
> Goal: agent/scripts/package_agent.py——① python -m venv <产物>/python；venv pip install -r requirements.txt + spaCy 模型；② 拷贝 delector/ static/ start.py 进产物；③ go build 产物二进制（-trimpath -ldflags '-s -w'，版本从 main.go 常量读或 ldflags 注入）；④ 写 README.txt（启动说明 + 端口 + key 说明）；⑤ 压缩为 DeLector-Agent-<ver>-<os>-<arch>.zip|tar.gz。幂等（重跑清旧产物）。
> 约束：不碰 package_windows.py 与 build-release.yml；产物目录名/结构按计划 Global Constraints。
> 验收: 本机 Windows 跑通全流程 + 产物冒烟（下一 Task 前置：dist 产物内 delector.exe run 起服务、GET /api/tools/ 200）。
> Return: JSON 报告含打包输出尾部与产物体积。"

**Step Breakdown:**
- [ ] Step 1: 脚本实现（venv/拷贝/go build/压缩四段，每段可独立重跑）
- [ ] Step 2: 本机全流程打包成功（记录产物体积，对照 ~50MB 预期）
- [ ] Step 3: 产物冒烟：`delector.exe run` 起服务 + 工具 200（复用 2a integration 断言逻辑）
- [ ] Step 4: 提交 `build(agent): venv+go 二进制绿色便携包打包脚本（Phase2b T3）`

---

### Task 4: CI——`build-agent.yml` 三平台 workflow [Role: CI Builder]

**Files:**
- Create: `.github/workflows/build-agent.yml`（独立 workflow：push tag v* / workflow_dispatch；jobs: build-agent-{windows,linux,macos}；步骤 = checkout → setup-go 1.26 + setup-python 3.11 → 复用 package_agent.py → upload-artifact；**不挂 publish**，2b 不发 release）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 4: agent CI workflow.
> Goal: .github/workflows/build-agent.yml 三平台 job（windows-latest/ubuntu-latest/macos-latest），各 job：actions/checkout → setup-go（go-version: '1.26'）→ setup-python 3.11 → python agent/scripts/package_agent.py → actions/upload-artifact（DeLector-Agent-<os>-<arch>）。
> 约束：触发仅 tag v* 与 workflow_dispatch；不 join build-release.yml 的 publish-github-release（2b 只出 artifact）；yml 里不出现任何密钥。
> 验收: `act` 不可用时做 YAML 语法静态验证（python -c yaml.safe_load）+ 步骤名/结构人工评审；真实触发留给下次 tag（计划注明）。
> Return: JSON 报告。"

**Step Breakdown:**
- [ ] Step 1: workflow 编写（三 job 矩阵，缓存 pip/go mod）
- [ ] Step 2: YAML 语法验证 + 与 build-release.yml 零交集确认（git diff 仅新增文件）
- [ ] Step 3: workflow_dispatch 手动触发一次验证三平台绿（若权限允许；否则记 unverified 留待 tag）
- [ ] Step 4: 提交 `ci(agent): 三平台 agent artifact 构建流水线（Phase2b T4）`

---

### Task 5: 收官——文档回填 + README + work.log [Role: Docs]

**Files:**
- Modify: 本计划（状态块）、`README.md`（Roadmap 加 Phase 2b 条目 + 下载表注 agent artifact 为「预览通道」）、`WORKMEMORY/work.log` + `PROJECT_OVERVIEW.md`

**Step Breakdown:**
- [ ] Step 1: 计划状态块（偏差记录：产物实测体积、CI 触发状态、跨平台验证程度）
- [ ] Step 2: README 两处（Roadmap changelog 顶部 + agent 行更新「含打包」）
- [ ] Step 3: work.log WORK_END 事件 + PROJECT_OVERVIEW Phase 2b 快照
- [ ] Step 4: 提交 `docs(plans): Phase 2b 收官状态回填` 并 push

---

## 明确不做（Out of Scope）
- **替换 PyInstaller 桌面版**：agent 包与现有四端并存，用户主入口仍是 start.py；替换决策留给 Phase 3（数据收集后）。
- **Android 形态**：Chaquopy 与 Go 无交集，不碰 build-android job。
- **签名/公证**（macOS notarization 等）：预览通道 artifact 免签，Phase 2c/3 再议。
- **简历叙事与架构图**（ADR-0008 T16）：归 Phase 2c。
