# -*- coding: utf-8 -*-
"""NLP 引擎、CEFR 词典与分级算法、德语文本分析流水线。"""

import importlib
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    import spacy
except ImportError:
    # spaCy 缺失时的运行时降级占位（红线 1：降级路径是有意设计）。
    spacy = None  # type: ignore[assignment]

from delector.core.lexicon import get_core_cefr_level, lookup_core_vocab
from delector.core.utils import is_android

from .syntax_tree import analyze_sentence_topology, build_clause_tree, split_sentences_pure_python

# md 带词向量、标注更准，是桌面端首选；sm 体积小，Android 包里装的和自动下载兜底都用它。
# 按顺序取第一个能加载的。
SPACY_MODEL_CANDIDATES = ("de_core_news_md", "de_core_news_sm")
AUTO_DOWNLOAD_MODEL = "de_core_news_sm"

# processed_json 的 schema 版本号 —— 全仓唯一真相源。
# 惰性迁移判据（routes/main.py 的 GET /api/articles/{article_id}）按它比对：
# 判据端与写入端 MUST 共用这一个常量。曾因两端各写一份字面量而漂移
#（写入 "3.5.0" / 判据 "3.4.0"），判据恒真 ⇒ 「惰性迁移」退化成
#「每次 GET 都重跑 spaCy 并 UPDATE articles」。改版本号只改这里。
PROCESSED_JSON_VERSION = "3.5.0"


