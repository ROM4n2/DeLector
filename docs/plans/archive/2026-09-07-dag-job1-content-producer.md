# Sub-Plan B: Go DAG 真执行 + job#1（语料→分级卡包内容生产引擎）

> **Goal**: 让 agent 从「只装配不执行」变成**首个真执行 job**：`delector job run encounter-pack` 扫描本地语料目录 → 去重/限量/并发调度 → 每篇 DAG（analyze→vocab_stats→DeepSeek 定级/释义→export cardpack JSON）→ 可选投递 `POST /api/encounter/import-pack` 喂饱遇见区。DeepSeek 走既有 go llm client；Python 侧只加 **1 个**新 leaf 工具 `vocab_stats`。
> **Tech Stack**: Go 1.26.5（agent/ module `github.com/ROM4n2/DeLector/agent`）/ Python 3.11（`delector` FastAPI 既有，599+1 基线零回退）
> **Spec Reference**: ADR-0010 §4/§5（Go 拥有：队列/去重/并发/退避/LLM/卡包组装；Python 保留：spaCy/词表）；Master + Sub-Plan A（cardpack schema、`POST /api/encounter/import-pack` 契约）
> **Global Constraints**:
> - **跨边界契约**：cardpack JSON schema `encounter-pack/v1` 与 A Task 2 定义**逐字段一致**；变更两端同步 + 两端测试。投递端点已是 A2 产物（本机闸）。
> - **Python 基线**：`vocab_stats` 是**第 6 个** leaf tool——同步更新三处：① `delector/tools/__init__.py` TOOL_REGISTRY ② Python `tests/test_tools.py` 工具清单断言（5→6）③ Go `agent/internal/registry/registry.go` `defaultTools` golden 与 golden 测试（5→6，注释指向同步）。Go registry 只暴露 Python 实存工具，防漂移。
> - **凭证/成本护栏**：`DEEPSEEK_API_KEY` 仅环境变量；job 必须带并发上限 + token 预算；**测试一律用 stub**（httptest 桩 base URL，仿 `llm/deepseek_test.go`）；集成门禁跑 stub，无 key 也可全绿。
> - **门禁**（agent/ 内）：`gofmt -l .` 空 + `go vet ./...` + `go test -count=1 -race ./...`；涉及真实 Python 链路的任务用 `-tags integration`（注入临时 `DATABASE_PATH`/`DELECTOR_DATA_DIR`，绝不动用户库）。
> - 复用不重造：语料文本本地读取走 Go（.txt/.md）；URL 抓取不引入（URL→html 的 ingest python tool 留给后续 feed 扩展）。并发护栏复用既有教训（goroutine 不泄露：超时 ctx + cap channel 非阻塞）；退避重试仿 supervisor 既有退避风格。
> - 提交：`feat|fix|test|docs|ci(agent): 中文描述`，Task 原子提交 push，maker-checker 照旧。

---

## Task B1: Python 新 leaf 工具 `vocab_stats` + 三处清单同步 [Role: TDD Builder]

**Files:**
- Create: `delector/tools/vocab_stats.py`
- Modify: `delector/tools/__init__.py`（TOOL_REGISTRY 加 `"vocab_stats"`）、`tests/test_tools.py`（工具清单 5→6 + 新工具契约用例）、`agent/internal/registry/registry.go`（`defaultTools` 加 `vocab_stats`）+ 其 golden 测试预期
- Test: `tests/test_vocab_stats.py`（新建）

**契约（与 A2/A5 词表口径一致）:**
```json
// payload:
{ "tokens": [ {"text":"geht","lemma":"gehen","pos":"VERB"} ],
  "known_extra": [],          // 可选调用方补充已知词 hw 列表
  "levels": ["A1","A2"] }     // 参与 known 基准的考纲等级
// return:
{ "tokens_total": 120, "known_count": 80, "known_rate": 0.667,
  "unknown_ranked": [ {"lemma":"…","count":2} ],   // 按频降序，封顶 60
  "level_hint": "A2" }        // 经验规则：unknown_rate≤0.15→A1, ≤0.35→A2, else B1（P0 启发式）
```
已知 = lemma ∈ (A1∪A2 考纲词 lemma 集) ∪ known_extra。**考纲词集从既有 `delector/services/exam_catalog.py` 取，禁止内嵌新词表**（A1/A2 考纲词服务端已就位）。工具纯函数、无 DB（ADR-0009 纪律）；已知 lemma 集构建做成模块级惰性缓存。

