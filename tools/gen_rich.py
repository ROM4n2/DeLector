# -*- coding: utf-8 -*-
"""
Build official_vocab_rich.py — rich side-car (ipa + example_de + example_zh + topic)
for Goethe A1/A2/B1 official word lists.

Schema: lemma -> {"ipa","example_de","example_zh","topic"}  (Python dict literal, not JSON)

ipa source (now populated):
  Each level's IPA comes from a g2p.py rule-based transcription of the German headwords
  (same method used for the A1 bilingual PDF). ipa_map.json files (keyed by RAW headword)
  live in each level's _build dir:
    - A1 : D:/Ran/German/_build/ipa_map.json            (g2p.py, default dir)
    - A2 : D:/Ran/Goethe_A2/_build/ipa_map.json         (g2p.py D:/Ran/Goethe_A2/_build)
    - B1 : D:/Ran/Goethe_B1/_build/ipa_map.json         (g2p.py D:/Ran/Goethe_B1/_build)
  headword -> lemma alignment uses the EXACT normalizer that built each fragment:
    - A1 : build_a1.normalize_lemma (+ reflexive -> sich- prefix)
    - A2/B1 : build_a2b1_v2.parse_entry (no sich- prefix; matches a2b1_fragment.py)
  Entries the G2P engine cannot derive deterministically are marked 待确认 and left blank
  (no fabrication, no guessing).

example_de: from entries_raw.json (Goethe PDF Beispielsätze).
example_zh: A1 from tr_*.json [de,zh]; A2/B1 from a2b1_enrich.json (de+zh pre-aligned).
zh examples are taken VERBATIM from provided source files (not machine-translated by assistant).
topic: "general" (sources carry no topic tags).

Step 0 self-check (see report_rich.md):
  IPA column ABSENT from word-list sources -> derived via g2p rule engine (not extracted from
  a pronunciation dictionary). example columns PRESENT -> branch "only examples + derived ipa".

【仓库归档】本脚本为外部生成链的归档快照，用于可重放性参考。它依赖外部目录（D:/Ran/...）
与外部 helper（build_a1 / build_a2b1_v2 / g2p.py），在本仓库内不可直接运行。
重新生成时需先具备这些外部前置条件（源 entries_raw.json / tr_*.json / a2b1_enrich.json /
ipa_map.json / *_fragment.py 均位于外部目录），并注意本仓已回填的 10 条空 IPA（见
delector/data/official_vocab_rich.py 的模块 docstring），重跑后需一并带回，否则回退丢失。
"""
import importlib.util
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------- reuse build_a1.normalize_lemma (single source of truth for A1 lemma keys) ----------
_spec = importlib.util.spec_from_file_location("build_a1", os.path.join(HERE, 'build_a1.py'))
assert _spec is not None and _spec.loader is not None  # 归档快照：缺外部 helper 时直接失败
_ba1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ba1)
_norm_lemma = _ba1.normalize_lemma

def normalize_a1(hw: str) -> str:
    """Mirror build_a1.parse_entry's final lemma derivation exactly (sich- prefix for reflexive)."""
    lemma, _article, _rest, reflexive, _plural_only = _norm_lemma(hw)
    if reflexive and not lemma.startswith('sich-'):
        lemma = 'sich-' + lemma
    return lemma  # type: ignore[no-any-return]  # 外部 helper normalize_lemma 无注解→Any；按契约 lemma 恒为 str

# ---------- reuse build_a2b1_v2.parse_entry (exact A2/B1 lemma keys, no sich- prefix) ----------
_spec2 = importlib.util.spec_from_file_location("build_a2b1_v2", os.path.join(HERE, 'build_a2b1_v2.py'))
assert _spec2 is not None and _spec2.loader is not None  # 归档快照：缺外部 helper 时直接失败
_ba2 = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(_ba2)

