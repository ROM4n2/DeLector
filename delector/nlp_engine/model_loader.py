# -*- coding: utf-8 -*-
"""spaCy 模型加载的唯一真相源（ADR-0018 §7.6 / ADR-0027 / ADR-0028）。

本模块只做「拿一个可用的 spaCy 模型」这一件事：模型名常量、本地三级回退、自动下载
兜底（Android 禁止）、服务就绪后后台预热、惰性加载缓存、加载失败诊断与引擎状态。

依赖方向（重构前 `processor` 与 `syntax_tree` 互为反向导入，把环藏在函数内）：

    processor ──> model_loader <── syntax_tree

两个消费方都只单向依赖本模块，模块级依赖图不再闭环。
"""

import importlib
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    import spacy as spacy  # 显式再导出：processor 等模块按原路径 `processor.spacy` 使用
except ImportError:
    # spaCy 缺失时的运行时降级占位（红线 1：降级路径是有意设计）。
    spacy = None  # type: ignore[assignment]

from delector.core.utils import is_android

# 模型档位定案（ADR-0027，2026-11-04）：只支持 de_core_news_sm。
# 历史上的 "md 优先" 从未生效（CI、自动下载、Android 打包、uv 环境都只装 sm），
# 只是被 sm 静默兜底 —— 代码与运行事实不符。运行期加载与自动下载共用这一个常量，
# 不再保留候选元组或独立的下载口径。要评估 md 必须另立一次性实验（ADR-0027 OPEN）。
SPACY_MODEL_NAME = "de_core_news_sm"


def _load_spacy_model(name: str) -> Tuple[Any, str]:
    """加载指定德语模型，返回 (nlp, 加载方式描述)；全部策略失败则抛 RuntimeError。

    为什么不能只用 spacy.load(name)：它走 spacy.util.is_package()，查的是
    importlib.metadata 的 .dist-info 元数据。当前打包（含 Android APK）已含 dist-info，
    `spacy.load` 可用；三级回退仅防御**打包方式回退**——历史上曾把模型裸拷进 Chaquopy
    源码目录、缺 dist-info 导致 "[E050] Can't find model"（2026-11-05 实测该问题已修复，
    ADR-0028）。所以按名称失败后仍要退到模块自身的 load()，最后退到数据目录路径。
    """
    errors = []
    try:
        return spacy.load(name), name
    except Exception as e:
        errors.append(f"spacy.load({name!r}) -> {e}")

    try:
        module = importlib.import_module(name)
    except Exception as e:
        errors.append(f"import {name} -> {e}")
        raise RuntimeError("; ".join(errors))

    try:
        # 等价于 load_model_from_init_py(module.__file__)，绕开 is_package 检查
        return module.load(), f"{name}(module.load)"
    except Exception as e:
        errors.append(f"{name}.load() -> {e}")

    try:
        # meta.json 里的版本与实际数据目录名不一致时，上一步会失败，这里直接找目录
        module_file = module.__file__
        if not module_file:
            # __file__ 缺失时原实现在 Path(None) 处抛 TypeError 被外层 except 吞掉，
            # 错误信息含混；这里显式抛出同类失败（同样被外层捕获并记入 errors）。
            raise FileNotFoundError(f"{name} 模块没有 __file__，无法定位数据目录")
        root = Path(module_file).parent
        data_dirs = sorted(root.glob(f"{name}-*"))
        if not data_dirs:
            raise FileNotFoundError(f"{root} 下没有 {name}-* 数据目录")
        return spacy.load(data_dirs[-1]), f"{name}({data_dirs[-1].name})"
    except Exception as e:
        errors.append(f"path load -> {e}")

    raise RuntimeError("; ".join(errors))


# ── 惰性模型加载（ADR-0018 §7.6 O0 杠杆 / ADR-0021 替代投资#4）────────────────────
# 为什么改惰性：桌面冷启动到 /api/health 200 约 2.6~3.1s，其中 spacy.load 模型约
# 1.5~1.7s（约占首启 58%）。把模型加载从 import 期搬到「首次真正需要 NLP 时」，冷启动
# 只付 import 成本；代价是首次 NLP 请求要多等一次模型加载（量化见 tools/bench_cold_start.py）。
# 2026-11-06 修订（ADR-0028）：这个代价在 Android 实测为 +1,215.6 ms（T5/T6），故增加
# 服务就绪后后台预热，把等待移出用户路径；首次使用仍保留同步兜底（见下方预热段）。
# 三条硬约束：① import 期不得 spacy.load；② 首次并发调用只加载一次（互斥锁 + 双检）；
# ③ 加载失败必须**大声失败**（抛异常），不得静默返回空结果。
_model_lock = threading.Lock()
_nlp_model: Any = None  # 解析成功后的真实模型对象
_nlp_resolved = False  # 是否已解析（成功或失败都置位，保证「只加载一次」）
_nlp_error = ""  # 解析失败原因（供错误信息与诊断）

