# -*- coding: utf-8 -*-
"""SSRF 判定与 IP 过滤、网页正文提取与安全抓取、RSS 订阅解析。"""
import re
import html
import socket
import ipaddress
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from typing import List, Dict, Any, Tuple
from fastapi import HTTPException
import httpx


def _resolve_ssrf_targets(ip_obj):
    """把地址归一到「数据包真正会打到的目的地」，再交给闸门判定。

    IPv4-mapped(`::ffff:0:0/96`)、6to4(`2002::/16`)、Teredo(`2001::/32`) 三种
    IPv6 地址的真实目的主机是**内嵌的那个 IPv4**，`is_private` / `is_reserved`
    这些旗标描述的是外层包装。直接拿外层旗标判定会同时犯两个方向的错，
    两个方向本机都实测过：

    - **误放（真 SSRF 通道）**：`2002:c0a8:0101::1` 外层 `is_global` 为真，
      而它路由到 `192.168.1.1`；`2002:7f00:0001::1` 路由到 `127.0.0.1`。
      旧写法对这两个一律放行。
    - **误拒**：Teredo 落在 ipaddress 的私有段清单 `2001::/23` 里，于是
      Windows 上开着 Teredo 隧道的用户连正常公网站点都进不来
      （本机 `www.dw.com` 曾解析出 `2001::b92d:7b9`，URL 导入对所有站点全废）；
      `::ffff:8.8.8.8` 被判 `is_reserved`，同理。

    Teredo 只校验 client 字段（数据包实际封装去的那个公网 IPv4）；server 字段
    仅在非全零时才校验 —— 观测到的真实 Teredo 地址 server 段就是全零，
    把全零当 `is_unspecified` 拒掉等于没修。
    """
    mapped = getattr(ip_obj, "ipv4_mapped", None)
    if mapped is not None:
        return [mapped]
    sixtofour = getattr(ip_obj, "sixtofour", None)
    if sixtofour is not None:
        return [sixtofour]
    teredo = getattr(ip_obj, "teredo", None)
    if teredo is not None:
        server_ip, client_ip = teredo
        targets = [client_ip]
        if not server_ip.is_unspecified:
            targets.append(server_ip)
        return targets
    return [ip_obj]


# 自己钉住的 IPv6 特殊用途段：**不能把安全边界外包给 `ipaddress` 的私有段表**，
# 那张表会随 Python 补丁版本变化。3.11.8 里有一条粗粒度的 `2001::/23`，把整个
# IETF Protocol Assignments 块兜住了；3.11.16 换成细粒度条目后 `2001:20::/28`
# (ORCHIDv2) 掉了出来，闸门就此放行 —— 同一份代码，同一个 3.11 大版本，
# 判定结果相反（本机绿、CI 红，正是这条测试抓到的）。
#
# `2001::/23` 整块是 IETF 协议保留、永不会分配给网站，所以规则是「落在这块里
# 就拒，除 Teredo 外」—— Teredo 在上面已经解包成内嵌的目的 IPv4 了。
# 这样比枚举子段更稳：将来 IANA 往这块里加新用途，无需改代码。
# 代价是 `2001:3::/32`(AMT)、`2001:4:112::/48`(AS112-v6) 这类 IANA 标为可全球
# 路由的锚播基础设施段也一并拒掉 —— 对「抓一篇文章」这个用途没有损失，
# 而 SSRF 闸拿不准时就该往拒绝的方向倒。
_IETF_PROTOCOL_ASSIGNMENTS = ipaddress.ip_network("2001::/23")
_IPV6_DENY_PREFIXES = tuple(ipaddress.ip_network(n) for n in (
    "2001:db8::/32",      # 文档示例段（在 /23 之外，要单列）
    "100::/64",           # discard-only
    "5f00::/16",          # SRv6 SID
    "64:ff9b:1::/48",     # 本地用 IPv4/IPv6 转换
))


