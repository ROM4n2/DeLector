r"""Task1 Step3: 平台绑定行为测试 — Android vs Desktop get_bind_host()

Task4 追加：`claim_instance` —— 单实例判定的**唯一**入口（spec 2026-10-21 §3.2）。

为什么这组用例一律把锁落点钉到 `tmp_path`
----------------------------------------
`claim_instance` 会**真去取锁**（`instance_lock.try_acquire`），而桌面默认落点是
`%LOCALAPPDATA%\DeLector`。不注入落点就等于：跑一次测试在本机的真实数据目录里留下一把
锁与一份 `instance.json`，并让后续用例（甚至用户自己的实例）被误判成「已有实例在运行」。
故每条用例都经 `_pin_lock_dir` 把 `LockPaths.for_platform` 指向 `tmp_path`。

同理：任何拿到的 `Ready.lock` 都 MUST 在 finally 里 `release()` —— 锁是文件级的，
同进程的下一条用例会真的撞上它（那是假红，不是缺陷）。
"""

import logging
import sys
import types
from pathlib import Path

import pytest

import start
from delector.core import instance_lock
from delector.core.version import APP_VERSION


def test_get_bind_host_on_android(monkeypatch):
    monkeypatch.setattr(start, "is_android", lambda: True)
    assert start.get_bind_host() == "127.0.0.1"


def test_get_bind_host_on_desktop(monkeypatch):
    monkeypatch.setattr(start, "is_android", lambda: False)
    assert start.get_bind_host() == "0.0.0.0"


def test_get_bind_host_android_loopback_only(monkeypatch):
    """Android 上必须只监听回环：POST /api/settings 无鉴权，绑 0.0.0.0 会暴露给整个局域网。"""
    monkeypatch.setattr(start, "is_android", lambda: True)
    host = start.get_bind_host()
    assert host == "127.0.0.1"
    assert host != "0.0.0.0"


def test_get_bind_host_desktop_allows_lan(monkeypatch):
    """桌面端有意绑 0.0.0.0 以允许同 Wi-Fi 设备访问文章。"""
    monkeypatch.setattr(start, "is_android", lambda: False)
    assert start.get_bind_host() == "0.0.0.0"


# ── Task 4：claim_instance 单一判定点 ────────────────────────────────────────────
def _pin_lock_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> instance_lock.LockPaths:
    """把锁落点定到 `tmp_path`，并返回这份落点（供断言「锁有没有被释放」时复用）。

    为什么 patch 的是 `instance_lock.LockPaths.for_platform` 而不是 `start.LockPaths`：
    `start` 拿到的是**同一个类对象**，在类上换方法对一切引用方生效；将来实现改回
    `from ... import LockPaths` 或改成 `instance_lock.LockPaths(...)` 都不影响本注入点。
    """
    paths = instance_lock.LockPaths(
        lock=str(tmp_path / "instance.lock"),
        meta=str(tmp_path / "instance.json"),
    )
    monkeypatch.setattr(instance_lock.LockPaths, "for_platform", staticmethod(lambda env: paths))
    return paths


def _hold_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: str,
    data_dir: str,
    pid: int = 424242,
    port: int = 8004,
) -> tuple[instance_lock.LockPaths, instance_lock.LockHandle]:
    """模拟「另一个实例已持锁」，并让它把身份（版本 / 数据目录）写进 meta。

    用**真锁**而不是 patch `try_acquire`：Windows 的字节区间锁对同进程的另一个 fd 同样
    冲突（实测 `msvcrt.locking` 返回 EACCES ⇒ `try_acquire` 返回对方 `LockRecord`），
    所以这里能把「抢锁失败 → 读对方身份」整条真实链路验掉，不必伪造。
    """
    paths = _pin_lock_dir(tmp_path, monkeypatch)
    holder = instance_lock.try_acquire(
        paths,
        instance_lock.LockRecord(
            pid=pid,
            version=version,
            port=port,
            data_dir=data_dir,
            acquired_at="2026-10-21T00:00:00",
        ),
    )
    assert isinstance(holder, instance_lock.LockHandle), "前提失败：模拟实例没能拿到锁"
    return paths, holder


