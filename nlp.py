# -*- coding: utf-8 -*-
"""NLP 引擎、CEFR 词典与分级算法、德语文本分析流水线。"""
import importlib
import re
from pathlib import Path
from typing import Dict, Any

try:
    import spacy
except ImportError:
    spacy = None

from start import is_android
from core_dict import lookup_core_vocab, get_core_cefr_level
from syntax_tree import (analyze_sentence_topology, build_clause_tree,
                         split_sentences_pure_python)

# md 带词向量、标注更准，是桌面端首选；sm 体积小，Android 包里装的和自动下载兜底都用它。
# 按顺序取第一个能加载的。
SPACY_MODEL_CANDIDATES = ("de_core_news_md", "de_core_news_sm")
AUTO_DOWNLOAD_MODEL = "de_core_news_sm"


def _load_spacy_model(name: str):
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
        root = Path(module.__file__).parent
        data_dirs = sorted(root.glob(f"{name}-*"))
        if not data_dirs:
            raise FileNotFoundError(f"{root} 下没有 {name}-* 数据目录")
        return spacy.load(data_dirs[-1]), f"{name}({data_dirs[-1].name})"
    except Exception as e:
        errors.append(f"path load -> {e}")

    raise RuntimeError("; ".join(errors))


nlp = None
# 记录实际生效的引擎，便于在真机上（adb logcat / GET /api/settings）确认
# 到底是 spaCy 还是纯 Python 降级路径在跑——降级本身是静默的。
NLP_ENGINE = "pure_python"
NLP_ENGINE_DETAIL = "spaCy 未安装，使用纯 Python 降级路径（无依存句法/格标注）"

if spacy is not None:
    load_errors = []
    for candidate in SPACY_MODEL_CANDIDATES:
        try:
            nlp, how = _load_spacy_model(candidate)
            NLP_ENGINE = "spacy"
            NLP_ENGINE_DETAIL = f"spaCy {spacy.__version__} + {how}"
            break
        except Exception as e:
            load_errors.append(str(e))

    if nlp is None:
        # 自动下载模型只在桌面端有意义。Android 上 spacy.cli.download 会起 pip
        # 子进程去拉模型：Chaquopy 里必然失败，却会在 import 期阻塞启动。
        if is_android():
            NLP_ENGINE_DETAIL = "spaCy 已装但模型加载失败，降级为纯 Python：" + " | ".join(load_errors)
        else:
            try:
                from spacy.cli import download
                download(AUTO_DOWNLOAD_MODEL)
                nlp, how = _load_spacy_model(AUTO_DOWNLOAD_MODEL)
                NLP_ENGINE = "spacy"
                NLP_ENGINE_DETAIL = f"spaCy {spacy.__version__} + {how}（自动下载）"
            except Exception as e:
                NLP_ENGINE_DETAIL = f"spaCy 已装但模型不可用，降级为纯 Python：{e}"

print(f"[DeLector] NLP 引擎: {NLP_ENGINE} — {NLP_ENGINE_DETAIL}", flush=True)

CEFR_DICT = {
    # A1 core
    "ich": "A1", "du": "A1", "er": "A1", "sie": "A1", "es": "A1", "wir": "A1", "ihr": "A1",
    "mein": "A1", "dein": "A1", "sein": "A1", "haben": "A1", "werden": "A1",
    "können": "A1", "müssen": "A1", "wollen": "A1", "sollen": "A1", "dürfen": "A1", "möchten": "A1",
    "lernen": "A1", "arbeiten": "A1", "gut": "A1", "tag": "A1", "gehen": "A1", "nach": "A1",
    "kommen": "A1", "wohnen": "A1", "heißen": "A1", "hallo": "A1", "deutsch": "A1", "deutschkurs": "A1",
    "trinken": "A1", "essen": "A1", "kaffee": "A1", "brot": "A1", "brötchen": "A1", "obst": "A1",
    "kaufen": "A1", "frisch": "A1", "supermarkt": "A1", "unterricht": "A1", "spaß": "A1", "viel": "A1",
    "morgen": "A1", "nachmittag": "A1", "abend": "A1", "u-bahn": "A1", "bahn": "A1", "kurs": "A1",
    "jetzt": "A1", "sprachschule": "A1", "schule": "A1", "jeder": "A1", "groß": "A1", "klein": "A1",
    "neu": "A1", "alt": "A1", "schön": "A1", "eins": "A1", "zwei": "A1", "drei": "A1", "jahr": "A1",
    "mann": "A1", "frau": "A1", "kind": "A1", "haus": "A1", "stadt": "A1", "zimmer": "A1",
    "der": "A1", "die": "A1", "das": "A1", "ein": "A1", "eine": "A1", "in": "A1", "an": "A1",
    "auf": "A1", "aus": "A1", "mit": "A1", "zu": "A1", "zum": "A1", "zur": "A1", "von": "A1",
    "bei": "A1", "für": "A1", "über": "A1", "unter": "A1", "vor": "A1", "hinter": "A1",
    "und": "A1", "oder": "A1", "aber": "A1", "denn": "A1", "nicht": "A1", "kein": "A1",
    "wie": "A1", "was": "A1", "wo": "A1", "woher": "A1", "wohin": "A1", "wann": "A1", "wer": "A1",
    
    # A2
    "erzählen": "A2", "erklären": "A2", "bestehen": "A2", "prüfung": "A2", "beruf": "A2", "reise": "A2",
    "fahren": "A2", "wochenende": "A2", "zug": "A2", "reservieren": "A2", "stadtzentrum": "A2",
    "wetter": "A2", "deshalb": "A2", "ganz": "A2", "garten": "A2", "verbringen": "A2",
    "typisch": "A2", "bayerisch": "A2", "spezialität": "A2", "traditionell": "A2", "restaurant": "A2", "probieren": "A2",
    "besuchen": "A2", "helfen": "A2", "treffen": "A2", "beginnen": "A2", "verstehen": "A2",
    
    # B1
    "entscheiden": "B1", "entwickeln": "B1", "zusammenhang": "B1", "gesellschaft": "B1", "meinung": "B1",
    "klimawandel": "B1", "klimaschutz": "B1", "herausforderung": "B1", "beitrag": "B1", "leisten": "B1",
    "umweltschutz": "B1", "experte": "B1", "empfehlen": "B1", "umsteigen": "B1", "energie": "B1",
    "haushalt": "B1", "sparen": "B1", "bewusst": "B1", "ernährung": "B1", "regional": "B1",
    "lebensmittel": "B1", "ebenfalls": "B1", "rolle": "B1", "spielen": "B1", "alltag": "B1",
    
    # B2
    "beeinträchtigen": "B2", "gewährleisten": "B2", "hervorheben": "B2", "voraussetzen": "B2",
    "digitalisierung": "B2", "transformation": "B2", "arbeitsbedingung": "B2", "grundlegend": "B2",
    "unternehmen": "B2", "mitarbeiter": "B2", "flexibel": "B2", "arbeitszeitmodell": "B2",
    "verfügung": "B2", "vereinbarkeit": "B2", "beschäftigte": "B2", "grenze": "B2", "fortschreitend": "B2",
    "arbeitswelt": "B2", "homeoffice": "B2", "ethisch": "B2", "fragestellung": "B2", "existenziell": "B2",
    "tragweite": "B2",
    
    # C1
    "implizieren": "C1", "fungieren": "C1", "paradigma": "C1", "unabdingbar": "C1",
    "differenzieren": "C1", "konstatieren": "C1", "ambivalent": "C1", "sukzessive": "C1"
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


def calculate_cefr_stats(tokens_list: list) -> Dict[str, Any]:
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
        "cefr_percentages": percentages
    }


