# -*- coding: utf-8 -*-
"""`tools/bench_spacy_unit.py` 的输出契约与「首次 / 稳态分离」回归闸（ADR-0018 D1 / Task 2）。

钉住什么
--------
仓库里有两个互相矛盾、且都**不可复跑**的 spaCy 单价：

- `delector/routes/syntax_hard.py:9` 的注释：`spaCy ~42ms/句`
- `docs/reviews/2026-09-28-swarm-audit-master.md:36`：`实测 ~2.1 ms/句`

差 20 倍。本文件把「唯一可复跑值」这件事钉成断言，共四层：

1. 脚本**存在且可跑**（子进程实跑：脚本要在真实 CLI 形态下独立可用，
   否则「可复跑」是空话）；
2. 输出**逐行可解析**：`model_load_ms` / `warmup_ms` / `per_sentence_ms` /
   `per_token_us` / `sentences` / `tokens` / `rounds` 七条数值行 +
   `model=` / `engine=` 两条可枚举行，且**值必须为正**；
3. **首次与稳态必须分开计时**（本任务的核心不变量）：`model_load_ms` 与
   `warmup_ms` 各占一行且都为正 —— 只给一个数字的脚本在这里立刻红；
4. `verdict=` 必须**点名对照 42ms 与 2.1ms**，并给出落在哪一侧的判定。

为什么这些断言不是恒真
----------------------
- **源码级断言**（`print(f"xxx=`）：只匹配输出里的 `xxx=` 是半恒真的 —— 脚本的
  模块 docstring 里也写着输出契约，删掉 `main()` 里的 print 行，docstring 里的
  裸字面量仍会让「输出含该行」的断言变绿。故每条契约行都**额外**钉源码里真实的
  print 语句（照抄 `tests/test_cards_endpoint_cost.py` 的教训）。
- **正值断言**（`> 0`）：计时段若被改坏（空跑、`samples` 恒空、`median([])` 兜
  底 0），值会塌成 0 ⇒ 红。
- **`model=` / `engine=` 用严格正则枚举**：脚本不得塞入自由文本（如
  `model=见日志`），`de_core_news_md` / `de_core_news_sm` / `pure-python` 之外
  一律红；`spacy` / `pure_python` 之外一律红。这同时守住 [Instinct:
  Model-Availability]：降级必须**如实打印**，不得静默跳过也不得硬失败。
- **句长档位序**（`bucket_long_ms > bucket_short_ms`）：三档句长是本基准的
  自变量，长句不比短句贵说明分档被写反或语料被掏空 ⇒ 红。
- **档位 token 数单调**（`tokens_per_bucket_short < mid < long`）：只有耗时分档
  **和** token 数分档同时单调，「句长效应」才成立；光看耗时会把噪声当句长效应。
- **语料真实性**（白名单而非黑名单）：`"lorem" not in src` 是可绕过的黑名单
  （换成英文语料照样绿），且 `tokens >= sentences*5` 相对实测（≈24 token/句）
  松了 4.8 倍。故改为：用 AST 抽出 `CORPUS_*` 字面量（docstring 里的德语词不算），
  要求含德语功能词（`der|die|das|und|ist` 多项）+ 变音符号 / `ß`，且实测
  `tokens/sentences` 落在 `[10, 60]`。
- **常数 ↔ 文案 ↔ 测量互锁**：verdict 里的 `"42ms"` / `"2.1ms"` 若是硬编码字面
  量，把常量改掉（甚至删掉对比逻辑只留文案）门禁仍绿。故比值**从脚本源码解析出
  常量**、**从 verdict 解析出数值**，再与输出行的 `per_sentence_ms` 三向对齐。
- **禁类型检查豁免**：新增代码里出现任何类型检查 / lint 豁免注释一律红（本任务
  硬要求 6；判据见下方 `SUPPRESSION_RES` —— 那里的正则**用于禁止**这些写法，
  本文件与基准脚本都不使用它们）。

隔离纪律（`[Instinct: Isolated-DB]`）
-------------------------------------
基准脚本 MUST NOT 触碰仓库根的真实 `delector.db`（桌面端用户数据）。这里做
**源码级**静态断言（而非跑后比对 mtime）：跑后比对需要仓库根存在真实
`delector.db`（CI 上不存在 ⇒ 断言恒真，等于没有断言）。源码里出现 `mkdtemp`
+ 三个环境变量 + `shutil.rmtree`，才是这条纪律真正被写下的证据。
"""

