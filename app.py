"""Nanolaunch: a launch platform for indie products. Run: python app.py  (stdlib only)."""
import json
import mimetypes
import os
import re
import secrets
import time
from html import escape as e
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import ai
import compare_data as cd
import db

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.environ.get("SITE_URL", "http://localhost:8000").rstrip("/")
YEAR = time.strftime("%Y")
PERIODS = {"today": ("Today", 1), "week": ("This week", 7), "month": ("This month", 30), "all": ("All time", 36500)}


# ---------- shared layout ----------
def ago(ts):
    d = int(time.time()) - ts
    for n, s in ((86400, "d"), (3600, "h"), (60, "m")):
        if d >= n:
            return f"{d // n}{s} ago"
    return "just now"


def jsonld(*items):
    return "".join('<script type="application/ld+json">%s</script>' % json.dumps(i).replace("</", "<\\/") for i in items)


def layout(title, desc, body, path="/", user=None, ld="", og_type="website", noindex=False):
    url = SITE + path
    nav = [("/", "Leaderboard"), ("/browse", "Browse"), ("/compare", "Compare"), ("/launch/new", "New launch")]
    links = "".join(f'<a href="{h}"{" aria-current=page" if h == path else ""}>{t}</a>' for h, t in nav)
    if user:
        auth = f'<a class="btn ghost sm" href="/u/{e(user["username"])}">@{e(user["username"])}</a><form method="post" action="/logout"><button class="btn ghost sm">Log out</button></form>'
    else:
        auth = '<a class="btn ghost sm" href="/login">Log in</a><a class="btn sm" href="/signup">Sign up</a>'
    robots = '<meta name="robots" content="noindex">' if noindex else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<meta name="description" content="{e(desc)}"><link rel="canonical" href="{e(url)}">{robots}
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}">
<meta property="og:type" content="{og_type}"><meta property="og:url" content="{e(url)}"><meta property="og:site_name" content="Nanolaunch">
<meta name="twitter:card" content="summary"><meta name="theme-color" content="#05060a">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%236366f1'/%3E%3Cpath d='M9 23V9l7 9 7-9v14' stroke='white' stroke-width='3' fill='none'/%3E%3C/svg%3E">
<link rel="stylesheet" href="/static/style.css">{ld}</head><body>
<header class="top"><div class="wrap bar"><a class="logo" href="/"><span class="mark">N</span><span>Nano<b>launch</b></span></a>
<button class="burger" aria-label="Menu" aria-expanded="false">☰</button>
<nav class="menu" aria-label="Main">{links}<div class="auth">{auth}</div></nav></div></header>
<main class="wrap">{body}</main>
<footer class="foot"><div class="wrap cols">
<div><a class="logo" href="/"><span class="mark">N</span><span>Nano<b>launch</b></span></a><p class="muted">The launch platform for world-class indie products. Free, forever.</p></div>
<div><h4>Platform</h4><a href="/">Leaderboard</a><a href="/browse">Browse products</a><a href="/launch/new">Launch a product</a><a href="/signup">Sign up</a></div>
<div><h4>Compare</h4><a href="/compare">All comparisons</a><a href="/compare/microlaunch">Microlaunch alternative</a><a href="/compare/product-hunt">Product Hunt alternative</a><a href="/compare/uneed">Uneed alternative</a></div>
<div><h4>Categories</h4>{"".join(f'<a href="/browse?cat={s}">{n}</a>' for s, n, _ in db.CATEGORIES[:5])}</div>
</div><div class="wrap muted small">© {YEAR} Nanolaunch. Independent project; not affiliated with the platforms we compare.</div></footer>
<script src="/static/app.js" defer></script></body></html>"""


def card(p, rank=None, voted=False):
    return f"""<article class="item"><span class="rank">{f'#{rank}' if rank else ''}</span>
