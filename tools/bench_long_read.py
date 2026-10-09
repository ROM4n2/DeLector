# -*- coding: utf-8 -*-
"""长文精读端到端基准：比较同一材料的 `_RANK_CACHE` 冷读与热读。

冷读/热读各取至少五轮中位数。每轮先直接清空 `_RANK_CACHE`（生产函数
`invalidate_rank_cache()` 只失效聚合键，不能清掉单材料键），再计时一次
`api_syntax_hard_sentences` 冷读；冷读建立该轮全新的缓存生命周期后，紧接着计时
同材料热读。下一轮再次清空，因此没有两个热读样本复用同一缓存生命周期。

`spacy_ms` 是独立地对材料全部句子逐句调用 `process_german_text` 的一轮累计耗时，
再对多轮取中位数；它是完整 NLP 管线口径，而冷读中的热路径是 `rank_sentences` →
`analyze_syntax_tree`，两者不可直接比较。`other_ms = cold_ms - spacy_ms` 仅是跨口径
近似差值，允许为负；`spacy_pct = spacy_ms / cold_ms` 也只作成本量级参考。

`nlp_path` 是本基准的可信前提：spaCy 加载失败是**静默降级**（processor.py:437 与
syntax_tree.py:1533 双双退回纯 Python），此时 `spacy_ms` 量到的是纯 Python 成本，
与历史值 42ms/句（原 `syntax_hard.py:9` 注释，2026-10-09 移除）的对照不成立。故本脚本用**生产自己的
判据**读实际路径（`syntax_tree.get_spacy_nlp()` 与 `processor.NLP_ENGINE`，
也就是 syntax_hard.py:225 `/spacy-status` 对外报的那套），不在基准里另发明一套；
只有两层都报 spaCy 才标 `nlp_path=spacy`，分歧靠 `nlp_path_detail` 行暴露。

Task 5b 起冷读/热读同时输出 **p95**（`cold_p95_ms` / `warm_p95_ms`）与原始样本行
（`samples_cold_ms` / `samples_warm_ms`）：ADR-0018 §6 的判定门条件②按 **p95 > 2 倍
目标** 判，不是按中位数。p95 与中位数取自**同一批**样本（不重新计时），口径见
`tools/bench_stats.py`：n=5 时该分位 ≈ 最大值且**系统性低估尾部**，故样本不足时不许
拿它下强结论。

`cache_speedup` 的分母是微秒级 dict 命中（抖动 ±10%），只报 2 位有效数字，只作
数量级参考，不解读为算法加速倍数。`cache_items_identical` 逐轮比对冷读与热读返回
的 items：只证"热读更快"不够，热读还必须返回同一份结果，否则是缓存正确性问题。

隔离纪律：脚本先用 `mkdtemp` 设置三个数据环境变量，再动态导入 delector，最后在
`finally` 中删除临时目录。材料直接 INSERT 到 articles，造数阶段绝不调用 NLP。
"""

import importlib
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from types import ModuleType
from typing import Any, Callable, Dict, List, Optional, Tuple, cast

