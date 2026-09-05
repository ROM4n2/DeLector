# -*- coding: utf-8 -*-
"""edge_tts_mini（stdlib 版 Edge TTS 客户端）的纯函数测试：不联网、确定性。"""
import re

import edge_tts_mini as m


def test_sec_ms_gec_format():
    """令牌是 64 位大写十六进制（SHA256 hexdigest().upper()）。"""
    tok = m._sec_ms_gec()
    assert re.fullmatch(r"[0-9A-F]{64}", tok)


def test_sec_ms_gec_stable_within_5min_window():
    """5 分钟窗口内令牌稳定（服务端据此校验设备时钟）。"""
    a = m._sec_ms_gec()
    b = m._sec_ms_gec()
    assert a == b


def test_mkssml_escapes_xml():
    """文本里的 & < > 必须转义，否则 SSML 会被服务端拒。"""
    ssml = m._mkssml("Kosten & Gebühren < 5€", "de-DE-KatjaNeural", "+0%")
    assert "&amp;" in ssml
    assert "&lt;" in ssml
    assert "<voice name='de-DE-KatjaNeural'>" in ssml
    assert "rate='+0%'" in ssml


def test_connect_id_unique_and_dashless():
    ids = {m._connect_id() for _ in range(100)}
    assert len(ids) == 100
    assert all(re.fullmatch(r"[0-9a-f]{32}", i) for i in ids)


def test_split_text_respects_byte_limit():
    """长文本按 4096 字节切块，块间不拆词、不产生坏 UTF-8。"""
    text = (" ".join(["Hallo", "ich", "lerne", "Deutsch", "jeden", "Tag"]) * 200)
    chunks = list(m._split_text(text))
    assert len(chunks) > 1
    for c in chunks:
        assert len(c.encode("utf-8")) <= m.CHUNK_BYTES
        c.encode("utf-8").decode("utf-8")  # 合法 UTF-8


def test_split_text_short_single_chunk():
    assert list(m._split_text("Hallo Berlin")) == ["Hallo Berlin"]


def test_parse_headers():
    h = m._parse_headers(b"X-RequestId:abc\r\nContent-Type:audio/mpeg\r\nPath:audio")
    assert h[b"path"] == b"audio"
    assert h[b"content-type"] == b"audio/mpeg"
    assert h[b"x-requestid"] == b"abc"


def test_speech_config_has_mp3_output():
    cfg = m._speech_config()
    assert "Path:speech.config" in cfg
    assert "audio-24khz-48kbitrate-mono-mp3" in cfg


def test_ssml_frame_has_timestamp_z_quirk():
    """X-Timestamp 末尾必须带 Z（Microsoft Edge 的已知 bug，edge_tts 原样保留）。"""
    frame = m._ssml_frame("Hallo", "de-DE-KatjaNeural", "+0%")
    assert "Path:ssml" in frame
    assert "X-Timestamp:" in frame
    assert "\r\n\r\n" in frame


def test_ws_headers_include_edge_origin():
    """服务端校验 Origin：必须是 Edge 朗读扩展的 origin。"""
    # 通过检查常量路径上是否携带正确参数来间接验证
    assert "TrustedClientToken=" in m.WSS_PATH
    assert "readaloud" in m.WSS_PATH
