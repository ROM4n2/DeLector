# -*- coding: utf-8 -*-
"""`rank_sentences` / `analyze_syntax_tree` 的**纯函数单价**基准（ADR-0018 §8 `Unknown 5`）。

为什么需要这个脚本（它补的是**同一路径**上两个互相矛盾的旧值之间的缺口）
----------------------------------------------------------------------
`syntax_hard.py:9` 的模块 docstring **曾写** ``spaCy ~42ms/句``；审计文档
``docs/reviews/2026-09-28-swarm-audit-master.md:36`` 写 ``rank_sentences 实测 ~2.1 ms/句``，
**同一路径、差 20 倍**，且两边都不可复跑：

- 42ms 已于 2026-10-09 从代码移除（不可复跑、且不参与任何参数决策：TTL 由陈旧性决定、
  缓存容量由内存上界定、聚合 key 由淘汰悬崖决定，均非由该数字推出 —— 依据：perf 席位裁定）。
- 2.1ms 只活在审计文档里，没有脚本兜底 ⇒ 任何以它为输入的决策都悬空。

上一轮（``tools/bench_long_read.py``）覆盖的是**端到端**冷读：它走
``api_syntax_hard_sentences → _rank_source → rank_sentences``，实测 ≈10ms/句，但**含端点开销**
（DB 读正文、路由装配、序列化）。仍缺的是「**无端点开销的纯函数单价**」—— 本脚本补的就是它。

被测对象与口径纪律（**最重要的一条边界，改注释时务必一起守**）
------------------------------------------------------------
本脚本测一条路径上的**两个函数**，都是纯文本入参、不碰 DB：

========================  ==================================================================
口径                      被测函数
========================  ==================================================================
``analyze``（主口径）      ``analyze_syntax_tree``（``nlp_engine/syntax_tree.py:1521``）单句调用
                          —— 只建 clause_tree + topology，是单句分析的**最小口径**
``rank``                   ``rank_sentences``（``services/syntax_score.py:230``）整段调用
                          —— 内部逐句 ``analyze_syntax_tree`` 后评分排序；归一到每句
========================  ==================================================================

- **不可与端到端相除**：``bench_long_read`` 的 ≈10ms/句含 DB 读 + 端点装配/序列化，本脚本是
  纯函数（无端点开销），两者是不同口径，比值只能读作「端点开销占多少」的方向性参考。
- **不可与 ``bench_spacy_unit`` 比较**：它测的是 ``process_german_text``（**完整管线**：
  token + lemma + morph + CEFR 反查 + 可分动词回扫 + 统计），是**另一个函数**，更重。
- 42ms / 2.1ms 的被测对象正是本条路径 ⇒ 本脚本是**第一个**给出该路径可复跑值的脚本，
  但结论只允许对「落在哪一侧 + 是否足以解释 20 倍」下**可判定**结论，**不足以定案就明说不足**。

核心自变量：句长
----------------
该路径成本随句长（token 数）增长最明显，故语料内嵌短/中/长三档（各 6 句，共 18 句），
并输出三档各自的每句耗时与 token 数。**耗时与 token 数都要单调**，句长效应才成立
（只看耗时会把噪声当句长效应）。

口径与隔离（照抄既有基准，不另发明）
------------------------------------
- 中位数与 p95 **同批样本、不重新计时**：分位实现从 ``tools/bench_stats.py`` 取
  （n=5 的经验 p95 ≈ 最大值、**系统性低估尾部**，样本不足时不许拿它下强结论）；
- ``MIN_ROUNDS = 5``（[Instinct: Median-Not-Mean]：少于 5 轮噪声压不住）；
- 隔离：``tempfile.mkdtemp()`` + ``DELECTOR_DATA_DIR`` / ``DATABASE_PATH`` / ``PROGRESS_DB_PATH``
  三环境变量**在 import delector 之前**设好（``database.py`` 导入期就按 ``DATA_DIR`` 建目录），
  ``finally`` 里 ``shutil.rmtree`` 清理。**绝不打开仓库根的真实 ``delector.db``**。

``nlp_path`` 判定（`[Instinct: Model-Availability]`）
----------------------------------------------------
spaCy 加载失败会**静默降级**为纯 Python（``analyze_syntax_tree`` 分支在 ``get_spacy_nlp()``）。
故用**生产自己的判据**读实际路径（``syntax_tree.get_spacy_nlp()`` + ``processor.NLP_ENGINE``，
与 ``bench_spacy_unit.py`` 同款），只两层都报 spaCy 才标 ``nlp_path=spacy``；否则标 ``pure``，
此时本基准测的是纯 Python 路径，**与 spaCy 口径的历史值对照不成立**（verdict 明说）。

用法
----
::

    export PYTHONIOENCODING=utf-8
    python tools/bench_rank_sentences.py                       # 默认 7 轮中位数
    BENCH_RANK_ROUNDS=5 python tools/bench_rank_sentences.py   # 门禁快档（下限 5）

输出契约（``tests/test_rank_sentences_cost.py`` 逐行断言，勿改格式）::

    unit=analyze_syntax_tree|rank_sentences   # 本次报告的主口径（两者都测，主口径取 analyze）
    analyze_per_sentence_ms=N.NN              # analyze_syntax_tree 单句调用（中位）
    analyze_p95_ms=N.NN                       # 同上 p95（同批样本）
    analyze_per_token_us=N.NN
    rank_per_sentence_ms=N.NN                 # rank_sentences 整段 → 归一到每句（中位）
    rank_p95_ms=N.NN
    rank_per_token_us=N.NN
    sentences=N / tokens=N / rounds=N
    nlp_path=<spacy|pure>
    model=<实际生效模型名>                    # de_core_news_md / de_core_news_sm (md 不可用) / pure-python
    p95_note=<两条 p95 不可直接比较/相除的声明>
    samples_analyze_ms=<逗号分隔>             # 原始样本（可审计）
    verdict=<可判定结论>
"""

