# 桌面单实例与端口顺延 · 设计稿

> **性质**：设计稿（`docs/specs/`），不是实施计划。落地时另立 `docs/plans/` 计划。
> **状态**：APPROVED（2026-10-21，用户批准；同日修正 §3.1 为「锁/元数据双文件」，理由见该节引用块）。
> **实施计划**：`docs/plans/archive/2026-10-21-desktop-single-instance.md`。
> **上游**：ADR-0019 §6.4 第 4 条（`docs/adr/2026-10-10-adr-0019-windows-desktop-pwa-first-and-data-dir-externalization.md:141`，
> 原文：`%LOCALAPPDATA%\DeLector\instance.lock`（pid + 版本 + 数据目录）；探测改为验证 `/api/health` 带
> DeLector 标识，不匹配则顺延 `8001–8010` —— **单实例靠文件锁而非端口探测**）。该条当年只登记、未实施。
> **相关**：ADR-0020 §6「health 探测必须校验身份与版本」（已实施为 `probe_identity`，**不含版本**）。
> **基线**：master `85fb029`（本轮 onboard 实测 2517 passed + 2 skipped）。

---

## 0. 结论先行

**采用全局文件锁 `%LOCALAPPDATA%\DeLector\instance.lock`，锁内容是唯一真相源；端口顺延范围改为 `8002–8010`。**

三处**在对话里给出、但本稿推翻**的初判（写错的接口比写漏的更危险，先标出来）：

| 初判 | 本稿结论 | 依据 |
| --- | --- | --- |
| 锁文件放**数据目录**内（per-data-dir 单实例，允许便携版与安装版并存） | **放平台默认目录，全局唯一** | ADR-0019 §6.4 已登记该位置；且「一个用户 = 一个 DeLector」是单机学习工具的诚实模型。per-data-dir 会引入「两个窗口、两个库、两份托盘」的新状态面，收益未测 |
| 顺延 `8001–8010` | **`8002–8010`** | `8001` 已被 Go supervisor 占用为保留端口：`agent/internal/pythonsvc/doc.go:9-10`「127.0.0.1:8001（8000 留给用户直启实例）」、`supervisor.go:32-43` |
| 身份探测仍作为同数据目录的判据 | **降为第二腿**（只在锁不可用时使用） | 启动期竞争：服务未就绪时 `probe_identity` 为假，会把「自己正在启动」误报成「端口被其他程序占用」 |

---

## 1. 实测基线 & 问题陈述

### 1.1 今天真实存在的四条失败路径（全部带现场）

| # | 现象 | 现场 |
| --- | --- | --- |
| F1 | 端口被占且对方是 DeLector ⇒ **无条件复用并打开它的页面**，不看版本、不看数据目录 | `start.py:203` `_handle_existing_port` → `probe_identity(port)` 为真即 `open_browser` |
| F2 | **启动期竞争**：空闲端口上 `is_port_in_use` 在 Windows 实测耗时 **~2.03s**（ADR-0020 §124），而健康端点此时可能尚未就绪（spaCy 冷启动）⇒ `probe_identity` 为假 ⇒ 报「端口被其他程序占用」并 `exit(1)`。**诊断指向了不存在的元凶** | `start.py:137` → `:203`；`server_lifecycle.py:116` |
| F3 | 双版本并存时无法告出版本：桌面壳的 P0-1 守卫只能判「是不是 DeLector」，判不出「是旧版本」 | `desktop.py:873` `_check_port_or_fail`，`:889` 只调 `probe_identity`；身份载荷只有 `app`+`version`（`routes/main.py:580`），且 `_has_identity` **只比对 `app`**（`server_lifecycle.py:111-113`） |
| F4 | `8000` 被**无关程序**占用 ⇒ 两条入口都直接失败，无顺延 | `start.py:66` `is_port_in_use`；`desktop.py:873` |

另有两条**既有缺陷**与本设计直接耦合：

