#!/usr/bin/env python3
"""
DeLector - Cross-Platform Instant Launcher
Auto-detects port availability, LAN IP, and launches default browser.
"""

import argparse
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Callable, Mapping, Optional, Sequence

# 为什么必须在最顶部就把 stdout/stderr 重配成 utf-8（本仓既有写法，见 package_windows.py 顶部）：
# 下面那条启动横幅用 print() 打中文，而**被重定向到文件的 stdout 在 Windows 上默认按 locale/ANSI
# 编码打开**（CI runner 上是 cp1252，本机是 GBK）⇒ 打中文直接抛 UnicodeEncodeError ⇒ 进程退出 1。
# 而"输出被重定向 / 被日志采集 / 由服务或计划任务拉起"正是"当服务用"最常见的环境 —— 不加固等于
# 这些场景下根本起不来（`DeLector.exe --server-only` 启动即崩，实测原始报错 position 13-28 即标题行汉字）。
# 先判 `sys.stdout`/`sys.stderr` 是否为 None（--windowed 冻结后可能为 None）；errors="replace" 保证
# 即便重配失败也不会因一个字符崩掉整个进程。
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 数据落点必须在 `import server` **之前**定下来：`delector.core.database` 在被 import 的
# 那一瞬就按"当时的 env"算出 DATA_DIR，之后再设 DELECTOR_DATA_DIR 毫无作用 —— 于是数据
# 仍落在程序目录里，用户"解压新版覆盖旧目录 / 删掉旧目录"= 学习记录全空且零提示
# （ADR-0019 Q2-A / Q3-B）。真正的调用在 `main()` 开头的第一个语句处（见那里的注释）。
from delector.core.data_dir_bootstrap import bootstrap_data_dir, resolve_data_dir

# 单实例锁模块排在 bootstrap 导入**之后**（spec §3.2 要求抢锁先于搬库；这里只借位置表达
# 「同属启动前哨」）。放模块顶层是安全的：它只吃 stdlib、不在模块级 import `delector.database`
# —— 由 `tests/test_desktop_data_dir_bootstrap.py::test_instance_lock_module_does_not_import_database`
# 钉住，那条用例正是 `_BOOTSTRAP_SAFE_IMPORTS` 放行它的唯一凭据。
from delector.core.instance_lock import (
    UNKNOWN_RECORD,
    LockHandle,
    LockPaths,
    LockRecord,
    read_record,
    try_acquire,
    write_record,
)


def _ensure_entry_streams(debug_console: bool) -> None:
    """跨平台入口复用桌面壳的 launch.log 标准流收口。

    整段（含 `from desktop import ...`）都在 try 里，是**刻意的**：Android APK 的 Python 源集
    只有 `start.py` + `delector/`（见 .github/workflows/build-release.yml：只 `cp -r
    start.py`，**没有** `cp desktop.py`），而 APK 入口正是 `py.getModule("start")
    .callAttr("main")`（MainActivity.java）⇒ 这里一句硬 import 就会在 `main()` 首行抛
    ModuleNotFoundError，被 Java 侧 `catch (Throwable)` 兜成「Python 引擎异常」，**APK 起不来**。
    而 Android 上 `sys.stdout` 本就不是 None（Chaquopy 重定向到 logcat）⇒ 这次收口在 Android 上
    恒为 no-op，却换来一次致命崩溃。故：收口失败时宁可不留痕，也绝不得阻断启动。
    """
    try:
        from desktop import ensure_streams, resolve_log_path

        ensure_streams(resolve_log_path(os.environ), debug_console)
    except Exception:
        return


def _noop_signal_context(*_args: object, **_kwargs: object) -> AbstractContextManager[None]:
    """空 context manager：替代 uvicorn 的 capture_signals（Android 子线程禁信号用）。"""
    return nullcontext()


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        # getsockname() 被 typeshed 标成 Any（地址族相关）；AF_INET 下 [0] 本就是 str，
        # 声明成 str 只做静态收窄、不改运行时值，顺带消掉 no-any-return。
        ip: str = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def is_android() -> bool:
    """是否跑在 Chaquopy/Android 运行时里。"""
    return hasattr(sys, "getandroidapilevel") or "ANDROID_ROOT" in os.environ


def get_bind_host() -> str:
    """桌面端绑 0.0.0.0 是有意的特性（同 Wi-Fi 的手机/平板可访问）。

    Android 上只有应用内的 WebView 需要连本机，绑 0.0.0.0 等于把无鉴权的
    POST /api/settings（可改写 API Key 与 base_url）暴露给整个局域网。
    """
    return "127.0.0.1" if is_android() else "0.0.0.0"


# ── 单实例判定（spec 2026-10-21 §3.2）──────────────────────────────────────────
#
# 为什么判定必须收敛到**一个**函数：`main()`、桌面壳（`desktop.py`）与日后的 supervisor 都要问
# 同一句「这台机器上是不是已经有一个 DeLector 在跑、它是谁」。判据各抄一份就会漂成「壳说没有、
# 服务说有两个」—— 那类缺陷不报错、只让用户看到两个窗口抢同一个库，且事后无法归因。

