# -*- coding: utf-8 -*-
"""标准库版 Microsoft Edge TTS 客户端（edge-tts 的 Android 替代）。

为什么需要：edge-tts 包及其依赖（aiohttp/websockets/...）没有 Android wheel，
Chaquopy 索引里也没有，APK 内 `import edge_tts` 必然失败。桌面端走完整 edge_tts，
安卓端则用本模块复刻同一协议——纯 stdlib（socket/ssl/base64/hashlib），零依赖。

协议（与 edge-tts 6.x/7.x 相同，见 constants.py / communicate.py / drm.py）：
  1. WebSocket 握手到 wss://speech.platform.bing.com/.../edge/v1
  2. 带 Sec-MS-GEC（SHA256(win文件时间向下取整5分钟 + TrustedClientToken) 的十六进制大写）
  3. 先发 speech.config 文本帧，再发 SSML 文本帧
  4. 收二进制音频帧（Path: audio, Content-Type: audio/mpeg），到 turn.end 结束
"""
from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import struct
import time
from xml.sax.saxutils import escape

# 与 edge_tts.constants 保持一致（上游若更换令牌需同步）
TRUSTED_CLIENT_TOKEN = "6A5AA1D4EAFF4E9FB37E23D68491D6F4"
WSS_HOST = "speech.platform.bing.com"
WSS_PATH = (
    "/consumer/speech/synthesize/readaloud/edge/v1"
    f"?TrustedClientToken={TRUSTED_CLIENT_TOKEN}"
)
CHROMIUM_VERSION = "143.0.3650.75"
SEC_MS_GEC_VERSION = f"1-{CHROMIUM_VERSION}"
WIN_EPOCH = 11644473600  # Unix epoch → Windows file time epoch 的秒偏移
# 每块 SSML 文本的字节上限（对齐 edge_tts 的 4096）
CHUNK_BYTES = 4096

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    f" (KHTML, like Gecko) Chrome/{CHROMIUM_VERSION.split('.')[0]}.0.0.0"
    f" Safari/537.36 Edg/{CHROMIUM_VERSION.split('.')[0]}.0.0.0"
)


def _sec_ms_gec(clock_skew: float = 0.0) -> str:
    """按当前时间（Windows 文件时间、向下取整 5 分钟）生成令牌。"""
    ticks = time.time() + clock_skew + WIN_EPOCH
    ticks -= ticks % 300
    ticks *= 1e7  # 秒 → 100 纳秒
    return hashlib.sha256(f"{ticks:.0f}{TRUSTED_CLIENT_TOKEN}".encode("ascii")).hexdigest().upper()


def _connect_id() -> str:
    """无横线的随机 32 位 hex（等价 edge_tts 的 uuid4().hex）。"""
    return os.urandom(16).hex()


def _split_text(text: str):
    """按字节上限切成块；优先在空格处断，避免拆词。"""
    encoded = text.encode("utf-8")
    if len(encoded) <= CHUNK_BYTES:
        yield text
        return
    while len(encoded) > CHUNK_BYTES:
        cut = encoded.rfind(b" ", 0, CHUNK_BYTES)
        if cut < 0:
            cut = CHUNK_BYTES
            while cut > 0 and (encoded[cut] & 0xC0) == 0x80:
                cut -= 1
            if cut == 0:
                raise ValueError("chunk too small")
        yield encoded[:cut].decode("utf-8", errors="ignore").strip()
        encoded = encoded[cut:].lstrip()
    if encoded:
        yield encoded.decode("utf-8", errors="ignore").strip()


def _mkssml(text: str, voice: str, rate: str) -> str:
    return (
        "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>"
        f"<voice name='{voice}'>"
        f"<prosody pitch='+0Hz' rate='{rate}' volume='+0%'>"
        f"{escape(text)}"
        "</prosody>"
        "</voice>"
        "</speak>"
    )


