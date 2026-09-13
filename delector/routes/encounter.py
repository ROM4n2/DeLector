# -*- coding: utf-8 -*-
"""`/api/encounter/*` 路由（遇见区 i+1 Task A2）。

提供三类能力：
- GET 列表 / 详情（读 encounter_texts，word_count 由服务端按空白分词算，跑不上 spaCy）
- POST 手工加文本（限本机）：title/level/source/content → 201
- POST import-pack（限本机）：把 job#1 的 encounter-pack/v1 整包落库成一篇短文
- GET packs / packs/{pack_id}（**局域网只读**）：桌面货架，供手机端出站拉取
- POST pull-pack（限本机）：手机端出站拉取桌面货架并幂等落库

跨边界契约 `encounter-pack/v1` 定在本模块（`CARD_PACK_SCHEMA` + `validate_pack`）：
A/B 两端共同遵守这份 schema 定义。import 落库复用一个跨任务约定的语义：本机
pack_id 已存在时幂等返回既有行 id（不新增），因此同一包重复 POST 只会产生一行。

word_count = 简单空白分词计数（服务端 cheap 计算），不做 spaCy。
"""

import copy
import json
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from delector.core.database import (
    _require_localhost,
    create_encounter_text,
    get_encounter_text,
    import_encounter_pack,
    list_encounter_texts,
)
from delector.nlp_engine import process_german_text

router = APIRouter(prefix="/api/encounter", tags=["Encounter"])

# encounter-pack/v1 契约常量：A/B 侧共同校验的 schema 版本。
CARD_PACK_SCHEMA = "encounter-pack/v1"

# 建议阅读等级白名单（与表契约一致）。
_ALLOWED_LEVELS = ("A1", "A2", "B1")


class CreateTextRequest(BaseModel):
    title: str = Field(min_length=1)
    level: str = "A2"
    source: str = ""
    content: str = Field(min_length=1)


class ImportPackRequest(BaseModel):
    pack: dict


class PullPackRequest(BaseModel):
    """手机端出站拉取桌面货架的入参。"""

    desktop_base: str = Field(min_length=1)
    pack_id: Optional[str] = None


def _normalize_level(raw: str, field_name: str = "level") -> str:
    """把输入的 level 规一到白名单内的大写 A1/A2/B1，非法抛 HTTPException(400)。"""
    normalized = (raw or "").strip().upper()
    if normalized not in _ALLOWED_LEVELS:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} 仅支持 {'/'.join(_ALLOWED_LEVELS)}，收到: {raw!r}",
        )
    return normalized


def _count_words(content: str) -> int:
    """word_count：按空白分词（服务端 cheap 计算，不跑 spaCy）。"""
    return len(content.split())


def validate_pack(pack) -> None:
    """校验一个 encounter-pack/v1 卡包的结构（不校验 estimated_cefr —— 那在路由归一）。

    与 A1 import_encounter_pack 的 guard 语义一致：缺必需键抛 ValueError，文案用中文。
    仅做结构必需校验，不触碰估计等级（归一/白名单由路由层负责）。
    """
    if not isinstance(pack, dict):
        raise ValueError("pack 必须是 dict")
    if pack.get("schema") != CARD_PACK_SCHEMA:
        raise ValueError(f"pack.schema 必须为 {CARD_PACK_SCHEMA!r}，收到: {pack.get('schema')!r}")
    pack_id = pack.get("pack_id")
    if not pack_id or not str(pack_id).strip():
        raise ValueError("pack.pack_id 必填且不能为空")
    article = pack.get("article")
    if article is None or not isinstance(article, dict):
        raise ValueError("pack.article 必须是 dict 且必填")
    if not article.get("title") or not str(article["title"]).strip():
        raise ValueError("pack.article.title 必填且不能为空")
    if not article.get("raw_text") or not str(article["raw_text"]).strip():
        raise ValueError("pack.article.raw_text 必填且不能为空")


def _to_list_payload(row: dict) -> dict:
    """把 store 行压缩成列表端点所需的元数据（不含 content/pack_json）。"""
    return {
        "id": row["id"],
        "title": row["title"],
        "level": row["level"],
        "source": row["source"],
        "word_count": _count_words(row["content"] or ""),
        "created_at": row["created_at"],
    }


@router.get("/texts")
def api_list_texts(level: Optional[str] = None) -> dict:
    """遇见区短文列表：可传 ?level=A2 过滤，含服务端算的 word_count。"""
    rows = list_encounter_texts(level=level)
    return {"texts": [_to_list_payload(r) for r in rows]}


