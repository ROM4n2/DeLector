# Mypy 类型检查清账与 CI 门禁接入 Implementation Plan

> **Goal**: 继 Ruff（PR #41）之后补齐静态质量工具链的最后一块——为全仓 Python 代码（98 源文件）接入 Mypy 并清账至零错误，接入 PR/push 门禁；`strict` 全量类型注解另立计划（递延）。
> **Tech Stack**: Mypy 2.3.1（开发期工具，**不进 requirements.txt**）/ pytest（基线 751+1 不回退）/ GitHub Actions
> **Spec Reference**: Vault `PYTHON-STANDARDS` §8.1（Type Checker MUST 过 Mypy 严格模式——**本计划为渐进路径的第一阶段**）/ 上游：`docs/plans/2026-09-13-ruff-cleanup.md`（同型工程债，已收官）
> **Global Constraints**:
> - **禁止裸 `# type: ignore`**：每处豁免必须带错误码 + 理由注释（`# type: ignore[attr-defined]  # 理由`）；`--warn-unused-ignores` 开启后多余的 ignore 也会报错，形成自净。
> - **每处告警要么真修、要么带理由豁免**——清账不得变成"到处 ignore"（掩耳盗铃）。
> - 类型注解层改动**不得改变运行时行为**；若某处必须动行为（如 `cast`/显式默认值），在 commit body 说明并由全量 pytest 兜底。
> - **mypy 不进 `requirements.txt`**（开发期工具；Android 打包面只装运行时依赖）——CI 内单独 `pip install mypy`。
> - 分批清账、每批原子 commit；CPE 实现 + 主线程复核/提交；PR CI 真验证。

---

## 配置档位决策（本计划核心决策）

实测三档规模（`--ignore-missing-imports`，spaCy 等第三方无 stub 故必须忽略缺失导入）：

| 档位 | delector/ | 全仓（98 文件） | 评价 |
|---|---|---|---|
| 默认（不检查未注解函数体） | 39 errors / 8 files | 54 errors / 12 files | 太松：未注解函数体完全不检查，抓到的问题少 |
| **适度严格（采用）** | 47 errors / 9 files | **139 errors / 31 files** | ✅ 检查未注解函数体（catch 真实 bug）+ 4 个高价值 flag，规模可控 |
| `--strict` | 250 errors / 25 files | 预计 >600 | ❌ 主体是 `no-untyped-def`（要给 ~200 处函数补注解），收益递减，**递延另立** |

**采用档位**（`mypy.ini`）：
```ini
[mypy]
python_version = 3.11
ignore_missing_imports = True        # spaCy 等第三方无 stub
check_untyped_defs = True            # 关键：未注解函数体也检查（默认档抓不到的那部分）
no_implicit_optional = True
warn_unused_ignores = True           # 自净：多余的 ignore 会报错
warn_redundant_casts = True
exclude = (\.venv|dist|build|android|scratch|tools/raw)
```

**基线分布**（适度严格档，全仓 139）：`tests/` **76** · `delector/` **51** · `tools/` **16**；
错误码（delector 口径）：`attr-defined` 21 / `assignment` 7 / `misc` 5 / `var-annotated` 4 / `index` 4 / `arg-type` 3 / `union-attr` 2 / `call-arg` 1。

---

### Task 1: `mypy.ini` 落地 + 基线归档 [Builder]
**要点**: 按上表建配置（含决策依据注释）；跑基线并归档分布进本计划执行状态块。
**验证**: `python -m mypy delector/ tests/ tools/ conftest.py start.py package_windows.py` 输出与基线一致。

### Task 2: 清账 `delector/` [CPE + 主线程分批提交]
**要点**: 按子包分批（core → routes → services → nlp_engine → data/server）；每处：真修优先（补局部注解/修正类型/收窄 `Optional`），确需豁免则带错误码与理由。
**特别关注**: `attr-defined` 21 处——若揭示**真实 bug**（如访问了不存在的属性），就地报告并最小修复 + 加测试说明；不得借机重构。

### Task 3: 清账 `tests/` + `tools/` + 根脚本 [CPE + 主线程]
**要点**: tests 是最大面（76 处）；常见形态是 `**kwargs`/动态属性/`TestClient` 泛型——优先补注解，其次带理由豁免。tools 为独立脚本，改动风险低。
**纪律**: 不得改断言语义与 fixture 行为；类型注解仅补不改逻辑。

### Task 4: CI 门禁 + 守卫测试 [TDD Builder]
**要点**: 先扩 `tests/test_ci_hardening.py`（mypy 步骤契约 + `mypy.ini` 关键配置项逐条钉死 + `mypy` 不进 requirements）→ RED → `ci.yml` 插入 `pip install mypy` + `mypy ...`（放在 ruff 之后、pytest 之前）→ GREEN。
**验证**: 守卫先红后绿；本地 `python -m mypy ...` 零错误。

### Task 5: 收官 [Verifier]
**要点**: 全量门禁（pytest 751+1 不回退 / `ruff check .` 零告警 / Go 三门禁不受影响）+ OVERVIEW/work.log 回填 + 开 PR（**PR CI 首次真跑 mypy**）。

---

## 执行状态（收官时回填）

- 状态：**PENDING**
- 已知边界（不进本轮）：
  - **`--strict` 全量**（~250+ 错误，主体是 `no-untyped-def`：需为约 200 处函数补参数与返回注解）——另立计划；可选路径是**按模块渐进 strict**（从 `delector/core` 开始），但需先有本阶段的零错误基线。
  - 第三方 stub 治理（spaCy 无 stub，依赖 `ignore_missing_imports`；如需精确类型可后续引入 `types-*` 或局部 stub）。
