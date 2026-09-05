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


def test_reader_syntax_ghost_pill_explicit_trigger():
    reader_js = (ROOT / "static" / "js" / "reader.js").read_text(encoding="utf-8")

    # 1. Assert computeArticleSyntaxStats is exported and defined
    assert "export function computeArticleSyntaxStats(" in reader_js, (
        "computeArticleSyntaxStats must be exported in static/js/reader.js"
    )

    # 2. Assert _syntaxHoverTimer is completely eliminated
    assert "_syntaxHoverTimer" not in reader_js, (
        "_syntaxHoverTimer must NOT be present in static/js/reader.js"
    )

    # 3. Assert sentWrapper in reader.js contains explicit button trigger
    expected_btn = '<button class="sent-syntax-btn" onclick="event.stopPropagation(); openSyntaxDrawerForSentence(${Number(sent.id)})"'
    assert expected_btn in reader_js, (
        f"sentWrapper in static/js/reader.js must contain {expected_btn}"
    )


def test_render_radar_svg_and_radar_panel_integration():
    reader_js = (ROOT / "static" / "js" / "reader.js").read_text(encoding="utf-8")
    style_css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")

    # 1. Assert renderRadarSvg and saveAndRenderSyntaxRadar are exported
    assert "export function renderRadarSvg(" in reader_js, (
        "renderRadarSvg must be exported from static/js/reader.js"
    )
    assert "export async function saveAndRenderSyntaxRadar(" in reader_js, (
        "saveAndRenderSyntaxRadar must be exported from static/js/reader.js"
    )

    # 2. Assert openSyntaxDrawerForSentence calls saveAndRenderSyntaxRadar
    open_syntax_drawer_start = reader_js.find("export function openSyntaxDrawerForSentence(")
    assert open_syntax_drawer_start != -1, "openSyntaxDrawerForSentence must exist"
    open_syntax_drawer_end = reader_js.find("export function ", open_syntax_drawer_start + 30)
    if open_syntax_drawer_end == -1:
        open_syntax_drawer_end = len(reader_js)
    open_syntax_fn_body = reader_js[open_syntax_drawer_start:open_syntax_drawer_end]
    assert "saveAndRenderSyntaxRadar(" in open_syntax_fn_body, (
        "openSyntaxDrawerForSentence must invoke saveAndRenderSyntaxRadar"
    )

    # 3. Assert CSS styles for radar panel, legend, and labels
    assert ".radar-legend" in style_css, ".radar-legend must be present in static/style.css"
    assert "#grammar-radar-panel" in style_css or ".grammar-radar-panel" in style_css, (
        "#grammar-radar-panel or .grammar-radar-panel must be present in static/style.css"
    )
    assert ".radar-label" in style_css or ".radar-axis" in style_css or "radar" in style_css, (
        "Radar styles must be present in static/style.css"
    )

    # 4. Test renderRadarSvg with Node.js execution
    import subprocess
    import json

    # Extract renderRadarSvg and a mock esc function to run in pure Node.js
    radar_fn_start = reader_js.find("export function renderRadarSvg(")
    assert radar_fn_start != -1, "renderRadarSvg definition must exist"
    radar_fn_end = reader_js.find("export async function saveAndRenderSyntaxRadar(", radar_fn_start)
    assert radar_fn_end != -1, "saveAndRenderSyntaxRadar must follow renderRadarSvg"
    radar_fn_code = reader_js[radar_fn_start:radar_fn_end].replace("export function renderRadarSvg", "function renderRadarSvg")

    test_js = f"""
    const esc = (s) => String(s);
    {radar_fn_code}
    const current = {{
      avg_clause_depth: 2.5,
      passive_rate: 0.2,
      konjunktiv_rate: 0.1,
      vl_rate: 0.3,
      sent_count: 10
    }};
    const historical = {{
      avg_clause_depth: 2.0,
      passive_rate: 0.15,
      konjunktiv_rate: 0.05,
      vl_rate: 0.25,
      total_articles: 5
    }};
    const svg = renderRadarSvg(current, historical);
    console.log(JSON.stringify(svg));
    """
    res = subprocess.run(
        ["node", "--input-type=module"],
        input=test_js,
        capture_output=True,
        text=True,
        encoding="utf-8"
    )
    assert res.returncode == 0, f"Node execution failed: {res.stderr}"
    svg_output = json.loads(res.stdout.strip())

    # Verify that the generated SVG contains polygon, labels for 4 axes, current & historical polygons
    assert "<polygon" in svg_output, "SVG must contain <polygon>"
    assert "深度" in svg_output or "avg_clause_depth" in svg_output, "SVG must contain 深度 axis label"
    assert "被动" in svg_output or "passive" in svg_output, "SVG must contain 被动 axis label"
    assert "Konj" in svg_output or "konjunktiv" in svg_output, "SVG must contain Konj axis label"
    assert "VL" in svg_output, "SVG must contain VL axis label"
    # Should contain current polygon with accent and historical with muted/dashed
    assert "var(--accent" in svg_output or "#c14a2b" in svg_output, "SVG must style current polygon with accent"
    assert "stroke-dasharray" in svg_output, "SVG must contain dashed stroke for historical polygon"


