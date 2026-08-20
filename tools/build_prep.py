#!/usr/bin/env python
"""一次性构建工具：为现有词库里的动词/形容词生成固定介词搭配数据集。

为什么存在：Präposition + 格 是歌德考试的高频失分点，而查词抽屉现在只给
词形（可分动词 / 强变化 / 复合词），不给「这个词该配哪个介词、支配什么格」。
本工具从**本 App 已有词库**里筛出 VERB/ADJ 逐批问 AI，产出 prep_dict.py。

为什么筛现有词库而不是让 AI 自由产出教材式清单：功能的价值发生在
「用户点文章里的词、抽屉里就有搭配」那一刻。一份不与本词库对齐的自由清单
会大量 miss —— 便宜的是错的东西。

与 build_dict.py 的关系：复用它的 API 配置解析（.env 优先，DB 兜底），
但**缓存目录独立**（tools/raw_prep/）。共用 tools/raw/ 会撞文件名：
两边的缓存键都是 `batch_{索引}`，索引按各自词表位置算，共用即互相覆写。

用法：
  python tools/build_prep.py --dry-run              # 只看目标规模，不调 AI
  python tools/build_prep.py --parallel 6           # 全量生成
  python tools/build_prep.py --resume --parallel 6  # 断点续跑（读 tools/raw_prep/）
  python tools/build_prep.py --reemit               # 纯从缓存重建 prep_dict.py
  python tools/build_prep.py --only bestehen,warten # 试点几个词
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "tools" / "raw_prep"

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from core_dict import CORE_VOCAB_DB  # noqa: E402
from build_dict import _read_api_config  # noqa: E402  复用 .env 优先的配置解析

# ── 目标词筛选 ──────────────────────────────────────────────────────────
TARGET_POS = ("VERB", "ADJ")


def collect_targets() -> Dict[str, str]:
    """从现有词库取 VERB/ADJ → {lemma: pos}。键已是小写（core_dict 全小写）。"""
    return {lemma: entry[1] for lemma, entry in CORE_VOCAB_DB.items()
            if entry[1] in TARGET_POS}


# ── AI 生成 ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """你是德语语法专家，专精 Verben/Adjektive mit Präpositionen（介词搭配）。
我会给你一个德语词元的 JSON 数组。请返回严格 JSON（不要其它文字）：

{"results":[
  {"wort":"bestehen","kollokationen":[
     {"praeposition":"auf","kasus":"Dat","bedeutung_zh":"坚持","beispiel":"Er besteht auf seiner Meinung."},
     {"praeposition":"aus","kasus":"Dat","bedeutung_zh":"由…组成","beispiel":"Das Team besteht aus fünf Personen."}]},
  {"wort":"abholen","kollokationen":[]}
]}

规则：
- 只收录**固定搭配**（Verb/Adjektiv + Präposition 构成语法上固定的支配关系）。
  普通的地点/时间状语（gehen in die Schule）不是固定搭配，不要收。
