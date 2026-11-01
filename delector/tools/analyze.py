# -*- coding: utf-8 -*-
"""NLP 分析 tool：薄包装 nlp_engine.processor.process_german_text 并提供面向 Agent 的蒸馏投影。"""

from __future__ import annotations

from typing import Any, Dict, List

from delector.nlp_engine.processor import process_german_text


def _extract_field_text(raw_topo: Dict[str, Any], field_name: str) -> str:
    """提取拓扑场域的纯文本字符串，优先使用 field_texts，其次拼接 token 列表。"""
    field_texts = raw_topo.get("field_texts")
    if isinstance(field_texts, dict) and field_name in field_texts:
        val = field_texts[field_name]
        if isinstance(val, str):
            return val
    raw_val = raw_topo.get(field_name, "")
    if isinstance(raw_val, str):
        return raw_val
    if isinstance(raw_val, list):
        parts: list[str] = []
        for item in raw_val:
            if isinstance(item, dict):
                text = item.get("text", "")
                if text:
                    parts.append(str(text))
            elif item is not None:
                parts.append(str(item))
        return " ".join(parts).strip()
    return str(raw_val) if raw_val is not None else ""


def distill_analysis_for_agent(raw_res: Dict[str, Any]) -> Dict[str, Any]:
    """将包含庞大 AST、重复 token 副本与 spaCy 调试指针的原始分析结果，蒸馏为高信噪比投影。

    - 剔除 clause_tree AST 与 stats 统计。
    - 拓扑 5 场域仅保留纯文本字符串及 sentence_type、bracket_structure。
    - 词元列表剥离 head_id, dep, tag, is_space, is_punct 等内部指针，
      仅保留 text, lemma, pos, case, gender, number, cefr_level。
    """
    raw_sentences = raw_res.get("sentences", [])
    if not isinstance(raw_sentences, list):
        return {"sentences": []}

    sentences: List[Dict[str, Any]] = []
    for raw_sent in raw_sentences:
        if not isinstance(raw_sent, dict):
            continue

        raw_topo: Dict[str, Any] = raw_sent.get("topology") or {}

        # 从拓扑场域中提取 token 映射，补充 tokens 列表缺失的形态学字段（如 number）
        topo_tokens: Dict[int, Dict[str, Any]] = {}
        for field in ("vorfeld", "linke_klammer", "mittelfeld", "rechte_klammer", "nachfeld"):
            field_tokens = raw_topo.get(field, [])
            if isinstance(field_tokens, list):
                for tok_item in field_tokens:
                    if isinstance(tok_item, dict) and "id" in tok_item and isinstance(tok_item["id"], int):
                        topo_tokens[tok_item["id"]] = tok_item

        topology: Dict[str, str] = {
            "vorfeld": _extract_field_text(raw_topo, "vorfeld"),
            "linke_klammer": _extract_field_text(raw_topo, "linke_klammer"),
            "mittelfeld": _extract_field_text(raw_topo, "mittelfeld"),
            "rechte_klammer": _extract_field_text(raw_topo, "rechte_klammer"),
            "nachfeld": _extract_field_text(raw_topo, "nachfeld"),
            "sentence_type": str(raw_topo.get("sentence_type", "") or ""),
            "bracket_structure": str(raw_topo.get("bracket_structure", "") or ""),
        }

        raw_tokens = raw_sent.get("tokens", [])
        tokens: List[Dict[str, str]] = []
        if isinstance(raw_tokens, list):
            for t in raw_tokens:
                if not isinstance(t, dict):
                    continue
                if t.get("is_space"):
                    continue

                tok_id = t.get("id")
                number = t.get("number")
                if not number and isinstance(tok_id, int) and tok_id in topo_tokens:
                    number = topo_tokens[tok_id].get("number", "")

                tokens.append({
                    "text": str(t.get("text", "") or ""),
                    "lemma": str(t.get("lemma", "") or ""),
                    "pos": str(t.get("pos", "") or ""),
                    "case": str(t.get("case", "") or ""),
                    "gender": str(t.get("gender", "") or ""),
                    "number": str(number or ""),
                    "cefr_level": str(t.get("cefr_level", "") or ""),
                })

        sentences.append({
            "id": str(raw_sent.get("id", "")),
            "text": str(raw_sent.get("text", "") or ""),
            "topology": topology,
            "tokens": tokens,
        })

    return {
        "sentences": sentences,
        "stats": raw_res.get("stats", {}),
    }


async def run(payload: Dict[str, Any]) -> Dict[str, Any]:
    """运行 NLP 分析 tool，默认返回面向 Agent 蒸馏后的高信噪比投影。"""
    text = payload["text"]
    raw_res = process_german_text(text)
    if payload.get("raw"):
        return raw_res
    return distill_analysis_for_agent(raw_res)
