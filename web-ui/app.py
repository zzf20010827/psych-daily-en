"""Flask web backend for PsychLit Daily — wraps Python scripts as REST API + serves UI."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from threading import Lock

from flask import Flask, jsonify, request, send_from_directory

# Ensure scripts module is importable
SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
sys.path.insert(0, str(SCRIPT_DIR))

import search_literature as sl
import format_digest as fd

app = Flask(__name__, static_folder=".", static_url_path="")
_lock = Lock()
PUBLISHED_FILE = DATA_DIR / "published.html"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── helpers ──────────────────────────────────────────────────────────

def _load_config() -> dict:
    cfg_path = SCRIPT_DIR / "config.yaml"
    if not cfg_path.exists():
        cfg = {}
    else:
        import yaml
        with cfg_path.open(encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    return cfg


def _load_history() -> list[dict]:
    path = DATA_DIR / "sent_history.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _save_history(history: list[dict]) -> None:
    path = DATA_DIR / "sent_history.json"
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_manual() -> list[dict]:
    path = DATA_DIR / "manual_papers.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _save_manual(papers: list[dict]) -> None:
    path = DATA_DIR / "manual_papers.json"
    path.write_text(json.dumps(papers, ensure_ascii=False, indent=2), encoding="utf-8")


_PUBLIC_PAGE_TPL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; background:#f5f5f5; color:#333; }}
  nav {{ background:#1a5fb4; color:#fff; padding:0 16px; display:flex; align-items:center; height:48px; gap:24px; position:sticky; top:0; z-index:100; }}
  nav .brand {{ font-weight:600; font-size:15px; }}
  nav a {{ color:rgba(255,255,255,.85); text-decoration:none; font-size:13px; transition:color .15s; }}
  nav a:hover {{ color:#fff; }}
  nav a.active {{ color:#fff; font-weight:500; border-bottom:2px solid #fff; padding-bottom:2px; }}
  nav .spacer {{ flex:1; }}
  .container {{ max-width:800px; margin:0 auto; padding:16px; }}
  .hero {{ background:linear-gradient(135deg,#1a5fb4,#2563eb); color:#fff; padding:32px 24px; border-radius:10px; margin-bottom:20px; }}
  .hero h1 {{ font-size:24px; margin-bottom:6px; }}
  .hero p {{ opacity:.85; font-size:14px; }}
  .page {{ display:none; }}
  .page.active {{ display:block; }}
  .paper {{ background:#fff; border-radius:8px; padding:16px; margin-bottom:12px; box-shadow:0 1px 3px rgba(0,0,0,.08); }}
  .paper .topic {{ font-size:11px; color:#1a5fb4; font-weight:600; text-transform:uppercase; letter-spacing:.5px; }}
  .paper h3 {{ font-size:15px; margin:6px 0 4px; }}
  .paper h3 a {{ color:#333; text-decoration:none; }}
  .paper h3 a:hover {{ color:#1a5fb4; }}
  .paper .meta {{ font-size:12px; color:#888; margin-bottom:6px; }}
  .paper .abstract {{ font-size:13px; line-height:1.6; color:#555; max-height:0; overflow:hidden; transition:max-height .3s ease; }}
  .paper .abstract.open {{ max-height:300px; overflow-y:auto; }}
  .paper .toggle {{ font-size:12px; color:#1a5fb4; cursor:pointer; user-select:none; }}
  .paper .toggle:hover {{ text-decoration:underline; }}
  .footer {{ text-align:center; font-size:12px; color:#999; padding:24px 0; }}
  .empty {{ text-align:center; padding:60px 20px; color:#888; }}
  .empty h2 {{ font-size:18px; margin-bottom:8px; }}
  .about-section {{ background:#fff; border-radius:8px; padding:24px; box-shadow:0 1px 3px rgba(0,0,0,.08); }}
  .about-section h2 {{ font-size:16px; margin-bottom:12px; }}
  .about-section p {{ font-size:13px; line-height:1.7; color:#555; margin-bottom:10px; }}
  .badge {{ display:inline-block; background:#e8f0fe; color:#1a5fb4; font-size:11px; padding:2px 8px; border-radius:4px; }}
</style>
</head>
<body>
<nav>
  <span class="brand">PsychLit Daily</span>
  <a href="#" class="active" data-page="home">Home</a>
  <a href="#" data-page="papers">Latest Papers</a>
  <a href="#" data-page="about">About</a>
  <span class="spacer"></span>
  <a href="/admin">Dashboard</a>
</nav>
<div class="container">
  <div class="page active" id="page-home">
    <div class="hero">
      <h1>Psychology Literature Daily</h1>
      <p>{subtitle}</p>
    </div>
    <div style="margin-bottom:16px;font-size:13px;color:#666;">Latest papers: <span class="badge">{count} papers</span></div>
    {papers_preview}
    <p style="text-align:center;margin-top:16px;"><a href="#" data-page="papers" style="color:#1a5fb4;font-size:13px;" onclick="switchPage('papers');return false;">View all papers →</a></p>
  </div>
  <div class="page" id="page-papers">
    <h2 style="font-size:18px;margin-bottom:16px;">Latest Papers</h2>
    {papers_full}
  </div>
  <div class="page" id="page-about">
    <div class="about-section">
      <h2>About PsychLit Daily</h2>
      <p>An automated psychology literature tracking system that searches PubMed across multiple subdomains (Clinical Psychology, Cognitive Neuroscience, Developmental Psychology, Social Psychology) and publishes the latest findings to this page.</p>
      <p>Data is updated daily via automated search. Each paper includes title, authors, journal, abstract, and links to the full text.</p>
      <p><strong>Data Sources:</strong> PubMed</p>
      <p><strong>Last Updated:</strong> {subtitle}</p>
    </div>
  </div>
</div>
<div class="footer">Auto-generated by Psychology Literature Daily &middot; Data: PubMed</div>
<script>
function switchPage(name) {{
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById('page-'+name).classList.add('active');
  document.querySelectorAll('nav a[data-page]').forEach(a => a.classList.remove('active'));
  var link = document.querySelector('nav a[data-page="'+name+'"]');
  if (link) link.classList.add('active');
}}
document.querySelectorAll('nav a[data-page]').forEach(function(a) {{
  a.addEventListener('click', function(e) {{ e.preventDefault(); switchPage(this.getAttribute('data-page')); }});
}});
document.querySelectorAll('.toggle').forEach(function(b) {{
  b.addEventListener('click', function() {{
    var abs = this.parentElement.querySelector('.abstract');
    abs.classList.toggle('open');
    this.textContent = abs.classList.contains('open') ? '▲ Hide abstract' : '▼ Show abstract';
  }});
}});
</script>
</body>
</html>"""