import ast
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Pattern

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "bench_spacy_unit.py"

# 契约数值行（脚本 MUST 逐条打印，且值为正）。
NUM_KEYS = ("model_load_ms", "warmup_ms", "per_sentence_ms", "per_token_us", "sentences", "tokens", "rounds")
# 契约枚举行：model 三选一（允许 `(md 不可用)` 之类的降级后缀），engine 二选一。
MODEL_RE: Pattern[str] = re.compile(
    r"^model=(de_core_news_md|de_core_news_sm|pure-python)(?:\s+\(.*\))?$", re.MULTILINE
)
ENGINE_RE: Pattern[str] = re.compile(r"^engine=(spacy|pure_python)$", re.MULTILINE)
# 句长三档：短/中/长。
BUCKETS = ("short", "mid", "long")
BUCKET_RE: Pattern[str] = re.compile(r"^bucket_(short|mid|long)_ms=([0-9]+(?:\.[0-9]+)?)$", re.MULTILINE)
VERDICT_RE: Pattern[str] = re.compile(r"^verdict=(.+)$", re.MULTILINE)

# 本任务要收口的两个旧值：verdict 必须**点名**它们，否则等于没结论。
LEGACY_SYNTAX_HARD = "42ms"
LEGACY_AUDIT = "2.1ms"

# 防豁免（硬要求 6）：写成正则而非裸字面量，避免本文件自身被「检索豁免」的
# grep 误命中（这里的意图是**禁止**它出现，不是使用它）。
SUPPRESSION_RES = (
    re.compile(r"type:\s+ignore"),
    re.compile(r"#\s*noqa"),
    re.compile(r"disable-error-code"),
)

# 门禁轮数：取计划要求的最小值 5（[Instinct: Median-Not-Mean]，≥5 轮中位数）。
GATE_ROUNDS = "5"


def _num_re(key: str) -> Pattern[str]:
    """抓 `key=N.NN` 形式的数值行（行首锚定，多行模式）。"""
    return re.compile(rf"^{key}=([0-9]+(?:\.[0-9]+)?)$", re.MULTILINE)


def _run_bench(tmp_path: Path, env_extra: Optional[Dict[str, str]] = None) -> str:
    """在隔离环境里实跑基准脚本，返回 stdout 原文（失败时把 stdout/stderr 全吐出来）。

    `env_extra` 用于注入额外环境（如用假 `spacy` 桩逼出降级路径）。
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["BENCH_SPACY_ROUNDS"] = GATE_ROUNDS
    # 双保险：即便脚本自身有 bug，也把库/数据路径钉在临时目录里。
    env["DELECTOR_DATA_DIR"] = str(tmp_path / "gate_data")
    env["DATABASE_PATH"] = str(tmp_path / "gate_delector.db")
    env["PROGRESS_DB_PATH"] = str(tmp_path / "gate_progress.db")
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=900,
        check=False,
    )
    assert proc.returncode == 0, (
        f"基准脚本退出码 {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    return proc.stdout


@pytest.fixture(scope="module")
def bench_out(tmp_path_factory: pytest.TempPathFactory) -> str:
    """整个模块只实跑一次基准（模型加载 + 7×18 次调用不便宜），各断言共享输出。"""
    return _run_bench(tmp_path_factory.mktemp("bench_spacy_gate"))


def _nums(out: str) -> Dict[str, float]:
    """抓全部契约数值行 → {键: 数值}（找不到就不进字典，交给调用方断言报错）。"""
    found: Dict[str, float] = {}
    for key in NUM_KEYS:
        matches = _num_re(key).findall(out)
        if matches:
            found[key] = float(matches[-1])
    return found


def _script_constants() -> Dict[str, float]:
    """从基准脚本**源码**里解析两个旧值常量，而不是在测试里另抄一份字面量。

    抄字面量 ⇒ 脚本把 `LEGACY_AUDIT_MS` 从 2.1 改成别的值，测试还拿 2.1 去比，
    门禁照样绿 —— 这与「verdict 里写死文案」是同一个病。故常量也必须是解析出来的。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    parsed: Dict[str, float] = {}
    for name in ("LEGACY_SYNTAX_HARD_MS", "LEGACY_AUDIT_MS"):
        m = re.search(rf"^{name}\s*=\s*([0-9]+(?:\.[0-9]+)?)", src, re.MULTILINE)
        assert m is not None, f"基准脚本里找不到常量 {name}"
        parsed[name] = float(m.group(1))
    return parsed


