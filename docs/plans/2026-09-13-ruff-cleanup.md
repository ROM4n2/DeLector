# Ruff 静态工具链清账与 CI 门禁接入 Implementation Plan

> **Goal**: 补齐 CI Hardening 显式登记的已知边界——为全仓 Python 代码（96 文件）引入 Ruff lint 清账（2265 → 0 告警）并接入 PR/push 门禁；`ruff format` 全量统一格式（独立成笔可回滚）；Mypy 严格模式递延另立计划。
> **Tech Stack**: Ruff 0.16.7（开发期工具，不进 requirements.txt）/ pytest（回归门禁，基线 715+1 不回退）/ GitHub Actions（ci.yml PR/push master）
> **Spec Reference**: Vault `PYTHON-STANDARDS` §8.1（Ruff 全面采用、零告警 MUST；Mypy 严格模式 MUST——本期递延）/ `AUTOMATION-GOTCHAS` §5（反冻结集合断言）；上游计划 `docs/plans/2026-09-09-ci-hardening.md`（本计划即其"已知边界"的落地）
> **Global Constraints**:
> - **ruff 不进 `requirements.txt`**（开发期工具；混入运行时依赖会增大 Android 打包面体积与漂移面）——CI 内单独 `pip install ruff`。
> - **E402 一律 `# noqa`，禁止重排 import**：`delector/server.py` 的"`load_env()` 之后才 import"是刻意设计（env 必须先载入，红线 9 生态）；tests 的"先设 env 再 import"同理（曾因重排导致整批跑红 `no such table`）。
> - **零行为改动**：只修告警与格式；不改函数签名/公开名字/路由/SQL/断言语义；发现的真 bug 仅在报告中登记。
> - **format 独立成笔 commit**（巨量纯格式 diff，可整体 revert 而不丢清账成果）；format 后必须全量回归。
> - 分批清账、每批原子 commit；CPE 实现 + 主线程复核/提交；收尾开 PR（**PR CI 首次真跑 ruff 门禁**）。

---

### Task 1: 基线探测与 `ruff.toml` 定稿 [Builder]
**要点**: 安装 ruff → `ruff check --statistics .` 归档存量 → 据分布定规则集/行宽/豁免。
**证据**: 基线 E/F/I 共 **2265 告警**（E501 **2113**，占 93%；I001 91 / F401 15 / E701·E702 各 11 / E741 10 / E401 7 / E402 6 / E731 1）；行宽 P50=43 / P90=74 / P95=86 / P99=139，>120 的 553 行中 **429 行（78%）集中在 `delector/data/`** 纯数据字典 → 文件：行宽取 120 + data/ 豁免 E501（配置生效后 287 告警）。

### Task 2: 清账 `delector/` [CPE + 主线程分批提交]
**要点**: `--fix` 自动修（I001/F401/E401）+ 手工清（E501 拆行 / E701·E702 拆多行 / E741 重命名 / E731 改 def），E402 加 noqa 保留 `load_env` 时序。
**证据**: 23 文件、523/235 行；`ruff check delector/` All checks passed；`tests/test_server.py` 227 passed + 1 skipped（门面契约）；全量 0 FAILED。

### Task 3: 清账 `tests/` + `tools/` + 根脚本 + `agent/scripts/package_agent.py` [CPE + 主线程]
**要点**: 同 T2 纪律；tests 的 E402 一律 noqa；F401 删前确认非 `__all__`/非跨模块引用。
**证据**: 36 文件、337/166 行；全仓 `ruff check .` 一度仅剩 `agent/scripts/package_agent.py:369` E741（T2/T3 范围外，主线程补修）→ 零告警；全量 717 passed + 1 skipped。

### Task 4: `ruff format` 全量 [主线程]
**要点**: 预览规模（106 文件待格式化 / 72 已合规，diff ~3.2 万行）→ 执行 → 复检 lint → 全量回归。
**证据**: `106 files reformatted`；`ruff check .` 仍 All checks passed；全量 **0 FAILED**（读源码断言特征串的审计测试全部幸免）；独立成笔 commit（`2a5fee4`）。

### Task 5: CI 门禁 + 守卫测试 [TDD Builder]
**要点**: 先扩 `tests/test_ci_hardening.py` 两条（ruff 步骤契约 / ruff.toml 规则集与豁免面 + ruff 不进 requirements）→ RED → ci.yml 插入 `pip install ruff` + `ruff check .`（放在 spaCy 下载与全量测试之前，秒级快速失败）→ GREEN。
**证据**: RED（1 failed）→ GREEN（5 passed）；本地 `ruff check .` 零告警。

### Task 6: 收官 [Verifier]
**要点**: 全量门禁 + OVERVIEW/work.log 回填 + 开 PR（PR CI 首次真跑 ruff 步骤）。

---

## 执行状态（2026-09-13 收官）

- 状态：**DONE**
- 逐 Task commit：T1 `deacdc5`（ruff.toml + 基线）→ T2 六笔（`067da33` core → `c2ce28f` routes → `90bf679` services → `433bcc8` nlp_engine → `3d97c6f` data → `9e3e041` server）→ T3 四笔（`ea0cfb9` tests → `4786f60` tools → `c5369d6` 根脚本 → `6c9d592` package_agent）→ T4 `2a5fee4`（format 全量）→ T5 `276fc0d`（CI 门禁 + 守卫）→ T6 本笔（状态回填 + PR）。
- 门禁证据：`ruff check .` **All checks passed**（起点 2265 → 0）；全量 pytest **717 passed + 1 skipped**（基线不回退，format 后 0 FAILED）；`tests/test_ci_hardening.py` 5 passed。
- **偏差与决策记录**：
  1. `line-length = 120` + `delector/data/*.py` 豁免 E501：若不豁免需改 429 行纯数据（伤可读性与 diff 稳定性）；豁免面**限定在 data/ 目录**（不扩大），守卫测试钉死该声明。
  2. `delector/server.py` 的分节 import 顺序是刻意设计（`load_env()` 先于 import，红线 9 生态）；自动修曾打乱顺序，已完整还原并逐处 `# noqa: E402`，另加注释说明——**禁止再重排**。
  3. `agent/scripts/package_agent.py` 落 T2/T3 范围之外，由主线程补修 1 处 E741。
  4. `tests/test_encounter_addcard.py` 的 E501 位于 JS 探针字符串内，无法加 noqa（会污染探针字节）→ 拆分 JS 源码语句（语义不变，全量回归验证）。
  5. E401 全部由 `--fix` 自动处理（计划曾列为手工项）。
- 已知边界（不进本轮）：**Mypy 严格模式**递延（存量类型债规模大于 lint，需独立计划）；`ruff format` 未纳入 CI 门禁（只 gate `check`，避免新提交因格式细节卡住——如需可后续加 `ruff format --check`）。