def _build_papers_html(papers: list[dict]) -> str:
    """Build HTML for a list of paper dicts (with topic, title, authors, etc.)."""
    parts = []
    for p in papers:
        parts.append(f'''<div class="paper">
  <div class="topic">{p.get("topic","")}</div>
  <h3><a href="{p.get("url","#")}" target="_blank" rel="noopener">{p.get("title","")}</a></h3>
  <div class="meta">{p.get("authors","")} &middot; {p.get("journal","")} &middot; {p.get("date","")}</div>
  <div class="abstract">{p.get("abstract","Abstract unavailable")}</div>
  <span class="toggle">▼ Show abstract</span>
</div>''')
    return "\n".join(parts) if parts else '<div class="empty"><h2>No papers yet</h2><p>Run a search from the dashboard to publish papers.</p></div>'


@app.route("/")
def homepage():
    papers = []
    if PUBLISHED_FILE.exists():
        try:
            import json
            papers = json.loads(PUBLISHED_FILE.read_text(encoding="utf-8"))
        except Exception:
            papers = []
    count = len(papers)
    if not papers:
        subtitle = "No papers published yet"
        papers_preview = '<div class="empty"><h2>No content yet</h2><p>Use the dashboard to search and publish the latest papers.</p><p><a href="/admin" style="color:#1a5fb4;">Go to Dashboard →</a></p></div>'
        papers_full = papers_preview
    else:
        subtitle = f"Published {datetime.now().strftime('%Y-%m-%d %H:%M')} &middot; {count} papers"
        preview = papers[:min(3, count)]
        papers_preview = _build_papers_html(preview)
        papers_full = _build_papers_html(papers)
    html = _PUBLIC_PAGE_TPL.format(title=f"Psychology Literature Daily ({count} papers)" if count else "Psychology Literature Daily", subtitle=subtitle, count=count, papers_preview=papers_preview, papers_full=papers_full)
    return html


@app.route("/admin")
def admin():
    return send_from_directory(".", "index.html")


@app.route("/api/status")
def api_status():
    cfg = _load_config()
    history = _load_history()
    topics = cfg.get("topics", [])
    today = datetime.now().strftime("%Y-%m-%d")
    today_count = sum(1 for h in history if h.get("sent_at", "").startswith(today))
    return jsonify({
        "papers_today": today_count,
        "papers_week": len(history),
        "topics_count": len(topics),
        "scheduled": "8:00 AM daily",
        "last_send": history[-1]["sent_at"] if history else None,
        "topic_breakdown": {t.get("name", "?"): 0 for t in topics},
        "status": "ready",
    })