# ── 服务就绪后后台预热（ADR-0028 2026-11-06 修订）──────────────────────────────
# 动因：Android T5/T6 实测首次分析仍多付 1,215.6 ms（改造前 12.6 ms）的模型加载。
# 选项 B：服务就绪（uvicorn lifespan startup）后起后台线程加载，把这段时间移出用户等待；
# 首次分析若恰好早于预热完成，仍走 `_resolve_nlp_model()` 同步兜底（同一把 `_model_lock`，
# 只会真正加载一次）。
# 硬约束：① 只在 lifespan 触发，import 期绝不加载；② 不阻塞启动路径与 /api/health；
# ③ 失败语义不变（D4 硬失败，后台线程只记录诊断、不崩进程）；④ 可用环境变量整体关闭。
PREWARM_ENV = "DELECTOR_MODEL_PREWARM"
_PREWARM_DISABLED_VALUES = frozenset({"0", "false", "no", "off", "disabled"})

# 预热起步前的静默窗口（秒）：让 uvicorn 完成 bind、首个 /api/health 与窗口出现先走完，
# 避免后台模型加载在启动瞬间争抢 GIL。预热本身仍是纯后台，不阻塞任何请求。
_PREWARM_GRACE_S = 0.5

_prewarm_lock = threading.Lock()
_prewarm_started = False
_prewarm_thread = None  # type: Any  # 供测试确定性地 join；生产不依赖它
_model_load_count = 0  # `_resolve_nlp_model` 真正进入加载入口的次数（预热/并发证据）

# 平台判定：Android 运行期禁止 spacy.cli.download（Chaquopy 里会起 pip 子进程阻塞启动页）。
# 这里先算一次，作为 `_load_model_with_autodownload` 的下载门控依据。
_android_runtime = is_android()

# 导入期只做**廉价**判定（import spacy 已在模块顶部试过），绝不在此 spacy.load。
# 此处写下的 NLP_ENGINE 是**导入期声明值**：spaCy 可用时（桌面与 Android 同口径）为 "spacy"，
# **不代表模型已加载**——模型的**真实**加载结果由 `_resolve_nlp_model` 在首次使用时回填
#（成功仍 "spacy"、失败改 "spacy(加载失败)"）。真机可用 adb logcat / GET /api/settings 确认实际走的路径。
if spacy is None:
    # 红线 1：spaCy 缺失 ⇒ 纯 Python 降级路径（既有语义，保持不变）。
    NLP_ENGINE = "pure_python"
    NLP_ENGINE_DETAIL = "spaCy 未安装，使用纯 Python 降级路径（无依存句法/格标注）"
else:
    # spaCy 可用（桌面与 Android 同口径，ADR-0028）：服务就绪后后台预热。
    # import 期**不** spacy.load；预热由 lifespan 触发，首次使用若仍未加载则同步兜底。
    # 故下面的 NLP_ENGINE = "spacy" 是**声明值**（模型未加载也如此），**不是**"首次加载成功才赋值"。
    NLP_ENGINE = "spacy"
    NLP_ENGINE_DETAIL = (
        f"spaCy {getattr(spacy, '__version__', 'unknown')} 已装（服务就绪后后台预热；"
        "预热未完成时首次使用同步加载）"
    )

print(f"[DeLector] NLP 引擎: {NLP_ENGINE} — {NLP_ENGINE_DETAIL}", flush=True)


