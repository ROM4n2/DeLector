"""
Regression lock for Reader word click -> sentence syntax sync issue (DFS-DEBUG).
Verifies:
1. inspect(tokenId, sentId) updates syntax view for sentId via renderSyntaxViewForSentence.
2. inspect(tokenId, sentId) preserves activeDrawerTab when user is studying in 'syntax' or other non-vocab tab.
3. switchDrawerTab('syntax') updates syntax view for the active sentence.
4. ShadowPlayer.seekSentence notifies renderSyntaxViewForSentence on sentence advancement.
"""
from pathlib import Path


def test_reader_syntax_sync_contract():
    reader_path = Path("static/js/reader.js")
    assert reader_path.exists(), "static/js/reader.js must exist"
    content = reader_path.read_text(encoding="utf-8")

    # 1. renderSyntaxViewForSentence must exist and be exported
    assert "export function renderSyntaxViewForSentence(" in content, (
        "renderSyntaxViewForSentence must be exported from reader.js"
    )

    # 2. inspect() must invoke renderSyntaxViewForSentence(sentId)
    inspect_start = content.find("export function inspect(")
    assert inspect_start != -1, "inspect function not found"
    inspect_end = content.find("export function ", inspect_start + 25)
    if inspect_end == -1:
        inspect_end = len(content)
    inspect_body = content[inspect_start:inspect_end]

    assert "renderSyntaxViewForSentence(sentId)" in inspect_body, (
        "inspect() must update or sync syntax for the clicked token's sentence"
    )

    # 3. inspect() must not blindly force-switch to 'vocab' if user is on syntax tab
    assert "state.activeDrawerTab" in inspect_body, (
        "inspect() must check state.activeDrawerTab before overriding drawer tab"
    )

    # 4. switchDrawerTab('syntax') must render the active sentence
    tab_start = content.find("export function switchDrawerTab(")
    assert tab_start != -1, "switchDrawerTab not found"
    tab_end = content.find("export function ", tab_start + 25)
    tab_body = content[tab_start:tab_end]
    assert "renderSyntaxViewForSentence" in tab_body, (
        "switchDrawerTab('syntax') must render the active sentence syntax"
    )

    # 5. player.js seekSentence should notify renderSyntaxViewForSentence
    player_path = Path("static/js/player.js")
    assert player_path.exists(), "static/js/player.js must exist"
    player_content = player_path.read_text(encoding="utf-8")
    assert "renderSyntaxViewForSentence" in player_content, (
        "ShadowPlayer.seekSentence must notify renderSyntaxViewForSentence on seek/next/prev"
    )
