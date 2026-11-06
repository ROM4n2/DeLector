# -*- coding: utf-8 -*-
"""模型后台预热回归锁（ADR-0028 2026-11-06 决策修订）。

钉住什么
--------
Android 实测（T5/T6，2026-11-06）显示：把模型加载从导入期搬到「首次分析」后，
首次分析仍要多等 **1,215.6 ms**（改造前 12.6 ms，model_loader.py 的惰性加载代价）。
选项 B 把这次加载挪到**服务就绪后的后台线程**，用户等待里不再包含它。本文件用行为锁住
六条性质：

1. **导入期不加载、也不启动预热**（ADR-0018 §7.6 的 O0 杠杆不许回退）。
2. **服务就绪（lifespan startup）会触发预热**，而不是永不触发。
3. **预热失败不崩进程、诊断保留、首次分析仍硬失败**（D4 No-Silent-Failure）。
4. **Android 后台预热同样不发起下载**（门控在 `_load_model_with_autodownload()` 内部，
   后台线程走的是同一条入口，不是另开一条）。
5. **并发：预热进行中发请求，模型只加载一次**（同一把 `_model_lock`，加载次数可测）。
6. **开关 `DELECTOR_MODEL_PREWARM=0` 能整体关掉预热**。

为什么用**子进程**
------------------
被测对象是「进程的第一次导入」与「后台线程的完整生命周期」——进程内跑会命中
`sys.modules` / 残留全局（`_nlp_resolved`），测出来恒真。故除 lifespan 接线一条
（它本身就是进程内装配行为）外，其余都在干净解释器里跑，且把三个数据环境变量钉进
临时目录（`database.py` 在导入期就按 `DATA_DIR` 建目录）。
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent

# 子进程探针统一前缀：`sys.path` 必须含仓库根，否则 `import delector` 失败。
_BOOTSTRAP = "import os, sys\nsys.path.insert(0, %r)\n"

_PROBE_TIMEOUT_SEC = 300


def _run_probe(code: str, tmp_path: Path, extra_env: Optional[Dict[str, str]] = None) -> str:
    """在干净解释器里跑探针，返回 stdout+stderr 合并文本。"""
    env: Dict[str, str] = dict(os.environ)
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "DELECTOR_DATA_DIR": str(tmp_path / "data"),
            "DATABASE_PATH": str(tmp_path / "delector.db"),
            "PROGRESS_DB_PATH": str(tmp_path / "progress.db"),
            # 默认显式打开：避免外部环境残留把本该测「预热发生」的用例静默关掉。
            "DELECTOR_MODEL_PREWARM": "1",
        }
    )
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, "-c", _BOOTSTRAP % str(ROOT) + code],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_PROBE_TIMEOUT_SEC,
        check=False,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, f"探针退出码 {proc.returncode}\n{out}"
    return out


def _field(out: str, key: str) -> str:
    for line in out.splitlines():
        if line.startswith(key + "="):
            return line[len(key) + 1 :]
    raise AssertionError(f"探针输出缺少 `{key}=` 行\n{out}")


def test_import_does_not_load_or_prewarm(tmp_path: Path) -> None:
    """① 导入 `delector.server` 既不得加载模型，也不得启动预热线程。

    在 import **之前**把四条加载/下载路径全部替换成计数器：回退到导入期加载时计数器非零
    ⇒ 立刻红。`_prewarm_started` 仍为 False，证明预热只挂在 lifespan，而不是模块顶层。
    """
    code = (
        "import spacy, spacy.util\n"
        "import spacy.cli\n"
        "calls = []\n"
        "def spy(*a, **k):\n"
        "    calls.append(a)\n"
        "    raise AssertionError('导入期不应触发模型加载/下载')\n"
        "spacy.load = spy\n"
        "spacy.util.load_model_from_init_py = spy\n"
        "spacy.util.load_model_from_path = spy\n"
        "spacy.cli.download = spy\n"
        "import delector.server\n"
        "from delector.nlp_engine import model_loader as m\n"
        "print('LOAD_CALLS=%d' % len(calls))\n"
        "print('PREWARM_STARTED=%s' % m._prewarm_started)\n"
        "print('LOAD_COUNT=%d' % m.get_model_load_count())\n"
    )
    out = _run_probe(code, tmp_path)
    assert _field(out, "LOAD_CALLS") == "0", f"导入 delector.server 触发了模型加载/下载\n{out}"
    assert _field(out, "PREWARM_STARTED") == "False", f"导入期就启动了预热线程（必须等 lifespan）\n{out}"
    assert _field(out, "LOAD_COUNT") == "0", f"导入期加载计数非零\n{out}"


def test_lifespan_startup_triggers_prewarm(monkeypatch) -> None:
    """② 服务就绪（lifespan startup）必须触发预热，而不是永不触发。

    用 `with TestClient(app)` 真正进入 lifespan；把 `start_background_prewarm` 换成计数器后，
    `/api/health` 仍须 200（证明预热没有占住启动路径）。
    """
    from delector.nlp_engine import model_loader
    from delector.server import create_app

    calls = []

    def fake_start() -> bool:
        calls.append("prewarm")
        return True

    # 调用点不在本模块内：delector.server 的 lifespan 于调用期经
    # `model_loader.start_background_prewarm()` 做模块属性查找，故本补丁即时生效。
    # mock-drift-ok: 符号消费方在 delector.server 的 lifespan（调用期模块属性查找），补丁即时生效
    monkeypatch.setattr(model_loader, "start_background_prewarm", fake_start)
    app = create_app()
    with TestClient(app, client=("127.0.0.1", 54321)) as client:
        response = client.get("/api/health")
        assert response.status_code == 200, "预热不得阻塞 /api/health"
    assert calls == ["prewarm"], "lifespan startup 没有触发后台预热"


def test_prewarm_failure_keeps_process_alive_and_first_use_hard_fails(tmp_path: Path) -> None:
    """③ 预热失败：进程存活 + 诊断保留 + 首次分析仍抛 RuntimeError（D4）。

    「进程存活」由探针正常走完并打印 ALIVE 证明；后台异常若逃逸到线程外，进程会带栈退出。
    """
    code = (
        "from delector.nlp_engine import model_loader as m\n"
        "def boom():\n"
        "    raise RuntimeError('模拟：德语模型不可用')\n"
        "m._load_model_with_autodownload = boom\n"
        "m._PREWARM_GRACE_S = 0.0\n"
        "started = m.start_background_prewarm()\n"
        "m._prewarm_thread.join(10)\n"
        "print('STARTED=%s' % started)\n"
        "print('THREAD_DONE=%s' % (not m._prewarm_thread.is_alive()))\n"
        "print('ALIVE=yes')\n"
        "print('DIAG_OK=%s' % ('德语模型不可用' in m.get_spacy_load_error()))\n"
        "raised = 'no'\n"
        "message = ''\n"
        "try:\n"
        "    m._resolve_nlp_model()\n"
        "except RuntimeError as exc:\n"
        "    raised = 'yes'\n"
        "    message = str(exc)\n"
        "print('FIRST_RAISES=%s' % raised)\n"
        "print('MSG_OK=%s' % ('加载失败' in message))\n"
        "print('LOAD_COUNT=%d' % m.get_model_load_count())\n"
    )
    out = _run_probe(code, tmp_path)
    assert _field(out, "STARTED") == "True", f"默认开启时预热没有启动\n{out}"
    assert _field(out, "THREAD_DONE") == "True", f"预热线程未在 10s 内收尾\n{out}"
    assert _field(out, "ALIVE") == "yes", f"预热失败把进程带走了\n{out}"
    assert _field(out, "DIAG_OK") == "True", f"预热失败未留下诊断（_nlp_error 为空）\n{out}"
    assert _field(out, "FIRST_RAISES") == "yes", f"预热失败后首次分析没有硬失败（疑似静默降级）\n{out}"
    assert _field(out, "MSG_OK") == "True", f"首次分析的异常信息未点明'加载失败'\n{out}"
    # 预热已试过一次；首次分析只复用失败状态，不再重复加载。
    assert _field(out, "LOAD_COUNT") == "1", f"失败后首次分析又加载了一次\n{out}"
    assert "模型预热：失败" in out, f"预热失败没有留可观测日志\n{out}"


def test_android_prewarm_never_downloads(tmp_path: Path) -> None:
    """④ Android 路径下后台预热走同一条门控：不发起 `spacy.cli.download`。

    把 `_android_runtime` 置 True、本地三级回退做成必失败、下载换成哨兵：若后台线程绕过
    门控另开一条加载路径，下载哨兵会被调用 ⇒ 红。
    """
    code = (
        "import spacy.cli\n"
        "downloads = []\n"
        "def download_spy(*a, **k):\n"
        "    downloads.append(a)\n"
        "    raise AssertionError('Android 后台预热不得发起下载')\n"
        "spacy.cli.download = download_spy\n"
        "from delector.nlp_engine import model_loader as m\n"
        "m._android_runtime = True\n"
        "m._PREWARM_GRACE_S = 0.0\n"
        "def local_fail(name):\n"
        "    raise RuntimeError('本地模型不可用')\n"
        "m._load_spacy_model = local_fail\n"
        "m.start_background_prewarm()\n"
        "m._prewarm_thread.join(10)\n"
        "print('DOWNLOAD_CALLS=%d' % len(downloads))\n"
        "print('FAILED_VISIBLE=%s' % ('本地模型不可用' in m.get_spacy_load_error()))\n"
        "print('LOAD_COUNT=%d' % m.get_model_load_count())\n"
    )
    out = _run_probe(code, tmp_path)
    assert _field(out, "DOWNLOAD_CALLS") == "0", f"Android 预热触发了下载（门控被绕过）\n{out}"
    assert _field(out, "FAILED_VISIBLE") == "True", f"Android 预热失败未留下诊断\n{out}"
    assert _field(out, "LOAD_COUNT") == "1", f"Android 预热没有走统一加载入口\n{out}"
    assert "模型预热：失败" in out, f"Android 预热失败没有留可观测日志\n{out}"


def test_concurrent_first_use_during_prewarm_loads_once(tmp_path: Path) -> None:
    """⑤ 预热进行中并发首次调用：只加载一次，所有调用拿到同一结果。"""
    code = (
        "import threading, time\n"
        "from delector.nlp_engine import model_loader as m\n"
        "calls = []\n"
        "lock = threading.Lock()\n"
        "def slow_loader():\n"
        "    with lock:\n"
        "        calls.append('load')\n"
        "    time.sleep(0.2)\n"  # 拉宽竞态窗，逼出「预热与请求各加载一次」
        "    return (object(), 'fake')\n"
        "m._load_model_with_autodownload = slow_loader\n"
        "m._PREWARM_GRACE_S = 0.0\n"
        "started = m.start_background_prewarm()\n"
        "results = []\n"
        "errors = []\n"
        "def worker():\n"
        "    try:\n"
        "        results.append(m._resolve_nlp_model())\n"
        "    except Exception as exc:\n"
        "        errors.append(exc)\n"
        "threads = [threading.Thread(target=worker) for _ in range(8)]\n"
        "for t in threads:\n"
        "    t.start()\n"
        "for t in threads:\n"
        "    t.join(10)\n"
        "m._prewarm_thread.join(10)\n"
        "print('STARTED=%s' % started)\n"
        "print('LOAD_CALLS=%d' % len(calls))\n"
        "print('INTERNAL_COUNT=%d' % m.get_model_load_count())\n"
        "print('N_RESULTS=%d' % len(results))\n"
        "print('N_ERRORS=%d' % len(errors))\n"
        "print('ALL_SAME=%s' % (len({id(r) for r in results}) == 1 if results else False))\n"
    )
    out = _run_probe(code, tmp_path)
    assert _field(out, "STARTED") == "True", f"默认开启时预热没有启动\n{out}"
    assert _field(out, "LOAD_CALLS") == "1", f"预热 + 并发请求触发了多次加载\n{out}"
    assert _field(out, "INTERNAL_COUNT") == "1", f"加载计数不是 1（线程安全证据失败）\n{out}"
    assert _field(out, "N_RESULTS") == "8", f"有并发调用没拿到结果\n{out}"
    assert _field(out, "N_ERRORS") == "0", f"并发调用拿到异常\n{out}"
    assert _field(out, "ALL_SAME") == "True", f"并发调用拿到了不同结果\n{out}"
    assert "模型预热：开始" in out, f"预热开始没有可观测日志\n{out}"
    assert "模型预热：完成" in out, f"预热完成没有可观测日志\n{out}"
    assert "耗时" in out, f"预热完成日志缺少耗时\n{out}"


def test_prewarm_disabled_by_env_switch(tmp_path: Path) -> None:
    """⑥ `DELECTOR_MODEL_PREWARM=0` 时预热不发生（加载计数保持 0）。"""
    code = (
        "from delector.nlp_engine import model_loader as m\n"
        "def boom():\n"
        "    raise AssertionError('开关关闭时不得加载模型')\n"
        "m._load_model_with_autodownload = boom\n"
        "started = m.start_background_prewarm()\n"
        "print('STARTED=%s' % started)\n"
        "print('THREAD=%s' % (m._prewarm_thread is not None))\n"
        "print('COUNT=%d' % m.get_model_load_count())\n"
    )
    out = _run_probe(code, tmp_path, extra_env={"DELECTOR_MODEL_PREWARM": "0"})
    assert _field(out, "STARTED") == "False", f"开关关闭时预热仍启动\n{out}"
    assert _field(out, "THREAD") == "False", f"开关关闭时仍创建了预热线程\n{out}"
    assert _field(out, "COUNT") == "0", f"开关关闭时模型仍被加载\n{out}"