def _load_spacy_model(name: str) -> Tuple[Any, str]:
    """加载指定德语模型，返回 (nlp, 加载方式描述)；全部策略失败则抛 RuntimeError。

    为什么不能只用 spacy.load(name)：它走 spacy.util.is_package()，查的是
    importlib.metadata 的 .dist-info 元数据。Android 上模型是被直接拷进 Chaquopy
    的 Python 源码目录的（见 CI 的 sync 步骤），没有 dist-info，于是即便这个包
    import 得动，也只会报 "[E050] Can't find model"——真机上就是这么退化成纯
    Python 路径的。所以按名称失败后要退到模块自身的 load()，最后退到数据目录路径。
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
# 三条硬约束：① import 期不得 spacy.load；② 首次并发调用只加载一次（互斥锁 + 双检）；
# ③ 加载失败必须**大声失败**（抛异常），不得静默返回空结果。
_model_lock = threading.Lock()
_nlp_model: Any = None  # 解析成功后的真实模型对象
_nlp_resolved = False  # 是否已解析（成功或失败都置位，保证「只加载一次」）
_nlp_error = ""  # 解析失败原因（供错误信息与诊断）

# 平台分流：Android 导入期既不 spacy.load 也不 (spacy.cli.)download —— Chaquopy 里
# download 会起 pip 子进程阻塞启动页。故这里先算一次，作为下方下载路径的门控依据。
_android_runtime = is_android()


def _load_model_with_autodownload() -> Tuple[Any, str]:
    """按候选顺序加载模型；候选全失败时自动下载兜底。返回 (nlp, 加载方式描述)。

    「Android 不下载」的保证由调用方给出：Android 路径根本不会走到本函数（见本块末尾的
    平台分支），故旧故障（Chaquopy 里 spacy.cli.download 起 pip 子进程阻塞启动页）不会复发。
    """
    errors: List[str] = []
    for candidate in SPACY_MODEL_CANDIDATES:
        try:
            return _load_spacy_model(candidate)
        except Exception as e:
            errors.append(str(e))
    try:
        from spacy.cli import download  # type: ignore[attr-defined]  # spacy.cli 不显式导出 download

        download(AUTO_DOWNLOAD_MODEL)
        return _load_spacy_model(AUTO_DOWNLOAD_MODEL)
    except Exception as e:
        errors.append(f"自动下载 {AUTO_DOWNLOAD_MODEL} -> {e}")
    raise RuntimeError("; ".join(errors))


def _require_loaded_model() -> Any:
    """读取已解析模型；此前解析失败则抛出同一失败（不反复重试，避免每次请求都慢）。"""
    if _nlp_model is None:
        raise RuntimeError(f"德语 spaCy 模型不可用（此前加载失败）：{_nlp_error}")
    return _nlp_model


def _resolve_nlp_model() -> Any:
    """首次真正需要 NLP 时加载模型；成功返回模型，失败抛 RuntimeError（No-Silent-Failure）。

    并发安全（双检）：无锁快路径先查 `_nlp_resolved`，只有未解析才进锁，锁内再查一次 ——
    uvicorn 的首批并发请求因此只触发一次 spacy.load，其余等锁后复用同一结果，不会出现
    「两次加载」或「半初始化被读到」。

    引擎状态同步：`NLP_ENGINE` / `NLP_ENGINE_DETAIL` 在**导入期**已按平台分支置好（桌面为
    **声明值** "spacy"，不代表模型已加载，见文件末尾分支）；本函数成功时用**实际加载结果**
    再刷一遍，失败时改写为 "spacy(加载失败)"（让 live 读取方看到真实状态；理由见失败分支注释）。
    """
    global _nlp_model, _nlp_resolved, _nlp_error, NLP_ENGINE, NLP_ENGINE_DETAIL
    if _nlp_resolved:
        return _require_loaded_model()
    with _model_lock:
        if _nlp_resolved:
            return _require_loaded_model()
        try:
            _nlp_model, how = _load_model_with_autodownload()
        except Exception as e:
            # ② 失败语义（刻意设计，勿当 bug）：模型加载失败 = **硬失败，不降级**到纯 Python。
            # 理由：静默降级会让用户以为分析成功（拿到的是错误标注 —— 见 architecture.md
            # 「降级路径不只是精度低，而是会给出错误的语法标注」），比可见的 500 危险得多。
            # 注意：此时 `nlp` 仍是**非 None 的惰性代理**（本函数只记下「首用失败」），故本次及
            # 后续调用都抛 RuntimeError，绝不静默返回空值。
            # 与**红线 1**（spaCy 缺失 ⇒ 纯 Python）分属不同层次：那是**导入期**判定的平台路径
            # （`nlp is None`，见文件末尾 `if spacy is None` 分支），发生在任何请求之前；本分支是
            # **运行期**模型加载失败，发生在首次真正需要 NLP 时。二者处置不同、互不影响。
            _nlp_error = str(e)
            _nlp_resolved = True
            # ③ 失败后同步反映真实状态（避免 /api/settings 仍报 spacy 的轻微误导）：`NLP_ENGINE`
            # 是**显示用**字符串，调用方判「能否调用」用的是 `nlp is None`（此处仍非 None）⇒ 改这
            # 个字符串**不破坏**可调用语义。live 读取方（/api/settings、各基准）据此看到真实状态；
            # by-value 快照方看不到（旧写法），故 routes/main.py 的 /api/settings 已改为 live 读。
            NLP_ENGINE = "spacy(加载失败)"
            NLP_ENGINE_DETAIL = f"德语 spaCy 模型加载失败（硬失败，不降级到纯 Python）：{e}"
            print(f"[DeLector] NLP 引擎: {NLP_ENGINE} — {NLP_ENGINE_DETAIL}", flush=True)
            raise RuntimeError(f"德语 spaCy 模型加载失败（首次使用时加载）：{e}") from e
        # 成功：NLP_ENGINE 在导入期已是 "spacy"（声明值），这里用实际加载到的模型信息刷新 detail。
        NLP_ENGINE = "spacy"
        NLP_ENGINE_DETAIL = f"spaCy {getattr(spacy, '__version__', 'unknown')} + {how}"
        _nlp_resolved = True
        print(f"[DeLector] NLP 引擎（首次使用时加载）: {NLP_ENGINE} — {NLP_ENGINE_DETAIL}", flush=True)
        return _nlp_model


class _LazyNlp:
    """惰性 spaCy 模型代理：首次**调用**时才真正加载（ADR-0018 §7.6 O0）。

    为什么用代理而不是把 nlp 设成 None / 改成函数：既有调用方按**值**使用 `processor.nlp`
    （`from ... import nlp` 后 `nlp(text)` 与 `nlp is None`）。代理保留「可调用」这一既有语义，
    调用方无需改代码；同时把昂贵的 spacy.load 推迟到首次真正调用。`nlp is None` 仍能区分
    「spaCy 可用 vs 缺失/Android 降级」（后两者绑定真正的 None，见下方平台分支）。
    """

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return _resolve_nlp_model()(*args, **kwargs)


# 导入期只做**廉价**判定（import spacy 已在模块顶部试过），绝不在此 spacy.load。
# 此处写下的 NLP_ENGINE 是**导入期声明值**：桌面分支按平台选定为 "spacy"，**不代表模型已加载**
# —— 模型的**真实**加载结果由 `_resolve_nlp_model` 在首次使用时回填（成功仍 "spacy"、失败改
# "spacy(加载失败)"）。真机可用 adb logcat / GET /api/settings 确认实际走的路径。
if spacy is None:
    # 红线 1：spaCy 缺失 ⇒ 纯 Python 降级路径（既有语义，保持不变）。
    nlp: Any = None
    NLP_ENGINE = "pure_python"
    NLP_ENGINE_DETAIL = "spaCy 未安装，使用纯 Python 降级路径（无依存句法/格标注）"
elif _android_runtime:
    # Android：模型以裸源码目录拷贝、无 dist-info，spacy.load(名字) 必失败；导入期加载只会
    # 白白阻塞启动页，且必须避免 spacy.cli.download 起 pip 子进程。既有行为已实际退化到纯 Python
    #（docs/agents/architecture.md）——这里显式化：不导入期加载、不联网下载，直接降级（红线 1）。
    nlp = None
    NLP_ENGINE = "pure_python"
    NLP_ENGINE_DETAIL = "Android：模型不在导入期加载（无 dist-info/避免 pip 下载），走纯 Python 降级"
else:
    # 桌面：惰性加载。import 期**不** spacy.load；模型于首次 process_german_text 时加载。
    # 故下面的 NLP_ENGINE = "spacy" 是**声明值**（模型未加载也如此），**不是**"首次加载成功才赋值"。
    nlp = _LazyNlp()
    NLP_ENGINE = "spacy"
    NLP_ENGINE_DETAIL = f"spaCy {getattr(spacy, '__version__', 'unknown')} 已装（惰性加载：首次使用时加载模型）"

print(f"[DeLector] NLP 引擎: {NLP_ENGINE} — {NLP_ENGINE_DETAIL}", flush=True)

CEFR_DICT = {
    # A1 core
    "ich": "A1",
    "du": "A1",
    "er": "A1",
    "sie": "A1",
    "es": "A1",
    "wir": "A1",
    "ihr": "A1",
    "mein": "A1",
    "dein": "A1",
    "sein": "A1",
    "haben": "A1",
    "werden": "A1",
    "können": "A1",
    "müssen": "A1",
    "wollen": "A1",
    "sollen": "A1",
    "dürfen": "A1",
    "möchten": "A1",
    "lernen": "A1",
    "arbeiten": "A1",
    "gut": "A1",
    "tag": "A1",
    "gehen": "A1",
    "nach": "A1",
    "kommen": "A1",
    "wohnen": "A1",
    "heißen": "A1",
    "hallo": "A1",
    "deutsch": "A1",
    "deutschkurs": "A1",
    "trinken": "A1",
    "essen": "A1",
    "kaffee": "A1",
    "brot": "A1",
    "brötchen": "A1",
    "obst": "A1",
    "kaufen": "A1",
    "frisch": "A1",
    "supermarkt": "A1",
    "unterricht": "A1",
    "spaß": "A1",
    "viel": "A1",
    "morgen": "A1",
    "nachmittag": "A1",
    "abend": "A1",
    "u-bahn": "A1",
    "bahn": "A1",
    "kurs": "A1",
    "jetzt": "A1",
    "sprachschule": "A1",
    "schule": "A1",
    "jeder": "A1",
    "groß": "A1",
    "klein": "A1",
    "neu": "A1",
    "alt": "A1",
    "schön": "A1",
    "eins": "A1",
    "zwei": "A1",
    "drei": "A1",
    "jahr": "A1",
    "mann": "A1",
    "frau": "A1",
    "kind": "A1",
    "haus": "A1",
    "stadt": "A1",
    "zimmer": "A1",
    "der": "A1",
    "die": "A1",
    "das": "A1",
    "ein": "A1",
    "eine": "A1",
    "in": "A1",
    "an": "A1",
    "auf": "A1",
    "aus": "A1",
    "mit": "A1",
    "zu": "A1",
    "zum": "A1",
    "zur": "A1",
    "von": "A1",
    "bei": "A1",
    "für": "A1",
    "über": "A1",
    "unter": "A1",
    "vor": "A1",
    "hinter": "A1",
    "und": "A1",
    "oder": "A1",
    "aber": "A1",
    "denn": "A1",
    "nicht": "A1",
    "kein": "A1",
    "wie": "A1",
    "was": "A1",
    "wo": "A1",
    "woher": "A1",
    "wohin": "A1",
    "wann": "A1",
    "wer": "A1",
    # A2
    "erzählen": "A2",
    "erklären": "A2",
    "bestehen": "A2",
    "prüfung": "A2",
    "beruf": "A2",
    "reise": "A2",
    "fahren": "A2",
    "wochenende": "A2",
    "zug": "A2",
    "reservieren": "A2",
    "stadtzentrum": "A2",
    "wetter": "A2",
    "deshalb": "A2",
    "ganz": "A2",
    "garten": "A2",
    "verbringen": "A2",
    "typisch": "A2",
    "bayerisch": "A2",
    "spezialität": "A2",
    "traditionell": "A2",
    "restaurant": "A2",
    "probieren": "A2",
    "besuchen": "A2",
    "helfen": "A2",
    "treffen": "A2",
    "beginnen": "A2",
    "verstehen": "A2",
    # B1
    "entscheiden": "B1",
    "entwickeln": "B1",
    "zusammenhang": "B1",
    "gesellschaft": "B1",
    "meinung": "B1",
    "klimawandel": "B1",
    "klimaschutz": "B1",
    "herausforderung": "B1",
    "beitrag": "B1",
    "leisten": "B1",
    "umweltschutz": "B1",
    "experte": "B1",
    "empfehlen": "B1",
    "umsteigen": "B1",
    "energie": "B1",
    "haushalt": "B1",
    "sparen": "B1",
    "bewusst": "B1",
    "ernährung": "B1",
    "regional": "B1",
    "lebensmittel": "B1",
    "ebenfalls": "B1",
    "rolle": "B1",
    "spielen": "B1",
    "alltag": "B1",
    # B2
    "beeinträchtigen": "B2",
    "gewährleisten": "B2",
    "hervorheben": "B2",
    "voraussetzen": "B2",
    "digitalisierung": "B2",
    "transformation": "B2",
    "arbeitsbedingung": "B2",
    "grundlegend": "B2",
    "unternehmen": "B2",
    "mitarbeiter": "B2",
    "flexibel": "B2",
    "arbeitszeitmodell": "B2",
    "verfügung": "B2",
    "vereinbarkeit": "B2",
    "beschäftigte": "B2",
    "grenze": "B2",
    "fortschreitend": "B2",
    "arbeitswelt": "B2",
    "homeoffice": "B2",
    "ethisch": "B2",
    "fragestellung": "B2",
    "existenziell": "B2",
    "tragweite": "B2",
    # C1
    "implizieren": "C1",
    "fungieren": "C1",
    "paradigma": "C1",
    "unabdingbar": "C1",
    "differenzieren": "C1",
    "konstatieren": "C1",
    "ambivalent": "C1",
    "sukzessive": "C1",
}


# 词尾启发式（get_cefr_level 每词调用，常量化免重建元组）
_CEFR_B2_SUFFIX_HINTS = ("ität", "ismus", "schaft", "ung")


def get_cefr_level(lemma: str) -> str:
    if not lemma:
        return "A1"
    low = lemma.lower().strip()

    # 1. Exact core dictionary lookup
    dict_lvl = get_core_cefr_level(low)
    if dict_lvl:
        return dict_lvl

    # 2. Hardcoded fallback list
    if low in CEFR_DICT:
        return CEFR_DICT[low]

    # 3. Suffix and length heuristics
    if any(low.endswith(s) for s in _CEFR_B2_SUFFIX_HINTS):
        return "B2" if len(low) > 10 else "B1"
    if len(low) > 11:
        return "B2"
    if len(low) > 7:
        return "B1"
    if len(low) > 4:
        return "A2"
    return "A1"


def calculate_cefr_stats(tokens_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts = {"A1": 0, "A2": 0, "B1": 0, "B2": 0, "C1": 0}
    words = [t for t in tokens_list if t.get("cefr_level")]
    total_words = len(words)

    for w in words:
        lvl = w["cefr_level"]
        if lvl in counts:
            counts[lvl] += 1

    percentages = {}
    for lvl, cnt in counts.items():
        percentages[lvl] = round((cnt / total_words * 100), 1) if total_words > 0 else 0.0

    non_a1_count = total_words - counts["A1"]
    non_a1_ratio = (non_a1_count / total_words) if total_words > 0 else 0.0

    if non_a1_ratio < 0.15:
        recommended = "A1"
    elif non_a1_ratio < 0.30:
        recommended = "A2"
    elif non_a1_ratio < 0.50:
        recommended = "B1"
    else:
        recommended = "B2+"

    est_minutes = max(1, round(total_words / 90))  # 90 words/min 精读标准

    return {
        "word_count": total_words,
        "est_reading_minutes": est_minutes,
        "recommended_level": recommended,
        "cefr_counts": counts,
        "cefr_percentages": percentages,
    }


def _process_german_text_pure_python(text: str) -> Dict[str, Any]:
    raw_sents = split_sentences_pure_python(text)
    sentences = []
    all_tokens = []
    global_tok_id = 0
    for sent_idx, sent_text in enumerate(raw_sents):
        tokens = []
        raw_toks = re.findall(r"\w+|[^\w\s]", sent_text, re.UNICODE)
        for raw_tok in raw_toks:
            is_punct = bool(re.match(r"^[^\w\s]+$", raw_tok))
            # 无 spacy 时靠核心词库反查词元，命中则用词典词元覆盖朴素小写形
            dict_entry = lookup_core_vocab(raw_tok) or {}
            lemma = dict_entry.get("lemma") or raw_tok.lower()
            pos = dict_entry.get("pos") or ("PUNCT" if is_punct else ("NOUN" if raw_tok[0].isupper() else "ADV"))
            gender = dict_entry.get("gender", "")
            cefr = dict_entry.get("cefr_level") or ("" if is_punct else get_cefr_level(lemma))
            tok = {
                "id": global_tok_id,
                "text": raw_tok,
                "lemma": lemma,
                "pos": pos,
                "gender": gender,
                "case": "",
                "cefr_level": cefr,
                "is_punct": is_punct,
                "is_space": False,
            }
            tokens.append(tok)
            all_tokens.append(tok)
            global_tok_id += 1
        sentences.append(
            {
                "id": sent_idx,
                "text": sent_text,
                "tokens": tokens,
                "topology": {
                    "vorfeld": [],
                    "linke_klammer": [],
                    "mittelfeld": [t["text"] for t in tokens if not t["is_punct"]],
                    "rechte_klammer": [],
                    "nachfeld": [],
                },
                "clause_tree": {
                    "id": "root",
                    "type": "hauptsatz",
                    "label": "Hauptsatz",
                    "label_zh": "主句核心",
                    "connector": "",
                    "finite_verb": "",
                    "token_ids": list(range(len(tokens))),
                    "formula": "",
                    "children": [],
                },
            }
        )
    stats = calculate_cefr_stats(all_tokens)
    return {
        "version": PROCESSED_JSON_VERSION,
        "sentence_count": len(sentences),
        "sentences": sentences,
        "stats": stats,
    }


def process_german_text(text: str) -> Dict[str, Any]:
    if nlp is None:
        return _process_german_text_pure_python(text)
    doc = nlp(text)
    sentences = []
    all_tokens = []
    for sent_idx, sent in enumerate(doc.sents):
        tokens = []
        token_map = {}
        spacy_tokens = list(sent)
        for t in spacy_tokens:
            morph = t.morph.to_dict()
            is_word = not t.is_punct and not t.is_space
            tok = {
                "id": t.i,
                "text": t.text,
                "lemma": t.lemma_,
                "pos": t.pos_,
                "gender": morph.get("Gender", ""),
                "case": morph.get("Case", ""),
                "cefr_level": get_cefr_level(t.lemma_) if is_word else "",
                "is_punct": t.is_punct,
                "is_space": t.is_space,
            }
            tokens.append(tok)
            token_map[t.i] = tok
            all_tokens.append(tok)

        # Detect separable verb prefixes in sentence (compound:prt or svp or PTKVZ)
        for t in spacy_tokens:
            if t.dep_ in ("compound:prt", "svp", "ptkv") or t.tag_ == "PTKVZ":
                head = t.head
                if head and head.i in token_map:
                    prefix_str = (t.lemma_ or t.text).lower().strip()
                    verb_lemma = (head.lemma_ or head.text).lower().strip()
                    if verb_lemma.startswith(prefix_str):
                        sep_lemma = verb_lemma
                    else:
                        sep_lemma = f"{prefix_str}{verb_lemma}"

                    verb_tok = token_map[head.i]
                    prefix_tok = token_map[t.i]

                    verb_tok["separable"] = {"sep_prefix_id": t.i, "sep_lemma": sep_lemma}
                    prefix_tok["separable"] = {"sep_verb_id": head.i, "sep_lemma": sep_lemma}

                    # Re-evaluate CEFR level based on full separable verb
                    # (e.g. einsteigen -> A1 instead of steigen -> B1)
                    sep_cefr = get_cefr_level(sep_lemma)
                    verb_tok["cefr_level"] = sep_cefr
                    prefix_tok["cefr_level"] = sep_cefr
        # Compute topological 5 fields and clause AST tree for each sentence
        top = analyze_sentence_topology(sent)
        tree = build_clause_tree(sent)
        sentences.append({"id": sent_idx, "text": sent.text, "tokens": tokens, "topology": top, "clause_tree": tree})
    stats = calculate_cefr_stats(all_tokens)
    return {
        "version": PROCESSED_JSON_VERSION,
        "sentence_count": len(sentences),
        "sentences": sentences,
        "stats": stats,
    }


SYSTEM_GRAMMAR_PROMPT = (
    """你是一位精通德语欧标（Goethe-Zertifikat A1-C1）的资深德语教学与考点解析专家。
用户会提供一个德语完整句子，以及他们点击的目标词汇或短语（用户可能是 A1-A2 零基础/初学者）。

请详细分析该词或短语在句中的关键语法考点，特别关照初学者的痛点（如：冠词四格变化、三格动词、动词现在时变位、可分动词前缀、从句动词置后、固定介词搭配）。

以严格的 JSON 格式输出，字段如下：
{
  "grammar_name": "考点名称（如：Akkusativ mit bestimmtem Artikel / Trennbare Verben / """
    """Nomen-Verb-Verbindung / Präposition mit Dativ）",
  "cefr_level": "考点对应的欧标等级，只能是 A1/A2/B1/B2/C1 之一",
  "explanation_zh": "面向初学者的通俗精炼中文解析（1-3句话，解释在句中的语法作用、为什么用这个格/变位，"""
    """指出考试高频错点）",
  "rule_formula": "语法规则或公式（如：trinken + Akkusativ: den Kaffee (m.) / fahren mit + Dativ: der U-Bahn (f.)）",
  "collocations": ["高频用法1", "高频用法2"]
}
不要输出除 JSON 以外的任何文字。"""
)
