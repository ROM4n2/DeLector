# Master Plan: 遇见区 P0 + Go DAG job#1 内容生产引擎（ADR-0010 落地）

> **Goal**: 按 ADR-0010 分层定案把「背词→阅读桥」做成真实闭环：P0 遇见区最小版（Python/Web 交互，手选短文，已背词高亮 + 生词进卡 + 小复习）先行上线；随后 Go agent 落地**首个真执行 job**（语料→分级卡包批处理，DeepSeek 定级/释义），产物喂给遇见区。
> **Tech Stack**: Python 3.11（FastAPI + spaCy + SQLite）/ 原生 ES 前端 / Go 1.26.5（`github.com/ROM4n2/DeLector/agent`）
> **Spec Reference**: Vault `08-Projects/DeLector/01-ADR/0010-encounter-zone-layered-go-agent-producer.md`（Accepted）；ADR-0008（DAG 口径）；ADR-0009（Python 工具契约）；上一阶段计划 `docs/plans/2026-09-06-go-agent-runtime-phase2a.md`、`...-phase2b.md`
> **子计划（按执行顺序，A 先行）**:
> - **Sub-Plan A** → `docs/plans/2026-09-07-encounter-zone-p0.md`（P0 遇见区，Python + 前端）
> - **Sub-Plan B** → `docs/plans/2026-09-07-dag-job1-content-producer.md`（Go DAG 执行运行时 + job#1）

## 核心约束（两个子计划共用）

1. **ADR-0010 红线**：交互请求（含已背词判定/进卡）**不离开本机**、不加 Go 代理跳；Python 599+1 测试核心零重写；不建跨网 hub；桌面分发不碰（PyInstaller/Android 面零改动）。
2. **跨子计划契约 = cardpack JSON**（schema `encounter-pack/v1`，字段清单见子计划 A Task 2 / B Task 5 一致定义）：B 产出 → 经 `POST /api/encounter/import-pack`（本机闸）投递给 A 的 `encounter_texts`。**schema 变更必须同步改两端 + 两端测试**。
3. **Python 基线**：当前 `599 passed + 1 skipped` 零回退；新增路由/tool 允许净增测试；跑法 `pytest -v`（仓库根，conftest 插 sys.path 长期保留）。
4. **Go 门禁**（agent/ 下）：`gofmt -l .` 为空 + `go vet ./...` + `go test -count=1 -race ./...`；涉及真实 Python 链路的用 `-tags integration`（注入临时 `DATABASE_PATH`/`DELECTOR_DATA_DIR`，绝不动用户库）。
5. **凭证纪律**：`DEEPSEEK_API_KEY` 仅环境变量；批量调 LLM 必须带预算/并发护栏；测试一律走 stub（httptest 桩 base URL，禁止真实 key）。
6. **提交**：每 Task 原子提交并 push，`feat|fix|test|docs|ci(agent|encounter): 中文描述`；maker-checker 流水线照旧（CPE → CRV → 主线程核销 + 提交）。
7. **名词约定**：德语词库=「词表/考纲词」（服务端 exam_catalog A1/A2 集）；「已背词/known」= 用户背词工作台 deck 里**已学过**的卡（`reps > 0`，见 A Task 5）；工具新增名统一为 **`vocab_stats`**（6 号 leaf tool）。

## 验收门（ADR §7.3，两个子计划全部完成时）

- [ ] Python `pytest -v` 全绿（599+1 基线零回退，新增测试净增）
- [ ] `cd agent && gofmt -l .`（空）+ `go vet ./...` + `go test -count=1 -race ./...` 全绿
- [ ] `go test -tags integration`：**真 DAG → 真 Python 工具（vocab_stats）→ LLM(stub) → cardpack 文件 → POST import-pack → GET /api/encounter/texts 命中** 全链路 200
- [ ] 遇见区 P0 手选短文在「桌面源码实例 + Android Chaquopy 实例」双端手工可用（Android 手工清单见 A Task 7）

## 已知边界与开放项（不进本轮，正式记录）

- **喂到女友设备**：`encounter_texts` 是各实例本地 DB 行；Android 端通过 App 内「加文本」表单（A Task 4）就地录入，本轮不做文本库跨端同步。后续可评估把 `encounter_texts` 并入 LAN 对等同步域。
- **job#1 覆盖基准**：vocab_stats 的"已知"以 A1∪A2 考纲词表为基准（批处理面向大众 i+1 卡包）；她的个人 deck 覆盖统计留在 P0 阅读端（近设备），不做进 job。
- **DeepSeek 真实调用**：有 key 才能跑真 gloss；无 key 时 job 以 `--dry-run`/stub 可验证全链路（验收门即 stub 形态）。

## 执行状态

> 回填于两子计划收官（Sub-Plan A = A7 于 `2026-09-07`；Sub-Plan B = B9 于 `2026-09-07`）。
> 均已各自 CRV APPROVED 后原子提交；A/B 偏差与验收门勾选详见两子计划文末执行状态块。

**Sub-Plan A（遇见区 P0）**：提交区间 `d5c1155..2d78c09`（A1–A6 + A7 收官），全 CRV APPROVED，
偏差（skip 守卫 / CSS 迁移 / A6 REWORK）已闭环；验收门 A 侧全绿（import-pack/annotate/API 冒烟 done）。

**Sub-Plan B（Go DAG job#1）**：提交区间 `a1e4245..13d8535`（B1–B8 + B9 收官），全 CRV APPROVED，
偏差 5 条记账（a 词源常量 lemma-key / b B3 黄并入 B5 / c B7 导出 helper / d B8 投递信封红卡修复 /
e envelopePack 未显式 json.Valid）；验收门 B 侧全绿（race / integration 真链路 / pytest 686+1 / 冒烟）。

**验收门状态（Master 门 4 条）：**

- [x] Python `pytest -v` 全绿（**686 passed + 1 skipped**，599+1 基线零回退，新增测试净增）
- [x] `cd agent && gofmt -l .`（空）+ `go vet ./...` + `go test -count=1 -race ./...` 全绿
- [x] `go test -tags integration`：真 DAG → 真 Python 工具（vocab_stats）→ LLM(stub) → cardpack 文件 → POST import-pack → GET /api/encounter/texts 命中，全链路 200（`TestEncounterRealChain` PASS）
- [ ] 遇见区 P0 手选短文在「桌面源码实例 + Android Chaquopy 实例」双端手工可用（Android 手工清单见 A Task 7）——**PENDING-作者**（需作者在双端手工跑 A7 清单；仓库可跑门禁为 stub/集成形态，真实双端不在 CI）
- [ ] 真实 DeepSeek 冒烟档——**PENDING-作者**（桌面无 `DEEPSEEK_API_KEY`；作者配 key 后真跑 gloss 并记录 token 消耗，计划允许无 key 时以 stub 记一档）

状态同步：`WORKMEMORY/PROJECT_OVERVIEW.md` 当前状态已更新（agent 从壳变首个真执行 job#1）；README 路线图已加 Sub-Plan B 完成行。
