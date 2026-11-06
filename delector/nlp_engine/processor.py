# -*- coding: utf-8 -*-
"""NLP 引擎、CEFR 词典与分级算法、德语文本分析流水线。"""

import re
from typing import Any, Dict, List, Tuple

from delector.core.lexicon import get_core_cefr_level, lookup_core_vocab

from . import model_loader as _model_loader

# 模型档位常量（ADR-0027）与加载实现（ADR-0028）的唯一真相源是 model_loader。
# 依赖方向：processor ──> model_loader <── syntax_tree（单向，无环）。
from .model_loader import SPACY_MODEL_NAME as SPACY_MODEL_NAME
from .model_loader import _LazyNlp
from .model_loader import spacy as spacy
from .syntax_tree import analyze_sentence_topology, build_clause_tree, split_sentences_pure_python

# processed_json 的 schema 版本号 —— 全仓唯一真相源。
# 惰性迁移判据（routes/main.py 的 GET /api/articles/{article_id}）按它比对：
# 判据端与写入端 MUST 共用这一个常量。曾因两端各写一份字面量而漂移
#（写入 "3.5.0" / 判据 "3.4.0"），判据恒真 ⇒ 「惰性迁移」退化成
#「每次 GET 都重跑 spaCy 并 UPDATE articles」。改版本号只改这里。
PROCESSED_JSON_VERSION = "3.5.0"


# ── 模型加载兼容入口（实现已迁至 `model_loader`，此处只做转发）────────────────────
# 历史原因：加载器与缓存原本长在本模块，`syntax_tree` 只能用函数内 import 反向取用，
# 把 processor ↔ syntax_tree 的环藏起来。2026-11-06 抽出 model_loader 后，两方都只单向
# 依赖它；本模块保留这些名字，供既有调用方/工具/测试按原路径使用。
def _load_spacy_model(name: str) -> Tuple[Any, str]:
    """兼容入口：实现见 `model_loader._load_spacy_model`（三级回退的唯一真相源）。"""
    return _model_loader._load_spacy_model(name)


def _load_model_with_autodownload() -> Tuple[Any, str]:
    """兼容入口：Android 禁下载门控在 `model_loader` 的实现**内部**（ADR-0028 D5）。"""
    return _model_loader._load_model_with_autodownload()


def _resolve_nlp_model() -> Any:
    """兼容入口：双检锁、硬失败与状态回填见 `model_loader._resolve_nlp_model`。"""
    return _model_loader._resolve_nlp_model()


def get_loaded_nlp() -> Any:
    """兼容入口：只读已加载模型、不触发加载（实现见 model_loader）。"""
    return _model_loader.get_loaded_nlp()


def try_load_nlp_no_download() -> Any:
    """兼容入口：仅本地加载、绝不下载（实现见 model_loader）。"""
    return _model_loader.try_load_nlp_no_download()


# 导入期只做**廉价**判定（spacy 的 import 已由 model_loader 完成），绝不在此 spacy.load。
# 此处绑定的 nlp 与引擎状态：spaCy 可用时（桌面与 Android 同口径）为惰性代理 + 声明值 "spacy"，
# **不代表模型已加载**——真实加载结果由 model_loader 在首次使用时回填。
if spacy is None:
    # 红线 1：spaCy 缺失 ⇒ 纯 Python 降级路径（既有语义，保持不变）。
    nlp: Any = None
else:
    # spaCy 可用（桌面与 Android 同口径，ADR-0028）：惰性加载。
    # import 期**不** spacy.load；模型于首次 process_german_text 时加载。
    nlp = _LazyNlp()


def __getattr__(name: str) -> Any:
    """把引擎状态与加载缓存代理到 `model_loader` 的**实时**值。

    唯一真相源在 model_loader：live 读取方（`/api/settings`、`tools/bench_*`）经
    `processor.<name>` 访问时必须看到最新值。`from ... import NLP_ENGINE` 仍是导入期快照
    （既有语义，未改变）。
    """
    if name in (
        "NLP_ENGINE",
        "NLP_ENGINE_DETAIL",
        "_nlp_model",
        "_nlp_resolved",
        "_nlp_error",
        "_android_runtime",
        "_model_lock",
    ):
        return getattr(_model_loader, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
