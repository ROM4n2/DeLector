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

## 2. 可判定预算

| 项目 | 预算 | 实测依据与策略 |
| --- | --- | --- |
| Python matrix 单 job | **timeout-minutes: 8** | 当前最长 229s，约 2.1 倍余量；不得回到默认 360 分钟 |
| Go / Go↔Python integration 单 job | **timeout-minutes: 5** | 当前 39s/48s，保留环境波动余量；integration 不得再设 20 分钟 |
| 轻量机械闸单 job | **timeout-minutes: 2** | 当前 5–8s；异常挂死必须尽快暴露 |
| 整体墙钟 | **≤8 分钟（含排队）** | 当前 278s，约 1.7 倍余量；超预算先查重复与关键路径，不得先删检查 |
| 峰值并发 | **≤13 个执行 job** | 与当前峰值一致；新增执行面不得靠继续加 job 扩张 |
| Windows Portable Smoke | **触发前单独实测；目标 ≤15 分钟** | 本样本 skipped，无有效时长；现行 30 分钟上限登记为待整改项，本轮不改结构 |
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

## 5. 浪费登记与待办（TODO-CI-01 已实施）

### TODO-CI-01（已完成，PR #210）：Ruff/mypy 六份静态检查去重

- 将六个 matrix 公共的 Ruff/mypy 安装与执行收敛为**现有 job 中的一份**，六个 pytest 分片仍各跑原用例，检查数量不得减少。
- 实测重复成本 **89s**；保留单份约 **15s**，预计可省 **约 74s 累计 runner 时间**。
- **墙钟不得写成必省 74s**：若静态检查留在当前关键路径 `unit-1`，其它分片去重不会缩短总墙钟；若移到较短既有 job 且不引入新依赖，按本样本理论上限约 **19s**，实施后必须重测。
- 实施（2026-11-04）：六步加 `if: matrix.suite.name == 'unit-2'`，宿主是最短分片；`tests/test_ci_hardening.py` 新增去重守卫（三处变异实测 RED 后还原复绿）。
- 实测结果见 §1.3：累计 **92s → 14s**，墙钟**未下降**（样本波动大于收益）。

### TODO-CI-02：Windows Smoke 实测后收紧上限

- 当前样本为 skipped，缺实测；下次触发时先记录构建、启动与验包分段耗时，再把 30 分钟上限收敛到实测可支撑的 ≤15 分钟或提出书面例外。
- 不得为凑新预算删掉 Windows 真启验包。

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
