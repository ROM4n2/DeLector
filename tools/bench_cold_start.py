# -*- coding: utf-8 -*-
"""冷启动基准（子计划 2 / Task 4）：量化「进程起到**可服务**」的各段耗时。

为什么需要这个脚本
------------------
用户体感里最直观的一项就是「双击 exe 之后多久能用」。仓库里此前**没有任何**可复跑
的冷启动数字，只有两条来自 Android 侧的定性/上限描述
（`docs/agents/architecture.md:100-101`）：

- 「Chaquopy 要把三个包解到内部存储（约 30MB 写盘），只发生在第一次」
- 「启动页轮询上限约 84 秒」

没有桌面侧数字，就无法回答「Android 首启慢到底是解包（30MB 写盘）还是 Python 侧
import/建库/装配」——84 秒是**轮询上限**不是实测耗时，两者不可相减。本脚本给出桌面
侧**唯一可复跑**的口径，并把它与 Android 已知口径的关系写进 `verdict`。

五段口径（**各段独立子进程、前置状态不同 ⇒ 只可看概念包含，不可比大小**）
--------------------------------------------------------------------------
===================  ==================================================  ============================
行                   怎么测                                              含义
===================  ==================================================  ============================
``import_ms``        **独立子进程**：``import delector.server`` 的墙钟    含 spaCy 模型加载（
                                                                         ``processor.py:81-111`` 在
                                                                         导入期加载）+ 路由模块
                                                                         import + **模块级
                                                                         ``app = create_app()``**
                                                                         （``server.py:356``）
``init_db_ms``       **独立子进程**：导入 database 后单独计 ``init_db()``  仅建表（DDL）
``app_ready_ms``     probe B **同一进程**内 import 完之后，对另一套全新库    冷库装配：建表 + 预置文章导入
                     再调一次 ``create_app()``（**第二次装配**）             + 遇见区补装 + 静态挂载；其冷度
                                                                         与 probe A 不同源（见下）
``health_200_ms``    **独立子进程**起真实 uvicorn，轮询                    **用户体感主指标**
                     ``/api/health`` 直到 200                             （进程起 → 可服务）
``model_load_ms``    **独立子进程**：``import                             含 ``import spacy`` 本身；
                     delector.nlp_engine.processor``                     与 ``bench_spacy_unit.py``
                                                                         同口径
===================  ==================================================  ============================

``import_ms`` / ``app_ready_ms`` / ``init_db_ms`` 只有**概念上的**包含关系（``import``
``delector.server`` 时模块级就调了 ``create_app()``，而 ``create_app()`` 内部又调了
``init_db()``），但**三段各由独立子进程测得、前置状态不同**（probe B 的进程在 import
期已跑过一次完整 ``create_app()``，进程级与文件系统级缓存已热）⇒ **不可按大小关系解读**
（谁大谁小随机器与前置状态变：本机 ``app_ready_ms > init_db_ms``、CI 反向，见 ``segments_note``）。
``model_load_ms`` 概念上是 ``import_ms`` 的**子集**（模型加载发生在 import 之内），但两者
同样来自**不同子进程**，故 ``import_ms − model_load_ms`` 只作近似归因，**不可当作一个独立分段**，
也**不可据此断言 ``model_load_ms <= import_ms``**。

为什么每段都用**独立子进程**
----------------------------
冷启动的被测对象就是「Python 进程的第一次 import」——同一进程里第二次 import 会命中
``sys.modules``，测出来是 0。故 probe A（model/init_db）、probe B（import/app_ready）与
serve 各起一个干净解释器，轮数之间也各自新建临时数据目录，保证每一轮都是**真首次启动**
（空库 ⇒ 预置文章导入也走冷路径）。

例外要点名：``app_ready_ms`` 与 ``import_ms`` **共用 probe B 这一个进程** —— 该进程在
``import`` 期就跑了模块级 ``create_app()``，所以 ``app_ready_ms`` 量到的是"进程已热"后的
**第二次装配**，其冷度与 probe A 的独立 ``init_db()`` 不同源（见上文与 ``segments_note``）。

隔离纪律（`[Instinct: Isolated-DB]`）——**子进程也要隔离**
--------------------------------------------------------
父进程 ``tempfile.mkdtemp()`` 建**每轮一个**临时数据目录，把
``DELECTOR_DATA_DIR`` / ``DATABASE_PATH`` / ``PROGRESS_DB_PATH`` 三个环境变量**通过
``_child_env()`` 传给每一个子进程**（``database.py`` 在**导入期**就用 ``DATA_DIR``
``makedirs .cache/audio``，父进程不传 ⇒ 子进程写仓库根），``finally`` 里
``shutil.rmtree``。子进程入口第一件事是 ``_require_isolated_env()``：父进程漏传就
**响亮失败**，绝不静默写回仓库根。

脚本还会**行为自检**这两条：子进程是否真把 ``.cache/audio`` 建在了临时数据目录里
（``child_isolation_verified``），以及仓库根真实 ``delector.db`` 的 size/mtime 是否
被动过（``repo_db_untouched``）——只写注释不算数。

端口为什么不能硬编码 8000
-------------------------
``start.py:61`` 硬编码 8000。基准照抄会撞上用户**正在跑的实例**（本机常驻服务），
并发跑测试也会互撞。故 ``_free_port()`` 先 ``bind((127.0.0.1, 0))`` 让系统分配空闲
端口，再经 ``getsockname()`` 取回实际端口号传给子进程；仍有极小概率在 bind 与子进程
bind 之间被抢 ⇒ 失败时换新端口**重试**而非写死。

一处必须说明的「中和」（不是绕过生产校验）
------------------------------------------
``database.preflight_data_dir()``（迁移闸）在 ``init_db()`` 无参调用时跑：当
``DATA_DIR`` 是临时目录而**仓库根存在真实 ``delector.db``** 时，它的四个条件全中
（新位置无库 + 旧位置有库且非空 + 两路径不同）⇒ 抛 ``RuntimeError``。这是**正确的**
生产行为（防止「用户数据留在旧位置而程序偷偷建空库」），但基准**刻意**就要一次性空
库。故本脚本在临时数据目录里预置一个 **0 字节** ``delector.db``（SQLite 视 0 字节
文件为空库），使闸按其设计条件①「新位置已有库」返回；整个测量期间 ``DATABASE_PATH``
全程指向 tmpdir，闸要防的那件事在本基准里根本不存在。见输出行 ``data_dir_gate_note``。

Android 侧：**不伪造**
----------------------
``[Instinct: No-Silent-Conclusion]``：本机没有 Android SDK / 模拟器 / Chaquopy
运行时 ⇒ 30MB 解包与真机首启**不可测**。故输出 ``android=unmeasured`` 并给原因，
``verdict`` 里把 84000 ms 明确标为「轮询上限而非实测耗时」，禁止把桌面数字与它相减
/相除得出「Android 侧还剩多少」这类伪结论。

用法
----
:::

    export PYTHONIOENCODING=utf-8
    python tools/bench_cold_start.py                        # 5 轮中位数（默认）
    BENCH_COLD_START_ROUNDS=9 python tools/bench_cold_start.py   # 人工档，多几轮压噪声
    BENCH_P95_ROUNDS=20 python tools/bench_cold_start.py         # 人工档：提 p95 样本量

输出契约（``tests/test_cold_start_cost.py`` 逐行断言，勿改格式）::

    import_ms=N.NN          # import delector.server（含 spaCy 模型加载 + 模块级 create_app）
    init_db_ms=N.NN         # **独立子进程**：单独计 init_db()（连带初始化进度库 + 预置文章导入）
    init_db_tables=N        # probe A 自检：init_db() 后 initdb/init.db 的 sqlite_master 表数（0=没建表/落热库）
    init_db_progress_tables=N  # 同上，initdb/init_progress.db（两库对称，机器无关的防恒真判据）
    app_ready_ms=N.NN       # probe B 同一进程内**第二次 create_app()**：对另一套全新库装配
                            #   （冷度与 probe A 不同源，见 segments_note；不可据此与 init_db_ms 比大小）
    app_ready_db_tables=N   # 第二次 create_app() 后 appready/second.db 的 sqlite_master 表数（0=没建表）
    app_ready_progress_tables=N  # 同上，appready/second_progress.db
    app_ready_fresh_db_used=<yes|no>  # 第二次 create_app() 是否真写在全新库路径上（no=又写回了 main_db）
    health_200_ms=N.NN      # 子进程起服务 → /api/health 200 的墙钟（用户体感主指标）
    health_200_p95_ms=N.NN  # 与 health_200_ms **同一批**样本的 p95（n=5 时≈最大值、系统性低估尾部）
    samples_health_200_ms=N.NN,...  # 该批原始样本，供下游独立重算分位（不许拿中位数冒充）
    model_load_ms=N.NN      # import delector.nlp_engine.processor（import_ms 的子集）
    rounds=N
    nlp_path=<spacy|pure>   # 生产自己的判据：processor.NLP_ENGINE + syntax_tree.get_spacy_nlp()
    android=unmeasured      # 本机无 Android SDK，见 android_note
    verdict=<可判定结论：点名 Android 30MB / 84000ms 口径>
"""