**Subagent Prompt Scaffold:**
> "Implement Task B1: vocab_stats leaf 工具.
> Goal: 第 6 个 Python 工具——按 A1/A2 考纲词集 + known_extra 统计 token known 覆盖与未知词排名；同步三处清单（Python TOOL_REGISTRY、test_tools 5→6、Go defaultTools golden 5→6）.
> Target Files: Create `delector/tools/vocab_stats.py`; Modify `delector/tools/__init__.py`, `tests/test_tools.py`, `agent/internal/registry/registry.go`(+registry_test.go); Test 新建 `tests/test_vocab_stats.py`.
> 既有事实：tools 统一 `async def run(payload)`；exam_catalog.py 提供 A1/A2 词条（先读确认可取的 lemma 字段与取数函数签名）；registry.go defaultTools var + golden 测试位置。
> TDD Steps:
> 1. RED：`tests/test_vocab_stats.py`——已知/未知判定、known_extra 追加、unknown 频序封顶、level_hint 阈值、空 tokens。
> 2. 实现 vocab_stats.run（惰性词集 + Guard Clause）。
> 3. GREEN + 更新 test_tools 清单 5→6；再改 Go defaultTools+golden 5→6 并跑 `cd agent && go test -count=1 -race ./internal/registry/`。
> 4. 全量 `pytest -v` 收尾。
> Return: python + go 双端测试证据."

**Step Breakdown:**
- [ ] Step 1: RED 测试（词集判定/频序/封顶/hint）
- [ ] Step 2: 实现 `vocab_stats.run`
- [ ] Step 3: 三处清单同步 + 双端测试绿
- [ ] Step 4: 全量 pytest + go registry 测试
- [ ] Step 5: 原子提交 push

---

## Task B2: 语料源 `internal/corpus`（本地目录扫描 + 去重 + 限量）[Role: TDD Builder]

**Files:**
- Create: `agent/internal/corpus/source.go` + `source_test.go`
- Test: fixture 语料目录（测试内 t.TempDir 造）

**Interfaces:**
```go
type Article struct { Path, Title, Text, Hash string }
type Options struct { Extensions []string; MaxArticles int } // Extensions 默认 {".txt",".md"}; MaxArticles<=0 不限
func ScanDir(ctx context.Context, dir string, opts Options) ([]Article, error)
// 语义：递归扫描→按扩展名过滤→sha256(text) 去重（保首个）→MaxArticles 截断→按路径排序稳定
```

**Subagent Prompt Scaffold:**
> "Implement Task B2: corpus 语料扫描.
> Goal: 本地目录→去重后 Article 列表（标题=文件名去扩展；hash=sha256 文本）.
> Target Files: Create `agent/internal/corpus/source.go`+`source_test.go`.
> TDD Steps:
> 1. RED：t.TempDir 造 4 文件（含 1 重复内容 txt、1 大 md、1 无关 .json 应跳过、1 子目录）断言去重/过滤/排序/截断。
> 2. 实现 → 3. GREEN → 4. `cd agent && go test -count=1 -race ./internal/corpus/` + gofmt/vet。
> Return: 测试证据."

---

## Task B3: `internal/job` 骨架 + cardpack schema + 预算器 [Role: TDD Builder]

**Files:**
- Create: `agent/internal/job/pack.go`（类型 + Validate）、`agent/internal/job/budget.go`（TokenBudget + 估算）、对应 `_test.go`

**Interfaces:**
```go
// pack.go —— 与 A2 契约逐字段一致
type Pack struct {
  Schema    string   `json:"schema"`             // "encounter-pack/v1"
  PackID    string   `json:"pack_id"`
  Source    PackSource `json:"source"`
  CreatedAt string   `json:"created_at"`         // RFC3339 UTC
  Article   PackArticle `json:"article"`
  Analysis  PackAnalysis `json:"analysis"`
  Glosses   []PackGloss `json:"glosses"`
  EstimatedCEFR string `json:"estimated_cefr"`   // A1|A2|B1（大小写归一）
}
type PackArticle struct { Title, RawText string; CharCount int }
type PackAnalysis struct { TokensTotal, KnownCount int; KnownRate float64; LevelHint string; UnknownLemmas []LemmaCount }
type LemmaCount struct { Lemma string; Count int }
type PackGloss struct { Lemma, GlossZH, CEFR string; Pos string }
func (p *Pack) Validate() error                 // 必填键 + schema 固定 + estimated 白名单
type PackSource struct { Kind, Path, File string }

// budget.go —— 成本护栏（DeepSeek 真调用防失控）
type TokenBudget struct { cap, used int }
func NewTokenBudget(cap int) *TokenBudget
func (b *TokenBudget) Reserve(est int) error     // 估算 = len(text)/4 + 每词 8；超 cap → ErrBudgetExceeded
func (b *TokenBudget) Used() int
```
（可选单测：并行 Reserve 原子性用 mutex；cap 0 = 无限。）

