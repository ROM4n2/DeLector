# -*- coding: utf-8 -*-
"""spaCy 处理单价基准（ADR-0018 D1 / Task 2）：收口「42ms/句 vs 2.1ms/句」的 20 倍矛盾。

为什么需要这个脚本
------------------
仓库里有两个互相矛盾、且都**不可复跑**的 spaCy 单价：

- `delector/routes/syntax_hard.py:9`（模块 docstring 的性能纪律）**曾写的** ``spaCy ~42ms/句``
  —— **该数字已于 2026-10-09 从代码中移除**（不可复跑、且不参与任何参数决策：TTL 由陈旧性
  决定、缓存容量由内存上界定、聚合 key 由淘汰悬崖决定，均非由该数字推出 —— 依据：perf 席位
  裁定 + 用户采纳）；此处仅作**历史值**对照，其热路径（``:187``）走的同样是 ``rank_sentences``
- `docs/reviews/2026-09-28-swarm-audit-master.md:36`（perf-profiler 座 CONFIRMED）：
  ``每篇跑 spaCy rank_sentences（实测 ~2.1 ms/句）``

两边都没有脚本兜底 ⇒ 任何以它们为输入的容量/缓存决策都悬空。本脚本给出**唯一可
复跑值**，并把两个旧值各自可能的口径摆到台面上。

**但先看清口径**：两个旧值其实是**同一条路径**上的两个估值 ——
``rank_sentences``（``services/syntax_score.py:230-242``）→ ``analyze_syntax_tree``
（``nlp_engine/syntax_tree.py:1521``）只建 clause_tree + topology，不做
token/lemma/morph/CEFR 反查/可分动词回扫/统计；而本脚本实测的是
``process_german_text``（``nlp_engine/processor.py:436``，**完整管线**）。即本脚
本与两个旧值**都不是同一个函数** ⇒ 打印出来的比值一律是「跨函数差」，**不得**
读作「某个旧值偏乐观/悲观 N 倍」（红卡 1 的根因）。历史值 42ms 已从 ``syntax_hard.py:9``
注释移除（2026-10-09）；若要为该路径留一个可复跑值，必须先补测 ``rank_sentences`` 的单价
—— 本脚本**未覆盖**该路径（未完成项）。

核心假设与测量设计（**首次与稳态必须分开**）
--------------------------------------------
两个数字的口径很可能不是同一个东西：spaCy 的首次调用会 lazy-init 管道组件、
词表与向量表，而稳态吞吐不含这些一次性开销。故本脚本把时间切成**三段**，
每段单独计时、单独打印：

======  ==================================================  ==============================
段      测什么                                              含义
======  ==================================================  ==============================
加载    ``import delector.nlp_engine.processor``            仅含 ``import spacy`` 本身；
                                                           **不含**模型反序列化（模型已
                                                           惰性化，见 processor.py 惰性加载块）
预热    第一次 ``process_german_text`` 调用                  含**模型惰性加载（反序列化）**
                                                           + 组件 lazy init（首次调用）
稳态    ``rounds`` × 语料全量，逐句单独调用，取中位数          可复跑的"单价"
======  ==================================================  ==============================

``first_vs_steady_ratio = warmup_ms / bucket_short_ms`` 是判定两个旧值口径的
直接证据：比值接近 20 倍 ⇒ 42ms 是首次口径；接近 1 ⇒ 首次加载解释不了差距。

口径诚实说明（**勿说过头**）
----------------------------
- ``warmup_ms`` 只覆盖**第一次调用**（语料第一句，短档）。残余 lazy init 会漏进
  后续未计数的采样，故它是**首次开销的下界**，不是完整上界。
- ``per_sentence_ms`` 是**逐句单独调用**的中位耗时（一次调用 = 一句），与两个
  旧值的「/句」口径对齐；它不是"整篇一次性处理"的摊薄值（后者因批处理而更便宜）。
- ``per_token_us = per_sentence_ms / 平均每句 token 数``，两者同取自逐句口径；
  平均每句 token 数另打一行（``tokens_per_sentence``）以免口径含混。
- **跨口径警告（本脚本最重要的一条边界）**：``per_sentence_ms`` 与 42ms、2.1ms
  **分属不同函数**。42ms / 2.1ms 的被测对象是 ``rank_sentences`` →
  ``analyze_syntax_tree``（更轻量：只建 clause_tree + topology），本脚本的被测对象
  是 ``process_german_text``（完整管线：token + lemma + morph + CEFR 反查 + 可分
  动词回扫 + ``calculate_cefr_stats``）。故 verdict 里的 ``实测/2.1 = N×`` 只能
  读作「两个函数的固有成本差」，**不能**读作「2.1ms 偏乐观 N 倍」，也**不足以**
  支撑为 ``syntax_hard.py:9`` 该路径补一个可复跑值 —— 那需要先补测 ``rank_sentences`` 单价。
- **冷启动摊薄假说不可证伪（红卡 2）**：``cold_amortized_sentences_to_42ms`` 由
  ``(model_load + warmup + N×steady) / N = 42`` 反解得 N；对任意
  ``0 < steady < 42`` 该方程**恒有正解** ⇒ 本脚本永远算得出一个 N，**永远无法**
  证伪这个假说。N 还是自由参数（仓库里没有任何地方记载 42ms 是在多少句材料上测
  的），分子又含词库 import（换机器即变）。故该假说在结论里只作为**候选解释之一**
  与「md 口径」「整篇含 DB 写入口径」并列，且必须写明「需独立的句子数证据才能定案」。

隔离纪律（`[Instinct: Isolated-DB]`）
------------------------------------
``tempfile.mkdtemp()`` + ``DATABASE_PATH`` / ``PROGRESS_DB_PATH`` /
``DELECTOR_DATA_DIR`` 三个环境变量**在 import delector 之前**设好
（``database.py`` 在导入期就用 ``DATA_DIR`` 建目录），``finally`` 里
``shutil.rmtree`` 清理。**绝不打开仓库根的真实 ``delector.db``**。

模型可用性降级（`[Instinct: Model-Availability]`）
-------------------------------------------------
``processor.SPACY_MODEL_CANDIDATES`` 是 ``(md, sm)``：md 装不上时 processor 会
自动退到 sm，故 ``model=`` 一行在非首选模型生效时**如实标注**
``de_core_news_sm (md 不可用)``；spaCy/模型全不可用（Android、离线）时走纯
Python 降级路径，照样打印 ``engine=pure_python`` + ``model=pure-python`` 与该
路径的单价 —— **不静默跳过，也不硬失败**，因为降级路径本身的单价对 Android 面
是有意义的成本输入。

用法
----
::

    export PYTHONIOENCODING=utf-8
    python tools/bench_spacy_unit.py                  # 默认 7 轮中位数
    BENCH_SPACY_ROUNDS=5 python tools/bench_spacy_unit.py   # 门禁快档（下限 5）

输出契约（``tests/test_spacy_unit_cost.py`` 逐行断言，勿改格式）::

    model_load_ms=N.NN            # import processor（含 import spacy；**不含**模型反序列化）耗时
    warmup_ms=N.NN                # 第一次 process_german_text（含模型惰性加载 + 组件 lazy init）
    per_sentence_ms=N.NN          # 稳态：单次 process_german_text 的中位耗时
    per_token_us=N.NN             # 稳态：每 token 微秒
    model=<name>                  # de_core_news_md / de_core_news_sm / pure-python
    engine=<spacy|pure_python>    # 对应 processor.NLP_ENGINE
    sentences=N                   # 语料句数
    tokens=N                      # 语料 token 总数
    rounds=N                      # 稳态轮数（中位数）
    verdict=<点名对照 42ms 与 2.1ms 的可判定结论>

补充行（非门禁断言，但同属结论的输入）：``bucket_{short,mid,long}_ms``（三档各自
中位耗时）、``tokens_per_bucket_{short,mid,long}``（三档 token 数；门禁断言其
**单调递增** —— 这才真正钉住「三档句长」这个自变量）、``tokens_per_sentence``、
``first_vs_steady_ratio``、``cold_amortized_sentences_to_42ms``（按
``(model_load + warmup + N×steady) / N = 42`` 反解出的 N，**不是**
``(model_load+warmup)/N = 42`` —— 后者算出来是 35ms/句，与 42ms 不符，是本脚本
早先措辞写错的地方）。该 N 恒有正解 ⇒ 只能检验、不能定案。
"""