def _load_model_with_autodownload() -> Tuple[Any, str]:
    """加载唯一模型（sm）；本地加载失败时自动下载同一模型一次兜底。返回 (nlp, 加载方式描述)。

    Android 例外（ADR-0028 D5）：只做本地三级回退，**绝不** `spacy.cli.download`
    （Chaquopy 里会起 pip 子进程阻塞启动页且无网络）。本地失败直接抛 RuntimeError，
    由 `_resolve_nlp_model` 按硬失败处理，不降级纯 Python。

    门控 MUST 留在本函数内部（不能只靠调用方不进入）：否则本地回退失败后会起 pip 子进程/联网。
    """
    if _android_runtime:
        return _load_spacy_model(SPACY_MODEL_NAME)
    errors: List[str] = []
    try:
        return _load_spacy_model(SPACY_MODEL_NAME)
    except Exception as e:
        errors.append(str(e))
    try:
        from spacy.cli import download  # type: ignore[attr-defined]  # spacy.cli 不显式导出 download

        download(SPACY_MODEL_NAME)
        return _load_spacy_model(SPACY_MODEL_NAME)
    except Exception as e:
        errors.append(f"自动下载 {SPACY_MODEL_NAME} -> {e}")
    raise RuntimeError("; ".join(errors))


def _require_loaded_model() -> Any:
    """读取已解析模型；此前解析失败则抛出同一失败（不反复重试，避免每次请求都慢）。"""
    if _nlp_model is None:
        raise RuntimeError(f"德语 spaCy 模型不可用（此前加载失败）：{_nlp_error}")
    return _nlp_model


def get_spacy_load_error() -> str:
    """返回运行期模型加载失败的最新诊断（成功或尚未解析则为空串）。"""
    return _nlp_error


def get_nlp_readiness() -> Dict[str, Any]:
    """只读返回 NLP 就绪状态（**零副作用**：绝不触发加载、绝不下模型）。

    ``state`` 语义（供 `/api/health` 与文章详情快退判定）：
    - ``ready``：模型已加载，可直接分词；
    - ``loading``：尚未解析（含后台预热进行中 / 尚未开始预热）—— 此时请求内同步加载
      会把首开拖到数十秒，必须让调用方选择「返回旧结果」或「503 + Retry-After」；
    - ``error``：此前尝试加载失败（硬失败，不降级到纯 Python，按红线 1）；
    - ``unavailable``：运行环境没有 spaCy（导入期判定的纯 Python 平台路径）。

    为什么需要它：Android 首屏在服务 listening 后立刻可进入，但 spaCy 仍在后台预热；
    没有这个只读探针，`GET /api/articles/{id}` 的惰性迁移只能在请求里硬等模型加载，
    前端 fetch 超时后把「还没准备好」渲染成「加载失败」（2026-11-10 真机点验）。
    """
    if spacy is None:
        state = "unavailable"
    elif _nlp_resolved and _nlp_model is not None:
        state = "ready"
    elif _nlp_resolved:
        state = "error"
    else:
        state = "loading"
    return {
        "state": state,
        "loaded": state == "ready",
        "model": SPACY_MODEL_NAME,
        "prewarm_started": _prewarm_started,
        "error": _nlp_error if state == "error" else "",
    }