**Subagent Prompt Scaffold:**
> "Implement Task B3: job 骨架+schema+预算.
> Goal: Pack 类型与校验、TokenBudget 护栏（先于 DAG 步骤落地，供 B4/B5 依赖）.
> Target Files: Create `agent/internal/job/pack.go`、`budget.go` + tests.
> TDD Steps: RED(Validate 必填/schema/白名单；Budget Reserve 超限/并发原子/0=无限)→GREEN→go test -race ./internal/job/。
> Return: 测试证据."

---

## Task B4: gloss 步骤（LLM 抽象 + prompt + JSON 解析）[Role: TDD Builder]

**Files:**
- Create: `agent/internal/job/gloss.go` + `gloss_test.go`
- Consumes: `agent/internal/llm`（`Client.Complete`；接口对齐其 `Option`）

**Interfaces / 语义（定死）:**
```go
type GlossLLM interface {
  Complete(ctx context.Context, system, user string, opts ...llm.Option) (string, error)
}
type GlossRequest struct {
  Text          string          // 正文前 N 段抽样（防超长：按词截断 ~1200 token）
  UnknownLemmas []LemmaCount    // 来自 vocab_stats，封顶 60
  KnownRate     float64
}
type GlossResult struct {
  EstimatedCEFR string      `json:"estimated_cefr"` // A1|A2|B1
  Glosses       []PackGloss `json:"glosses"`        // lemma+gloss_zh+cefr+pos
}
func BuildGlossPrompt(r GlossRequest) (system, user string)   // 系统提示要求严格 JSON（附示例 + 禁多余文本）
func ParseGlossLLMOutput(raw string) (GlossResult, error)     // 容错：剥离 ```json 围栏 / 首尾空白后 json.Unmarshal；未知词逐条校验
```
- 真实实现 = `*llm.Client`（Config 注入 BaseURL/Model，供 stub）。步骤内每次调用前 `budget.Reserve(估算)`。
- 测试：httptest 桩（DeepSeek chat/completions 形状，仿 `llm/deepseek_test.go`）；ParseGlossLLMOutput 测围栏剥离、坏 JSON、空 glosses。

**Subagent Prompt Scaffold:**
> "Implement Task B4: gloss 步骤核心.
> Goal: DeepSeek 定级/释义的 prompt 与返回解析，抽象成 GlossLLM 便于 stub.
> Target Files: Create `agent/internal/job/gloss.go`+test（先读 `agent/internal/llm/deepseek.go` 的 Complete/Option 与桩测试手法）。
> TDD Steps:
> 1. RED：ParseGlossLLMOutput（带 ```json 围栏/纯 JSON/坏 JSON/字段缺失）+ BuildGlossPrompt 抽样长度与 JSON 指令断言。
> 2. 实现 + httptest 桩冒烟（GlossLLM=真 client + 桩 BaseURL）→ GREEN。
> Return: 测试证据."

---

## Task B5: encounter-pack DAG 预设（analyze→vocab_stats→gloss→export_pack）[Role: TDD Builder]

**Files:**
- Create: `agent/internal/job/encounter.go`（DAG 构建 + per-article runner）+ `encounter_test.go`
- Consumes: `agent/internal/dag`、`agent/internal/registry`、B3/B4