def _corpus_text() -> str:
    """用 AST 抽出 `CORPUS_{SHORT,MID,LONG}` 里的字面量（只看语料，不看注释）。

    刻意不对**整个源码**做关键词匹配：模块 docstring / 注释里同样写着德语词和
    变音符号，会把白名单喂饱 ⇒ 语料被整段换掉也照样绿。
    """
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    chunks: List[str] = []
    for node in tree.body:
        # 语料常量带类型注解（`CORPUS_SHORT: Tuple[str, ...] = (...)`）⇒ 是
        # AnnAssign 而不是 Assign，两种都要认，否则抽出来是空的。
        name = ""
        value: Optional[ast.expr] = None
        if isinstance(node, ast.Assign):
            plain = [t for t in node.targets if isinstance(t, ast.Name)]
            if plain:
                name, value = plain[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
            name, value = node.target.id, node.value
        if name not in ("CORPUS_SHORT", "CORPUS_MID", "CORPUS_LONG") or value is None:
            continue
        for elt in ast.walk(value):
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                chunks.append(elt.value)
    assert chunks, "AST 里抽不到 CORPUS_* 语料字面量——语料被删除或改名"
    return "\n".join(chunks)


def _script_measured_target() -> str:
    """从源码里解析 `MEASURED_TARGET`（被测对象），同样不在测试里抄字面量。"""
    src = SCRIPT.read_text(encoding="utf-8")
    m = re.search(r'^MEASURED_TARGET\s*=\s*"([^"]+)"', src, re.MULTILINE)
    assert m is not None, "基准脚本里找不到 MEASURED_TARGET 常量"
    return m.group(1)


def test_bench_script_exists() -> None:
    """① 脚本存在 —— 「唯一可复跑值」的载体不能被静默删除。"""
    assert SCRIPT.is_file(), f"缺少基准脚本：{SCRIPT}"


def test_bench_script_isolated_from_repo_db() -> None:
    """①' 脚本源码自带临时目录隔离（`[Instinct: Isolated-DB]` 的可执行化）。"""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "tempfile.mkdtemp" in src, "基准脚本必须用 tempfile.mkdtemp() 建隔离目录"
    assert "DELECTOR_DATA_DIR" in src, "基准脚本必须重定向 DELECTOR_DATA_DIR（database.py 导入期 makedirs）"
    assert "DATABASE_PATH" in src, "基准脚本必须重定向 DATABASE_PATH"
    assert "PROGRESS_DB_PATH" in src, "基准脚本必须重定向 PROGRESS_DB_PATH"
    assert "shutil.rmtree" in src, "基准脚本必须在 finally 里清理临时目录"


def test_bench_script_bootstraps_env_before_importing_delector() -> None:
    """①'' 隔离**顺序**有人看守：环境变量必须先于 `import delector` 生效。

    现在脚本做对了（import 在 `main()` 里、在 `_bootstrap_env()` 之后），但把
    `from delector.nlp_engine import processor` 挪到模块顶层，17 条断言仍会全绿
    —— 因为 `database.py` 在导入期就按 `DATA_DIR` 建目录、真实 db 立刻被碰。
    故这里用 AST 钉两件事：① 模块层不得有任何 `delector` 导入；② 对
    `_bootstrap_env` 的**调用**必须排在 `delector` 导入之前。
    """
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in tree.body:  # 只看模块层
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        assert not any(n.split(".")[0] == "delector" for n in names), (
            f"基准脚本在模块层导入了 {names}：`_bootstrap_env()` 会晚于它执行，"
            f"真实 delector.db 将在隔离生效前被触碰（[Instinct: Isolated-DB]）"
        )
    boot_lines = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_bootstrap_env"
    ]
    imp_lines = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == "delector"
    ]
    assert boot_lines, "脚本里找不到对 `_bootstrap_env` 的调用"
    assert imp_lines, "脚本里找不到对 delector 的导入"
    assert min(boot_lines) < min(imp_lines), (
        f"`_bootstrap_env()` 在第 {min(boot_lines)} 行，却在第 {min(imp_lines)} 行之后才导入 "
        f"delector —— 隔离顺序反了"
    )


