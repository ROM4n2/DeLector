# 2026-11-05 CI 关键路径：cost-guards 拆分与前端探针去重

> 目标文档：`docs/agents/ci-speed-budget.md` §5 TODO-CI-04。
> 本文只处理「cost-guards 成为唯一关键路径」这一件事，不改任何成本断言的
> 规模、轮数或阈值。

## 1. 目标与基线

- **目标**：缩短 Python 门禁关键路径（最早 pytest job 起步 → 最晚 pytest job 结束），
  且不删除/弱化任何真实检查。
- **基线**（push，run [`41864029091`](https://github.com/ROM4n2/DeLector/actions/runs/41864029091)，
  head `7c345bf`）：
  - `cost-guards` job **126s** = 环境 35s（setup/checkout 15s + 依赖 17s + spaCy 2s + 其余 1s）
    + 4 条前端探针 5s + pytest 83s + 收尾 3s；其余分片 77–99s。
  - 历史两个样本：`41811788954` cost-guards 143s（pytest 107.9s）、`41813339091` 157s
    （pytest 118.9s，排队晚 20s 起步）。
- **约束**（来自任务书）：
  - 不用 `pytest-xdist`（cost 用例是计时/基准断言，并行 worker 污染结果）；
  - 不把 cost 文件摊进 unit 分片（计时门禁会与普通测试混在同一进程）；
  - 任何并行/分片/预热方案都不能让基准断言在共享资源抖动下随机红；
  - 关键路径没变快就如实写「无收益」。

## 2. 候选方案对比

| # | 方案 | 证据类型 | 预期收益 | 风险 | 结论 |
| --- | --- | --- | --- | --- | --- |
| A | **拆分 cost 分片为两个专项分片**：`cost-guards`（articles + cards）、`cost-cold-start`（cold_start），两个独立 runner | cost 文件自身是结构性/比值断言（`test_cold_start_cost.py` 明确拒绝绝对毫秒；`test_cards_endpoint_cost.py` 用 `per_row_us` 比值、留 3.2× 余量）；CI 实跑 job 时长 | 关键路径 pytest 83s → 约 45–50s；job 约 126s → 约 85s | 新增 1 个 job（峰值并发 14 > 预算 13）；专项分片语义要由守卫重新钉住 | **采纳**，用 C 抵消并发 |
| B | **4 条前端探针从 6 个分片去重到 1 份**（与 TODO-CI-01 同款） | CI step 时间戳（cost-guards 4 条合计 5s）；6 份累计 30s | `cost-guards` 减 5s；runner 累计约 -25s | Node 安装**不能**一起去重：`conftest.py::pytest_sessionstart` 在 CI 下对每个 pytest job 都要求 node 存在 | **采纳**（仅去重 4 条探针，Node 保留） |
| C | **把 3 个纯 stdlib 机械闸 job 合并为 1 个 job**（silent / mock / layer） | 各 job 7–8s；§3.3 明确要求单断言闸并入现有机械闸 | 省 2 个并发 job（抵消 A 的 +1，峰值 13→12）；runner 累计约 -20s | 失败定位从 job 级降到 step 级；无 continue-on-error 时必须逐步红 | **采纳** |
| D | **什么都不做**（对照） | 同上基线 | 0 | `cost-guards` 仍是唯一关键路径（126–157s） | **否决**（本任务就是处置该待办） |
| E | 拆分 cost 文件到 2 个**既有** unit job | — | 相近 | 计时断言与无关测试共享同一进程/缓存/磁盘，**会随机红** | **排除**（任务书明令） |
| F | `pytest-xdist` / 预热 worker | — | — | 并行污染计时 | **排除**（既有结论） |
| G | 减少轮数 / 放宽阈值 / 把 cost 闸降级 | — | 大 | 删除或弱化真实检查 | **排除**（需用户授权，不在本轮） |

**计时语义保护**：A 的两个分片各自只含 cost 文件，仍是独立 runner、独立 pytest 进程，
无 xdist、无无关测试混跑；拆分后 cold_start 单独跑，其断言只依赖正数与结构性不等式
（见文件头 `Flaky-Aware` 声明），不依赖与另外两个文件同进程的预热状态。

## 3. 验收判据

1. 全部 `tests/test_*.py` 恰好被一个分片收录（既有守卫）。
2. 两个 cost 分片的**并集**恰好等于 3 个 cost 文件，且每个分片只含 cost 文件；
   unit 分片与 cost 分片零交集。
3. 4 条前端探针在每个分片「最多且恰好一次」执行：全部挂同一个 `if:
   matrix.suite.name == '<host>'`，host 真实存在于 matrix 且不是 cost 分片。
4. 合并后的机械闸 job 仍逐步运行 3 个判定器，且无 `continue-on-error`、
   `timeout-minutes ≤ 2`（轻量闸预算）。
5. 峰值并发执行 job ≤ 13（A 的 +1 由 C 的 -2 抵消）。
6. CI 实测：PR 与 push 各 ≥3 个样本，分别报墙钟 / 关键路径跨度 / runner 累计；
   若关键路径未缩短，写明「无收益」。

## 4. 依赖顺序

1. 先在 `tests/test_ci_hardening.py` 写/改守卫（RED），跑单测确认变红。
2. 再改 `tools/ci_shards.py` + `.github/workflows/ci.yml`（GREEN），跑守卫确认转绿。
3. 具名变异：把 cost 文件塞回 unit 分片 / 去掉前端探针 `if` / 从合并 job 删一个判定器，
   三次都必须让指定断言变红，然后还原。
4. 更新 `docs/agents/ci-speed-budget.md` §5（TODO-CI-04 状态与实测口径）。
5. 开 PR（不合并），取 ≥3 个 PR 样本与 ≥3 个 push 基线样本。

## 5. 执行分级

- **Tier 2（Maker-Checker）**：改动触及 CI 定义文件，按 `dfs-exec` 硬升级规则必须
  ≥ Tier 2。
- **Maker**：主线程（TDD 实现）；**Checker**：独立 reviewer subagent（对抗式审查，
  只给 Red/Yellow 卡，不直接改码）。
- **红测/绿测证据**：命令退出码 + 断言原文；变异在父树重放并引用失败断言。
