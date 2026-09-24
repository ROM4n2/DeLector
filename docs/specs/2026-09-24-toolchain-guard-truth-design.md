# 工具链守卫收口：让两处「假门」变真门 设计

- **日期**：2026-09-24
- **状态**：设计已定，待 `/vault-plan` → `/vault-exec`
- **类别**：Architectural（两项工程债收口；不改任何业务行为）
- **前置**：
  - `08-Projects/DeLector/POST-MORTEM-V5.4.0-FASTAPI-DEPENDENCY-DRIFT.md`
  - Vault `01-Rules/AUTOMATION-VERIFICATION-THREE-PROOFS.md`（门禁「三证」：活性证 / 判别力证 / 成本证）
- **来源**：`/vault-spark` 2026-09-24 排查 dependabot PR #48 时发现（两处均为既有缺陷，非本轮引入）

---

## 1. 问题与用户价值 (Problem Statement & User Value)

**两处「门禁在跑，但保护力是假的」**：

| # | 假门 | 取证 | 危害 |
|---|---|---|---|
| **A** | 路由守卫测试**对上游语义漂移零免疫** | `tests/test_server.py:4452` 建 `{r.endpoint for r in probe.routes}`，`:4465` 用 `route.endpoint not in registered` 判缺 —— **端点函数对象身份**比对。starlette ≥1.6（随 fastapi ≥0.141 漂移进来）后 `include_router` 生成的路由**不再保持原函数对象引用** → **全部路由**误判 missing（CI run `35883141059` 实测复现） | ① **fastapi 升级被永久禁用**（`requirements.txt` pin `==0.136.3` + 本次刚加的 `dependabot.yml ignore`）；② 真漏挂 `include_router` 时**也**报"全部 missing" → 报警噪音淹没信号、无法定位真问题 |
| **B** | `mypy --strict` **静默漏检 6 个文件** | `pyproject.toml` 的 `exclude` 正则含**裸子串 `build`** → `tools/build_*.py` 等 6 个文件在**目录模式**下被跳过：`mypy --strict tools` 报 `no issues found in 5 source files`，而 `tools/` 实有 **11** 个 `.py`。用**显式文件清单**绕过 exclude 后实测 **47 errors in 4 files**（裸 `set`/`dict`/`list` 缺参数 + 缺函数签名） | 该门禁对 6 个产包/生成脚本**零覆盖**——本地全绿、错误永不被发现，与 Vault `AUTOMATION-VERIFICATION-THREE-PROOFS` 记载的"假门"同型 |

**用户价值**：
- **A 的产出**：解除 fastapi/starlette 升级禁区（并让守卫在真漏挂时**精确定位到具体 path**，而不是"全量 missing"）。
- **B 的产出**：`mypy --strict delector tools` 真覆盖 `tools/` 全部 11 个文件（其中 4 个的 47 个存量错误清账）。

**共同主题**：两处都是"接线在、报告在，但判别力是假的"——本计划把它们的**判别力**修出来，并各自给出**判别力反证**（三证之二）。

### 非目标 (Non-goals)

- **不重构 `tools/*.py` 的业务逻辑**：B 只补类型注解，**零行为改动**（若注解过程中发现真实缺陷 → 报告，不擅自改；同 v5.9.3 先例：mypy 曾抓到 2 处真缺陷）。
- **不改 `delector/` 任何代码**。
- **不引入运行时新依赖**：A 的新依赖验证在**隔离环境**（`pip install --target` 或 venv）内进行，**不进 `requirements.txt`**，除非该环境下**全量 pytest 绿**（此时才把 pin 升上去 —— 见 §2 的条件分支）。
- **不重写守卫测试**：只更换比对键（对象身份 → `(prefix+path, methods)`）。
- 不做"守卫测试全面分层重构"（那是更大的命题，本计划只修 A、B 两处）。

---

## 2. 用户旅程（工程视角 / 核心流程）

### A. 路由守卫改造（含条件分支）