# bench_stats 与本脚本同处 tools/：以脚本方式运行（`python tools/xxx.py`）时 Python 已把
# tools/ 放进 sys.path[0]，故可直接顶层导入（放在这里也顺带避开 E402）。p95 口径与它的
# 已知偏差方向见 tools/bench_stats.py —— 三个基准必须共用同一份实现，不许各写一份。
from bench_stats import format_samples, median_ms, p95_ms

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLS_DIR = os.path.join(_REPO_ROOT, "tools")
# tools/ 也要进 sys.path：本脚本与其余基准共用 tools/bench_stats.py 的 p95 口径，
# 而 tools/ 不是包（无 __init__.py），只能靠目录进路径做顶层 import。
for _path in (_REPO_ROOT, _TOOLS_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

MIN_ROUNDS = 5
DEFAULT_ROUNDS = 7
# 历史值：原 delector/routes/syntax_hard.py:9 注释里的数字（已于 2026-10-09 移除；不可复跑、
# 且不参与任何参数决策：TTL 由陈旧性决定、缓存容量由内存上界定、聚合 key 由淘汰悬崖决定，
# 均非由该数字推出 —— 依据：perf 席位裁定 + 用户采纳）
LEGACY_SYNTAX_HARD_MS = 42.0
# 输出旁的一句 caveat：cache_speedup 的分母是微秒级命中，other_ms/spacy_pct 是跨口径近似。
# 写在输出里而不是只写在 docstring 里，是因为读数字的人（含后续回填 ADR）只看 stdout。
APPROX_NOTE = (
    "cache_speedup 分母 warm_ms 是微秒级 dict 命中（抖动 ±10%），只作数量级参考，"
    "不解读为算法加速倍数；other_ms/spacy_pct 为跨口径近似，仅量级参考"
)

LONG_ARTICLE_SENTENCES: Tuple[str, ...] = (
    "Als die Stadtverwaltung im vergangenen Frühjahr ankündigte, dass der alte Güterbahnhof "
    "in ein neues Kulturzentrum umgebaut werden solle, reagierten viele Bewohner zunächst "
    "skeptisch, weil frühere Großprojekte häufig teurer geworden waren als geplant.",
    "Der Bahnhof, dessen Backsteinhallen seit fast dreißig Jahren leer stehen, erinnert an die "
    "Zeit, in der täglich schwere Züge Kohle, Maschinen und landwirtschaftliche Erzeugnisse "
    "aus der gesamten Region in die wachsende Industriestadt brachten.",
    "Obwohl einige Hallen inzwischen beschädigte Dächer haben und Feuchtigkeit in das Mauerwerk "
    "eingedrungen ist, halten Fachleute eine behutsame Sanierung technisch für möglich, sofern "
    "die tragenden Stahlkonstruktionen gründlich geprüft und verstärkt werden.",
    "Nach dem aktuellen Entwurf sollen im Erdgeschoss Werkstätten für Künstler, kleine Bühnen "
    "und öffentlich zugängliche Proberäume entstehen, während die oberen Etagen günstige Büros "
    "für Vereine und junge Unternehmen aufnehmen könnten.",
    "Besonders umstritten ist jedoch der geplante Veranstaltungssaal, der zweitausend Besucher "
    "fassen würde, denn die Anwohner befürchten nicht nur nächtlichen Lärm, sondern auch lange "
    "Staus in den schmalen Straßen des benachbarten Wohnviertels.",
    "Die Projektleitung verspricht deshalb ein Verkehrskonzept, bei dem Eintrittskarten zugleich "
    "als Fahrkarten gelten, zusätzliche Straßenbahnen eingesetzt werden und nur wenige neue "
    "Parkplätze unmittelbar neben dem denkmalgeschützten Gebäude entstehen.",
    "Eine Bürgerinitiative fordert darüber hinaus, dass der breite Platz vor dem Bahnhof nicht "
    "vollständig gepflastert wird, sondern große Bäume, entsiegelte Flächen und einen Spielplatz "
    "erhält, damit das Gelände auch an gewöhnlichen Tagen genutzt werden kann.",
    "Finanziert werden soll der Umbau durch Mittel der Stadt, ein europäisches Förderprogramm "
    "und private Spenden, wobei der Gemeinderat jeder größeren Kostensteigerung erneut zustimmen "
    "müsste, bevor weitere Aufträge an Baufirmen vergeben werden dürfen.",
    "Kritiker weisen darauf hin, dass die bislang veranschlagten achtzig Millionen Euro weder "
    "unerwartete Altlasten im Boden noch stark steigende Materialpreise ausreichend berücksichtigen "
    "und deshalb wahrscheinlich nicht bis zur Eröffnung reichen werden.",
    "Befürworter entgegnen, die Stadt müsse langfristig denken, weil ein lebendiges Kulturzentrum "
    "neue Gäste anziehen, Arbeitsplätze schaffen und zugleich verhindern könne, dass ein wichtiges "
    "Zeugnis der örtlichen Geschichte endgültig verfällt.",
    "Bevor die Bauarbeiten beginnen, wird ein unabhängiges Büro sämtliche Einwände auswerten und "
    "in mehreren öffentlichen Sitzungen erläutern, welche Vorschläge übernommen wurden und aus "
    "welchen rechtlichen oder finanziellen Gründen andere Wünsche unberücksichtigt bleiben.",
    "Wenn der endgültige Beschluss im Herbst fällt und keine weiteren Klagen eingereicht werden, "
    "könnte die Sanierung Anfang des nächsten Jahres starten, doch selbst nach optimistischer "
    "Schätzung wäre das Kulturzentrum frühestens vier Jahre später vollständig geöffnet.",
)
LONG_ARTICLE_TEXT = " ".join(LONG_ARTICLE_SENTENCES)

ProcessFn = Callable[[str], Dict[str, Any]]
RankFn = Callable[[str, Optional[int], Optional[str], Optional[float], int], Dict[str, Any]]


def _env_rounds() -> int:
    """轮数：`BENCH_P95_ROUNDS` 优先，否则沿用 `BENCH_LONG_READ_ROUNDS` / 默认 7。

    p95 对样本量远比中位数敏感（n=5 的经验 p95≈最大值、系统性低估尾部），故"提精度"
    单独给一个开关，避免它顺带改写人工档既有的轮数口径。
    """
    raw_p95 = os.environ.get("BENCH_P95_ROUNDS", "").strip()
    if raw_p95:
        return max(MIN_ROUNDS, int(raw_p95))
    raw = os.environ.get("BENCH_LONG_READ_ROUNDS", "").strip()
    return max(MIN_ROUNDS, int(raw)) if raw else DEFAULT_ROUNDS


def _bootstrap_env(tmpdir: str) -> None:
    os.environ.update(
        {
            "DELECTOR_DATA_DIR": tmpdir,
            "DATABASE_PATH": os.path.join(tmpdir, "bench_delector.db"),
            "PROGRESS_DB_PATH": os.path.join(tmpdir, "bench_progress.db"),
        }
    )


def _median_ms(samples: List[float]) -> float:
    return median_ms(samples)


def _seed_article(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "INSERT INTO articles (title, source_url, raw_text, processed_json) VALUES (?, ?, ?, ?)",
            ("Der alte Güterbahnhof", "bench://long-read", LONG_ARTICLE_TEXT, "{}"),
        )
        conn.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("文章造数未返回 id")
        return int(cursor.lastrowid)
    finally:
        conn.close()


def _items_of(result: Dict[str, Any]) -> object:
    """取 `api_syntax_hard_sentences` 返回的 items；缺失/类型不符返回 None（参与相等比较即判否）。"""
    items = result.get("items")
    return items if isinstance(items, list) else None


def _read_samples(
    rank: RankFn, clear_cache: Callable[[], None], article_id: int, rounds: int
) -> Tuple[List[float], List[float], bool]:
    """冷/热读各采 rounds 轮**原始样本**返回；同时逐轮比对两者返回的 items 是否一致。

    为什么返回样本而不是中位数：Task 5b 要求 p95，而 p95 必须与中位数取自**同一批**
    样本（另跑一轮计时的话，两者之差就混进了两次测量的抖动）。故这里只采样，统计量
    由调用方从同一批样本里同时折叠出中位数与 p95。

    为什么每轮都比：只证明"热读更快"不足以说明缓存是对的——热读若返回了另一份
    （或空）结果，那比慢更严重。故把"同样快"与"同样对"一起测，任一轮不等即判否。
    """
    cold_samples: List[float] = []
    warm_samples: List[float] = []
    items_identical = True
    for _ in range(rounds):
        clear_cache()
        cold_start = time.perf_counter()
        cold_result = rank("article", article_id, None, None, 100)
        cold_samples.append((time.perf_counter() - cold_start) * 1000.0)
        warm_start = time.perf_counter()
        warm_result = rank("article", article_id, None, None, 100)
        warm_samples.append((time.perf_counter() - warm_start) * 1000.0)
        if _items_of(cold_result) != _items_of(warm_result):
            items_identical = False
    return cold_samples, warm_samples, items_identical


def _count_tokens(result: Dict[str, Any]) -> int:
    batch = result.get("sentences")
    if not isinstance(batch, list):
        return 0
    return sum(
        len(tokens)
        for sentence in batch
        if isinstance(sentence, dict)
        for tokens in [sentence.get("tokens")]
        if isinstance(tokens, list)
    )


def _spacy_samples(process: ProcessFn, sentences: List[str], rounds: int) -> Tuple[float, int]:
    samples: List[float] = []
    tokens = 0
    for round_index in range(rounds):
        results: List[Dict[str, Any]] = []
        start = time.perf_counter()
        for sentence in sentences:
            results.append(process(sentence))
        samples.append((time.perf_counter() - start) * 1000.0)
        if round_index == 0:
            tokens = sum(_count_tokens(result) for result in results)
    return _median_ms(samples), tokens


def _cache_effect(cold_ms: float, warm_ms: float) -> str:
    if warm_ms < cold_ms * 0.9:
        return "yes"
    if warm_ms >= cold_ms:
        return "no"
    return "unknown"


def _nlp_path(syntax_tree: ModuleType, processor: ModuleType) -> Tuple[str, str]:
    """用**生产自己的判据**读出本次实际走的是 spaCy 还是纯 Python 降级路径。

    - `analyze_syntax_tree`（冷读热路径）分支在 `syntax_tree.get_spacy_nlp()`
      （syntax_tree.py:1532-1534），生产 route syntax_hard.py:225 的 `/spacy-status`
      用的就是同一个判据；
    - `process_german_text`（spacy_ms 口径）分支在 processor 模块级 `nlp`
      （processor.py:437），生产把实际生效的引擎记在 `NLP_ENGINE` / `NLP_ENGINE_DETAIL`。

    为什么不在基准里重新 `import spacy` 判一次：那会与生产加载模型的候选顺序、
    自动下载、Android 判定分叉，测出来的"路径"可能不是生产的路径。两层都报 spaCy
    才敢标 `spacy`；否则标 `pure`，并由 detail 行暴露到底哪层降了级。
    """
    tree_path = "spacy" if syntax_tree.get_spacy_nlp() else "pure"
    proc_path = "spacy" if processor.NLP_ENGINE == "spacy" else "pure"
    path = "spacy" if tree_path == "spacy" and proc_path == "spacy" else "pure"
    # 生产记的 detail 可能带异常文本（含换行），压成单行，保证输出仍是 key=value 逐行可解析
    detail = " ".join(str(processor.NLP_ENGINE_DETAIL).split())
    return path, f"syntax_tree={tree_path};processor={proc_path}({detail})"


def _format_speedup(value: float) -> str:
    """只报 2 位有效数字：分母 warm_ms 是微秒级 dict 命中（抖动 ±10%），多打印一位就是伪精度。

    个位区（<10）例外保留两位小数：那已经落在"缓存无效"区间，两位有效数字会把
    1.05 打成 1，反而丢掉"到底有没有快一点"这个判定所需的信息。
    """
    if value >= 10.0:
        return f"{value:.2g}"
    return f"{value:.2f}"


def _verdict(effect: str, cold_ms: float, warm_ms: float, sentences: int, nlp_path: str) -> str:
    if effect == "yes":
        cache_text = f"缓存生效，热读比冷读快 {_format_speedup(cold_ms / warm_ms)} 倍（仅数量级）"
    elif effect == "no":
        cache_text = "缓存未生效，热读没有快于冷读"
    else:
        cache_text = "缓存效果不明确，热读虽更快但改善不足 10%"
    per_sentence = cold_ms / sentences
    if nlp_path == "spacy":
        path_text = "nlp_path=spacy：本环境 spaCy 实际加载成功，spacy_ms 走 spaCy 路径"
    else:
        path_text = (
            "nlp_path=pure：本环境 spaCy 不可用，process_german_text 与 analyze_syntax_tree "
            "双双走纯 Python 降级路径，spacy_ms 量到的是纯 Python 成本，与历史值 42ms/句的对照不成立"
            "（哪一层降级见 nlp_path_detail 行）"
        )
    return (
        f"{cache_text}；{path_text}；对照历史值 spaCy ~{LEGACY_SYNTAX_HARD_MS:g}ms/句"
        "（原 syntax_hard.py:9 注释，2026-10-09 移除）："
        f"本次冷缓存端到端为 {per_sentence:.2f}ms/句，但其热路径是 rank_sentences，"
        "spacy_ms 测的是 process_german_text 完整管线，二者跨函数不可直接比较；"
        "因此本次只能判定缓存收益，不能支持或否证该历史值 42ms/句（已从代码移除）。"
    )


def main() -> int:
    rounds = _env_rounds()
    tmpdir = tempfile.mkdtemp(prefix="delector_bench_long_read_")
    try:
        _bootstrap_env(tmpdir)
        database = importlib.import_module("delector.core.database")
        syntax_hard = importlib.import_module("delector.routes.syntax_hard")
        syntax_tree = importlib.import_module("delector.nlp_engine.syntax_tree")
        processor = importlib.import_module("delector.nlp_engine.processor")
        init_db = cast(Callable[[str], None], database.init_db)
        rank = cast(RankFn, syntax_hard.api_syntax_hard_sentences)
        rank_cache = cast(Dict[str, object], syntax_hard._RANK_CACHE)
        clear_cache = rank_cache.clear
        # 用生产自己的读入口自检：清空后该材料键必须 miss，"冷读"才真的冷
        # （顺带钉住 key 形状 f"{source}:{source_id}" 与生产一致）。
        get_rank_cache = cast(Callable[[str], Optional[object]], syntax_hard._get_rank_cache)
        split = cast(Callable[[str], List[str]], syntax_tree.split_sentences_pure_python)
        process = cast(ProcessFn, processor.process_german_text)
        db_path = os.environ["DATABASE_PATH"]
        init_db(db_path)
        article_id = _seed_article(db_path)
        clear_cache()
        cleared = get_rank_cache(f"article:{article_id}") is None
        sentences = split(LONG_ARTICLE_TEXT)
        cold_samples, warm_samples, items_identical = _read_samples(rank, clear_cache, article_id, rounds)
        # 中位数与 p95 必须来自**同一批**样本：见 bench_stats 的口径说明（n 小时 p95 系统性低估尾部）。
        cold_ms = _median_ms(cold_samples)
        warm_ms = _median_ms(warm_samples)
        cold_p95_ms = p95_ms(cold_samples)
        warm_p95_ms = p95_ms(warm_samples)
        spacy_ms, tokens = _spacy_samples(process, sentences, rounds)
        effect = _cache_effect(cold_ms, warm_ms)
        speedup = cold_ms / warm_ms
        other_ms = cold_ms - spacy_ms
        spacy_pct = spacy_ms / cold_ms * 100.0
        nlp_path, nlp_path_detail = _nlp_path(syntax_tree, processor)
        print(f"cold_ms={cold_ms:.6f}")
        print(f"warm_ms={warm_ms:.6f}")
        print(f"cold_p95_ms={cold_p95_ms:.6f}")
        print(f"warm_p95_ms={warm_p95_ms:.6f}")
        print(f"samples_cold_ms={format_samples(cold_samples)}")
        print(f"samples_warm_ms={format_samples(warm_samples)}")
        print(f"cache_speedup={_format_speedup(speedup)}")
        print(f"approx_note={APPROX_NOTE}")
        print(f"cache_effective={effect}")
        print(f"cache_items_identical={'yes' if items_identical else 'no'}")
        print(f"cache_clear_verified={'yes' if cleared else 'no'}")
        print(f"nlp_path={nlp_path}")
        print(f"nlp_path_detail={nlp_path_detail}")
        print(f"sentences={len(sentences)}")
        print(f"tokens={tokens}")
        print(f"spacy_ms={spacy_ms:.3f}")
        print(f"other_ms={other_ms:.3f}")
        print(f"spacy_pct={spacy_pct:.1f}%")
        print(f"rounds={rounds}")
        print(f"verdict={_verdict(effect, cold_ms, warm_ms, len(sentences), nlp_path)}")
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