<a class="logo-box" href="/launch/{p['slug']}" aria-hidden="true" tabindex="-1">{e(p['emoji'])}</a>
<div class="info"><h3><a href="/launch/{p['slug']}">{e(p['name'])}</a></h3><p>{e(p['tagline'])}</p>
<div class="meta"><a class="pill" href="/browse?cat={p['category']}">{e(db.CAT_NAMES.get(p['category'], p['category']))}</a>
<span>💬 {p['ncom']}</span></div></div>{votebtn(p, voted)}</article>"""


def votebtn(p, voted):
    return (f'<form method="post" action="/launch/{p["slug"]}/upvote" class="vote-form"><button class="vote{" on" if voted else ""}" '
            f'aria-label="Upvote {e(p["name"])}" aria-pressed="{str(bool(voted)).lower()}">▲<b>{p["score"]}</b></button></form>')


def query_products(c, uid, days=None, cat=None, search=None, limit=50, maker=None):
    since = int(time.time()) - (days or 36500) * 86400
    sql = """select p.*, (select count(*) from votes v where v.product_id=p.id and v.created>=?) score,
      (select count(*) from comments m where m.product_id=p.id) ncom,
      (select count(*) from votes v where v.product_id=p.id and v.user_id=?) voted from products p where 1=1"""
    args = [since, uid or 0]
    if cat:
        sql += " and p.category=?"; args.append(cat)
    if search:
        sql += " and (p.name like ? or p.tagline like ?)"; args += [f"%{search}%"] * 2
    if maker:
        sql += " and p.maker_id=?"; args.append(maker)
    sql += " order by score desc, p.created desc limit ?"
    args.append(limit)
    return c.execute(sql, args).fetchall()


# ---------- pages ----------
def page_home(c, user, q):
    per = q.get("p", ["week"])[0]
    per = per if per in PERIODS else "week"
    rows = query_products(c, user and user["id"], PERIODS[per][1])
    tabs = "".join(f'<a class="tab{" on" if k == per else ""}" href="/?p={k}">{v[0]}</a>' for k, v in PERIODS.items())
    items = "".join(card(p, i + 1, p["voted"]) for i, p in enumerate(rows))
    stats = c.execute("select (select count(*) from products), (select count(*) from users), (select count(*) from votes)").fetchone()
    cats = "".join(f'<a class="chip" href="/browse?cat={s}">{em} {n}</a>' for s, n, em in db.CATEGORIES)
    comp = "".join(f'<a class="chip" href="/compare/{x["slug"]}">{e(x["name"])} alternative</a>' for x in cd.all_entries())
    body = f"""<section class="hero"><span class="badge">🚀 New products live every week</span>
<h1>The Launch Platform for <span class="grad">World-Class Startups</span></h1>
<p class="lead">Discover, try, and support next-generation products. Launch yours free and let AI draft your listing in seconds.</p>
<div class="cta"><a class="btn lg" href="/launch/new">Launch your product</a><a class="btn ghost lg" href="/browse">Browse products</a></div>
<p class="stats"><b>{stats[0]}</b> products · <b>{stats[1]}</b> makers · <b>{stats[2]}</b> upvotes</p></section>
<div class="grid2"><section aria-labelledby="lb"><div class="row between"><h2 id="lb">Leaderboard</h2><div class="tabs" role="tablist">{tabs}</div></div>
<div class="list">{items or '<p class="empty">No launches in this period yet. Be the first!</p>'}</div></section>
<aside class="side"><div class="box"><h3>Meet the makers 👨‍🚀</h3><p class="muted">Launch free, get structured feedback with Idea and Product ratings.</p><a class="btn sm" href="/signup">Sign up →</a></div>
<div class="box"><h3>Browse by category</h3><div class="chips">{cats}</div></div>
<div class="box"><h3>Looking for an alternative?</h3><p class="muted">See how Nanolaunch stacks up.</p><div class="chips">{comp}</div><p><a href="/compare">All comparisons →</a></p></div></aside></div>
<section class="features"><div class="box"><h3>✨ AI launch copy</h3><p class="muted">Paste your URL and get a tagline, description, features and a first comment.</p></div>
<div class="box"><h3>⭐ Real feedback</h3><p class="muted">Rate the idea and the product separately, not just a thumbs-up.</p></div>
<div class="box"><h3>🆓 Free forever</h3><p class="muted">No paid placements. Rankings come from the community.</p></div></section>"""
    ld = jsonld({"@context": "https://schema.org", "@type": "WebSite", "name": "Nanolaunch", "url": SITE,
                 "potentialAction": {"@type": "SearchAction", "target": SITE + "/browse?q={q}", "query-input": "required name=q"}})
    return layout("Nanolaunch: The Launch Platform for World-Class Startups", "Launch your startup free, get upvotes, ratings and feedback. Discover new indie products and use AI to write your launch copy.", body, "/", user, ld)


def page_browse(c, user, q):
    cat = q.get("cat", [""])[0]
    s = q.get("q", [""])[0].strip()
    rows = query_products(c, user and user["id"], None, cat if cat in db.CAT_NAMES else None, s or None)
    chips = '<a class="chip%s" href="/browse">All</a>' % ("" if cat else " on") + "".join(
        f'<a class="chip{" on" if cat == s_ else ""}" href="/browse?cat={s_}">{em} {n}</a>' for s_, n, em in db.CATEGORIES)
    title = (db.CAT_NAMES.get(cat) + " products") if cat in db.CAT_NAMES else "Browse products"
    body = f"""<h1 class="h1s">{e(title)}</h1><form class="search" action="/browse"><input name="q" value="{e(s)}" placeholder="Search products…" aria-label="Search"><button class="btn">Search</button></form>