def test_bench_script_declares_all_contract_lines() -> None:
    """② 源码里真有这些 print 语句（**不是**只出现在 docstring 的契约块里）。

    照抄 `test_cards_endpoint_cost.py` 的教训：只匹配裸字面量 `per_sentence_ms=`
    会被模块 docstring 里的输出契约块喂饱 ⇒ 删掉 print 行照样绿（半恒真）。
    钉 `print(f"` 前缀后，删 print 即红。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    for key in NUM_KEYS:
        assert f'print(f"{key}=' in src, f"基准脚本源码不再打印 `{key}=` 行"
    assert 'print(f"model=' in src, "基准脚本源码不再打印 `model=` 行"
    assert 'print(f"engine=' in src, "基准脚本源码不再打印 `engine=` 行"
    assert 'print(f"verdict=' in src, "基准脚本源码不再打印 `verdict=` 结论行"
    # 档位 token 数同样出现在 docstring 的补充行里 ⇒ 一样要钉 print 语句本身。
    assert 'print(f"tokens_per_bucket_{bucket}=' in src, (
        "基准脚本源码不再打印 `tokens_per_bucket_*=` 行（三档句长自变量的刻度）"
    )


def test_bench_script_has_no_type_check_suppressions() -> None:
    """②' 硬要求 6：新增代码里不得出现任何类型检查 / lint 豁免。

    注意 `delector/nlp_engine/processor.py` 里有**既有**的 spaCy 相关豁免
    （spaCy 无类型导出），本任务既不复制也不新增。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    for rx in SUPPRESSION_RES:
        assert rx.search(src) is None, f"基准脚本含被禁的豁免注释：{rx.pattern}"


@pytest.mark.parametrize("key", NUM_KEYS)
def test_bench_output_has_positive_number(key: str, bench_out: str) -> None:
    """③ 每条契约数值行都存在、可解析、且为正（防「计时段塌成 0」的恒真）。"""
    found = _nums(bench_out)
    assert key in found, f"输出里找不到 `{key}=N.NN` 这一行\n{bench_out}"
    assert found[key] > 0.0, f"`{key}` = {found[key]} 非正——计时段没真正跑到\n{bench_out}"


def test_bench_output_rounds_at_least_min(bench_out: str) -> None:
    """③' 稳态轮数 ≥ 5（[Instinct: Median-Not-Mean]：少于 5 轮噪声压不住）。"""
    found = _nums(bench_out)
    assert found["rounds"] >= 5.0, f"稳态轮数 {found['rounds']} < 5，中位数口径不成立\n{bench_out}"


def test_bench_output_model_and_engine_parsable(bench_out: str) -> None:
    """④ `model=` / `engine=` 必须是可枚举值，不得是自由文本。

    这条同时守住 [Instinct: Model-Availability]：md 不可用降级到 sm 时**必须**
    如实打印（允许 `(md 不可用)` 后缀），spaCy 完全不可用时必须打印
    `pure-python` + `engine=pure_python` —— 静默跳过或硬失败都红。
    """
    models = MODEL_RE.findall(bench_out)
    engines = ENGINE_RE.findall(bench_out)
    assert models, f"输出里没有可解析的 `model=` 行（期望 md / sm / pure-python）\n{bench_out}"
    assert engines, f"输出里没有可解析的 `engine=` 行（期望 spacy / pure_python）\n{bench_out}"
    assert engines[0] == "spacy" or engines[0] == "pure_python", f"engine 枚举失败：{engines}\n{bench_out}"


def test_bench_output_separates_first_from_steady(bench_out: str) -> None:
    """⑤ 核心不变量：首次（加载 / 预热）与稳态**分开**计时，两个数字都得在场。

    42ms vs 2.1ms 的 20 倍矛盾，最大嫌疑就是「一个含首次加载、一个是稳态」。
    若脚本只吐一个数字（把首次摊进稳态或反过来），这里的差值断言会塌 ⇒ 红。
    断言形式刻意取「加载 + 预热都远大于 0」而不是断言 `warmup > steady`：
    后者在稳态极快的机器上未必成立（预热未必触发 lazy init），而前者守的是
    「两个口径都被测量并如实打印」这件事本身。
    """
    found = _nums(bench_out)
    assert found["model_load_ms"] > 0.0, f"model_load_ms 非正：首次加载没被单独计时\n{bench_out}"
    assert found["warmup_ms"] > 0.0, f"warmup_ms 非正：首次调用（预热）没被单独计时\n{bench_out}"
    assert found["per_sentence_ms"] > 0.0, f"per_sentence_ms 非正：稳态没被单独计时\n{bench_out}"
    # 两个口径不仅要各打各的数字，还要显式给出**比值** —— 收口 20 倍矛盾的判据就是它。
    assert re.search(r"^first_vs_steady_ratio=[0-9]+(?:\.[0-9]+)?x$", bench_out, re.MULTILINE), (
        f"输出里找不到 `first_vs_steady_ratio=N.Nx`：首次与稳态没有被显式对照\n{bench_out}"
    )


