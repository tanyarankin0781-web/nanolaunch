"""AI launch-copy assistant: fetch the product URL, then ask Claude for launch copy.
Without ANTHROPIC_API_KEY it falls back to a metadata-based draft."""
import html
import ipaddress
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
CATS = ["ai-tools", "productivity", "marketing", "dev-tools", "social-media", "design", "saas"]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _check_public(url):
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("Enter a valid http(s) URL")
    for info in socket.getaddrinfo(p.hostname, None):
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("That address is not allowed")


def fetch_page(url):
    opener = urllib.request.build_opener(_NoRedirect)
    for _ in range(4):
        _check_public(url)
        req = urllib.request.Request(url, headers={"User-Agent": "NanolaunchBot/1.0"})
        try:
            with opener.open(req, timeout=8) as r:
                raw = r.read(400_000)
                return raw.decode(r.headers.get_content_charset() or "utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                url = urllib.parse.urljoin(url, e.headers["Location"])
                continue
            raise
    raise ValueError("Too many redirects")


def extract(raw):
    def meta(*names):
        for n in names:
            m = re.search(r'<meta[^>]+(?:name|property)=["\']%s["\'][^>]*content=["\']([^"\']*)' % re.escape(n), raw, re.I) or \
                re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:name|property)=["\']%s["\']' % re.escape(n), raw, re.I)
            if m:
                return html.unescape(m.group(1)).strip()
        return ""
    t = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
    title = html.unescape(t.group(1)).strip() if t else ""
    body = re.sub(r"<(script|style|noscript)[\s\S]*?</\1>", " ", raw, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", body))
    text = re.sub(r"\s+", " ", text).strip()[:5000]
    return {"title": meta("og:title") or title, "desc": meta("og:description", "description"),
            "site": meta("og:site_name"), "text": text}


def fallback(url, info, note):
    host = urllib.parse.urlparse(url).hostname or "product"
    name = (info.get("site") or re.split(r"[|\-–:]", info.get("title") or host)[0]).strip()[:40] or host
    desc = info.get("desc") or info.get("text", "")[:300] or f"{name} is a new product."
    return {"name": name, "tagline": (desc.split(". ")[0])[:70], "description": desc[:600], "category": "saas",
            "features": [], "first_comment": f"Hey everyone! I'm the maker of {name}. Would love your honest feedback.",
            "mode": "basic", "note": note}


def call_claude(url, info, notes):
    key = os.environ.get("ANTHROPIC_API_KEY")
    prompt = (
        "You write launch-platform listings for indie products. Using ONLY the facts below, produce JSON with keys: "
        "name (string), tagline (max 60 chars, concrete, no hype words), description (2 short paragraphs, plain text), "
        f"category (one of {CATS}), features (array of exactly 3 short strings), first_comment (a warm, honest maker comment, 2-3 sentences). "
        "Do not invent customers, numbers or awards. Return JSON only.\n\n"
        f"URL: {url}\nPage title: {info['title']}\nMeta description: {info['desc']}\nMaker notes: {notes}\nPage text: {info['text']}")
    body = json.dumps({"model": MODEL, "max_tokens": 900, "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        out = json.load(r)
    txt = "".join(b.get("text", "") for b in out.get("content", []))
    data = json.loads(re.search(r"\{[\s\S]*\}", txt).group(0))
    data["mode"] = "ai"
    if data.get("category") not in CATS:
        data["category"] = "saas"
    data["features"] = [str(f)[:80] for f in (data.get("features") or [])][:3]
    return data


def generate(url, notes=""):
    try:
        info = extract(fetch_page(url))
    except ValueError:
        raise
    except Exception:
        info = {"title": "", "desc": "", "site": "", "text": ""}
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return call_claude(url, info, notes)
        except Exception as e:
            return fallback(url, info, f"AI request failed ({type(e).__name__}); showing a basic draft.")
    return fallback(url, info, "Basic mode: set ANTHROPIC_API_KEY on the server to get AI-written copy.")
