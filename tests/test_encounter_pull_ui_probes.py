# -*- coding: utf-8 -*-
"""遇见区「从电脑导入」（WiFi 内容分发）前端探针（Plan Task 3）。

架构安全边界（ADR-0004 + Plan 全局约束）：
  - 手机前端**只**调本机相对路径 /api/encounter/pull-pack（同源零跨域）；
    出站拉取由手机服务端完成（Android 实例绑回环）。
  - desktop_base 仅作为 POST body 字段，**绝不**在前端拼进 fetch()/api() 直连
    桌面 —— 跨域回归是本架构的关键红线，必须在测试里钉死。

测试分两层：
  1. 静态契约：encounter.js 调对端点 + 用对记忆键；main.js 全局映射齐（防
     HTML onclick 找不到函数 → 死按钮）；index.html 有入口与面板 DOM。
  2. 行为探针（node 直跑真源码，红线 11）：把 encounter-pull.js **逐字节复制**
     成 .mjs 直读，断言地址归一 / 记忆读写 / 数据映射的真实行为（非字符串存在）。
  3. 反例钉：源码中不得出现把 desktop_base 拼进 fetch(/api( 直连桌面的形态。

运行（仓库根）：export PYTHONIOENCODING=utf-8 && python -m pytest tests/test_encounter_pull_ui_probes.py -v
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PULL_SRC = ROOT / "static" / "js" / "encounter-pull.js"
ENCOUNTER_JS = (ROOT / "static" / "js" / "encounter.js").read_text(encoding="utf-8")
MAIN_JS = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

# 单条 ESM 探针：按 ctx.op 分派，import 同目录 encounter-pull.mjs（逐字节复制品）。
_RUNNER = r"""
import fs from "node:fs";
const ctx = JSON.parse(fs.readFileSync(0, "utf8"));
const P = await import("./encounter-pull.mjs");
const out = {};
if (ctx.op === "normalize") {
  try {
    out.value = P.normalizeDesktopBase(ctx.raw);
    out.threw = false;
  } catch (e) {
    out.threw = true;
    out.message = String(e && e.message);
  }
} else if (ctx.op === "readBase") {
  const storage = ctx.falsy ? null : {
    getItem: (k) =>
      ctx.store && Object.prototype.hasOwnProperty.call(ctx.store, k)
        ? ctx.store[k]
        : null,
  };
  out.value = P.readDesktopBase(storage);
} else if (ctx.op === "writeBase") {
  const box = {};
  const storage = ctx.falsy ? null : {
    setItem: (k, v) => {
      box[k] = v;
    },
  };
  out.ok = P.writeDesktopBase(storage, ctx.value);
  out.box = box;
} else if (ctx.op === "mapRows") {
  out.rows = P.mapPackRows(ctx.packs);
} else if (ctx.op === "request") {
  out.body = P.pullPackRequest(ctx.base, ctx.pack);
  out.keys = Object.keys(out.body).sort();
} else if (ctx.op === "consts") {
  out.key = P.DESKTOP_KEY;
  out.endpoint = P.PULL_ENDPOINT;
}
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture
def pull(tmp_path):
    """把真 encounter-pull.js 逐字节复制成 encounter-pull.mjs；缺失即 RED。"""
    if not PULL_SRC.exists():
        pytest.fail("static/js/encounter-pull.js 尚不存在（Task 3 未实现 → RED）")
    dest = tmp_path / "encounter-pull.mjs"
    src_bytes = PULL_SRC.read_bytes()
    dest.write_bytes(src_bytes)
    assert dest.read_bytes() == src_bytes, "encounter-pull.mjs 必须逐字节等于真源码"
    return dest