@router.get("/texts/{text_id:int}")
def api_get_text(text_id: int) -> dict:
    """取单篇短文（含 content / pack_json），缺失 404。"""
    row = get_encounter_text(text_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"短文未找到: {text_id}")
    return {
        "id": row["id"],
        "title": row["title"],
        "level": row["level"],
        "source": row["source"],
        "content": row["content"],
        "pack_json": row["pack_json"],
    }


def _annotate_tokens(sent_payload: dict) -> list:
    """把 process_german_text 产出的单句 tokens 映射成 annotate 需要的
    {text, lemma, pos}（标点也保留，前端自行过滤）；跳过纯空白伪 token。"""
    out = []
    for tok in sent_payload.get("tokens", []):
        if tok.get("is_space"):
            continue
        out.append({"text": tok["text"], "lemma": tok["lemma"], "pos": tok["pos"]})
    return out


@router.get("/texts/{text_id:int}/annotate")
def api_annotate_text(text_id: int) -> dict:
    """逐句逐 token 注解（lemma + 粗粒度 POS），前端据此做已背词匹配。

    读取 encounter_texts 正文，跑 spaCy（P0 直跑、禁缓存）。sentence idx 0-based
    顺序；total_tokens = 各句 token 数之和。文本缺失 404。

    零漂移保证：复用 process_german_text 产出的 tokens（已含 text/lemma/pos），
    只做映射、不改其返回结构 —— analyze 契约不受影响（test_tools.py 钉住）。
    """
    row = get_encounter_text(text_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"短文未找到: {text_id}")

    parsed = process_german_text(row["content"] or "")
    sentences = [{"idx": s["id"], "tokens": _annotate_tokens(s)} for s in parsed["sentences"]]
    total_tokens = sum(len(s["tokens"]) for s in sentences)
    return {
        "text_id": text_id,
        "total_tokens": total_tokens,
        "sentences": sentences,
    }


@router.post("/texts", status_code=201, dependencies=[Depends(_require_localhost)])
def api_create_text(req: CreateTextRequest) -> dict:
    """本机新增一篇手工短文，返回 {id,title,level}。"""
    level = _normalize_level(req.level)
    new_id = create_encounter_text(
        title=req.title.strip(),
        level=level,
        source=req.source or "",
        content=req.content,
    )
    return {"id": new_id, "title": req.title.strip(), "level": level}


@router.post("/import-pack", dependencies=[Depends(_require_localhost)])
def api_import_pack(req: ImportPackRequest) -> dict:
    """把 encounter-pack/v1 整包落库成一篇短文。

    落库前先本地校验结构 + 把 estimated_cefr 规一到白名单大写（A1/A2/B1）。
    幂等语义在存储层：同一 pack_id 重复 POST 返回既有行 id、不新增行 —— 见
    database.import_encounter_pack 注释。这里 `imported` 恒为 True 是文档化选择：
    存储层幂等已保证"不产生重复行"，上层无需再自造 pre-read 探测；要证幂等就看
    import-pack 重复调用返回同一 id 且列表行数不增（测试钉这条）。
    """
    pack = req.pack
    try:
        validate_pack(pack)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    raw_level = str(pack.get("estimated_cefr") or "A2").strip()
    normalized_level = _normalize_level(raw_level, field_name="estimated_cefr")

    # A1 import_encounter_pack 从 pack["estimated_cefr"] 取 level 落库，不接受独立
    # level 参数。要存规一化后的大写值，得在入库前改写 pack 副本（保持 db 层不动）。
    normalized_pack = copy.deepcopy(pack)
    normalized_pack["estimated_cefr"] = normalized_level
    new_id = import_encounter_pack(normalized_pack)
    return {"id": new_id, "imported": True}


# ── 桌面货架（局域网只读）────────────────────────────────────────────────────
# 安全边界（不可推翻）：这两个端点**不挂** _require_localhost —— 它们是局域网内
# 只读的内容数据，与既有 `GET /api/wb/state`（拉取免 key）同级。手机端要能读到桌面
# 的卡包，前提就是桌面货架对局域网开放。
# 反向约束：这里**绝不提供任何写操作**。局域网内的任何设备都不能通过货架改动桌面
# 数据——写路径仍然只存在于 import-pack / texts（均挂本机闸）。若将来要加写能力，
# 必须走 X-WB-Key 式的 key 闸，而不是直接放开。
#
# 手工短文（pack_json 为空）不进清单：货架的唯一用途是「把 job#1 产的 encounter-pack/v1
# 搬到手机」，不是通用短文导出；手工短文没有 pack_id、搬过去也无法幂等去重。