<div class="chips pad">{chips}</div><div class="list">{"".join(card(p, None, p["voted"]) for p in rows) or '<p class="empty">Nothing found. Try another search or <a href="/launch/new">launch it yourself</a>.</p>'}</div>"""
    return layout(f"{title} | Nanolaunch", f"Discover {title.lower()} launched by indie makers on Nanolaunch.", body, "/browse", user, noindex=bool(s))


def stars(n):
    return "★" * round(n) + "☆" * (5 - round(n)) if n else "–"


def page_product(c, user, slug, err=""):
    rows = c.execute("select id from products where slug=?", (slug,)).fetchone()
    if not rows:
        return None
    p = c.execute("""select p.*, (select count(*) from votes v where v.product_id=p.id) score,
      (select count(*) from comments m where m.product_id=p.id) ncom,
      (select count(*) from votes v where v.product_id=p.id and v.user_id=?) voted,
      (select username from users where id=p.maker_id) maker from products p where p.id=?""", (user["id"] if user else 0, rows["id"])).fetchone()
    r = c.execute("select avg(idea) i, avg(product) p, count(*) n from ratings where product_id=?", (p["id"],)).fetchone()
    mine = user and c.execute("select * from ratings where product_id=? and user_id=?", (p["id"], user["id"])).fetchone()
    coms = c.execute("select m.*, u.username from comments m join users u on u.id=m.user_id where product_id=? order by created desc", (p["id"],)).fetchall()
    feats = "".join(f"<li>{e(f)}</li>" for f in p["features"].split("|") if f)
    sel = lambda name, cur: f'<select name="{name}" aria-label="{name}">' + "".join(f'<option value="{i}"{" selected" if cur == i else ""}>{i} ★</option>' for i in range(5, 0, -1)) + "</select>"
    rate = (f'<form method="post" action="/launch/{slug}/rate" class="rate"><label>Idea {sel("idea", mine and mine["idea"])}</label><label>Product {sel("product", mine and mine["product"])}</label><button class="btn sm">{"Update" if mine else "Submit"} rating</button></form>'
            if user else '<p class="muted"><a href="/login">Log in</a> to rate this launch.</p>')
    cform = (f'<form method="post" action="/launch/{slug}/comment"><textarea name="body" required maxlength="1000" placeholder="Share feedback with the maker…"></textarea><button class="btn sm">Post comment</button></form>'
             if user else '<p class="muted"><a href="/login">Log in</a> to join the discussion.</p>')
    cl = "".join(f'<div class="cmt"><b><a href="/u/{e(m["username"])}">@{e(m["username"])}</a></b> <span class="muted small">{ago(m["created"])}</span><p>{e(m["body"])}</p></div>' for m in coms)
    body = f"""<nav class="crumbs" aria-label="Breadcrumb"><a href="/">Leaderboard</a> / <a href="/browse?cat={p['category']}">{e(db.CAT_NAMES.get(p['category'], ''))}</a> / {e(p['name'])}</nav>