#: 端口候选。8000 是历史默认；**8001 刻意不在表里** —— 它是 Go supervisor 的保留端口
#: （`agent/internal/pythonsvc/doc.go:9-10`），抢到它等于和 supervisor 争同一个监听点。
PORT_CANDIDATES: tuple[int, ...] = (8000, 8002, 8003, 8004, 8005, 8006, 8007, 8008, 8009, 8010)

#: 全局硬约束「8001 是 Go supervisor 的保留端口，MUST 永不选中」的实现点。仅靠 `PORT_CANDIDATES`
#: 不含它只挡住了**自动顺延**；显式 `requested_port=8001`（壳 / supervisor / 用户传参）照样会被
#: 直接返回 —— 那就是和 supervisor 争同一个监听点，两个进程里必有一个起不来且原因看日志都像
#: 「端口神秘被占」。故显式值也要过这道闸。
SUPERVISOR_RESERVED_PORT: int = 8001


@dataclass(frozen=True)
class Ready:
    """本进程即那个实例：`port` 已选定、`lock` 已持有（调用方退出/失败时 MUST `lock.release()`）。"""

    port: int
    lock: LockHandle


@dataclass(frozen=True)
class AlreadyRunning:
    """已有实例在跑（或端口被占）：`reason` 说明凭什么这么判，`record` 是对方身份。

    ⚠️ 上层 MUST 按 `reason` 分派，MUST NOT 按 `record` 分派：`no_free_port` / `port_busy`
    没有可归因的对方实例，`record` 只能复用 `UNKNOWN_RECORD`（pid=0/port=0 的占位值）——
    拿它当「对方是谁」去读，会把「端口全占」讲成「有个身份不明的实例在跑」。
    """

    record: LockRecord
    reason: str


def _held_reason(record: LockRecord, data_dir: str) -> str:
    """锁被持有时归因，顺序即优先级：`unknown` > `version_mismatch` > `data_dir_mismatch` > `same`。

    为什么 `unknown` 排最前：`pid == 0` 是 `UNKNOWN_RECORD` 的形态（meta 缺失 / 半截 / 读不动）。
    此时 `version` 与 `data_dir` 都是占位值，拿它们继续比会得出「版本不同」这种**假结论**，
    上层照着提示「请升级对方」——用户升级完依旧起不来，而他手里的两个解释都是错的。

    `port <= 0` 也是同一档：抢到锁到回写端口之间有一个**合法的中间态**（`claim_instance` 先以
    `port=0` 占位抢锁，选定端口后才回写）。别人恰好读到这一刻，pid / 版本 / 目录全都对得上，
    但端口还是占位的 `0` —— 若照 `same` 归因，上层会拼出 `http://127.0.0.1:0` 这种指不到任何
    东西的地址。故端口未回写一律视为「身份未知」，宁可让用户重试，也不给假地址。

    ⚠️ 这一档的**常态成因是对方正在启动**（它要逐个探 10 个候选端口，最坏 ~20s），而不是
    「上一个死进程留下的残骸」。故上层文案 MUST NOT 断言「残留进程」—— 那会让用户去杀掉一个
    完全健康的实例（见 `_report_already_running` 的兜底分支）。
    """
    if record.pid == 0 or record.port <= 0:
        return "unknown"
    if record.version != _app_version():
        return "version_mismatch"
    # 规范化后再比：`D:\DeLector\data` 与 `d:\delector\data\` 是同一个目录。纯字符串比较会把
    # 「同一份库」误判成 `data_dir_mismatch`，上层于是提示「另一份库的实例在跑」—— 用户照做
    # 只会关掉本该复用的那一个。`normcase` 在 POSIX 上是恒等，故不影响大小写敏感平台。
    if os.path.normcase(os.path.normpath(record.data_dir)) != os.path.normcase(os.path.normpath(data_dir)):
        return "data_dir_mismatch"
    return "same"


def _pick_port(
    probe: Callable[[int], bool],
    requested: Optional[int],
    busy_sink: Optional[list[int]] = None,
) -> Optional[int]:
    """选定端口；无可用端口返回 `None`。

    显式 `requested` **只试它、不顺延**：调用方（壳 / supervisor / 用户）已经对外承诺了那个
    地址（地址文件、反代、hosts），偷偷换一个端口等于让承诺的地址永远连不上；宁可报
    `port_busy` 让上层去决定。反之遍历候选时必须顺延，否则「8000 被别的程序占」就直接起不来。

    `busy_sink`：把**探测为被占用**的端口按序收集起来，供身份探测（第二腿）复用。为什么不另写
    一个循环再探一次：`is_port_in_use` 单次真实成本 ~2s（ADR-0018 Unknown 8），最坏情形下重探
    一遍等于把启动时延翻倍；端口占用状态本身就是这次探测的结果，没有第二次获取的必要。
    """
    if requested is not None:
        # 显式指定也 MUST 过保留端口闸：8001 是 Go supervisor 的监听点（见 `SUPERVISOR_RESERVED_PORT`），
        # 抢到它等于和 supervisor 争同一个端口。按「不可用」处理，让上层落 `port_busy` —— 那正是
        # 事实：这个端口对本进程永远不可用，与此刻有没有人在听无关，故**不调 probe**。
        if requested == SUPERVISOR_RESERVED_PORT:
            return None
        if not probe(requested):
            return requested
        if busy_sink is not None:
            busy_sink.append(requested)
        return None
    for port in PORT_CANDIDATES:
        if not probe(port):
            return port
        if busy_sink is not None:
            busy_sink.append(port)
    return None