- **L1 硬编码端口外泄**：`/api/wb/lan-info` 返回写死的 `"port": 8000`（`delector/routes/backup.py:179`）。一旦启用顺延，手机端会拿到**错的**局域网地址 —— 表现为「扫码/输入地址后打不开」，且完全无提示。
- **L2 入口判法漂移风险**：`start.py` 复用、`desktop.py` 拒绝，两套结论对同一端口不一致（`desktop.py:873` 自己就写明「两处判法一旦漂移，桌面端与 `--server-only` 就会对同一端口给出不同结论」）。

### 1.2 用户价值

- **目标用户**：双击 exe 的桌面用户（单机、单用户）；可能同时留着便携版与安装版。
- **目标场景**：第二次双击 / 升级后忘记退出旧进程 / 8000 被别的软件（IDE、代理、别的本地服务）占着。
- **不做的代价**：用户看到的是「数据不对」或「版本没生效」—— 这两类症状在本仓历史上都被误判为**缓存没刷**（`docs/agents/ops.md` 第 11 条整节在处理这个误判），排查成本以小时计。

---

## 2. 用户旅程与核心流程

### 2.1 正常路径（≤3 步）

1. 双击 `DeLector.exe` → 进程启动即取全局锁（**早于**任何数据目录迁移与服务导入）→ 8000 空闲 → 正常出窗。
2. 再次双击（同一版本、锁被持有）→ 弹窗「DeLector 已在运行（vX.Y.Z，pid N）」→ 退出码 0（**不是** 3，因为它不是失败）。
3. `python start.py` 走在同一判定上 → 提示 + 打开 `http://127.0.0.1:<实际端口>`。

### 2.2 分支路径（每支都必须有人话 + 日志）

| 条件 | 行为 | 退出码 |
| --- | --- | --- |
| 锁被持有，**版本不同** | 弹窗/文案带双方版本：「旧版本 v5.18.0 仍在运行（pid N），请先退出再启动 v5.19.0」 | 3（桌面）/ 1（start.py） |
| 锁被持有，**数据目录不同** | 同上并列出两个目录（本地弹窗，不进 HTTP） | 3 / 1 |
| 锁被持有，读不出内容（空/损坏） | 「已有 DeLector 实例在运行（版本未知）」——**不猜、不复用** | 3 / 1 |
| 锁可用，8000 被**无关程序**占 | 静默顺延 `8002–8010`；日志与横幅写明实际端口 | 0 |
| 锁可用，8002–8010 全占 | 人话报错并列占用者提示 | 3 / 1 |
| 锁文件**建不出来**（只读介质/权限） | 记 WARNING，回退到现有端口+身份探测路径（行为等于今天） | 按现状 |

### 2.3 摩擦点与刻意不做

- **刻意不做「把已有窗口提到前台」**：pywebview 的跨进程窗口激活需要 Win32 `FindWindow`/`SetForegroundWindow` 与窗口标题契约，属另一条能力线；本设计的诚实做法是「告诉你在跑，然后退出」。
- **刻意不做「允许并发实例」**：见 §0 与 §6。

---

## 3. 架构与数据模型

### 3.1 新模块：`delector/core/instance_lock.py`

**边界**：纯 IO + 平台锁原语；**不得**在模块级 import `database`（同 `data_dir_bootstrap` 的硬约束，见
`tests/test_desktop_data_dir_bootstrap.py:478-488`），**不得** import FastAPI。

```text
@dataclass(frozen=True)
class LockRecord:
    pid: int
    version: str        # APP_VERSION
    port: int           # 实际监听端口（拿到锁后回写）
    data_dir: str       # resolve_data_dir(env) 的结果；仅用于本地提示，不出现在任何 HTTP 响应里
    acquired_at: str    # ISO8601，仅供人工排障

@dataclass(frozen=True)
class LockPaths:
    lock: str           # <dir>/instance.lock —— **只被 flock 锁，永不替换**
    meta: str           # <dir>/instance.json —— 元数据，原子替换
    @staticmethod
    def for_platform(env: Mapping[str, str]) -> "LockPaths": ...
        """Windows: %LOCALAPPDATA%\DeLector\；POSIX: ~/.local/share/DeLector\。
        **刻意不做** Android / 便携版分支：这条路径与数据目录无关（全局唯一）。"""

@dataclass
class LockHandle:       # 持有期间 MUST 保持锁 fd 打开；release() 幂等
    paths: LockPaths
    record: LockRecord
    def release(self) -> None: ...

def try_acquire(paths: LockPaths, record: LockRecord) -> LockHandle | LockRecord
    """拿到锁 → LockHandle；被持有 → 返回**对方**的 LockRecord（读不出/读不全则返回 unknown 记录）"""
def write_record(handle: LockHandle, record: LockRecord) -> None
    """端口/数据目录确定后回写 meta：临时文件 + os.replace，读者永远看到完整 JSON"""
```