<article class="pdp"><div class="pdp-head"><div class="logo-box big">{e(p['emoji'])}</div><div class="grow"><h1>{e(p['name'])}</h1><p class="lead">{e(p['tagline'])}</p>
<div class="cta"><a class="btn" href="{e(p['url'])}" target="_blank" rel="noopener nofollow ugc">Visit website ↗</a></div></div>{votebtn(p, p['voted'])}</div>
{f'<p class="err">{e(err)}</p>' if err else ''}
<div class="grid2"><div><h2>About</h2>{"".join(f"<p>{e(x)}</p>" for x in p['description'].split(chr(10)) if x.strip())}
<h2>Key features</h2><ul class="ticks">{feats}</ul><h2>Discussion ({p['ncom']})</h2>{cform}<div class="cmts">{cl or '<p class="empty">No comments yet.</p>'}</div></div>
<aside class="side"><div class="box"><h3>Community ratings</h3><p>Idea <span class="star">{stars(r['i'])}</span> {f"{r['i']:.1f}" if r['n'] else ''}</p><p>Product <span class="star">{stars(r['p'])}</span> {f"{r['p']:.1f}" if r['n'] else ''}</p><p class="muted small">{r['n']} ratings</p>{rate}</div>
<div class="box"><h3>Maker</h3><p><a href="/u/{e(p['maker'])}">@{e(p['maker'])}</a></p><p class="muted small">Launched {ago(p['created'])}</p></div></aside></div></article>"""
    ld = jsonld({"@context": "https://schema.org", "@type": "SoftwareApplication", "name": p["name"], "description": p["tagline"], "url": p["url"], "applicationCategory": "BusinessApplication"},
                {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Leaderboard", "item": SITE + "/"},
                    {"@type": "ListItem", "position": 2, "name": p["name"], "item": f"{SITE}/launch/{slug}"}]})
    return layout(f"{p['name']}: {p['tagline']} | Nanolaunch", f"{p['tagline']}. Read reviews, ratings and discussion for {p['name']} on Nanolaunch.", body, f"/launch/{slug}", user, ld)


def page_new(user, form=None, err=""):
    f = form or {}
    v = lambda k: e(f.get(k, [""])[0]) if f else ""
    opts = "".join(f'<option value="{s}"{" selected" if v("category") == s else ""}>{n}</option>' for s, n, _ in db.CATEGORIES)
    body = f"""<h1 class="h1s">Launch your product</h1><p class="lead">Paste your URL and let AI draft the listing, then edit anything before you publish.</p>
{f'<p class="err">{e(err)}</p>' if err else ''}
<form method="post" action="/launch/new" class="form card-form" id="launch-form">
<label>Website URL<div class="row"><input name="url" id="f-url" type="url" required placeholder="https://yourproduct.com" value="{v('url')}"><button type="button" class="btn" id="ai-btn">✨ Autofill with AI</button></div></label>
<p id="ai-note" class="muted small" role="status"></p>
<label>Product name<input name="name" id="f-name" required maxlength="40" value="{v('name')}"></label>
<label>Tagline <span class="muted small">(max 60)</span><input name="tagline" id="f-tagline" required maxlength="60" value="{v('tagline')}"></label>
<label>Description<textarea name="description" id="f-description" required rows="6" maxlength="2000">{v('description')}</textarea></label>
<label>Category<select name="category" id="f-category">{opts}</select></label>
<label>Key features <span class="muted small">(one per line, up to 3)</span><textarea name="features" id="f-features" rows="3">{v('features')}</textarea></label>
<label>Emoji logo<input name="emoji" id="f-emoji" maxlength="4" value="{v('emoji') or '🚀'}"></label>
<button class="btn lg">Publish launch</button></form>"""
    return layout("Launch your product free | Nanolaunch", "Submit your startup to Nanolaunch for free. Use the AI assistant to write your tagline, description and first comment.", body, "/launch/new", user, noindex=True)


def page_auth(user, mode, err="", vals=None):
    vals = vals or {}
    s = mode == "signup"
    body = f"""<div class="auth-card"><h1 class="h1s">{'Create your account' if s else 'Welcome back'}</h1>