**语义（DAG 数据流——实现前先读 `dag.go`/`presets.go`，保持与既有 Run/AddStep/deps 视图一致）:**
```
input: {text, title, hash}（load 步骤产出）
步骤（每篇一 DAG，跨篇由 B6 并发）:
 1) analyze     依赖 load   → payload {text}                    → python analyze 输出（含 tokens/lemma 若其 sentences 已带；否则取 B 侧所需字段）
 2) vocab_stats 依赖 analyze → payload {tokens: 来自 analyze}    → 覆盖统计 + unknown_ranked
 3) gloss       依赖 vocab_stats+load → 先 Budget.Reserve → GlossLLM.Complete → GlossResult
 4) export_pack 依赖 gloss+vocab_stats+load → 组装 Pack → JSON 写 outDir（名 <slug>-<hash8>.pack.json，目录自动建）→ 返回 {path, pack_id}
```
- 测试隔离：注册 fake ToolFunc 到 registry 代替 python；fake GlossLLM 返回固定 JSON——**单测不碰 python/网络**。
- 输出的 Pack 用 `Validate()` 钉 schema 一致；写文件用 `os.WriteFile`（原子：先 tmp 后 rename，遵循仓库既有写文件纪律若存在）。

**Subagent Prompt Scaffold:**
> "Implement Task B5: encounter-pack DAG 预设.
> Goal: 4 步 per-article DAG（含 export 组装+落盘），全部 fake 可单测.
> Target Files: Create `agent/internal/job/encounter.go`+test.
> 既有事实：dag.DAG.AddStep(id, fn, deps...)/Run(ctx, input)；presets.go 展示 ToolFunc→StepFunc 适配；registry.Registry.Run(ctx,name,payload)。
> TDD Steps:
> 1. RED（fake registry + fake gloss）：跑一篇 fixture 文本 → 断言 steps 调用顺序/依赖、输出 Pack 字段（title/level/glosses/known_rate）与 Validate 通过、落盘文件存在且 JSON 可回读。
> 2. 实现 → GREEN → `go test -count=1 -race ./internal/job/`。
> Return: 测试证据（含顺序断言）。"

---

## Task B6: 调度 runner（并发限量 + 预算 + 退避 + 错误报告）[Role: TDD Builder]

**Files:**
- Create: `agent/internal/job/runner.go` + `runner_test.go`

**语义:**
```go
type RunConfig struct { CorpusDir, OutDir string; Concurrency, MaxArticles, BudgetTokens int; DryRun bool; DeliverURL string }
type Result struct { Packs []string; Failed []string }  // Failed = {path, err}
func RunEncounterPack(ctx context.Context, t *registry.Registry, g GlossLLM, cfg RunConfig) (Result, error)
```
- 流程：ScanDir（B2）→ DryRun 时仅返回清单不执行 → 并发上限用 `chan struct{}` 容量 N（或用仓库既有 worker-pool 模板，注意 golang.org/x/sync 若已引入则复用）→ 每篇 Budget 共享一个 TokenBudget：预算耗尽 → 该篇 gloss 步骤记 fail（ErrBudgetExceeded），**其余篇继续但不再调 LLM** → 每篇错误收集进 Failed；`DeliverURL` 非空时对每篇成功 Pack POST `/api/encounter/import-pack`（http.NewRequestWithContext + 5s 超时；429/5xx 退避重试 3 次，仿既有退避风格）。
- ctx 取消（SIGINT/SIGTERM 冒泡）：goroutine 零泄露（测试用 `go.uber.org/goleak` 不引入——用现有既有惯例：`-race` + 显式 WaitGroup/ctx 断言）。
- 测试：fake registry/gloss + t.TempDir：并发上限生效（慢 fake 下最大在飞数断言 ≤N）、预算耗尽降级、一坏篇不影响他篇、DeliverURL 用 httptest 断言 POST body schema + 幂等重试、ctx cancel 提前退出。

**Subagent Prompt Scaffold:**
> "Implement Task B6: runner 调度.
> Goal: 跨篇并发/预算/退避/错误报告 + 投递.
> Target Files: Create `agent/internal/job/runner.go`+test.
> TDD Steps: 逐断言 RED→GREEN（并发上限/预算耗尽/fail 隔离/投递 body/重试/cancel），`go test -count=1 -race ./internal/job/`。
> Return: 测试证据."

---

## Task B7: cobra `delector job run encounter-pack` + app 接线 [Role: TDD Builder]

**Files:**
- Create: `agent/cmd/delector/job.go`
- Modify: `agent/cmd/delector/main.go`（rootCmd 加 `newJobCmd`；版本/`run` 不动）
- Test: `agent/cmd/delector/job_test.go`（flag 解析 + 无参数报错 + `--help` 文档字符串；不真跑 python）