def _note(message: str) -> None:
    """启动期提示：stderr 可用就照旧（与既有风格一致），被收口成 None 时退到 logger，绝不静默。

    为什么不能只 `print(..., file=sys.stderr)`：`--windowed`/`pythonw` 桌面壳下 `sys.stderr`
    是 **None**，CPython 对 `file=None` 的 `print` 是**直接丢弃**（不报错、不落任何地方）——
    于是「端口被占用改用了别的端口」「元数据回写失败」这类只能靠日志归因的提示在桌面端
    100% 消失，用户只看到地址变了却零线索。
    """
    if sys.stderr is not None:
        print(message, file=sys.stderr)
        return
    logging.getLogger("delector").warning(message)


def _android_ready(env: Mapping[str, str]) -> Ready:
    """Android 的短路结果：不取锁、不探端口。

    两个理由：① Android 的数据落点由宿主（`MainActivity`）注入 `DELECTOR_DATA_DIR`，本进程
    替它猜一个锁目录只会造出一把与真实实例无关的锁；② 监听口由 WebView 侧约定，候选顺延在
    移动端没有意义。返回的句柄是**降级句柄**（`_fd == -1`，`release()` 是幂等空操作），
    这样调用方仍可统一写 `lock.release()`，不必为移动端分支记第二套约定。
    """
    port = PORT_CANDIDATES[0]
    record = LockRecord(
        pid=os.getpid(),
        version=_app_version(),
        port=port,
        data_dir=resolve_data_dir(env),
        # 这条记录不会被写盘（没有锁文件），时间戳留空以避免伪造「何时抢到锁」的痕迹。
        acquired_at="",
    )
    return Ready(port=port, lock=LockHandle(paths=LockPaths.for_platform(env), record=record))


def _identity_holder(
    handle: LockHandle,
    data_dir: str,
    busy: Sequence[int],
    identity_probe: Callable[[int], bool],
) -> Optional[AlreadyRunning]:
    """第二腿：锁降级时，在**被占的候选端口**上找 DeLector 身份；找到就返回 `AlreadyRunning`。

    为什么必须有这一腿：锁降级的成因（目录只读 / 权限不足 / 无锁原语）恰好也是「另一个
    DeLector 同样抢不到锁」的成因。此时「候选端口被占」≠「陌生程序」——若直接顺延，就会
    起**第二个服务**、两个进程改同一个库，正是本计划要消灭的缺陷。

    为什么"找到"不一定是 `same`：端口上是 DeLector，但它可能来自另一个版本 / 另一份库
    （meta 里写着自己是谁）。归因仍走 `_held_reason`（同一套优先级，不接受第二套口径）；
    唯一例外是 meta 读不出（`UNKNOWN_RECORD`，pid==0/port==0 的占位值）——**线上已经探到
    DeLector 身份**，此时再按占位值讲「版本不同」就是假话，故收敛为 `same`。
    """
    for port in busy:
        if not identity_probe(port):
            continue
        # meta 可能是别人（或上一次运行）留下的：读得出就带上版本/目录，读不出就是占位记录；
        # 两种情况下端口都以**探到的**为准 —— 那是唯一可验证的事实。
        record = replace(read_record(handle.paths) or UNKNOWN_RECORD, port=port)
        reason = _held_reason(record, data_dir)
        return AlreadyRunning(record=record, reason="same" if reason == "unknown" else reason)
    return None


