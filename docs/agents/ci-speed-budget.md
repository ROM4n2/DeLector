# CI 闸门速度与并发预算

> 适用范围：本规范约束**闸门本身的开销**，不减少真实检查。要砍只能砍重复执行、重复安装与无意义等待；不得用提速名义删除测试、契约检查或安全闸。
> 与 `CONTRIBUTING.md` 的提交粒度规范并列：前者约束提交如何拆，本文约束 CI 如何保持快。

## 1. 实测基线

- 读取时点：**2026-11-04 12:41:53 +08:00**。
- 样本：PR #206 最新成功 CI run [`41773483635`](https://github.com/ROM4n2/DeLector/actions/runs/41773483635)，head `3a05df36e7b54fbb537044311be43bf7eb73f38f`。
- run 创建到更新结束：**278 秒（4m38s，含排队）**；最早 job 开始到最晚 job 结束：**230 秒（3m50s）**。
- 13 个执行 job、2 个跳过 job；峰值并发 **13**；执行 job 时长累计 **914 秒**。累计值用于核算 runner 成本，不能当作墙钟。
- 最长 job：`unit-1` **229 秒**，决定当前关键路径。

### 1.1 每个 job 的实测时长

| Job | 时长 | 备注 |
| --- | ---: | --- |
| Detect packaging-surface changes | 5s | 路径检测 |
| No Silent Degradation Gate | 8s | 既有机械闸 |
| Layer Invariants Gate | 7s | 既有机械闸 |
| Go Gates | 39s | Go 安装/缓存 2s，race 27s |
| Secret Scan | 8s | gitleaks |
| Python unit-4 | 145s | 依赖/setup 32s，测试 90s |
| Go↔Python Integration Gate | 48s | 依赖/setup 23s |
| Python integration-heavy | 109s | 依赖/setup 33s，测试 55s |
| Python cost-guards | 118s | 依赖/setup 25s，测试 74s |
| Python unit-1 | **229s** | 依赖/setup 31s，测试 172s；关键路径 |
| Python unit-3 | 121s | 依赖/setup 32s，测试 61s |
| Mock Drift Gate | 7s | 既有机械闸 |
| Python unit-2 | 70s | 依赖/setup 18s，测试 36s |
| Master Direct-Push Scope Gate | skipped | 本样本未执行 |
| Windows Portable Smoke | skipped | 本样本未执行，不能据此伪造其预算实测值 |

### 1.2 依赖安装、重复测试与缓存

- 六个 pytest 分片分别执行 `Install Python dependencies`，累计 **86s**；Go↔Python integration 另为 **12s**。这些 job 使用独立 runner，安装无法靠口头“共用环境”消除。
- 缓存实际命中：Python `setup-python` 日志显示 pip cache **restored successfully**（unit-1 约 284 MB；integration 约 137 MB）；Go `setup-go` 约 29 MB 且 **restored successfully**。当前不是“无缓存的全量依赖安装”。
- pytest 六个分片按文件集合拆分，integration-heavy 与 cost-guards 从相应分片排除；**未发现同一 pytest 用例在多个 job 重复执行**。
  - **2026-11-04 复核更正**：上述结论有误。旧分片的 `--ignore` 在 bash 展开 glob 后失效，实测一次 run 重复执行 356 个用例，见 §1.4。
- **真实重复项**：Ruff/mypy 位于 matrix 公共 steps，六个分片都安装并执行一次。

| 重复步骤 | 六 job 累计 |
| --- | ---: |
| Install Ruff | 7s |
| Ruff lint gate | <1s（逐 job 时间戳取整为 0） |
| Install Mypy | 17s |
| Mypy strict（delector/tools） | 47s |
| Mypy tests baseline | 15s |
| Mypy desktop entry | 3s |
| **合计** | **89s** |

### 1.3 去重实施后的实测（2026-11-04，PR #210）

- 改动：Ruff/mypy 六步只在 `unit-2` 执行（`if: matrix.suite.name == 'unit-2'`）；其余五个分片照常跑各自用例集合。未新增 job、未删除任何检查、未动缓存。
- 样本：PR #210 run [`41802137331`](https://github.com/ROM4n2/DeLector/actions/runs/41802137331)，head `efdbb17`，结论 success。
- 同日三个样本的分片级对比（`unit-1` 的 pytest 步骤本身就在 129s–186s 间波动，未改 workflow 的 `master` 样本也跑了 178s）：