> **为什么锁与元数据分两个文件（实现期才发现的硬约束，必须照办）**：POSIX 上 `flock` 锁的是
> **inode**，不是路径。若对同一个文件 `os.replace(tmp, lock)`，旧 fd 仍锁着已被 unlink 的旧 inode，
> 下一个进程打开新 inode 就能成功加锁 —— **锁静默失效**（正是本设计要消除的那类失败）。
> 因此 `instance.lock` 只做锁目标、内容可为空且永不替换；元数据单独放 `instance.json` 走原子替换。
> 代价：读元数据必须容忍「锁被持有但 meta 缺失/半截」⇒ 归入 §4 的 unknown 分支，**不新增**判定路径。

**平台锁原语**（先例：vault `vault_transaction.py` 的 `acquire_lock`，同一套三档降级）：

- Windows：`msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)`（先 `seek(0)`，锁 1 字节）。
- POSIX：`fcntl.flock(fd, LOCK_EX | LOCK_NB)`。
- 两者均不可用：**降级为「仅按锁文件内容判定」** + 写 stderr WARNING，并在日志里明确「本次不是真互斥」。
  **不得静默**（`tools/check_silent_degradation.py` 会抓裸 `except: pass`）。

**生命周期**：锁随 fd 关闭由 OS 释放 ⇒ 崩溃自愈；**不做 pid 探活启发式**（pid 复用与「刚死未回收」都会骗人）。
正常退出在 `coordinated_shutdown` 之后显式 `release()`（幂等，只为让下一个实例的提示更干净）。

### 3.2 启动编排（单一判定点）

新增 `start.claim_instance(env) -> Decision`，`desktop.py` 与 `start.py` **共用**（沿用 `desktop.py:887`
「惰性 import `start`，不另写一套」的既有做法）：

```text
Decision = Ready(port: int, lock: LockHandle) | AlreadyRunning(record: LockRecord, reason: str)
```

顺序（**每一步都有不变量**）：

1. `resolve_data_dir(env)` —— 纯函数，无副作用（`data_dir_bootstrap.py:118`），只用于填充提示字段。
2. `try_acquire(LockPaths.for_platform(env), record)` —— **必须先于** `bootstrap_data_dir`：迁移会移动文件，
   并发迁移是当前未设防的窗口。
3. 未拿到锁 ⇒ 按 §2.2 分支返回 `AlreadyRunning`，调用方负责弹窗/文案后退出（**不再调 `open_browser` 前先判版本**）。
4. 拿到锁 ⇒ 选端口：`--port` 显式给定时只用它（占用即报错，**不顺延** —— 显式意图优先）；
   否则从 `8000` 起、跳过 `8001`、止于 `8010` 取第一个 `is_port_in_use()` 为假者。
5. `bootstrap_data_dir(env)` → `write_record(handle, 最终 record)`（数据目录可能因迁移失败回退）。
6. 端口经 `app.state.server_port` 暴露给路由（见 §3.3）。

> **对既有守卫的影响（必须显式登记）**：`tests/test_desktop_data_dir_bootstrap.py:402-409` 的
> `_is_delector_import` 只允许 `delector.core.data_dir_bootstrap` 出现在 `bootstrap_data_dir` **之前**。
> 本设计需要在它之前 import `delector.core.instance_lock` ⇒ **白名单加一项**，并补一条同款窄守卫
> `test_instance_lock_module_does_not_import_database`（证明它不会冻结 `DATA_DIR`）。
> 这是**前提更新**，不是放宽：原断言「bootstrap 早于 `delector.server`」一字不动。

