from pathlib import Path


ROOT = Path(__file__).parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
WRITER = (ROOT / "static" / "js" / "writer.js").read_text(encoding="utf-8")
STYLE = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


def test_mobile_writer_has_panel_sheet_controls():
    assert 'id="writer-mobile-panel-trigger"' in INDEX
    assert 'id="writer-mobile-panel-sheet"' in INDEX
    assert "writer-mobile-panel-sheet" in STYLE


def test_writer_supports_tap_to_open_error_details():
    assert "editor.addEventListener('click'" in WRITER
    assert "selectWriterSpan" in WRITER


def test_android_disables_inlay_hints_by_default():
    assert "navigator.userAgent" in WRITER
    assert "inlayEnabled" in WRITER


def test_static_assets_are_bumped_for_v4_3():
    assert 'src="/js/main.js?v=4.4.3"' in INDEX
    assert "delector-static-v4.4.3" in (ROOT / "static" / "sw.js").read_text(encoding="utf-8")
    gradle = (ROOT / "android" / "app" / "build.gradle").read_text(encoding="utf-8")
    assert 'versionCode 40400' in gradle
    assert 'versionName "4.4.0"' in gradle
