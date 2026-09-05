"""语料句法复杂度雷达 (Grammatik-Radar) 前端面板契约测试。"""

from pathlib import Path

ROOT = Path(__file__).parent
INDEX_HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")


def test_radar_panel_present_in_syntax_drawer():
    # 1. Assert that #d-tab-syntax still exists so manual tab switching remains backwards-compatible
    assert 'id="d-tab-syntax"' in INDEX_HTML, "Tab switch button #d-tab-syntax must exist for backward compatibility"

    # 2. Assert that #drawer-syntax-section exists
    assert 'id="drawer-syntax-section"' in INDEX_HTML, "#drawer-syntax-section must be present in index.html"

    # Extract the content of #drawer-syntax-section
    syntax_section_start = INDEX_HTML.find('id="drawer-syntax-section"')
    assert syntax_section_start != -1

    # Find the next drawer section or end of drawer
    next_section_start = INDEX_HTML.find('id="drawer-note-section"', syntax_section_start)
    assert next_section_start != -1, "Next section #drawer-note-section should follow syntax section"

    syntax_drawer_html = INDEX_HTML[syntax_section_start:next_section_start]

    # 3. Assert that #drawer-syntax-section contains <details id="grammar-radar-panel"
    assert '<details id="grammar-radar-panel"' in syntax_drawer_html or 'id="grammar-radar-panel"' in syntax_drawer_html, (
        "#grammar-radar-panel must be present inside #drawer-syntax-section"
    )

    # 4. Assert that inside #grammar-radar-panel, there is <svg id="grammar-radar-svg" and <div id="grammar-radar-stats"
    radar_panel_start = syntax_drawer_html.find('id="grammar-radar-panel"')
    assert radar_panel_start != -1
    radar_panel_end = syntax_drawer_html.find('</details>', radar_panel_start)
    assert radar_panel_end != -1, "#grammar-radar-panel details element must be closed"

    radar_panel_html = syntax_drawer_html[radar_panel_start:radar_panel_end]

    assert '<svg id="grammar-radar-svg"' in radar_panel_html, "<svg id=\"grammar-radar-svg\"> must exist within #grammar-radar-panel"
    assert '<div id="grammar-radar-stats"' in radar_panel_html, "<div id=\"grammar-radar-stats\"> must exist within #grammar-radar-panel"