### 3.3 `lan-info` 真端口（L1 修复）

`delector/routes/backup.py:179` 的 `"port": 8000` 改为读 `getattr(request.app.state, "server_port", 8000)`：
- 装配期写入：`start.py` / `desktop.py` 在 `build_server` 之后 `app.state.server_port = port`。
- 默认 8000 保留给 `TestClient`（测试不设 state 时行为不变）、Android（固定 8000）与旧装配路径。
- **绝不用 `request.url.port`**：它来自 `Host` 头，可被伪造，而这条响应是给手机端拼地址用的。

### 3.4 集成点与明确边界

- **Go supervisor 不受本锁保护**：`agent/internal/pythonsvc/supervisor.go:34` 直接
  `python -m uvicorn delector.server:app`（不走 `start.py`），端口固定 8001。它与用户直启实例
  **仍可同时打开同一个库**（SQLite WAL 允许）。本设计**不覆盖**该路径，理由见 §6。
- **Android**：`bootstrap_data_dir` 返回空串（`data_dir_bootstrap.py:258-259`）⇒ `claim_instance` 直接返回
  `Ready(8000)`，不取锁、不改行为。

---

## 4. 边界情况与韧性

| 场景 | 设计响应 | 依据 |
| --- | --- | --- |
| 进程被任务管理器杀掉 | OS 释放锁，锁文件残留但**可被重新获取**（内容会在下次写入时被覆盖） | `flock`/`LockFile` 语义；不依赖内容判断存活 |
| 锁文件内容半截/非 JSON | 拿到锁的条件下**直接覆盖**（内容只是元数据）；拿不到锁时返回 unknown 记录并给通用文案 | 与「不复用未知身份」一致 |
| 两个进程**同时**首启 | 只有一个能拿到 OS 锁 ⇒ 失败方按 AlreadyRunning 处理；**不留 TOCTOU** | 锁在端口探测之前 |
| 端口探测与 bind 之间被抢 | 起服失败由既有 `await_ready` 总截止 + splash 失败路径接住（`desktop.py` Task 3），**不新增**重试逻辑 | 避免与 ADR-0018 Unknown 8 的探测改造撞车 |
| `--port` 显式指定且被占 | 直接报错，不顺延（显式意图优先，避免「我让你开 9000 你却开了 9001」） | 最小惊讶 |
| 锁目录不可写 | WARNING + 回退现状（端口+身份探测），**不阻断启动** | 启动失败比降级更糟 |
| 便携版 + 安装版同时想跑 | 第二个被明确拒绝，并说明对方版本与数据目录 | 全局单实例（§0） |

---

## 5. 测试策略

**单元（新文件 `tests/test_instance_lock.py`）**
1. 同进程二次 `try_acquire` 返回对方 record（两个独立 fd）。
2. `release()` 后同进程可再取；`release()` 幂等。
3. 内容损坏/空文件：被持有时返回 unknown；可获取时被覆盖且写后内容可解析。
4. 写记录用 `os.replace` 写 `instance.json`：并发读只会看到完整 JSON（要么旧、要么新）；
   **且 `instance.lock` 的 inode/句柄在回写后不变**（防「替换后锁失效」回归哨兵）。
5. `LockPaths.for_platform` 在 Windows/POSIX 两种 env 下的字面值（用 `monkeypatch` 注入 `LOCALAPPDATA`/`HOME`）。

**跨进程（一条真子进程用例，`tests/test_instance_lock_subprocess.py`）**
6. 子进程持有锁 → 父进程 `try_acquire` 拿不到，且 record 的 pid/version 与子进程一致；子进程退出后父进程可取到。
   —— 现有 `test_desktop_*` 全是 `monkeypatch`，**盖不住真锁语义**（这是本设计唯一的不可替代用例）。

