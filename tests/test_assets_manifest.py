# -*- coding: utf-8 -*-
"""静态资源内容指纹：构建期 / 运行期必须用同一套算法，否则「旧 UI」无法判定。"""

from pathlib import Path

from delector.core.assets_manifest import (
    ASSET_STAMP_META_NAME,
    compute_assets_fingerprint,
    inject_js_stamp,
    inject_stamp_meta,
    iter_asset_files,
)

INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <title>DeLector</title>
  </head>
  <body><script type="module" src="/js/main.js"></script></body>
</html>
"""


def _make_static(root: Path) -> Path:
    static = root / "static"
    (static / "js").mkdir(parents=True)
    (static / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (static / "style.css").write_text(":root{--a:1}", encoding="utf-8")
    (static / "js" / "main.js").write_text("export const a = 1;", encoding="utf-8")
    (static / "js" / "build-stamp.js").write_text(
        'export const BUILD_STAMP = "";', encoding="utf-8"
    )
    return static


def test_fingerprint_is_stable_and_content_addressed(tmp_path):
    static = _make_static(tmp_path)

    first = compute_assets_fingerprint(static, use_cache=False)
    assert len(first) == 12 and all(c in "0123456789abcdef" for c in first)
    assert compute_assets_fingerprint(static, use_cache=False) == first

    # 只改 CSS 的一个值，指纹必须变（这正是「代码改了但页面没变」要能证伪的点）。
    (static / "style.css").write_text(":root{--a:2}", encoding="utf-8")
    assert compute_assets_fingerprint(static, use_cache=False) != first


def test_fingerprint_ignores_its_own_stamp_files(tmp_path):
    static = _make_static(tmp_path)
    baseline = compute_assets_fingerprint(static, use_cache=False)

    (static / "asset-fingerprint.txt").write_text(baseline, encoding="utf-8")
    (static / "build-info.json").write_text('{"assets_fingerprint": "x"}', encoding="utf-8")
    assert compute_assets_fingerprint(static, use_cache=False) == baseline


def test_injected_stamp_does_not_change_fingerprint(tmp_path):
    """写戳前后指纹必须一致，否则构建期与运行期会互报失配。"""
    static = _make_static(tmp_path)
    before = compute_assets_fingerprint(static, use_cache=False)

    inject_stamp_meta(static / "index.html", before)
    html = (static / "index.html").read_text(encoding="utf-8")
    assert f'<meta name="{ASSET_STAMP_META_NAME}" content="{before}" />' in html
    assert compute_assets_fingerprint(static, use_cache=False) == before

    # 覆盖已有戳也必须幂等（不能越注入越多）。
    inject_stamp_meta(static / "index.html", "deadbeefcafe")
    html = (static / "index.html").read_text(encoding="utf-8")
    assert html.count(f'name="{ASSET_STAMP_META_NAME}"') == 1
    assert "deadbeefcafe" in html
    assert compute_assets_fingerprint(static, use_cache=False) == before


def test_placeholder_stamp_normalizes_like_real_stamp(tmp_path):
    """占位戳与真戳都必须被整枚剔除，算出的指纹一致。"""
    static = _make_static(tmp_path)
    html = (static / "index.html").read_text(encoding="utf-8")
    html = html.replace(
        "</head>",
        f'<meta name="{ASSET_STAMP_META_NAME}" content="__DELECTOR_ASSETS__" />\n  </head>',
    )
    (static / "index.html").write_text(html, encoding="utf-8")
    with_placeholder = compute_assets_fingerprint(static, use_cache=False)

    inject_stamp_meta(static / "index.html", "0123456789ab")
    assert compute_assets_fingerprint(static, use_cache=False) == with_placeholder


def test_js_stamp_does_not_change_fingerprint(tmp_path):
    """JS 戳与 HTML 戳一样不能自指；写戳前后指纹必须一致。"""
    static = _make_static(tmp_path)
    before = compute_assets_fingerprint(static, use_cache=False)

    inject_js_stamp(static / "js" / "build-stamp.js", before)
    text = (static / "js" / "build-stamp.js").read_text(encoding="utf-8")
    assert f'BUILD_STAMP = "{before}"' in text
    assert compute_assets_fingerprint(static, use_cache=False) == before


def test_file_order_is_platform_independent(tmp_path):
    """遍历顺序必须按相对路径码位，不能跟着平台走。

    回归：Windows 的 ``sorted(Path)`` 大小写不敏感，``icons/lucide-sprite.svg`` 排在
    ``icons/README.md`` 前面；Android/Linux 上相反 ⇒ 构建期写进页面的戳与设备运行期
    现算的指纹永不相等（实测 3061541188d7 ≠ cc1efb3c37f8）。
    """
    static = _make_static(tmp_path)
    icons = static / "icons"
    icons.mkdir()
    (icons / "README.md").write_text("readme", encoding="utf-8")
    (icons / "lucide-sprite.svg").write_text("<svg/>", encoding="utf-8")

    expected = sorted(
        [
            "icons/README.md",
            "icons/lucide-sprite.svg",
            "index.html",
            "js/build-stamp.js",
            "js/main.js",
            "style.css",
        ]
    )
    assert [rel.as_posix() for rel, _ in iter_asset_files(static)] == expected


def test_missing_directory_returns_empty_string(tmp_path):
    assert compute_assets_fingerprint(tmp_path / "nope", use_cache=False) == ""