def test_bench_output_bucket_ordering_is_sane(bench_out: str) -> None:
    """⑥ 句长三档都在，且长句档必须贵于短句档。

    长句（~45 词）token 数是短句（~8 词）的 5 倍上下，若测出来长句不比短句贵，
    说明分档写反了 / 语料被掏空 / 计时段挂错了对象 ⇒ 红。
    """
    found = dict(BUCKET_RE.findall(bench_out))
    assert set(BUCKETS) <= set(found), f"三档句长不全，缺：{set(BUCKETS) - set(found)}\n{bench_out}"
    short_ms = float(found["short"])
    long_ms = float(found["long"])
    assert short_ms > 0.0, f"短句档耗时 {short_ms} 非正\n{bench_out}"
    assert long_ms > short_ms, (
        f"长句档 {long_ms:.3f}ms 未贵于短句档 {short_ms:.3f}ms：句长分档或计时对象多半被改坏\n{bench_out}"
    )


def test_bench_corpus_is_real_german(bench_out: str) -> None:
    """⑦ 语料是真实德语：白名单式形态标记 + 实测 token 密度落在区间内。

    旧版 `"lorem" not in src.lower()` 是**黑名单**：语料整段换成英文照样绿；
    `tokens >= sentences * 5` 相对实测（≈24 token/句）又松了 4.8 倍 ⇒ 换英文
    语料照样过。故改为白名单（德语功能词 + 变音符号/ß）+ 密度区间 `[10, 60]`。
    """
    lower = _corpus_text().lower()
    hits = [w for w in ("der", "die", "das", "und", "ist") if re.search(rf"\b{w}\b", lower)]
    assert len(hits) >= 3, f"语料里德语功能词只命中 {hits}（少于 3 个）——语料疑似被换成非德语\n{bench_out}"
    assert re.search(r"[äöüß]", lower), "语料里没有 ä/ö/ü/ß ——不像德语语料"
    found = _nums(bench_out)
    assert found["sentences"] >= 9.0, f"语料句数 {found['sentences']} 少于 9（三档各 ≥3 句）\n{bench_out}"
    per_sentence = found["tokens"] / found["sentences"]
    assert 10.0 <= per_sentence <= 60.0, (
        f"实测 {per_sentence:.1f} token/句 落在 [10, 60] 之外——语料被掏空或不是真实句子\n{bench_out}"
    )


def test_bench_bucket_tokens_are_monotonic(bench_out: str) -> None:
    """⑦' 三档**token 数**必须单调（短 < 中 < 长）。

    只断言 `bucket_long_ms > bucket_short_ms` 有个洞：耗时差可能只是噪声，而本
    基准的自变量是「句长」。token 数才是句长的直接刻度 ⇒ 三档 token 数不单调，
    说明分档写反或语料被掏空。
    """
    counts: Dict[str, float] = {}
    for bucket in BUCKETS:
        m = re.search(rf"^tokens_per_bucket_{bucket}=([0-9]+)$", bench_out, re.MULTILINE)
        assert m is not None, f"输出里找不到 `tokens_per_bucket_{bucket}=N` 行\n{bench_out}"
        counts[bucket] = float(m.group(1))
    assert counts["short"] > 0.0, f"短档 token 数非正：{counts}\n{bench_out}"
    assert counts["short"] < counts["mid"] < counts["long"], (
        f"档位 token 数不单调（短/中/长 = {counts['short']:.0f}/{counts['mid']:.0f}/"
        f"{counts['long']:.0f}）——三档句长这个自变量没被真正钉住\n{bench_out}"
    )