def claim_instance(
    env: Mapping[str, str],
    requested_port: Optional[int] = None,
    probe: Optional[Callable[[int], bool]] = None,
    identity_probe: Optional[Callable[[int], bool]] = None,
) -> Ready | AlreadyRunning:
    """单实例判定的唯一入口：先抢锁、再选端口。

    顺序为什么不能反（计划 Task 4 GREEN 的硬要求）：先探端口再抢锁，等于在「另一个实例正在
    监听」的噪声里判断可用性 —— 顺延时会把对方实例的端口当成「被陌生人占用」，报错话术与
    真实原因不符；更糟的是探测与抢锁之间的窗口里可能又冒出第三个进程。

    `identity_probe`（可选）：锁**降级**时（`LockHandle.is_degraded`）的第二腿 —— 此时锁没有权威，
    「候选端口被占」既可能是陌生程序、也可能是另一个同样抢不到锁的 DeLector。对**被跳过的**
    端口逐个问它，答是 ⇒ 判 `AlreadyRunning`（绝不顺延起第二个服务）。拿到**真锁**时一律不调：
    锁是唯一判据（见 `tests/test_start.py::test_claim_instance_skips_identity_probe_when_lock_is_real`）。
    """
    if is_android():
        return _android_ready(env)

    # `probe` 必须在**函数体内**求值：写成默认参数 `probe=is_port_in_use` 会在 import 期把当时的
    # 函数对象焊死，测试 monkeypatch `start.is_port_in_use` 就完全失效（判据看着在跑、实际恒真）。
    probe_fn: Callable[[int], bool] = probe or is_port_in_use
    # 落点先解析：它既是判据（和对方的 data_dir 比），也要写进自己的记录供下一个进程读。
    data_dir = resolve_data_dir(env)
    paths = LockPaths.for_platform(env)

    # 端口此刻还不知道 ⇒ 先以 `port=0` 抢锁（记录里 0 只表示「还没定」），选定端口后回写。
    acquired = try_acquire(
        paths,
        LockRecord(
            pid=os.getpid(),
            version=_app_version(),
            port=0,
            data_dir=data_dir,
            acquired_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        ),
    )
    if isinstance(acquired, LockRecord):
        # 被持有 ⇒ 读到的就是对方身份（读不出时 `try_acquire` 已收敛成 `UNKNOWN_RECORD`）。
        return AlreadyRunning(record=acquired, reason=_held_reason(acquired, data_dir))

    handle = acquired
    # 从这里到 `return Ready(...)` 之间的每一步都可能抛：`_pick_port` 的 `probe` 是外部注入的
    # （生产实现 `is_port_in_use` 在 fd 耗尽时会抛 `OSError`），`write_record` 也可能是
    # `TypeError`/`ValueError` 之外的异常。异常穿出而不释放 fd ⇒ 锁被一个已经失败的进程
    # 攥着 ⇒ 同进程后续 claim（以及用户重开）全被判「已在运行」的**假红**。
    # `BaseException` 而非 `Exception`：`KeyboardInterrupt` 同样必须放锁，否则 Ctrl+C 之后
    # 进程还没退出就再也起不来了。
    # 句柄是否**降级**（`is_degraded`：目录建不出来 / 文件打不开 / 无锁原语）决定了「端口被占」该怎么读：
    # 真锁在手 ⇒ 锁是唯一判据，被占的端口一定是别人的（**不**调身份探测，避免多一次 HTTP 往返，
    # 也避免让陌生程序有机会冒充自己）；降级 ⇒ 锁没有权威，必须补上第二腿（见 `_identity_holder`）。
    # 读 `LockHandle.is_degraded` 而不是跨模块点 `handle._fd`：`_fd` 是 instance_lock 的私实现细节
    # （将来换成 HANDLE/句柄对象就变），降级这件事必须由那个模块自己回答。
    degraded = handle.is_degraded
    identity_fn: Optional[Callable[[int], bool]] = identity_probe if degraded else None
    busy: list[int] = []
    try:
        port = _pick_port(probe_fn, requested_port, busy if identity_fn is not None else None)
        # 身份判定 MUST 早于「用上刚选到的空闲端口」：降级锁下 8000 上的 DeLector 只是抢不到锁，
        # 顺延到 8002 就会变成两个服务同时改一个库 —— 那正是本计划要消灭的缺陷。故先看被跳过的
        # 那些端口上是不是自己人，是则整体放弃启动（而不是"占个别的口先跑起来"）。
        holder = None if identity_fn is None else _identity_holder(handle, data_dir, busy, identity_fn)
        if holder is not None:
            handle.release()
            return holder
        if port is None:
            # 早退**必须**先释放锁：残留的锁会让下一次启动（含同进程的下一条用例）被判成
            # 「已有实例在运行」—— 症状是本进程明明退出了，用户每次重开都被告知"已在运行"。
            handle.release()
            reason = "port_busy" if requested_port is not None else "no_free_port"
            return AlreadyRunning(record=UNKNOWN_RECORD, reason=reason)

        if requested_port is None and port != PORT_CANDIDATES[0]:
            # No Silent Fallback：默认端口被别的程序占走时，用户看到的地址会变 —— 必须自己说出来，
            # 否则「为什么我在 8000 打不开」只能靠猜。
            _note(f"[提示] 端口 {PORT_CANDIDATES[0]} 被占用，改用 {port}。")

        record = replace(handle.record, port=port)
        try:
            write_record(handle, record)
        except OSError as exc:
            # 回写失败只影响「别人看到哪个端口」，不影响互斥、也不影响本进程将要监听的那个端口
            # ⇒ 留痕后继续（与 instance_lock.try_acquire 的降级口径一致），不把启动挡在门外。
            _note(f"[警告] 单实例元数据回写失败（{exc}）：其他实例可能读到旧端口。")
        # 句柄里的 record 也要跟上：`Ready.lock.record.port` 是调用方唯一能读到的"我占了哪个口"。
        handle.record = record
        return Ready(port=port, lock=handle)
    except BaseException:
        # `release()` 幂等，故与上面 `port is None` 分支的显式释放不冲突。
        handle.release()
        raise