@app.route("/api/search", methods=["POST"])
def api_search():
    data = request.get_json(silent=True) or {}
    days_back = int(data.get("days_back", 1))
    max_papers = int(data.get("max_papers", 10))

    with _lock:
        cfg = _load_config()
        cfg.setdefault("search", {})["days_back"] = days_back
        cfg.setdefault("search", {})["max_papers"] = max_papers
        papers, stats = sl.search_all(cfg)
        manual = sl.load_manual_papers(str(DATA_DIR / "manual_papers.json"))
        if manual:
            papers = sl.sort_papers(papers + manual)[:max_papers]
        history = _load_history()
        keys = {h["key"] for h in history if "key" in h}
        papers, skipped = sl.filter_history(papers, keys)

    result = []
    for p in papers:
        result.append({
            "topic": p.topic,
            "title": p.title,
            "authors": p.authors,
            "journal": p.journal,
            "date": p.date,
            "abstract": (p.abstract or "")[:300],
            "doi": p.doi,
            "pmid": p.pmid,
            "url": p.url,
            "fulltext_url": p.fulltext_url,
            "is_oa": p.is_oa,
            "source": p.source,
        })

    return jsonify({
        "papers": result,
        "total_raw": stats.total_raw,
        "total_after_dedupe": stats.total_after_dedupe,
        "skipped_history": skipped,
        "topic_hits": stats.topic_hits,
    })


@app.route("/api/publish", methods=["POST"])
def api_publish():
    data = request.get_json(silent=True) or {}
    days_back = int(data.get("days_back", 1))
    max_papers = int(data.get("max_papers", 10))

    with _lock:
        cfg = _load_config()
        cfg.setdefault("search", {})["days_back"] = days_back
        cfg.setdefault("search", {})["max_papers"] = max_papers
        papers, stats = sl.search_all(cfg)
        manual = sl.load_manual_papers(str(DATA_DIR / "manual_papers.json"))
        if manual:
            papers = sl.sort_papers(papers + manual)[:max_papers]
        history = _load_history()
        keys = {h["key"] for h in history if "key" in h}
        papers, skipped = sl.filter_history(papers, keys)

        # Save papers as JSON for the interactive homepage
        paper_list = []
        for p in papers:
            paper_list.append({
                "topic": p.topic,
                "title": p.title,
                "authors": p.authors,
                "journal": p.journal,
                "date": p.date,
                "abstract": p.abstract or "Abstract unavailable",
                "doi": p.doi,
                "pmid": p.pmid,
                "url": p.url,
                "fulltext_url": p.fulltext_url,
                "source": p.source,
            })
        PUBLISHED_FILE.write_text(json.dumps(paper_list, ensure_ascii=False, indent=2), encoding="utf-8")

        if papers:
            now_iso = datetime.now().isoformat()
            for p in papers:
                history.append({"key": p.dedupe_key(), "title": p.title, "sent_at": now_iso})
            _save_history(history)

    return jsonify({
        "success": True,
        "papers_count": len(papers),
        "skipped": skipped,
        "url": "/",
    })


@app.route("/api/history")
def api_history():
    history = _load_history()
    return jsonify(history)


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        cfg_path = SCRIPT_DIR / "config.yaml"
        import yaml
        with cfg_path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        if "smtp" in data:
            cfg["smtp"].update(data["smtp"])
        if "email" in data:
            cfg["email"].update(data["email"])
        if "search" in data:
            cfg["search"].update(data["search"])
        if "topics" in data:
            cfg["topics"] = data["topics"]
        with cfg_path.open("w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
        return jsonify({"success": True})
    cfg = _load_config()
    return jsonify(cfg)


@app.route("/api/import", methods=["GET", "POST", "DELETE"])
def api_import():
    if request.method == "GET":
        return jsonify(_load_manual())
    if request.method == "POST":
        paper = request.get_json(silent=True) or {}
        if not paper.get("title"):
            return jsonify({"error": "Title is required"}), 400
        manual = _load_manual()
        manual.append(paper)
        _save_manual(manual)
        return jsonify({"success": True, "count": len(manual)})
    if request.method == "DELETE":
        body = request.get_json(silent=True) or {}
        idx = body.get("index")
        manual = _load_manual()
        if idx is not None and 0 <= idx < len(manual):
            manual.pop(idx)
        else:
            manual = []
        _save_manual(manual)
        return jsonify({"success": True, "count": len(manual)})


@app.route("/api/activity")
def api_activity():
    history = _load_history()
    recent = history[-20:] if len(history) > 20 else history
    return jsonify([{"key": h["key"], "title": h["title"], "sent_at": h["sent_at"]} for h in reversed(recent)])


# ── Run ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") == "development"
    app.run(host="0.0.0.0", port=port, debug=debug)