def test_bench_degrades_to_pure_python_without_spacy(tmp_path: Path) -> None:
    """⑪ 降级路径自动化闸（硬要求 6）：spaCy 不可用 ⇒ 不硬失败、不静默跳过。

    之前这条只做过人工验证（手搓一个 `raise ImportError` 的假 `spacy.py`），
    没有门禁 ⇒ 回归时没人守。这里用 `PYTHONPATH` 注入同一个桩：processor 的
    `try: import spacy / except ImportError` 会退到纯 Python，脚本必须照样
    打印 `engine=pure_python` + `model=pure-python` + 正的单价（Android 无模型面
    的成本输入就靠它）。
    """
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    (stub_dir / "spacy.py").write_text(
        "raise ImportError('gate stub: spacy unavailable')\n", encoding="utf-8"
    )
    env_extra = {
        "PYTHONPATH": str(stub_dir) + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    out = _run_bench(tmp_path, env_extra)
    assert re.search(r"^engine=pure_python$", out, re.MULTILINE), (
        f"spaCy 被桩掉后未降级到 pure_python\n{out}"
    )
    assert re.search(r"^model=pure-python$", out, re.MULTILINE), (
        f"spaCy 被桩掉后 model 未如实打印为 pure-python\n{out}"
    )
    found = _nums(out)
    for key in ("per_sentence_ms", "sentences", "tokens"):
        assert found.get(key, 0.0) > 0.0, f"降级路径下 `{key}` 非正——降级后没真正测量\n{out}"


def test_bench_verdict_names_both_legacy_values(bench_out: str) -> None:
    """⑧ `verdict=` 必须点名 42ms 与 2.1ms，且**常数 ↔ 文案 ↔ 测量**三者互锁。

    纯子串匹配太弱：把 `LEGACY_AUDIT_MS` 改成别的值、甚至删掉对比逻辑只留文案，
    门禁仍绿。故这里把 verdict 里的比值**解析回数字**，要求它与
    `per_sentence_ms / LEGACY_AUDIT_MS`（`LEGACY_*` 从脚本源码解析）一致。
    """
    matches = VERDICT_RE.findall(bench_out)
    assert matches, f"输出里找不到 `verdict=` 结论行\n{bench_out}"
    verdict = matches[-1]
    assert LEGACY_SYNTAX_HARD in verdict, (
        f"结论未点名旧值 42ms（syntax_hard.py:9）——不对照旧值等于没收口矛盾\n{verdict}"
    )
    assert LEGACY_AUDIT in verdict, (
        f"结论未点名旧值 2.1ms（swarm-audit-master.md:36）——不对照旧值等于没收口矛盾\n{verdict}"
    )
    assert "见上文" not in verdict, f"结论是空话（「见上文」之类），不是可判定结论\n{verdict}"
    found = _nums(bench_out)
    per_sentence_ms = found["per_sentence_ms"]
    # ① 结论里的实测量必须与输出行是同一个数（防文案写死）。
    assert f"{per_sentence_ms:.2f}ms/句" in verdict, (
        f"结论里的实测量与输出行的 per_sentence_ms={per_sentence_ms:.3f} 对不上\n{verdict}"
    )
    consts = _script_constants()
    # ② 解析「实测/2.1 = N×」：底数必须是脚本里的常量，比值必须等于实测/常量。
    m = re.search(r"实测/([0-9]+(?:\.[0-9]+)?)\s*=\s*([0-9]+(?:\.[0-9]+)?)×", verdict)
    assert m is not None, f"结论里没有可解析的『实测/2.1 = N×』比值\n{verdict}"
    assert float(m.group(1)) == consts["LEGACY_AUDIT_MS"], (
        f"结论里的对照底数 {m.group(1)} ≠ 脚本常量 {consts['LEGACY_AUDIT_MS']}——文案与常数脱钩\n{verdict}"
    )
    assert abs(float(m.group(2)) - per_sentence_ms / consts["LEGACY_AUDIT_MS"]) <= 0.01, (
        f"结论里的比值 {m.group(2)} ≠ 实测/常量 = {per_sentence_ms / consts['LEGACY_AUDIT_MS']:.2f}\n{verdict}"
    )
    # ③ 解析「42/实测 = N×」：同上（两个旧值各锁一次）。
    m2 = re.search(r"([0-9]+(?:\.[0-9]+)?)/实测\s*=\s*([0-9]+(?:\.[0-9]+)?)×", verdict)
    assert m2 is not None, f"结论里没有可解析的『42/实测 = N×』比值\n{verdict}"
    assert float(m2.group(1)) == consts["LEGACY_SYNTAX_HARD_MS"], (
        f"结论里的对照底数 {m2.group(1)} ≠ 脚本常量 {consts['LEGACY_SYNTAX_HARD_MS']}\n{verdict}"
    )
    assert abs(float(m2.group(2)) - consts["LEGACY_SYNTAX_HARD_MS"] / per_sentence_ms) <= 0.01, (
        f"结论里的比值 {m2.group(2)} ≠ 常量/实测 = "
        f"{consts['LEGACY_SYNTAX_HARD_MS'] / per_sentence_ms:.2f}\n{verdict}"
    )


def test_bench_verdict_declares_measured_target_and_scope(bench_out: str) -> None:
    """⑨ 结论**开头**必须声明被测对象，并写明「与旧值不可直接相除」（红卡 1）。

    本脚本测的是 `process_german_text`（完整管线），两个旧值的口径是
    `rank_sentences` → `analyze_syntax_tree`（更轻量）。不声明被测对象，下游就会
    把跨函数比值读成「2.1ms 偏乐观 3.3×」，并据此去改另一个函数的注释 —— 那正是
    要把 20 倍矛盾换个外壳继续传下去。
    """
    verdict = VERDICT_RE.findall(bench_out)[-1]
    target = _script_measured_target()
    assert verdict.startswith(f"实测对象={target}"), (
        f"结论开头未声明被测对象（期望 `实测对象={target}`）\n{verdict}"
    )
    assert "process_german_text" in verdict, f"结论未点名被测函数\n{verdict}"
    assert "不可直接相除" in verdict, f"结论未声明跨口径不可相除\n{verdict}"
    assert "rank_sentences" in verdict, f"结论未点名旧值的口径（rank_sentences）\n{verdict}"
    # 下游要改 syntax_hard.py:9 的 42ms，必须看到「未覆盖该路径」而不是「可以改了」。
    assert "未覆盖" in verdict and "补测" in verdict, (
        f"结论未把「补测 rank_sentences 单价」写成未完成项\n{verdict}"
    )


def test_bench_verdict_amortization_is_candidate_not_conclusion(bench_out: str) -> None:
    """⑩ 冷启动摊薄必须写成**公式 B + 不可证伪 + 候选之一**（红卡 2）。

    旧措辞写的是公式 A 的语义（1485ms 摊到 42 句上每句 42ms），按 A 算只有
    35.4ms/句 ≠ 42ms ⇒ 措辞与算式脱节；且公式 B 对任意 `0 < steady < 42` 恒有正
    解 ⇒ 本脚本永远算得出一个 N，永远无法证伪。故它只能是候选，不能是断言。
    """
    verdict = VERDICT_RE.findall(bench_out)[-1]
    consts = _script_constants()
    hard = f"{consts['LEGACY_SYNTAX_HARD_MS']:g}"
    assert f"(model_load+warmup+N×steady)/N = {hard}" in verdict, (
        f"结论未写出公式 B（(model_load+warmup+N×steady)/N = {hard}）\n{verdict}"
    )
    assert "自由参数" in verdict and "无法证伪" in verdict, (
        f"结论未声明 N 是自由参数 / 本脚本无法证伪该假说\n{verdict}"
    )
    assert "候选①" in verdict and "候选②" in verdict and "候选③" in verdict, (
        f"结论未把三个口径候选并列\n{verdict}"
    )
    assert f"{hard}ms 疑似" not in verdict, f"结论仍在用断言语气下判定：\n{verdict}"
    # 数值行保留（下游可自行复算），且必须与公式 B 自洽。
    found = _nums(bench_out)
    m = re.search(r"^cold_amortized_sentences_to_42ms=([0-9]+(?:\.[0-9]+)?)$", bench_out, re.MULTILINE)
    assert m is not None, f"输出里没有 `cold_amortized_sentences_to_42ms=N` 行\n{bench_out}"
    n = float(m.group(1))
    assert n > 0.0, f"cold_amortized_sentences_to_42ms = {n} 非正\n{bench_out}"
    steady = found["per_sentence_ms"]
    expected = (found["model_load_ms"] + found["warmup_ms"]) / (
        consts["LEGACY_SYNTAX_HARD_MS"] - steady
    )
    assert abs(n - expected) <= 1.5, (
        f"N={n:.0f} 与公式 B 反解值 {expected:.1f} 不符（打印取整，容差 1.5）——"
        f"若按公式 A 算则是 "
        f"{(found['model_load_ms'] + found['warmup_ms']) / consts['LEGACY_SYNTAX_HARD_MS']:.1f}\n{bench_out}"
    )