def _is_blocked_addr(ip_obj) -> bool:
    for t in _resolve_ssrf_targets(ip_obj):
        if (t.is_private or t.is_loopback or t.is_link_local
                or t.is_reserved or t.is_multicast or t.is_unspecified):
            return True
        if t.version == 6 and (t in _IETF_PROTOCOL_ASSIGNMENTS
                               or any(t in net for net in _IPV6_DENY_PREFIXES)):
            return True
    return False


def is_safe_public_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        if hostname.lower().strip(".") == "localhost":
            return False

        for info in socket.getaddrinfo(hostname, None):
            if _is_blocked_addr(ipaddress.ip_address(info[4][0])):
                return False
        return True
    except Exception:
        return False


def clean_html_to_article(raw_html: str) -> Tuple[str, str]:
    title_match = re.search(r'<title>(.*?)</title>', raw_html, re.IGNORECASE | re.DOTALL)
    title = html.unescape(title_match.group(1).strip()) if title_match else "Extracted Article"
    title = re.split(r'[-|–]\s*(?:DER SPIEGEL|DW|Tagesschau|ZEIT ONLINE|ZDF|FAZ|SZ|Süddeutsche|Deutschlandfunk)', title)[0].strip()
    
    # Remove script, style, nav, header, footer, etc.
    cleaned = re.sub(r'<(script|style|nav|header|footer|svg|aside|form|button|noscript|figure)[^>]*>.*?</\1>', '', raw_html, flags=re.IGNORECASE | re.DOTALL)
    
    # Prefer <article> block if available
    article_match = re.search(r'<article[^>]*>(.*?)</article>', cleaned, flags=re.IGNORECASE | re.DOTALL)
    scope_html = article_match.group(1) if article_match else cleaned

    paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', scope_html, flags=re.IGNORECASE | re.DOTALL)
    clean_paras = []
    for p in paragraphs:
        txt = re.sub(r'<[^>]+>', '', p)
        txt = html.unescape(txt).strip()
        if len(txt) > 20 and not any(k in txt.lower() for k in ["cookie", "datenschutz", "abonnieren", "newsletter", "all rights reserved", "impressum", "urheberrecht"]):
            clean_paras.append(txt)
            
    if not clean_paras:
        raw_text = re.sub(r'<[^>]+>', ' ', scope_html)
        clean_paras = [html.unescape(line).strip() for line in raw_text.split('\n') if len(line.strip()) > 30]

    body_text = "\n\n".join(clean_paras)
    return title, body_text


# 公网站点间的正常跳转链远短于此；超限视为异常抓取直接中止。
MAX_REDIRECT_HOPS = 5


async def fetch_remote_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8"
    }
    current_url = url
    # 逐跳手动跟随重定向：每一跳都在**发起请求之前**过 SSRF 闸。
    # follow_redirects=True 的写法先打请求、后校验最终 URL——重定向到内网时
    # 内网服务已经收到 GET（盲 SSRF），哪怕响应随后被丢弃。
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        for _hop in range(MAX_REDIRECT_HOPS + 1):
            if not is_safe_public_url(current_url):
                raise HTTPException(400, "禁止访问内网或保留地址 (SSRF Protection)")
            resp = await client.get(current_url, headers=headers)
            if resp.is_redirect:
                location = resp.headers.get("location")
                if not location:
                    raise HTTPException(400, f"无法抓取该网页 (HTTP {resp.status_code}，缺少重定向目标)")
                current_url = str(httpx.URL(current_url).join(location))
                continue
            if resp.status_code != 200:
                raise HTTPException(400, f"无法抓取该网页 (HTTP {resp.status_code})")
            return resp.text
        raise HTTPException(400, "重定向次数过多，已中止抓取")