1. 比对键从「端点函数对象」改为「**`(router.prefix + route.path, frozenset(methods))`**」。
2. **当前 pin 下验证**：`fastapi 0.136.3 + starlette 1.6.0` → 守卫**绿**（不得回归）。
3. **新依赖下双向验证**（隔离环境，不污染本机 pin）：
   - **旧实现**在该环境 → **红**（复现 CI 现象，坐实"改造前无免疫"）；
   - **新实现**在该环境 → **绿**（坐实"改造后免疫"）。
4. **条件分支**（依据第 3 步）：
   - 若新环境下**全量 pytest 也绿** → 升级 `requirements.txt` 的 pin（`fastapi==0.141.1` / `starlette==1.6.0`）+ **撤销** `.github/dependabot.yml` 的 `ignore` + 更新两处注释（pin 处的"必须 pin"说明改为"已验证可升"口径）。
   - 若新环境下**有其它失败** → **保留 pin 与 ignore**，把失败清单（用例名 + 断言消息）写进本 spec 的 §4「实测记录」，并明确"守卫误判已解决，但升级另有阻碍 → 另立计划"。
5. **判别力反证（必做）**：从 `register_routes` 临时摘掉一个模块的 `include_router` → 新守卫必红，且 `missing` **只列该模块的路由**（不再"全量"）。这是 A 的「判别力证」。

### B. mypy 覆盖修复

1. `pyproject.toml` 的 `exclude` 把裸子串 `build` 换成**锚定路径段**的写法（见 §3）。
2. `mypy --strict delector tools` → 覆盖文件数应从 **62**（57 + 5）变为 **68**（57 + 11），并暴露 47 个错误。
3. 逐个补注解（零行为）→ 再跑 → **0 error**。
4. 确认 `ci.yml` 的 mypy 门禁**口径**（若它写的是 `mypy --strict delector tools` 则自动受益；若写的是别的形态需同步）—— 并把"`tools/build_*.py` 此前从未被扫"这一事实在 `pyproject.toml` 注释里留证，防止正则再被改回裸子串。

---

## 3. 架构与数据模型 (Architecture & Data Models)

### 3.1 A：比对键

```python
# 已注册侧（probe.routes 里带 path 的路由）
registered = {
    (r.path, frozenset(getattr(r, "methods", ()) or ()))
    for r in probe.routes
    if hasattr(r, "path")
}

# 定义侧（router 上的 path 不含 prefix → 拼回完整 path）
key = (router.prefix + route.path, frozenset(getattr(route, "methods", ()) or ()))
if key not in registered:
    missing.append(f"{mod_info.name}:{key[0]}")
```

**为何 `path`/`methods` 可靠而 `endpoint` 不可靠**：前两者是**HTTP 语义**（框架文档化契约、跨版本稳定），后者是**实现细节**（对象身份无任何向后兼容承诺）。这正是 post-mortem §4.2 那条"依赖对象身份/私有属性的测试是漂移哨兵而非回归防线"的直接落地。

**边界**：`Mount`（static 挂载）无 `methods` → 空 `frozenset()`，不会与 APIRoute 键碰撞（真实路由必带方法）；`router.prefix` 为空时退化为 `route.path`。

### 3.2 B：exclude 正则锚定

```toml
# 原（裸子串 build 会吃掉 tools/build_*.py）
# exclude = '(\.venv|dist|build|android|scratch|tools/raw)'
# 新（锚定为独立路径段）
exclude = '(\.venv|dist|android|scratch|tools/raw|(^|/)build(/|$))'
```

`(^|/)build(/|$)` 只匹配**独立的 build 目录段**（如 `build/`、`./build/...`），不再匹配 `tools/build_prep.py`（`build` 后紧跟 `_`）。

### 3.3 隔离验证环境（A 第 3 步）

首选（轻量，只覆盖 fastapi/starlette）：

```bash
python -m pip install -q --target /tmp/tc_dep "fastapi==0.141.1" "starlette==1.6.0"
PYTHONPATH=/tmp/tc_dep python -m pytest tests/test_server.py -q -k register_routes
```