def _run_node(ctx, pull):
    if not shutil.which("node"):
        pytest.skip("node 不在 PATH 上，跳过 Node 行为探针")
    runner = pull.parent / "_runner.mjs"
    runner.write_text(_RUNNER, encoding="utf-8")
    # 运行前再断言 verbatim：测试跑的一定是线上代码。
    assert pull.read_bytes() == PULL_SRC.read_bytes(), (
        "测试用的 encounter-pull.mjs 必须是 static/js/encounter-pull.js 的逐字节副本"
    )
    res = subprocess.run(
        ["node", str(runner)],
        input=json.dumps(ctx, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    assert res.returncode == 0, "encounter-pull Node 探针执行失败：\n%s\n%s" % (
        res.stdout,
        res.stderr,
    )
    return json.loads(res.stdout)


# ── 行为探针：地址归一 ──────────────────────────────────────────────────────


def test_normalize_strips_trailing_slash(pull):
    """归一：去尾斜杠（含多个）+ 去首尾空白；合法 http(s) 原样保留主机端口。"""
    out = _run_node({"op": "normalize", "raw": "  http://192.168.1.5:8000/  "}, pull)
    assert out["threw"] is False
    assert out["value"] == "http://192.168.1.5:8000"

    out = _run_node({"op": "normalize", "raw": "https://192.168.1.5:8443///"}, pull)
    assert out["value"] == "https://192.168.1.5:8443"


def test_normalize_rejects_missing_scheme(pull):
    """拒绝无 scheme（含只有 scheme、空串、纯主机）→ 抛错且信息是人话。"""
    for raw in ["192.168.1.5:8000", "", "  ", "//192.168.1.5:8000", "ftp://x", "http://"]:
        out = _run_node({"op": "normalize", "raw": raw}, pull)
        assert out["threw"] is True, "应拒绝非法地址: %r" % raw
        assert "http" in out["message"]


# ── 行为探针：记忆读写（localStorage 键 enc.desktop.v1）─────────────────────


def test_memory_roundtrip_and_key(pull):
    """写→读回同一值，且落地键恰为 enc.desktop.v1。"""
    out = _run_node(
        {"op": "writeBase", "value": "http://10.0.0.9:8000"}, pull
    )
    assert out["ok"] is True
    assert out["box"] == {"enc.desktop.v1": "http://10.0.0.9:8000"}

    out = _run_node(
        {"op": "readBase", "store": {"enc.desktop.v1": "http://10.0.0.9:8000"}}, pull
    )
    assert out["value"] == "http://10.0.0.9:8000"


def test_memory_degrades_safely_without_storage(pull):
    """storage 不可用（falsy）：读回空串、写返回 False，均不抛。"""
    out = _run_node({"op": "readBase", "falsy": True}, pull)
    assert out["value"] == ""
    out = _run_node({"op": "writeBase", "falsy": True, "value": "x"}, pull)
    assert out["ok"] is False


def test_memory_missing_key_returns_empty(pull):
    """无记忆键 → 空串（不返回 null / undefined 污染输入框）。"""
    out = _run_node({"op": "readBase", "store": {}}, pull)
    assert out["value"] == ""


# ── 行为探针：货架数据映射 ──────────────────────────────────────────────────


def test_map_rows_keeps_expected_fields(pull):
    """映射保 title/level/word_count/pack_id 四字段完整；word_count 非数字归 0。"""
    packs = [
        {"pack_id": "p1", "title": "Der Kaffee", "level": "A2", "word_count": 120},
        {"pack_id": "p2", "title": "Bahnhof", "level": "A1", "word_count": "n/a"},
    ]
    out = _run_node({"op": "mapRows", "packs": packs}, pull)
    r0, r1 = out["rows"]
    assert r0 == {
        "pack_id": "p1",
        "title": "Der Kaffee",
        "level": "A2",
        "word_count": 120,
    }
    assert r1["pack_id"] == "p2"
    assert r1["title"] == "Bahnhof"
    assert r1["level"] == "A1"
    assert r1["word_count"] == 0  # 非数字归 0


def test_map_rows_drops_unknown_fields(pull):
    """只保白名单 4 字段：多余字段（潜在机密）不得透传。"""
    packs = [
        {
            "pack_id": "p1",
            "title": "T",
            "level": "A2",
            "word_count": 5,
            "pack_json": {"secret": "leak"},
            "internal_path": "/etc/passwd",
        }
    ]
    out = _run_node({"op": "mapRows", "packs": packs}, pull)
    assert set(out["rows"][0].keys()) == {
        "pack_id",
        "title",
        "level",
        "word_count",
    }


def test_map_rows_handles_garbage(pull):
    """非数组 / 含非对象元素 → 安全降级（空数组 / 空字段），不抛。"""
    assert _run_node({"op": "mapRows", "packs": None}, pull)["rows"] == []
    assert _run_node({"op": "mapRows", "packs": "nope"}, pull)["rows"] == []
    out = _run_node({"op": "mapRows", "packs": [None, 3]}, pull)
    assert out["rows"][0]["pack_id"] == ""
    assert out["rows"][1]["word_count"] == 0


# ── 行为探针：请求体构造（pack_id 可选）─────────────────────────────────────


def test_request_body_listing_vs_import(pull):
    """pack_id 省略 → 只带 desktop_base（代理货架）；带 pack_id → 追加字段。"""
    out = _run_node({"op": "request", "base": "http://10.0.0.9:8000"}, pull)
    assert out["keys"] == ["desktop_base"]
    assert out["body"]["desktop_base"] == "http://10.0.0.9:8000"

    out = _run_node(
        {"op": "request", "base": "http://10.0.0.9:8000", "pack": "p1"}, pull
    )
    assert out["keys"] == ["desktop_base", "pack_id"]
    assert out["body"]["pack_id"] == "p1"


def test_constants_key_and_endpoint(pull):
    """常量：记忆键 enc.desktop.v1；端点为本机相对路径（不含 scheme/主机）。"""
    out = _run_node({"op": "consts"}, pull)
    assert out["key"] == "enc.desktop.v1"
    assert out["endpoint"] == "/api/encounter/pull-pack"
    assert out["endpoint"].startswith("/")  # 相对路径 = 同源


# ── 静态契约：encounter.js 接线 ─────────────────────────────────────────────


def test_encounter_js_calls_local_pull_endpoint():
    """encounter.js 必须调本机 /api/encounter/pull-pack（且经 encounter-pull 模块）。"""
    assert "./encounter-pull.js" in ENCOUNTER_JS
    assert "PULL_ENDPOINT" in ENCOUNTER_JS
    assert "/api/encounter/pull-pack" in PULL_SRC.read_text(encoding="utf-8")


def test_encounter_js_uses_fixed_desktop_key():
    """记忆键固定 enc.desktop.v1，且只在 encounter-pull.js 里以常量形式出现。"""
    assert 'enc.desktop.v1' in PULL_SRC.read_text(encoding="utf-8")


def test_main_js_exposes_pull_entrypoints_globally():
    """新入口函数必须挂进 main.js 全局映射，否则 HTML 的 onclick 找不到 → 死按钮。"""
    for api_name, global_name in (
        ("togglePullPanel", "encounterTogglePullPanel"),
        ("cancelPull", "encounterCancelPull"),
        ("connectDesktop", "encounterConnectDesktop"),
    ):
        assert api_name in MAIN_JS, "main.js 未 import %s" % api_name
        assert global_name in MAIN_JS, "main.js 未把 %s 挂全局" % global_name


def test_index_has_pull_entry_and_panel():
    """index.html：列表页有「从电脑导入」入口 + 面板 DOM（地址框/连接/列表/错误行）。"""
    assert "从电脑导入" in INDEX
    assert "encounterTogglePullPanel()" in INDEX
    assert 'id="encounter-pull-panel"' in INDEX
    assert 'id="enc-pull-base"' in INDEX
    assert 'id="enc-pull-connect"' in INDEX
    assert 'id="encounter-pull-list"' in INDEX
    assert 'id="enc-pull-error"' in INDEX
    # 引导小字：指向电脑端背词同步面板查 IP
    assert "背词同步" in INDEX


def test_index_entry_reuses_add_form_styling():
    """入口与面板复用既有类名/视觉族系（不另造风格）。

    断言拉取入口按钮与既有「＋ 加文本」入口同为 `btn btn-accent` 视觉族系，
    且面板复用加文本表单的 `encounter-add-form` 类。
    """
    assert 'id="encounter-pull-toggle"' in INDEX
    pull_btn = INDEX.split('id="encounter-pull-toggle"')[1]
    pull_btn = pull_btn[: pull_btn.index(">")]
    assert 'class="btn btn-accent"' in pull_btn
    panel = INDEX.split('id="encounter-pull-panel"')[1]
    panel = panel[: panel.index(">")]
    assert "encounter-add-form" in panel


# ── 反例钉：防跨域回归（本架构关键安全边界）─────────────────────────────────


def _strip_js_comments(src):
    """剥掉 // 与 /* */ 注释，只对真实代码做跨域回归断言（注释可解释约定）。"""
    out = []
    i = 0
    n = len(src)
    while i < n:
        if src[i : i + 2] == "/*":
            j = src.find("*/", i + 2)
            i = (j + 2) if j >= 0 else n
        elif src[i : i + 2] == "//":
            j = src.find("\n", i + 2)
            i = j if j >= 0 else n
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


def test_no_direct_cross_origin_fetch_to_desktop_base():
    """红线：前端源码**不得**把 desktop_base 拼进 fetch()/api() 直连桌面。

    检测真实调用形态：fetch(desktop… / fetch(`${desktop… / api(desktop… /
    api(`${base}… —— 一旦出现即跨域回归（出站必须由手机服务端做）。
    """
    for name, src in (
        ("encounter.js", ENCOUNTER_JS),
        ("encounter-pull.js", PULL_SRC.read_text(encoding="utf-8")),
    ):
        code = _strip_js_comments(src)
        banned = [
            r"fetch\s*\(\s*desktop",
            r"fetch\s*\(\s*`\s*\$\{\s*desktop",
            r"fetch\s*\(\s*`\s*\$\{\s*base",
            r"api\s*\(\s*desktop",
            r"api\s*\(\s*`\s*\$\{\s*desktop",
            r"api\s*\(\s*`\s*\$\{\s*base",
        ]
        for pat in banned:
            assert not re.search(pat, code), (
                "%s 出现直连桌面的跨域调用（%s）——出站必须由手机服务端做" % (name, pat)
            )


def test_frontend_never_builds_absolute_desktop_url():
    """encounter-pull.js 不得含 http:// 字面量拼装逻辑（仅校验允许 http(s) 前缀）。

    纯逻辑模块只归一/校验地址，不发起请求；任何把 scheme+host 拼成请求 URL
    的形态都应缺席。
    """
    code = _strip_js_comments(PULL_SRC.read_text(encoding="utf-8"))
    for pat in (r"fetch\s*\(", r"\bapi\s*\(", r"XMLHttpRequest", r"\.open\s*\("):
        assert not re.search(pat, code), (
            "encounter-pull.js 是纯逻辑模块，不应发起任何请求（命中 %s）" % pat
        )
