# 「进程创建 → 计时起点」未测段的可观测化 Implementation Plan

> **Goal**: 把 `desktop.py` 启动链上**当前计时起点之前那段**（解释器启动 + `desktop.py` 模块级 import + PyInstaller bootstrap）纳入 `launch.log`，让"用户双击 → 首屏"有**真口径**，而不是拿 6s 当用户感知值。
> **Tech Stack**: Python 3.11 / `ctypes`（stdlib）/ pywebview 桌面壳（Windows 专属入口）/ pytest。
> **Spec Reference**: ADR-0018 §8 `[Unknown 8]` 复核条（"计时起点晚于解释器启动与该模块 import ⇒ 用户感知端到端**比 6s 更长**，那段**未测**"）+ ADR-0020 §6 `[Unknown 2]`。
> **Global Constraints**:
> - **零新依赖**（只用 `ctypes` + `kernel32`）。
> - **不改任何既有日志行的字面量**：`tools/first_screen_from_log.py` 的三条锚串（`开始启动（进程级计时起点）` / `服务已就绪` / `真实 UI 已加载（首屏可用）`）MUST 保持为既有行的**子串**，新信息**另起一行**。
> - **fail-soft + 平台安全（MUST）**：取进程创建时刻必须**绝不抛**，且必须 `sys.platform` 守卫 —— CI 是 ubuntu（`ctypes.windll` 在 Linux 上**不存在**），`desktop.py` 被测试 import，模块顶层与调用路径都不许炸。
> - **绝不近似冒充**：`time.time()` / `time.perf_counter()` 的进程内起点**不是**进程创建时刻，禁止拿它顶替。
> - 门禁不许削弱：`ruff check .` / `mypy --strict delector tools` / `mypy --platform win32 --strict --follow-imports=skip desktop.py package_windows.py conftest.py start.py` / `pytest`。
> - 每任务交付**物理证据**（原始命令 + 退出码 + 计数 + `git diff --stat`）。

---

## 🏛️ Decisions So Far

