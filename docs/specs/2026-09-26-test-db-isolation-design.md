# 测试库隔离修复：消除「模块级 env 抢占 + 删库」导致的跨模块 `no such table`

- **日期**：2026-09-26
- **状态**：设计已定（根因已用受控实验证实），待 `/vault-plan` → `/vault-exec`
- **类别**：Architectural（测试基础设施的跨文件约定修复；**不改任何生产代码**）
- **前置**：`docs/specs/2026-09-24-toolchain-guard-truth-design.md`（该计划的 fastapi 升版正卡在这 2 例既有失败上）
- **调试方法**：`/vault-debug` 4 步协议（Step 1 受控实验已完成）

---

## 1. 问题与用户价值 (Problem Statement & User Value)

**现象**：半 A（`pytest --ignore=tests/test_server.py`）稳定红 2 例：

```
tests/test_goethe_a1_hoeren.py::test_hoeren_api_endpoints - sqlite3.OperationalError: no such table: exam_trials
tests/test_goethe_a1_lesen.py::test_lesen_api_endpoints   - sqlite3.OperationalError: no such table: exam_trials
```

**关键取证**（Step 1）：
| 事实 | 证据 |
|---|---|
| **单跑全绿** | `pytest tests/test_goethe_a1_hoeren.py tests/test_goethe_a1_lesen.py -q` → **8 passed**；只跑那 2 例 → **2 passed** |
| **与任一"抢 env"模块组合即红** | `test_audit_hardening` / `test_exam_catalog` / `test_exam_trials` 与 hoeren 组合 → 各 `1 failed, N passed` |
| **受控实验（决定性）** | 把 `test_audit_hardening.py:15-16` 的**模块级赋值**注释掉 → 同一组合 `1 failed, 34 passed` → **`35 passed`**（还原后逐字节一致） |
| **只在 Windows 红** | CI（ubuntu）长期 success —— 因 ubuntu 上句柄未释放使 `os.remove` 抛错被 `except OSError` 吞掉，库其实还在（详见 §3 机制） |
| **`database.get_db_path()` 每调用读 env** | 见 `test_audit_hardening.py:44` 注释 —— 故 **`server.app` 单例是无辜的**（app 不冻结库路径） |

**根因链（已闭合）**：

1. 某测试模块在**模块级**直接赋值 `os.environ["DATABASE_PATH"] = "test_X.db"`（**永久、无人还原**）。
2. 于是 `delector.server` 首次被 import 时（模块顶层有 `init_db()` 副作用），`init_db()` 建的是 **`test_X.db`**。
3. 后续模块（如 `test_goethe_a1_hoeren`）的模块级 `os.environ.setdefault(...)` **失效**（env 已被设置）。
4. 它的 autouse fixture `_m5_isolated_db_teardown` **只做清理**（`gc.collect()` + `os.remove`），**既不钉 env 也不建表** —— 其隔离 100% 依赖"`setdefault` 生效 + `server` 顶层 `init_db()` 建过表"这个**隐式前提**。
5. 而 `test_X.db` 又被 X 模块自己的 fixture 在结尾 **`os.remove`** 掉。
6. 于是 hoeren 的用例请求时：env 指向 `test_X.db`（被删）→ sqlite **新建空库** → 无 `exam_trials` 表 → `no such table` ❌

**为何 ubuntu 绿**：第 5 步 `os.remove` 在 ubuntu 上常因 sqlite 句柄未释放而抛 `OSError`，被 `except OSError: pass` 吞掉 → 库文件仍在、表仍在 → 不报错。Windows 上 `gc.collect()` 后句柄释放、删除真成功 → 才暴露。**这不是"Windows 环境问题"，是跨平台都存在的顺序耦合，只是 ubuntu 恰好掩盖了它。**

**用户价值**：这 2 例是 `docs/specs/2026-09-24-toolchain-guard-truth-design.md` 里"安全升级 fastapi/starlette"的**唯一前置**（守卫已免疫、升级无回归，但"全量真绿"的门槛卡在它们身上）。修掉它即可同笔升 pin + 撤 `dependabot.yml` 的 `ignore`。同时消除一类"新测试只要在模块级碰 env 就会随机打爆别人"的系统性陷阱。

