# -*- coding: utf-8 -*-
r"""文章 / 遇见区短文与预置种子、Anki 导出、音频缓存。

本模块由 `delector/core/database.py` 按职责切分搬出（database-split / Task 4）。
搬出纪律：**纯移动 + 显式 re-export** —— `database.py` 逐名
`from delector.core.db.content import X` 再导出，公开面零变化。

本片承载的整组职责：
- 遇见区短文 CRUD：`list_encounter_texts` / `get_encounter_text` /
  `create_encounter_text` / `import_encounter_pack`
- 文章写入与预置文章种子：`ingest_article` / `PRESET_ARTICLES` / `preset_text_hash` /
  `preset_processed_data_path` / `preset_processed_json` / `seed_preset_articles`
- 遇见区预置卡包版本化补装：`PRESET_SEED_VERSION` / `seed_preset_encounter_texts`
  （只增 / 只补空 / 逐包异常隔离）
- Anki 牌组导出：`VOCAB_MODEL` / `GRAMMAR_MODEL` / `A1_VOCAB_MODEL` /
  `export_anki_deck` / `export_a1_anki_deck`
- 音频缓存信息与清理：`get_cache_info` / `prune_audio_cache`

模块级状态（预生成数据索引缓存 `_preset_processed_entries` / `_preset_processed_loaded`）随
函数同迁，全仓仅此一份。
"""

import hashlib
import html as _html
import json
import logging
import os
import random
from typing import Any, Dict, List, Optional

import genanki

# 循环导入纪律：`database.py` 在**定义完连接访问器与路径常量之后**才 re-export 本模块，
# 故此处 import 拿到的 database 模块对象已完成到该点（下列名字均已绑定），
# 与 `delector/core/db/backup.py` / `schema.py` / `settings.py` 同款成例。
from delector.core.database import (
    _PKG_DIR,
    AUDIO_CACHE_DIR,
    db_conn,
    get_db_path,
)

# `set_setting` 住 Task-3 切出的 `db/settings.py`：本片 `seed_preset_encounter_texts` 成功后
# 写版本号用它。直接从 settings 模块导入（不绕 database 的 re-export，避免受其位置影响）。
from delector.core.db.settings import set_setting
from delector.nlp_engine.processor import (
    PROCESSED_JSON_VERSION,
    _process_german_text_pure_python,
    process_german_text,
)