- **本轮实测（2026-10-11，3 次稳定）**：源路径未测段 = **98–99 ms（解释器启动） + ≈245 ms（`import desktop`） ≈ 0.34–0.35 s** ⇒ 源路径真实端到端 ≈ **6.35s**，缺口 **≈5%**。**首屏 6s 的优化空间不在这段** ⇒ 本任务定位为**口径补全**，不是提速。
- **机制选定：`GetProcessTimes`（ctypes）**而非"父进程计时 shim"或"外部工具"：进程创建时刻由 OS 给出 ⇒ **对源码路径与打包产物路径同样有效**（PyInstaller bootstrap 也含在内），且零新依赖、无需改启动方式。已在本会话实测可用（`wintypes.FILETIME` + `GetSystemTimeAsFileTime` 交叉验证：换算出 unix 时间与 `time.time()` 吻合，差值 96.15ms）。
- **落点是"另起一行"而非"给起点行加后缀"**：起点行是解析器**唯一锚**（子串匹配）、也是测试断言的对象；把机器相关数字塞进锚行会让既有断言变脆。新行紧随起点行之后 ⇒ 不影响 `_last_index('开始说话…起点')` 的取法。
- **单枚新标记而非一套新框架**：与 Task-1（6 枚阶段标记）同款风格（内联字面量 + `_append_log`），不新建常量表/模块。
- **精度口径写死**：新段是**毫秒**精度，其余三段是**秒级**；因此"进程创建 → 首屏"的合计**只在秒级可比**，工具输出必须明写这一点（不得把它当 ms 级精度值）。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: `desktop.py` 落「进程创建 → 此处」毫秒（新行 + fail-soft + 平台守卫） [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `desktop.py`（新增私有函数 + 在 `run_desktop` 的起点标记之后落一行）
- Test: `tests/test_desktop_shell.py`

**Interfaces:**
- Consumes: `desktop._append_log(log_path: str, message: str) -> None`（既有，绝不抛）
- Produces:
  - `def _ms_since_process_create() -> Optional[float]` —— 返回毫秒（float）或 `None`；**任何异常/非 Windows ⇒ None，绝不抛**
  - 新日志行（紧随 `开始启动（进程级计时起点）。` 之后）：`进程已运行 {N} ms（自进程创建；此前为未测段）`，其中 `N` 为整数毫秒；取不到时写 `进程已运行 ? ms（自进程创建；此前为未测段）` **并保持该行存在**（消费者据此判"本机取不到"）

**Injected Instincts:**
- [ ] `[Instinct: Fail-Open]`：`_ms_since_process_create()` 内部 `try/except Exception` + `sys.platform` 守卫（`ctypes.windll` 在 Linux 不存在）；**取不到不得阻断启动**。
- [ ] `[Instinct: No-Anchor-Mutation]`：既有 4 条锚行字面量**逐字不动**；新行不得包含三条锚串（否则解析器抢错行，见 Task-2 的碰撞锁）。
- [ ] `[Instinct: No-Fake-Source]`：不得用 `time.time()`/`perf_counter()` 的"进程内起点"顶替进程创建时刻（那会漏掉解释器启动与 bootstrap，正是本任务要测的）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: `desktop.py` 落「进程创建 → 此处」毫秒。
> Mode: AFK | Role: TDD Builder
> Goal: 让 `launch.log` 能算出**当前计时起点之前那段**（解释器启动 + 模块 import + 打包 bootstrap）。
> Target Files: Modify `desktop.py`；Test `tests/test_desktop_shell.py`。
> TDD: ① 先写失败测试（RED）：AST 断言新行存在且**紧随**起点标记之后（沿用该文件既有 `_parse_desktop/_funcs_by_name/_calls/_call_label` 辅助），并断言新行**不含**三条锚串；再写一条**行为级**用例：monkeypatch `_ms_since_process_create` 返回 123.4 ⇒ 调用 `run_desktop` 的日志路径（或直接的落行函数）后，日志里出现 `进程已运行 123 ms`；再写一条**fail-soft 用例**：让它内部抛异常 ⇒ 仍写出 `进程已运行 ? ms` 且**调用方不抛**。
> ② 跑测试确认 RED 原因正确 ③ 实现（GREEN）④ ruff + mypy（含 --platform win32 入口面）⑤ **变异自证**：把 fail-soft 的 try/except 拿掉 ⇒ fail-soft 用例必须红；把新行里的数字换成常量 ⇒ 行为级用例必须红。
> Return: MANDATORY 物理回执（命令 + 退出码 + 计数 + git diff --stat）。"

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）**——存在/位置/无锚串碰撞（AST）+ 行为级（monkeypatch 产出具体 ms）+ fail-soft（抛异常仍不抛、写 `?`）
- [ ] **Step 2: 跑并确认按预期失败**
- [ ] **Step 3: 实现最小生产代码（GREEN）**
- [ ] **Step 4: 跑测试 + `ruff` + `mypy --platform win32 … desktop.py`**
- [ ] **Step 5: 变异自证两条**（去掉 try/except ⇒ 红；数字写成常量 ⇒ 红），贴原始输出
- [ ] **Step 6: 物理证据门**（命令 + 退出码 0 + 通过数 + `git diff --stat`）
- [ ] **Step 7: 原子提交**

### Task 2: `tools/first_screen_from_log.py` 解析新行并输出第 4 段 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `tools/first_screen_from_log.py`
- Test: `tests/test_first_screen_from_log.py`

**Interfaces:**
- Consumes: 既有 `run(log_path) -> int` 与三条锚串常量
- Produces:
  - 新常量 `PRE_START_MARKER = "自进程创建"`（与新行对齐）
  - 输出新增一行：`进程创建 → 计时起点（此前未测段）: {N} ms`
  - **老日志（无该行）**：输出 `进程创建 → 计时起点（此前未测段）: 该日志不含此项（旧版本）`，**退出码不变**（仍 0 / 3 等既有语义）—— 这是**可选增强**，不得把老日志变成红
  - 输出末尾附一行口径：`（毫秒段为进程创建→起点；其余各段为秒级时间戳相减，故"进程创建→首屏"合计仅在秒级可比）`

**Injected Instincts:**
- [ ] `[Instinct: Optional-Not-Fatal]`：缺该行 ⇒ 提示缺失，**不得**改退出码、不得静默给 0。
- [ ] `[Instinct: Precision-Honesty]`：不得把毫秒段与秒级段相加后报成"毫秒精度"。
- [ ] `[Instinct: Same-Source-Test]`：测试里从 `desktop.py` **AST 同源取**该新行的模板（沿用 `_new_stage_markers_from_desktop` 的做法），禁止在测试里复制第二份字面量。

**Step Breakdown:**
- [ ] **Step 1: 写失败测试（RED）**——合成日志含/不含新行两条路径 + 逐行断言输出
- [ ] **Step 2: 跑并确认失败**
- [ ] **Step 3: 实现（GREEN）**
- [ ] **Step 4: 变异自证**（把新行的 ms 换成常量 ⇒ 红；把"缺行"路径改成静默 0 ⇒ 红）
- [ ] **Step 5: 物理证据 + 原子提交**

### Task 3: 回写文档（ADR 两份 + PROJECT_OVERVIEW + work.log） [Mode: AFK] [Role: 文档]

**Files:**
- Modify: `docs/adr/2026-10-09-adr-0018-…md`（§8 复核条）+ **vault 正式件同段落逐字同步**
- Modify: `docs/adr/2026-10-10-adr-0020-…md`（§6 `[Unknown 2]`）+ **vault 正式件同样**
- Modify: `WORKMEMORY/PROJECT_OVERVIEW.md`、`WORKMEMORY/work.log`（追加）

**Produces**: 把"用户感知端到端**比 6s 更长**（未测）"改为**实测**：源路径 **≈6.35s**（其中进程创建→起点 ≈0.35s）；**打包产物路径待实测（Task 4）**。

**Step Breakdown:**
- [ ] **Step 1: 改仓内两份 ADR**（就地更新，不新起节）
- [ ] **Step 2: 同段落写入 vault 两份正式件**，并**机器比对正文逐行同源**（贴输出）
- [ ] **Step 3: PROJECT_OVERVIEW + work.log**
- [ ] **Step 4: 证据 + 原子提交**

### Task 4: 真启取数并对比两条路径 [Mode: HITL] [Role: Operator]

**Files:** 无（只读 `%LOCALAPPDATA%\DeLector\launch.log`）

**Produces**: 两条路径的「进程创建 → 首屏」实测值：
- 源路径：`python desktop.py`
- **产物路径：双击 `dist/DeLector-v5.16.0-Windows-x64-Portable\DeLector.exe`**（用户日常形态）

**Step Breakdown:**
- [ ] **Step 1: 用户跑一次源路径** ⇒ `python tools/first_screen_from_log.py`，贴输出
- [ ] **Step 2: 用户双击一次产物** ⇒ 同命令读 `launch.log`，贴输出
- [ ] **Step 3: 把两个数字回填 Task 3 的文档**（谁大、差多少、bootstrap 段多大）

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Unknown 1] 打包产物（PyInstaller）的 bootstrap 段大小**：未知，可能数秒。由 Task 4 揭示 —— **这正是本任务最可能有价值的部分**（源路径已实测只差 0.35s）。
- **[Unknown 2] `--server-only` 路径是否也要同款标记**：`start.py` 侧另有一套启动（且它有"端口占用早退"逻辑）。本轮**不做**；若用户也关心该路径，再单独立项。
- **[Unknown 3] 是否值得把"起点"本身前移到模块最早处**（而非新起一行）：那会改既有锚行的**位置**（进而改 `_last_index` 的取法语义与既有测试），收益只是少一行日志 ⇒ 暂不做，若 Task 1/2 落地后发现新行信息不足再说。

---

## 🚫 Out of Scope

- **任何提速改动**（本轮只做可观测化；源路径缺口仅 0.35s，提速空间不在这一段）。
- **那 2s 端口探测**（`connect_ex` 环境层排查）—— 已按用户裁定**暂缓**，见 ADR-0018 §8 `[Unknown 8]`；本计划**不碰** `is_port_in_use` 与 `_check_port_or_fail` 的任何语义。
- **毫秒时间戳改造**（把 `_append_log` 的 `%H:%M:%S` 改成带毫秒）—— 另一独立项（早前记作"选项 B"）。
- **`start.py` / `--server-only` 路径**、**Android 侧**、**打包面**（不改 spec/产物结构）。