### 非目标 (Non-goals)

- **不改任何生产代码**（`delector/**` 不动；`server.py` 的模块级 `app` 保持原样 —— 已证实它无辜）。
- **不重构整个测试套件的隔离方案**（不引入 pytest 插件、不改成 per-test 的 `create_app()`）。
- **不改测试断言或测试意图**（只改隔离机制）。
- **不动与本故障无关的模块**（`test_tools.py` 等无 autouse fixture 但半 A 未红者，本次不扩范围）。
- **不升级 fastapi/starlette**（那是本修复的**后续**动作，另行处理）。

---

## 2. 流程（工程视角）

1. **消除污染源**：让"模块级直接赋值 `DATABASE_PATH`"在 `tests/` 中**不再存在**（它是根因链第 1 环）。
2. **给受害者自洽能力**：让"只清理不建库"的模块的隔离 fixture 变成**自建库**（钉 env + `init_db`），不再依赖"谁先 import"。
3. **兜底**：`conftest.py`（仓库根） 提供稳定的测试默认 env，确保 `server` 顶层 `init_db()` 永远不会落到仓库根的真实 `delector.db`。
4. **根因级守卫**：新增 AST 守卫测试 —— 任何**模块级**直接赋值 `os.environ["DATABASE_PATH"]` 都判红（把这次踩的坑钉死成契约）。
5. **验收**：半 A / 半 B 双绿 + 全量（不分半）在下也尽量绿。

---

## 3. 架构与数据模型（隔离契约）

### 3.1 契约（修复后，所有测试模块 MUST 遵守）

| # | 规则 | 理由 |
|---|---|---|
| C1 | **MUST NOT** 在模块级直接赋值 `os.environ["DATABASE_PATH"]` / `PROGRESS_DB_PATH` | 它会永久污染进程 env（根因链第 1 环） |
| C2 | 需要独立库的模块 → 在 **autouse fixture** 内：**捕获 `saved` → 钉自己的 env → `init_db()` → `yield` → 清理 → 还原 `saved`** | 用完归位；且保证"库真的建过表" |
| C3 | fixture **可以**删自己的库（它已不在 env 里被别的模块引用 —— 因为 C2 会还原） | 删库不再伤人 |
| C4 | 只做纯逻辑断言、不碰 DB 的模块 → 可完全不加夹具 | YAGNI |

> C2 相比现状的关键增量：**"钉 env 之后必须 `init_db()`"** —— hoeren/lesen 现在缺的正是这一步（它们的 fixture 只 yield 后清理）。

### 3.2 兜底：`conftest.py`（仓库根）

在现有 sys.path 注入之后追加：

```python
# 测试默认库：保证「任何测试模块 import server 之前 env 已有值」，
# 使 server 模块顶层的 init_db() 落到测试库而非仓库根的真实 delector.db；
# 同时给各模块 fixture 的 env 还原提供稳定目标（见 C2/C3）。
os.environ.setdefault("DATABASE_PATH", "test_conftest_default.db")
os.environ.setdefault("PROGRESS_DB_PATH", "test_conftest_default_progress.db")
```

用 `setdefault` 而非强赋值：尊重外部已设值（若 CI 显式指定库则以其为准）。conftest 由 pytest **最先** import → 它设的值成为"稳定基线"。

### 3.3 改动面（预计）

| 文件 | 改动 |
|---|---|
| `conftest.py`（仓库根） | +兜底 env（§3.2） |
| `tests/test_audit_hardening.py` | 删模块级 `os.environ[...] = ...`（2 行），保留 fixture |
| `tests/test_exam_catalog.py` | 同上 |
| `tests/test_exam_trials.py` | 同上 |
| `tests/test_server.py` | 同上（**注意**：该文件正被另一计划 `chore/toolchain-guards` 改守卫用例；本计划只动其模块级 env 两行，冲突面极小，合并时按序处理） |
| `tests/test_goethe_a1_hoeren.py` | `_m5_isolated_db_teardown` 扩展为「钉 env + `init_db()` → yield → 清理 + 还原」 |
| `tests/test_goethe_a1_lesen.py` | 同上 |
| `tests/test_test_isolation.py` | **新增**（AST 守卫，见 §3.4） |