**Flags:**
```text
--corpus <dir>（必填）--out <dir>（必填）
--concurrency N（默认 4）--max-articles N（默认 0=不限）--budget-tokens N（默认 100_000）--dry-run
--python-url（默认空=自动 supervisor 起 python 于 127.0.0.1:8001，仿 `run` 流程；非空则直连）
--deliver-url（默认 http://127.0.0.1:8000）
--llm-base-url（默认空=DeepSeek 官方；测试/stub 用）
```
- 运行流程：python 可达性（supervisor 或直连）→ registry（DefaultRegistry，须已含 vocab_stats=6 工具）→ ScanDir → RunEncounterPack → 打印 Result（packs/failed 统计 + 退出码：有 failed → 1；成功 0）。

**Subagent Prompt Scaffold:**
> "Implement Task B7: job 子命令.
> Goal: `delector job run encounter-pack` cobra 命令 + 接线既有 run 的 python 启动路径.
> Target Files: Create `agent/cmd/delector/job.go`+job_test.go; Modify main.go.
> 既有事实：newRunCmd 的 python resolve/supervisor/baseURLForPort 组装在 `agent/cmd/delector/main.go` 与 `internal/app`——先读并提取可复用帮助函数（勿复制粘贴长逻辑，抽公共函数供 run/job 共用）。
> TDD Steps: flag/cobra 单测（RED→GREEN）→ `cd agent && go vet ./... && go test -count=1 -race ./...`。
> Return: 证据."

---

## Task B8: 集成真链路（`-tags integration`：真 python + stub LLM）[Role: TDD Builder]

**Files:**
- Create: `agent/integration_encounter_test.go`（build tag `integration`，仿既有 `integration_test.go` 的临时环境注入法）

**门禁语义（Master 验收门第 3 条）:**
1. 起真实 python 实例（临时 `DATABASE_PATH`/`DELECTOR_DATA_DIR`，port 8001 同既有集成）。
2. `GET /api/tools/` 断言含 **6** 工具（vocab_stats 在列）。
3. stub DeepSeek httptest（BaseURL 指向桩）。
4. 在 t.TempDir 造语料 fixture（2 篇短文）→ `RunEncounterPack`（deliver-url = python 实例的 `http://127.0.0.1:8001`）→ 断言：2 篇 pack 落盘、Pack.Validate 过、POST import-pack 200。
5. `GET /api/encounter/texts`（python 侧 TestClient 或同实例 GET）断言 2 行命中、level 归一。
6. python 全量 `pytest -v` 复跑（无回归）+ go 全量。

**Subagent Prompt Scaffold:**
> "Implement Task B8: 集成真链路.
> Goal: DAG→真 python 工具→stub LLM→落盘→import-pack→encounter texts 命中 的端到端门禁.
> Target Files: Create `agent/integration_encounter_test.go`.
> 既有事实：读 `agent/integration_test.go` 看临时库注入 + supervisor 起法（ProbeTimeout 调 30s 教训）；A2 的 import-pack 契约已就绪。
> Steps: 按门禁语义逐条实现，跑 `cd agent && go test -count=1 -tags integration ./...`；再仓库根 `pytest -v` 复跑。
> Return: 双端证据."

---

## Task B9: 文档收尾 + 全量门禁 [Role: TDD Builder]

**Files:**
- Modify: `WORKMEMORY/PROJECT_OVERVIEW.md`（agent 从壳变能力：job#1 状态）、README 路线图（如含 agent 段）、Master plan 执行状态块（A/B commit + CRV + 偏差）
- Modify: 若 Go registry `run` 展示语义变化（6 工具）需同步 `docs/` 中工具清单文档

**交付物:** Master 验收门 4 条全部勾绿 + 真实冒烟记录（作者桌面跑 2 篇 fixture：DEEPSEEK_API_KEY 存在则真跑一次 gloss 且记录 token 消耗，不存在则以 stub 记录）+ 偏差记录。

**Subagent Prompt Scaffold:**
> "Implement Task B9: 文档收尾.
> Goal: 状态文档 + 全量门禁确认 + 偏差记录.
> Steps: 复跑 Master 验收门全命令取证据；文档就地更新；真实/桩 LLM 冒烟各记一档。
> Return: 门禁证据汇总表 + diff 摘要."

