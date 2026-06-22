"""Format literature digest as HTML and plain text email bodies."""

from __future__ import annotations

from datetime import datetime
from html import escape

from search_literature import Paper, SearchStats

TOPIC_COLORS = [
    ("#e8f4fd", "#1a5fb4"), ("#fce8e6", "#c01c28"),
    ("#e6f4ea", "#2ec27e"), ("#fef3e6", "#e5a50a"),
    ("#f3e8fd", "#813d9c"), ("#e6f0fa", "#3584e4"),
]


def _topic_color(topic: str) -> tuple[str, str]:
    return TOPIC_COLORS[hash(topic) % len(TOPIC_COLORS)]


def _safe(text: str) -> str:
    if not text:
        return ""
    return escape(" ".join(text.split()))


def _link_row(paper: Paper) -> str:
    links = []
    if paper.fulltext_url:
        links.append(f'<a href="{_safe(paper.fulltext_url)}" style="color:#2ec27e;">Full Text (Free)</a>')
    if paper.url:
        links.append(f'<a href="{_safe(paper.url)}" style="color:#3584e4;">PubMed</a>')
    if paper.doi:
        links.append(f'<a href="https://doi.org/{_safe(paper.doi)}" style="color:#3584e4;">DOI</a>')
    return " &middot; ".join(links) if links else ""


def _meta_line(paper: Paper) -> str:
    parts = [p for p in (paper.authors, paper.journal, paper.date) if p]
    meta = " &middot; ".join(parts)
    tag = {"pubmed": "PubMed", "crossref": "Crossref", "semantic_scholar": "Semantic Scholar", "manual": "Manual"}.get(paper.source, paper.source)
    if paper.pmc_id:
        meta += f" &middot; {escape(paper.pmc_id)}"
    meta += f" &middot; Source: {escape(tag)}"
    return meta


def format_paper_html(paper: Paper, index: int) -> str:
    bg, fg = _topic_color(paper.topic)
    oa = f'<span style="color:#2ec27e;font-size:11px;margin-left:6px;border:1px solid #2ec27e;border-radius:3px;padding:0 4px;">OA</span>' if paper.is_oa else ""
    link = paper.fulltext_url or paper.url or (f"https://doi.org/{paper.doi}" if paper.doi else "#")
    abstract = paper.abstract or ""
    ablock = ""
    if abstract and abstract != "Abstract unavailable":
        ablock = f'<div style="margin:10px 0 4px 0;"><div style="font-size:12px;color:#888;margin-bottom:4px;">Abstract</div><div style="font-size:13px;color:#555;line-height:1.6;">{_safe(abstract)}</div></div>'
    else:
        ablock = f'<div style="margin:10px 0 4px 0;font-size:13px;color:#999;">Abstract unavailable</div>'
    return f"""
    <div style="margin-bottom:22px;padding:16px;border:1px solid #e0e0e0;border-radius:8px;background:#fff;">
      <div style="margin-bottom:8px;"><span style="background:{bg};color:{fg};padding:2px 8px;border-radius:4px;font-size:12px;">{_safe(paper.topic)}</span>{oa}</div>
      <div style="font-size:16px;font-weight:600;line-height:1.4;margin-bottom:4px;">{index}. <a href="{_safe(link)}" style="color:#1a5fb4;text-decoration:none;">{_safe(paper.title)}</a></div>
      <div style="font-size:12px;color:#666;margin-bottom:8px;">{_meta_line(paper)}</div>
      {ablock}
      <div style="margin-top:10px;font-size:12px;">{_link_row(paper)}</div>
    </div>
    """


def format_digest_html(papers: list[Paper], stats: SearchStats, skipped_history: int, days_back: int, is_test: bool = False) -> tuple[str, str]:
    today = datetime.now().strftime("%Y-%m-%d")
    prefix = "[TEST] " if is_test else ""
    subject = f"{prefix}[Psychology Literature Daily] {today} &middot; {len(papers)} new papers"
    if not papers:
        body = f"""
        <div style="font-family:-apple-system,'Segoe UI',sans-serif;max-width:680px;margin:0 auto;">
          <div style="background:#1a5fb4;color:#fff;padding:20px;border-radius:8px 8px 0 0;">
            <h1 style="margin:0;font-size:20px;">Psychology Literature Daily</h1>
            <p style="margin:8px 0 0;opacity:0.9;">{today} &middot; No new papers</p>
          </div>
          <div style="padding:20px;border:1px solid #e0e0e0;border-top:none;border-radius:0 0 8px 8px;">
            <p>In the past {days_back} day(s), no new papers were found.</p>
          </div>
        </div>"""
        return subject, body + "\n<!--PLAIN-->\n" + f"{subject}\n\nNo new papers (window: {days_back} days)."
    tags = " ".join(f'<span style="background:rgba(255,255,255,0.2);padding:2px 8px;border-radius:4px;margin-right:6px;font-size:12px;">{_safe(t)}: {c}</span>' for t, c in stats.topic_hits.items())
    papers_html = "".join(format_paper_html(p, i+1) for i, p in enumerate(papers))
    oa_count = sum(1 for p in papers if p.is_oa)
    overview = f'<div style="background:#f5f5f5;padding:12px 16px;border-radius:6px;margin:20px 0;font-size:13px;color:#555;"><strong>Search Overview</strong><br>Window: past {days_back} day(s) &middot; Raw hits: {stats.total_raw}<br>Selected: {len(papers)} &middot; Skipped: {skipped_history} &middot; OA: {oa_count}</div>'
    body_html = f"""
    <div style="font-family:-apple-system,'Segoe UI',sans-serif;max-width:680px;margin:0 auto;color:#333;">
      <div style="background:#1a5fb4;color:#fff;padding:20px;border-radius:8px 8px 0 0;">
        <h1 style="margin:0;font-size:20px;">Psychology Literature Daily</h1>
        <p style="margin:8px 0 0;opacity:0.9;">{today} &middot; {len(papers)} new papers</p>
        <div style="margin-top:10px;">{tags}</div>
      </div>
      <div style="padding:20px;border:1px solid #e0e0e0;border-top:none;">
        <h2 style="font-size:16px;border-bottom:2px solid #1a5fb4;padding-bottom:6px;">Today's Selection</h2>
        {papers_html}{overview}
        <div style="font-size:12px;color:#999;border-top:1px solid #eee;padding-top:12px;margin-top:20px;line-height:1.6;">
          Auto-generated by Psychology Literature Daily. Data: PubMed, Crossref, Semantic Scholar. For academic exchange only.
        </div>
      </div>
    </div>"""
    plain = "\n".join([subject, "", f"Today's Selection - {len(papers)} papers (OA: {oa_count})", ""] +
        [f"{'='*60}\n{i+1}. [{p.topic}] {p.title}\n   {_meta_line(p)}\n   [Abstract] {p.abstract}" for i, p in enumerate(papers)] +
        ["", "="*60, f"Window: {days_back} day(s), Raw: {stats.total_raw}, Selected: {len(papers)}, Skipped: {skipped_history}"])
    return subject, body_html + "\n<!--PLAIN-->\n" + plain


def split_html_plain(combined: str) -> tuple[str, str]:
    if "\n<!--PLAIN-->\n" in combined:
        html, plain = combined.split("\n<!--PLAIN-->\n", 1)
        return html, plain
    return combined, ""