def _speech_config() -> str:
    return (
        "X-Timestamp:" + time.strftime("%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)", time.gmtime())
        + "\r\nContent-Type:application/json; charset=utf-8\r\n"
        "Path:speech.config\r\n\r\n"
        '{"context":{"synthesis":{"audio":{"metadataoptions":{'
        '"sentenceBoundaryEnabled":"true","wordBoundaryEnabled":"false"},'
        '"outputFormat":"audio-24khz-48kbitrate-mono-mp3"}}}}\r\n'
    )


def _ssml_frame(text: str, voice: str, rate: str) -> str:
    ts = time.strftime("%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)", time.gmtime())
    return (
        f"X-RequestId:{_connect_id()}\r\n"
        "Content-Type:application/ssml+xml\r\n"
        f"X-Timestamp:{ts}Z\r\n"  # 注意末尾 Z，Microsoft Edge 的已知怪癖
        "Path:ssml\r\n\r\n"
        f"{_mkssml(text, voice, rate)}"
    )


class _HandshakeError(Exception):
    """WebSocket 升级被拒，携带响应状态与头（用于 403 时钟校准重试）。"""

    def __init__(self, status_line: bytes, headers: dict):
        super().__init__(f"handshake failed: {status_line.decode('latin-1')}")
        self.status_code = int(status_line.split(b" ", 2)[1]) if len(status_line.split(b" ", 2)) > 1 else 0
        self.headers = headers


class _WebSocket:
    """最小 WebSocket 客户端（只支持文本/二进制/close/ping-pong，客户端帧做掩码）。"""

    def __init__(self, host: str, timeout: float = 30.0):
        self._sock = socket.create_connection((host, 443), timeout=timeout)
        self._sock.settimeout(timeout)
        try:
            ctx = ssl.create_default_context()
        except Exception:
            # Android/Chaquopy 的默认证书路径可能不可用，退回不校验证书（仅本地 TTS 合成，非敏感通道）
            ctx = ssl._create_unverified_context()
        self._sock = ctx.wrap_socket(self._sock, server_hostname=host)
        self._buf = b""

    def _read_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("socket closed by peer")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def handshake(self, path: str, host: str) -> None:
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Pragma: no-cache\r\n"
            "Cache-Control: no-cache\r\n"
            "Origin: chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold\r\n"
            f"User-Agent: {_UA}\r\n"
            f"Cookie: muid={os.urandom(16).hex().upper()};\r\n"
            "\r\n"
        )
        self._sock.sendall(req.encode())
        while b"\r\n\r\n" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("handshake: socket closed")
            self._buf += chunk
        head, self._buf = self._buf.split(b"\r\n\r\n", 1)
        lines = head.split(b"\r\n")
        status_line = lines[0]
        if b" 101 " not in status_line:
            headers = {}
            for line in lines[1:]:
                if b":" in line:
                    k, v = line.split(b":", 1)
                    headers[k.strip().lower()] = v.strip()
            raise _HandshakeError(status_line, headers)
        # 剩余可能已有帧数据，保留在缓冲区

    def send_text(self, payload: str) -> None:
        data = payload.encode("utf-8")
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        header = bytearray([0x81])
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        self._sock.sendall(bytes(header) + mask + masked)

    def recv_frame(self):
        """返回 (opcode, payload)。自动处理 ping→pong 与分片续帧。"""
        while True:
            hdr = self._read_exact(2)
            opcode = hdr[0] & 0x0F
            fin = bool(hdr[0] & 0x80)
            n = hdr[1] & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read_exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read_exact(8))[0]
            payload = self._read_exact(n)
            if opcode == 0x9:  # ping
                self._send_ctrl(0xA, payload)
                continue
            if opcode == 0x8:  # close
                raise ConnectionError("websocket closed by peer")
            if not fin and opcode in (0x1, 0x2):
                # 分片：续帧 opcode 0，直到 fin
                acc = bytearray(payload)
                while True:
                    h2 = self._read_exact(2)
                    fin2 = bool(h2[0] & 0x80)
                    n2 = h2[1] & 0x7F
                    if n2 == 126:
                        n2 = struct.unpack(">H", self._read_exact(2))[0]
                    elif n2 == 127:
                        n2 = struct.unpack(">Q", self._read_exact(8))[0]
                    acc += self._read_exact(n2)
                    if fin2:
                        break
                return opcode, bytes(acc)
            return opcode, payload

    def _send_ctrl(self, opcode: int, payload: bytes) -> None:
        header = bytes([0x80 | opcode, len(payload)])
        self._sock.sendall(header + payload)

    def close(self) -> None:
        try:
            self._send_ctrl(0x8, b"")
            self._sock.close()
        except Exception:
            self._sock.close()