def open_browser(port: int) -> None:
    time.sleep(1.2)
    # Support Android Termux termux-open-url fallback
    if os.environ.get("TERMUX_VERSION") or os.path.exists("/data/data/com.termux"):
        os.system(f"termux-open-url http://localhost:{port}")
    else:
        webbrowser.open(f"http://127.0.0.1:{port}")


def _address_lines(port: int, android: bool) -> list[str]:
    """横幅里的地址行（Android 只监听回环、桌面端还会给出局域网地址，故两者文案不同）。"""
    if android:
        return [f"  ● 仅本机监听: http://127.0.0.1:{port} (应用内 WebView)"]
    lines = [f"  ● 电脑本机访问: http://localhost:{port}"]
    ip = get_local_ip()
    if ip != "127.0.0.1":
        lines.append(f"  ● 手机/平板访问: http://{ip}:{port} (同一 Wi-Fi 局域网)")
    return lines


def print_banner(port: int, android: bool) -> None:
    """打印启动横幅（含中文）。

    为什么抽成独立函数：这是"重定向流下打中文会崩"那条缺陷的落点，抽出来后回归锁可在真子进程里
    直接调用它、精确复现"敌意流"（见 tests/test_start_banner_encoding.py），不必真起服务。
    """
    print("=" * 60)
    print("  DeLector — 德语欧标沉浸阅读与考点剖析工作台")
    print("=" * 60)
    for line in _address_lines(port, android):
        print(line)
    print("=" * 60)
    print("  按 Ctrl+C 停止服务\n")


def _say(message: str) -> None:
    """面向用户的启动文案：stdout 可用就照旧，被收口成 None（`pythonw`/窗口化）时退到 logger。

    与 `_note` 的差别只在**默认落点**：`_note` 面向排障（stderr / 日志），`_say` 面向用户
    （正常输出）。两者都必须对 `sys.stdout is None` 免疫 —— 否则桌面端「已在运行」这类
    唯一线索会被 `print(..., file=None)` 静默丢弃。
    """
    if sys.stdout is not None:
        print(message)
        return
    logging.getLogger("delector").warning(message)


def _fail(message: str) -> None:
    """启动失败：正常控制台下**只**写 stdout，然后退出码 1。

    为什么不再同时写 stdout 与 stderr：正常控制台里两条流都指向同一个屏幕 ⇒ 用户会看到同一行
    错误**两遍**（第一遍是噪音，第二遍让人以为是两个不同的错）。排障需要的是「被收口」时仍在——
    `sys.stdout` 为 None（`pythonw` / `--windowed` 桌面壳）才退到 `_note`（stderr / 日志）那条路。
    同一个字符串，不另拟文案；两路都不会静默丢弃，故「为什么没起来」始终留痕。
    """
    if sys.stdout is not None:
        print(message)
    else:
        _note(message)
    sys.exit(1)


def _describe_holder(record: LockRecord) -> str:
    """把对方身份拼成一段人话（只列**已知**字段，绝不给占位值）。"""
    parts: list[str] = []
    if record.version and record.version != UNKNOWN_RECORD.version:
        parts.append(f"v{record.version}")
    if record.pid > 0:
        parts.append(f"pid {record.pid}")
    # `port <= 0` 是「端口还没回写」的占位值：写出来会得到 `端口 0` 这种指不到任何东西的地址。
    if record.port > 0:
        parts.append(f"端口 {record.port}")
    return "，".join(parts)


