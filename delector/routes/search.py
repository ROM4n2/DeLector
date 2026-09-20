# -*- coding: utf-8 -*-
"""全文检索 API（/api/search，Task 3）。

薄路由：把请求交给 ``delector.services.search`` 纯函数，自身只做三件事——
1. ``scope`` 白名单校验（非法 → 400）。spec §3.3：service 纯函数**不承担输入校验**，
   收到非法 scope 一律按 ``all`` 处理且不抛错，故校验必须落在路由层；
2. 用**只读短连接**（``db_conn``）读语料（``iter_corpus_docs``）并喂给 ``search``；
3. 把 ``truncated`` 置为**语料 hard cap** 的结果（``corpus_truncated``）——这是
   ``truncated`` 的**唯一**来源（Task 6：不再与 limit 截断 OR 合并）。

截断语义（Task 6）：``truncated`` 仅表示「语料 hard cap 未扫完」这一真异常；``limit``
的每组限量（几乎总发生）改由 ``search`` 返回的 ``groups_total`` 表达，由前端按组比较
``groups_total[k] > len(groups[k])`` 显示信息性提示，**不**触发 ``truncated``。

只读、无副作用：不写库、不落盘。``limit`` 钳制 1..100 由 ``search`` 内部完成，本路由
**不重复钳制**（避免双重语义），仅透传 int（类型由 FastAPI 校验）。
"""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from delector.core.database import db_conn
from delector.services.search import iter_corpus_docs, search

router = APIRouter(prefix="/api/search", tags=["search"])

# 合法 scope 白名单（spec §3.3）。非法值由本路由 400；service 纯函数收到非法值按 all 处理。
_VALID_SCOPES = frozenset({"all", "vocab", "example", "colloc", "corpus"})


@router.get("")
def api_search(q: str, scope: str = "all", limit: int = 20) -> Dict[str, Any]:
    """全文检索：``q`` 必填；``scope`` 非法 → 400；``limit`` 透传给 ``search``（内钳 1..100）。

    响应形状：``{q, scope, total, groups:{vocab,example,colloc,corpus}, groups_total, truncated}``。
    ``truncated`` 现仅表示「语料 hard cap 未扫完」（Task 6）；limit 的每组限量由
    ``groups_total`` 表达。``fold(q)`` 后长度 <2 → ``search`` 返回四组空数组、``total=0``（不 500）。
    """
    if scope not in _VALID_SCOPES:
        raise HTTPException(status_code=400, detail=f"非法 scope：{scope}")
    with db_conn() as conn:
        corpus_docs, corpus_truncated = iter_corpus_docs(conn)
    res = search(q, scope=scope, limit=limit, corpus_docs=corpus_docs)
    # Task 6：`truncated` 语义拆分后**只**表示语料 hard cap 未扫完（真异常）。语料被
    # `iter_corpus_docs` 的 max_docs/max_chars 截断时 `search()` 不可见（它只知注入进来的
    # corpus_docs），故必须在**路由层**落到响应。limit 的每组限量（几乎总发生）不再计入
    # truncated——它由 `search()` 返回的 `groups_total` 表达，前端按组显示「仅显示前 N 条」。
    res["truncated"] = corpus_truncated
    return res
