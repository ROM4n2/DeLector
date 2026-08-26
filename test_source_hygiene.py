# -*- coding: utf-8 -*-
"""源码卫生棘轮：dict 字面量里重复的键。

为什么值得单独一个文件：这类问题**不报错、不改变外观、还会静默改变行为**，
唯一能发现它的途径是有人恰好去跑一次静态检查。而 AGENTS.md 记的静态检查命令
只扫 `server.py syntax_tree.py start.py` —— `linguistics.py` 不在里面，所以
它的 14 条重复键告警从产生到被发现隔了整整 7 个版本（v4.4.1 修，v4.4.8 才注意到）。
把它变成 pytest 里的一条断言，就不用再依赖"有人记得手动跑 pyflakes 加上正确的文件名"。

用 ast 而不是调 pyflakes 子进程：零外部依赖、不受 CI 是否装了 pyflakes 影响，
而且能自己决定扫哪些目录、报出行号。
"""
import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent

# 不扫的目录：第三方代码与构建产物里的重复键不是我们能修的
_SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", "node_modules",
    "build", "dist", ".pytest_cache", ".mypy_cache", ".claude",
}


def _project_py_files():
    for path in sorted(ROOT.rglob("*.py")):
        if _SKIP_DIRS.isdisjoint(path.relative_to(ROOT).parts):
            yield path


def _duplicate_keys(path):
    """返回 [(行号, 键, 次数, 值是否全都相同), ...]。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:                       # 语法坏了是另一回事，交给别的测试报
        raise AssertionError(f"{path} 解析失败：{exc}") from exc

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        # key 为 None 表示 `**other` 展开；计算出来的键（f-string、变量）
        # 静态看不出重不重，一律跳过 —— 这个棘轮只管字面量常量键。
        literal = [
            (k.value, v) for k, v in zip(node.keys, node.values)
            if isinstance(k, ast.Constant) and isinstance(k.value, (str, int))
            and not isinstance(k.value, bool)
        ]
        counts = Counter(k for k, _ in literal)
        for key, n in counts.items():
            if n < 2:
                continue
            dumps = {ast.dump(v) for k, v in literal if k == key}
            found.append((node.lineno, key, n, len(dumps) == 1))
    return found


def test_no_duplicate_keys_in_any_dict_literal():
    """dict 字面量里重复的键 —— 后写的静默胜出，前面那份定义直接消失。

    这是个棘轮：现在全仓库为 0，新增任何一条都会让这里变红。

    `linguistics.py` 就栽在这上面：`LINGUISTICS_VOCAB_EXT`（`849-1056` 行）内部
    有两个注释分隔的块各写了 `klima`/`schutz`/`wandel`/`wachstum`/`modell`/
    `bund`/`regierung` 一遍，值还不一样。**因为 dict 后写的胜，实际生效的是后一块
    （释义更简的那份），前一块更完整的释义被静默丢掉** —— 渲染正常、测试全绿、
    没有任何告警会浮到眼前。

    值相同的重复也一并报：它此刻无害，但下一个人只改其中一份就会变成上面那种情形。
    """
    offenders = []
    for path in _project_py_files():
        for lineno, key, n, same_value in _duplicate_keys(path):
            rel = path.relative_to(ROOT).as_posix()
            kind = "值相同" if same_value else "值不同，后写的胜"
            offenders.append(f"  {rel}:{lineno} 键 {key!r} 出现 {n} 次（{kind}）")

    assert not offenders, (
        "dict 字面量里有重复的键，后写的会静默覆盖前面的定义：\n"
        + "\n".join(offenders)
    )


def test_linguistics_vocab_ext_dedup_kept_the_fuller_glosses():
    """钉住 v4.4.1(`bba1b65`) 去重后**实际生效**的那份值。

    那次清理删的是后写的那块，所以是"让前一块开始生效"，不是纯 lint 修复——
    它改了运行时行为。多数键只是释义变长，但 `wachstum` 的 CEFR 跟着从
    **B1 翻成 B2**，而当时没有任何测试覆盖这个翻转，等于无人知晓地改了难度分级。

    这里钉的是 CEFR 和词性/词性属性，不钉释义文字（释义还会正常润色，
    钉了只会变成每次改文案都要来改测试的噪音）。
    """
    from linguistics import LINGUISTICS_VOCAB_EXT as EXT

    expected = {
        "klima":     ("A2", "NOUN", "Neut"),
        "schutz":    ("B1", "NOUN", "Masc"),
        "wandel":    ("B1", "NOUN", "Masc"),
        "wachstum":  ("B2", "NOUN", "Neut"),   # ← v4.4.1 起从 B1 变成 B2
        "modell":    ("A2", "NOUN", "Neut"),
        "bund":      ("B1", "NOUN", "Masc"),
        "regierung": ("B1", "NOUN", "Fem"),
    }
    for word, (cefr, pos, gender) in expected.items():
        entry = EXT.get(word)
        assert entry, f"{word} 从 LINGUISTICS_VOCAB_EXT 里消失了"
        assert (entry[0], entry[1], entry[2]) == (cefr, pos, gender), (
            f"{word} 的 (CEFR, 词性, 性) 从 {(cefr, pos, gender)} 变成了 {entry[:3]}；"
            f"如果这是有意调整，改这里的期望值并在提交信息里说明理由"
        )
        assert entry[3], f"{word} 的中文释义是空的"