def raw_to_lemma_a2b1(hw: str) -> Optional[str]:
    """Mirror build_a2b1_v2.parse_entry lemma derivation (article/reflexive strip, spaces->hyphen)."""
    pos_label = "n." if _ba2.ART_RE.match(hw) else "v."
    r, err = _ba2.parse_entry({"hw": hw, "pos_label": pos_label, "zh": ""})
    return r["lemma"] if r else None

# ---------- reuse g2p.transcribe_lemma as fallback for lemmas the headword-map missed ----------
# (e.g. prefix-pair expansions an-/ausziehen -> anziehen/ausziehen, which g2p marked 待确认
#  on the combined form but CAN transcribe per expanded lemma).
_specg = importlib.util.spec_from_file_location("g2p", os.path.join('D:/Ran/German/_build', 'g2p.py'))
assert _specg is not None and _specg.loader is not None  # 归档快照：缺外部 helper 时直接失败
_g2p = importlib.util.module_from_spec(_specg)
_specg.loader.exec_module(_g2p)

def g2p_ipa(lem: str) -> str:
    ipa, unc = _g2p.transcribe_lemma(lem)
    return "" if (unc or not ipa) else ipa

# simple normalizer retained for A2/B1 headwords (matches build_a2b1_v2 normalization)
ART = re.compile(r'^(der|die|das|den|dem|des|ein|eine|einen|einem|einer)\s+', re.I)
def normalize(hw: str) -> str:
    s = hw.strip()
    s = re.sub(r'^\(sich\)\s*', '', s, flags=re.I)
    s = ART.sub('', s).strip()
    s = s.split(',')[0].strip()
    return s.lower()

def load_fragment(path: str, const: str) -> Any:
    ns: Dict[str, Any] = {}
    exec(open(path, encoding='utf-8').read(), ns)
    return ns[const]

# ---------- A1 sources ----------
A1_TR_DIR = 'D:/Ran/German/_build'
a1_entries = json.load(open(os.path.join(A1_TR_DIR, 'entries_raw.json'), encoding='utf-8'))['entries']
# A1 tr: dict keyed by headword -> [[POS, gloss, [de, zh]], ...]
a1_tr = {}
for fn in os.listdir(A1_TR_DIR):
    if re.match(r'tr_.*\.json', fn):
        d = json.load(open(os.path.join(A1_TR_DIR, fn), encoding='utf-8'))
        if isinstance(d, dict):
            a1_tr.update(d)
# build A1 lookups (normalized with normalize_a1 so keys == a1_fragment lemma keys)
a1_tr_ex: Dict[str, Tuple[str, str]] = {}      # lemma -> (de, zh)  from tr [de,zh]
a1_er_ex: Dict[str, List[str]] = {}       # lemma -> [de, ...] from entries_raw
for k, v in a1_tr.items():
    lem = normalize_a1(k)
    sense = v[0] if v and isinstance(v, list) else None
    if sense and len(sense) >= 3 and isinstance(sense[2], list) and sense[2]:
        pair = sense[2]
        if len(pair) >= 2 and pair[0] and pair[1]:
            a1_tr_ex[lem] = (pair[0], pair[1])
        elif len(pair) >= 1 and pair[0]:
            a1_tr_ex[lem] = (pair[0], '')
for e in a1_entries:
    lem = normalize_a1(e['headword'])
    a1_er_ex.setdefault(lem, []).extend(e.get('examples') or [])

# ---------- A2/B1 sources ----------
ENRICH = json.load(open('D:/Ran/tools/data/a2b1_enrich.json', encoding='utf-8'))
a2_entries = json.load(open('D:/Ran/Goethe_A2/_build/entries_raw.json', encoding='utf-8'))['entries']
b1_entries = json.load(open('D:/Ran/Goethe_B1/_build/entries_raw.json', encoding='utf-8'))['entries']
a2b1_er_ex: Dict[str, List[str]] = {}
for e in a2_entries + b1_entries:
    lem = normalize(e['headword'])
    a2b1_er_ex.setdefault(lem, []).extend(e.get('examples') or [])

