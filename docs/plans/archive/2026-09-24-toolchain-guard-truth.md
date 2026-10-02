# 工具链守卫收口（假门变真门）实施计划

> **Goal**: 把两处「在跑但判别力是假的」门禁修成真门 —— ① 路由守卫测试从「端点函数对象身份」比对改为「`(prefix+path, methods)`」比对，从而解除 fastapi/starlette 升级禁区；② 修掉 `pyproject.toml` 里 `exclude` 的裸子串 `build`，让 `mypy --strict delector tools` 真覆盖 `tools/` 全部 11 个文件（并清账 47 个存量注解错误）。
> **Tech Stack**: Python 3.10+（pytest / mypy --strict / fastapi+starlette）/ 无新增运行时依赖（新依赖验证在隔离环境内）
> **Spec Reference**: `docs/specs/2026-09-24-toolchain-guard-truth-design.md`
> **Global Constraints**:
> - **零业务行为改动**：A 只换比对键；B **只补类型注解**（若发现真实缺陷 → 立即报告，不擅自改行为）
> - **不改 `delector/` 任何代码**
> - **不引入运行时新依赖**：A 的升版验证走隔离环境（`pip install --target` 或 venv），**不得**直接 `pip install -U` 本机或改 `requirements.txt`，除非新环境下**全量 pytest 绿**（此时才允许升级 pin + 撤 `ignore`）
> - **本机 pin 保护**：任何步骤后 `python -c "import fastapi, starlette; print(fastapi.__version__, starlette.__version__)"` 必须仍是 `0.136.3 1.6.0`（隔离环境失败即回滚）
> - **既有守卫不得回归**：`tests/test_ci_hardening.py`（含 pyproject / dependabot 断言）与 `tests/test_server.py` 全绿
> - **环境**：Windows / bash；Python 前 `export PYTHONIOENCODING=utf-8`；全量 pytest **分半跑**（`--ignore=tests/test_server.py` + 单跑 `tests/test_server.py`）
> - **纪律**：子代理**不 git add / commit / push / 切分支**（主线程统一执行）；每 Task 收尾跑 目标测试 → ruff → `mypy --strict delector tools` → 全 `tools/*.mjs` 零漂移

---

### Task 1: 路由守卫改造 + 双向验证 + 条件升级 [Role: TDD Builder]

**Files:**
- Modify: `tests/test_server.py`（仅 `test_register_routes_covers_every_module_in_routes_package` 的比对键）
- Modify（**条件触发**，仅当新依赖下全量绿）：`requirements.txt`、`.github/dependabot.yml`
- Modify（条件触发）：`docs/specs/2026-09-24-toolchain-guard-truth-design.md` §4「实测记录」回填