import math
import os
import shutil
import statistics
import sys
import tempfile
import time
from typing import Any, Dict, List, Tuple

# 允许从任意 CWD 直接 `python tools/bench_spacy_unit.py` 运行（同 tools/ 其余脚本约定）。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

MIN_ROUNDS = 5  # 取中位数而非均值；少于 5 轮噪声压不住（[Instinct: Median-Not-Mean]）
DEFAULT_ROUNDS = 7

# 两个待收口的历史值（改这里等于改对照对象；两者都**不再**是代码里的当前值）。
# 历史值：原 delector/routes/syntax_hard.py:9 注释里的数字（已于 2026-10-09 移除；
# 不可复跑、且不参与任何参数决策：TTL 由陈旧性决定、缓存容量由内存上界定、聚合 key
# 由淘汰悬崖决定，均非由该数字推出 —— 依据：perf 席位裁定 + 用户采纳）
LEGACY_SYNTAX_HARD_MS = 42.0
LEGACY_AUDIT_MS = 2.1  # docs/reviews/2026-09-28-swarm-audit-master.md:36

# 本脚本的被测对象（verdict 开头必须显式声明，否则读者会拿它去和另一个函数相除）。
MEASURED_TARGET = "process_german_text（完整管线）"
# 两个旧值的**被测口径**：它们都出自 rank_sentences → analyze_syntax_tree，
# 只建 clause_tree + topology，不做 token/lemma/morph/CEFR 反查/可分动词回扫/统计，
# 比 process_german_text 轻量 ⇒ 与本脚本的比值是「跨函数差」，不是「旧值偏差」。
LEGACY_AUDIT_SCOPE = "rank_sentences→analyze_syntax_tree（仅 clause_tree+topology，更轻量）"
# 对数中点 = sqrt(2.1 * 42) ≈ 9.39：用它而不是算术中点判定"落在哪一侧"，
# 因为 20 倍是**倍数**差距，算术中点（22ms）会把 9ms 这种量级误判到 42ms 一侧。
LEGACY_GEO_MID_MS = math.sqrt(LEGACY_SYNTAX_HARD_MS * LEGACY_AUDIT_MS)

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

