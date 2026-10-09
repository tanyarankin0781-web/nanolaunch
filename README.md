# Nanolaunch

A launch platform for indie products (a rebuild of microlaunch.net's core idea). Python stdlib only, SQLite, server-rendered.

```
python app.py                      # http://localhost:8000
PORT=8077 SITE_URL=https://yourdomain.com python app.py
ANTHROPIC_API_KEY=sk-... python app.py   # enables Claude-written launch copy
```

Demo login: demo@nanolaunch.dev / demo1234. The database is created and seeded on first run (delete nanolaunch.db to reset).
Set SITE_URL in production so canonical URLs, sitemap and structured data use your real domain.