**Interfaces:**
- Consumes: `delector.routes.register_routes`、`fastapi.APIRouter.routes`（`route.path` / `route.methods`）、`router.prefix`
- Produces: 改造后的守卫测试；以及**一份取证结论**（新依赖环境下旧实现红 / 新实现绿 / 全量 pytest 结果 → 是否升级 pin 与撤 `ignore`）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 1: 路由守卫改造 + 双向验证 + 条件升级。
> Goal: 让 `test_register_routes_covers_every_module_in_routes_package` 不再依赖端点函数对象身份（改比 `(prefix+path, methods)`），从而对 starlette/fastapi 的上游语义漂移免疫；并以隔离环境取证决定是否解除 fastapi 升级禁区。
> Target Files: Modify `tests/test_server.py`（仅该用例的比对键）。
> TDD Steps:
> 1. 先读现状：`tests/test_server.py:4434-4469`。把 `registered = {r.endpoint for ...}` 改为 `registered = {(r.path, frozenset(getattr(r, "methods", ()) or ())) for r in probe.routes if hasattr(r, "path")}`；把 `if route.endpoint not in registered` 改为 `key = (router.prefix + route.path, frozenset(getattr(route, "methods", ()) or ()))` + `if key not in registered`，`missing` 仍拼 `f"{mod_info.name}:{key[0]}"`。同步更新该用例 docstring（说明"比对的是 HTTP 语义键而非对象身份，故对上游实现细节漂移免疫"）。
> 2. 当前 pin 下跑绿：`export PYTHONIOENCODING=utf-8 && python -m pytest tests/test_server.py -q -k register_routes` → 期望 1 passed。（若红，说明改造有误，先修改造。）
> 3. **判别力反证（必做）**：用 `cp` 备份 `delector/routes/__init__.py`，临时注释掉**一个**模块的 `include_router`（如 `listen`），再跑守卫 → **必红**，且断言消息里的 `missing` **只含该模块的路由**（记录原文）；`cp` 还原并确认守卫回绿。**禁止 `git checkout --`**。
> 4. **新依赖双向验证（隔离环境，不污染本机 pin）**：
>    `python -m pip install -q --target /tmp/tc_dep "fastapi==0.141.1" "starlette==1.6.0"`
>    先跑一次 `PYTHONPATH=/tmp/tc_dep python -c "import fastapi, starlette; print(fastapi.__version__, starlette.__version__)"` 确认拿到 0.141.1/1.6.0。
>    ① **旧实现**：`cp` 备份改后的测试文件 → 用 `cp` 把旧实现（对象身份版）临时写回 → `PYTHONPATH=/tmp/tc_dep python -m pytest tests/test_server.py -q -k register_routes` → 期望**红**（复现 '全量 missing' 现象，记录 missing 条数）；`cp` 还原改后版本。
>    ② **新实现**：`PYTHONPATH=/tmp/tc_dep python -m pytest tests/test_server.py -q -k register_routes` → 期望**绿**。
>    ③ 若 ①② 均成立，再跑 `PYTHONPATH=/tmp/tc_dep python -u -m pytest -q tests/test_server.py 2>&1 | tail -6` 与（可选）半 A 全量，评估**新依赖下是否有其它失败**。
>    ④ 最后确认本机 pin 未被污染：`python -c "import fastapi, starlette; print(fastapi.__version__, starlette.__version__)"` → 必须仍是 `0.136.3 1.6.0`（若被污染，立即 `pip install -q -r requirements.txt` 复原并报告）。
> 5. **条件分支（严格按取证结果，不要臆测）**：
>    - **若第 4 步 ③ 全绿** → 升级 `requirements.txt`（`fastapi==0.141.1`、`starlette==1.6.0`），并更新其顶部注释（把"必须 pin"改为"已在上游验收过的组合；升级须跑全量 pytest"口径，保留历史根因说明）；**撤销** `.github/dependabot.yml` 里 fastapi/starlette 的 `ignore` 块并更新其注释（说明禁区已解除、守卫已免疫）；跑 `python -m pytest tests/test_ci_hardening.py -q` 确认守卫不回归。
>    - **若第 4 步 ③ 有失败** → **不动** `requirements.txt` 与 `dependabot.yml`；把失败用例名 + 断言消息 + 你的判断（是否与 fastapi/starlette 相关）整理成清单，**回报编排者**（不要自己扩大范围去修）。
> 6. 回填取证结果到 `docs/specs/2026-09-24-toolchain-guard-truth-design.md` §4 的「实测记录」小节（隔离环境是否可用、旧/新实现结果、全量结果、是否升级）。
> 7. 门禁：`python -m pytest tests/test_server.py tests/test_ci_hardening.py -q` / `python -m ruff check .` / `python -m mypy --strict delector tools` / 全 `tools/*.mjs` 零漂移。
> Return: Summary with test execution evidence（含判别力反证的 missing 原文、隔离环境双向结果、本机 pin 复核）+ 是否升级 pin 的结论。"

**Step Breakdown:**
- [ ] **Step 1: 改造比对键**（`(prefix+path, methods)`）+ docstring 说明
- [ ] **Step 2: 当前 pin 下守卫绿**
- [ ] **Step 3: 判别力反证**（摘 include → 只列该模块；`cp` 还原）
- [ ] **Step 4: 隔离环境双向验证**（旧实现红 / 新实现绿 / 全量评估 / 本机 pin 复核）
- [ ] **Step 5: 条件分支**（全绿才升 pin + 撤 ignore；否则回报）
- [ ] **Step 6: 回填 spec 实测记录 + 收尾门禁**