# 降级标注里用短名（`de_core_news_md` → `md`），与工程师口头/文档口径一致。
MODEL_LABEL_PREFIX = "de_core_news_"


# --------------------------------------------------------------------------- #
# 环境准备：必须在 import delector 之前完成
# --------------------------------------------------------------------------- #
def _env_rounds() -> int:
    raw = os.environ.get("BENCH_SPACY_ROUNDS", "").strip()
    if not raw:
        return DEFAULT_ROUNDS
    return max(MIN_ROUNDS, int(raw))


def _bootstrap_env(tmpdir: str) -> Dict[str, str]:
    """把三处库/缓存路径全部钉进 tmpdir，返回写回 os.environ 的键值。

    ``DELECTOR_DATA_DIR`` 必须一起设：``delector/core/database.py`` 在**导入期**
    用它算缓存目录并 ``makedirs``，只设两个库路径的话脚本仍会在仓库根建目录
    （违反隔离纪律）。
    """
    env = {
        "DELECTOR_DATA_DIR": tmpdir,
        "DATABASE_PATH": os.path.join(tmpdir, "bench_delector.db"),
        "PROGRESS_DB_PATH": os.path.join(tmpdir, "bench_progress.db"),
    }
    os.environ.update(env)
    return env


def _corpus_items() -> List[Tuple[str, str]]:
    """语料展平成 ``[(档位, 句子), ...]``，档位顺序固定为 short → mid → long。"""
    return [(bucket, text) for bucket in BUCKET_ORDER for text in CORPUS[bucket]]


# --------------------------------------------------------------------------- #
# 计时与统计（[Instinct: Median-Not-Mean]）
# --------------------------------------------------------------------------- #
def _median(samples: List[float]) -> float:
    """中位数。刻意不用均值：单轮会被 GC / 页面缓存污染成尖峰，均值把尖峰摊进
    结果里，而中位数对单侧尖峰不敏感。"""
    if not samples:
        return 0.0
    return float(statistics.median(samples))


def _count_tokens(result: Dict[str, Any]) -> int:
    """统计一次 ``process_german_text`` 结果里的 token 总数（用引擎自己的切分）。"""
    total = 0
    sents = result.get("sentences")
    if not isinstance(sents, list):
        return 0
    for sent in sents:
        if not isinstance(sent, dict):
            continue
        toks = sent.get("tokens")
        if isinstance(toks, list):
            total += len(toks)
    return total