def _report_already_running(decision: AlreadyRunning, android: bool) -> None:
    """`AlreadyRunning` 的分派点：**按 `reason` 分派**（`record` 只用来读身份字段）。

    按 `record` 分派会出错：`port_busy` / `no_free_port` 根本没有可归因的对方实例，`record`
    只能是 `UNKNOWN_RECORD`（pid=0/port=0 的占位值）—— 拿它当「对方是谁」，就会把「端口全被
    别的软件占着」讲成「有个身份不明的 DeLector 在跑」，用户于是去关一个并不存在的窗口。

    三种结局：
    - `same` ⇒ 人话 + （非 Android）**先复核**对方端口确实响应 `/api/health` 再打开页面，
      **正常返回**（退出码 0：用户看到的就是既有实例）。
    - `port_busy` / `no_free_port` ⇒ 说「端口不可用」并退出 1。**刻意不提**「已在运行」：
      那不是同一件事（见上）。
    - 其余（`unknown` / `version_mismatch` / `data_dir_mismatch`）⇒ 说明差异后退出 1：
      用户要做的是关掉/升级旧实例，盲目顺延只会得到两个进程改同一个库。
    """
    record = decision.record
    reason = decision.reason
    if reason == "same":
        detail = _describe_holder(record)
        # 不变式：**绝不为一个不响应 `/api/health` 的端口打开页面**（ADR-0020 §6.4）。
        # `record` 可能是上一次运行留下的陈旧 meta（`write_record` 失败只 WARNING ⇒ 端口仍是旧值），
        # 此时 `record.port` 上未必真有一个 DeLector；照旧开页面等于把用户扔到一个打不开的地址，
        # 且用户无法判断"是不是已经在跑"。故开页面之前用 `_identity_probe` 复核一次。
        # 退出码仍为 0（正常返回，不 `sys.exit`）：对方确实存在且持锁（`same` 的判据是锁，不是端口），
        # 端口无响应只是**暂态**（它可能正在逐个探候选端口，最坏 ~20s）—— 以 1 结束会让桌面壳 /
        # supervisor 把"本该复用的实例"当成启动失败并反复重启，反过来对健康实例造成启动风暴。
        if not android and not _identity_probe(record.port):
            _say(
                f"[提示] DeLector 已在运行（{detail}），但该端口无响应"
                "（可能正在启动或已退出）。请稍等几秒后重试。"
            )
            return
        _say(f"[提示] DeLector 已在运行（{detail}），正在打开已有页面...")
        if not android:
            open_browser(record.port)
        return
    if reason == "port_busy":
        _fail("[错误] 端口不可用：指定的端口已被其他程序占用，无法启动 DeLector。")
        return
    if reason == "no_free_port":
        first, last = PORT_CANDIDATES[0], PORT_CANDIDATES[-1]
        _fail(f"[错误] 端口不可用：{first}–{last} 全部被其他程序占用，无法启动 DeLector。请关闭占用端口的程序后重试。")
        return
    if reason == "version_mismatch":
        _fail(
            f"[错误] 这台机器上已有一个 DeLector 在运行，但版本不同"
            f"（正在运行 v{record.version}，本程序 v{_app_version()}）。请关闭它后再启动。"
        )
        return
    if reason == "data_dir_mismatch":
        _fail(
            f"[错误] 这台机器上已有一个 DeLector 在运行，但它使用的是另一份数据目录"
            f"（{record.data_dir}）。请关闭它后再启动。"
        )
        return
    # 兜底落在 `unknown`：锁被持有但身份读不出来（meta 缺失 / 半截 / 端口未回写）。
    # 不猜版本也不猜端口 —— 那两个字段此刻都是占位值，说出来只会误导。
    # 文案 MUST NOT 断言「残留进程」：`port == 0` 的常态成因是对方**正在启动**（逐个探候选端口，
    # 最坏 ~20s）—— 照「残留」讲，用户会去杀掉一个健康实例，本进程照样起不来（锁仍被持有）。
    _fail(
        "[错误] 这台机器上已有一个 DeLector 在运行，但读不到它的版本与端口信息"
        "（实例信息缺失或损坏）。若刚刚双击过图标，请稍等几秒再试；"
        "若持续如此，请先关闭正在运行的 DeLector 再重新启动。"
    )