<p class="muted">{'Join the community of makers. Free forever.' if s else 'Log in to upvote, comment and launch.'}</p>{f'<p class="err">{e(err)}</p>' if err else ''}
<form method="post" class="form">{'<label>Username<input name="username" required minlength="3" maxlength="20" pattern="[A-Za-z0-9_]+" value="%s"></label>' % e(vals.get("username", "")) if s else ''}
<label>Email<input name="email" type="email" required value="{e(vals.get('email', ''))}"></label>
<label>Password<input name="password" type="password" required minlength="8"></label><button class="btn lg">{'Sign up' if s else 'Log in'}</button></form>
<p class="muted">{'Already a maker? <a href="/login">Log in</a>' if s else 'New here? <a href="/signup">Create an account</a> · Demo: demo@nanolaunch.dev / demo1234'}</p></div>"""
    return layout(("Sign up" if s else "Log in") + " | Nanolaunch", "Create a free Nanolaunch account to launch products, upvote and comment." if s else "Log in to Nanolaunch.", body, "/signup" if s else "/login", user)


def page_profile(c, user, name):
    u = c.execute("select * from users where username=?", (name,)).fetchone()
    if not u:
        return None
    rows = query_products(c, user and user["id"], None, maker=u["id"])
    body = f"""<div class="pdp-head"><div class="logo-box big">{e(u['username'][0].upper())}</div><div><h1>@{e(u['username'])}</h1><p class="muted">{e(u['bio'])} Joined {ago(u['created'])}.</p></div></div>
<h2>Launches ({len(rows)})</h2><div class="list">{"".join(card(p, None, p["voted"]) for p in rows) or '<p class="empty">No launches yet.</p>'}</div>"""
    return layout(f"@{u['username']} | Nanolaunch", f"Products launched by {u['username']} on Nanolaunch.", body, f"/u/{name}", user, noindex=True)


# ---------- comparison pages ----------
def cta_box(name=None):
    return f"""<section class="cta-band"><h2>Ready to try the better launch flow?</h2><p>{'Switch from ' + e(name) + ' or add Nanolaunch to your launch plan.' if name else 'Launch your product free.'} Paste your URL and our AI drafts your listing in seconds.</p>
<a class="btn lg" href="/signup">Sign up and launch free</a></section>"""


def page_compare_hub(user):
    cards = "".join(f'<a class="box hub" href="/compare/{x["slug"]}"><h3>Nanolaunch vs {e(x["name"])}</h3><p class="muted">{e(x["blurb"])}</p><span class="more">Read comparison →</span></a>' for x in cd.all_entries())
    body = f"""<nav class="crumbs" aria-label="Breadcrumb"><a href="/">Home</a> / Compare</nav><h1 class="h1s">Best Product Hunt &amp; Microlaunch alternatives for makers in 2026</h1>
<p class="lead">Honest, side-by-side comparisons of Nanolaunch and the best launch platforms for indie makers: features, pricing, audience and who each one is really for.</p>
<div class="hubgrid">{cards}</div>
<section class="prose"><h2>How to choose a launch platform</h2><p>Match the platform to your goal. Big one-day audiences suit products with a following. Persistent boards suit solo makers who need steady discovery. Pre-launch directories help you collect waitlist signups. Most successful makers launch on several, so use this guide to build a shortlist.</p></section>{cta_box()}"""
    ld = jsonld({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": SITE + "/"}, {"@type": "ListItem", "position": 2, "name": "Compare", "item": SITE + "/compare"}]},
        {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "url": f"{SITE}/compare/{x['slug']}", "name": f"Nanolaunch vs {x['name']}"} for i, x in enumerate(cd.all_entries())]})
    return layout("Launch Platform Comparisons: Product Hunt, Microlaunch & More Alternatives (2026) | Nanolaunch",
                  "Compare Nanolaunch with Product Hunt, Microlaunch, Uneed, Peerlist, Fazier, DevHunt, BetaList and TinyLaunch: features, pricing and which is best for your launch.", body, "/compare", user, ld)


def page_compare(user, slug):
    c = next((x for x in cd.all_entries() if x["slug"] == slug), None)
    if not c:
        return None
    n = c["name"]
    rows = "".join(f'<tr><th scope="row">{lbl}</th><td>{e(cd.APP[k])}</td><td>{e(c[k])}</td></tr>' for lbl, k in cd.ROWS)
    li = lambda xs: "".join(f"<li>{e(x)}</li>" for x in xs)
    faq = cd.faqs(c)
    faqh = "".join(f"<details><summary>{e(q)}</summary><p>{e(a)}</p></details>" for q, a in faq)
    others = "".join(f'<a class="chip" href="/compare/{x["slug"]}">vs {e(x["name"])}</a>' for x in cd.all_entries() if x["slug"] != slug)
    title = f"Nanolaunch vs {n}: features, pricing and which is better in 2026"
    desc = f"Nanolaunch vs {n} compared side by side: launch window, pricing, audience, feedback tools and pros and cons. Find out which launch platform fits your product."
    body = f"""<nav class="crumbs" aria-label="Breadcrumb"><a href="/">Home</a> / <a href="/compare">Compare</a> / {e(n)}</nav>