---

### Task 2: mypy exclude 锚定 + 47 注解清账 [Role: TDD Builder]

**Files:**
- Modify: `pyproject.toml`（`[tool.mypy]` 的 `exclude` 正则 + 注释留证）
- Modify: `tools/build_prep.py` 及另 3 个被暴露的文件（**仅注解层**）
- Modify（如 `ci.yml` 门禁口径需同步）：`.github/workflows/ci.yml`

**Interfaces:**
- Consumes: 现有 `[tool.mypy]` 配置（`pyproject.toml`）
- Produces: `mypy --strict delector tools` 覆盖 **68** 文件且 **0 error**；`tools/` 全部 11 个 `.py` 纳入门禁

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 2: mypy exclude 锚定 + `tools/build_*.py` 注解清账。
> Goal: 修掉 `pyproject.toml` 里 `exclude` 的**裸子串 `build`**（它会静默吃掉 `tools/build_*.py`），并把这 6 个脚本的存量 strict 错误清到 0（**只补注解，零行为改动**）。
> Target Files: Modify `pyproject.toml`、Modify `tools/*.py`（被暴露的那 4 个）、（如需）`.github/workflows/ci.yml`。
> TDD Steps:
> 1. **先取证**：记录当前 `python -m mypy --strict delector tools 2>&1 | tail -2` 的输出（应为 `62 source files`）；再用**显式文件清单**（绕过 exclude）确认存量错误规模：
>    `python -m mypy --strict tools/build_a1_dict.py tools/build_dict.py tools/build_embedded_audio.py tools/build_prep.py tools/build_workbench_seed.py tools/gen_a1_fragments.py tools/gen_rich.py tools/make_icon.py tools/audit_official_vocab.py tools/vault-proactive-scan.py`
>    基线记录：`Found 47 errors in 4 files (checked 10 source files)`（若与 47 不一致，以你实测为准并记录）。
> 2. **改 exclude**：把 `exclude = '(\.venv|dist|build|android|scratch|tools/raw)'` 改为锚定路径段的写法 `exclude = '(\.venv|dist|android|scratch|tools/raw|(^|/)build(/|$))'`（保留原有的真实排除项），并在该行上方加注释说明：**裸子串 `build` 曾静默排除 `tools/build_*.py`（2026-09-24 修复），改回裸子串会让 6 个脚本再次脱离门禁**。
> 3. 跑 `python -m mypy --strict delector tools 2>&1 | tail -3` → 期望覆盖文件数变为 **68** 且暴露那 47 个错误（逐条分类：`[type-arg]` 裸 `set`/`dict`/`list` 缺参数、`[no-untyped-def]` 缺函数签名、其它）。
> 4. **清账**：逐文件补注解（`set` → `set[str]`、`dict` → `dict[str, Any]`、函数补参数与返回类型；必要时 `from typing import Any, Dict, List, Optional, Set, Tuple`）。**MUST NOT 改行为**：不得改逻辑、不得改默认值、不得改数据字面量；只允许加注解、加 typing import、必要时把裸泛型容器改为带参数形式。若发现某处需要改行为才能过 → **停下回报**。
> 5. 再跑 `python -m mypy --strict delector tools` → 期望 **`Success: no issues found in 68 source files`**；`python -m pytest tests/test_ci_hardening.py -q` 不回归。
> 6. **口径确认**：检查 `.github/workflows/ci.yml` 里 mypy 门禁的实际命令；若它不是 `mypy --strict delector tools`（例如是裸 `mypy`），确认它同样以**配置的 files/exclude 口径**运行、因此自动受益（若不然，同步修正并回报）。
> 7. **抽查防作弊**：从 `git diff` 里抽查至少 3 处改动，确认改动仅为注解层；并对 4 个文件各跑一次显式文件 `mypy --strict <file>` → 全 `Success`。
> 8. 门禁：`python -m pytest tests/test_ci_hardening.py tests/test_encounter_seed.py -q`（build_encounter_seed 相关）/ `python -m ruff check .` / `python -m mypy --strict delector tools` / 全 `tools/*.mjs` 零漂移。
> **变异验证（判别力）**：把 `exclude` 改回裸子串 `build` → 确认 `mypy --strict delector tools` **又变回 62 files 且 0 error**（即门禁重新失明）→ 证明本修复有判别力；再改回锚定写法。
> Return: Summary with 覆盖文件数前后对比（62 → 68）+ 47→0 的清账证据 + 变异验证结论 + 是否改动 ci.yml 的说明。"