def _process_german_text_pure_python(text: str) -> Dict[str, Any]:
    raw_sents = split_sentences_pure_python(text)
    sentences = []
    all_tokens = []
    global_tok_id = 0
    for sent_idx, sent_text in enumerate(raw_sents):
        tokens = []
        raw_toks = re.findall(r'\w+|[^\w\s]', sent_text, re.UNICODE)
        for raw_tok in raw_toks:
            is_punct = bool(re.match(r'^[^\w\s]+$', raw_tok))
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
                "is_space": False
            }
            tokens.append(tok)
            all_tokens.append(tok)
            global_tok_id += 1
        sentences.append({
            "id": sent_idx,
            "text": sent_text,
            "tokens": tokens,
            "topology": {"vorfeld": [], "linke_klammer": [], "mittelfeld": [t["text"] for t in tokens if not t["is_punct"]], "rechte_klammer": [], "nachfeld": []},
            "clause_tree": {"id": "root", "type": "hauptsatz", "label": "Hauptsatz", "label_zh": "主句核心", "connector": "", "finite_verb": "", "token_ids": list(range(len(tokens))), "formula": "", "children": []}
        })
    stats = calculate_cefr_stats(all_tokens)
    return {"version": "3.5.0", "sentence_count": len(sentences), "sentences": sentences, "stats": stats}


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
                "is_space": t.is_space
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
                    
                    verb_tok["separable"] = {
                        "sep_prefix_id": t.i,
                        "sep_lemma": sep_lemma
                    }
                    prefix_tok["separable"] = {
                        "sep_verb_id": head.i,
                        "sep_lemma": sep_lemma
                    }

                    # Re-evaluate CEFR level based on full separable verb (e.g. einsteigen -> A1 instead of steigen -> B1)
                    sep_cefr = get_cefr_level(sep_lemma)
                    verb_tok["cefr_level"] = sep_cefr
                    prefix_tok["cefr_level"] = sep_cefr
        # Compute topological 5 fields and clause AST tree for each sentence
        top = analyze_sentence_topology(sent)
        tree = build_clause_tree(sent)
        sentences.append({
            "id": sent_idx,
            "text": sent.text,
            "tokens": tokens,
            "topology": top,
            "clause_tree": tree
        })
    stats = calculate_cefr_stats(all_tokens)
    return {"version": "3.5.0", "sentence_count": len(sentences), "sentences": sentences, "stats": stats}


SYSTEM_GRAMMAR_PROMPT = """你是一位精通德语欧标（Goethe-Zertifikat A1-C1）的资深德语教学与考点解析专家。
用户会提供一个德语完整句子，以及他们点击的目标词汇或短语（用户可能是 A1-A2 零基础/初学者）。

请详细分析该词或短语在句中的关键语法考点，特别关照初学者的痛点（如：冠词四格变化、三格动词、动词现在时变位、可分动词前缀、从句动词置后、固定介词搭配）。

以严格的 JSON 格式输出，字段如下：
{
  "grammar_name": "考点名称（如：Akkusativ mit bestimmtem Artikel / Trennbare Verben / Nomen-Verb-Verbindung / Präposition mit Dativ）",
  "cefr_level": "考点对应的欧标等级，只能是 A1/A2/B1/B2/C1 之一",
  "explanation_zh": "面向初学者的通俗精炼中文解析（1-3句话，解释在句中的语法作用、为什么用这个格/变位，指出考试高频错点）",
  "rule_formula": "语法规则或公式（如：trinken + Akkusativ: den Kaffee (m.) / fahren mit + Dativ: der U-Bahn (f.)）",
  "collocations": ["高频用法1", "高频用法2"]
}
不要输出除 JSON 以外的任何文字。"""