def _resolve_nlp_model() -> Any:
    """首次真正需要 NLP 时加载模型；成功返回模型，失败抛 RuntimeError（No-Silent-Failure）。

    并发安全（双检）：无锁快路径先查 `_nlp_resolved`，只有未解析才进锁，锁内再查一次 ——
    uvicorn 的首批并发请求因此只触发一次 spacy.load，其余等锁后复用同一结果，不会出现
    「两次加载」或「半初始化被读到」。

    引擎状态同步：`NLP_ENGINE` / `NLP_ENGINE_DETAIL` 在**导入期**已声明为 "spacy"（**声明值**，
    不代表模型已加载，见本模块导入期分支）；本函数成功时用**实际加载结果**再刷一遍，失败时
    改写为 "spacy(加载失败)"（让 live 读取方看到真实状态；理由见失败分支注释）。
    """
    global _nlp_model, _nlp_resolved, _nlp_error, _model_load_count, NLP_ENGINE, NLP_ENGINE_DETAIL
    if _nlp_resolved:
        return _require_loaded_model()
    with _model_lock:
        if _nlp_resolved:
            return _require_loaded_model()
        # 计数放在加载入口之前、持锁区内：预热与并发首次分析共用本函数，
        # 因此「计数 == 1」就是「只真正加载一次」的可测证据。
        _model_load_count += 1
        try:
            _nlp_model, how = _load_model_with_autodownload()
        except Exception as e:
            # ② 失败语义（刻意设计，勿当 bug）：模型加载失败 = **硬失败，不降级**到纯 Python。
            # 理由：静默降级会让用户以为分析成功（拿到的是错误标注 —— 见 architecture.md
            # 「降级路径不只是精度低，而是会给出错误的语法标注」），比可见的 500 危险得多。
            # 注意：此时 `nlp` 仍是**非 None 的惰性代理**（本函数只记下「首用失败」），故本次及
            # 后续调用都抛 RuntimeError，绝不静默返回空值。
            # 与**红线 1**（spaCy 缺失 ⇒ 纯 Python）分属不同层次：那是**导入期**判定的平台路径
            # （`nlp is None`，见 processor 的导入期分支），发生在任何请求之前；本分支是
            # **运行期**模型加载失败，发生在首次真正需要 NLP 时。二者处置不同、互不影响。
            _nlp_error = str(e)
            _nlp_resolved = True
            # ③ 失败后同步反映真实状态（避免 /api/settings 仍报 spacy 的轻微误导）：`NLP_ENGINE`
            # 是**显示用**字符串，调用方判「能否调用」用的是 `nlp is None`（此处仍非 None）⇒ 改这
            # 个字符串**不破坏**可调用语义。live 读取方（/api/settings、各基准）据此看到真实状态；
            # by-value 快照方看不到（旧写法），故 routes/settings.py 的 /api/settings 已改为 live 读。
            NLP_ENGINE = "spacy(加载失败)"
            NLP_ENGINE_DETAIL = f"德语 spaCy 模型加载失败（硬失败，不降级到纯 Python）：{e}"
            print(f"[DeLector] NLP 引擎: {NLP_ENGINE} — {NLP_ENGINE_DETAIL}", flush=True)
            raise RuntimeError(f"德语 spaCy 模型加载失败（首次使用时加载）：{e}") from e
        # 成功：NLP_ENGINE 在导入期已是 "spacy"（声明值），这里用实际加载到的模型信息刷新 detail。
        NLP_ENGINE = "spacy"
        NLP_ENGINE_DETAIL = f"spaCy {getattr(spacy, '__version__', 'unknown')} + {how}"
        _nlp_resolved = True
        print(f"[DeLector] NLP 引擎（模型已加载）: {NLP_ENGINE} — {NLP_ENGINE_DETAIL}", flush=True)
        return _nlp_model


# ── 后台预热入口（ADR-0028 2026-11-06 修订）────────────────────────────────────
def prewarm_enabled() -> bool:
    """`DELECTOR_MODEL_PREWARM` 是否开启：未设置/其他值 = 开启，`0/false/no/off/disabled` = 关闭。"""
    raw = os.environ.get(PREWARM_ENV, "")
    return raw.strip().lower() not in _PREWARM_DISABLED_VALUES


def get_model_load_count() -> int:
    """返回 `_resolve_nlp_model()` 真正进入加载入口的次数（预热/首次分析共用该入口）。

    只统计带自动下载兜底的主入口；`try_load_nlp_no_download()` 的本地只读加载不计入。
    """
    return _model_load_count


def _prewarm_worker() -> None:
    """后台预热线程体：**只调用统一入口** `_resolve_nlp_model()`，不另开加载路径。

    - Android 禁下载门控在 `_load_model_with_autodownload()` 内部，走统一入口即自动生效。
    - 与首次分析共用 `_model_lock`：两边只会真正加载一次，另一边等锁后复用结果。
    - 失败不抛出到线程外（否则会留下未捕获异常栈，Android 上还可能被当成崩溃）；诊断由
      `_resolve_nlp_model()` 写入 `_nlp_error`，首次分析仍按 D4 抛 RuntimeError。
    """
    if _PREWARM_GRACE_S > 0:
        time.sleep(_PREWARM_GRACE_S)
    print("[DeLector] 模型预热：开始（后台）", flush=True)
    started_at = time.monotonic()
    try:
        _resolve_nlp_model()
    # silent-ok: 预热失败已记入 _nlp_error 并打印诊断，首次分析仍按 D4 硬失败
    except Exception as e:
        elapsed_ms = (time.monotonic() - started_at) * 1000.0
        print(f"[DeLector] 模型预热：失败（耗时 {elapsed_ms:.0f} ms）— {e}", flush=True)
        return
    elapsed_ms = (time.monotonic() - started_at) * 1000.0
    print(f"[DeLector] 模型预热：完成（耗时 {elapsed_ms:.0f} ms）", flush=True)