# --- RSS & News Feeds Integration ---
PRESET_FEEDS = [
    {
        "id": "tagesschau_news",
        "name": "Tagesschau · 德国权威时事",
        "level": "B2-C1",
        "category": "Aktuell",
        "url": "https://www.tagesschau.de/xml/rss2/",
        "description": "德国第一电视台权威时政要闻"
    },
    {
        "id": "tagesschau_ausland",
        "name": "Tagesschau · 国际与环球",
        "level": "B2-C1",
        "category": "Ausland",
        "url": "https://www.tagesschau.de/ausland/index~rss2.xml",
        "description": "全球时事与地缘观察精读"
    },
    {
        "id": "dw_deutsch",
        "name": "DW · 德语时事综合",
        "level": "B1-B2",
        "category": "Lernen",
        "url": "https://rss.dw.com/rdf/rss-de-all",
        "description": "德国之声精选德语新闻文章"
    },
    {
        "id": "dlf_news",
        "name": "Deutschlandfunk · 每日整点新闻",
        "level": "B2-C1",
        "category": "Nachrichten",
        "url": "https://www.deutschlandfunk.de/nachrichten-100.rss",
        "description": "标准德语广播权威每日简讯"
    },
    {
        "id": "spiegel_politik",
        "name": "Spiegel · 政治与深度",
        "level": "C1",
        "category": "Politik",
        "url": "https://www.spiegel.de/politik/index.rss",
        "description": "明镜周刊深度时政报道与分析"
    },
    {
        "id": "zeit_online",
        "name": "Zeit Online · 精选社论",
        "level": "C1",
        "category": "Kultur",
        "url": "https://newsfeed.zeit.de/index",
        "description": "时代周报文化与学术随笔"
    }
]


def parse_rss_feed(xml_text: str) -> List[Dict[str, Any]]:
    items = []
    try:
        root = ET.fromstring(xml_text)
        found_items = [el for el in root.iter() if el.tag.split("}")[-1] == "item"]
        if found_items:
            for item in found_items:
                title = ""
                link = ""
                desc = ""
                pub_date = ""
                for child in item:
                    tag = child.tag.split("}")[-1]
                    if tag == "title" and not title:
                        title = child.text or ""
                    elif tag == "link" and not link:
                        link = child.text or child.get("href", "")
                    elif tag in ("description", "encoded", "summary") and not desc:
                        desc = child.text or ""
                    elif tag in ("pubDate", "date", "updated", "published") and not pub_date:
                        pub_date = child.text or ""
                clean_desc = html.unescape(re.sub(r"<[^>]+>", "", desc)).strip()
                if title and link:
                    items.append({
                        "title": html.unescape(title.strip()),
                        "link": link.strip(),
                        "summary": clean_desc[:220] + ("…" if len(clean_desc) > 220 else ""),
                        "pub_date": pub_date.strip()
                    })
        else:
            found_entries = [el for el in root.iter() if el.tag.split("}")[-1] == "entry"]
            for entry in found_entries:
                title = ""
                link = ""
                desc = ""
                pub_date = ""
                for child in entry:
                    tag = child.tag.split("}")[-1]
                    if tag == "title" and not title:
                        title = child.text or ""
                    elif tag == "link" and not link:
                        link = child.get("href", "") or child.text or ""
                    elif tag in ("summary", "content") and not desc:
                        desc = child.text or ""
                    elif tag in ("updated", "published", "date") and not pub_date:
                        pub_date = child.text or ""
                clean_desc = html.unescape(re.sub(r"<[^>]+>", "", desc)).strip()
                if title and link:
                    items.append({
                        "title": html.unescape(title.strip()),
                        "link": link.strip(),
                        "summary": clean_desc[:220] + ("…" if len(clean_desc) > 220 else ""),
                        "pub_date": pub_date.strip()
                    })
    except Exception:
        pass
    return items


__all__ = [
    "_resolve_ssrf_targets",
    "_IETF_PROTOCOL_ASSIGNMENTS",
    "_IPV6_DENY_PREFIXES",
    "_is_blocked_addr",
    "is_safe_public_url",
    "clean_html_to_article",
    "MAX_REDIRECT_HOPS",
    "fetch_remote_html",
    "PRESET_FEEDS",
    "parse_rss_feed",
]