def list_encounter_texts(level: Optional[str] = None, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """遇见区短文列表：可选按建议阅读等级过滤，行按 id 倒序（新→旧）。"""
    target_path = get_db_path(db_path)
    with db_conn(target_path) as conn:
        if level is not None:
            rows = conn.execute(
                "SELECT * FROM encounter_texts WHERE level = ? ORDER BY id DESC",
                (level,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM encounter_texts ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def get_encounter_text(text_id: int, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """按 id 取单篇短文；不存在返回 None。"""
    target_path = get_db_path(db_path)
    with db_conn(target_path) as conn:
        row = conn.execute("SELECT * FROM encounter_texts WHERE id = ?", (text_id,)).fetchone()
        return dict(row) if row else None


def create_encounter_text(
    title: str,
    level: str,
    source: str,
    content: str,
    pack_id: Optional[str] = None,
    pack_json: Optional[str] = None,
    db_path: Optional[str] = None,
) -> int:
    """手工/导入新增一篇短文，返回新行自增 id。"""
    target_path = get_db_path(db_path)
    with db_conn(target_path) as conn:
        cur = conn.execute(
            "INSERT INTO encounter_texts (title, level, source, content, pack_id, pack_json) VALUES (?, ?, ?, ?, ?, ?)",
            (title or "", level or "A2", source or "", content or "", pack_id, pack_json),
        )
        return cur.lastrowid  # type: ignore[return-value]  # typeshed 标 lastrowid 为 int | None，INSERT 后运行时恒 int


def import_encounter_pack(pack: Dict[str, Any], db_path: Optional[str] = None) -> int:
    """把 job#1 encounter-pack/v1 整包落库为一行短文；幂等。

    契约：pack_id 已存在时直接返回既有行的 id（不新增）。缺必需键
    （schema / pack_id / article{title, raw_text}）抛 ValueError。level 不做
    规一（A2 的 validate_pack 负责），本函数只存包中原值（缺省 'A2'）。
    """
    if not isinstance(pack, dict):
        raise ValueError("import_encounter_pack: pack 必须是 dict")
    article = pack.get("article")
    missing = [k for k in ("schema", "pack_id") if not pack.get(k)]
    if article is None or not isinstance(article, dict):
        missing.append("article")
    if missing:
        raise ValueError("import_encounter_pack: 缺少必需键 " + ", ".join(sorted(set(missing))))
    # 类型收窄（运行时恒真）：上面的守卫已保证 article 是 dict —— None/非 dict 都会被计入
    # missing 并由此抛错。用 assert 而非重构报错分支，是为了保持「多键缺失合并成一条
    # 错误信息」的既有语义。
    assert isinstance(article, dict)
    if not article.get("title") or not article.get("raw_text"):
        raise ValueError("import_encounter_pack: article 需含 title 与 raw_text")

    target_path = get_db_path(db_path)
    pack_id = pack["pack_id"]
    with db_conn(target_path) as conn:
        existing = conn.execute("SELECT id FROM encounter_texts WHERE pack_id = ?", (pack_id,)).fetchone()
        if existing:
            return existing["id"]  # type: ignore[no-any-return]  # sqlite3.Row 索引为 Any，主键恒 int
        cur = conn.execute(
            "INSERT INTO encounter_texts (pack_id, title, level, content, pack_json) VALUES (?, ?, ?, ?, ?)",
            (
                pack_id,
                article["title"],
                pack.get("estimated_cefr") or "A2",
                article["raw_text"],
                json.dumps(pack, ensure_ascii=False),
            ),
        )
        return cur.lastrowid  # type: ignore[return-value]  # typeshed 标 lastrowid 为 int | None，INSERT 后运行时恒 int


PRESET_ARTICLES = [
    {
        "title": "【A1 入门篇】Hallo Berlin! Mein erster Tag in Deutschland",
        "text": (
            "Guten Tag! Ich heiße Lukas und ich komme aus China. Jetzt wohne ich in Berlin und lerne "
            "Deutsch an einer Sprachschule. Jeden Morgen trinke ich einen Kaffee, esse ein Brötchen "
            "und fahre mit der U-Bahn zum Deutschkurs. Der Unterricht macht viel Spaß. Am Nachmittag "
            "gehe ich in den Supermarkt und kaufe frisches Obst und Brot."
        ),
    },
    {
        "title": "【A2 进阶篇】Eine Reise nach München: Hotel und Freizeit",
        "text": (
            "Letztes Wochenende bin ich mit dem Zug nach München gefahren. Ich habe ein kleines "
            "Zimmer im Stadtzentrum reserviert. Das Wetter war sehr schön, deshalb habe ich den "
            "ganzen Nachmittag im Englischen Garten verbracht. Am Abend habe ich typische bayerische "
            "Spezialitäten in einem traditionellen Restaurant probiert."
        ),
    },
    {
        "title": "【B1 提升篇】Klimaschutz im Alltag: Was jeder tun kann",
        "text": (
            "Der Klimawandel ist eine der größten Herausforderungen unserer Zeit. Viele Menschen "
            "fragen sich, wie sie im Alltag einen Beitrag zum Umweltschutz leisten können. Experten "
            "empfehlen, öfter auf das Fahrrad umzusteigen und Energie im Haushalt zu sparen. Eine "
            "bewusste Ernährung mit regionalen Lebensmitteln spielt ebenfalls eine wichtige Rolle."
        ),
    },
    {
        "title": "【B2 高级篇】Die Transformation der modernen Arbeitswelt: Homeoffice",
        "text": (
            "Die fortschreitende Digitalisierung hat die Arbeitsbedingungen grundlegend verändert. "
            "Immer mehr Unternehmen stellen ihren Mitarbeitern flexible Arbeitszeitmodelle zur "
            "Verfügung. Obwohl das Arbeiten von zu Hause aus die Vereinbarkeit von Beruf und Familie "
            "erleichtert, stehen viele Beschäftigte vor der Herausforderung, klare Grenzen zwischen "
            "Arbeit und Freizeit zu ziehen."
        ),
    },
]


def ingest_article(title: str, text: str, db_path: Optional[str] = None, source_url: Optional[str] = None) -> int:
    processed = process_german_text(text)
    target_path = get_db_path(db_path)
    with db_conn(target_path) as conn:
        cur = conn.execute(
            # P1-6：stats 投影列与 processed_json 同步写（列表只读投影列，不再解析整列 blob）
            "INSERT INTO articles (title, raw_text, processed_json, stats_json, source_url) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                title or "Untitled",
                text,
                json.dumps(processed, ensure_ascii=False),
                json.dumps(processed.get("stats") or {}, ensure_ascii=False),
                source_url or "",
            ),
        )
        return cur.lastrowid  # type: ignore[return-value]  # typeshed 标 lastrowid 为 int | None，INSERT 后运行时恒 int


def _preset_processed_json_lite(text: str) -> str:
    """预置文章**免模型**分析：用纯 Python 路径产出 processed_json（毫秒级）。

    这是 ``preset_processed_json`` 的**回退路径**（未命中构建期预生成数据时用）。不走
    ``process_german_text`` 的理由：那会触发 spaCy 模型加载（本机约 0.5~1.7s），而
    ``create_app() → init_db() → seed_preset_articles()`` 处在桌面冷启动的关键路径上
    （ADR-0018 §7.6 的 O0 杠杆 / ADR-0021 替代投资#4）。故回退时以纯 Python 落库，
    并**不带 ``version``**：单篇 GET（``/api/articles/{id}``）的既有「惰性迁移」判据
    ``pj.get("version") != PROCESSED_JSON_VERSION`` 因此命中，用户**首次打开该文**时用
    spaCy 全量重算并回写 —— 模型加载被推迟到「首次真正需要 NLP 的请求」。列表
    （``/api/articles``）仍能读到非空的 ``stats``（含 ``cefr_percentages``）。

    代价（诚实登记）：回退生效时，列表里的难度预览在文章被首次打开前是纯 Python 口径（略粗），
    打开即升级为 spaCy 全量口径 ⇒ 存在「A2 → A1」跳变。构建期预生成数据正是为消除该跳变。
    """
    processed = _process_german_text_pure_python(text)
    processed.pop("version", None)
    return json.dumps(processed, ensure_ascii=False)


# ── 预置文章预生成数据（子计划 2A：谁固定，就在哪算）──────────────────────────────
# 预置文本是随代码发布的固定文本，「算准」应发生在**构建期**；推迟到运行时会因列表预览
# （纯 Python 口径）与首次打开（惰性迁移升级为 spaCy 口径）不一致而让用户看到难度跳变。
# 生成器：tools/gen_preset_processed.py；产物：delector/data/preset_processed.json（按文本哈希索引）。
PRESET_PROCESSED_SCHEMA = "preset-processed/v1"
_PRESET_PROCESSED_FILENAME = "preset_processed.json"
_preset_processed_entries: Optional[Dict[str, Any]] = None
_preset_processed_loaded = False


def preset_text_hash(text: str) -> str:
    """预置文章正文的内容哈希（sha256 十六进制）。

    生成器与运行时 MUST 共用本函数：两边各算一份，任一侧写法漂移都会让「命中」判据恒不成立、
    预生成数据静默永不命中（退化成未命中回退，且只在日志里可见）。
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def preset_processed_data_path() -> str:
    """预生成数据文件路径（相对**包目录**定位，dev 与 PyInstaller 冻结后同一相对位置）。

    本模块在 ``delector/core/``：回指一级到包目录再进 ``data/``。PyInstaller onedir 下
    ``__file__`` 指向 ``_internal/delector/core/database.pyc``，故本相对路径冻结后同样成立
    —— 前提是打包时用 ``--add-data ...;delector/data`` 把文件收到同一位置（见
    package_windows.py 与 build-release.yml；漏收不崩，但会**静默降级**，故打包守卫 + 产物
    验收闸兜底）。
    """
    return os.path.join(os.path.dirname(_PKG_DIR), "data", _PRESET_PROCESSED_FILENAME)


def _warn_preset_processed(reason: str) -> None:
    """预置文章降级为纯 Python 口径时的**可见**告警（No-Silent-Failure）。

    降级本身可接受（有回退），但后果是「列表预览与详情跳变」这一已知缺陷复发；静默降级则让
    「打包漏收数据文件」这类问题无从观测，故 MUST 打出 WARNING。
    """
    logging.getLogger("delector").warning(
        "预置文章未走构建期预生成数据，已回退纯 Python 口径（首次打开可能跳变）：%s", reason
    )


def _load_preset_processed() -> Dict[str, Any]:
    """读并缓存预生成数据索引：``{text_hash: {"version": ..., "processed": {...}}}``。

    只读 JSON，**绝不**触发 spaCy 模型加载（「import 期不加载模型」这条不变量由此保持，
    tests/test_nlp_lazy_load.py 钉它）。文件缺失 / 解析失败 / 结构不符 → 返回 ``{}`` 并
    **可见**告警一次，由调用方回退纯 Python 口径。
    """
    global _preset_processed_entries, _preset_processed_loaded
    if _preset_processed_loaded:
        return _preset_processed_entries or {}
    _preset_processed_loaded = True
    path = preset_processed_data_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        _warn_preset_processed(f"读取 {path} 失败：{exc!r}")
        _preset_processed_entries = {}
        return _preset_processed_entries
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        _warn_preset_processed(f"{path} 结构不符：缺少 entries 映射")
        _preset_processed_entries = {}
        return _preset_processed_entries
    _preset_processed_entries = entries
    return _preset_processed_entries


def _reset_preset_processed_cache() -> None:
    """清空预生成数据缓存（测试在 monkeypatch 文件路径后用它强制重载）。"""
    global _preset_processed_entries, _preset_processed_loaded
    _preset_processed_entries = None
    _preset_processed_loaded = False


def preset_processed_json(text: str) -> str:
    """预置文章落库用的 ``processed_json``：优先用构建期预生成数据，未命中则**可见地**回退。

    命中判据 = 文本哈希一致 **且** 条目 version 等于 ``PROCESSED_JSON_VERSION``（版本不符说明
    预生成数据已过期，同「未命中」处理并告警）。命中即落 spaCy 口径 + version ⇒ 单篇 GET 的
    惰性迁移判据不成立 ⇒ 首次打开**不再跳变**。

    未命中 / 文件缺失 ⇒ 记一条 WARNING（可见的降级提示）后回退 ``_preset_processed_json_lite``
    （纯 Python 口径、**不带 version**，靠惰性迁移在首次打开时升级）。
    """
    text_hash = preset_text_hash(text)
    entry = _load_preset_processed().get(text_hash)
    if isinstance(entry, dict) and entry.get("version") == PROCESSED_JSON_VERSION:
        processed = entry.get("processed")
        if isinstance(processed, dict):
            return json.dumps(processed, ensure_ascii=False)
    _warn_preset_processed(f"文本哈希 {text_hash[:12]} 未命中（或版本不符 / 文件缺失）")
    return _preset_processed_json_lite(text)


def seed_preset_articles(db_path: Optional[str] = None) -> None:
    target = get_db_path(db_path)
    with db_conn(target) as conn:
        count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        if count == 0:
            for art in PRESET_ARTICLES:
                pj = preset_processed_json(art["text"])
                conn.execute(
                    # P1-6：预置落库同步写 stats 投影列（json_extract 与回填同一口径，
                    # 只算一次 preset_processed_json，避免回退路径下纯 Python 分析跑两遍）
                    "INSERT INTO articles (title, raw_text, processed_json, stats_json, source_url) "
                    "VALUES (?, ?, ?, json_extract(?, '$.stats'), ?)",
                    (art["title"], art["text"], pj, pj, ""),
                )


# 遇见区预置内容的**内容版本号**。升这个号（+1）才会让已升级过的设备再触发一次补装：
# seed 成功走完后把本值写进 app_settings["encounter_seed_version"]，下次启动读到
# `>= PRESET_SEED_VERSION` 即热路径早退（只读 1 行 app_settings）。因此**新增预置内容
# 时必须同步 +1**，否则存量设备永远拿不到新内容。
PRESET_SEED_VERSION: int = 2

_ENCOUNTER_SEED_VERSION_KEY = "encounter_seed_version"


def _read_preset_seed_version(db_path: Optional[str] = None) -> int:
    """读 app_settings["encounter_seed_version"]；缺失 / 非法一律视为 0（从未补装过）。

    **不经 env** 的直读 SQL（参数化）：版本闸是「库内真值」判定，不能走 `get_setting`
    —— 后者尾部有 `return os.environ.get(key, default)` 兜底，进程环境里恰好存在同名
    变量（`encounter_seed_version`）时会**伪造版本**，强制跳过或反复触发补装。DB 是
    唯一真值，故读取只认库行（写入路径 `set_setting` 本就只写库，保持不变）。
    """
    try:
        with db_conn(db_path) as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = ?",
                (_ENCOUNTER_SEED_VERSION_KEY,),
            ).fetchone()
    except Exception:
        return 0
    if row is None or row["value"] is None:
        return 0
    try:
        return int(row["value"])
    except (TypeError, ValueError):
        return 0


def _backfill_pack_lemma_seq(
    pack_id: str,
    existing_pack_json: Optional[str],
    new_pack: Dict[str, Any],
) -> Optional[str]:
    """能力闸门（只补空）：既有行缺 `analysis.lemma_seq` 时返回补装后的 `pack_json` 文本。

    返回 `None` 表示「无需写回」（调用方据此跳过 UPDATE）。判据：
    - 新包无**非空** `lemma_seq`，或既有 `pack_json` 为空 → `None`；
    - 既有 `lemma_seq` **非空**即返回 `None`（**不覆盖**，哪怕值是哨兵）；
    - 旧 `pack_json` 解析失败 / 结构异常一律返回 `None` 并 `logging.error`，**绝不抛**
      ——单行数据损坏不得崩启动。
    """
    new_seq: Any = (new_pack.get("analysis") or {}).get("lemma_seq") or []
    if not new_seq or not existing_pack_json:
        return None
    try:
        old_pack: Any = json.loads(existing_pack_json)
    except (TypeError, ValueError) as exc:
        logging.error("seed_preset_encounter_texts: 既有行 pack_json 解析失败 pack_id=%r: %r", pack_id, exc)
        return None
    if not isinstance(old_pack, dict):
        logging.error("seed_preset_encounter_texts: 既有行 pack_json 非对象 pack_id=%r", pack_id)
        return None
    analysis = old_pack.get("analysis")
    if not isinstance(analysis, dict):
        logging.error("seed_preset_encounter_texts: 既有行 pack_json.analysis 非对象 pack_id=%r", pack_id)
        return None
    if analysis.get("lemma_seq"):  # 非空（含哨兵）→ 不覆盖
        return None
    patched: Dict[str, Any] = dict(old_pack)
    patched["analysis"] = {**analysis, "lemma_seq": new_seq}
    return json.dumps(patched, ensure_ascii=False)


def _seed_or_backfill_preset_pack(pack: Dict[str, Any], db_path: str) -> bool:
    """处理单个预置包，返回是否**新建**了行。

    - `pack_id` 不存在 → `import_encounter_pack` 只增导入（返回 True）；
    - `pack_id` 已存在 → 只补空 `lemma_seq`（返回 False，不新增行）。

    空库即「全部缺失」，自然退化为「全量导入」；非空库则「只增缺失 + 只补空既有」。
    """
    pack_id = str(pack.get("pack_id") or "")
    with db_conn(db_path) as conn:
        row = conn.execute("SELECT id, pack_json FROM encounter_texts WHERE pack_id = ?", (pack_id,)).fetchone()
    if row is None:
        import_encounter_pack(pack, db_path=db_path)
        return True
    patched = _backfill_pack_lemma_seq(pack_id, row["pack_json"], pack)
    if patched is not None:
        with db_conn(db_path) as conn:
            conn.execute(
                "UPDATE encounter_texts SET pack_json = ? WHERE pack_id = ?",
                (patched, pack_id),
            )
    return False


def _try_seed_or_backfill_preset_pack(pack: Any, db_path: str) -> Optional[bool]:
    """逐包异常隔离的唯一落点：成功返回「是否新建行」，失败返回 `None` 并 `logging.error`。

    任何异常（离线数据损坏 / 约束冲突）都在此吞成 `None`，**绝不外溢崩启动**。
    """
    try:
        return _seed_or_backfill_preset_pack(pack, db_path)
    except Exception as exc:  # noqa: BLE001 —— 单包失败不得崩启动
        # 类型安全取值：pack 可能**非 dict**（损坏的数据模块项，如 str/list）。
        # 旧写法 `(pack or {}).get(...)` 会在日志行对非 dict 再次 .get 抛
        # AttributeError，异常逃逸出本函数 → 违反「单包失败不得崩启动」。
        logging.error(
            "seed_preset_encounter_texts: 预置包导入失败 pack_id=%r: %r",
            pack.get("pack_id") if isinstance(pack, dict) else None,
            exc,
        )
        return None


def seed_preset_encounter_texts(db_path: Optional[str] = None) -> int:
    """版本化增量补装预置遇见区卡包（encounter-pack/v1）；返回本次**实际新建**的行数。

    语义（红线 12 / Vault `01-Rules/STORED-DATA-BACKFILL`：只增 + 只补空 + 幂等）
    ---------------------------------------------------------------------------
    1. **版本闸**：先读 `app_settings["encounter_seed_version"]`（缺省 0），
       `>= PRESET_SEED_VERSION` 即热路径返回 0（每次启动只读 1 行）。升
       `PRESET_SEED_VERSION` 才会再触发一次补装。
    2. **只增补装**：逐包走既有 `import_encounter_pack`（按 `pack_id` 去重，不自己写
       INSERT）——库里没有的 `pack_id` 新建，已存在的**不动其行**。空库即等于
       「全量导入」（7 包全缺），保留既有「空库 = 空列表」的空态语义。
    3. **只补空**：已存在的 `pack_id`，若其 `pack_json.analysis` 缺 `lemma_seq`
       （或为空）而新包有非空值，则**仅补写该字段**（UPDATE `pack_json`），绝不触碰
       `title/level/content/source/created_at` 与其它键；既有序列**非空则不覆盖**
       （哪怕值是哨兵）。解析失败/结构异常跳过该行 + `logging.error`，绝不抛。
    4. **成功后写版本**：全部包无失败时写入 `app_settings["encounter_seed_version"]
       = PRESET_SEED_VERSION`；有失败则不写（下次启动重试缺失包），返回值只计**成功
       新建**行数（失败数与包总数可从日志与「返回值 < 包数」推知）。
    5. **逐包异常隔离**：单包导入失败不得让整个启动崩（离线数据损坏/约束冲突时仍要
       起得来）。失败包记录到日志，**绝不静默吞掉**导致数据半残而无从观测。

    **不引墓碑**：版本闸天然只补「这一次」，用户主动删除的预置短文不会在后续每次启动
    复活（记录已是 2）。代价：升级那一次会把用户删过的预置包补回来一次——可接受，且
    行为可解释（「随版本发布的内容资产」与「用户数据」分离）。

    为何不进 `init_db()`
    -------------------
    既有契约测试（`tests/test_encounter_routes.py::test_get_list_empty` 等 6 条）
    把「空库 = 空列表」钉成遇见区的**空态语义**；测试夹具调用 `init_db()` 建库，
    若 seed 塞进 `init_db`，这些用例会集体由「空」变「含 7 篇」而变红，语义被
    削弱为「包含」。预置内容属**产品默认内容**而非 schema 事务，schema 建表
    （`init_db`）与默认内容供给（`create_app`）必须分权：由唯一的生产装配入口
    `create_app()` 在 `seed_preset_articles()` 之后调用本函数。
    """
    # 延迟导入：数据模块只应在真正 seed 时被拉起（导入期零副作用，项目红线 9）。
    from delector.data.encounter_seed_dict import PRESET_ENCOUNTER_PACKS

    target = get_db_path(db_path)
    # 热路径：版本已够 → 只读 1 行 app_settings 即返回，不碰 encounter_texts。
    if _read_preset_seed_version(target) >= PRESET_SEED_VERSION:
        return 0

    imported = 0
    failed = 0
    for pack in PRESET_ENCOUNTER_PACKS:
        created = _try_seed_or_backfill_preset_pack(pack, target)
        if created is None:
            failed += 1
        elif created:
            imported += 1
    if failed:
        logging.error(
            "seed_preset_encounter_texts: %d/%d 预置包导入失败（成功新建 %d）",
            failed,
            len(PRESET_ENCOUNTER_PACKS),
            imported,
        )
        return imported  # 有失败：不写版本，下次启动重试缺失包
    set_setting(_ENCOUNTER_SEED_VERSION_KEY, str(PRESET_SEED_VERSION), db_path=target)
    return imported


VOCAB_MODEL = genanki.Model(
    1607392319,
    "DeLector Vocab",
    fields=[{"name": "Front"}, {"name": "Word"}, {"name": "Lemma"}, {"name": "Meta"}, {"name": "Definition"}],
    templates=[
        {
            "name": "Card",
            "qfmt": '<div style="font-family:sans-serif;font-size:20px;padding:20px;">{{Front}}</div>',
            "afmt": (
                '{{FrontSide}}<hr><div style="font-family:sans-serif;font-size:18px;padding:20px;'
                'color:#1e293b;"><b>{{Definition}}</b><br><span style="color:#64748b;font-size:14px;">'
                "{{Lemma}} ({{Meta}})</span></div>"
            ),
        }
    ],
)

GRAMMAR_MODEL = genanki.Model(
    1607392320,
    "DeLector Goethe Grammar",
    fields=[
        {"name": "Sentence"},
        {"name": "GrammarName"},
        {"name": "CEFR"},
        {"name": "Explanation"},
        {"name": "Formula"},
    ],
    templates=[
        {
            "name": "Card",
            "qfmt": (
                '<div style="font-family:sans-serif;font-size:20px;padding:20px;">'
                '<span style="background:#e0e7ff;color:#3730a3;padding:2px 8px;border-radius:99px;'
                'font-size:12px;">Goethe {{CEFR}}</span><br><br>{{Sentence}}</div>'
            ),
            "afmt": (
                '{{FrontSide}}<hr><div style="font-family:sans-serif;font-size:18px;padding:20px;">'
                '<b>{{GrammarName}}</b><br><code style="background:#f1f5f9;color:#0369a1;'
                'padding:4px 8px;">{{Formula}}</code><p style="color:#334155;">{{Explanation}}</p></div>'
            ),
        }
    ],
)


def _anki_esc(value: Any) -> str:
    """用户/可编辑数据进 Anki HTML 字段前一律转义。

    genanki 不自动转义，裸标签（如 `<img onerror>`）在 Anki 打开牌组时会执行，
    是存储型 XSS。quote=True 一并转义引号，防 attribute 注入。
    """
    return _html.escape(str(value or ""), quote=True)


def _vocab_anki_note(r: Dict[str, Any]) -> genanki.Note:
    """构造词汇卡 note：先转义再高亮替换，顺序不可颠倒（先转义否则破坏 <b> 结构）。"""
    word = _anki_esc(r["word"])
    sentence = _anki_esc(r["sentence_context"])
    styled_front = sentence.replace(word, f'<b style="color:#2563eb;">{word}</b>')
    meta = f"{_anki_esc(r['pos'])} · {_anki_esc(r['gender'] or '')} · {_anki_esc(r['cefr_level'])}"
    return genanki.Note(
        model=VOCAB_MODEL,
        fields=[
            styled_front,
            word,
            _anki_esc(r["lemma"]),
            meta,
            _anki_esc(r["definition_zh"]),
        ],
    )


def _grammar_anki_note(r: Dict[str, Any]) -> genanki.Note:
    """构造语法卡 note：五个模板字段全部来自句库/卡片数据，逐字段转义。"""
    return genanki.Note(
        model=GRAMMAR_MODEL,
        fields=[
            _anki_esc(r["sentence_context"]),
            _anki_esc(r["grammar_name"]),
            _anki_esc(r["cefr_level"]),
            _anki_esc(r["explanation_zh"]),
            _anki_esc(r["rule_formula"] or ""),
        ],
    )


def export_anki_deck(output_path: str, db_path: Optional[str] = None) -> str:
    target_path = get_db_path(db_path)
    with db_conn(target_path) as conn:
        vocab_rows = conn.execute("SELECT * FROM vocab_cards").fetchall()
        grammar_rows = conn.execute("SELECT * FROM grammar_cards").fetchall()

    deck = genanki.Deck(random.randrange(1 << 30, 1 << 31), "DeLector::Goethe Deck")
    for r in vocab_rows:
        deck.add_note(_vocab_anki_note(r))
    for r in grammar_rows:
        deck.add_note(_grammar_anki_note(r))

    genanki.Package(deck).write_to_file(output_path)
    return output_path


A1_VOCAB_MODEL = genanki.Model(
    1607392321,
    "DeLector Goethe A1 Wortliste",
    fields=[
        {"name": "Front"},
        {"name": "Word"},
        {"name": "Lemma"},
        {"name": "POS"},
        {"name": "Plural"},
        {"name": "Definition"},
        {"name": "ExampleDe"},
        {"name": "ExampleZh"},
        {"name": "Topic"},
    ],
    templates=[
        {
            "name": "Goethe A1 Card",
            "qfmt": (
                '<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;padding:24px;'
                'text-align:center;"><div style="display:inline-block;background:#e0e7ff;color:#3730a3;'
                'padding:3px 10px;border-radius:99px;font-size:12px;font-weight:600;margin-bottom:12px;">'
                'Goethe A1 · {{Topic}}</div><div style="font-size:26px;font-weight:700;color:#1e293b;'
                'margin:12px 0;">{{Front}}</div>{{#Plural}}<div style="font-size:14px;color:#64748b;">'
                "Plural: {{Plural}}</div>{{/Plural}}</div>"
            ),
            "afmt": (
                '{{FrontSide}}<hr style="border:none;border-top:1px solid #e2e8f0;margin:16px 0;">'
                '<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;'
                'padding:0 24px 24px;text-align:left;"><div style="font-size:18px;font-weight:600;'
                'color:#0f172a;margin-bottom:8px;">{{Definition}}</div><div style="font-size:13px;'
                'color:#64748b;margin-bottom:16px;">词性: {{POS}}</div><div style="background:#f8fafc;'
                'border-left:3px solid #6366f1;padding:10px 14px;border-radius:0 6px 6px 0;">'
                '<div style="font-size:15px;color:#1e293b;font-weight:500;">{{ExampleDe}}</div>'
                '<div style="font-size:13px;color:#64748b;margin-top:4px;">{{ExampleZh}}</div></div></div>'
            ),
        }
    ],
)


def export_a1_anki_deck(output_path: str) -> str:
    from delector.data import a1_dict

    deck = genanki.Deck(1607392321, "DeLector::Goethe A1 Wortliste")
    topic_map = dict((k, label) for k, label, _ in a1_dict.A1_TOPICS)

    for lemma, entry in a1_dict.GOETHE_A1_VOCAB.items():
        word = entry.get("word", lemma)
        topic_label = topic_map.get(entry.get("topic", "personal"), entry.get("topic", "A1"))
        pos = entry.get("pos", "")
        plural = entry.get("plural", "")
        defn = entry.get("definition_zh", "")
        ex_de = entry.get("example_de", "")
        ex_zh = entry.get("example_zh", "")
        gender = entry.get("gender")

        if gender == "Masc":
            color = "#2563eb"
        elif gender == "Fem":
            color = "#dc2626"
        elif gender == "Neut":
            color = "#16a34a"
        else:
            color = "#475569"

        word_esc = _anki_esc(word)
        front_html = f'<span style="color:{color};">{word_esc}</span>'
        note = genanki.Note(
            model=A1_VOCAB_MODEL,
            fields=[
                front_html,
                word_esc,
                _anki_esc(lemma),
                _anki_esc(pos),
                _anki_esc(plural),
                _anki_esc(defn),
                _anki_esc(ex_de),
                _anki_esc(ex_zh),
                _anki_esc(topic_label),
            ],
        )
        deck.add_note(note)

    genanki.Package(deck).write_to_file(output_path)
    return output_path


def get_cache_info(cache_dir: Optional[str] = None) -> Dict[str, Any]:
    target_dir = cache_dir or AUDIO_CACHE_DIR
    total_size = 0
    count = 0
    if os.path.exists(target_dir):
        for fname in os.listdir(target_dir):
            fpath = os.path.join(target_dir, fname)
            if os.path.isfile(fpath):
                count += 1
                total_size += os.path.getsize(fpath)
    return {"file_count": count, "total_size_mb": round(total_size / (1024 * 1024), 2), "total_size_bytes": total_size}


def prune_audio_cache(max_files: int = 300, cache_dir: Optional[str] = None) -> None:
    target_dir = cache_dir or AUDIO_CACHE_DIR
    if not os.path.exists(target_dir):
        return
    files = []
    for fname in os.listdir(target_dir):
        fpath = os.path.join(target_dir, fname)
        if os.path.isfile(fpath):
            files.append((fpath, os.path.getmtime(fpath)))
    if len(files) > max_files:
        files.sort(key=lambda x: x[1])
        for fpath, _ in files[: len(files) - max_files + 30]:
            try:
                os.remove(fpath)
            except Exception:
                pass