### 3.4 根因级守卫（AST）

```python
def test_no_module_level_database_path_assignment():
    """测试模块 MUST NOT 在模块级直接赋值 DATABASE_PATH / PROGRESS_DB_PATH：
    这会永久污染进程 env，令后续模块 setdefault 失效并命中被删的空库
    （2026-09-26 的 no such table: exam_trials 根因）。
    允许：fixture/函数内的赋值（用完还原，见 C2）。"""
    # 遍历 tests/*.py，用 ast 取 Module.body 里对 os.environ[...] 的直接赋值
```

- 判别力：对现有代码应**全绿**（因为污染源已被删）；把任一处模块级赋值加回去 → **必红**。
- 与 `conftest.py` 的兜底职责区分：conftest 负责"有值可用"，守卫负责"没人抢"。

---

## 4. 边界与韧性 (Edge Cases & Resilience)

| 场景 | 行为 |
|---|---|
| 外部（CI）显式设置 `DATABASE_PATH` | conftest 的 `setdefault` 尊重它；各模块 fixture 仍钉自己的（C2） |
| 模块 fixture 内 `init_db()` 失败 | 与现状一致（不额外吞异常）；`init_db` 幂等 |
| 两个模块用同一个库名 | 各自 fixture 前后钉 + 还原 → 互不越界（但属命名冲突，守卫不覆盖；记录） |
| Windows 句柄未释放致 `os.remove` 失败 | 已被 `except OSError: pass` 容忍；且修复后"删不掉"不再有害（C2 保证用前建表） |
| `test_server.py` 与 `chore/toolchain-guards` 分支冲突 | 本计划只动其模块级 env 两行；合并顺序：先 toolchain-guards 再本分支（或反之），冲突可手工解决 |
| 全量（不分半）跑 | 本机历史上"不可靠"（跨文件 env 串扰）；修复**旨在**改善，但**验收以分半双绿为准**（全量作为附加观察，记录不阻塞） |
| `test_tools.py`（无 autouse 但半 A 未红） | 本次不动（YAGNI）；若守卫/全量暴露它有问题，记录、另议 |

---

## 5. 测试策略 (Test Strategy)

1. **受控实验复现已固化**：`pytest tests/test_audit_hardening.py tests/test_goethe_a1_hoeren.py -q` —— 修复前 `1 failed`，修复后应 `35 passed`（这是最直接的判别点）。
2. **失败组合矩阵**：3 个污染源 × 2 个受害者，修复后全部绿。
3. **半 A / 半 B**：`pytest -q --ignore=tests/test_server.py` 与 `pytest -q tests/test_server.py` 双绿（半 A 应从 `2 failed, 891 passed` 变为 `0 failed, 893 passed`，数字以实测为准）。
4. **新守卫**：`tests/test_test_isolation.py` 全绿；**变异验证** —— 把任一模块的模块级赋值加回 → 守卫必红。
5. **零行为改动核对**：`git diff tests/` 中除 fixture 机制与删掉的两行 env 外，**不得**有断言/测试意图变化。

---

## 6. 关联索引

- `docs/plans/2026-09-26-test-db-isolation.md`（实施计划）
- `docs/specs/2026-09-24-toolchain-guard-truth-design.md`（本修复是其"安全升级 fastapi"的前置）
- `WORKMEMORY/PROJECT_OVERVIEW.md`（测试契约节：跨文件 env 串扰的分半跑纪律）
- 项目 memory 记载的原始纪律：「新测试不得删库文件、env 必须用 `setdefault`」—— 本计划把该纪律**精确化**为 C1–C4（因为"删库"在 C2 下其实安全，真凶是"模块级赋值"）