import argparse
import importlib
import os
import re
import shutil
import socket
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from types import ModuleType
from typing import Any, Callable, Dict, List, Optional, Tuple

# bench_stats 与本脚本同处 tools/：以脚本方式运行（`python tools/bench_cold_start.py`）时
# Python 已把 tools/ 放进 sys.path[0]，故可直接顶层导入。**必须放在文件顶部**（早于任何
# 其他语句）才不触发 E402 —— 与其余两个基准保持同一写法，三个基准共用同一份 p95 口径。
# p95 的口径与已知偏差方向见 tools/bench_stats.py。
from bench_stats import format_samples, p95_ms

# 允许从任意 CWD 直接 `python tools/bench_cold_start.py` 运行（同 tools/ 其余脚本约定）。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLS_DIR = os.path.join(_REPO_ROOT, "tools")
# tools/ 也要进 sys.path：本脚本与其余基准共用 tools/bench_stats.py 的 p95 口径，
# 而 tools/ 不是包（无 __init__.py），只能靠目录进路径做顶层 import。
for _path in (_REPO_ROOT, _TOOLS_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

_SCRIPT = os.path.abspath(__file__)

MIN_ROUNDS = 5  # 取中位数而非均值；少于 5 轮噪声压不住（[Instinct: Median-Not-Mean]）
DEFAULT_ROUNDS = 5  # 一轮≈3 个子进程（每个都要冷加载 spaCy），默认就取下限

# 绑回环而非 0.0.0.0：桌面生产（start.get_bind_host()）绑 0.0.0.0 是**有意的特性**
# （同 Wi-Fi 设备可访问），但基准没必要把一个无鉴权实例暴露给局域网（arch.md:92-94
# 正是拿这条解释 Android 只绑回环）。绑定地址不进入任何被测分段，只影响可连接性。
_HOST = "127.0.0.1"

_POLL_INTERVAL_SEC = 0.02
_HEALTH_TIMEOUT_SEC = 120.0  # 远超实测（数秒）：留足慢机器余量，超时即响亮失败
_PROBE_TIMEOUT_SEC = 300.0
_PORT_RETRIES = 3

# Android 已知口径（docs/agents/architecture.md:100-101）。改这里等于改对照对象。
ANDROID_POLL_CAP_MS = 84000.0  # 「启动页轮询上限约 84 秒」——是上限，不是实测首启耗时
ANDROID_UNPACK_MB = 30.0  # 首次启动 Chaquopy 解包三个包的写盘量
ANDROID_STATUS = "unmeasured"
ANDROID_NOTE = (
    "android=unmeasured：本机无 Android SDK / 模拟器 / Chaquopy 运行时 ⇒ "
    "30MB 解包与真机首启均不可测（docs/plans/2026-10-09-performance-measurement.md "
    "Unknown 2 已登记该项留空、不在本计划伪造）；84000 ms 是启动页**轮询上限**而非实测首启"
    "耗时，与桌面 health_200_ms 分属不同口径，不可相减/相除"
)

DATA_DIR_GATE_NOTE = (
    "迁移闸中和：database.preflight_data_dir() 在 DATA_DIR 为临时目录且仓库根存在真实 "
    "delector.db 时会抛 RuntimeError（防『用户数据留在旧位置而程序偷偷建空库』，生产行为正确）；"
    "本基准刻意用一次性空库，故在临时数据目录预置 0 字节 delector.db（SQLite 视为空库）"
    "使闸按条件①『新位置已有库』返回 —— DATABASE_PATH 全程指向 tmpdir，闸要防的那件事不存在"
)
SEGMENTS_NOTE = (
    "分段口径：import_ms / app_ready_ms / init_db_ms 各由**独立子进程**测得，且前置状态不同 —— "
    "probe B 的进程在 import delector.server 时模块级已跑过一次完整 create_app()（server.py:356），"
    "其进程级缓存与文件系统缓存已热；probe A 是独立进程里单次 init_db()。三者只有**概念上的**"
    "包含关系（import 含 create_app、create_app 含 init_db），**不可按大小关系解读**"
    "（谁大谁小随机器与前置状态变：本机 app_ready>init_db、CI 反向），相加亦无意义"
)
MODEL_LOAD_NOTE = (
    "model_load_ms 是**独立子进程**里 import delector.nlp_engine.processor 的墙钟"
    "（含 import spacy 本身，与 bench_spacy_unit.py 的 model_load_ms 同口径）；"
    "processor 在导入期就加载模型 ⇒ 它是 import_ms 的**子集**，两者非互斥分段，"
    "import_ms − model_load_ms 只作近似归因，不可直接相减"
)


# --------------------------------------------------------------------------- #
# 环境准备（父进程侧）
# --------------------------------------------------------------------------- #
def _env_rounds() -> int:
    """轮数：`BENCH_P95_ROUNDS` 优先，否则沿用 `BENCH_COLD_START_ROUNDS` / 默认 5。

    冷启动是抖动最大的一档（每轮一个全新解释器 + 一次起服务），判"p95 未超 2 倍目标"
    这种强结论必须有足够样本；单独开关让人工档能一键把 n 提到 ≥20 而不改代码。
    """
    raw_p95 = os.environ.get("BENCH_P95_ROUNDS", "").strip()
    if raw_p95:
        return max(MIN_ROUNDS, int(raw_p95))
    raw = os.environ.get("BENCH_COLD_START_ROUNDS", "").strip()
    if not raw:
        return DEFAULT_ROUNDS
    return max(MIN_ROUNDS, int(raw))


def _child_env(data_dir: str, db_path: str, progress_db_path: str) -> Dict[str, str]:
    """构造**子进程**环境：三个数据路径全部钉进临时目录。

    少传任何一个都会让子进程在导入期把 ``.cache/audio`` 建到仓库根（或打开真实
    ``delector.db``），故这里是隔离纪律的真正落点（``[Instinct: Isolated-DB]``）。
    """
    env = dict(os.environ)
    env["DELECTOR_DATA_DIR"] = data_dir
    env["DATABASE_PATH"] = db_path
    env["PROGRESS_DB_PATH"] = progress_db_path
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"  # 起服务时日志不缓冲，超时诊断才有内容可读
    return env


def _require_isolated_env() -> str:
    """子进程入口自检：父进程必须已经把三个数据路径钉死，否则**响亮失败**。

    不做「缺失就用默认值兜底」：那正是静默污染仓库根的写法。
    """
    missing = [
        key for key in ("DELECTOR_DATA_DIR", "DATABASE_PATH", "PROGRESS_DB_PATH") if not os.environ.get(key)
    ]
    if missing:
        raise SystemExit(f"子进程缺少隔离环境变量 {missing}：本脚本必须由父进程传入临时数据目录")
    return os.environ["DELECTOR_DATA_DIR"]


def _free_port() -> int:
    """向系统要一个空闲端口（bind port 0），不再沿用 ``start.py`` 的硬编码端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((_HOST, 0))
        return int(sock.getsockname()[1])


# --------------------------------------------------------------------------- #
# 子进程探针：每段一个干净解释器（冷 import 只能发生一次）
# --------------------------------------------------------------------------- #
def _nlp_path(syntax_tree: ModuleType, processor: ModuleType) -> Tuple[str, str]:
    """用**生产自己的判据**读出本次走的是 spaCy 还是纯 Python 降级路径。

    - ``syntax_tree.get_spacy_nlp()``：生产 ``/spacy-status`` 用的判据；
    - ``processor.NLP_ENGINE``：processor 自己记录的生效引擎。

    刻意不在基准里自己 ``import spacy`` 判一次：那会与生产的候选顺序 / 自动下载 /
    Android 判定分叉。两层都报 spaCy 才标 ``spacy``。
    """
    tree_path = "spacy" if syntax_tree.get_spacy_nlp() else "pure"
    proc_path = "spacy" if processor.NLP_ENGINE == "spacy" else "pure"
    path = "spacy" if tree_path == "spacy" and proc_path == "spacy" else "pure"
    detail = " ".join(str(processor.NLP_ENGINE_DETAIL).split())
    return path, f"syntax_tree={tree_path};processor={proc_path}({detail})"


def _count_tables(db_path: str) -> int:
    """数一个 SQLite 库 sqlite_master 里的表数；文件不存在返回 0。

    供 probe A（init_db）与 probe B（app_ready）**对称**自检：哪段的 env 失效、把建库落到了
    已初始化/热库上，这里就会暴露成 0 —— 这是个**机器无关**的判据（表要么在、要么不在），
    比"两次跨进程耗时谁大谁小"可靠得多。两段都要用它，避免守卫只设在一侧。
    """
    if not os.path.isfile(db_path):
        return 0
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()
        return int(row[0])
    finally:
        conn.close()


def _probe_model_and_initdb() -> int:
    """探针 A：``model_load_ms``（import processor）+ ``init_db_ms``（冷库建表）。

    除两段耗时外还自报两条**机器无关**的自检：``init_db()`` 之后两张库里的
    ``sqlite_master`` 表数（与 probe B 对称，见 ``_count_tables``）。若 env 未生效 /
    ``init_db()`` 落到了已初始化热库上，表数会直接变 0 —— 否则 ``init_db_ms`` 可任意小，
    而只用 ``> 0`` 兜底，正是本次被修缺陷在另一个探针上的翻版。
    """
    _require_isolated_env()
    start = time.perf_counter()
    processor = importlib.import_module("delector.nlp_engine.processor")
    model_load_ms = (time.perf_counter() - start) * 1000.0

    database = importlib.import_module("delector.core.database")
    init_db: Callable[[], Any] = database.init_db
    start_db = time.perf_counter()
    init_db()  # 无参 ⇒ 走 DATABASE_PATH（父进程给的全新库）
    init_db_ms = (time.perf_counter() - start_db) * 1000.0

    # 行为自检：init_db() 必须真在这两张**全新库**上建出表（env 失效落到热库 ⇒ 表数为 0）。
    # 表在就是 ≥1、不在就是 0 —— 与机器/缓存无关，是 probe A 防恒真的判据（与 probe B 对称）。
    init_db_tables = _count_tables(os.environ["DATABASE_PATH"])
    init_db_progress_tables = _count_tables(os.environ["PROGRESS_DB_PATH"])

    syntax_tree = importlib.import_module("delector.nlp_engine.syntax_tree")
    nlp_path, nlp_detail = _nlp_path(syntax_tree, processor)
    print(f"probe_model_load_ms={model_load_ms:.2f}")
    print(f"probe_init_db_ms={init_db_ms:.2f}")
    print(f"probe_init_db_tables={init_db_tables}")
    print(f"probe_init_db_progress_tables={init_db_progress_tables}")
    print(f"probe_nlp_path={nlp_path}")
    print(f"probe_nlp_path_detail={nlp_detail}")
    return 0


def _probe_import_and_app_ready(fresh_db: str, fresh_progress: str) -> int:
    """探针 B：``import_ms``（冷 import）+ ``app_ready_ms``（对**全新库**再装一次）。

    除两段耗时外还自报三条**机器无关**的自检：第二次 ``create_app()`` 之后，两张全新库里的
    ``sqlite_master`` 表数、以及它是否真写在新库路径上（见 ``_count_tables``）。把
    "app_ready 到底测到了什么"直接暴露成可断言的行，而不是靠跨进程耗时大小去猜。
    """
    _require_isolated_env()
    # 先记下 import 期模块级 create_app() 用的那套库（env 原值），供下面**独立**判「换没换路径」。
    main_db = os.environ["DATABASE_PATH"]
    start = time.perf_counter()
    server = importlib.import_module("delector.server")
    import_ms = (time.perf_counter() - start) * 1000.0

    # 模块级 create_app() 已经把 env 里那套库装好了；换到全新库再装一次，才能量到
    # 「冷库装配」（建表 + 预置文章导入 + 遇见区补装 + 静态挂载）而不是幂等空转。
    os.environ["DATABASE_PATH"] = fresh_db
    os.environ["PROGRESS_DB_PATH"] = fresh_progress
    create_app: Callable[[], Any] = server.create_app
    start_app = time.perf_counter()
    create_app()
    app_ready_ms = (time.perf_counter() - start_app) * 1000.0

    # 行为自检：第二次 create_app() 必须把表建在**全新库**上（而不是又写回模块级那套 main_db）。
    # 表在就是 ≥1、不在就是 0 —— 与机器/缓存无关，是这条门禁真正的防恒真判据。
    app_ready_db_tables = _count_tables(fresh_db)
    app_ready_progress_tables = _count_tables(fresh_progress)
    # fresh_used **独立**判「新库文件真的出现在新路径上」：不再由表数派生（那样两者同真同假，
    # 名字却暗示"判路径"）。这里查三样彼此独立的证据：文件在、规范化绝对路径与 main_db 不同、
    # 且（拿得到 inode 时）inode 也不同。表数断言仍在下方独立保留，两条不再互为派生。
    fresh_exists = os.path.isfile(fresh_db)
    path_differs = os.path.normcase(os.path.abspath(fresh_db)) != os.path.normcase(os.path.abspath(main_db))
    inode_differs = True  # 拿不到 inode 时不影响判定；拿得到则必须不同（顺带比对）
    try:
        if fresh_exists and os.path.isfile(main_db):
            inode_differs = os.stat(fresh_db).st_ino != os.stat(main_db).st_ino
    except OSError:
        inode_differs = True
    fresh_used = "yes" if fresh_exists and path_differs and inode_differs else "no"

    print(f"probe_import_ms={import_ms:.2f}")
    print(f"probe_app_ready_ms={app_ready_ms:.2f}")
    print(f"probe_app_ready_db_tables={app_ready_db_tables}")
    print(f"probe_app_ready_progress_tables={app_ready_progress_tables}")
    print(f"probe_app_ready_fresh_db_used={fresh_used}")
    return 0


def _serve(port: int) -> int:
    """探针 C（常驻）：起真实 uvicorn 服务，供父进程轮询 ``/api/health``。"""
    _require_isolated_env()
    uvicorn = importlib.import_module("uvicorn")
    server = importlib.import_module("delector.server")
    config = uvicorn.Config(
        server.app,
        host=_HOST,
        port=port,
        reload=False,
        log_level="warning",
        access_log=False,
    )
    uvicorn.Server(config).run()
    return 0


# --------------------------------------------------------------------------- #
# 父进程侧：跑子进程、轮询健康探针
# --------------------------------------------------------------------------- #
def _tail(path: str, limit: int = 2000) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()[-limit:]
    except OSError as exc:
        return f"(读日志失败：{exc})"


def _run_probe(args: List[str], env: Dict[str, str]) -> Dict[str, str]:
    """跑一个子进程探针，解析它打印的 ``probe_<key>=<value>`` 行。"""
    proc = subprocess.run(
        [sys.executable, _SCRIPT, *args],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=_PROBE_TIMEOUT_SEC,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"探针 {args} 退出码 {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    parsed = dict(re.findall(r"^probe_([a-z_]+)=(.*)$", proc.stdout, re.MULTILINE))
    if not parsed:
        raise RuntimeError(f"探针 {args} 没打印任何 probe_* 行：\n{proc.stdout}")
    return parsed


def _wait_health_200(port: int, proc: subprocess.Popen[str], start: float, timeout: float) -> Optional[float]:
    """轮询 ``/api/health`` 直到 200，返回从 ``start`` 起的墙钟毫秒；失败返 None。"""
    url = f"http://{_HOST}:{port}/api/health"
    while time.perf_counter() - start < timeout:
        if proc.poll() is not None:  # 子进程已退出（端口被抢 / import 炸了）
            return None
        try:
            with urllib.request.urlopen(url, timeout=2.0) as response:
                if int(response.status) == 200:
                    response.read()
                    return (time.perf_counter() - start) * 1000.0
        except urllib.error.HTTPError:
            pass  # 503 = 库不可用（main.py:2612）：继续轮询，超时后由调用方响亮失败
        except (urllib.error.URLError, ConnectionError, socket.timeout, OSError):
            pass  # 还没监听
        time.sleep(_POLL_INTERVAL_SEC)
    return None


def _terminate(proc: Optional[subprocess.Popen[str]]) -> None:
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


def _measure_health_200(data_dir: str, db_path: str, progress_path: str) -> float:
    """起真实 uvicorn 子进程，测「Popen → /api/health 首次 200」的墙钟。

    端口冲突（bind 到子进程 bind 之间被抢）用换端口重试兜住，而不是写死端口。
    """
    last_error = "未知原因"
    for attempt in range(_PORT_RETRIES):
        port = _free_port()
        log_path = os.path.join(os.path.dirname(db_path), f"serve_{attempt}.log")
        proc: Optional[subprocess.Popen[str]] = None
        try:
            start = time.perf_counter()
            with open(log_path, "w", encoding="utf-8") as log:
                proc = subprocess.Popen(
                    [sys.executable, _SCRIPT, "--serve", "--port", str(port)],
                    cwd=_REPO_ROOT,
                    env=_child_env(data_dir, db_path, progress_path),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                elapsed = _wait_health_200(port, proc, start, _HEALTH_TIMEOUT_SEC)
            if elapsed is None:
                last_error = _tail(log_path) or f"子进程已退出（端口 {port}）"
                continue
            return elapsed
        finally:
            _terminate(proc)
    raise RuntimeError(
        f"/api/health 在 {_PORT_RETRIES} 次尝试内都没返回 200，最后一次日志尾部：{last_error}"
    )


def _prepare_round_dir(tmpdir: str) -> Dict[str, str]:
    """在临时数据目录里摆好各探针**各自的**库路径（保证每段都是冷库）。"""
    paths = {
        "main_db": os.path.join(tmpdir, "delector.db"),
        "main_progress": os.path.join(tmpdir, "progress.db"),
        "initdb_db": os.path.join(tmpdir, "initdb", "init.db"),
        "initdb_progress": os.path.join(tmpdir, "initdb", "init_progress.db"),
        "appready_db": os.path.join(tmpdir, "appready", "second.db"),
        "appready_progress": os.path.join(tmpdir, "appready", "second_progress.db"),
        "serve_db": os.path.join(tmpdir, "serve", "serve.db"),
        "serve_progress": os.path.join(tmpdir, "serve", "serve_progress.db"),
    }
    for sub in ("initdb", "appready", "serve"):
        os.makedirs(os.path.join(tmpdir, sub), exist_ok=True)
    # 迁移闸中和：0 字节文件（SQLite 视为空库），理由见 DATA_DIR_GATE_NOTE。
    with open(paths["main_db"], "wb"):
        pass
    return paths


def _measure_round() -> Dict[str, Any]:
    """一轮完整冷启动测量：三个干净子进程 + 一轮真实起服务。"""
    tmpdir = tempfile.mkdtemp(prefix="delector_bench_cold_start_")
    try:
        paths = _prepare_round_dir(tmpdir)
        probe_a = _run_probe(
            ["--probe", "model"],
            _child_env(tmpdir, paths["initdb_db"], paths["initdb_progress"]),
        )
        probe_b = _run_probe(
            ["--probe", "import", "--fresh-db", paths["appready_db"], "--fresh-progress", paths["appready_progress"]],
            _child_env(tmpdir, paths["main_db"], paths["main_progress"]),
        )
        health_200_ms = _measure_health_200(tmpdir, paths["serve_db"], paths["serve_progress"])
        # 行为自检：子进程是否真把缓存目录建在了临时数据目录里（父进程漏传 env ⇒ 否）。
        child_isolated = os.path.isdir(os.path.join(tmpdir, ".cache", "audio"))
        return {
            "import_ms": float(probe_b["import_ms"]),
            "app_ready_ms": float(probe_b["app_ready_ms"]),
            "model_load_ms": float(probe_a["model_load_ms"]),
            "init_db_ms": float(probe_a["init_db_ms"]),
            "init_db_tables": int(probe_a["init_db_tables"]),
            "init_db_progress_tables": int(probe_a["init_db_progress_tables"]),
            "health_200_ms": health_200_ms,
            "nlp_path": probe_a["nlp_path"],
            "nlp_path_detail": probe_a["nlp_path_detail"],
            "child_isolated": child_isolated,
            "app_ready_db_tables": int(probe_b["app_ready_db_tables"]),
            "app_ready_progress_tables": int(probe_b["app_ready_progress_tables"]),
            "app_ready_fresh_db_used": probe_b["app_ready_fresh_db_used"],
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _median_ms(samples: List[float]) -> float:
    """中位数：单轮会被 GC / 磁盘 / 杀毒软件扫描污染成尖峰，中位数对单侧尖峰不敏感。"""
    return float(statistics.median(samples))


# --------------------------------------------------------------------------- #
# 结论（[Instinct: No-Silent-Conclusion]）
# --------------------------------------------------------------------------- #
def _repo_db_signature() -> Optional[Tuple[int, int]]:
    path = os.path.join(_REPO_ROOT, "delector.db")
    if not os.path.isfile(path):  # CI 上通常没有 ⇒ 无从改动，输出 absent 而非假装通过
        return None
    stat = os.stat(path)
    return (stat.st_size, stat.st_mtime_ns)


def _verdict(
    health_200_ms: float,
    import_ms: float,
    model_load_ms: float,
    init_db_ms: float,
    app_ready_ms: float,
    nlp_path: str,
    residual_ms: float,
) -> str:
    """点名 Android 已知口径的可判定结论。

    纪律：84000 ms 是**轮询上限**，30MB 是**解包量**，两者都不是实测首启耗时 ⇒
    结论里**不得**把它们与桌面数字相减/相除得出「Android 侧还剩多少」。
    """
    head = (
        f"桌面首次启动（空数据目录）到 /api/health 200 的中位墙钟 health_200_ms={health_200_ms:.0f}"
        f"（≈{health_200_ms / 1000.0:.1f}s），nlp_path={nlp_path}"
    )
    # 各段来自不同子进程、前置状态不同 ⇒ 任何跨进程比率（model_load/import、单项/health_200）
    # 都不是份额、不可作证据。故这里**不给百分比**，只保留"不可比大小"的口径。
    segments = (
        f"分段（各段独立子进程、不可比大小，见 segments_note）：import_ms={import_ms:.0f}"
        f"（其中 spaCy 模型加载 model_load_ms={model_load_ms:.0f}：跨进程近似归因，仅示意、不可当份额）"
        f"｜init_db_ms={init_db_ms:.0f}（仅建表）｜create_app(第二次装配, 冷度与 probe A 不同源) "
        f"app_ready_ms={app_ready_ms:.0f}"
        f"｜其余（进程起 + uvicorn 装配 + 首个请求）≈{residual_ms:.0f}"
    )
    # 近似归因（跨进程，仅示意）：只用来定位"本机实测里哪个单项最大"。含跨进程相减 ⇒ 原始差
    # 可为负，故 max 到 0 仅作显示，不代表它是独立分段。
    parts = {
        "spaCy 模型加载": model_load_ms,
        # 跨进程相减，仅作示意，可为负（下面的 max 到 0 只为显示，不代表它是独立分段）。
        "其余 import（路由模块 + 首装 create_app）": max(import_ms - model_load_ms, 0.0),
        "进程起 + uvicorn 装配 + 首请求（近似）": max(residual_ms, 0.0),
    }
    biggest = max(parts, key=lambda key: parts[key])
    # 建议方向据"本机实测分布"给出，**不**用跨进程比率当证据（所以这里不打印占比）。
    desktop = (
        f"桌面侧归因（近似归因，各段跨进程、仅示意）：本机实测分布里最大单项是『{biggest}』"
        f"{parts[biggest]:.0f}ms；据此，要压桌面首启先压它（方向据本机实测分布，非跨进程比率论证）"
    )
    android = (
        f"对照 Android 已知口径（docs/agents/architecture.md:100-101：首次启动解包约 "
        f"{ANDROID_UNPACK_MB:g}MB 写盘、启动页轮询上限约 {ANDROID_POLL_CAP_MS:g} ms）："
        f"{ANDROID_NOTE}"
    )
    ratio = ANDROID_POLL_CAP_MS / health_200_ms if health_200_ms > 0 else 0.0
    if health_200_ms > ANDROID_POLL_CAP_MS:
        judge = (
            f"判定：桌面首启 {health_200_ms:.0f}ms 已超过 Android 轮询上限 {ANDROID_POLL_CAP_MS:g}ms"
            f" —— 桌面侧慢于 Android 侧最坏假设（解包 + 轮询全满），首优面在桌面；"
            f"但本档对机器负载极敏感，需复核负载后复跑再定"
        )
    elif ratio >= 10.0:
        judge = (
            f"判定：桌面首启仅用掉 Android 轮询上限的 1/{ratio:.0f}（余量 {ratio:.0f}×）⇒ "
            f"Android 那 {ANDROID_POLL_CAP_MS:g}ms 的绝大部分**不可能**由本脚本可测的这几段"
            f"（Python import + 建库 + 装配）解释，首启瓶颈落在本机不可测的 Chaquopy 解包"
            f"（约 {ANDROID_UNPACK_MB:g}MB 写盘）环节；要证实须在真机/模拟器上测，本计划不伪造"
        )
    else:
        judge = (
            f"判定：桌面首启为 Android 轮询上限的 1/{ratio:.1f}（余量 {ratio:.1f}×，不足 10×）⇒ "
            f"与 {ANDROID_UNPACK_MB:g}MB 解包同量级的可能性存在，不能排除 Android 首启主要由解包"
            f"之外的 Python 侧造成；仍需真机数据（android=unmeasured）"
        )
    tail = ""
    if nlp_path != "spacy":
        tail = (
            "；降级边界：本环境 spaCy 不可用，import_ms / model_load_ms 量到的是纯 Python 降级路径"
            "的 import 成本，不代表带模型机器的冷启动"
        )
    return f"{head}；{segments}；{desktop}；{android}；{judge}{tail}"


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def _parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DeLector 冷启动基准（进程起 → 可服务）")
    parser.add_argument("--probe", choices=("model", "import"), default="", help="子进程探针模式")
    parser.add_argument("--serve", action="store_true", help="子进程模式：起 uvicorn 供父进程轮询")
    parser.add_argument("--port", type=int, default=0, help="--serve 模式下的监听端口（父进程动态分配）")
    parser.add_argument("--fresh-db", default="", help="--probe import 模式下第二次 create_app 用的全新库")
    parser.add_argument("--fresh-progress", default="", help="同上，对应的 progress 库")
    return parser.parse_args(argv)


def _run_benchmark(rounds: int) -> int:
    repo_before = _repo_db_signature()
    sample_keys = ("import_ms", "init_db_ms", "app_ready_ms", "health_200_ms", "model_load_ms")
    samples: Dict[str, List[float]] = {key: [] for key in sample_keys}
    nlp_path = "unknown"
    nlp_detail = ""
    isolated = True
    init_db_tables: List[int] = []
    init_db_progress_tables: List[int] = []
    app_ready_db_tables: List[int] = []
    app_ready_progress_tables: List[int] = []
    fresh_used_flags: List[bool] = []
    for _ in range(rounds):
        result = _measure_round()
        for key in samples:
            samples[key].append(float(result[key]))
        nlp_path = str(result["nlp_path"])
        nlp_detail = str(result["nlp_path_detail"])
        isolated = isolated and bool(result["child_isolated"])
        init_db_tables.append(int(result["init_db_tables"]))
        init_db_progress_tables.append(int(result["init_db_progress_tables"]))
        app_ready_db_tables.append(int(result["app_ready_db_tables"]))
        app_ready_progress_tables.append(int(result["app_ready_progress_tables"]))
        fresh_used_flags.append(str(result["app_ready_fresh_db_used"]) == "yes")

    medians = {key: _median_ms(values) for key, values in samples.items()}
    residual_ms = medians["health_200_ms"] - medians["import_ms"]
    # 表数取**最小轮**（最保守）：任一轮为 0 就报 0 ⇒ 门会红；fresh 要求**每轮**都为 yes。
    # probe A 与 probe B 同口径（都取最小轮），守卫对称。
    min_init_db_tables = min(init_db_tables) if init_db_tables else 0
    min_init_db_progress_tables = min(init_db_progress_tables) if init_db_progress_tables else 0
    min_app_ready_db_tables = min(app_ready_db_tables) if app_ready_db_tables else 0
    min_app_ready_progress_tables = min(app_ready_progress_tables) if app_ready_progress_tables else 0
    app_ready_fresh_used = "yes" if fresh_used_flags and all(fresh_used_flags) else "no"
    repo_after = _repo_db_signature()
    if repo_before is None and repo_after is None:
        repo_state = "absent"  # CI 上没有真实库文件 ⇒ 无从改动，不算通过也不算失败
    elif repo_before == repo_after:
        repo_state = "yes"
    else:
        repo_state = "no"

    print("=== bench_cold_start ===")
    print(f"rounds={rounds}")
    print(f"nlp_path={nlp_path}")
    print(f"nlp_path_detail={nlp_detail}")
    print(f"import_ms={medians['import_ms']:.2f}")
    print(f"init_db_ms={medians['init_db_ms']:.2f}")
    print(f"init_db_tables={min_init_db_tables}")
    print(f"init_db_progress_tables={min_init_db_progress_tables}")
    print(f"app_ready_ms={medians['app_ready_ms']:.2f}")
    print(f"app_ready_db_tables={min_app_ready_db_tables}")
    print(f"app_ready_progress_tables={min_app_ready_progress_tables}")
    print(f"app_ready_fresh_db_used={app_ready_fresh_used}")
    print(f"health_200_ms={medians['health_200_ms']:.2f}")
    # p95 与中位数取自**同一批**样本（不重新计时）：冷启动每轮一个全新解释器，重跑
    # 一遍计时就等于换了一次测量，尾部与中位数不再可比。
    print(f"health_200_p95_ms={p95_ms(samples['health_200_ms']):.2f}")
    print(f"samples_health_200_ms={format_samples(samples['health_200_ms'])}")
    print(f"model_load_ms={medians['model_load_ms']:.2f}")
    print(f"import_other_ms={medians['import_ms'] - medians['model_load_ms']:.2f}")
    print(f"residual_ms={residual_ms:.2f}")
    print(f"model_load_note={MODEL_LOAD_NOTE}")
    print(f"segments_note={SEGMENTS_NOTE}")
    print(f"data_dir_gate_note={DATA_DIR_GATE_NOTE}")
    print(f"bind_host={_HOST}")
    print(f"port_source=dynamic(bind {_HOST}:0 → getsockname，失败换端口重试 {_PORT_RETRIES} 次)")
    print("db_state=empty(每轮全新临时数据目录 ⇒ init_db 与预置内容导入全走冷路径)")
    print(f"child_isolation_verified={'yes' if isolated else 'no'}")
    print(f"repo_db_untouched={repo_state}")
    print(f"android={ANDROID_STATUS}")
    print(f"android_note={ANDROID_NOTE}")
    verdict_text = _verdict(
        medians["health_200_ms"],
        medians["import_ms"],
        medians["model_load_ms"],
        medians["init_db_ms"],
        medians["app_ready_ms"],
        nlp_path,
        residual_ms,
    )
    print(f"verdict={verdict_text}")
    return 0 if repo_state != "no" else 1


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    if args.serve:
        return _serve(args.port)
    if args.probe == "model":
        return _probe_model_and_initdb()
    if args.probe == "import":
        return _probe_import_and_app_ready(args.fresh_db, args.fresh_progress)
    return _run_benchmark(_env_rounds())


if __name__ == "__main__":
    raise SystemExit(main())