# ---------- load final fragments (join keys = lemma) ----------
A1_DB = load_fragment('D:/Ran/tools/data/a1_fragment.py', 'A1_VOCAB_DB')
A2B1_DB = load_fragment('D:/Ran/tools/data/a2b1_fragment.py', 'A2B1_VOCAB_DB')
A2_DB = {k: v for k, v in A2B1_DB.items() if v[0] == 'A2'}
B1_DB = {k: v for k, v in A2B1_DB.items() if v[0] == 'B1'}

# ---------- IPA maps (g2p rule-based; keyed by RAW headword) -> lemma->ipa ----------
def load_ipa(path: str) -> Dict[str, str]:
    return json.load(open(path, encoding='utf-8')) if os.path.exists(path) else {}

IPA_SRC = {
    'A1': load_ipa('D:/Ran/German/_build/ipa_map.json'),
    'A2': load_ipa('D:/Ran/Goethe_A2/_build/ipa_map.json'),
    'B1': load_ipa('D:/Ran/Goethe_B1/_build/ipa_map.json'),
}

def build_lemma_ipa(ipa_map: Dict[str, str], level: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for hw, ipa in ipa_map.items():
        if not ipa or ipa == '待确认':
            continue                       # 待确认 = 无法确定性推导 -> 留空，不编造
        lem = normalize_a1(hw) if level == 'A1' else raw_to_lemma_a2b1(hw)
        if not lem:
            continue
        out.setdefault(lem, ipa)          # first valid wins (per lemma)
    return out

IPA_A1 = build_lemma_ipa(IPA_SRC['A1'], 'A1')
IPA_A2 = build_lemma_ipa(IPA_SRC['A2'], 'A2')
IPA_B1 = build_lemma_ipa(IPA_SRC['B1'], 'B1')

# Fallback: transcribe any lemma still missing ipa directly via g2p (covers prefix-pair
# expansions and any headword->lemma gap). 待确认 lemmas stay blank (no fabrication).
for IPA, db in ((IPA_A1, A1_DB), (IPA_A2, A2_DB), (IPA_B1, B1_DB)):
    for lem in db:
        if lem not in IPA:
            ipa = g2p_ipa(lem)
            if ipa:
                IPA[lem] = ipa

def lookup(lemma: str, tr_ex: Dict[str, Tuple[str, str]], er_ex: Dict[str, List[str]]) -> Tuple[str, str]:
    if lemma in tr_ex:
        return tr_ex[lemma][0], tr_ex[lemma][1]
    if lemma in er_ex and er_ex[lemma]:
        return er_ex[lemma][0], ''
    # reflexive fallback: sich-X -> (sich) X
    if lemma.startswith('sich-'):
        alt = normalize_a1('(sich) ' + lemma[5:])
        if alt in tr_ex:
            return tr_ex[alt][0], tr_ex[alt][1]
        if alt in er_ex and er_ex[alt]:
            return er_ex[alt][0], ''
    return '', ''

def build(
    db: Dict[str, Any],
    tr_ex: Dict[str, Tuple[str, str]],
    er_ex: Dict[str, List[str]],
    ipa_map: Dict[str, str],
) -> Dict[str, Dict[str, str]]:
    out = {}
    for lem in db:
        de, zh = lookup(lem, tr_ex, er_ex)
        out[lem] = {'ipa': ipa_map.get(lem, ''), 'example_de': de,
                    'example_zh': zh, 'topic': 'general'}
    return out

RICH_A1 = build(A1_DB, a1_tr_ex, a1_er_ex, IPA_A1)

# ENRICH is keyed by lemma with {ex:[{de,zh}]}; override A2/B1 from it for clean de+zh
def from_enrich(db: Dict[str, Any], enrich: Any, ipa_map: Dict[str, str]) -> Dict[str, Dict[str, str]]:
    out = {}
    for lem in db:
        rec = enrich.get(lem)
        if rec and rec.get('ex'):
            ex0 = rec['ex'][0]
            de, zh = ex0.get('de', ''), ex0.get('zh', '')
        else:
            de, zh = lookup(lem, {}, a2b1_er_ex)
        out[lem] = {'ipa': ipa_map.get(lem, ''), 'example_de': de,
                    'example_zh': zh, 'topic': 'general'}
    return out
RICH_A2 = from_enrich(A2_DB, ENRICH, IPA_A2)
RICH_B1 = from_enrich(B1_DB, ENRICH, IPA_B1)

# ---------- emit ----------
def stats(name: str, d: Dict[str, Dict[str, str]]) -> None:
    n = len(d)
    hde = sum(1 for v in d.values() if v['example_de'])
    hzh = sum(1 for v in d.values() if v['example_zh'])
    hb = sum(1 for v in d.values() if v['example_de'] and v['example_zh'])
    hipa = sum(1 for v in d.values() if v['ipa'])
    miss = sum(1 for v in d.values() if not v['example_de'] and not v['example_zh'])
    print(f'  {name}: total={n} | has_de={hde} | has_zh={hzh} | has_both={hb} | has_ipa={hipa} | no_example={miss}')

print('=== coverage stats ===')
stats('A1', RICH_A1)
stats('A2', RICH_A2)
stats('B1', RICH_B1)
print('A2+B1 fragment split:', len(A2_DB), '+', len(B1_DB), '=', len(A2_DB)+len(B1_DB))
print('IPA map sizes (lemma): A1=%d A2=%d B1=%d' % (len(IPA_A1), len(IPA_A2), len(IPA_B1)))

# ---------- diagnose missing A1 lemmas (for delivery note transparency) ----------
missing_a1 = [lem for lem in sorted(RICH_A1) if not RICH_A1[lem]['example_de'] and not RICH_A1[lem]['example_zh']]
if missing_a1:
    print('\nA1 still without any example:', missing_a1)

def dump(name: str, d: Dict[str, Dict[str, str]]) -> str:
    lines = [f'{name} = {{']
    for lem in sorted(d):
        v = d[lem]
        lines.append(
            f"    {lem!r}: " + "{" +
            f"\"ipa\": {v['ipa']!r}, \"example_de\": {v['example_de']!r}, " +
            f"\"example_zh\": {v['example_zh']!r}, \"topic\": \"general\"" + "},"
        )
    lines.append('}')
    return '\n'.join(lines)

out = ['# -*- coding: utf-8 -*-',
       '# OFFICIAL_RICH — Goethe A1/A2/B1 rich side-car (ipa + examples).',
       '# Schema: lemma -> {"ipa","example_de","example_zh","topic"}',
       '# ipa: rule-based IPA from g2p.py (same method as A1 bilingual PDF). Source ipa_map.json',
       '#      per level: German/_build (A1), Goethe_A2/_build (A2), Goethe_B1/_build (B1).',
       '#      待确认 entries left blank (no fabrication). headword->lemma uses the exact',
       '#      normalizer of each fragment (build_a1.normalize_lemma for A1; build_a2b1_v2.parse_entry for A2/B1).',
       '# example_de: from entries_raw.json (Goethe PDF Beispielsätze).',
       '# example_zh: A1 from tr_*.json [de,zh]; A2/B1 from a2b1_enrich.json (de+zh pre-aligned).',
       '# zh examples are taken VERBATIM from provided source files (not machine-translated by assistant).',
       '# topic: "general" (sources carry no topic tags).',
       '# Generated by gen_rich.py. Do NOT hand-edit; rerun script to regenerate.',
       '']
out.append(dump('OFFICIAL_RICH_A1', RICH_A1))
out.append('')
out.append(dump('OFFICIAL_RICH_A2', RICH_A2))
out.append('')
out.append(dump('OFFICIAL_RICH_B1', RICH_B1))
open('D:/Ran/tools/data/official_vocab_rich.py', 'w', encoding='utf-8').write('\n'.join(out) + '\n')
print('\nWrote D:/Ran/tools/data/official_vocab_rich.py')
