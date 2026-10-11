# 桌面壳「起点 → 服务就绪」3s 空档的可归因化 Implementation Plan

> **Goal**: 让 `desktop.py` 启动链上那段**当前无标记的 3s**（`开始启动` → `已创建 splash 窗口`）可被 `launch.log` 归因——**只加标记、不改启动行为**。
> **Tech Stack**: Python 3.11 / pywebview 桌面壳（`desktop.py`）/ pytest / AST 静态锁。
> **Spec Reference**: ADR-0018 §8 `[Unknown 8]` **复核条**（commit `4f01d72`：实测 3s / 2s / 1s，明写"那 3s 是一个未标记的空档，无法归因"）+ ADR-0020 §6 `[Unknown 2]`。
> **Global Constraints**:
> - **零新依赖**；**不改启动行为**（只增加日志调用，不改顺序/不改逻辑）。
> - **日志行格式不变**（`[YYYY-MM-DD HH:MM:SS] 消息`，秒级）——`tools/first_screen_from_log.py` 依赖它。
> - **新标记 MUST NOT 把解析器的三个锚串当子串包含**：`开始启动（进程级计时起点）` / `服务已就绪` / `真实 UI 已加载（首屏可用）`。否则 `_last_index` / `_first_index_after` 会抢错行，首屏数字静默变成别的意思。
> - 门禁不许削弱：`ruff check .` / `mypy --strict delector tools` / `mypy --platform win32 --strict --follow-imports=skip desktop.py package_windows.py conftest.py start.py` / `pytest`。
> - 每任务交付**物理证据**（原始命令 + 退出码 + 测试计数 + `git diff --stat`）。

---

## 🏛️ Decisions So Far

- **用户 2026-10-11 拍板选项 A**（在"补 3s 空档标记 / 加毫秒时间戳 / 先不动"三选一里）：**先补标记**——因为观测差异只有 3s/2s/1s 三档，秒级分辨率足够归因；毫秒（选项 B）留待将来。
- **本轮目标是"可归因"，不是"提速"**：不加标记就无法判断该优化 Python 侧前置（`import delector.server` / `build_server`）还是 webview 建窗。
- **标记住 `_run_desktop_inner`**（服务侧前置）**而非 `_show_window`**：后者的建窗/托盘三段（`已创建 splash` / `已创建主窗口` / `托盘线程已启动`）**本来就有标记**，无需重复。
- **沿用既有内联字面量风格**（不新建"标记常量表"）：与 `desktop.py` 现有 17 处 `_append_log` 一致，避免第二份真相源。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: `_run_desktop_inner` 补 6 枚启动阶段标记 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `desktop.py:603-627`（`_run_desktop_inner`）
- Test: `tests/test_desktop_shell.py`

**Interfaces:**
- Consumes: `desktop._append_log(log_path: str, message: str) -> None`（既有）
- Produces: 6 枚新日志标记，**按写入顺序**：
  1. `端口与身份校验通过。`（`_check_port_or_fail` 返回 True 之后）
  2. `WebView2 运行时检测通过。`（`ensure_webview2_runtime()` 为真之后）
  3. `数据目录已就绪（bootstrap_data_dir 完成）。`（`bootstrap_data_dir(os.environ)` 之后）
  4. `服务端模块已导入（delector.server）。`（`from delector.server import app` 之后）
  5. `HTTP 服务已装配（build_server 完成）。`（`build_server(...)` 之后）
  6. `本地服务线程已启动（等在就绪窗口内命中）。`（`serve_in_thread(server)` 之后）

**Injected Instincts:**
- [ ] `[Instinct: Zero-Behavior-Change]`：新调用**只写日志**；不得移动/删改既有语句顺序（`bootstrap_data_dir` 必须仍在 `from delector.server import app` 之前——见该处既有注释）。
- [ ] `[Instinct: No-Marker-Collision]`：三条锚串不得成为新标记的子串（Global Constraints 第 3 条）。
- [ ] `[Instinct: Fail-Open-Logging]`：`_append_log` 已保证"绝不抛"；新调用不得引入任何可抛路径。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: `_run_desktop_inner` 补 6 枚启动阶段标记。
> Mode: AFK | Role: TDD Builder
> Goal: 让 `launch.log` 能把「开始启动 → 已创建 splash 窗口」这段 3s 拆成 6 个可归因区间（校验 / WebView2 检测 / 数据目录 / 服务栈 import / build_server / 服务线程）。
> Target Files: Modify `desktop.py` 的 `_run_desktop_inner`；Test `tests/test_desktop_shell.py`。
> Injected Instincts: 只加日志不改行为；新标记不得含三条锚串；`_append_log` 不抛。
> TDD Steps:
> 1. 在 `tests/test_desktop_shell.py` 写失败测试（RED）：AST 取 `_run_desktop_inner` 内 `_append_log` 的**字符串实参按行号排序**，断言 6 枚标记按上述顺序出现、且各自落在对应语句之后（至少断言顺序 + 每枚存在）。
> 2. 运行 `python -m pytest tests/test_desktop_shell.py -q` 并确认失败信息符合预期。
> 3. 在 `desktop.py` 加 6 次 `_append_log`（GREEN）。
> 4. 再跑一次确认全绿。
> Return: Summary with MANDATORY Physical Execution Receipt (exit code + stdout snippet + git diff --stat)。"

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）**——AST 断言 6 枚标记存在且顺序正确
- [ ] **Step 2: 运行并确认按预期失败**
- [ ] **Step 3: 实现最小生产代码（GREEN）**——6 次 `_append_log`
- [ ] **Step 4: 跑测试确认全绿**
- [ ] **Step 5: Refactor**——守卫式压平（`_run_desktop_inner` 保持最大缩进 2 层）
- [ ] **Step 6: 物理证据**（命令 + 退出码 0 + 通过数 + `git diff --stat`）
- [ ] **Step 7: 原子提交**