def main(
    debug_console: bool = False,
    on_serving: Optional[Callable[[int], None]] = None,
    no_agent: bool = False,
) -> None:
    _ensure_entry_streams(debug_console)
    android = is_android()
    # 单一判定点（spec §3.2）：抢锁 → 选端口 → 归因。`identity_probe` 只在**锁降级**时被用到
    # （见 `claim_instance` 的 `degraded` 分支）：真锁在手时锁是唯一判据，不额外发 HTTP 探测。
    decision = claim_instance(os.environ, identity_probe=_identity_probe)
    if isinstance(decision, AlreadyRunning):
        # 已有实例 / 端口不可用 / 身份存疑：这里 MUST 早退，且**早于** bootstrap_data_dir ——
        # 别人的库不能动（Windows 上改名会被占用挡住），`delector.server` 也不必 import。
        _report_already_running(decision, android)
        return

    ready = decision
    # 端口从此只来自 `ready.port`：横幅、浏览器、build_server、on_serving 全部用它。
    port = ready.port
    # `finally` 放锁是**硬要求**（不是"顺手清理"）：锁是文件级的，同进程里反复调 `main()` 的测试
    # 若漏放，后面的用例会被判「已在运行」而集体假红；真实用户侧则表现为 Ctrl+C 之后再也起不来
    # （进程还在退出中，锁仍被自己的 fd 攥着）。
    agent_sup: Optional[Any] = None
    try:
        # ⚠️ 必须在 `from delector.server import app` **之前**执行：那一行一跑，`database`
        # 已按仓库根把 DATA_DIR 落定，此时再设 DELECTOR_DATA_DIR 就晚了。
        bootstrap_data_dir(os.environ)

        if not android and not no_agent:
            try:
                from delector.core.go_agent_supervisor import GoAgentSupervisor

                agent_sup = GoAgentSupervisor(port=8002, python_port=port)
                if agent_sup.start(deadline_s=5.0):
                    print("[伴学] Go Agent 伴学服务已自动托管启动 (http://127.0.0.1:8002)")
                else:
                    print("[伴学] 未检测到 Go 环境或启动超时，伴学功能由 Python 内核自适应兜底")
            except Exception as a_err:
                print(f"[伴学] 伴学服务托管尝试跳过 ({a_err})，由 Python 内核兜底")

        host = get_bind_host()
        print_banner(port, android)

        if not android:
            threading.Thread(target=open_browser, args=(port,), daemon=True).start()

        from delector.core.server_lifecycle import SHUTDOWN_GRACE_S, build_server, serve_in_thread, shutdown
        from delector.server import app

        server = build_server(host, port, app)
        # Task 5：端口校验已过（由 `claim_instance` 选定，被占的端口根本不会被返回）、
        # `uvicorn.Server` 已组装 ⇒ 调用方（desktop `--server-only`）据此写对外可见的地址文件。
        # 写入 MUST 晚于"确认本进程将持有该端口"：端口不可用 / 启动失败时根本到不了这里，
        # 故绝不留下指向错误目标的地址。
        if on_serving is not None:
            on_serving(port)
        try:
            # 禁用信号处理：Android Chaquopy 在子线程里跑 server，而 signal.signal 只允许
            # 在 Python 主线程调用。注意 uvicorn 的 API 随版本迁移（0.52 起只有
            # capture_signals，install_signal_handlers 已不存在）——两代都覆盖，
            # 否则「防护」会静默失效成一条没人调用的实例属性（mypy 抓到这个失效）。
            if threading.current_thread() is not threading.main_thread():
                # 用 setattr(名字字符串) 覆盖两代 API：按名字赋值绕开静态属性检查（不同 uvicorn
                # 版本声明的属性不一样，直接点属性访问会被 mypy 判 attr-defined/method-assign），
                # 行为与直接属性赋值逐字一致 —— 不必写 `# type: ignore`（禁新增豁免）。
                setattr(server, "install_signal_handlers", lambda: None)  # 旧 uvicorn API
                setattr(server, "capture_signals", _noop_signal_context)  # 新 uvicorn API
        except Exception:
            pass
        # 非 daemon 线程里跑 server，主线程 join 等待；Ctrl+C 时先收尸再退出 —— 这替代了
        # 原来裸 `server.run()` 的「无退出控制」，消除「壳退了服务还残留」的静默失败。
        thread = serve_in_thread(server)
        try:
            # 轮询式等待（**每次 join 都带显式超时**，禁裸等）：语义仍是「主线程陪 server 到结束」，
            # 但单次等待封在 SHUTDOWN_GRACE_S 内（与 shutdown() 的宽限同口径，不另发明数字）——
            # 裸 join() 一旦线程不结束就无上界，整个退出路径会被它吞掉。Ctrl+C 打断的正是这一次
            # join（KeyboardInterrupt 从 join 抛出），仍走下方收尸分支。
            while True:
                thread.join(timeout=SHUTDOWN_GRACE_S)
                if not thread.is_alive():
                    break
        except KeyboardInterrupt:
            print("\n[提示] 收到停止信号，正在收尸...")
        # join 之后再收一次是**有意保留**的兜底：覆盖 KeyboardInterrupt 之外的退出路径。
        # `shutdown` 是幂等的（置 should_exit + join 一个已结束的线程都无副作用），重复调用安全
        # —— 勿当成"重复 shutdown 的 bug"删除。
        if not shutdown(server, thread):
            # 尊重返回值（旧代码丢弃它并无条件报「已停止」＝假成功）：停不干净必须可见 —— 人话进
            # stderr（无控制台时由流收口落 launch.log），退出码 1（干净退出才是 0）。继续静默返回
            # 的后果：解释器退出时 threading._shutdown() 再 join 这个非 daemon 线程 ⇒ 进程挂住、
            # 端口仍占 ⇒ 下次启动会撞上一个连自己都关不掉的实例。
            print("[错误] 服务未能干净退出（端口可能仍被占用）。", file=sys.stderr)
            sys.exit(1)
        print("[提示] 服务已停止。")
    finally:
        if agent_sup is not None:
            try:
                agent_sup.stop()
            except Exception:
                pass
        # `release()` 幂等（降级句柄是空操作 ⇒ Android 分支同样安全）。放在最外层 `finally`
        # 而不是 shutdown 之后：`bootstrap_data_dir` / `build_server` / `on_serving` 任一步抛，
        # 锁都必须被放开 —— 一个已经失败的进程攥着锁，等于用户每次重开都被告知「已在运行」。
        ready.lock.release()