def test_claim_instance_ready_on_free_8000(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """8000 空闲 ⇒ `Ready(8000)`，且回写后的 `record.port` 必须是真端口而非占位的 0。"""
    _pin_lock_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(start, "is_port_in_use", lambda port: False)

    result = start.claim_instance({"DELECTOR_DATA_DIR": str(tmp_path / "data")})

    assert isinstance(result, start.Ready), f"锁空闲时应拿到 Ready，实际 {result!r}"
    try:
        assert result.port == 8000
        assert result.lock.record.port == 8000, "Ready.lock.record.port 必须是选定端口（抢锁时只能先写 0）"
    finally:
        result.lock.release()


def test_claim_instance_uses_patched_probe_not_a_welded_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """`monkeypatch start.is_port_in_use` 必须真生效：钉住「probe 默认值在函数体内求值」。

    这条用例是**变异自证**过的（旧版是死绿）：判据必须让「patch 生效」与「默认参数焊死」
    两条路径**必然分叉**，否则两者结果相同、无论实现怎么写都绿。
    做法：patch 后只声明 8000 被占 ⇒ 生效时顺延到 8002；焊死时（用真实探测）本机 8000 空闲
    ⇒ 返回 8000 ⇒ 断言立刻转红。旧版只 patch 成「全部空闲」，焊死路径同样返回 8000，故恒绿。
    """
    _pin_lock_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(start, "is_port_in_use", lambda port: port == 8000)

    result = start.claim_instance({"DELECTOR_DATA_DIR": str(tmp_path / "data")})

    assert isinstance(result, start.Ready), f"8002 应可用，实际 {result!r}"
    try:
        assert result.port == 8002, (
            "patch 未生效（probe 被默认参数焊死）⇒ 会拿到真实探测的 8000；"
            f"期望顺延到 8002，实际 {result.port}"
        )
        assert result.lock.record.port == 8002
        assert result.port != start.SUPERVISOR_RESERVED_PORT
    finally:
        result.lock.release()


def test_claim_instance_skips_busy_ports_and_never_picks_reserved_8001(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """8000 与 8001 被占 ⇒ 顺延到 8002；**永不**选 8001（哨兵），且顺延必须留痕。"""
    assert 8001 not in start.PORT_CANDIDATES, (
        "8001 是 Go supervisor 的保留端口（agent/internal/pythonsvc/doc.go:9-10），"
        "不得进入候选：抢到它等于和 supervisor 抢同一个端口"
    )
    _pin_lock_dir(tmp_path, monkeypatch)
    busy = {8000, 8001}

    result = start.claim_instance(
        {"DELECTOR_DATA_DIR": str(tmp_path / "data")},
        probe=lambda port: port in busy,
    )

    assert isinstance(result, start.Ready), f"还有空闲候选时应拿到 Ready，实际 {result!r}"
    try:
        assert result.port == 8002
        assert result.port != 8001
        assert result.lock.record.port == 8002
        err = capsys.readouterr().err
        assert "8000" in err and "8002" in err, (
            f"顺延必须写一条含新旧端口的日志（No Silent Fallback），实际 stderr={err!r}"
        )
    finally:
        result.lock.release()


def test_claim_instance_reports_no_free_port_and_releases_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """8000–8010 全占 ⇒ `no_free_port`，且**必须已释放锁**（否则后续启动全被判「已在运行」）。"""
    paths = _pin_lock_dir(tmp_path, monkeypatch)

    result = start.claim_instance({"DELECTOR_DATA_DIR": str(tmp_path / "data")}, probe=lambda port: True)

    assert isinstance(result, start.AlreadyRunning), f"无端口可选时应是 AlreadyRunning，实际 {result!r}"
    assert result.reason == "no_free_port"
    assert result.record == instance_lock.UNKNOWN_RECORD, "这种情况没有可归因的对方实例 ⇒ 只能是 unknown 记录"

    reacquired = instance_lock.try_acquire(paths, instance_lock.UNKNOWN_RECORD)
    assert isinstance(reacquired, instance_lock.LockHandle), (
        "放弃端口时必须释放锁：残留的锁会让下一次启动（以及同进程的下一条用例）被误判成「已有实例在运行」"
    )
    reacquired.release()


def test_claim_instance_reports_version_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """锁被持有且版本不同 ⇒ `version_mismatch`，回执带**对方**版本（上层据此提示升级）。"""
    data_dir = str(tmp_path / "data")
    _, holder = _hold_lock(tmp_path, monkeypatch, version="0.9.9", data_dir=data_dir)
    probed: list[int] = []

    def probe(port: int) -> bool:
        probed.append(port)
        return False

    try:
        result = start.claim_instance({"DELECTOR_DATA_DIR": data_dir}, probe=probe)

        assert isinstance(result, start.AlreadyRunning), f"锁被持有时应是 AlreadyRunning，实际 {result!r}"
        assert result.reason == "version_mismatch"
        assert result.record.version == "0.9.9", "回执必须带对方版本，否则用户看不到「该升级了」"
        assert probed == [], "锁都没抢到就去探端口：探测本身有意义，但顺序必须是先锁后探（计划 GREEN 明确要求）"
    finally:
        holder.release()


def test_claim_instance_reports_data_dir_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """锁被持有、版本相同但数据目录不同 ⇒ `data_dir_mismatch`（另一份库的实例在跑）。"""
    data_dir = str(tmp_path / "data")
    _, holder = _hold_lock(tmp_path, monkeypatch, version=APP_VERSION, data_dir=str(tmp_path / "other"))
    try:
        result = start.claim_instance({"DELECTOR_DATA_DIR": data_dir}, probe=lambda port: False)

        assert isinstance(result, start.AlreadyRunning), f"锁被持有时应是 AlreadyRunning，实际 {result!r}"
        assert result.reason == "data_dir_mismatch"
        assert result.record.data_dir == str(tmp_path / "other")
    finally:
        holder.release()


def test_claim_instance_requested_port_busy_does_not_fall_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """`requested_port=9000` 且被占 ⇒ `port_busy`，**不**落到 9001（显式指定就是唯一目标）。"""
    paths = _pin_lock_dir(tmp_path, monkeypatch)
    probed: list[int] = []

    def probe(port: int) -> bool:
        probed.append(port)
        return port == 9000

    result = start.claim_instance(
        {"DELECTOR_DATA_DIR": str(tmp_path / "data")},
        requested_port=9000,
        probe=probe,
    )

    assert isinstance(result, start.AlreadyRunning), f"指定端口被占时应是 AlreadyRunning，实际 {result!r}"
    assert result.reason == "port_busy"
    assert probed == [9000], f"requested_port 给定时只许试它，绝不能顺延（实际探测 {probed}）"

    reacquired = instance_lock.try_acquire(paths, instance_lock.UNKNOWN_RECORD)
    assert isinstance(reacquired, instance_lock.LockHandle), "port_busy 早退同样必须释放锁"
    reacquired.release()


def test_claim_instance_rejects_explicit_reserved_8001(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """显式 `requested_port=8001` ⇒ `port_busy`：8001 是 supervisor 的监听点，永远不许选。

    `PORT_CANDIDATES` 不含 8001 只挡住**自动顺延**；显式传参走的是另一条路径，必须同样过闸。
    且 8001 对本进程恒不可用（与此刻有没有人在听无关）⇒ 连 probe 都不该调。
    """
    paths = _pin_lock_dir(tmp_path, monkeypatch)
    probed: list[int] = []

    def probe(port: int) -> bool:
        probed.append(port)
        return False  # 空闲也不许要

    result = start.claim_instance(
        {"DELECTOR_DATA_DIR": str(tmp_path / "data")},
        requested_port=start.SUPERVISOR_RESERVED_PORT,
        probe=probe,
    )

    assert isinstance(result, start.AlreadyRunning), f"保留端口应被判不可用，实际 {result!r}"
    assert result.reason == "port_busy"
    assert probed == [], f"保留端口与探测结果无关，不该去 probe（实际探测 {probed}）"

    reacquired = instance_lock.try_acquire(paths, instance_lock.UNKNOWN_RECORD)
    assert isinstance(reacquired, instance_lock.LockHandle), "保留端口早退同样必须释放锁"
    reacquired.release()


def test_claim_instance_unknown_when_holder_has_no_pid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """`pid == 0` 的持有者记录（meta 缺失 / 半截）⇒ `unknown`，且**优先级**高于版本比较。

    反证方式：这条记录同时把版本与数据目录都写成「不同」—— 若实现先比版本，会得出
    `version_mismatch`；那个结论是假的（占位值不携带任何信息），用户照着「请升级对方」
    升级完依旧起不来。
    """
    data_dir = str(tmp_path / "data")
    _, holder = _hold_lock(
        tmp_path, monkeypatch, version="0.9.9", data_dir=str(tmp_path / "other"), pid=0
    )
    try:
        result = start.claim_instance({"DELECTOR_DATA_DIR": data_dir}, probe=lambda port: False)

        assert isinstance(result, start.AlreadyRunning), f"锁被持有时应是 AlreadyRunning，实际 {result!r}"
        assert result.reason == "unknown", (
            f"pid==0 必须最先归因 unknown（先比版本会得到假的 version_mismatch），实际 {result.reason}"
        )
    finally:
        holder.release()


def test_claim_instance_unknown_when_holder_port_not_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """端口未回写的中间态（`port == 0`）⇒ `unknown`，绝不归 `same`。

    `claim_instance` 先以 `port=0` 抢锁、选定端口后才回写；别人恰好读到这一刻时 pid / 版本 /
    目录全都对得上，但端口还是 0 —— 归 `same` 会让上层拼出 `http://127.0.0.1:0`。
    这里版本与目录**完全相同**，唯一能挡住 `same` 的就是端口判据。
    """
    data_dir = str(tmp_path / "data")
    _, holder = _hold_lock(tmp_path, monkeypatch, version=APP_VERSION, data_dir=data_dir, port=0)
    try:
        result = start.claim_instance({"DELECTOR_DATA_DIR": data_dir}, probe=lambda port: False)

        assert isinstance(result, start.AlreadyRunning), f"锁被持有时应是 AlreadyRunning，实际 {result!r}"
        assert result.reason == "unknown", (
            f"端口未回写必须归 unknown（否则上层会拼出 :0 的地址），实际 {result.reason}"
        )
    finally:
        holder.release()


def test_claim_instance_reports_same_instance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """同版本、同数据目录 ⇒ `same`，回执带对方端口（上层据此直接打开已有页面）。"""
    data_dir = str(tmp_path / "data")
    _, holder = _hold_lock(tmp_path, monkeypatch, version=APP_VERSION, data_dir=data_dir)
    try:
        result = start.claim_instance({"DELECTOR_DATA_DIR": data_dir}, probe=lambda port: False)

        assert isinstance(result, start.AlreadyRunning), f"锁被持有时应是 AlreadyRunning，实际 {result!r}"
        assert result.reason == "same"
        assert result.record.port == 8004, "same 时上层要拿对方端口去开页面"
    finally:
        holder.release()


def test_claim_instance_treats_equivalent_paths_as_same(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """`<dir>/data/../data` 与 `<dir>/data` 是同一目录 ⇒ `same`，不是 `data_dir_mismatch`。

    纯字符串比较会把同一份库误判成「另一份库的实例在跑」，用户于是关掉本该复用的那个实例。
    （`normcase` 的大小写折叠在 Windows 上同样归到这里：`D:\\X` 与 `d:\\x\\` 亦须判同。）
    """
    data_dir = str(tmp_path / "data")
    _, holder = _hold_lock(
        tmp_path, monkeypatch, version=APP_VERSION, data_dir=str(tmp_path / "data" / ".." / "data")
    )
    try:
        result = start.claim_instance({"DELECTOR_DATA_DIR": data_dir}, probe=lambda port: False)

        assert isinstance(result, start.AlreadyRunning), f"锁被持有时应是 AlreadyRunning，实际 {result!r}"
        assert result.reason == "same", (
            f"等价路径必须规范化后再比（实际 {result.reason}，对方 data_dir={result.record.data_dir!r}）"
        )
    finally:
        holder.release()


def test_claim_instance_on_android_never_takes_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Android 短路：`Ready(8000)` 且**不**创建任何锁文件（降级句柄 `is_degraded`）。

    Android 的数据落点由宿主注入，本进程替它猜一个锁目录只会造出一把与真实实例无关的锁。
    """
    paths = _pin_lock_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(start, "is_android", lambda: True)

    result = start.claim_instance({"DELECTOR_DATA_DIR": str(tmp_path / "data")})

    assert isinstance(result, start.Ready), f"Android 应直接给 Ready，实际 {result!r}"
    assert result.port == start.PORT_CANDIDATES[0]
    assert result.lock.is_degraded, "Android 必须是降级句柄（release() 为空操作）"
    assert not Path(paths.lock).exists(), f"Android MUST NOT 创建锁文件：{paths.lock}"


def test_claim_instance_releases_lock_when_probe_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """`probe` 抛异常（生产实现 fd 耗尽时抛 `OSError`）⇒ 异常穿出，但锁 MUST 已释放。

    不释放 ⇒ 一个已经失败的进程攥着锁 ⇒ 同进程后续 claim（以及用户重开）全被判「已在运行」。
    """

    def boom(port: int) -> bool:
        raise OSError("fd 耗尽")

    paths = _pin_lock_dir(tmp_path, monkeypatch)

    with pytest.raises(OSError):
        start.claim_instance({"DELECTOR_DATA_DIR": str(tmp_path / "data")}, probe=boom)

    reacquired = instance_lock.try_acquire(paths, instance_lock.UNKNOWN_RECORD)
    assert isinstance(reacquired, instance_lock.LockHandle), "probe 抛异常必须放锁，否则后续启动全是假红"
    reacquired.release()


def test_claim_instance_notes_reach_logger_when_stderr_is_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """`sys.stderr is None`（`pythonw` 桌面壳常态）时顺延提示 MUST 落到 logger，不得静默消失。

    CPython 对 `print(..., file=None)` 是直接丢弃、不报错 ⇒ 只写 `print` 的实现在桌面端 100%
    丢失「端口被占用改用了别的端口」这条唯一的归因线索。
    """
    _pin_lock_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(start.sys, "stderr", None)

    with caplog.at_level(logging.WARNING, logger="delector"):
        result = start.claim_instance(
            {"DELECTOR_DATA_DIR": str(tmp_path / "data")}, probe=lambda port: port == 8000
        )

    assert isinstance(result, start.Ready), f"8002 应可用，实际 {result!r}"
    try:
        assert "8000" in caplog.text and "8002" in caplog.text, (
            f"无 stderr 时顺延提示必须进 logger（No Silent Fallback），实际日志={caplog.text!r}"
        )
    finally:
        result.lock.release()


# ── Task 6：main() 接线（claim → 端口 → bootstrap → serve；finally 放锁）────────────
def _patch_serving(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[tuple[str, int]], types.SimpleNamespace]:
    """把 uvicorn 装配链换成替身：既断言 `main()` 的接线，又不真起服务、不拉 spaCy。

    与 `tests/test_start_lifecycle.py` 同款手法（patch `server_lifecycle` 的四个入口 +
    `sys.modules` 里放一个假 `delector.server`）—— 那里验的是生命周期语义，这里验的是
    「claim 的结果有没有被真的接到 build_server / on_serving 上」。
    """
    from delector.core import server_lifecycle

    built: list[tuple[str, int]] = []
    fake_server = types.SimpleNamespace(should_exit=False)

    def _build(host: str, port: int, app: object) -> object:
        built.append((host, port))
        return fake_server

    class _FinishedThread:
        """替身线程：join 立即返回、is_alive 恒 False。"""

        daemon = False

        def join(self, *_args: object, **_kwargs: object) -> None:
            return None

        def is_alive(self) -> bool:
            return False

    monkeypatch.setitem(sys.modules, "delector.server", types.SimpleNamespace(app=object()))
    monkeypatch.setattr(server_lifecycle, "build_server", _build)
    monkeypatch.setattr(server_lifecycle, "serve_in_thread", lambda server: _FinishedThread())
    monkeypatch.setattr(server_lifecycle, "shutdown", lambda *_a, **_k: True)
    return built, fake_server


def test_main_exits_without_importing_server_when_lock_held_by_other_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """锁被另一版本持有 ⇒ 退出码 1、**不** import `delector.server`、**不**搬库、不写地址。

    为什么钉「不 import `delector.server`」而不是只钉退出码：那一行一跑，`database` 就按
    当时的 env 把 DATA_DIR 落定，还会拉起 spaCy —— 一个注定要退出的进程没理由付这笔账，
    而且「判出已有实例 ⇒ 绝不动它的库」正是本设计的不变量。
    实现方式：往 `sys.modules` 塞一个**属性访问即炸**的哨兵模块；`from delector.server
    import app` 一旦执行就会撞上它（不是靠"恰好没导入"这种弱断言）。
    """

    class _ServerSentinel(types.ModuleType):
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"判出「已在运行」时不得 import delector.server（触发了 {name}）")

    data_dir = str(tmp_path / "data")
    monkeypatch.setenv("DELECTOR_DATA_DIR", data_dir)
    _, holder = _hold_lock(tmp_path, monkeypatch, version="0.0.1-legacy", data_dir=data_dir)
    monkeypatch.setattr(start, "is_android", lambda: False)
    monkeypatch.setattr(start, "open_browser", lambda port: pytest.fail("版本不同 ⇒ 不得为它打开页面"))
    monkeypatch.setattr(
        start, "bootstrap_data_dir", lambda *_a, **_k: pytest.fail("已有实例在跑时不得动它的库")
    )
    monkeypatch.setitem(sys.modules, "delector.server", _ServerSentinel("delector.server"))

    try:
        with pytest.raises(SystemExit) as excinfo:
            start.main()
    finally:
        holder.release()

    assert excinfo.value.code == 1, f"实例冲突必须以退出码 1 结束，实际 {excinfo.value.code!r}"
    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert "0.0.1-legacy" in text and APP_VERSION in text, (
        f"文案必须同时给出双方版本，用户才知道该升级哪一个；实际输出={text!r}"
    )
    assert "Traceback" not in text, f"面向用户的文案不得含堆栈：{text!r}"


def test_main_serves_on_fallback_port_when_8000_is_taken_by_foreign_program(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """8000 被无关程序占 ⇒ 服务必须建在 claim 选定的 8002 上（`on_serving` 也拿到 8002）。

    这里是**接线**断言：`Ready.port` 必须一路传到横幅 / 浏览器 / `build_server` / `on_serving`；
    任何一处仍写死 8000，用户/壳拿到的地址就与实际监听点不一致。
    """
    _pin_lock_dir(tmp_path, monkeypatch)
    built, _ = _patch_serving(monkeypatch)
    ready = start.Ready(
        port=8002,
        lock=instance_lock.LockHandle(
            paths=instance_lock.LockPaths(
                lock=str(tmp_path / "instance.lock"), meta=str(tmp_path / "instance.json")
            ),
            record=instance_lock.UNKNOWN_RECORD,
        ),
    )
    monkeypatch.setattr(start, "claim_instance", lambda *_a, **_k: ready)
    monkeypatch.setattr(start, "is_android", lambda: True)  # 只绑回环、且不起浏览器线程
    monkeypatch.setattr(start, "bootstrap_data_dir", lambda *_a, **_k: "")
    served: list[int] = []

    start.main(on_serving=served.append)

    assert served == [8002], f"on_serving 必须收到顺延后的端口，实际 {served}"
    assert built == [("127.0.0.1", 8002)], f"build_server 必须建在顺延端口上，实际 {built}"


def test_main_opens_browser_for_same_instance_and_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """锁被**同一**实例持有 ⇒ 打印人话 + 打开对方端口，然后正常返回（不 sys.exit、不起服务）。"""
    data_dir = str(tmp_path / "data")
    monkeypatch.setenv("DELECTOR_DATA_DIR", data_dir)
    _, holder = _hold_lock(tmp_path, monkeypatch, version=APP_VERSION, data_dir=data_dir, port=8006)
    built, _ = _patch_serving(monkeypatch)
    opened: list[int] = []
    monkeypatch.setattr(start, "is_android", lambda: False)
    monkeypatch.setattr(start, "open_browser", lambda port: opened.append(port))
    # `same` 分支开页面前会用 `_identity_probe` 复核对方端口（ADR-0020 §6.4）。这里替身回「是
    # DeLector」：本用例钉的是「识别为同一实例 ⇒ 打开对方端口并返回」，不钉复核逻辑
    # （复核为假的分支由 `test_main_does_not_open_browser_when_same_instance_port_is_silent` 钉）。
    # 不 patch 就会去打真实的 127.0.0.1:8006（本机无监听）⇒ 判「无响应」⇒ 用例假红。
    monkeypatch.setattr(start, "_identity_probe", lambda port: True)
    monkeypatch.setattr(
        start, "bootstrap_data_dir", lambda *_a, **_k: pytest.fail("已有实例在跑时不得动它的库")
    )

    try:
        start.main()  # 不得抛 SystemExit（退出码 0 的语义就是"正常返回"）
    finally:
        holder.release()

    assert opened == [8006], f"必须打开**对方**的端口（不是写死的 8000），实际 {opened}"
    assert built == [], f"识别为同一实例时绝不能再建第二个 server，实际 {built}"
    out = capsys.readouterr().out
    assert "8006" in out and "424242" in out, f"人话里必须点名端口与 pid，实际输出={out!r}"


def test_main_reports_unavailable_ports_without_claiming_an_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """8000–8010 全被占 ⇒ 退出码 1，且文案说的是「端口不可用」而**不是**「已有实例在运行」。

    两件事必须区分：端口被陌生程序占住，跟「另一个 DeLector 在跑」完全无关；讲混了用户会去
    关一个并不存在的窗口，而真正的元凶（别的软件）永远没被提到。
    """
    _pin_lock_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(start, "is_android", lambda: False)
    monkeypatch.setattr(start, "is_port_in_use", lambda _port: True)
    monkeypatch.setattr(start, "open_browser", lambda port: pytest.fail("端口不可用时不得打开页面"))

    with pytest.raises(SystemExit) as excinfo:
        start.main()

    assert excinfo.value.code == 1, f"没有可用端口必须以退出码 1 结束，实际 {excinfo.value.code!r}"
    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert "8000" in text, f"文案必须点名被占的端口，实际 {text!r}"
    assert "已在" not in text, f"端口不可用 ≠ 已有 DeLector 在运行，实际 {text!r}"
    assert "端口不可用" in text, f"必须说清是哪一类失败，实际 {text!r}"


def test_main_releases_instance_lock_after_keyboard_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """`main()` 因 Ctrl+C 返回后，锁 MUST 已释放（同进程可再次取到）。

    这条挡的是「同进程反复调 `main()`」的**假红**：不释放 ⇒ 第二次启动被判「已在运行」，
    所有后续用例连带变红，而缺陷其实只在一处。
    """
    from delector.core import server_lifecycle

    paths = _pin_lock_dir(tmp_path, monkeypatch)
    _patch_serving(monkeypatch)

    class _InterruptOnJoin:
        daemon = False

        def join(self, *_args: object, **_kwargs: object) -> None:
            raise KeyboardInterrupt

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(server_lifecycle, "serve_in_thread", lambda server: _InterruptOnJoin())
    monkeypatch.setattr(start, "is_port_in_use", lambda _port: False)
    # 刻意**不**patch `is_android`：Android 短路返回的是降级句柄（release 是空操作），
    # 那样这条用例就永远绿、根本证明不了「finally 放锁」—— 必须先让本进程真的把锁攥在手里。
    monkeypatch.setattr(start, "is_android", lambda: False)
    monkeypatch.setattr(start, "open_browser", lambda port: None)
    monkeypatch.setattr(start, "bootstrap_data_dir", lambda *_a, **_k: "")

    start.main()

    assert Path(paths.meta).exists(), "前提失败：main() 没真取锁（meta 未被回写），本用例证明不了放锁"
    reacquired = instance_lock.try_acquire(paths, instance_lock.UNKNOWN_RECORD)
    assert isinstance(reacquired, instance_lock.LockHandle), (
        "main() 退出路径（含 KeyboardInterrupt）MUST 在 finally 放锁，否则同进程二次启动全是假红"
    )
    reacquired.release()


def test_claim_instance_identity_probe_on_degraded_lock_reports_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """锁降级（`LockHandle.is_degraded`）时，被占的候选端口若探到 DeLector ⇒ 判 `same`，**绝不顺延**。

    锁降级的成因（只读目录 / 权限 / 无原语）恰恰也是「另一个 DeLector 抢不到锁」的成因 ⇒
    此时"候选端口被占"不等于"陌生程序"：直接顺延就会起**第二个服务**，正是本计划要消灭的缺陷。
    """
    _pin_lock_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(instance_lock, "_acquire_os_lock", lambda fd: None)  # 原语不可用 ⇒ 降级句柄
    probed: list[int] = []

    def identity(port: int) -> bool:
        probed.append(port)
        return port == 8000

    result = start.claim_instance(
        {"DELECTOR_DATA_DIR": str(tmp_path / "data")},
        probe=lambda port: port == 8000,
        identity_probe=identity,
    )

    assert isinstance(result, start.AlreadyRunning), f"8000 上是 DeLector ⇒ 不该顺延，实际 {result!r}"
    assert result.reason == "same", f"线上已探到 DeLector 身份 ⇒ 应为 same，实际 {result.reason!r}"
    assert result.record.port == 8000, "必须把探到的端口填进 record，上层才能打开已有页面"
    assert probed == [8000], f"只该探**被占**的候选端口，实际 {probed}"


def test_claim_instance_skips_identity_probe_when_lock_is_real(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """拿到**真锁**时 MUST NOT 调身份探测：锁是唯一判据，探测只是第二腿。

    反证：「锁在我手里 ⇒ 8000 上的不是我」是硬事实；此时再去看 8000 上是谁，等于给
    陌生程序一个冒充 DeLector 的机会（也让启动白白多付一次 HTTP 往返）。
    """
    _pin_lock_dir(tmp_path, monkeypatch)

    def identity(port: int) -> bool:
        # 用 raise 而不是 `pytest.fail`：后者在 typeshed 里的返回类型不是 NoReturn，
        # 会让 `-> bool` 撞上 mypy 的 missing-return（这里断言失败与抛异常等价）。
        raise AssertionError(f"拿到真锁时不得调身份探测（锁是唯一判据），却探了 {port}")

    result = start.claim_instance(
        {"DELECTOR_DATA_DIR": str(tmp_path / "data")},
        probe=lambda port: True,
        identity_probe=identity,
    )

    assert isinstance(result, start.AlreadyRunning), f"全部候选被占 ⇒ AlreadyRunning，实际 {result!r}"
    assert result.reason == "no_free_port"


# ── 返修轮：main() 级身份探测接线 ────────────────────────────────────────────────
def test_main_consults_identity_probe_when_instance_lock_is_degraded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """锁降级 ⇒ `main()` MUST 把 `_identity_probe` 交给 `claim_instance`。

    为什么这条必须是 `main()` 级：`claim_instance(..., identity_probe=...)` 的实参写在 `main()`
    里，`claim_instance` 自己的用例（`test_claim_instance_identity_probe_on_degraded_lock_reports_same`）
    是直接传参的 —— 它钉得住 `claim_instance` 的语义，**钉不住 `main()` 有没有把这条腿接上**。
    删掉那个 kwarg，那些用例全绿，而线上行为退化成：锁降级时 8000 上的 DeLector 不被识别 ⇒
    顺延到 8002 ⇒ 两个进程同时改同一个库。

    现场（锁降级 + 8000 上有 DeLector）：
      * `instance_lock._acquire_os_lock` ⇒ `None`（原语缺失 / 加锁被拒 ⇒ 降级句柄）
      * `is_port_in_use` 只对 8000 为真（其余候选空闲）
      * `_identity_probe` 只对 8000 为真（线上真有一个 DeLector 在跑）
    变异自证：删掉 `identity_probe=_identity_probe` ⇒ 8000 被当「陌生程序占端口」而顺延到 8002
    ⇒ 走进 `bootstrap_data_dir`（此处被 patch 成 `pytest.fail`）⇒ 本用例转红。
    """
    _pin_lock_dir(tmp_path, monkeypatch)
    monkeypatch.setenv("DELECTOR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(instance_lock, "_acquire_os_lock", lambda fd: None)  # 降级句柄
    monkeypatch.setattr(start, "is_port_in_use", lambda port: port == 8000)
    monkeypatch.setattr(start, "_identity_probe", lambda port: port == 8000)
    built, _ = _patch_serving(monkeypatch)
    opened: list[int] = []
    monkeypatch.setattr(start, "is_android", lambda: False)
    monkeypatch.setattr(start, "open_browser", lambda port: opened.append(port))
    monkeypatch.setattr(
        start, "bootstrap_data_dir", lambda *_a, **_k: pytest.fail("已在运行 ⇒ 不得动库")
    )

    start.main()  # 不得抛 SystemExit：识别为既有实例是正常返回

    assert built == [], f"已在运行 ⇒ 绝不能再建第二个 server（那正是本用例要消灭的双实例），实际 {built}"
    assert opened == [8000], f"应打开线上探到的 8000（不是顺延算出来的端口），实际 {opened}"
    out = capsys.readouterr().out
    assert "已在运行" in out, f"必须告诉用户已有实例在跑，实际输出={out!r}"


def test_main_does_not_open_browser_when_same_instance_port_is_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """`same` 但对方端口不响应 `/api/health` ⇒ 提示 + **不**开页面。

    不变式（ADR-0020 §6.4）：绝不为一个不响应 `/api/health` 的端口打开页面。`record` 可能来自
    上一次运行留下的陈旧 meta（`write_record` 失败只 WARNING），此时 `record.port` 上未必真有
    DeLector —— 照旧开页面等于把用户扔到一个打不开的地址，且他无从判断「到底在不在跑」。
    """
    data_dir = str(tmp_path / "data")
    monkeypatch.setenv("DELECTOR_DATA_DIR", data_dir)
    _, holder = _hold_lock(tmp_path, monkeypatch, version=APP_VERSION, data_dir=data_dir, port=8006)
    built, _ = _patch_serving(monkeypatch)
    opened: list[int] = []
    monkeypatch.setattr(start, "is_android", lambda: False)
    monkeypatch.setattr(start, "open_browser", lambda port: opened.append(port))
    monkeypatch.setattr(start, "_identity_probe", lambda port: False)  # 该端口上没人应答
    monkeypatch.setattr(
        start, "bootstrap_data_dir", lambda *_a, **_k: pytest.fail("已有实例在跑时不得动它的库")
    )

    try:
        start.main()  # 不得起第二个服务，也不得 SystemExit（暂态，退出码仍是 0）
    finally:
        holder.release()

    assert opened == [], f"端口不响应 /api/health 时绝不开页面，实际 {opened}"
    assert built == [], f"识别为同一实例时不能再建 server，实际 {built}"
    out = capsys.readouterr().out
    assert "已在运行" in out and "无响应" in out, (
        f"必须说清「在跑但该端口无响应」，而不是静默或只开页面，实际输出={out!r}"
    )
