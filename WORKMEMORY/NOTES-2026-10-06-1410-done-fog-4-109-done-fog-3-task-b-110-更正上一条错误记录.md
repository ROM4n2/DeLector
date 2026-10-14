### 2026-10-06 14:10 | codebuddy | DONE(Fog 4 #109) + DONE(Fog 3 Task B #110) + 更正上一条错误记录

> 本文件是 `WORKMEMORY/work.log` 中该事件的**正文**（原事件 4334 B，超 `PROTOCOL.md` §4 的 4096 B 上限）。
> 拆分时间：2026-10-14；正文逐行无损搬运，未删改任何内容。

Caps: filesystem-read, filesystem-write, shell-exec
事件：Fog 3 / Fog 4 收口。**编排者上一条记录里有个虚构事实，本次更正。**
⚠️ **更正**：`shutil.which("rm")` **全仓 0 次**（三重交叉验证：`grep -rc 'shutil.which("rm")' tests/ delector/` = 0、`def test_cleanup` 全仓 0 次、`delector/core/database.py` 内 `shutil` 0 次）。上一条 log 记的"`database.py:2086` 的 `test_cleanup` 用 `shutil.which("rm")`，是第 8 处同类 skip 漏网"**是错的**——`tests/db_cleanup.py::remove_db_files` 用的是跨平台 `os.remove`。**教训：不要把未核实的记忆当事实写进 log。**
- **Fog 4（#109，`tests/test_ci_hardening.py` +165）**：把「CI 必需运行时」清单**显式化**成守卫，并钉住两条**否定式**结论。①`rm` 标注为"平台相关、非 CI 必需"；②**`bash` 判为"平台相关"、不进清单**——依据：CI 是 ubuntu 且 GitHub Actions 的 `run:` 本身就以 bash 为默认 shell；`test_server.py:2591` 的 skip **不是** `if not shutil.which("bash")`，而是 `_find_bash()` **五套策略的最后一招**（`:2574`），语义是"本机找不到任何可用 bash"，Windows 无 Git-Bash 时跳过是**正确**行为。⇒ **扩进清单 0 项、未改 `conftest.py`**（硬塞 `bash` 只会制造一条错误门禁）。新守卫首跑**直接绿**（核实结论就是清单无需变更）⇒ 改用**五条变异**证非空转（清单清空/加 rm/加 bash/bash 同时进两个清单/`CI` 判据改恒真），全真红。
- **Fog 3 的编排者实测取证（两项，决定 Fog 3 的走向）**：
  - **Q1 校验顺序实测**：`in-body 闸 + 非法 body → 422` vs `Depends 闸 + 非法 body → 403`；合法 body 两者都 403。⇒ **统一成 `Depends` 的唯一真行为变化 = LAN + 非法参数时 422 → 403**（16 个 main.py 端点），语义收紧（不再对 LAN 泄露字段级校验消息）。
  - **Q3 运行时 `dependant` 枚举实测**：模块级 router 变量共 **14 个**（12×`router` + `hoeren_router` + `lesen_router`）；运行时枚举**只找出 4 条**（`encounter.router` 3 + `tools.router` 1，全 `Depends` 形式）——**看不到函数体内调用的 16 条**。⇒ **"改用运行时 dependant 更可靠"这一 Fog 3 原始论证不成立**：它只在完成 16 处形式统一后才可行，而那时守卫也一并要改。当前 20 条 allowlist **是正确的**（`hoeren_router`/`lesen_router` 上确实没闸）。
- **Fog 3 Task B（#110，只改 `tests/test_localhost_guard.py`，零行为变化）**：关掉三个**已实测确认**的漏检洞——①只认字面 `router`（现测 14 个 router 变量，将来给 `hoeren_router` 加闸则守卫**看不见、不报警**）；②prefix 只从单个 router 取（一模块双 router 时**键失真且恰好蒙对**）；③调用名字面量（`import ... as` 别名漏检）。三个洞均以**临时改 `delector/` 制造真实场景**完成"改前绿 / 改后红"取证，`delector/` 零残留（`git status --short -- delector/` 与 `diff --stat` 均为空）。allowlist 20 条**逐字未动**（`diff` 零删除行）。洞 3 **未覆盖** `functools.partial` / 包装函数间接调用 / `include_router` 跨模块前缀叠加，理由是需跨模块数据流分析、性价比低，**不假装做了**。
- **一处约束冲突（maker 指出，编排者任务书自相矛盾）**：要求"router 变量名纳入 path 键构造"与"allowlist 20 条不得变"互斥。调和：path 键保持完整 URL 不变，router 变量名作为**键的归属方**参与判定，跨 router 撞键**抛 AssertionError** 而非静默覆盖。
- **Fog 3 的 C-F（16 处形式统一）待用户裁决**：其收益（守卫可用运行时方案）已被实测证明需"改守卫 + 改 16 处"两步，而 Task B 已用零行为变化达成同等可靠性；成本是 422→403 的用户可见变化 + 16 处改动 + 误挂风险（`POST /api/wb/state` **刻意不挂闸**，用 `X-WB-Key`）。
**门禁**：`test_localhost_guard.py` 7 passed / `test_ci_hardening.py` 21 passed / 半 A `1048` / 半 B `264 passed, 1 skipped` / `mypy` 两道（`93` + `70` files）0 error / `ruff` 通过。