<article><h1 class="h1s">Nanolaunch vs {e(n)}: features, pricing and which is better in 2026</h1>
<p class="lead">Looking for a {e(n)} alternative? Here is an honest comparison of both launch platforms. Last reviewed {time.strftime("%B %Y")}. Verify current pricing on each site.</p>
<div class="verdict"><h2>The verdict</h2><p>{e(c['verdict'])}</p></div>
<h2>Side-by-side comparison</h2><div class="tablewrap"><table class="cmp"><thead><tr><th scope="col">Feature</th><th scope="col">Nanolaunch</th><th scope="col"><a href="{e(c['url'])}" rel="nofollow noopener" target="_blank">{e(n)}</a></th></tr></thead><tbody>{rows}</tbody></table></div>
<div class="proscons"><div class="box"><h3>Nanolaunch: pros</h3><ul class="ticks">{li(cd.APP_PROS)}</ul><h3>Nanolaunch: cons</h3><ul class="crosses">{li(cd.APP_CONS)}</ul></div>
<div class="box"><h3>{e(n)}: pros</h3><ul class="ticks">{li(c['pros'])}</ul><h3>{e(n)}: cons</h3><ul class="crosses">{li(c['cons'])}</ul></div></div>
<section class="prose"><h2>Which should you choose?</h2><p>Choose <b>{e(n)}</b> if you want: {e(c['best'].lower())}. Choose <b>Nanolaunch</b> if you want a free, no-paid-placement board with persistent rankings, structured ratings and an AI assistant that writes your launch copy. You can also launch on both.</p></section>
{cta_box(n)}<section><h2>Frequently asked questions</h2><div class="faq">{faqh}</div></section>
<section><h2>More comparisons</h2><div class="chips">{others}<a class="chip" href="/compare">All comparisons</a></div></section></article>"""
    ld = jsonld({"@context": "https://schema.org", "@type": "Product", "name": "Nanolaunch", "description": "Free launch platform for indie products with AI launch-copy assistant.",
                 "url": SITE, "brand": {"@type": "Brand", "name": "Nanolaunch"}, "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD", "url": SITE + "/signup"}},
                {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]},
                {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": SITE + "/"}, {"@type": "ListItem", "position": 2, "name": "Compare", "item": SITE + "/compare"},
                    {"@type": "ListItem", "position": 3, "name": f"Nanolaunch vs {n}", "item": f"{SITE}/compare/{slug}"}]})
    return layout(title, desc, body, f"/compare/{slug}", user, ld, "article")


def sitemap(c):
    urls = ["/", "/browse", "/compare", "/signup"] + [f"/compare/{x['slug']}" for x in cd.all_entries()] + \
           [f"/launch/{r['slug']}" for r in c.execute("select slug from products")]
    return '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(f"<url><loc>{SITE}{u}</loc></url>" for u in urls) + "</urlset>"


# ---------- server ----------
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def user(self, c):
        ck = SimpleCookie(self.headers.get("Cookie", ""))
        if "sid" not in ck:
            return None
        return c.execute("select u.* from sessions s join users u on u.id=s.user_id where s.token=?", (ck["sid"].value,)).fetchone()

    def send(self, code, body, ctype="text/html; charset=utf-8", headers=()):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def redirect(self, to, headers=()):
        self.send(303, b"", headers=[("Location", to), *headers])

    def not_found(self, u):
        self.send(404, layout("Page not found | Nanolaunch", "This page could not be found.", '<div class="empty"><h1>404</h1><p>We could not find that page.</p><a class="btn" href="/">Back to leaderboard</a></div>', "/404", u, noindex=True))

    def do_GET(self):
        u = urlparse(self.path)
        path, q = u.path.rstrip("/") or "/", parse_qs(u.query)
        if path.startswith("/static/"):
            f = os.path.normpath(os.path.join(HERE, "static", path[8:]))
            if not f.startswith(os.path.join(HERE, "static")) or not os.path.isfile(f):
                return self.send(404, "not found", "text/plain")
            return self.send(200, open(f, "rb").read(), mimetypes.guess_type(f)[0] or "application/octet-stream", [("Cache-Control", "public, max-age=3600")])
        if path == "/robots.txt":
            return self.send(200, f"User-agent: *\nAllow: /\nDisallow: /launch/new\nSitemap: {SITE}/sitemap.xml\n", "text/plain")
        c = db.conn()
        try:
            user = self.user(c)
            if path == "/sitemap.xml":
                return self.send(200, sitemap(c), "application/xml")
            m = None
            page = None
            if path == "/":
                page = page_home(c, user, q)
            elif path == "/browse":
                page = page_browse(c, user, q)
            elif path == "/compare":
                page = page_compare_hub(user)
            elif (m := re.fullmatch(r"/compare/([\w-]+)", path)):
                page = page_compare(user, m.group(1))
            elif path == "/launch/new":
                page = page_new(user) if user else None
                if not user:
                    return self.redirect("/login")
            elif (m := re.fullmatch(r"/launch/([\w-]+)", path)):
                page = page_product(c, user, m.group(1))
            elif path in ("/login", "/signup"):
                page = page_auth(user, path[1:])
            elif (m := re.fullmatch(r"/u/(\w+)", path)):
                page = page_profile(c, user, m.group(1))
            return self.send(200, page) if page else self.not_found(user)
        finally:
            c.close()

    def do_POST(self):
        u = urlparse(self.path)
        path = u.path.rstrip("/")
        n = min(int(self.headers.get("Content-Length") or 0), 100_000)
        raw = self.rfile.read(n).decode("utf-8", "replace")
        wants_json = "application/json" in (self.headers.get("Accept", "") + self.headers.get("Content-Type", ""))
        data = json.loads(raw or "{}") if "json" in self.headers.get("Content-Type", "") else parse_qs(raw)
        g = lambda k: (data.get(k, [""])[0] if isinstance(data.get(k), list) else data.get(k, "")).strip()
        c = db.conn()
        try:
            user = self.user(c)
            now = int(time.time())
            if path in ("/login", "/signup"):
                vals = {"username": g("username"), "email": g("email").lower()}
                if path == "/signup":
                    if not re.fullmatch(r"\w{3,20}", vals["username"]) or "@" not in vals["email"] or len(g("password")) < 8:
                        return self.send(400, page_auth(None, "signup", "Use a 3-20 char username, valid email and 8+ char password.", vals))
                    if c.execute("select 1 from users where username=? or email=?", (vals["username"], vals["email"])).fetchone():
                        return self.send(400, page_auth(None, "signup", "That username or email is already taken.", vals))
                    uid = c.execute("insert into users(username,email,pw,created) values(?,?,?,?)", (vals["username"], vals["email"], db.hash_pw(g("password")), now)).lastrowid
                else:
                    r = c.execute("select * from users where email=?", (vals["email"],)).fetchone()
                    if not r or not db.check_pw(g("password"), r["pw"]):
                        return self.send(400, page_auth(None, "login", "Incorrect email or password.", vals))
                    uid = r["id"]
                tok = secrets.token_urlsafe(32)
                c.execute("insert into sessions values(?,?,?)", (tok, uid, now))
                c.commit()
                return self.redirect("/", [("Set-Cookie", f"sid={tok}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000" + ("; Secure" if SITE.startswith("https") else ""))])
            if path == "/logout":
                ck = SimpleCookie(self.headers.get("Cookie", ""))
                if "sid" in ck:
                    c.execute("delete from sessions where token=?", (ck["sid"].value,)); c.commit()
                return self.redirect("/", [("Set-Cookie", "sid=; Path=/; Max-Age=0")])
            if path == "/api/ai/launch-copy":
                if not user:
                    return self.send(401, json.dumps({"error": "Log in first"}), "application/json")
                try:
                    return self.send(200, json.dumps(ai.generate(g("url"), g("notes"))), "application/json")
                except ValueError as ex:
                    return self.send(400, json.dumps({"error": str(ex)}), "application/json")
            if not user:
                if wants_json:
                    return self.send(401, json.dumps({"error": "login", "redirect": "/login"}), "application/json")
                return self.redirect("/login")
            if path == "/launch/new":
                name, tag, desc, url = g("name")[:40], g("tagline")[:60], g("description")[:2000], g("url")
                if not (name and tag and desc and re.match(r"https?://", url)):
                    return self.send(400, page_new(user, data, "Please fill every field with a valid http(s) URL."))
                base = db.slugify(name)
                slug, i = base, 2
                while c.execute("select 1 from products where slug=?", (slug,)).fetchone():
                    slug, i = f"{base}-{i}", i + 1
                cat = g("category") if g("category") in db.CAT_NAMES else "saas"
                feats = "|".join(x.strip()[:80] for x in g("features").splitlines() if x.strip())
                pid = c.execute("insert into products(slug,name,tagline,description,url,category,emoji,features,maker_id,created) values(?,?,?,?,?,?,?,?,?,?)",
                                (slug, name, tag, desc, url, cat, g("emoji")[:4] or "🚀", feats, user["id"], now)).lastrowid
                c.execute("insert into votes values(?,?,?)", (user["id"], pid, now))
                c.commit()
                return self.redirect(f"/launch/{slug}")
            m = re.fullmatch(r"/launch/([\w-]+)/(upvote|comment|rate)", path)
            if m:
                p = c.execute("select id from products where slug=?", (m.group(1),)).fetchone()
                if not p:
                    return self.not_found(user)
                act = m.group(2)
                score = None
                if act == "upvote":
                    if c.execute("select 1 from votes where user_id=? and product_id=?", (user["id"], p["id"])).fetchone():
                        c.execute("delete from votes where user_id=? and product_id=?", (user["id"], p["id"]))
                        voted = False
                    else:
                        c.execute("insert into votes values(?,?,?)", (user["id"], p["id"], now))
                        voted = True
                    c.commit()
                    score = c.execute("select count(*) from votes where product_id=?", (p["id"],)).fetchone()[0]
                    if wants_json:
                        return self.send(200, json.dumps({"count": score, "voted": voted}), "application/json")
                elif act == "comment" and g("body"):
                    c.execute("insert into comments(product_id,user_id,body,created) values(?,?,?,?)", (p["id"], user["id"], g("body")[:1000], now)); c.commit()
                elif act == "rate":
                    clamp = lambda v: min(5, max(1, int(v or 3)))
                    c.execute("insert or replace into ratings values(?,?,?,?)", (p["id"], user["id"], clamp(g("idea")), clamp(g("product")))); c.commit()
                ref = self.headers.get("Referer", "")
                return self.redirect(urlparse(ref).path + ("?" + urlparse(ref).query if urlparse(ref).query else "") if ref and urlparse(ref).netloc == self.headers.get("Host") else f"/launch/{m.group(1)}")
            self.not_found(user)
        finally:
            c.close()


if __name__ == "__main__":
    db.seed()
    port = int(os.environ.get("PORT", "8000"))
    print(f"Nanolaunch running at http://localhost:{port}  (AI: {'Claude' if os.environ.get('ANTHROPIC_API_KEY') else 'basic mode, set ANTHROPIC_API_KEY'})")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