def _shelf_entry(row: dict) -> Optional[dict]:
    """把一行 encounter_texts 压缩成货架清单项；非真 pack 行返回 None（不进清单）。

    只暴露跨机搬运必需的元数据（pack_id/title/level/word_count），**绝不返回
    pack_json 原文、content 正文或任何其它列**。
    """
    pack_json = row.get("pack_json")
    if not pack_json:
        return None
    try:
        pack = json.loads(pack_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(pack, dict) or not pack.get("pack_id"):
        return None
    return {
        "pack_id": pack["pack_id"],
        "title": row["title"],
        "level": row["level"],
        "word_count": _count_words(row["content"] or ""),
    }


@router.get("/packs")
def api_list_packs() -> dict:
    """桌面货架清单（**局域网只读**，不挂本机闸）。

    返回 {"packs": [{pack_id, title, level, word_count}, ...]}。只列真正的
    encounter-pack/v1 落库行（pack_json 可解析且含 pack_id），手工短文跳过；
    空货架返回空清单。**不含 pack_json / raw_text 等原文**（防泄）。
    """
    entries = []
    for row in list_encounter_texts():
        entry = _shelf_entry(row)
        if entry is not None:
            entries.append(entry)
    return {"packs": entries}


@router.get("/packs/{pack_id}")
def api_get_pack(pack_id: str) -> dict:
    """取货架上单个完整 encounter-pack/v1（**局域网只读**，不挂本机闸）。

    从任意 pack_json 可解析且 pack_id 匹配的行反序列化返回；未知 pack_id → 404。
    """
    for row in list_encounter_texts():
        raw = row.get("pack_json")
        if not raw:
            continue
        try:
            pack = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(pack, dict) and pack.get("pack_id") == pack_id:
            return pack
    raise HTTPException(status_code=404, detail=f"货架上没有这个卡包: {pack_id}")


# ── 手机端出站拉取（本机闸 + 出站）───────────────────────────────────────────
# 方向：手机服务端**出站** GET 桌面货架（Android 实例绑回环，出站不受监听限制），
# 前端只调本机 /api/encounter/pull-pack —— 同源零跨域。
_PULL_TIMEOUT = 5.0
_PULL_FAIL_HINT = "连不上电脑端（检查电脑是否开着 DeLector、手机与电脑是否同一 WiFi、或退出防火墙拦截）"


def _normalize_desktop_base(raw: str) -> str:
    """校验并规一 desktop_base：必须 http(s):// 前缀、非空、去尾斜杠；否则 400。"""
    base = (raw or "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")) or base in ("http://", "https://"):
        raise HTTPException(
            status_code=400,
            detail=f"desktop_base 需为 http:// 或 https:// 开头的地址，收到: {raw!r}",
        )
    return base


def _shelf_get(url: str) -> object:
    """出站 GET 桌面货架：非 2xx / 连接失败 / 超时 → 502 人话；JSON 解析失败 → 502。"""
    try:
        resp = httpx.get(url, timeout=_PULL_TIMEOUT)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=_PULL_FAIL_HINT) from exc
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=_PULL_FAIL_HINT)
    try:
        return resp.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=_PULL_FAIL_HINT) from exc


@router.post("/pull-pack", dependencies=[Depends(_require_localhost)])
def api_pull_pack(req: PullPackRequest) -> dict:
    """手机端出站拉取桌面货架（**挂本机闸**：写路径只允许本机触发）。

    - pack_id 为空 → 代理桌面货架清单（出站 GET {desktop_base}/api/encounter/packs），
      把 {"packs": [...]} 原样返回，前端因此零跨域。
    - pack_id 非空 → 出站取整包 → validate_pack → 规一 estimated_cefr（与 import-pack
      同语义）→ import_encounter_pack 幂等落库 → {"id", "imported": True, "pack_id"}。
      同一 pack_id 重复拉取返回同一 id、行数不增（幂等由存储层保证）。

    出站失败（连接错误/超时/非 2xx/JSON 解析失败）→ 502 中文人话；
    pack 结构非法 → 400。
    """
    base = _normalize_desktop_base(req.desktop_base)

    if not req.pack_id:
        listing = _shelf_get(f"{base}/api/encounter/packs")
        if not isinstance(listing, dict) or not isinstance(listing.get("packs"), list):
            raise HTTPException(status_code=502, detail=_PULL_FAIL_HINT)
        return {"packs": listing["packs"]}

    pack = _shelf_get(f"{base}/api/encounter/packs/{req.pack_id}")
    try:
        validate_pack(pack)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    raw_level = str(pack.get("estimated_cefr") or "A2").strip()
    normalized_level = _normalize_level(raw_level, field_name="estimated_cefr")

    normalized_pack = copy.deepcopy(pack)
    normalized_pack["estimated_cefr"] = normalized_level
    new_id = import_encounter_pack(normalized_pack)
    return {"id": new_id, "imported": True, "pack_id": normalized_pack["pack_id"]}