def _short_model_name(name: str) -> str:
    """``de_core_news_md`` → ``md``：降级标注用的短名。"""
    if name.startswith(MODEL_LABEL_PREFIX):
        return name[len(MODEL_LABEL_PREFIX) :]
    return name


def _model_label(detail: str, engine: str, candidates: Tuple[str, ...]) -> str:
    """从 ``processor.NLP_ENGINE_DETAIL`` 反解实际生效的模型名（含降级标注）。

    processor 按 ``SPACY_MODEL_CANDIDATES`` 顺序取第一个能加载的，故实际名 ≠ 首选
    名就意味着首选名不可用 —— 这正是 ``(md 不可用)`` 标注的来源（不是猜的，是
    processor 自己试过并失败后的结果）。
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


def _verdict(
    engine: str,
    model: str,
    per_sentence_ms: float,
    warmup_ms: float,
    model_load_ms: float,
    short_ms: float,
    long_ms: float,
    md_missing: bool,
) -> str:
    """点名对照 42ms 与 2.1ms 的可判定结论（[Instinct: No-Silent-Conclusion]）。

    只报区间不给判定等于把活推回给读者；故这里必须落到「落在哪一侧 + 为什么」，
    并且把两个旧值都写进文本里（门禁逐字断言）。

    **两条纪律（本函数被红卡的根因，改文案时务必一起守）**：

    1. **先声明被测对象**：本脚本测的是 ``process_german_text``（完整管线），而
       42ms / 2.1ms 的被测对象是 ``rank_sentences`` → ``analyze_syntax_tree``
       （更轻量）。函数不同 ⇒ 比值只能是「跨函数差」，绝不能写成「某旧值偏乐观
       /悲观 N 倍」；改注释所需的 ``rank_sentences`` 单价本脚本**未测**，必须以
       「未完成项」明写，不能让下游误以为已经可以改数。
    2. **假说只能当候选**：冷启动摊薄里 N 是自由参数、方程恒有正解 ⇒ 本脚本无法
       证伪它。故它与「md 口径」「整篇含 DB 写入口径」**并列**，全都不作断言。
    """
    head = (
        f"实测对象={MEASURED_TARGET}；稳态实测 {per_sentence_ms:.2f}ms/句"
        f"（engine={engine}, model={model}）"
    )
    # 历史值全部用常量插值：把常量改掉（或删掉对照逻辑只留文案）时，门禁必须跟着红。
    audit = f"{LEGACY_AUDIT_MS:g}ms"
    hard = f"{LEGACY_SYNTAX_HARD_MS:g}ms"
    audit_n = f"{LEGACY_AUDIT_MS:g}"
    hard_n = f"{LEGACY_SYNTAX_HARD_MS:g}"
    if per_sentence_ms <= LEGACY_GEO_MID_MS:
        side = (
            f"与历史值 {audit} 不可直接相除（其口径为 {LEGACY_AUDIT_SCOPE}）："
            f"实测/{audit_n} = {per_sentence_ms / LEGACY_AUDIT_MS:.2f}× 属跨函数差，"
            f"不能读作『{audit} 偏乐观』；{hard_n}/实测 = {LEGACY_SYNTAX_HARD_MS / per_sentence_ms:.2f}×"
            f"（历史值 {hard} 热路径同为 rank_sentences、且已从代码移除，同样是跨函数差）"
        )
    else:
        side = (
            f"与历史值 {hard} 不可直接相除（其热路径同为 rank_sentences、且已从代码移除）："
            f"{hard_n}/实测 = {LEGACY_SYNTAX_HARD_MS / per_sentence_ms:.2f}× 属跨函数差，"
            f"不能读作『{hard} 偏悲观』；实测/{audit_n} = {per_sentence_ms / LEGACY_AUDIT_MS:.2f}×"
            f"（{audit} 口径为 {LEGACY_AUDIT_SCOPE}）"
        )
    ratio = warmup_ms / short_ms if short_ms > 0 else 0.0
    mech = (
        f"首次口径证据：model_load_ms={model_load_ms:.2f}（import processor；模型现为**惰性加载**，"
        f"其反序列化已并入下面的 warmup_ms）+ warmup_ms={warmup_ms:.2f}"
        f"（首次调用含模型惰性加载 + 组件 lazy init），首次/稳态 = {ratio:.1f}×"
    )
    length = (
        f"句长敏感度：短句档 {short_ms:.2f}ms → 长句档 {long_ms:.2f}ms"
        f"（长/短 = {long_ms / short_ms:.1f}×）" if short_ms > 0 else "句长敏感度：无有效样本"
    )
    # 冷启动摊薄：**候选解释之一**，不是结论。公式 B 的完整表述必须写出来
    # （早先措辞写的是公式 A 的语义「1485ms 摊到 42 句上每句 42ms」，但按 A 算
    # 只有 35.4ms/句，与代码不符 ⇒ 措辞与算式脱节，红卡 2）。
    cold_ms = model_load_ms + warmup_ms
    if 0.0 < per_sentence_ms < LEGACY_SYNTAX_HARD_MS:
        n42 = cold_ms / (LEGACY_SYNTAX_HARD_MS - per_sentence_ms)
        amort = (
            f"冷启动摊薄（候选②，非结论）：按 (model_load+warmup+N×steady)/N = {hard_n} => "
            f"N≈{n42:.0f}（cold={cold_ms:.0f}ms，steady={per_sentence_ms:.2f}ms）；"
            f"N 为自由参数，任何 0<steady<{hard_n} 恒有正解 => 本脚本无法证伪该假说；"
            f"分子含词库 import，换机器即变；需独立的『{hard} 是在约 {n42:.0f} 句材料上测得』"
            f"证据才能定案（即便 N 与 {hard_n} 数值接近，也只是单位巧合，不构成证据）"
        )
    else:
        amort = f"冷启动摊薄（候选②）不适用：稳态单价已达 {hard_n} 量级，摊薄项可忽略"

    if ratio >= 5.0:
        evidence = (
            f"首次/稳态 = {ratio:.1f}×，量级上支持候选②（含冷启动摊薄），但不足以定案"
            f"（见候选②的不可证伪说明）"
        )
    elif ratio >= 2.0:
        evidence = (
            f"首次开销高于稳态但仅 {ratio:.1f}×，撑不满 20 倍：候选②至多解释其中一部分，"
            f"剩余差距要由候选①/③补"
        )
    else:
        evidence = (
            f"首次与稳态几乎同量级（{ratio:.1f}×）：**实测到的**首次开销撑不起 20 倍差距，"
            f"候选①/③更可疑；这不构成对候选②的排除（N 是自由参数、方程恒有正解，"
            f"与「实测首次开销不够大」是两件事），也不构成对它的支持 —— 缺独立句子数证据"
        )
    # 三个候选一律并列、一律不作断言：本脚本只测了其中一种口径，没有裁定权。
    candidates = (
        "历史值 20 倍差距的候选口径（并列，均非定案结论）："
        f"候选①：{hard} 是 md（带词向量，显著更贵）口径；"
        f"候选②：{hard} 含冷启动摊薄（见上，需独立句子数证据）；"
        f"候选③：{hard} 是整篇一次性处理 + DB 写入口径（本脚本测的是逐句单独调用）"
    )
    # 未完成项：本脚本没测 rank_sentences，故不足以给出该路径的可复跑单价。
    pending = (
        f"未完成项：本脚本测的是 {MEASURED_TARGET}，未覆盖 rank_sentences/analyze_syntax_tree "
        f"路径 —— 历史值 {hard} 已从 syntax_hard.py:9 注释移除，若要为该路径补一个可复跑值，"
        f"必须先补测该单价；现有数字不足以支撑定案"
    )

    tail = ""
    if engine != "spacy":
        tail += (
            "；降级路径边界：本环境 spaCy/模型不可用，以上单价是**纯 Python 降级路径**成本"
            "（Android 无模型面），不能替 spaCy 定性 —— 仍需在有模型的机器上复跑本脚本"
        )
    if md_missing:
        tail += f"；候选①的口径边界：本机未装 md => 本次无法排除 {hard} 是 md（带词向量，显著更贵）的口径"
    return f"{head}：{side}；{mech}；{evidence}；{candidates}；{amort}；{length}；{pending}{tail}"


def main() -> int:
    rounds = _env_rounds()
    tmpdir = tempfile.mkdtemp(prefix="delector_bench_spacy_")
    try:
        _bootstrap_env(tmpdir)
        # 延迟导入：必须在 _bootstrap_env 之后。processor 已改**惰性加载** —— import 期只做廉价
        # 判定（含 import spacy），**不再** spacy.load；模型反序列化推迟到首次调用（见下方预热段）。
        # 故这段量的是「import processor」本身，**不含**模型加载。
        t0 = time.perf_counter()
        from delector.nlp_engine import processor

        model_load_ms = (time.perf_counter() - t0) * 1000.0

        process = processor.process_german_text

        items = _corpus_items()

        # 预热段：全流程第一次调用（含 spaCy **模型惰性加载** + 组件 lazy init）。刻意只计
        # 这一次，与后面的稳态采样彻底分开 —— 42ms vs 2.1ms 的嫌疑就在这条缝上。模型加载已从
        # import 期搬到这次首次调用（ADR-0018 §7.6），故 warmup_ms 现在含模型反序列化。
        t1 = time.perf_counter()
        process(items[0][1])
        warmup_ms = (time.perf_counter() - t1) * 1000.0

        # 引擎 / 模型名必须在**首次调用（解析）之后**再读：模型惰性化后，导入期的
        # NLP_ENGINE_DETAIL 只说「将惰性加载」，不含实际生效的模型名。
        engine = str(processor.NLP_ENGINE)
        detail = str(processor.NLP_ENGINE_DETAIL)
        model = _model_label(detail, engine, tuple(processor.SPACY_MODEL_CANDIDATES))

        # 稳态段：逐句单独调用（一次调用 = 一句，与两个旧值的「/句」口径对齐）。
        samples: List[float] = []
        bucket_samples: Dict[str, List[float]] = {b: [] for b in BUCKET_ORDER}
        # 分档 token 数与分档耗时成对打印：耗时差只有在「token 数确实分档」时
        # 才是句长效应，否则可能只是噪声。门禁断言两者都单调。
        bucket_tokens: Dict[str, int] = {b: 0 for b in BUCKET_ORDER}
        tokens = 0
        for r in range(rounds):
            for bucket, text in items:
                t2 = time.perf_counter()
                result = process(text)
                dt = (time.perf_counter() - t2) * 1000.0
                samples.append(dt)
                bucket_samples[bucket].append(dt)
                if r == 0:
                    n = _count_tokens(result)
                    tokens += n
                    bucket_tokens[bucket] += n

        sentences = len(items)
        per_sentence_ms = _median(samples)
        short_ms = _median(bucket_samples["short"])
        mid_ms = _median(bucket_samples["mid"])
        long_ms = _median(bucket_samples["long"])
        tokens_per_sentence = tokens / sentences if sentences else 0.0
        per_token_us = per_sentence_ms * 1000.0 / tokens_per_sentence if tokens_per_sentence > 0 else 0.0
        ratio_first_steady = warmup_ms / short_ms if short_ms > 0 else 0.0
        # 冷启动摊薄（公式 B）：(model_load + warmup + N×steady) / N = 42 反解 N。
        # 注意 N 是自由参数、方程恒有正解 ⇒ 这行只能检验、不能定案（见 docstring）。
        amortized_n = (
            (model_load_ms + warmup_ms) / (LEGACY_SYNTAX_HARD_MS - per_sentence_ms)
            if 0.0 < per_sentence_ms < LEGACY_SYNTAX_HARD_MS
            else 0.0
        )
        md_missing = "不可用" in model

        print("=== bench_spacy_unit ===")
        print(f"engine_detail={detail}")
        print(f"model_load_ms={model_load_ms:.2f}")
        print(f"warmup_ms={warmup_ms:.3f}")
        print(f"per_sentence_ms={per_sentence_ms:.3f}")
        print(f"per_token_us={per_token_us:.2f}")
        print(f"model={model}")
        print(f"engine={engine}")
        print(f"sentences={sentences}")
        print(f"tokens={tokens}")
        print(f"tokens_per_sentence={tokens_per_sentence:.1f}")
        print(f"rounds={rounds}")
        print(f"bucket_short_ms={short_ms:.3f}")
        print(f"bucket_mid_ms={mid_ms:.3f}")
        print(f"bucket_long_ms={long_ms:.3f}")
        for bucket in BUCKET_ORDER:
            print(f"tokens_per_bucket_{bucket}={bucket_tokens[bucket]}")
        print(f"first_vs_steady_ratio={ratio_first_steady:.1f}x")
        print(f"cold_amortized_sentences_to_42ms={amortized_n:.0f}")
        verdict = _verdict(
            engine, model, per_sentence_ms, warmup_ms, model_load_ms, short_ms, long_ms, md_missing
        )
        print(f"verdict={verdict}")
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