| 样本 | 事件 | 墙钟 | job 跨度 | 峰值并发 | 六分片 static 累计 |
| --- | --- | ---: | ---: | ---: | ---: |
| `41793803081`（PR #209） | pull_request | 178s | 175s | 13 | 92s |
| `41799790408`（master） | push | 241s | 239s | 14 | 85s |
| `41802137331`（PR #210） | pull_request | 224s | 222s | 13 | **14s** |

- **墙钟没有变快，本次样本反而慢 46s**。原因不在去重：`unit-1` 的 `Run full pytest suite` 从 129s 涨到 186s，而未改 workflow 的 `master` 样本同一分片同样是 178s —— 同分片跨 runner 波动达 57s，远大于静态检查的 10s。
- **可确证的收益**：六分片静态检查累计 **92s → 14s（-78s runner 时间）**，与 TODO-CI-01 预估的 -74s 一致；`unit-1` 分片内静态开销 **10s → 0s**。
- `unit-2` 总时长 91s（静态 14s + 测试 43s + 环境），仍是最短分片，没有变成新关键路径。
- 口径：**只报 runner 累计节省，不报墙钟提速**。要让墙钟确定性下降必须动关键路径 `unit-1` 的用例负载，另立计划。

### 1.4 分片互斥失效与关键路径压缩（2026-11-04，PR #211）

复核 unit-1 的关键路径时发现更严重的问题：**旧分片并没有真正互斥**。

- 旧 matrix 的 `args` 形如 `tests/test_[a-c]*.py --ignore=tests/test_articles_list_cost.py ...`。bash 会先把 glob 展开成**显式文件路径**，而 pytest 的 `--ignore` 只作用于目录递归、**对显式传入的文件无效**。
- 实证：run `41793803081` 的 unit-1 日志 `721 passed`，按意图应为 608；差额 113 恰好等于 4 个被 ignore 文件的用例总和。unit-2 多 94（test_frontend_layers）、unit-4 多 149（server/settings/syntax_hard）。**一次 run 重复执行 356 个用例**，unit-1 的 pytest 从本该约 68s 被顶到 155.6s。
- 改法：`tools/ci_shards.py` 显式清单（六个分片唯一事实来源）+ `tools/ci_shard_weights.json`（本机 `pytest --durations=0` 实测权重）；matrix 去掉 `args`；`tests/test_ci_hardening.py` 新增四条守卫（分区完整互斥、专项套件独占、unit 配平 ±25%、禁止退回 glob + `--ignore`）。
- 配平后本地全量（六分片逐一跑，2749 passed / 4 skipped）：

| 分片 | 文件 | 用例 | 本机 pytest |
| --- | ---: | ---: | ---: |
| unit-1 | 42 | 654 | 86.4s |
| unit-2 | 50 | 683 | 72.3s（另加静态 14s） |
| unit-3 | 33 | 342 | 85.2s |
| unit-4 | 39 | 710 | 84.1s |
| integration-heavy | 5 | 316 | 79.3s |
| cost-guards | 3 | 44 | 131.0s |