---

## Sub-Plan B 验收（Master 门禁 B 侧）
- [x] `go test -count=1 -race ./...`（agent/ 全包）绿（2026-09-07 收官复跑，见文末状态块）
- [x] `go test -tags integration` 真链路绿（6 工具 + import-pack 命中，`TestEncounterRealChain` PASS）
- [x] Python 全量 `pytest -v` 零回退（**686 passed + 1 skipped**，vocab_stats 新测试净增）
- [x] `delector job run encounter-pack --dry-run` 与真实 run 各冒烟一档（stub LLM 记录，见文末状态块第 3 条）

---

## 执行状态（Sub-Plan B 收官）

> 追加于 B9（2026-09-07）。Sub-Plan B 八任务（B1–B8）已在分支 `feature/encounter-job1`
> 落地并经各自 CRV（Code Review Verdict）通过后提交；B9 收尾任务将验收门 B 侧勾绿、
> 复跑全量门禁、补偏差记录与状态文档。真实 DeepSeek 冒烟档已于 **2026-09-08**
> 由作者在桌面真跑补齐（token 消耗 **1,253**），见文末「真实 LLM 档」记录。

**逐任务提交哈希：**

| Task | 提交 | 说明 |
| --- | --- | --- |
| B1 | `a1e4245` | `vocab_stats` 第 6 号 leaf 工具 + 三处清单同步（12 测试，全量 686+1，CRV APPROVED；黄注释闭，A2 词源偏差正当，见偏差 a） |
| B2 | `2e00f4c` | corpus 语料扫描（递归/过滤/去重/限量/排序，8 测试 -race，CRV APPROVED） |
| B3 | `3dd4177` | `internal/job` Pack schema（encounter-pack/v1 tag 对齐 A2）+ TokenBudget 护栏（13 测试 -race，CRV APPROVED；黄 1 枚已由 B5 闭，见偏差 b） |
| B4 | `39558ff` | gloss 步骤（GlossLLM+prompt+容错 JSON 解析，20 用例 -race，CRV APPROVED） |
| B5 | `9ddeb4b` | encounter-pack DAG 预设（analyze→vocab_stats→gloss→export 原子落盘）+ 闭 B3 黄（CRV APPROVED；2 黄记账，见偏差 b） |
| B6 | `6c3e392` | runner 调度（worker-pool 并发/共享预算/退避投递/fail 隔离，7 测试 -race，CRV APPROVED；黄 YAGNI 见偏差 e） |
| B7 | `77ce8d4` | cobra `job run encounter-pack` + run/job 共享 supervisor helper（CRV APPROVED；零卡；导出 helper 超出 Files 见偏差 c） |
| B8 | `13d8535` | integration 真链路门禁 + 修复 deliver 投递信封 `{pack}`（集成红卡闭环，`TestEncounterRealChain` PASS，CRV APPROVED；缺陷信封见偏差 d） |

**Reviewer 判定：** B1–B8 均 CRV APPROVED；各 reviewer yellow（黄）均已闭环或在偏差中记账，
无遗留红卡。

**偏差记录：**

