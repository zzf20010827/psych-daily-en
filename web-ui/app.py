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
import send_email as se

app = Flask(__name__, static_folder=".", static_url_path="")
_lock = Lock()

# ── helpers ──────────────────────────────────────────────────────────

def _load_config() -> dict:
    cfg_path = SCRIPT_DIR / "config.yaml"
    if not cfg_path.exists():
        cfg = {}
    else:
        import yaml
        with cfg_path.open(encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    # Allow env var overrides (Render-friendly)
    smtp = cfg.setdefault("smtp", {})
    for key in ("sender", "auth_code", "recipient", "host"):
        env_val = os.environ.get(f"SMTP_{key.upper()}")
        if env_val:
            smtp[key] = env_val
    port_env = os.environ.get("SMTP_PORT")
    if port_env:
        smtp["port"] = int(port_env)
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


# ── API Routes ───────────────────────────────────────────────────────

@app.route("/")
def index():
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


@app.route("/api/send", methods=["POST"])
def api_send():
    data = request.get_json(silent=True) or {}
    is_test = data.get("test", False)
    days_back = int(data.get("days_back", 1))
    max_papers = int(data.get("max_papers", 10))

    with _lock:
        cfg = _load_config()
        if is_test:
            papers, stats, skipped = [], type("Stats", (), {"topic_hits": {}})(), 0
        else:
            cfg.setdefault("search", {})["days_back"] = days_back
            cfg.setdefault("search", {})["max_papers"] = max_papers
            papers, stats = sl.search_all(cfg)
            manual = sl.load_manual_papers(str(DATA_DIR / "manual_papers.json"))
            if manual:
                papers = sl.sort_papers(papers + manual)[:max_papers]
            history = _load_history()
            keys = {h["key"] for h in history if "key" in h}
            papers, skipped = sl.filter_history(papers, keys)

        if not papers and not is_test:
            return jsonify({"error": "No new papers to send. Use test=true to send a test email."}), 400

        subject, combined = fd.format_digest_html(
            papers, stats, skipped, days_back, is_test=is_test
        )
        html_body, plain_body = fd.split_html_plain(combined)

        try:
            se.send_qq_email(cfg, subject, html_body, plain_body)
        except Exception as e:
            return jsonify({"error": f"Send failed: {e}"}), 500

        if papers and not is_test:
            now_iso = datetime.now().isoformat()
            for p in papers:
                history.append({"key": p.dedupe_key(), "title": p.title, "sent_at": now_iso})
            _save_history(history)

    return jsonify({
        "success": True,
        "subject": subject,
        "papers_count": len(papers),
        "skipped": skipped,
        "is_test": is_test,
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


@app.route("/api/debug")
def api_debug():
    cfg = _load_config()
    smtp = cfg.get("smtp", {})
    import socket
    net_ok = False
    net_err = ""
    try:
        s = socket.create_connection(("smtp.qq.com", 465), timeout=5)
        s.close()
        net_ok = True
    except Exception as e:
        net_err = str(e)
    return jsonify({
        "has_sender": bool(smtp.get("sender")),
        "has_auth_code": bool(smtp.get("auth_code")),
        "has_recipient": bool(smtp.get("recipient")),
        "sender_env": bool(os.environ.get("SMTP_SENDER")),
        "auth_code_env": bool(os.environ.get("SMTP_AUTH_CODE")),
        "recipient_env": bool(os.environ.get("SMTP_RECIPIENT")),
        "sender_val": smtp.get("sender", ""),
        "auth_code_len": len(smtp.get("auth_code", "")),
        "smtp_reachable": net_ok,
        "smtp_error": net_err,
    })


# ── Run ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") == "development"
    app.run(host="0.0.0.0", port=port, debug=debug)
