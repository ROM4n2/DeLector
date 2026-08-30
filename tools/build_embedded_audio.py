"""
tools/build_embedded_audio.py — 预生成 EMBEDDED_AUDIO 嵌入音频词表

从歌德 A1→B2 核心词库按 CEFR 顺序取 top-N 词，调用 edge-tts 批量生成 MP3，
base64 编码后写出 workbench.html 的 EMBEDDED_AUDIO 替换片段。

用法：
  # 仅列词，不生成音频（CI/测试用）
  python tools/build_embedded_audio.py --dry-run

  # 生成 top-300 词，直接原地更新 workbench.html 里的 EMBEDDED_AUDIO = {} 占位符
  python tools/build_embedded_audio.py --top 300 --patch

注意事项：
  - 每个 MP3 约 20-50KB，300 词约 6-15MB base64（APK 体积代价）
  - edge-tts 需联网（speech.platform.bing.com）；离线机器用 --dry-run
  - 生成的词典键全部小写（与 CORE_VOCAB_DB 一致）
  - workbench.html 的查词路径已归一为 word.toLowerCase()
  - tools/raw_embedded/ 已加 .gitignore，缓存不提交
"""
import argparse
import asyncio
import base64
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
WORKBENCH = ROOT / "static" / "german" / "workbench.html"
CACHE_DIR = ROOT / "tools" / "raw_embedded"

CEFR_ORDER = {"A1": 0, "A2": 1, "B1": 2, "B2": 3}
TTS_VOICE = "de-DE-KatjaNeural"


def _get_ordered_words(top: int) -> list:
    sys.path.insert(0, str(ROOT))
    from core_dict import CORE_VOCAB_DB

    SKIP_POS = {"PREP", "CONJ", "ART", "PRON", "PART", "INT", "NUM", "INTERJ"}
    words = []
    for key, entry in CORE_VOCAB_DB.items():
        cefr, pos = entry[0], entry[1]
        if pos in SKIP_POS:
            continue
        if any(c in key for c in ("-", "(", " ")):
            continue
        words.append((CEFR_ORDER.get(cefr, 99), key))

    words.sort(key=lambda x: (x[0], x[1]))
    return [w for _, w in words[:top]]


async def _generate_one(word: str, out_path: Path):
    if out_path.exists():
        return out_path.read_bytes()
    try:
        import edge_tts
    except ImportError:
        print(f"[WARN] edge-tts 未安装，跳过 {word}", file=sys.stderr)
        return None
    try:
        communicate = edge_tts.Communicate(word, TTS_VOICE, rate="-10%")
        chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        if not chunks:
            return None
        data = b"".join(chunks)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)
        return data
    except Exception as e:
        print(f"[WARN] edge-tts 失败 {word}: {e}", file=sys.stderr)
        return None


def _patch_workbench(audio_dict: dict) -> None:
    src = WORKBENCH.read_text(encoding="utf-8")
    pattern = r"const EMBEDDED_AUDIO\s*=\s*\{[^}]*\};"
    replacement_body = json.dumps(audio_dict, ensure_ascii=False, indent=2)
    new_decl = f"const EMBEDDED_AUDIO = {replacement_body};"
    new_src, n = re.subn(pattern, new_decl, src, count=1, flags=re.DOTALL)
    if n == 0:
        print("[ERROR] workbench.html 里找不到 const EMBEDDED_AUDIO = {...};", file=sys.stderr)
        sys.exit(1)
    WORKBENCH.write_text(new_src, encoding="utf-8")
    print(f"[OK] 已更新 workbench.html：{len(audio_dict)} 词嵌入", file=sys.stderr)


async def _main_async(args: argparse.Namespace) -> None:
    words = _get_ordered_words(args.top)
    print(f"[INFO] 词表：{len(words)} 词（top {args.top}，CEFR A1→B2）", file=sys.stderr)

    if args.dry_run:
        for i, w in enumerate(words):
            print(f"  {i+1:>4}. {w}")
        print(f"\n共 {len(words)} 词（--dry-run，未生成音频）", file=sys.stderr)
        return

    audio_dict = {}
    for i, word in enumerate(words):
        out_path = CACHE_DIR / f"{word}.mp3"
        data = await _generate_one(word, out_path)
        if data:
            audio_dict[word] = base64.b64encode(data).decode("ascii")
            print(f"  [{i+1}/{len(words)}] {word}: {len(data)} bytes", file=sys.stderr)
        else:
            print(f"  [{i+1}/{len(words)}] {word}: 跳过", file=sys.stderr)

    if args.patch:
        _patch_workbench(audio_dict)
    elif args.out:
        out_js = f"const EMBEDDED_AUDIO = {json.dumps(audio_dict, ensure_ascii=False, indent=2)};\n"
        Path(args.out).write_text(out_js, encoding="utf-8")
    else:
        print(json.dumps(audio_dict, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="预生成 EMBEDDED_AUDIO 嵌入音频词表")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅列词，不调用 edge-tts（CI/测试无需联网）")
    parser.add_argument("--top", type=int, default=300, metavar="N",
                        help="取 CEFR A1→B2 顺序前 N 词（默认 300）")
    parser.add_argument("--patch", action="store_true",
                        help="直接原地更新 workbench.html 的 EMBEDDED_AUDIO 声明")
    parser.add_argument("--out", metavar="FILE",
                        help="输出 JS 片段到文件（不指定则写 stdout）")
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