- **（a）B1 —— A2 词集取用偏差（正当）**：计划契约本拟以「装饰 hw（含定冠词如 `das Abenteuer`）」匹配已知词，但 vocab_stats 的 `tokens` 来自 spaCy analyze，`lemma` 已还原成无装饰的原形（`Abenteuer`）。为对齐 A2 词集又避免键不匹配，B1 用 A2 `exam_catalog` 词条的**同源常量 `lemma-key`**（去装饰、无定冠词）构建 known 集合——与 A1/A2 词表口径一致且不内嵌新词表，语义正当（deviation approved by CRV）。
- **（b）B3 黄修复并入 B5**：B3 `pack.go` 的某条 reviewer 黄色改进点（细节入 B3 commit）未在 B3 原地闭环，B5 落地时一并修入（见 B5 提交说明「+ 闭 B3 黄」）；B5 另带 2 条记账黄（差异收口、字段注释），在 B5 CRV 已 approved 记账。
- **（c）B7 超出计划 Files**：B7 为让 `run`/`job` 复用 supervisor 启动路径（python resolve / srcDir / extraEnv / baseURLForPort）而不复制粘贴长逻辑，从 `cmd/delector/main.go` 抽出 **+2 个导出 helper**（授权单源共享），超出计划 Task B7 列出的 Files。属既有事实提示的「抽公共函数供 run/job 共用」执行，非架构新增，CRV approved。
- **（d）B8 —— 集成门禁抓出 B6-A2 投递信封缺陷（红卡闭环）**：B6 runner 投递 `POST /api/encounter/import-pack` 时最初以**裸 `Pack` JSON 作为 body** 直接 POST，而 A2 契约（`ImportPackRequest.pack`）要求请求体为 `{pack: <Pack>}` 信封——真链路因此 422（`Field required`，loc=[body,pack]）。集成红卡在 B8 抓出；B8 修复 runner `deliverPack` 先经 `envelopePack` 包裹（`json.RawMessage` 原封嵌入，pack 内部字段零重编码）再 POST，并强化 `TestRunner_DeliverBackoff` 断言外层含 `pack` 键且内层解析后 `schema == encounter-pack/v1`，`TestEncounterRealChain` 全链路 200 闭环。此为「非集成单测（httptest 自身定义期望）恒绿、真契约在集成层才暴露」的经典教训，已固化为集成门禁资产。
- **（e）envelopePack 未显式 `json.Valid`（黄，上游保证）**：投递信封解析处未对收到的 body 显式跑 `json.Valid`，依赖 Go `json.Unmarshal` 天然校验 + 上游（A2 import-pack / 本仓 runner 落盘）均为本仓合法 JSON。YAGNI 记账，不额外加层。

**Sub-Plan B 验收门 B 侧（2026-09-07 B9 收官复跑）：**

1. `go test -count=1 -race ./...`（agent/ 全包）**绿**——gofmt `-l` 空 + `go vet ./...` 空 + 全包 `-race` PASS。
2. `go test -count=1 -tags integration ./...` **绿**——`TestEncounterRealChain` PASS（`tools=[analyze export ingest tts vocab_stats writing_check] packs=2 texts=[im_supermarkt mein_tag]`，import-pack 200）。
3. Python 全量 `pytest -q`（仓库根）**686 passed + 1 skipped** 零回退（B1 前基线 = Sub-Plan A 收官 673+1；B1 起 vocab_stats 新测试净增 → B9 终值 686+1）。
4. 冒烟（stub 档，见下第 3 条 dry-run + 真实 run）；真实 LLM 档于 2026-09-08 补齐（见下）。

**Sub-Plan B 收官冒烟记录：**

- **CLI wiring（dry-run）**：`go run ./cmd/delector job run encounter-pack --corpus <tmp2篇A1> --out <tmp>/out --dry-run` → 自动 supervisor 起 python、列出预排 `packs=2 failed=0`、退出码 **0**（confirm 接线与 dry-run 清单语义）。
- **CLI 真实 run（stub LLM）**：同一 2 篇 fixture，`--deliver-url "" --llm-base-url http://127.0.0.1:18999`（本地 stub DeepSeek 桩，回吐固定 GlossResult JSON）→ supervisor python 真跑 `analyze`/`vocab_stats`、stub gloss、export 原子落盘 → `packs=2 failed=0`、退出码 **0**，产出 `supermarkt-2c6a3304.pack.json` 与 `mein-tag-c282b89f.pack.json`（`encounter-pack/v1` schema 可回读、`Validate()` 过）。
- **真实 LLM 档（2026-09-08 补齐，作者桌面）**：桌面已配 `DEEPSEEK_API_KEY`（经 `agent/.env` 加载——2026-09-08 增量：Go 启动时 `loadDotEnv()` 读取 cwd `.env`，并用 `agent/scripts/verify_encounter.ps1` 一键验证）。真跑 2 篇 A1 fixture → `packs=2 failed=0`、退出码 **0**，产出 `a1-1-2410f335.pack.json`（`estimated_cefr=A2`、`glosses=9`、`char_count=102`、`known_rate=0.36`）与 `a1-2-8fc4008d.pack.json`（`estimated_cefr=A1`、`glosses=8`、`char_count=96`、`known_rate=0.32`）；两包均按 `encounter-pack/v1` 逐字段校验 PASS（schema / pack_id / article.title·raw_text / estimated_cefr∈{A1,A2,B1}）。**token 消耗：1,253**（DeepSeek 平台「用量」页读数）。至此 Master 验收门仅余第 4 条的双端手工冒烟（A7 清单）。