def _identity_probe(port: int) -> bool:
    """第二腿：回答「这个端口上是不是 DeLector」（`claim_instance` 的 `identity_probe` 实参）。

    只在**锁降级**时才会被调用（见 `claim_instance` 的 `degraded` 分支）：真锁在手时锁是唯一
    判据，不该为陌生程序留一次「冒充自己」的机会，也不该白付一次 HTTP 往返。

    惰性 import 的理由与 `_handle_existing_port` 同款：`delector.core.server_lifecycle` 不在
    `_BOOTSTRAP_SAFE_IMPORTS` 白名单里，模块级导入会撞
    `tests/test_desktop_data_dir_bootstrap.py::test_start_py_bootstrap_precedes_every_delector_import`
    （该闸钉「bootstrap 调用早于任何 `delector.*` 导入」）。
    """
    from delector.core.server_lifecycle import probe_identity

    # 显式落到 bool 局部变量：入口面 mypy 闸带 `--follow-imports=skip`
    # （`.github/workflows/ci.yml`），被跳过的模块符号退化成 `Any` ⇒ 直接 `return`
    # 会报 `no-any-return`（本地不带该 flag 时是绿的，故这是**只在 CI 暴露**的那类红）。
    identity: bool = probe_identity(port)
    return identity


def _handle_existing_port(port: int, android: bool) -> None:
    """端口已被占用时的处理：先分辨占用者是不是 DeLector 自己，再决定动作。

    - 是 DeLector（`probe_identity` 为真，含库坏时的 503）⇒ 保持既有行为：提示 + 打开
      浏览器指向已有实例，然后返回（不重复起服务）。
    - 不是 DeLector ⇒ 明确报错并退出，**绝不**为无关程序打开页面（ADR-0020 §6.4）。

    **当前无生产调用者**：`main()` 自 Task 6 起按 `AlreadyRunning.reason` 分派（见
    `_report_already_running`），桌面壳走自己的 `_check_port_or_fail`（`desktop.py:873-921`），
    故本函数唯一引用者是 `tests/test_desktop_shell.py`。Task 7 把桌面壳改用 `claim_instance`
    后应删除此函数或改薄包装 —— 现在保留只是暂不删，避免提前改动桌面端行为。

    这里用**惰性 import** 而非文件顶部导入：本函数定义在 main() 之后，其 import 语句
    的行号才大于 main() 里 `bootstrap_data_dir(...)` 的调用行号 —— 否则会撞上
    tests/test_desktop_data_dir_bootstrap.py::test_start_py_bootstrap_precedes_every_delector_import
    （那条闸钉「bootstrap 必须早于任何 delector.* 导入」，以保 DATA_DIR 在被冻结前定好）。
    """
    from delector.core.server_lifecycle import probe_identity

    if probe_identity(port):
        print(f"[提示] DeLector 已在端口 {port} 运行，正在打开已有页面...")
        if not android:
            open_browser(port)
        return
    print(f"[错误] 端口 {port} 已被其他程序占用，无法启动 DeLector。")
    print("       请关闭占用该端口的程序，或结束残留的 DeLector 进程后重试。")
    sys.exit(1)


def _app_version() -> str:
    """取应用版本号（`claim_instance` 判「对方版本是否不同」的唯一来源）。

    这个函数**必须定义在 `main()` 之后**，理由与 `_handle_existing_port` 的惰性 import 同款：
    `tests/test_desktop_data_dir_bootstrap.py::test_start_py_bootstrap_precedes_every_delector_import`
    按**全模块最小行号**判「bootstrap 调用早于任何 `delector.*` 导入」，而 `delector.core.version`
    不在 `_BOOTSTRAP_SAFE_IMPORTS` 白名单里 ⇒ 这段 import 一旦落在 `main()` 之前，守卫就转红。
    `version` 是纯 stdlib 叶模块，惰性导入零成本，也不会碰 `database`。
    """
    from delector.core.version import APP_VERSION

    # 同 `_identity_probe`：`--follow-imports=skip` 下 `APP_VERSION` 是 `Any`，必须显式收窄。
    version: str = APP_VERSION
    return version


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """解析跨平台入口的调试控制台与伴学守护运行时开关。"""
    parser = argparse.ArgumentParser(prog="start.py", description="DeLector 跨平台启动器。")
    parser.add_argument(
        "--debug-console",
        action="store_true",
        help="调试时挂回控制台，不把缺失的标准流收口到 launch.log",
    )
    parser.add_argument(
        "--no-agent",
        action="store_true",
        help="禁用自动拉起 Go 伴学 Agent 子进程，强制由 Python 内核服务",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    # 先收口、后解析（Task 1，理由同 desktop.py 的 __main__）：None 流下 argparse 的
    # `--help`/错参输出无处可写 ⇒ 用户零线索。复用 main() 同款 `_ensure_entry_streams`
    # （整段包 try/except：Android APK 的 Python 源集没有 desktop.py，而 APK 上 sys.stdout
    # 本就不是 None，收口失败也不得阻断启动）。debug 开关从原始 argv 探。
    _ensure_entry_streams("--debug-console" in sys.argv[1:])
    _args = _parse_args(sys.argv[1:])
    main(debug_console=_args.debug_console, no_agent=_args.no_agent)