- CI 实测（run [`41811788954`](https://github.com/ROM4n2/DeLector/actions/runs/41811788954)，head `4116baa`，success；对照为 PR #210 的 [`41803741662`](https://github.com/ROM4n2/DeLector/actions/runs/41803741662)）：

| 指标 | 改前（41803741662） | 改后（41811788954） |
| --- | ---: | ---: |
| Python 门禁关键路径（最早 job → 最晚 pytest job） | 188s | **145s** |
| unit-1 job / pytest | 187s / 155.6s | 102s / 55.7s |
| unit-2 job / pytest | 116s / 56.3s | 106s / 46.3s（+静态 14s） |
| unit-3 job / pytest | 81s / 50.2s | 107s / 67.3s |
| unit-4 job / pytest | 161s / 125.1s | 89s / 59.8s |
| integration-heavy job / pytest | 79s / 44.4s | 87s / 50.8s |
| cost-guards job / pytest | 151s / 113.4s | **143s / 107.9s** |
| 峰值并发 | 13 | 13 |

- **关键路径口径**：与本仓库无 smoke 的基线 run `41793803081`（Python span 175s、墙钟 178s）相比，若本 PR 也不触发 Windows Smoke，墙钟应约 **148–180s**（视 `cost-guards` 抢 runner 的排队而定；见下条第二样本）。
- 新关键路径是 `cost-guards`：3 个 cost 基准文件本身 107.9s，加上环境准备约 35s = 143s。unit 分片已全部回落到 89–107s，不再是瓶颈。
- **不要把本 PR 的原始墙钟（242s）当作提速依据**：只要 PR 改动 `.github/workflows/*`，`Detect packaging-surface changes` 就会触发 Windows Portable Smoke（本次 230s），墙钟由 smoke 支配。可比的只有「Python 门禁关键路径」。
- 第二个样本 run [`41813339091`](https://github.com/ROM4n2/DeLector/actions/runs/41813339091)（head `6967ded`，success）给出波动区间：原始墙钟 228s（smoke 210s），Python span **177s** —— 该样本 `cost-guards` 抢 runner 排队晚 20s 才起步（10:19:18 对其它 10:18:58），其自身 157s / pytest 118.9s 未变；unit-4 pytest 80s 是本样本最慢 unit 段。结论：**分片重配平把 unit 分片从 155.6s 压到 55–80s，但 cost-guards 已成为唯一瓶颈，span 在 145–177s 间由排队抖动决定**，不是重配平回归。
- 已放弃的两条杠杆（不要重试）：
  - `pytest-xdist`：cost 用例本身就是计时/基准断言，并行 worker 会直接污染结果；integration-heavy 会起真实服务与端口，并行化不稳。分片已经用 6 个 runner 并行，xdist 只会把「计时门禁」变成 flaky 源。
  - 把 cost 基准文件摊到 unit 分片：能让 6 个 job 更平，但会把计时门禁混进普通测试进程，牺牲专项分片的隔离语义；本轮按约束不碰真实检查。

### 1.5 cost-guards 拆分与前端探针去重（2026-11-05，PR #216）

实施（`docs/plans/2026-11-05-ci-cost-guards-split.md`）：

- cost 专项分片拆成两个**各自只含 cost 文件**的分片：`cost-guards`（articles + cards）、
  `cost-cold-start`（cold_start），各自独立 runner、无 xdist、不与普通测试共享进程；
  并集仍恰好覆盖 3 个 cost 文件（守卫钉住）。
- 4 条前端探针（routes / index 同步 / 分层 / tsc）从 6 个分片去重到 `unit-2`；
  Node 安装仍留在公共 steps（根 `conftest.py::pytest_sessionstart` 在 CI 下要求每个
  pytest job 都有 node）。
- silent / mock / layer 三个秒级 stdlib 闸合并为 `static-invariants` 一个 job（三个
  判定器仍逐步执行、无 `continue-on-error`、`timeout-minutes: 2`），用于抵消拆分新增
  的 1 个 job。
- **所有成本断言、轮数、阈值零改动**。

样本口径：改后 = PR #216 run [`41871021385`](https://github.com/ROM4n2/DeLector/actions/runs/41871021385)
（head `fddc327`）的 attempt 1–3（同一 SHA、同一代码，重跑取波动）；改前 = 四个
pre-change PR run（`41811788954` / `41813339091` / `41852745136` / `41851476946`）。

| 指标 | 改前 PR（4 样本） | 改后 PR #216（3 attempts） |
| --- | --- | --- |
| Python 门禁关键路径（最早 job → 最晚 pytest job） | 143 / 177 / 158 / 159，中位 **158s**，区间 143–177 | 107 / 117 / 108，中位 **108s**，区间 107–117 |
| `cost-guards` job | 143 / 157 / 157 / 159，中位 **157s** | 88 / 93 / 95，中位 **93s** |
| `cost-cold-start` job | — | 57 / 70 / 63，中位 **63s** |
| cost pytest（单 job 内） | 83s（`41864029091` 实测；旧样本 107.9 / 118.9s） | **64s**（cost-guards）+ **28s**（cold），取 max **64s** |
| 墙钟（run 创建 → 更新） | 203 / 228 / 239 / 242，中位 **233.5s** | 238 / 240 / 265，中位 **240s** |
| runner 累计（所有 job 时长求和） | 962 / 973 / 978 / 1014，中位 **975.5s** | 941 / 1002 / 1014，中位 **1002s** |
| 峰值并发 | 12–13 | **12** |

结论（口径分离，不混写）：

- **关键路径有真实收益**：Python span 中位 **158s → 108s（-50s，-32%）**；
  `cost-guards` 从 143–159s 降到 88–95s，**已不是瓶颈**。新关键路径变成 unit 分片
  （`unit-4` 107s、`unit-1` 116s 的波动样本），受 unit 分片自身 77–116s 波动限制。
- **墙钟无语义**：所有样本都触发 Windows Portable Smoke（223–252s），墙钟由 smoke 支配，
  不能把 233.5s → 240s 读成「变慢」，也不能读成「变快」。
- **runner 累计略升**：中位 975.5s → 1002s（**+26s，+2.7%**）。原因：cost 环境准备
  （checkout + setup-python + 依赖安装 ≈ 24s）被复制成两份；前端探针 6→1 与三个机械闸
  合并只抵消了一部分。**这是本轮明确接受的代价**，不为压缩累计值牺牲计时隔离。
- **峰值并发 12 ≤ 13**：拆分 +1 由三闸合并 -2 抵消。
- 未采用且不要重走：把 cost 文件摊进 unit 分片（计时断言与无关测试共享进程）、
  `pytest-xdist`（并行污染计时）、减少轮数/放宽阈值（删除或弱化真实检查）。

## 2. 可判定预算

| 项目 | 预算 | 实测依据与策略 |
| --- | --- | --- |
| Python matrix 单 job | **timeout-minutes: 8** | 当前最长 229s，约 2.1 倍余量；不得回到默认 360 分钟 |
| Go / Go↔Python integration 单 job | **timeout-minutes: 5** | 当前 39s/48s，保留环境波动余量；integration 不得再设 20 分钟 |
| 轻量机械闸单 job | **timeout-minutes: 2** | 当前 5–8s；异常挂死必须尽快暴露 |
| 整体墙钟 | **≤8 分钟（含排队）** | 当前 278s，约 1.7 倍余量；超预算先查重复与关键路径，不得先删检查 |
| 峰值并发 | **≤13 个执行 job** | 与当前峰值一致；新增执行面不得靠继续加 job 扩张 |
| Windows Portable Smoke | **Verify 步骤 timeout-minutes: 10；job 级 30 保留为护栏** | 正常实测 27s，脚本内最坏路径约 6 分钟，10 分钟约为最坏路径的 1.7 倍（判据，非护栏）；30 分钟卡死根因未定位，证据边界见 TODO-CI-02 |
| 超时策略 | **每个可执行 job 显式 timeout，超时即失败** | 禁止挂半小时；只允许路径检测类步骤按既有设计 fail-open，测试/契约/安全闸不得 `continue-on-error` |
| 同 ref 并发 | **保留 concurrency cancel-in-progress** | 新 push 取消旧 run，避免无效排队与重复 runner 成本 |

## 3. 禁止事项

1. 同一测试套件或用例集合在多个 job 重复执行；分片必须可证明互斥且完整。
2. 为凑覆盖率把全量 pytest 塞进每个 job；全量本地串行验证与 CI 分片是两种口径，不得混用。
3. 只为一个断言或一个字符串存在性检查单开 job；应并入现有机械闸。
4. 无缓存的全量依赖安装。新增 Python/Go 依赖面必须复用既有 cache key/锁文件口径，缓存 miss 必须能在日志中说明原因。
5. 为提速删除真实测试、降低探针场景、跳过 Node/Go、放宽契约或把失败改成警告。
6. 新增 job 不写 `timeout-minutes`，或让 job 依赖 GitHub 默认 360 分钟。

## 4. 新增 job 的门槛

新增 job 前必须在 PR 描述中同时给出：

1. **独特拦截面**：它能拦住哪个现有闸拦不住的问题，附失败反例；不能只换一层目录或只查一个断言。
2. **实测成本**：至少一次真实运行的时长、依赖安装与缓存命中证据。
3. **预算归属**：加入后单 job、整体墙钟与峰值并发仍满足本文；超预算时必须二选一：
   - 合并进现有 job；
   - 改成已有 job 的一个 step。
4. 若只是重复安装/重复跑同一检查，不得新增；应先去重。

## 5. 浪费登记与待办

### TODO-CI-01（已完成，PR #210）：Ruff/mypy 六份静态检查去重

- 将六个 matrix 公共的 Ruff/mypy 安装与执行收敛为**现有 job 中的一份**，六个 pytest 分片仍各跑原用例，检查数量不得减少。
- 实测重复成本 **89s**；保留单份约 **15s**，预计可省 **约 74s 累计 runner 时间**。
- **墙钟不得写成必省 74s**：若静态检查留在当前关键路径 `unit-1`，其它分片去重不会缩短总墙钟；若移到较短既有 job 且不引入新依赖，按本样本理论上限约 **19s**，实施后必须重测。
- 实施（2026-11-04）：六步加 `if: matrix.suite.name == 'unit-2'`，宿主是最短分片；`tests/test_ci_hardening.py` 新增去重守卫（三处变异实测 RED 后还原复绿）。
- 实测结果见 §1.3：累计 **92s → 14s**，墙钟**未下降**（样本波动大于收益）。

### TODO-CI-02（部分完成，2026-11-04）：Windows Smoke 步骤级判据与分段实测

- **已落地**：`Verify Windows Portable（真启闸）` 步骤加 `timeout-minutes: 10`；job 级 `timeout-minutes: 30` 保留为兜底护栏（步骤级是判据，job 级是护栏，二者并存）。判据依据：正常实测 **27s**、脚本内最坏路径约 **6 分钟**（两次真启 × (120s 健康 + 10s 终止 + 10s 端口 + 15s 硬杀) + 清理），10 分钟约为最坏路径的 **1.7 倍**，不是护栏式宽值。
- **证据边界（不得写软）**：2026-11-04 run 41833602180 attempt 1 卡在 Verify 步骤 30 分钟被取消，**该 job 日志已不可得**——GitHub 未保留、API 返回 404，attempt 1 的日志包只含其余 13 个 job。因此**根因仍未定位**：现有判定为 **hang**，**置信度约 0.6**，最可能是 **runner/job worker 层停摆**（脚本内所有等待均有硬上限、最坏约 6 分钟；同一 SHA 重跑 27 秒即通过）。本次改动只把"静默卡死 30 分钟"变成"快速失败并保留步骤级定位线索"，**不是对该卡死的修复**，不得表述为"已解决卡死问题"。
- **仍待做的收窄手段**：
  - **B（心跳/阶段标记，待做）**：脚本按阶段打印 elapsed 与相位名。理由：**被取消的 job 日志可能整份丢失**（本次即如此），心跳是唯一还能留下的证据。
  - **C（拆步骤，待做）**：把完整性检查、标准真启、无控制台真启拆成独立 step，各自设预算，让 step 时间线本身就能定位卡在哪一相位。
  - **分段实测（待做）**：下次真实触发时记录构建、启动、验包分段耗时，再评估 job 级 30 分钟是否继续收敛。
- 不得为凑新预算删掉 Windows 真启验包。

### TODO-CI-03（已完成，PR #211）：分片互斥失效修复与关键路径配平

- 根因：bash 先展开 glob，pytest `--ignore` 对显式文件无效 ⇒ 一次 run 重复执行 356 个用例，unit-1 被顶成 155.6s 的关键路径。
- 实施：`tools/ci_shards.py` 显式清单 + `tools/ci_shard_weights.json` 权重；matrix 去掉 `args`；守卫钉住分区/独占/配平/禁止回退。
- 实测（§1.4）：Python 门禁关键路径 **188s → 145s**（-43s），峰值并发仍为 13；unit-1 pytest 155.6s → 55.7s。

### TODO-CI-04（已完成，PR #216）：`cost-guards` 是新关键路径（约 143s）

- 问题：3 个 cost 基准文件本身 107.9s（CI），环境准备约 35s，加 4 条前端探针 5s；unit 分片已全部 ≤107s。
- 实施（2026-11-05，计划见 `docs/plans/2026-11-05-ci-cost-guards-split.md`）：
  - cost 分片拆成 `cost-guards`（articles + cards）与 `cost-cold-start`（cold_start），
    两个分片各自只含 cost 文件、独立 runner、无 xdist；
  - 4 条前端探针从 6 个分片去重到 `unit-2`（Node 安装保留，根 conftest 要求）；
  - silent / mock / layer 三闸合并为 `static-invariants`（抵消新增 job，峰值并发 12）。
- 实测（§1.5）：Python 门禁关键路径中位 **158s → 108s（-50s，-32%）**；
  `cost-guards` 中位 157s → 93s，**已不是瓶颈**；新关键路径是 unit 分片（107–117s）。
  runner 累计中位 +26s（+2.7%，cost 环境复制两份的代价）；墙钟由 smoke 支配，不单独下结论。
- 守卫：`tests/test_ci_hardening.py` 钉住两分片并集、前端探针单一宿主、合并闸三步接线；
  三处具名变异（并回 cost 分片 / 去掉一条探针 `if` / 删一个判定器）实测 RED。
- 仍未解决：unit 分片自身 77–116s 的波动成为新关键路径上限；本轮不动 unit 用例集合。
- 不得为压关键路径删除成本断言、放宽阈值或把 cost 门禁改成警告。

### 明确不列为浪费的项

- 六个独立 runner 的 Python 依赖安装：当前 pip cache 命中，且 job 隔离真实存在；优先复用缓存，不做高风险环境共享。
- pytest 分片、Go race、Go↔Python integration：各自拦截面不同，不是重复套件。

## 6. 复核方法

每次调整 CI 前后，至少记录同一类 run 的以下数据：

```bash
gh run view <run-id> --json jobs,startedAt,updatedAt,createdAt,conclusion,status,headSha,event
gh run view --job <job-id> --log
```

比较：逐 job 时长、最长关键路径、run 创建到结束墙钟、峰值并发、重复步骤累计时长、缓存命中日志。缺少这些数据不得声称“CI 变快了”。
