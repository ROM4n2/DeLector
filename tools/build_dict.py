#!/usr/bin/env python
"""一次性构建工具：把歌德 A1-B2 词表扩成带中文释义的离线词库模块。

为什么存在：core_dict.py 只有 443 词条，覆盖面太薄；且查词链没做词形还原，
表面形（geht/Häuser/trinke）大量查不到。本工具：
  1. 抓取并规范化歌德词表源（B1 原始形 / A2 词元 / B2 CSV）
  2. 与现有 core_dict(443) + LINGUISTICS_VOCAB_EXT(~200) 去重
  3. 用 DeepSeek（真 key，从 .env / 环境变量读，绝不硬编码）批量生成中文释义
  4. 校验 schema，产出 core_dict_ext.py（Python dict 字面量，Chaquopy 可导入）

为什么落地成 .py 而非 JSON：Android Chaquopy extract_packages 为空，运行时
open() 数据文件会失败；.py 模块按 import 链正常打包（PyInstaller 自动分析，
CI 把 .py 拷进 android/app/src/main/python）。本工具只在 dev/CI 跑，不进运行时。

用法：
  python tools/build_dict.py --dry-run            # 只看源统计和目标清单规模，不调 AI
  python tools/build_dict.py --limit 3000         # 全量生成（默认 3000）
  python tools/build_dict.py --resume             # 断点续跑（读 tools/raw/ 缓存）
  python tools/build_dict.py --only geht,Häuser   # 只生成指定词（试点/补缺）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "tools" / "data"
RAW_DIR = REPO_ROOT / "tools" / "raw"

# 从现有词库 import 出已覆盖的词元，构建工具要排除它们（只补缺口）
sys.path.insert(0, str(REPO_ROOT))
from core_dict import CORE_VOCAB_DB  # noqa: E402
from linguistics import LINGUISTICS_VOCAB_EXT  # noqa: E402

# ── 词表源定义 ──────────────────────────────────────────────────────────
SOURCE_FILES = {
    "b1": DATA_DIR / "b1_sorted.txt",   # 2833 行原始表面形（含变位/冠词/复数）
    "a2": DATA_DIR / "a2_words.txt",    # 1215 词元（langfield 仓库 .md 文件名）
    "b2": DATA_DIR / "b2_all.csv",      # 1924 行 German,English（德国词在第 0 列）
}

# ── 规范化规则 ──────────────────────────────────────────────────────────
_TOKEN_RE = re.compile(r"^[a-zäöüß][a-zäöüß-]*$")
_ARTICLES = ("der ", "die ", "das ", "den ", "dem ", "des ")
_DROP_TAIL = re.compile(r"\((?:Pl\.?|Sg\.?)\)|!", re.I)


def _normalize_b1_line(line: str) -> Optional[str]:
    """B1 原始形 → 词元候选。逐条规则见下，丢弃返回 None。

    处理：剥括号注释（(Pl.)/(!) 等）→ 取逗号前首字段 → 剥冠词 → 丢弃含空格
    的多词短语 → 丢弃 `-` 后缀标记（ein-）→ 正则白名单。变位动词行（können, kann, ...）
    首字段即不定式，天然正确。"""
    line = line.strip()
    if not line:
        return None
    # 剥行内括号（如 "(hat können als Modalverb)"）
    line = _DROP_TAIL.sub("", line).strip()
    # 取逗号前首字段（变位列表取不定式）
    head = line.split(",")[0].strip()
    if not head:
        return None
    # 剥冠词
    lower = head.lower()
    for art in _ARTICLES:
        if lower.startswith(art):
            head = head[len(art):].strip()
            lower = head.lower()
            break
    # 丢弃带空格的多词短语（abgesehen davon）
    if " " in head or " " in lower:
        return None
    # 丢弃 `-` 后缀标记（ein- → 丢）、纯符号
    if head.endswith("-") or head.startswith("-"):
        return None
    if not _TOKEN_RE.match(lower):
        return None
    # 丢弃纯功能词/虚词（已由 AI 分级，但词表源里不应有标点符号类）
    return lower


def _normalize_a2(word: str) -> Optional[str]:
    """A2 源是 .md 文件名，本身已是词元。仍过一遍白名单防脏。"""
    w = word.strip().lower()
    return w if _TOKEN_RE.match(w) else None


def _normalize_b2(line: str) -> Optional[str]:
    """B2 CSV：取第 0 列德语词，单 token 保留。"""
    parts = line.split(",")
    if len(parts) < 1:
        return None
    w = parts[0].strip().lower()
    if " " in w:  # 多词短语（abgesehen davon）丢弃
        return None
    return w if _TOKEN_RE.match(w) else None


def collect_candidates() -> Dict[str, str]:
    """收集并规范化所有源 → {lemma: source}。"""
    candidates: Dict[str, str] = {}
    for key, path in SOURCE_FILES.items():
        if not path.exists():
            print(f"[skip] {key} 源缺失: {path}")
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                lemma = (_normalize_b1_line(line) if key == "b1"
                         else _normalize_a2(line) if key == "a2"
                         else _normalize_b2(line))
                if lemma:
                    candidates.setdefault(lemma, key)
    return candidates


def exclude_existing(candidates: Dict[str, str]) -> Dict[str, str]:
    """剔除已在现有词库的词元（只补缺口）。"""
    existing = set(CORE_VOCAB_DB.keys()) | set(
        k.lower() for k in LINGUISTICS_VOCAB_EXT.keys())
    return {k: v for k, v in candidates.items() if k not in existing}


# ── DeepSeek 批量生成 ───────────────────────────────────────────────────
SYSTEM_PROMPT = """你是一位德语-中文词典编纂专家。我会给你一个德语单词的 JSON 数组。
请为每个词返回严格 JSON（不要其它文字）：