from __future__ import annotations

import math
import os
import shutil
import sys
import tempfile
import time
from typing import Any, Callable, Dict, List, Tuple

# bench_stats 与本脚本同处 tools/：以脚本方式运行（`python tools/xxx.py`）时 Python 已把
# tools/ 放进 sys.path[0]，故可直接顶层导入（放在这里也顺带避开 E402）。p95 口径与它的
# 已知偏差方向见 tools/bench_stats.py —— 各基准必须共用同一份实现，不许各写一份。
from bench_stats import format_samples, median_ms, p95_ms

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLS_DIR = os.path.join(_REPO_ROOT, "tools")
# tools/ 也要进 sys.path：本脚本与其余基准共用 tools/bench_stats.py 的分位口径，
# 而 tools/ 不是包（无 __init__.py），只能靠目录进路径做顶层导入。
for _path in (_REPO_ROOT, _TOOLS_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

MIN_ROUNDS = 5  # 取中位数而非均值；少于 5 轮噪声压不住（[Instinct: Median-Not-Mean]）
DEFAULT_ROUNDS = 7

# 三个对照值（改这里等于改对照对象）。历史值 42ms 已从代码移除、2.1ms 只活在审计文档里，
# 两者都不可复跑；端到端 ≈10ms/句来自 tools/bench_long_read.py，含端点开销。
LEGACY_SYNTAX_HARD_MS = 42.0  # 原 delector/routes/syntax_hard.py:9 注释（2026-10-09 移除）
LEGACY_AUDIT_MS = 2.1  # docs/reviews/2026-09-28-swarm-audit-master.md:36
LEGACY_LONG_READ_E2E_MS = 10.0  # tools/bench_long_read.py 端到端冷读 ≈10ms/句
# 对数中点 = sqrt(2.1 * 42) ≈ 9.39：用它而非算术中点（22ms）判"落在哪一侧"，
# 因为 20 倍是**倍数**差距，算术中点会把 9ms 这种量级误判到 42ms 一侧。
LEGACY_GEO_MID_MS = math.sqrt(LEGACY_SYNTAX_HARD_MS * LEGACY_AUDIT_MS)

# verdict 开头必须声明被测对象，否则读者会拿它去和另一个口径相除。
MEASURED_TARGET = "rank_sentences→analyze_syntax_tree（纯函数：仅 clause_tree+topology，不碰 DB）"
# 本次报告的主口径：纯函数最小口径 analyze_syntax_tree（rank 归一到每句作为对照）。
UNIT_MAIN = "analyze_syntax_tree"

# 被测函数签名（显式类型，供 mypy --strict 与可读性）。
AnalyzeFn = Callable[[str], Dict[str, Any]]
RankFn = Callable[[str], object]

# --------------------------------------------------------------------------- #
# 真实德语语料：内嵌（不依赖任何数据文件，保证可复现），分短/中/长三档
# --------------------------------------------------------------------------- #
CORPUS_SHORT: Tuple[str, ...] = (
    "Der Bahnhof liegt hinter dem alten Rathaus.",
    "Ich kaufe jeden Morgen frische Brötchen.",
    "Das Kind spielt laut im kleinen Garten.",
    "Wir fahren morgen mit dem Zug nach München.",
    "Seine Schwester arbeitet seit Jahren im Krankenhaus.",
    "Der Regen dauerte die ganze Nacht an.",
)

CORPUS_MID: Tuple[str, ...] = (
    "Nachdem der Unterricht geendet hatte, gingen die Schüler langsam durch den nassen Park "
    "nach Hause und sprachen über die Prüfung.",
    "Weil die Straßenbahn wegen eines Unfalls ausfiel, mussten viele Fahrgäste auf den "
    "nächsten Bus warten und kamen zu spät.",
    "Obwohl der Wetterbericht Regen angekündigt hatte, entschieden wir uns für einen langen "
    "Spaziergang am Ufer des breiten Flusses, der durch die Stadt fließt.",
    "Die alte Bibliothek am Marktplatz öffnet erst am Nachmittag, weshalb die Studenten ihre "
    "Bücher zunächst in der Cafeteria lesen.",
    "Wenn du morgen früh kommst, bring bitte die Rechnung mit, damit wir sie gemeinsam mit "
    "dem Vermieter prüfen können.",
    "Der Mechaniker erklärte mir geduldig, dass der Motor schon seit Wochen zu wenig Öl "
    "bekommt und deshalb so laut klingt.",
)

CORPUS_LONG: Tuple[str, ...] = (
    "Als ich gestern Abend nach der Arbeit durch die dunklen Straßen der Altstadt ging, fiel "
    "mir ein kleines Geschäft auf, dessen Schaufenster noch hell erleuchtet war und in dem "
    "ein alter Mann Zeitungen sortierte, obwohl es schon fast Mitternacht war.",
    "Die Entscheidung, den alten Bahnhof nicht abzureißen, sondern in ein Museum für "
    "Industriegeschichte umzubauen, wurde nach langen Diskussionen im Stadtrat getroffen, "
    "weil viele Bürger die Erinnerung an die Eisenbahn bewahren wollten und weil das Gebäude "
    "unter Denkmalschutz steht.",
    "Obwohl die Ärztin ihm mehrfach erklärt hatte, dass er sich mehrere Wochen schonen müsse, "
    "ging er schon am nächsten Tag wieder ins Fitnessstudio, weil er den Wettkampf im Herbst "
    "unbedingt gewinnen wollte, auch wenn seine Freunde ihn davor warnten.",
    "Wenn du im Winter mit dem Fahrrad zur Arbeit fährst, solltest du nicht nur warme "
    "Handschuhe und eine Mütze tragen, sondern auch darauf achten, dass die Beleuchtung "
    "funktioniert, damit dich die Autofahrer rechtzeitig sehen können.",
    "Nachdem die Familie jahrelang in einer kleinen Wohnung im vierten Stock gelebt hatte, "
    "kaufte sie endlich ein Haus am Rand der Stadt, das zwar renovierungsbedürftig war, aber "
    "einen großen Garten mit alten Apfelbäumen besaß.",
    "Während die Kinder draußen im Schnee spielten und der Hund bellend um den Garten lief, "
    "saßen die Eltern in der warmen Küche, tranken Tee und besprachen ruhig, wie sie das "
    "kommende Jahr mit weniger Geld planen sollten.",
)

CORPUS: Dict[str, Tuple[str, ...]] = {"short": CORPUS_SHORT, "mid": CORPUS_MID, "long": CORPUS_LONG}
BUCKET_ORDER = ("short", "mid", "long")


# --------------------------------------------------------------------------- #
# 环境准备：必须在 import delector 之前完成
# --------------------------------------------------------------------------- #
def _env_rounds() -> int:
    """轮数：``BENCH_RANK_ROUNDS`` 优先，否则沿用 ``BENCH_P95_ROUNDS`` / 默认 7。"""
    raw = os.environ.get("BENCH_RANK_ROUNDS", "").strip()
    if not raw:
        raw = os.environ.get("BENCH_P95_ROUNDS", "").strip()
    return max(MIN_ROUNDS, int(raw)) if raw else DEFAULT_ROUNDS


def _bootstrap_env(tmpdir: str) -> None:
    """把三处库/缓存路径全部钉进 tmpdir。

    ``DELECTOR_DATA_DIR`` 必须一起设：``delector/core/database.py`` 在**导入期**用它算缓存
    目录并 ``makedirs``，只设两个库路径的话脚本仍会在仓库根建目录（违反隔离纪律）。
    """
    os.environ.update(
        {
            "DELECTOR_DATA_DIR": tmpdir,
            "DATABASE_PATH": os.path.join(tmpdir, "bench_delector.db"),
            "PROGRESS_DB_PATH": os.path.join(tmpdir, "bench_progress.db"),
        }
    )


def _corpus_items() -> List[Tuple[str, str]]:
    """语料展平成 ``[(档位, 句子), ...]``，档位顺序固定为 short → mid → long。"""
    return [(bucket, text) for bucket in BUCKET_ORDER for text in CORPUS[bucket]]


def _count_tokens(sentence: str, nlp: Any) -> int:
    """按**引擎自己的切分**数 token：有 spaCy 就用它；纯 Python 降级时与
    ``_analyze_syntax_tree_pure_python``（``syntax_tree.py:1482`` 的 ``sent_str.split()``）
    保持同一口径 —— 这样 ``per_token_us`` 的分母才是该路径真实看到的 token 数。
    """
    if nlp is not None:
        return len(nlp(sentence))
    return len(sentence.split())


# --------------------------------------------------------------------------- #
# 计时：主口径逐句调用、rank 整段归一到每句（[Instinct: Median-Not-Mean]）
# --------------------------------------------------------------------------- #
def _measure_analyze(
    analyze: AnalyzeFn, items: List[Tuple[str, str]], rounds: int
) -> Tuple[List[float], Dict[str, List[float]]]:
    """主口径：**单句调用** ``analyze_syntax_tree`` 各计一次时；返回全部样本与分档样本。

    逐句调用（一次调用 = 一句）与旧值的「/句」口径对齐；分档样本用于句长敏感度。
    """
    samples: List[float] = []
    bucket_samples: Dict[str, List[float]] = {bucket: [] for bucket in BUCKET_ORDER}
    for _ in range(rounds):
        for bucket, text in items:
            start = time.perf_counter()
            analyze(text)
            elapsed = (time.perf_counter() - start) * 1000.0
            samples.append(elapsed)
            bucket_samples[bucket].append(elapsed)
    return samples, bucket_samples


def _measure_rank(rank: RankFn, full_text: str, sentences: int, rounds: int) -> List[float]:
    """``rank_sentences`` 整段调用各计一次时，**除以句数**归一到每句返回样本。

    归一到每句才能与旧值的「/句」口径对齐；不归一的话整段耗时会随句数膨胀，无法与 42/2.1 比。
    """
    samples: List[float] = []
    for _ in range(rounds):
        start = time.perf_counter()
        rank(full_text)
        elapsed = (time.perf_counter() - start) * 1000.0
        samples.append(elapsed / sentences)
    return samples


def _nlp_path(nlp: Any, engine: str) -> Tuple[str, str]:
    """用**生产自己的判据**读出本次实际走的是 spaCy 还是纯 Python 降级路径。

    - ``analyze_syntax_tree`` 分支在 ``syntax_tree.get_spacy_nlp()``（``nlp`` 参数）；
    - ``processor.NLP_ENGINE`` 是生产记录的生效引擎（``bench_spacy_unit.py`` 同款判据）。

    两层都报 spaCy 才敢标 ``spacy``；否则标 ``pure``，由 detail 行暴露哪层降了级。
    """
    tree_path = "spacy" if nlp is not None else "pure"
    proc_path = "spacy" if engine == "spacy" else "pure"
    path = "spacy" if tree_path == "spacy" and proc_path == "spacy" else "pure"
    return path, f"syntax_tree={tree_path};processor={proc_path}"


# 降级标注里用短名（`de_core_news_md` → `md`），与工程师口头/文档口径一致（照抄 bench_spacy_unit）。
MODEL_LABEL_PREFIX = "de_core_news_"


def _short_model_name(name: str) -> str:
    """``de_core_news_md`` → ``md``：降级标注用的短名。"""
    if name.startswith(MODEL_LABEL_PREFIX):
        return name[len(MODEL_LABEL_PREFIX) :]
    return name


def _resolved_model_detail(nlp: Any, fallback_detail: str) -> str:
    """从**已加载**的 nlp 对象反解模型包名（如 ``de_core_news_sm``）；取不到则退回 detail。

    spaCy 的 ``nlp.meta`` 带 ``lang``（de）与 ``name``（core_news_sm）⇒ 拼回完整包名。
    模型惰性化（ADR-0018 §7.6 O0 杠杆）后，``processor.NLP_ENGINE_DETAIL`` 在解析前不含
    实际模型名；而本基准走 ``syntax_tree.get_spacy_nlp()``（不经 processor 的加载器）⇒
    ``model=`` 需改从被测对象自身取，否则会打成 ``unknown``（口径不可复核）。
    """
    meta = getattr(nlp, "meta", None)
    if not isinstance(meta, dict):
        return fallback_detail
    lang = str(meta.get("lang", ""))
    name = str(meta.get("name", ""))
    package = f"{lang}_{name}".strip("_")
    return package or fallback_detail


def _model_label(detail: str, engine: str, candidates: Tuple[str, ...]) -> str:
    """从 processor 的引擎信息反解**实际生效**的模型名（含降级标注）；照抄 bench_spacy_unit 口径。

    为什么需要这行（② 席位红线）
    ----------------------------
    `get_spacy_nlp()`（`syntax_tree.py`）**先试 ``de_core_news_md``、失败才退 ``sm``** ⇒
    脚本很可能本来就在 md 上测，而此前从不打印模型名 ⇒ verdict 里"md 口径未测"的前提
    **不可复核**。故必须如实打印本行，并让 verdict 的模型表述与之一致。

    ``engine`` 传的是本脚本的 ``nlp_path``（两层判据的合取）而非 ``processor.NLP_ENGINE``：
    被测的是 ``analyze_syntax_tree``（走 ``syntax_tree.get_spacy_nlp()``），只有 nlp_path 报
    spaCy 时该路径才真用 spaCy 模型 ⇒ 模型名必须与 nlp_path 一致，否则会出现
    ``nlp_path=pure`` 却 ``model=de_core_news_md`` 的自相矛盾。
    """
    if engine != "spacy":
        return "pure-python"
    name = "unknown"
    for cand in candidates:
        if cand in detail:
            name = cand
            break
    suffix = ""
    if candidates and name != candidates[0]:
        suffix += f" ({_short_model_name(candidates[0])} 不可用)"
    if "自动下载" in detail:
        suffix += " (自动下载)"
    return f"{name}{suffix}"


def _verdict(analyze_median_ms: float, rank_median_ms: float, nlp_path: str, model: str) -> str:
    """点名对照三个数（42ms / 2.1ms / 端到端≈10ms）的可判定结论（[Instinct: No-Silent-Conclusion]）。

    只报区间不给判定等于把活推回给读者；故这里必须落到「落在哪一侧 + 是否足以解释 20 倍」，
    并且明确写出三条口径差异（纯函数 vs 端到端 vs 完整管线）。**不足以定案就明说不足**。

    **模型口径必须与 ``model=`` 行一致**（② 席位红线）：``get_spacy_nlp()`` 先试 md、失败才
    退 sm ⇒ 本环境可能在 md 上测。若 ``model`` 实测为 md，就**不许**再说"md 未测是补差来源"；
    若是 sm，则保留该 hedge 但改写为"本环境实测为 sm（见 model= 行），md 口径未测"。
    """
    # 历史值全部用常量插值：改常量或删掉对照逻辑时，门禁必须跟着红。
    hard = f"{LEGACY_SYNTAX_HARD_MS:g}ms"
    audit = f"{LEGACY_AUDIT_MS:g}ms"
    e2e = f"{LEGACY_LONG_READ_E2E_MS:g}ms"
    geo = LEGACY_GEO_MID_MS
    head = (
        f"实测对象={MEASURED_TARGET}；主口径 analyze_syntax_tree 单句调用中位 "
        f"{analyze_median_ms:.2f}ms/句，rank_sentences 整段归一到每句中位 "
        f"{rank_median_ms:.2f}ms/句（nlp_path={nlp_path}, model={model}）"
    )
    legacy = (
        f"点名对照三个数：{hard}（原 syntax_hard.py:9 注释的历史值，2026-10-09 已从代码移除）、"
        f"{audit}（docs/reviews/2026-09-28-swarm-audit-master.md:36 审计值）、"
        f"以及 tools/bench_long_read.py 的端到端 ≈{e2e}/句（含端点开销的冷读）"
    )
    scope = (
        "口径必须分开：本基准是**纯函数**单价（不含 DB 读正文、不含端点装配/序列化），"
        f"与端到端 ≈{e2e}/句**不可直接相除**；bench_spacy_unit 测的是 process_german_text"
        "（完整管线，**另一个函数**），同样不可直接比较 —— 比值只能读作跨口径差，"
        "不能读作『某旧值偏乐观/悲观 N 倍』"
    )
    # 模型口径：据 model= 行**如实**表述（② 席位红线 —— 不许隐含"本环境不是 md"）。
    if model.startswith("de_core_news_md"):
        md_clause = (
            f"本环境实测为 **md**（model={model}，见 model= 行）⇒ 『md 口径未测』这条补差来源"
            f"**已被排除**，缺口不能再归因于词向量"
        )
    elif model.startswith("de_core_news_sm"):
        md_clause = (
            f"本环境实测为 **sm**（model={model}，见 model= 行），md（带词向量）口径**未测** ⇒ "
            f"缺口仍可能来自 md 与 sm 的模型差"
        )
    else:
        md_clause = (
            f"本环境为纯 Python 降级（model={model}，见 model= 行）⇒ 与 spaCy 口径的历史值"
            f"对照不成立，md/sm 差异无从谈起"
        )
    candidates = (
        f"20 倍差距的候选来源（并列，均非定案结论）："
        f"候选①：{hard} 是 md（带词向量，显著更贵）口径 —— {md_clause}；"
        f"候选②：{hard} 含冷启动摊薄（需独立句子数证据）；"
        f"候选③：{hard} 或 {audit} 测的是**别的语料 / 别的函数口径**（本脚本只测内嵌 18 句、"
        f"且只测 analyze_syntax_tree 单句调用；换语料或换函数即不可直接比）"
    )
    # 落在哪一侧：用对数中点判（20 倍是倍数差距，算术中点会误导），并**如实**给出两组倍数。
    mid = f"√({LEGACY_AUDIT_MS:g}×{LEGACY_SYNTAX_HARD_MS:g})≈{geo:.1f}ms"
    ratio_audit = analyze_median_ms / LEGACY_AUDIT_MS
    ratio_hard = analyze_median_ms / LEGACY_SYNTAX_HARD_MS
    if analyze_median_ms <= geo:
        side = (
            f"本测值 {analyze_median_ms:.2f}ms/句 落在历史值 {audit} 一侧"
            f"（对数中点 {mid}，按**倍数**而非算术中点判）"
        )
        explain = (
            f"本测值约为 {audit} 的 {ratio_audit:.1f} 倍、{hard} 的 {ratio_hard:.2f} 倍，"
            f"且与端到端 ≈{e2e}/句同一量级（端点开销占比不大，成本主体就在该路径自身）；"
            f"据此 {hard} 无法由**纯函数**口径解释，{audit} 方向更近但被低估约 {ratio_audit:.1f} 倍，"
            f"**不足以定案** 20 倍差距 —— 缺口归因见上方候选来源，需 md 环境 + 冷启动样本复跑才能定案"
        )
    else:
        side = (
            f"本测值 {analyze_median_ms:.2f}ms/句 落在历史值 {hard} 一侧"
            f"（对数中点 {mid}，按**倍数**而非算术中点判）"
        )
        explain = (
            f"本测值约为 {hard} 的 {ratio_hard:.2f} 倍、{audit} 的 {ratio_audit:.1f} 倍，"
            f"与端到端 ≈{e2e}/句同一量级；这与 {audit} 相去甚远、却逼近 {hard}，"
            f"说明 {audit} 偏乐观，但本基准是**纯函数**（无端点开销）、又只测单一路径，"
            f"**不足以定案** {hard} 的成因（缺口归因见上方候选来源）"
        )
    conc = f"{side}；是否足以解释 {hard} 与 {audit} 的 20 倍差距：{explain}"
    tail = ""
    if nlp_path != "spacy":
        tail = (
            "；降级路径边界：本环境 spaCy 不可用（get_spacy_nlp()/NLP_ENGINE 判据），"
            "以上是**纯 Python 降级**路径成本，与 spaCy 口径的历史值对照不成立 —— "
            "需在有模型的机器上复跑本脚本"
        )
    return f"{head}；{legacy}；{scope}；{candidates}；{conc}{tail}"


def main() -> int:
    rounds = _env_rounds()
    tmpdir = tempfile.mkdtemp(prefix="delector_bench_rank_")
    try:
        _bootstrap_env(tmpdir)
        # 延迟导入：必须在 _bootstrap_env 之后（database.py 在导入期就按 DATA_DIR 建目录）。
        from delector.nlp_engine import processor, syntax_tree
        from delector.services import syntax_score

        analyze: AnalyzeFn = syntax_tree.analyze_syntax_tree
        rank: RankFn = syntax_score.rank_sentences
        nlp = syntax_tree.get_spacy_nlp()
        nlp_path, nlp_path_detail = _nlp_path(nlp, str(processor.NLP_ENGINE))
        # 实际生效模型名：优先从**已加载**的 nlp.meta 反解（processor 的 NLP_ENGINE_DETAIL
        # 现已惰性，未触发 processor 加载时不含模型名），解析不出再退回该 detail；用 nlp_path 把关。
        model = _model_label(
            _resolved_model_detail(nlp, str(processor.NLP_ENGINE_DETAIL)),
            nlp_path,
            tuple(processor.SPACY_MODEL_CANDIDATES),
        )

        items = _corpus_items()
        sentences = len(items)
        full_text = " ".join(text for _, text in items)

        # token 数只算一次（引擎自己的切分）；它是 per_token_us 的分母与句长刻度。
        tokens = 0
        bucket_tokens: Dict[str, int] = {bucket: 0 for bucket in BUCKET_ORDER}
        for bucket, text in items:
            count = _count_tokens(text, nlp)
            tokens += count
            bucket_tokens[bucket] += count

        analyze_samples, bucket_samples = _measure_analyze(analyze, items, rounds)
        rank_samples = _measure_rank(rank, full_text, sentences, rounds)

        # 中位数与 p95 必须来自**同一批**样本：另跑一轮计时会把"尾部有多厚"混进两次抖动。
        analyze_median = median_ms(analyze_samples)
        analyze_p95 = p95_ms(analyze_samples)
        rank_median = median_ms(rank_samples)
        rank_p95 = p95_ms(rank_samples)
        bucket_ms = {bucket: median_ms(bucket_samples[bucket]) for bucket in BUCKET_ORDER}
        per_sentence_tokens = tokens / sentences if sentences else 0.0
        analyze_per_token_us = (
            analyze_median * 1000.0 / per_sentence_tokens if per_sentence_tokens > 0 else 0.0
        )
        rank_per_token_us = (
            rank_median * 1000.0 / per_sentence_tokens if per_sentence_tokens > 0 else 0.0
        )

        print("=== bench_rank_sentences ===")
        print(f"unit={UNIT_MAIN}")
        print(f"analyze_per_sentence_ms={analyze_median:.3f}")
        # p95 印 .6f（与 samples 同精度）：门禁靠样本重算核验同批样本，
        # 印 .3f 的舍入误差（≤5e-4）会超过重算容差、把"同批"误判成"不同批"。
        print(f"analyze_p95_ms={analyze_p95:.6f}")
        print(f"analyze_p95_n={len(analyze_samples)}")
        print(f"analyze_per_token_us={analyze_per_token_us:.3f}")
        print(f"rank_per_sentence_ms={rank_median:.3f}")
        print(f"rank_p95_ms={rank_p95:.6f}")
        print(f"rank_p95_n={len(rank_samples)}")
        # 两条 p95 聚合单元与样本量都不同 ⇒ 显式声明不可直接比较/相除（防相邻两行被相除）。
        # 首行刻意保留 `print(f"p95_note=` 连续前缀：门禁以 `print(f"<key>=` 钉源码；
        # 长文本用隐式拼接折行，避免 E501。
        print(f"p95_note=analyze_p95_ms 聚合单元=**单句调用**(n={len(analyze_samples)}=rounds×sentences)；"
              f"rank_p95_ms 聚合单元=**整段归一每句**(n={len(rank_samples)}=rounds)——"
              f"聚合单元与样本量都不同 ⇒ 二者**不可直接比较/相除**；结论只引中位数（两者归一单元一致）")
        print(f"rank_per_token_us={rank_per_token_us:.3f}")
        for bucket in BUCKET_ORDER:
            print(f"bucket_{bucket}_ms={bucket_ms[bucket]:.3f}")
        for bucket in BUCKET_ORDER:
            print(f"tokens_per_bucket_{bucket}={bucket_tokens[bucket]}")
        print(f"samples_analyze_ms={format_samples(analyze_samples)}")
        print(f"samples_rank_ms={format_samples(rank_samples)}")
        print(f"sentences={sentences}")
        print(f"tokens={tokens}")
        print(f"rounds={rounds}")
        print(f"nlp_path={nlp_path}")
        print(f"nlp_path_detail={nlp_path_detail}")
        print(f"model={model}")
        print(f"verdict={_verdict(analyze_median, rank_median, nlp_path, model)}")
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
