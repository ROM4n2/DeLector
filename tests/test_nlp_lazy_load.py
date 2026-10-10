# -*- coding: utf-8 -*-
"""spaCy 惰性加载回归锁（ADR-0018 §7.6 O0 杠杆 / ADR-0021 替代投资#4）。

钉住什么
--------
把 spaCy 模型加载从 import 期搬到「首次真正需要 NLP 时」后，必须守三条性质，
且每条都用**行为**证明（不是"函数存在"这种半恒真断言）：

1. **import 无副作用**：`import delector.nlp_engine.processor` **不得**触发任何模型加载
   （也不得联网下载）。改为 import 期加载（回退）⇒ 本锁必红。
2. **首用只加载一次 + 线程安全**：并发首次调用只触发**一次**加载，且所有并发调用拿到
   一致结果（互斥锁 + 双检；不得出现两次加载或半初始化被读到）。
3. **失败可见（No-Silent-Failure）**：加载失败时首次调用**抛明确异常**，绝不静默返回
   空值。

为什么用**子进程**而不是进程内 monkeypatch
----------------------------------------
被测对象就是"进程的第一次 import"——进程内 import 会命中 `sys.modules`，测出来恒真
（半恒真断言）。故每个锁起一个干净解释器，`cwd=ROOT` 且把三个数据环境变量钉进临时目录
（`database.py` 在导入期就按 `DATA_DIR` 建目录，父进程漏传 ⇒ 子进程写仓库根）。

隔离与卫生
----------
环境由 `dict(os.environ)` 派生并覆盖三个数据路径；本文件不使用任何类型检查 / lint 豁免。
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parent.parent

# 子进程探针统一前缀：`sys.path` 必须含仓库根，否则 `import delector` 失败。
_BOOTSTRAP = (
    "import os, sys\n"
    "sys.path.insert(0, %r)\n"
)

_PROBE_TIMEOUT_SEC = 300


def _run_probe(code: str, tmp_path: Path) -> str:
    """在干净解释器里跑探针，返回 stdout+stderr 合并文本。"""
    env: Dict[str, str] = dict(os.environ)
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "DELECTOR_DATA_DIR": str(tmp_path / "data"),
            "DATABASE_PATH": str(tmp_path / "delector.db"),
            "PROGRESS_DB_PATH": str(tmp_path / "progress.db"),
        }
    )
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


def test_import_does_not_load_model(tmp_path: Path) -> None:
    """① import 期不得加载模型（含不得联网下载）。

    在 import processor **之前**把四条加载/下载路径全部替换成计数器：回退到 import 期加载时，
    `spacy.load`（或 `spacy.cli.download`）会被调用，计数器非零 ⇒ 立刻红。
    """
    code = (
        "import spacy, spacy.util\n"
        "import spacy.cli\n"
        "calls = []\n"
        "def spy(*a, **k):\n"
        "    calls.append(a)\n"
        "    raise AssertionError('import 期不应触发模型加载/下载')\n"
        "spacy.load = spy\n"
        "spacy.util.load_model_from_init_py = spy\n"
        "spacy.util.load_model_from_path = spy\n"
        "spacy.cli.download = spy\n"
        "import delector.nlp_engine.processor as p\n"
        "print('LOAD_CALLS=%d' % len(calls))\n"
        "print('ENGINE=%s' % p.NLP_ENGINE)\n"
        "print('NLP_IS_NONE=%s' % (p.nlp is None))\n"
    )
    out = _run_probe(code, tmp_path)
    assert _field(out, "LOAD_CALLS") == "0", f"import processor 触发了模型加载/下载\n{out}"
    # 桌面（非 Android、spaCy 已装）下 nlp 必须是个占位代理（非 None），调用时才加载。
    assert _field(out, "NLP_IS_NONE") == "False", f"spaCy 已装却把 nlp 置成 None\n{out}"


def test_first_use_loads_exactly_once_across_threads(tmp_path: Path) -> None:
    """② 并发首次调用只加载一次，且结果一致（互斥锁 + 双检）。"""
    code = (
        "import threading, time\n"
        "from delector.nlp_engine import processor as p\n"
        "counter = {'n': 0}\n"
        "lock = threading.Lock()\n"
        "def fake_loader():\n"
        "    with lock:\n"
        "        counter['n'] += 1\n"
        "    time.sleep(0.2)\n"  # 拉宽竞态窗，逼出"两次加载"
        "    return (lambda s: s.upper(), 'fake')\n"
        "p._load_model_with_autodownload = fake_loader\n"
        "results = []\n"
        "def worker():\n"
        "    results.append(p.nlp('abc'))\n"
        "threads = [threading.Thread(target=worker) for _ in range(8)]\n"
        "for t in threads:\n"
        "    t.start()\n"
        "for t in threads:\n"
        "    t.join()\n"
        "print('LOAD_CALLS=%d' % counter['n'])\n"
        "print('N_RESULTS=%d' % len(results))\n"
        "print('ALL_SAME=%s' % all(r == 'ABC' for r in results))\n"
    )
    out = _run_probe(code, tmp_path)
    assert _field(out, "LOAD_CALLS") == "1", f"并发首次调用触发了多次加载\n{out}"
    assert _field(out, "N_RESULTS") == "8", f"有并发调用没拿到结果\n{out}"
    assert _field(out, "ALL_SAME") == "True", f"并发调用拿到了不一致的结果\n{out}"


def test_load_failure_is_visible_not_silent(tmp_path: Path) -> None:
    """③ 加载失败必须**大声失败**：首次调用抛明确异常，绝不清空返回。"""
    code = (
        "from delector.nlp_engine import processor as p\n"
        "def boom():\n"
        "    raise RuntimeError('模拟：德语模型不可用')\n"
        "p._load_model_with_autodownload = boom\n"
        "raised = 'no'\n"
        "second = 'no'\n"
        "try:\n"
        "    p.nlp('abc')\n"
        "except RuntimeError as exc:\n"
        "    raised = 'yes'\n"
        "    print('MSG_OK=%s' % ('加载失败' in str(exc)))\n"
        "try:\n"
        "    p.nlp('abc')\n"
        "except RuntimeError:\n"
        "    second = 'yes'\n"
        "print('RAISED=%s' % raised)\n"
        "print('SECOND_RAISES=%s' % second)\n"
    )
    out = _run_probe(code, tmp_path)
    assert _field(out, "RAISED") == "yes", f"加载失败却未抛异常（疑似静默降级）\n{out}"
    assert _field(out, "MSG_OK") == "True", f"异常信息未点明'加载失败'，真机上无从诊断\n{out}"
    # 失败要被记住：第二次调用同样抛错（不反复重试慢加载），且仍不是静默空值。
    assert _field(out, "SECOND_RAISES") == "yes", f"失败未被记住，第二次调用行为不一致\n{out}"