{"results":[{"wort":"gehen","cefr":"A1","pos":"VERB","gender":null,"plural":null,"definition_zh":"去，走"}]}

字段规则：
- cefr ∈ {A1,A2,B1,B2,C1}，按歌德欧标难度判断
- pos ∈ {NOUN,VERB,ADJ,ADV,PRON,PREP,CONJ,INTERJ,NUM}
- 名词必须给 gender(Masc/Fem/Neut) 和 plural（如 "-e"、"-en"、"-..er"、不可数"-"，拿不准给 null）；非名词 gender/plural 一律 null
- definition_zh：1-12 字简明中文释义，多义项用 "/" 分隔
- 只输出 JSON，不要任何解释"""


def _read_db_setting(key: str, default: str = "") -> str:
    """读 app_settings 表（与运行时 get_effective_api_key 同源）。

    为什么读 DB：get_setting 是 DB 优先、env 兜底，settings 弹窗存的真 key
    在 DB 里，而 .env 里可能留着一个失效旧 key（2026-08-19 实遇 401）。
    不 import server.py 避免触发模块顶层 init_db 的副作用。"""
    try:
        import sqlite3
        db_path = REPO_ROOT / "delector.db"
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
            if row and row[0]:
                return row[0]
    except Exception:
        pass
    return default


def _read_api_config() -> Tuple[str, str, str]:
    """读 key/base_url/model：.env/环境变量优先（用户维护的权威源），DB 兜底。

    为什么不是 DB 优先：2026-08-19 用户撤销旧 key 后只在 .env 加了新 key，
    app_settings 表里还留着被撤销的旧 key，DB 优先会拿到失效值（401）。
    本工具以 .env 为准。"""
    env = {}
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    key = os.environ.get("DEEPSEEK_API_KEY") or env.get("DEEPSEEK_API_KEY") or _read_db_setting("DEEPSEEK_API_KEY", "")
    base = os.environ.get("DEEPSEEK_API_BASE_URL") or env.get("DEEPSEEK_API_BASE_URL") or _read_db_setting("API_BASE_URL", "https://api.deepseek.com")
    model = os.environ.get("DEEPSEEK_API_MODEL") or env.get("DEEPSEEK_API_MODEL") or _read_db_setting("API_MODEL", "deepseek-v4-flash")
    if not key:
        raise SystemExit("未找到 DEEPSEEK_API_KEY（.env / 环境变量 / DB），无法生成释义")
    return key, base, model


async def call_deepseek_batch(words: List[str], key: str, base: str, model: str) -> List[dict]:
    """一次调用生成一批词的释义。返回 [{wort, cefr, pos, gender, plural, definition_zh}]。"""
    payload = {"wörter": words}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{base}/chat/completions", headers=headers, json=body)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    return parsed.get("results", [])


async def _generate_parallel(words: List[str], args, key: str, base: str, model: str) -> List[dict]:
    """并发处理所有批次。复用 tools/raw/ 缓存（断点续跑不重付钱）。"""
    sem = asyncio.Semaphore(max(1, args.parallel))
    entries: List[dict] = []
    seen: set = set()
    total = len(words)
    done = 0

    async def process(start: int):
        nonlocal done
        batch = words[start : start + args.batch_size]
        batch_index = start // args.batch_size
        cache_path = RAW_DIR / f"batch_{batch_index}.json"
        if args.resume and cache_path.exists():
            batch_entries = json.loads(cache_path.read_text(encoding="utf-8"))
        else:
            batch_entries = []
            failed = False
            async with sem:
                for attempt in range(4):
                    try:
                        batch_entries = await call_deepseek_batch(batch, key, base, model)
                        break
                    except Exception as e:
                        print(f"[retry] 批 {batch_index} 第 {attempt+1} 次失败: {e}")
                        await asyncio.sleep(2 * (attempt + 1))
                else:
                    failed = True
                    print(f"[FAIL] 批 {batch_index} 重试耗尽，跳过")
            # 失败批次不写缓存：空数组会被 --resume 当成「这批已问过、AI 什么都没给」，
            # 于是缺口永久静默。不写文件才能让下次 --resume 重跑这批。
            if not failed:
                cache_path.write_text(json.dumps(batch_entries, ensure_ascii=False), encoding="utf-8")
        for entry in batch_entries:
            # 键统一小写：AI 返回德语名词大写（Kerze），而查词链按小写查（core_dict 全是小写键），
            # 不归一化的话生成词永远查不到（2026-08-19 实测 3862 键里 238 个大写全 miss）
            if entry.get("wort"):
                entry["wort"] = entry["wort"].strip().lower()
            err = validate_entry(entry)
            if err:
                print(f"[reject] {entry.get('wort')}: {err}")
                continue
            if entry["wort"] not in seen:
                entries.append(entry)
                seen.add(entry["wort"])
        done += len(batch)
        if done % (args.batch_size * args.parallel) < args.batch_size or done >= total:
            print(f"  进度 {done}/{total}，累计有效 {len(entries)}")

    tasks = [process(i) for i in range(0, total, args.batch_size)]
    await asyncio.gather(*tasks)

    # 缺词自动补生成：AI 批量响应不保证返回全部请求词，漏的单独再跑一轮（最多 3 轮）
    for pass_no in range(1, 4):
        requested = set(words)
        missing = sorted(requested - seen)
        if not missing:
            break
        print(f"[refill] 第 {pass_no} 轮补 {len(missing)} 个缺词…")
        for m in missing:
            for attempt in range(3):
                try:
                    async with sem:
                        batch_entries = await call_deepseek_batch([m], key, base, model)
                    for entry in batch_entries:
                        if entry.get("wort"):
                            entry["wort"] = entry["wort"].strip().lower()
                        err = validate_entry(entry)
                        if err or entry["wort"] != m:
                            continue
                        if entry["wort"] not in seen:
                            entries.append(entry)
                            seen.add(entry["wort"])
                    break
                except Exception as e:
                    print(f"[refill-retry] {m} 第 {attempt+1} 次失败: {e}")
                    await asyncio.sleep(2 * (attempt + 1))
        else:
            print(f"[refill] 第 {pass_no} 轮后仍有 {len(sorted(set(words) - seen))} 个缺词（AI 拒绝/一直失败）")

    return entries


# ── schema 校验 ─────────────────────────────────────────────────────────
_VALID_CEFR = {"A1", "A2", "B1", "B2", "C1"}
_CEFR_ORDER = ("A1", "A2", "B1", "B2", "C1")
_VALID_POS = {"NOUN", "VERB", "ADJ", "ADV", "PRON", "PREP", "CONJ", "INTERJ", "NUM"}


def validate_entry(entry: dict) -> Optional[str]:
    """返回错误信息（合法返回 None）。"""
    if not entry.get("wort"):
        return "缺 wort"
    if entry.get("cefr") not in _VALID_CEFR:
        return f"非法 cefr: {entry.get('cefr')}"
    if entry.get("pos") not in _VALID_POS:
        return f"非法 pos: {entry.get('pos')}"
    if not entry.get("definition_zh"):
        return "缺 definition_zh"
    if entry["pos"] == "NOUN":
        if entry.get("gender") not in {"Masc", "Fem", "Neut"}:
            return f"名词缺合法 gender: {entry.get('gender')}"
        if not entry.get("plural"):
            return "名词缺 plural"
    return None


def emit_module(entries: List[dict], sources: Dict[str, str]) -> Path:
    """生成 core_dict_ext.py（按 cefr 再按词元排序）。返回输出路径。"""
    entries.sort(key=lambda e: (_CEFR_ORDER.index(e["cefr"]), e["wort"]))
    src_names = ",".join(sorted(set(sources.values())))
    lines = [
        "# -*- coding: utf-8 -*-",
        '"""AI 批量生成的歌德 A1-B2 离线中文词库扩展（auto-generated）。',
        "",
        "Schema: lemma -> (cefr, pos, gender, plural, definition_zh)",
        "用法: core_dict.py 模块底部合并进 CORE_VOCAB_DB。",
        "手动改会丢，改源后重跑 tools/build_dict.py。",
        '"""',
        "",
        f"CORE_VOCAB_EXT = {{  # {len(entries)} 词条 · 来源 {src_names} · cefr 由 AI 分级",
    ]
    for e in entries:
        w = e["wort"]
        cefr = e["cefr"]
        pos = e["pos"]
        gender = e.get("gender") or "None"
        plural = e.get("plural") or ""
        definition = e["definition_zh"].replace('"', "'")
        lines.append(f'    "{w}": ("{cefr}", "{pos}", "{gender}", "{plural}", "{definition}"),')
    lines.append("}")
    lines.append("")
    out = REPO_ROOT / "core_dict_ext.py"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def qa_spotcheck(entries: List[dict]) -> None:
    """QA 抽查：30 随机 + 10 定向。"""
    import random
    picked = random.sample(entries, min(30, len(entries)))
    targeted = ["gehen", "häuser", "ist", "trinke", "besser", "klimaschutz",
                "umwelt", "abenteuer", "abbiegen", "abschließen"]
    seen = set()
    print("\n=== QA 抽查（随机 30）===")
    for e in picked:
        print(f"  {e['wort']:20s} {e['cefr']} {e['pos']:5s} {e.get('gender') or '-':5s} {e.get('plural') or '-':4s} {e['definition_zh']}")
        seen.add(e["wort"])
    print("\n=== QA 抽查（定向 10）===")
    for w in targeted:
        e = next((x for x in entries if x["wort"] == w), None)
        if e:
            print(f"  {e['wort']:20s} {e['cefr']} {e['pos']:5s} {e.get('gender') or '-':5s} {e.get('plural') or '-':4s} {e['definition_zh']}")
            seen.add(w)
    print(f"\n覆盖定向 {len([w for w in targeted if w in seen])}/{len(targeted)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="扩词库：歌德词表 → AI 中文释义 → core_dict_ext.py")
    parser.add_argument("--dry-run", action="store_true", help="只看源统计/目标清单，不调 AI")
    parser.add_argument("--limit", type=int, default=3000, help="生成词条上限")
    parser.add_argument("--batch-size", type=int, default=25, help="每批调用词数")
    parser.add_argument("--resume", action="store_true", help="断点续跑（读 tools/raw/ 缓存）")
    parser.add_argument("--only", type=str, default="", help="只生成指定词（逗号分隔），试点用")
    parser.add_argument("--parallel", type=int, default=1,
                        help="并发路数（纯 I/O 任务，建议 4-8；太大可能触发 DeepSeek 429 限流）")
    parser.add_argument("--reemit", action="store_true",
                        help="纯从 tools/raw/ 缓存重建 core_dict_ext.py（键小写归一化），不调 AI")
    parser.add_argument("--refill", action="store_true",
                        help="只补生成仍缺的词（合并进现有 core_dict_ext.py，不整包重来）")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    candidates = collect_candidates()
    print(f"候选（未去重）: {len(candidates)} 词")
    targets = exclude_existing(candidates)
    print(f"剔除已有词库后待生成: {len(targets)} 词（现有 core_dict={len(CORE_VOCAB_DB)}, EXT={len(LINGUISTICS_VOCAB_EXT)}）")

    if args.only:
        only = {w.strip().lower() for w in args.only.split(",") if w.strip()}
        targets = {k: v for k, v in targets.items() if k in only}
        print(f"--only 过滤后: {len(targets)} 词")

    if args.dry_run:
        print("\n=== dry-run 结束（未调 AI）===")
        return

    if args.reemit:
        entries: List[dict] = []
        seen: set = set()
        for path in sorted(RAW_DIR.glob("batch_*.json")):
            for entry in json.loads(path.read_text(encoding="utf-8")):
                if entry.get("wort"):
                    entry["wort"] = entry["wort"].strip().lower()
                err = validate_entry(entry)
                if err or entry["wort"] in seen:
                    continue
                entries.append(entry)
                seen.add(entry["wort"])
        out = emit_module(entries, {})
        missing = sorted(set(collect_candidates().keys()) - seen)
        print(f"\n[reemit] 从 {len(list(RAW_DIR.glob('batch_*.json')))} 个缓存重建 {len(entries)} 词")
        print(f"[reemit] 已写出: {out} ({out.stat().st_size / 1024:.0f} KB)")
        print(f"[reemit] 源词表中仍缺 {len(missing)} 词（AI 从未返回）: {missing[:25]}…")
        return

    if args.refill:
        key, base, model = _read_api_config()
        words = sorted(targets.keys())
        print(f"[refill] 补生成 {len(words)} 个缺词，并行 {args.parallel}…")
        entries = asyncio.run(_generate_parallel(words, args, key, base, model))
        # 合并现有 core_dict_ext + 新补的词，整体重新 emit（不整包重来，只增缺）
        from core_dict_ext import CORE_VOCAB_EXT as EXISTING
        merged: List[dict] = []
        for k, t in EXISTING.items():
            merged.append({"wort": k, "cefr": t[0], "pos": t[1],
                           "gender": t[2], "plural": t[3] or "", "definition_zh": t[4]})
        seen = {e["wort"] for e in merged}
        for e in entries:
            if e["wort"] not in seen:
                merged.append(e)
                seen.add(e["wort"])
        out = emit_module(merged, targets)
        print(f"[refill] 补成 {len(entries)}/{len(words)}，合并后共 {len(merged)} 词，已写出 {out}")
        return

    key, base, model = _read_api_config()
    words = list(targets.keys())
    if args.limit:
        words = words[: args.limit]
    print(f"开始生成 {len(words)} 词，batch={args.batch_size}，并行={args.parallel}，"
          f"约 {max(1, len(words)//args.batch_size)} 次调用")

    entries = asyncio.run(_generate_parallel(words, args, key, base, model))

    # 与现有词库合并后总体覆盖统计（生成词去重后）
    merged = dict(CORE_VOCAB_DB)
    for e in entries:
        merged.setdefault(e["wort"], None)
    print(f"\n生成有效 {len(entries)} 词，合并后总词元 {len(merged)}")

    out = emit_module(entries, targets)
    print(f"已写出: {out} ({out.stat().st_size / 1024:.0f} KB)")
    qa_spotcheck(entries)

    # smoke：合并后能查到
    sys.path.insert(0, str(REPO_ROOT))
    import importlib
    import core_dict
    importlib.reload(core_dict)
    for w in ("gehen", "haus", "trinken", "klimaschutz"):
        print(f"smoke lookup_core_vocab({w!r}) ->", bool(core_dict.lookup_core_vocab(w)))


if __name__ == "__main__":
    main()