### Task 2: 解析器兼容性回归锁（行为级 + 变异自证） [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `tests/test_desktop_shell.py`（或新增 `tests/test_first_screen_from_log.py` 用例，取既有文件更省）
- Test: 同上

**Interfaces:**
- Consumes: `tools/first_screen_from_log.py::run(log_path: str) -> int`（既有，纯标准库）
- Produces: 用例 `test_new_stage_markers_do_not_hijack_first_screen_parser`

**Injected Instincts:**
- [ ] `[Instinct: Substring-Collision]`：本项目已多次栽在"字面量撞子串 ⇒ 断言恒真"。本任务要防的是**反向**撞车：新标记含锚串子串 ⇒ 解析器抢错行 ⇒ 数字静默变味。
- [ ] `[Instinct: Mutation-Proof]`：把某枚新标记临时改成含 `服务已就绪`（如 `服务已就绪（线程已启动）。`）⇒ 本用例 MUST 转红；恢复 ⇒ 绿。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: 解析器兼容性回归锁。
> Mode: AFK | Role: TDD Builder
> Goal: 证明新增阶段标记**不会**让 `tools/first_screen_from_log.py` 抢错锚行。
> Target Files: Test `tests/test_desktop_shell.py`。
> 做法（行为级，非源码字符串）：
> a. 造一份合成 `launch.log`（`tmp_path`）：含计时起点、6 枚新标记、`服务已就绪。`、`真实 UI 已加载（首屏可用）。`、`已创建 splash 窗口。`，**10 行 ⇒ 时间戳 10 个**：`08/08/09/09/10/10/11/11/13/14`（秒级；原稿误列 9 个、漏掉 splash 的 `11`，由 Task-2 复核席位 CRV 抓出，2026-10-11 就地修正）。
> b. 调 `run(str(log_path))`，断言退出码 0 且 stdout 三段数字 = `5s / 1s / 6s`（即锚行仍取自真锚，新标记未抢）。
> c. 加一条**结构化前置断言**：新标记字符串与三个锚串互不为子串（防将来有人手滑）。
> d. 变异自证：临时把某枚新标记改成 `服务已就绪（线程已启动）。` ⇒ 用例转红（附原始输出）。
> Return: MANDATORY Physical Execution Receipt（exit code + stdout + 变异前后的两段输出）。"

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）**（合成日志 + 断言三段数字）
- [ ] **Step 2: 运行并确认失败**
- [ ] **Step 3: 让用例通过（GREEN）**——如实现无误，通常只需修测试自身的口径
- [ ] **Step 4: 变异自证**（改标记 → 红 → 恢复 → 绿），保留原始输出
- [ ] **Step 5: 物理证据 + 原子提交**

### Task 3: 回写文档（ADR 两份 + PROJECT_OVERVIEW + work.log） [Mode: AFK] [Role: 文档]

**Files:**
- Modify: `docs/adr/2026-10-09-adr-0018-performance-measurement-before-runtime-swap.md`（§8 复核条）
- Modify: `d:/Obsidian/Coding/08-Projects/DeLector/01-ADR/0018-...md`（vault 正式件，**正文逐行同源**）
- Modify: `WORKMEMORY/PROJECT_OVERVIEW.md`、`WORKMEMORY/work.log`

**Interfaces:**
- Consumes: 本轮实测（标记已加）
- Produces: ADR 里"3s 是**未标记的空档**"改为"**已标记**（6 枚），**待用户重跑一次**取真实分段"；并写明"重跑前不得声称任何段占比"。

**Step Breakdown:**
- [ ] **Step 1: 改仓内 ADR 副本**
- [ ] **Step 2: 同段落到 vault 正式件（正文机器比对逐行同源）**
- [ ] **Step 3: PROJECT_OVERVIEW + work.log**
- [ ] **Step 4: 证据（`diff` 正文同源输出）+ 原子提交**

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Unknown 1] 6 枚标记各自的真实耗时**：**必须用户重跑一次桌面壳**才拿得到（`python desktop.py` → `tools/first_screen_from_log.py`）。在本轮内**禁止**猜测任一段占比。
- **[Unknown 2] 3s 里"Python 侧前置"与"webview 建窗"谁更大**：Task 1 只能把两者**分开**（第 6 枚与 `已创建 splash 窗口` 之间即纯建窗段），**不能**替我们判断下一步该打谁。判据在重跑后的数字里。
- **[Unknown 3] 是否需要毫秒时间戳（选项 B）**：若重跑后各段仍是 `0s/1s` 这类量化边界值，则秒级不足以支撑下一步决策 ⇒ 届时再单独立项（本 pipeline 不做）。

---

## 🚫 Out of Scope

- **毫秒时间戳 / 改 `_append_log` 格式**（选项 B，本 ADR 明确不做）。
- **任何启动提速改动**（本任务只做可归因化；提速由重跑数据决定后再立项）。
- **前端进一步优化 / 代码分割**（ADR-0018 §8 复核条已判"前端非主项，天花板 ~1s"）。
- **`launch.log` 轮转策略调整**（P2 已交付 5MB 启动时轮转）。
- **Android / 打包面**（本改动只在 Windows 桌面入口）。