def start_background_prewarm() -> bool:
    """服务就绪后启动一次后台预热；返回是否真的起了线程（幂等）。

    调用点只有一个：`delector.server` 的 lifespan startup。**不得**在 import 期调用。
    不等待加载完成 —— 启动路径与 `/api/health` 不被阻塞。
    """
    global _prewarm_started, _prewarm_thread
    if not prewarm_enabled():
        print(f"[DeLector] 模型预热：未启用（{PREWARM_ENV}=0）", flush=True)
        return False
    if spacy is None:
        print("[DeLector] 模型预热：跳过（spaCy 未安装，纯 Python 路径）", flush=True)
        return False
    if _nlp_resolved:
        print("[DeLector] 模型预热：跳过（模型已解析）", flush=True)
        return False
    with _prewarm_lock:
        if _prewarm_started:
            return False
        _prewarm_started = True
        thread = threading.Thread(target=_prewarm_worker, name="delector-model-prewarm", daemon=True)
        _prewarm_thread = thread
        thread.start()
    return True


# ── 只读 / 无下载加载助手（Task 1：给产品层「拿一个可用的 nlp」但不付下载成本）────────
# 说明：`_resolve_nlp_model()` 是「首用即加载」且**带 `spacy.cli.download` 兜底**（出网 + 起 pip
# 子进程、无时限）。产品层的润色循环不能付这个成本，于是拆成两件更窄的只读/无下载算力。
def get_loaded_nlp() -> Any:
    """只读**已加载**的 spaCy 模型：仅当此前成功解析过（`_nlp_resolved` 且 `_nlp_model` 非 None）才返回。

    绝不触发加载、绝不 `spacy.cli.download` —— 这是给产品层「先看有没有现成模型」的纯读探针。
    与 `_resolve_nlp_model()` 的分工：后者是首用即加载（可能起下载），本函数是**零副作用读取**。
    """
    if _nlp_resolved and _nlp_model is not None:
        return _nlp_model
    return None


def try_load_nlp_no_download() -> Any:
    """按 `SPACY_MODEL_NAME` **只做本地加载**：能装就装（写回既有缓存），装不上就返回 None。

    **为什么需要这个中间态**（设计理由，勿删）：
    - 只用 `get_loaded_nlp()` 会让**桌面首次润色**也落在 `rules_only`（模型是惰性加载的，别处
      还没触发过）⇒ 生产上引擎标记长期假降级，与真实能力不符；
    - 直接调 `_resolve_nlp_model()` 会走 `spacy.cli.download`（出网 + 起 pip 子进程，无时限）；
    - 本函数取中间态：**本地能加载就加载、加载不上就诚实返回 None，绝不下载**。

    成功 ⇒ 写入既有缓存（`_nlp_model` / `_nlp_resolved=True`）并刷新 `NLP_ENGINE` / `NLP_ENGINE_DETAIL`；
    失败 ⇒ **不写任何全局**（不改 `_nlp_resolved` / `_nlp_error`），返回 None。

    同步函数（内部不 await），可在 `asyncio.to_thread` 里跑，避免阻塞事件循环。并发安全：
    沿用 `_model_lock` + 双检，保证与 `_resolve_nlp_model()` 共用同一份缓存、不重复加载。
    """
    global _nlp_model, _nlp_resolved, NLP_ENGINE, NLP_ENGINE_DETAIL
    if _nlp_resolved and _nlp_model is not None:
        return _nlp_model
    with _model_lock:
        if _nlp_resolved and _nlp_model is not None:
            return _nlp_model
        try:
            model, how = _load_spacy_model(SPACY_MODEL_NAME)
        except Exception:
            # 本地加载失败 ⇒ 诚实返回 None；**绝不**退到 spacy.cli.download（见 docstring）。
            return None
        _nlp_model = model
        _nlp_resolved = True
        NLP_ENGINE = "spacy"
        NLP_ENGINE_DETAIL = f"spaCy {getattr(spacy, '__version__', 'unknown')} + {how}"
        return _nlp_model
    return None


class _LazyNlp:
    """惰性 spaCy 模型代理：首次**调用**时才真正加载（ADR-0018 §7.6 O0）。

    为什么用代理而不是把 nlp 设成 None / 改成函数：既有调用方按**值**使用 `processor.nlp`
    （`from ... import nlp` 后 `nlp(text)` 与 `nlp is None`）。代理保留「可调用」这一既有语义，
    调用方无需改代码；同时把昂贵的 spacy.load 推迟到首次真正调用。`nlp is None` 仍能区分
    「spaCy 可用 vs 未安装」（仅 spaCy 缺失时绑定真正的 None，见 processor 的导入期分支）。
    """

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return _resolve_nlp_model()(*args, **kwargs)
