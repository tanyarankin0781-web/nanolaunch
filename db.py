import hashlib
import os
import random
import re
import secrets
import sqlite3
import time

DB_PATH = os.path.join(os.environ.get("DATA_DIR") or os.path.dirname(os.path.abspath(__file__)), "nanolaunch.db")
DAY = 86400

CATEGORIES = [("ai-tools", "AI Tools", "🤖"), ("productivity", "Productivity", "⚡"),
              ("marketing", "Marketing & Growth", "📈"), ("dev-tools", "Dev Tools", "🛠️"),
              ("social-media", "Social Media", "💬"), ("design", "Design", "🎨"),
              ("saas", "SaaS", "☁️")]
CAT_NAMES = {c[0]: c[1] for c in CATEGORIES}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, email TEXT UNIQUE,
  pw TEXT, bio TEXT DEFAULT '', created INTEGER);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER, created INTEGER);
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, slug TEXT UNIQUE, name TEXT, tagline TEXT,
  description TEXT, url TEXT, category TEXT, emoji TEXT, features TEXT DEFAULT '', maker_id INTEGER, created INTEGER);
CREATE TABLE IF NOT EXISTS votes(user_id INTEGER, product_id INTEGER, created INTEGER, PRIMARY KEY(user_id, product_id));
CREATE TABLE IF NOT EXISTS comments(id INTEGER PRIMARY KEY, product_id INTEGER, user_id INTEGER, body TEXT, created INTEGER);
CREATE TABLE IF NOT EXISTS ratings(product_id INTEGER, user_id INTEGER, idea INTEGER, product INTEGER,
  PRIMARY KEY(product_id, user_id));
"""


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${h}"


def check_pw(pw, stored):
    salt = stored.split("$")[0]
    return secrets.compare_digest(hash_pw(pw, salt), stored)


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "product"


SEED = [
    ("Zinnia CRM", "A CRM that fills itself in from your inbox", "saas", "🌸", 0.9),
    ("Promptly", "Version control and testing for your LLM prompts", "ai-tools", "🧪", 1.0),
    ("Calmcal", "A calendar that protects your focus time automatically", "productivity", "📅", 0.8),
    ("Shipnote", "Turn commits into polished changelogs in one click", "dev-tools", "📝", 0.75),
    ("Reelmint", "Repurpose long videos into captioned short clips", "social-media", "🎬", 0.85),
    ("Growthlog", "Weekly growth experiments tracker for tiny teams", "marketing", "📈", 0.6),
    ("Pixelpour", "On-brand social graphics from a single sentence", "design", "🎨", 0.7),
    ("Tinybill", "Invoicing for freelancers that chases payment for you", "saas", "🧾", 0.65),
    ("Docsmith", "AI-written docs that stay in sync with your codebase", "dev-tools", "📚", 0.8),
    ("Quietinbox", "Email triage that surfaces only what needs a reply", "productivity", "📥", 0.55),
    ("Hookwise", "Generate and A/B test viral hooks for short video", "marketing", "🪝", 0.5),
    ("Mindloom", "A second brain that links your notes automatically", "ai-tools", "🧠", 0.7),
    ("Feedlane", "Collect and prioritise user feedback in one board", "saas", "🛣️", 0.45),
    ("Snapdeploy", "Deploy side projects to the edge with one command", "dev-tools", "🚀", 0.6),
    ("Chirpkit", "Schedule and analyse posts across every network", "social-media", "🐦", 0.4),
    ("Colorlab", "Accessible colour palettes with live contrast checks", "design", "🌈", 0.35),
]
DESCS = {
    "default": "Built by an indie maker who got tired of doing this by hand. {n} is fast, focused and opinionated, with a generous free plan so you can try it in minutes.\n\nWe launched to solve our own problem and are shipping improvements every week based on feedback from users like you."
}
SEED_COMMENTS = [
    "Love the focus here. Signed up in under a minute and it just worked.",
    "Congrats on the launch! Would love to see an API next.",
    "Clean UI. How are you handling data privacy for teams?",
    "This is exactly what I needed for my side project. Upvoted!",
    "Great idea, and the execution is tight. Following along.",
    "Pricing looks fair. Any plans for a lifetime deal?",
]


def seed():
    c = conn()
    c.executescript(SCHEMA)
    if c.execute("select count(*) from users").fetchone()[0]:
        c.close()
        return
    rnd = random.Random(7)
    now = int(time.time())
    names = ["ava", "noah", "mia", "liam", "zoe", "eli", "ivy", "sam", "kai", "luna", "max", "ruby",
             "finn", "nora", "owen", "ella", "jude", "tess", "cole", "maya", "ben", "lily", "ross",
             "ines", "theo", "dana", "omar", "yuki", "sara", "leo"]
    unusable = hash_pw(secrets.token_hex(16))
    uids = []
    for n in names:
        cur = c.execute("insert into users(username,email,pw,bio,created) values(?,?,?,?,?)",
                        (n, f"{n}@example.com", unusable, "Maker and early adopter.", now - rnd.randint(10, 90) * DAY))
        uids.append(cur.lastrowid)
    demo = c.execute("insert into users(username,email,pw,bio,created) values(?,?,?,?,?)",
                     ("demo", "demo@nanolaunch.dev", hash_pw("demo1234"), "Demo account. Launching tiny things.", now - 5 * DAY)).lastrowid
    for name, tag, cat, emoji, pop in SEED:
        maker = rnd.choice(uids)
        created = now - rnd.randint(1, 26) * DAY
        feats = "|".join(["Set up in under 5 minutes", "Generous free plan", "Built for small teams and solo makers"])
        pid = c.execute("insert into products(slug,name,tagline,description,url,category,emoji,features,maker_id,created) values(?,?,?,?,?,?,?,?,?,?)",
                        (slugify(name), name, tag, DESCS["default"].format(n=name), f"https://{slugify(name)}.example.com",
                         cat, emoji, feats, maker, created)).lastrowid
        for u in rnd.sample(uids, max(2, int(len(uids) * pop))):
            c.execute("insert or ignore into votes values(?,?,?)", (u, pid, max(created, now - int(rnd.random() ** 2 * 28 * DAY))))
        for u in rnd.sample(uids, 3):
            c.execute("insert into comments(product_id,user_id,body,created) values(?,?,?,?)",
                      (pid, u, rnd.choice(SEED_COMMENTS), created + rnd.randint(3600, 3 * DAY)))
        for u in rnd.sample(uids, 6):
            c.execute("insert or ignore into ratings values(?,?,?,?)", (pid, u, rnd.randint(3, 5), rnd.randint(3, 5)))
    c.commit()
    c.close()