- 没有固定介词搭配的词，kollokationen 返回空数组 []。**这是正常答案，不要硬凑。**
- 一个词有多个介词且意思不同时，全部列出（bestehen auf/aus/in）。
- kasus ∈ {Akk, Dat, Gen}，必须是该搭配实际支配的格（warten auf + Akk）。
- 反身动词：wort 保持不带 sich 的形式（freuen），在 bedeutung_zh 里标 "(sich)"。
- bedeutung_zh：1-12 字中文，写这个**搭配**的意思，不是词的泛义。
- beispiel：一句完整德语例句，必须真的用上该介词，12-80 字符。
- 数组里每个词都要出现在 results 里（哪怕是空数组）。
- 只输出 JSON。"""

# 介词白名单：AI 会把 "damit"/"dass" 之类的连词或副词当介词返回。
# 白名单是唯一能自动挡住这类幻觉的手段（没有任何权威表可以对照校验）。
_VALID_PREPS = {
    "an", "auf", "aus", "bei", "bis", "durch", "für", "gegen", "gegenüber",
    "hinter", "in", "mit", "nach", "neben", "ohne", "seit", "über", "um",
    "unter", "von", "vor", "zu", "zwischen", "wegen", "trotz", "statt",
    "anstatt", "außer", "dank", "laut", "während", "innerhalb", "entlang",
    "ab", "als", "nächst", "vom", "zum", "zur",
}
_VALID_CASES = {"Akk", "Dat", "Gen"}

# 人工校验的「必考搭配」底盘（floor）。
# 为什么要有：AI 生成是长尾补齐手段，但歌德考试反复考的就这几十条，
# 它们不能取决于某次调用的运气。同一词头以 seed 为准、AI 只补 seed 没有的词——
# 人工校验过的条目不该被一次幻觉降级。
# 格式与生成结果一致：lemma -> ((介词, 格, 中文义, 例句), ...)
SEED_COLLOCATIONS: Dict[str, list] = {
    "achten": [["auf", "Akk", "注意", "Bitte achten Sie auf die Verkehrszeichen."]],
    "anfangen": [["mit", "Dat", "开始做", "Wir fangen mit der Übung an."]],
    "antworten": [["auf", "Akk", "回答", "Er antwortet auf die Frage."]],
    "aufhören": [["mit", "Dat", "停止做", "Er hört mit dem Rauchen auf."]],
    "abhängig": [["von", "Dat", "依赖于", "Der Erfolg ist von vielen Faktoren abhängig."]],
    "ärgern": [["über", "Akk", "(sich)为…生气", "Er ärgert sich über den Fehler."]],
    "bekannt": [["für", "Akk", "因…闻名", "Die Stadt ist für ihre Architektur bekannt."]],
    "beschäftigen": [["mit", "Dat", "(sich)从事/研究", "Ich beschäftige mich mit deutscher Literatur."]],
    "bestehen": [["auf", "Dat", "坚持", "Er besteht auf seiner Meinung."],
                 ["aus", "Dat", "由…组成", "Das Team besteht aus fünf Personen."],
                 ["in", "Dat", "在于", "Die Aufgabe besteht in der Analyse der Daten."]],
    "beteiligen": [["an", "Dat", "(sich)参与", "Er beteiligt sich an der Diskussion."]],
    "bewerben": [["um", "Akk", "(sich)申请职位", "Er bewirbt sich um die Stelle."],
                 ["bei", "Dat", "(sich)向…求职", "Sie bewirbt sich bei einer Bank."]],
    "bereit": [["zu", "Dat", "愿意", "Er ist zu einem Kompromiss bereit."]],
    "bitten": [["um", "Akk", "请求", "Er bittet mich um Hilfe."]],
    "böse": [["auf", "Akk", "生气", "Sie ist böse auf ihn."]],
    "dankbar": [["für", "Akk", "感激", "Ich bin dir für deine Hilfe dankbar."]],
    "denken": [["an", "Akk", "想到", "Ich denke oft an meine Familie."]],
    "einverstanden": [["mit", "Dat", "同意", "Ich bin mit dem Plan einverstanden."]],
    "entschuldigen": [["für", "Akk", "(sich)为…道歉", "Ich entschuldige mich für die Verspätung."],
                      ["bei", "Dat", "(sich)向…道歉", "Er entschuldigt sich bei seinem Chef."]],
    "erinnern": [["an", "Akk", "(sich)记得", "Ich erinnere mich an den Tag."]],
    "fähig": [["zu", "Dat", "有能力", "Er ist zu großen Leistungen fähig."]],
    "freuen": [["auf", "Akk", "(sich)期待", "Ich freue mich auf die Ferien."],
               ["über", "Akk", "(sich)为…高兴", "Sie freut sich über das Geschenk."]],
    "gehören": [["zu", "Dat", "属于", "Dieses Buch gehört zu meiner Sammlung."]],
    "glauben": [["an", "Akk", "相信", "Sie glaubt an den Erfolg."]],
    "gratulieren": [["zu", "Dat", "祝贺", "Wir gratulieren ihr zu ihrem Erfolg."]],
    "gewöhnen": [["an", "Akk", "(sich)习惯于", "Ich gewöhne mich an das Klima."]],
    "helfen": [["bei", "Dat", "帮忙做", "Er hilft mir bei den Hausaufgaben."]],
    "hoffen": [["auf", "Akk", "希望", "Wir hoffen auf besseres Wetter."]],
    "interessieren": [["für", "Akk", "(sich)对…感兴趣", "Er interessiert sich für Politik."]],
    "kümmern": [["um", "Akk", "(sich)照顾", "Sie kümmert sich um die Kinder."]],
    "leiden": [["an", "Dat", "患（病）", "Er leidet an einer Allergie."],
               ["unter", "Dat", "受…之苦", "Sie leidet unter dem Lärm."]],
    "neugierig": [["auf", "Akk", "好奇", "Ich bin neugierig auf das Ergebnis."]],
    "rechnen": [["mit", "Dat", "预计", "Wir rechnen mit Regen."]],
    "schützen": [["vor", "Dat", "保护免受", "Die Creme schützt vor der Sonne."]],
    "sorgen": [["für", "Akk", "照料/负责", "Sie sorgt für ihre kranke Mutter."],
               ["um", "Akk", "(sich)担心", "Ich sorge mich um dich."]],
    "sprechen": [["über", "Akk", "谈论", "Wir sprechen über die Prüfung."],
                 ["mit", "Dat", "与…交谈", "Ich spreche mit dem Lehrer."],
                 ["von", "Dat", "提到", "Sie spricht oft von ihrer Reise."]],
    "stolz": [["auf", "Akk", "为…自豪", "Die Eltern sind stolz auf ihre Tochter."]],
    "teilnehmen": [["an", "Dat", "参加", "Sie nimmt an der Konferenz teil."]],
    "träumen": [["von", "Dat", "梦想", "Sie träumt von einer Weltreise."]],
    "überzeugt": [["von", "Dat", "确信", "Er ist von seiner Idee überzeugt."]],
    "unterhalten": [["über", "Akk", "(sich)聊起", "Wir unterhalten uns über Musik."]],
    "verantwortlich": [["für", "Akk", "对…负责", "Sie ist für das Projekt verantwortlich."]],
    "verlassen": [["auf", "Akk", "(sich)信赖", "Du kannst dich auf mich verlassen."]],
    "verzichten": [["auf", "Akk", "放弃", "Wir verzichten auf den Urlaub."]],
    "vorbereiten": [["auf", "Akk", "(sich)为…做准备", "Ich bereite mich auf die Prüfung vor."]],
    "warten": [["auf", "Akk", "等待", "Ich warte auf den Bus."]],
    "zufrieden": [["mit", "Dat", "满意", "Ich bin mit dem Ergebnis zufrieden."]],
    "zweifeln": [["an", "Dat", "怀疑", "Er zweifelt an seiner Entscheidung."]],
}


def merge_with_seed(collocations: Dict[str, list]) -> Dict[str, list]:
    """seed 覆盖 AI：人工校验过的词头以 seed 为准，AI 只补 seed 没有的词。"""
    merged = dict(collocations)
    merged.update(SEED_COLLOCATIONS)
    return merged


def validate_collocation(item: dict) -> Optional[str]:
    """返回错误信息（合法返回 None）。

    `beispiel` 必须真的含该介词 —— 这是本数据集唯一的自动幻觉检测：
    AI 编出 "warten für" 时往往顺手给一句其实用了 auf 的例句。
    """
    prep = (item.get("praeposition") or "").strip().lower()
    if not prep:
        return "缺 praeposition"
    if prep not in _VALID_PREPS:
        return f"非法介词: {prep!r}"
    if item.get("kasus") not in _VALID_CASES:
        return f"非法 kasus: {item.get('kasus')!r}"
    zh = (item.get("bedeutung_zh") or "").strip()
    if not zh or len(zh) > 20:
        return f"bedeutung_zh 长度异常: {zh!r}"
    example = (item.get("beispiel") or "").strip()
    if not 10 <= len(example) <= 120:
        return f"beispiel 长度异常({len(example)}): {example!r}"
    words = {w.strip(".,!?;:»«\"'").lower() for w in example.split()}
    if prep not in words:
        return f"例句未用上介词 {prep!r}: {example!r}"
    return None


async def call_deepseek_batch(words: List[str], key: str, base: str, model: str) -> List[dict]:
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({"wörter": words}, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{base}/chat/completions", headers=headers, json=body)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
    return json.loads(content).get("results", [])


def _parse_batch(raw_results: List[dict], requested: List[str],
                 verbose: bool = True) -> Tuple[Dict[str, list], List[str]]:
    """AI 原始响应 → (有搭配的词, 明确没有搭配的词)。

    这两者必须分开编码：**「本批失败」和「这些词确实没有搭配」不是一回事**。
    build_dict.py:233 把两者都存成 `[]`，于是重跑时无法区分「已问过、答案是没有」
    与「问失败了、还得再问」，只能整批重付一次钱（AGENTS.md 里的那个坑）。
    """
    asked = {w.lower() for w in requested}
    found: Dict[str, list] = {}
    none: List[str] = []
    for entry in raw_results:
        lemma = (entry.get("wort") or "").strip().lower()  # 键必须小写，否则查词全 miss
        if not lemma or lemma not in asked:
            continue
        items = entry.get("kollokationen") or []
        rows = []
        for item in items:
            err = validate_collocation(item)
            if err:
                if verbose:
                    print(f"[reject] {lemma}: {err}")
                continue
            rows.append([item["praeposition"].strip().lower(), item["kasus"],
                         item["bedeutung_zh"].strip(), item["beispiel"].strip()])
        if rows:
            found[lemma] = rows
        else:
            none.append(lemma)   # 问过了，答案是「没有固定搭配」
    return found, none


def _cache_path(batch: List[str]) -> Path:
    """缓存文件名由**批次内容**决定，不用批次序号。

    序号会撞：`--only a,b` 的第 0 批和全量跑的第 0 批是完全不同的词，
    文件名却都是 batch_0.json；--resume 会把前者当成后者的答案读进来，
    真正的第 0 批词从此永远不会被问（build_dict.py 那个坑的同款，
    只是这次撞的是本工具自己的两次运行）。
    """
    digest = hashlib.sha1(",".join(batch).encode("utf-8")).hexdigest()[:12]
    return RAW_DIR / f"batch_{digest}.json"


async def _generate(words: List[str], args, key: str, base: str,
                    model: str) -> Tuple[Dict[str, list], set]:
    """并发跑所有批次，返回 (搭配表, 已问过的词集合)。"""
    sem = asyncio.Semaphore(max(1, args.parallel))
    collocations: Dict[str, list] = {}
    answered: set = set()
    total = len(words)
    done = 0

    async def process(start: int):
        nonlocal done
        batch = words[start : start + args.batch_size]
        label = f"{start // args.batch_size}"
        cache_path = _cache_path(batch)
        if args.resume and cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            found, none = cached.get("collocations", {}), cached.get("none", [])
        else:
            raw: Optional[List[dict]] = None
            async with sem:
                for attempt in range(4):
                    try:
                        raw = await call_deepseek_batch(batch, key, base, model)
                        break
                    except Exception as e:
                        print(f"[retry] 批 {label} 第 {attempt+1} 次失败: {e}")
                        await asyncio.sleep(2 * (attempt + 1))
            if raw is None:
                # 失败批次**不写缓存**：写了就等于宣称「这些词都没有搭配」，
                # 而 --resume 会信它，缺口从此永久静默。
                print(f"[FAIL] 批 {label} 重试耗尽，不写缓存（下次 --resume 会重跑）")
                done += len(batch)
                return
            found, none = _parse_batch(raw, batch)
            cache_path.write_text(json.dumps(
                {"words": batch, "collocations": found, "none": none},
                ensure_ascii=False), encoding="utf-8")
        collocations.update(found)
        answered.update(found)
        answered.update(none)
        done += len(batch)
        print(f"  进度 {done}/{total}，累计有搭配 {len(collocations)} 词")

    await asyncio.gather(*[process(i) for i in range(0, total, args.batch_size)])
    return collocations, answered


def load_cache() -> Tuple[Dict[str, list], set]:
    """读全部缓存 → (搭配表, 已问过的词)。缺失的文件即「还没问过」。"""
    collocations: Dict[str, list] = {}
    answered: set = set()
    for path in sorted(RAW_DIR.glob("batch_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        found = data.get("collocations", {})
        collocations.update(found)
        answered.update(found)
        answered.update(data.get("none", []))
    return collocations, answered


# ── 产出模块 ────────────────────────────────────────────────────────────
def guard_regression(final: Dict[str, list], force: bool) -> None:
    """产出前拦住「越写越少」。

    2026-08-20 实遇：key 过期 → 全批 401 → 脚本仍照常写出一个 0 词条的
    prep_dict.py，把已有数据集整包抹掉。写出比不写更危险，因为它看起来成功了。
    """
    existing = REPO_ROOT / "prep_dict.py"
    if not existing.exists() or force:
        return
    try:
        import importlib
        sys.path.insert(0, str(REPO_ROOT))
        old = importlib.import_module("prep_dict").PREP_COLLOCATIONS
    except Exception:
        return
    if len(final) < len(old):
        raise SystemExit(
            f"[abort] 新结果 {len(final)} 词条少于现有 {len(old)} 词条，"
            "疑似部分批次失败。先 --resume 补齐，或确认要覆盖请加 --force")


def emit_module(collocations: Dict[str, list], answered_count: int) -> Path:
    """生成 prep_dict.py。位置元组惯例照 core_dict_ext.py。"""
    total_rows = sum(len(v) for v in collocations.values())
    lines = [
        "# -*- coding: utf-8 -*-",
        '"""AI 批量生成的德语动词/形容词固定介词搭配表（auto-generated）。',
        "",
        "Schema: lemma -> ((介词, 格, 中文义, 例句), ...)",
        "值是**元组的元组**：一个词头可带多个介词且意思不同",
        "（bestehen auf 坚持 / aus 由…组成 / in 在于），单值会丢义项。",
        "",
        "键全小写、反身动词不带 sich（freuen 而非 sich freuen），",
        "以便直接匹配 spaCy 的 lemma 输出。",
        "手动改会丢：必考搭配请改 tools/build_prep.py 的 SEED_COLLOCATIONS，",
        "长尾靠 AI 生成，两者由 tools/build_prep.py 合并（seed 优先）。",
        '"""',
        "",
        f"PREP_COLLOCATIONS = {{  # {len(collocations)} 词条 / {total_rows} 条搭配"
        f" · 已问过 {answered_count} 词 · seed {len(SEED_COLLOCATIONS)} 词 + AI 长尾",
    ]
    for lemma in sorted(collocations):
        rows = collocations[lemma]
        rendered = ", ".join(
            "({}, {}, {}, {})".format(*(json.dumps(c, ensure_ascii=False) for c in row))
            for row in rows)
        # 单元素元组要留逗号，否则退化成普通括号
        if len(rows) == 1:
            rendered += ","
        lines.append(f'    {json.dumps(lemma, ensure_ascii=False)}: ({rendered}),')
    lines.append("}")
    lines.append("")
    out = REPO_ROOT / "prep_dict.py"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def qa_spotcheck(collocations: Dict[str, list]) -> None:
    """定向抽查：这几个词的搭配是德语课本必考项，错了立刻看得出来。"""
    targeted = {
        "warten": "auf", "bestehen": "auf", "freuen": "auf", "denken": "an",
        "helfen": "bei", "teilnehmen": "an", "gehören": "zu", "stolz": "auf",
        "zufrieden": "mit", "abhängig": "von", "interessieren": "für",
        "sorgen": "für", "bitten": "um", "sprechen": "über",
    }
    print("\n=== QA 定向抽查 ===")
    hit = 0
    for lemma, expect in targeted.items():
        rows = collocations.get(lemma)
        if not rows:
            print(f"  {lemma:16s} —— 缺（期望有 {expect}）")
            continue
        preps = [r[0] for r in rows]
        ok = expect in preps
        hit += ok
        origin = "seed" if lemma in SEED_COLLOCATIONS else "AI"
        print(f"  {lemma:16s} {'✓' if ok else '✗'} [{origin}] {preps} 期望含 {expect}")
        for r in rows:
            print(f"      {r[0]:10s} {r[1]:4s} {r[2]:12s} {r[3]}")
    print(f"\n定向命中 {hit}/{len(targeted)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="生成介词搭配数据集 prep_dict.py")
    parser.add_argument("--dry-run", action="store_true", help="只看目标规模，不调 AI")
    parser.add_argument("--limit", type=int, default=0, help="目标词上限（0=全部）")
    parser.add_argument("--batch-size", type=int, default=25, help="每批词数")
    parser.add_argument("--parallel", type=int, default=1,
                        help="并发路数（建议 4-8；太大会触发 DeepSeek 429）")
    parser.add_argument("--resume", action="store_true", help="断点续跑（读 tools/raw_prep/）")
    parser.add_argument("--only", type=str, default="", help="只跑指定词（逗号分隔）")
    parser.add_argument("--reemit", action="store_true", help="纯从缓存重建 prep_dict.py")
    parser.add_argument("--force", action="store_true",
                        help="允许写出比现有更少（含 0）词条的模块，用于确认要清空时")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    targets = collect_targets()
    print(f"词库 VERB+ADJ 共 {len(targets)} 词"
          f"（VERB {sum(1 for p in targets.values() if p == 'VERB')} /"
          f" ADJ {sum(1 for p in targets.values() if p == 'ADJ')}）")

    if args.reemit:
        collocations, answered = load_cache()
        final = merge_with_seed(collocations)
        guard_regression(final, args.force)
        out = emit_module(final, len(answered | set(SEED_COLLOCATIONS)))
        print(f"[reemit] 缓存里 {len(answered)} 词已问过，其中 {len(collocations)} 词有搭配；"
              f"并入人工 seed {len(SEED_COLLOCATIONS)} 词 → 共 {len(final)} 词条")
        print(f"[reemit] 已写出 {out} ({out.stat().st_size / 1024:.0f} KB)")
        print(f"[reemit] 词库里仍未问过 {len(set(targets) - answered)} 词")
        qa_spotcheck(final)
        return

    words = sorted(targets)
    if args.only:
        only = {w.strip().lower() for w in args.only.split(",") if w.strip()}
        words = [w for w in words if w in only]
        print(f"--only 过滤后 {len(words)} 词")
    if args.limit:
        words = words[: args.limit]

    if args.resume:
        _, already = load_cache()
        before = len(words)
        words = [w for w in words if w not in already]
        print(f"--resume：缓存已覆盖 {before - len(words)} 词，还剩 {len(words)} 词要问")

    print(f"待生成 {len(words)} 词，batch={args.batch_size}，并行={args.parallel}，"
          f"约 {max(1, (len(words) + args.batch_size - 1) // args.batch_size)} 次调用")
    if args.dry_run:
        print("=== dry-run 结束（未调 AI）===")
        return

    key, base, model = _read_api_config()
    asyncio.run(_generate(words, args, key, base, model))

    # 从缓存整体重建：--resume 时新旧批次都要进最终模块
    collocations, answered = load_cache()
    if words and not answered and not args.force:
        raise SystemExit("[abort] 本次全部批次都失败（key 失效？断网？），"
                         "未改动 prep_dict.py。修好后重跑即可（缓存没被污染）")
    final = merge_with_seed(collocations)
    guard_regression(final, args.force)
    out = emit_module(final, len(answered | set(SEED_COLLOCATIONS)))
    rows = sum(len(v) for v in final.values())
    print(f"\n共 {len(answered)} 词已问过，AI 给出 {len(collocations)} 词有搭配；"
          f"并入 seed 后 {len(final)} 词条 / {rows} 条搭配")
    print(f"已写出 {out} ({out.stat().st_size / 1024:.0f} KB)")
    qa_spotcheck(final)


if __name__ == "__main__":
    main()