**Step Breakdown:**
- [ ] **Step 1: 取证**（62 files; 显式清单 47 errors/4 files）
- [ ] **Step 2: 改 exclude 为锚定写法 + 留证注释**
- [ ] **Step 3: 确认暴露（68 files + 47 errors）**
- [ ] **Step 4: 逐文件补注解（零行为）→ 0 error**
- [ ] **Step 5: ci.yml 口径确认 + git diff 抽查防作弊**
- [ ] **Step 6: 变异验证（改回裸子串 → 62 files 失明）+ 收尾门禁**

---

## 范围外 (Out of Scope)

- 不改 `delector/` 任何代码；不改业务逻辑
- 不重写守卫测试的其它用例、不做"测试分层"重构
- 不引入运行时新依赖（新依赖只在隔离环境内验证；升 pin 是 T1 的条件分支）
- 不处理本次若暴露出的**其它** mypy/测试失败（T2 只负责被 exclude 掩盖的那 47 个；T1 若发现新依赖下其它失败，另立计划）
- 不做 `tools/` 脚本的行为重构（YAGNI）

## 验证基线 (Verification Baseline)

| 阶段 | 命令 | 期望 |
|---|---|---|
| T1 | `python -m pytest tests/test_server.py -q -k register_routes` | 1 passed（当前 pin） |
| T1 | 判别力反证（摘 include） | 守卫红且 missing **只列被摘模块** |
| T1 | 隔离环境（`PYTHONPATH=/tmp/tc_dep`） | 旧实现红 / 新实现绿；本机 pin 复核仍 `0.136.3 1.6.0` |
| T2 | `python -m mypy --strict delector tools` | **62 → 68 files**，47 errors → **0 error** |
| T2 | 变异（exclude 回裸子串） | 退回 62 files / 0 error（证明判别力） |
| 收官 | 分半跑 pytest | 基线 **1119 passed + 1 skipped**（v5.12.0）→ 视改动净增；2 条既有 `exam_trials` env 失败保留 |
| 收官 | `ruff check .` / 全 `tools/*.mjs` | 0 告警 / 零漂移 |

## 回滚 (Rollback)

- 逐 Task 原子提交（主线程执行），任一可 `git revert <sha>`。
- **A 的回滚**：守卫测试单文件改动 → revert 即恢复对象身份比对（会重新变得对上游漂移敏感，即退回旧状态）。若已升级 `requirements.txt` + 撤 `ignore`，一并 revert 两者（两者必须**同进同退**：只 revert 其一会导致"门禁敏感 + 依赖已升"的必红组合）。
- **B 的回滚**：`pyproject.toml` 的 exclude 一行 + `tools/*.py` 的纯注解改动 → revert 后门禁回到"62 files 失明"状态（功能不受影响，只是门禁又聋了）。

## 关联索引

- `docs/specs/2026-09-24-toolchain-guard-truth-design.md`
- `08-Projects/DeLector/POST-MORTEM-V5.4.0-FASTAPI-DEPENDENCY-DRIFT.md`
- `01-Rules/AUTOMATION-VERIFICATION-THREE-PROOFS.md`
- `docs/specs/2026-09-18-mypy-strict-annotation-sweep-design.md`（B 的前序工程）
- `.github/dependabot.yml`（A 条件分支的撤销面）
