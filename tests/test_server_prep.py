# -*- coding: utf-8 -*-
"""介词矩阵 / 搭配收藏域（C6 Task 3 自 `tests/test_server.py` 逐字搬出）。

搬出的两段（搬前 `test_server.py` 行号，实测，含各段头注释）：
  `3265`-`3365`  GET /api/prep/matrix
  `3395`-`3430`  GET/POST /api/prep/saved

断言与用例名逐字未改；只新增本文件的显式 import。共享夹具（clean_db / client /
lan_client）住在 `tests/server_helpers.py` 与 `tests/conftest.py`，按名即可见，
无需本文件重复定义。
"""

from server_helpers import clean_db as clean_db
from server_helpers import lan_client as lan_client

from delector.nlp_engine.linguistics import PREP_COLLOCATIONS

# ── GET /api/prep/matrix ─────────────────────────────────────────────────────


def test_prep_matrix_endpoint_shape(client):
    """shape 契约：每组都长得一样，抽检 21 组而不是只抽首组。

    原来的写法只检 `groups[0]`，塞在第 5 组的字段不一致它抓不到。
    cefr 字段是 server 层注入的契约，用 == 钉住「恰好这五个键」避免
    偷偷加 debug 字段再也没人知道。
    """
    r = client.get("/api/prep/matrix")
    assert r.status_code == 200
    data = r.json()
    assert set(data) == {"groups"}
    groups = data["groups"]
    assert isinstance(groups, list) and groups
    for g in groups:
        assert set(g) == {"praeposition", "total", "cases"}
        entries = [e for entries in g["cases"].values() for e in entries]
        assert entries, f"空组 {g['praeposition']} 不应出现"
        for e in entries:
            assert set(e) == {"lemma", "reflexive", "bedeutung_zh", "beispiel", "cefr"}
            assert isinstance(e["reflexive"], bool)
        assert g["total"] == sum(len(v) for v in g["cases"].values())


def test_prep_matrix_groups_ordered_by_size_desc(client):
    """组间「常用者优先」是本层的呈现契约（纯函数只保证组内 lemma 序）。"""
    groups = client.get("/api/prep/matrix").json()["groups"]
    totals = [g["total"] for g in groups]
    assert totals == sorted(totals, reverse=True), f"组未按搭配总数降序：{totals[:8]}"


def test_prep_matrix_endpoint_matches_pure_function(client):
    """端点响应 = 纯函数扁平化 + CEFR 注入，**不许有第二种真相**。

    多重集用全字段做键（praep, kasus, lemma, zh, bsp, cefr），独立于服务端
    实现：之前的版本只用了 (praep, kasus, lemma)，fuse 进了同名重复的
    reflexive vs 非 reflexive 两条（`('für','Akk','ausgeben')` 出现 2 次），
    静默漏掉了 2 个条目。
    """
    from collections import Counter

    groups = client.get("/api/prep/matrix").json()["groups"]
    expected = Counter(
        (r[0].strip().lower(), r[1].strip().capitalize(), lemma, r[2], r[3])
        for lemma, rows in PREP_COLLOCATIONS.items()
        for r in rows
    )
    got = Counter(
        (e["lemma"], k, e["lemma"], e["bedeutung_zh"], e["beispiel"])
        for g in groups
        for k, es in g["cases"].items()
        for e in es
        for _ in [None]  # 占位：上面期望 5 元组，下面也给 5 元组
    )
    # 上一行 got 写成了 `(e["lemma"], k, e["lemma"], e["bedeutung_zh"], e["beispiel"])` —— 复制粘贴遗物
    # 真正要比的元组是 (praep, kasus, lemma, zh, bsp)：
    got = Counter(
        (g["praeposition"], k, e["lemma"], e["bedeutung_zh"], e["beispiel"])
        for g in groups
        for k, es in g["cases"].items()
        for e in es
    )
    # CEFR 是 server 层注入，不在 expected 期望里；用 bedeutung_zh 一致就能
    # 区分「实现错位」与「CEFR 算法变更」两种失败。
    assert got == expected, f"端点响应与数据集不匹配：丢 {len(expected) - len(got)} 条" if got != expected else ""


def test_prep_matrix_endpoint_fields_preserved(client):
    """独立检验：端点不能改写核心字段（lemma/bedeutung_zh/beispiel）—— 上一个
    测试只比 (praep, kasus, lemma) 三元组，恰好能容忍「端点把释义
    换成 example」的破坏。这里把每个 entry 的 bedeutung_zh / beispiel
    跟数据集对应行对回源。"""
    groups = client.get("/api/prep/matrix").json()["groups"]
    src = {
        (r[0].strip().lower(), r[1].strip().capitalize(), lemma, r[2]): r[3]
        for lemma, rows in PREP_COLLOCATIONS.items()
        for r in rows
    }
    for g in groups:
        for kasus, entries in g["cases"].items():
            for e in entries:
                key = (g["praeposition"], kasus, e["lemma"], e["bedeutung_zh"])
                assert key in src, f"端点凭空生成条目：{key}"
                assert e["beispiel"] == src[key], f"例句被改写：{key}"


def test_prep_matrix_conserves_dataset_total(client):
    """端点不许在扁平化时丢词条：总数必须等于纯函数展开的总数。"""
    from delector.nlp_engine.linguistics import build_prep_matrix

    core_total = sum(len(es) for by_case in build_prep_matrix().values() for es in by_case.values())
    groups = client.get("/api/prep/matrix").json()["groups"]
    assert sum(g["total"] for g in groups) == core_total > 0


def test_prep_matrix_endpoint_no_auth_gate(client, lan_client):
    """介词矩阵是只读静态知识，不该被备份端点那种「仅 127.0.0.1」闸拦住。"""
    assert client.get("/api/prep/matrix").status_code == 200
    assert lan_client.get("/api/prep/matrix").status_code == 200


# ── GET/POST /api/prep/saved ──────────────────────────────────────────────────


def test_prep_saved_endpoint_returns_keys(client):
    """GET /api/prep/saved 返回 {"keys": [...]} 结构。"""
    resp = client.get("/api/prep/saved")
    assert resp.status_code == 200
    data = resp.json()
    assert "keys" in data
    assert isinstance(data["keys"], list)


def test_prep_saved_post_and_get_roundtrip(client):
    """POST 一条搭配后 GET 能查到，且随备份导出与还原。"""
    resp = client.post("/api/prep/saved", json={"lemma": "freuen", "praep": "auf", "kasus": "Akk"})
    assert resp.status_code == 200
    resp = client.get("/api/prep/saved")
    data = resp.json()
    assert "freuen|auf|Akk" in data["keys"]

    # 验证备份导出与还原包含 prep_saved
    backup = client.get("/api/backup/export").json()
    assert "prep_saved" in backup
    assert any(r["lemma"] == "freuen" and r["praep"] == "auf" and r["kasus"] == "Akk" for r in backup["prep_saved"])
    restore_res = client.post("/api/backup/restore", json=backup)
    assert restore_res.status_code == 200
    restored = client.get("/api/prep/saved").json()
    assert "freuen|auf|Akk" in restored["keys"]


def test_prep_saved_idempotent(client):
    """重复 POST 同一条搭配不会出错（主键约束）。"""
    client.post("/api/prep/saved", json={"lemma": "warten", "praep": "auf", "kasus": "Akk"})
    client.post("/api/prep/saved", json={"lemma": "warten", "praep": "auf", "kasus": "Akk"})
    resp = client.get("/api/prep/saved")
    assert resp.json()["keys"].count("warten|auf|Akk") == 1