**编排（扩 `tests/test_desktop_port_guard.py` / `tests/test_start.py`）**
7. 版本不同 ⇒ 拒绝且文案含双方版本；版本相同 ⇒ 复用分支（`start.py`）/ 拒绝分支（`desktop.py`，行为不变）。
8. 8000 被无关程序占、8002 空 ⇒ `Decision.port == 8002`；`8001` **永不**被选中（回归哨兵）。
9. `--port 9000` 被占 ⇒ 报错，不落到 9001。
10. 源码顺序守卫：`claim_instance` 在 `main()` 内、早于 `from delector.server import app`（扩 `:431` 那条用例）。

**接口（扩 `tests/test_server_*.py`）**
11. `app.state.server_port = 8007` ⇒ `/api/wb/lan-info` 返回 8007；未设 ⇒ 8000（兼容 TestClient）。

**验证命令**（逐字复刻 CI 口径，不全绿不算完成）
```bash
python -m pytest tests/test_instance_lock.py tests/test_instance_lock_subprocess.py \
                 tests/test_desktop_port_guard.py tests/test_start.py tests/test_desktop_data_dir_bootstrap.py -q
python -m pytest tests/ -q                      # 单进程串行；本机并行会争数据目录守卫造成假红
ruff check .
python -m mypy --strict delector tools
python -m mypy --follow-imports=skip tests
python tools/check_layer_invariants.py && python tools/check_silent_degradation.py
```

---

## 6. 未决项与范围边界

> 本节的每一项都**已收敛为决定**：要么做，要么明确不做并写清理由。

**已解决的技术未知（实测收敛，不留到实现期）**

| 未知 | 结论 | 证据 |
| --- | --- | --- |
| 锁放数据目录还是全局？ | 全局 | ADR-0019 §6.4；本节末「否决项」 |
| 顺延起点是 8001 吗？ | 从 8002 起 | `agent/internal/pythonsvc/doc.go:9-10` 已把 8001 定为 supervisor 保留端口 |
| 身份探测还留吗？ | 留，降为锁不可用时的第二腿 | §3.2 |
| 锁内容能进 `/api/health` 吗？ | **不能**（`data_dir` 绝不出 HTTP） | 红线⑦同类：LAN 可读端点不得泄露本地路径 |
| pid 探活吗？ | 不 | 自愈交给 OS 锁语义 |

**明确不做（Out of Scope）**

1. **不做 per-data-dir 多实例**：允许便携版与安装版并存会带来两套窗口/托盘/端口，而真实需求未验证（YAGNI）。
   要做的话，锁路径改为数据目录、并补「两实例共享 `lan-address.txt`」的处置 —— 属另一次立项。
2. **不给 Go supervisor 加锁**：它按设计常驻 8001 并管理 Python 子进程，与用户直启实例共享库是**既有**行为；
   改它会牵动 supervisor 的崩溃退避与预算闸，超出本次范围。
3. **不做窗口激活/单例转发**（见 §2.3）。
4. **不动 `is_port_in_use` 的 ~2s 探测成本**：那是 ADR-0018 Unknown 8 的独立议题。本设计**不承诺**冷启动提速，
   即便快路径上少了一次身份探测。
5. **不改 `probe_identity` 的契约**（接受 503、只比 `app`）：它是既有守卫，收紧会波及 `await_ready` 与桌面壳。

---

## Self-Review Checklist

- [x] 零占位符：§6 的五个未知全部收敛为决定或明确不做。
- [x] 无隐藏范围蔓延：只碰启动编排、锁模块、`lan-info` 一处端口来源；不动 supervisor / Android / 探测成本。
- [x] Ladder of Reuse：平台锁用 stdlib（`msvcrt`/`fcntl`），先例为 vault `vault_transaction.py`；不引第三方依赖。
- [x] 与既有机械闸相容：不新增裸 `except`（`check_silent_degradation`）、模块级不 import `database`（`test_desktop_data_dir_bootstrap.py:478`）。
- [x] 三处推翻初判均已标注（§0），避免实现者照着对话里的旧结论写。