def _parse_headers(block: bytes) -> dict:
    headers = {}
    for line in block.split(b"\r\n"):
        if b":" in line:
            k, v = line.split(b":", 1)
            headers[k.strip().lower()] = v.strip()
    return headers


def _rfc2616_ts(date_str: str) -> float:
    """解析 HTTP Date 头为 unix 秒；失败返回 0（视为无需校准）。"""
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%A, %d-%b-%y %H:%M:%S %Z"):
        try:
            return time.mktime(time.strptime(date_str, fmt)) - time.timezone
        except ValueError:
            continue
    return 0.0


def synthesize(text: str, voice: str = "de-DE-KatjaNeural", rate: str = "+0%") -> bytes:
    """合成整段文本，返回 MP3 字节。任一环节失败抛异常（由调用方兜底）。

    403 表示 Sec-MS-GEC 因设备时钟偏差被拒：取服务端 Date 头算偏移，重试一次。
    """
    chunks = list(_split_text(text))
    if not chunks:
        raise ValueError("empty text")

    clock_skew = 0.0
    last_error = None
    for attempt in range(2):
        ws = None
        try:
            path = (
                f"{WSS_PATH}&ConnectionId={_connect_id()}"
                f"&Sec-MS-GEC={_sec_ms_gec(clock_skew)}"
                f"&Sec-MS-GEC-Version={SEC_MS_GEC_VERSION}"
            )
            ws = _WebSocket(WSS_HOST)
            ws.handshake(path, WSS_HOST)
            ws.send_text(_speech_config())
            audio = bytearray()
            for chunk in chunks:
                ws.send_text(_ssml_frame(chunk, voice, rate))
                while True:
                    opcode, payload = ws.recv_frame()
                    if opcode == 0x1:  # text 帧：metadata / turn.end
                        header_end = payload.find(b"\r\n\r\n")
                        if header_end < 0:
                            continue
                        headers = _parse_headers(payload[:header_end])
                        if headers.get(b"path") == b"turn.end":
                            break
                    elif opcode == 0x2:  # 二进制音频帧
                        if len(payload) < 2:
                            continue
                        hlen = int.from_bytes(payload[:2], "big")
                        if hlen > len(payload):
                            continue
                        headers = _parse_headers(payload[2:2 + hlen])
                        if headers.get(b"path") == b"audio" and headers.get(b"content-type") == b"audio/mpeg":
                            audio += payload[2 + hlen:]
            if not audio:
                raise RuntimeError("no audio received")
            return bytes(audio)
        except _HandshakeError as e:
            if e.status_code == 403 and attempt == 0:
                server_ts = _rfc2616_ts(e.headers.get(b"date", b"").decode("latin-1", "ignore"))
                if server_ts:
                    clock_skew = server_ts - time.time()
                    last_error = None
                    continue
            raise
        except Exception as e:
            last_error = e
            if attempt == 0:
                continue
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
    raise RuntimeError(f"edge_tts_mini synthesis failed: {last_error}")


if __name__ == "__main__":
    import sys

    sample = sys.argv[1] if len(sys.argv) > 1 else "Guten Morgen, wie geht es dir heute?"
    out = synthesize(sample)
    print(f"synthesized {len(out)} bytes")
    sys.stdout.buffer.write(out[:64])
    print()