`PYTHONPATH` 在 `sys.path` 中位于 `site-packages` **之前** → 仅覆盖这两个包，spaCy 等仍用系统版本。
备选（更干净但更慢）：`python -m venv /tmp/tc_venv` + 装完整 `requirements.txt`（含 spaCy 德语模型）。

---

## 4. 边界与韧性 (Edge Cases & Resilience)

| 场景 | 行为 |
|---|---|
| 路由模块 `prefix` 为空 | `router.prefix + route.path` 退化为 `route.path`，仍正确 |
| 同一 `(path, methods)` 在多处重复注册 | 已注册侧是 `set`（天然去重）；定义侧逐条比对仍可命中 |
| `probe.routes` 含 `Mount` / 非 APIRoute | `getattr(r, "methods", ())` → 空集，不参与匹配 |
| 路由 `methods` 为 `None` | `or ()` 兜底为空集（防御上游返回形态差异） |
| 隔离环境不可用（无网 / 装不上新版本） | **降级**：仅在当前 pin 下验证守卫绿 + 判别力反证；**不升级 pin、不撤 ignore**；把"新依赖下验证"记为未完成（放入 §4 实测记录） |
| 新依赖下全量 pytest 有失败 | **保留 pin 与 ignore**；失败清单写入本 spec；另立计划 |
| `mypy` 修注解时发现真实缺陷 | **立即报告**，不擅自改行为（`cp` 备份 + 单独提交路径由编排者决定） |
| `pyproject.toml` 的 exclude 改动破坏既有守卫 | `tests/test_ci_hardening.py` 对 pyproject 若有 exclude 断言须同步；改后必跑该文件 |
| CI（ubuntu）与本机差异 | 门禁口径以 `ci.yml` 实际命令为准；改完本地跑 `mypy` 裸跑（配置 files 口径）确认 |

### 实测记录（T1 第 3/4 步回填）

> 待 T1 执行后回填：新依赖环境是否可用、旧/新实现的双向结果、全量 pytest 结果、是否升级 pin。

---

## 5. 测试策略 (Test Strategy)

**A（守卫）**
- 改造后：`python -m pytest tests/test_server.py -q -k register_routes` **绿**（当前 pin 下）。
- **判别力反证（必做）**：临时把某模块的 `include_router` 注释掉 → 守卫**必红**，且 `missing` 只含该模块的路由（比对改造前的"全量 missing"行为描述）。`cp` 还原。
- **新依赖双向验证**：隔离环境下旧实现红 / 新实现绿（用 `git stash` 不可行 → 用 `cp` 备份新旧两份实现对比）。

**B（mypy）**
- 改 exclude 后：`python -m pytest tests/test_ci_hardening.py -q` 不回归。
- `python -m mypy --strict delector tools` → 覆盖 **68** 文件且 **0 error**（先暴露 47 → 清账至 0）。
- 逐文件复核：`git diff` 中 `tools/*.py` 的改动**全部为注解/import 层面**（可用"删掉 `type: ignore` 后是否仍过"等方式抽查，但不得改行为）。

**收官**
- 全量 pytest **分半跑**（`--ignore=tests/test_server.py` + 单跑 `tests/test_server.py`）；
- `ruff check .` 零告警；全 `tools/*.mjs` 零漂移。

---

## 6. 关联索引

- `docs/plans/2026-09-24-toolchain-guard-truth.md`（实施计划）
- `08-Projects/DeLector/POST-MORTEM-V5.4.0-FASTAPI-DEPENDENCY-DRIFT.md`（A 的历史根因）
- `01-Rules/AUTOMATION-VERIFICATION-THREE-PROOFS.md`（门禁三证；本计划即其执行）
- `docs/plans/2026-09-13-mypy-cleanup.md` / `docs/specs/2026-09-18-mypy-strict-annotation-sweep-design.md`（B 的历史脉络）
- `.github/dependabot.yml`（本次刚加的 `ignore`，A 完成后视条件撤销）
