"""Search psychology literature from PubMed and optional sources."""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import requests

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CROSSREF_BASE = "https://api.crossref.org/works"
S2_BASE = "https://api.semanticscholar.org/graph/v1/paper/search"


@dataclass
class Paper:
    title: str
    authors: str = ""
    journal: str = ""
    date: str = ""
    abstract: str = ""
    doi: str = ""
    pmid: str = ""
    url: str = ""
    topic: str = ""
    source: str = "pubmed"
    is_oa: bool = False
    pmc_id: str = ""
    fulltext_url: str = ""
    title_zh: str = ""
    abstract_zh: str = ""
    highlight_zh: str = ""

    def dedupe_key(self) -> str:
        if self.doi:
            return f"doi:{self.doi.lower().strip()}"
        if self.pmid:
            return f"pmid:{self.pmid}"
        normalized = re.sub(r"\W+", "", self.title.lower())[:80]
        return f"title:{normalized}"


@dataclass
class SearchStats:
    topic_hits: dict[str, int] = field(default_factory=dict)
    total_raw: int = 0
    total_after_dedupe: int = 0
    skipped_history: int = 0


def _date_window(days_back: int) -> tuple[str, str]:
    end = datetime.now()
    start = end - timedelta(days=max(1, days_back))
    return start.strftime("%Y/%m/%d"), end.strftime("%Y/%m/%d")


def _parse_pubmed_article(article: ET.Element, topic: str) -> Paper | None:
    medline = article.find("MedlineCitation")
    if medline is None:
        return None
    pmid_el = medline.find("PMID")
    pmid = pmid_el.text if pmid_el is not None and pmid_el.text else ""
    article_el = medline.find("Article")
    if article_el is None:
        return None
    title_el = article_el.find("ArticleTitle")
    title = "".join(title_el.itertext()).strip() if title_el is not None else ""
    if not title:
        return None
    abstract_parts: list[str] = []
    abstract_el = article_el.find("Abstract")
    if abstract_el is not None:
        for text_el in abstract_el.findall("AbstractText"):
            label = text_el.get("Label", "")
            text = "".join(text_el.itertext()).strip()
            if label:
                abstract_parts.append(f"{label}: {text}")
            elif text:
                abstract_parts.append(text)
    abstract = " ".join(abstract_parts)
    authors: list[str] = []
    author_list = article_el.find("AuthorList")
    if author_list is not None:
        for author in author_list.findall("Author"):
            last = author.findtext("LastName", "")
            fore = author.findtext("ForeName", "")
            collective = author.findtext("CollectiveName", "")
            if collective:
                authors.append(collective)
            elif last:
                authors.append(f"{fore} {last}".strip() if fore else last)
    journal = ""
    journal_el = article_el.find("Journal")
    if journal_el is not None:
        journal = journal_el.findtext("Title", "")
    pub_date = ""
    if journal_el is not None:
        jpd = journal_el.find("JournalIssue/PubDate")
        if jpd is not None:
            year = jpd.findtext("Year", "")
            month = jpd.findtext("Month", "01")
            day = jpd.findtext("Day", "01")
            if year:
                pub_date = f"{year}-{month}-{day}"
    doi = ""
    pmc_id = ""
    pubmed_data = article.find("PubmedData")
    if pubmed_data is not None:
        for id_el in pubmed_data.findall("ArticleIdList/ArticleId"):
            id_type = id_el.get("IdType", "")
            if id_type == "doi" and id_el.text:
                doi = id_el.text
            elif id_type in ("pmc", "pmcid") and id_el.text:
                pmc_id = id_el.text
    pmc_norm = pmc_id
    if pmc_norm and not pmc_norm.upper().startswith("PMC"):
        pmc_norm = f"PMC{pmc_norm}"
    fulltext_url = ""
    is_oa = bool(pmc_norm)
    if pmc_norm:
        fulltext_url = f"https://europepmc.org/article/med/{pmc_norm}"
    elif doi:
        fulltext_url = f"https://doi.org/{doi}"
    return Paper(
        title=title,
        authors=", ".join(authors[:5]) + (" et al." if len(authors) > 5 else ""),
        journal=journal,
        date=pub_date,
        abstract=abstract or "Abstract unavailable",
        doi=doi,
        pmid=pmid,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
        topic=topic,
        source="pubmed",
        pmc_id=pmc_norm,
        fulltext_url=fulltext_url,
        is_oa=is_oa,
    )


def _request_with_retry(url: str, params: dict, max_retries: int = 3, timeout: int = 30, **kwargs) -> requests.Response:
    for attempt in range(max_retries):
        resp = requests.get(url, params=params, timeout=timeout, **kwargs)
        if resp.status_code == 429:
            wait = 2 ** (attempt + 1)
            print(f"[rate-limited] 429 on {url}, retrying in {wait}s (attempt {attempt+1}/{max_retries})")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp
    raise requests.exceptions.HTTPError(f"429 Too Many Requests after {max_retries} retries: {url}")


def search_pubmed(query: str, topic: str, days_back: int, retmax: int = 30) -> list[Paper]:
    mindate, maxdate = _date_window(days_back)
    params = {
        "db": "pubmed",
        "term": query,
        "mindate": mindate,
        "maxdate": maxdate,
        "datetype": "edat",
        "retmax": retmax,
        "retmode": "json",
        "sort": "date",
    }
    try:
        search_resp = _request_with_retry(f"{EUTILS_BASE}/esearch.fcgi", params)
    except requests.exceptions.HTTPError:
        print(f"[pubmed] search failed for topic '{topic}', skipping")
        return []
    id_list = search_resp.json().get("esearchresult", {}).get("idlist", [])
    if not id_list:
        return []
    time.sleep(0.34)
    fetch_params = {"db": "pubmed", "id": ",".join(id_list), "retmode": "xml"}
    try:
        fetch_resp = _request_with_retry(f"{EUTILS_BASE}/efetch.fcgi", fetch_params, timeout=60)
    except requests.exceptions.HTTPError:
        print(f"[pubmed] fetch failed for topic '{topic}', skipping")
        return []
    root = ET.fromstring(fetch_resp.content)
    papers: list[Paper] = []
    for article in root.findall("PubmedArticle"):
        paper = _parse_pubmed_article(article, topic)
        if paper:
            papers.append(paper)
    return papers


def search_crossref(query: str, topic: str, days_back: int, rows: int = 15) -> list[Paper]:
    from_date = (datetime.now() - timedelta(days=max(1, days_back))).strftime("%Y-%m-%d")
    params = {
        "query": query,
        "filter": f"from-pub-date:{from_date},type:journal-article",
        "rows": rows, "sort": "published", "order": "desc",
    }
    headers = {"User-Agent": "PsychLiteratureDaily/1.0 (mailto:example@qq.com)"}
    resp = requests.get(CROSSREF_BASE, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    items = resp.json().get("message", {}).get("items", [])
    papers: list[Paper] = []
    for item in items:
        title_list = item.get("title") or []
        title = title_list[0] if title_list else ""
        if not title:
            continue
        authors = []
        for a in item.get("author", [])[:5]:
            name = f"{a.get('given', '')} {a.get('family', '')}".strip()
            if name:
                authors.append(name)
        date_parts = item.get("published-print", {}).get("date-parts") or item.get(
            "published-online", {}
        ).get("date-parts") or [[]]
        dp = date_parts[0] if date_parts else []
        date_str = "-".join(str(p) for p in dp) if dp else ""
        doi = item.get("DOI", "")
        license = (item.get("license") or [{}])
        is_oa = any(
            (lic.get("URL", "") or "").startswith("http://creativecommons.org") for lic in license
        )
        fulltext_url = next(
            (lic.get("URL", "") for lic in license if (lic.get("URL", "") or "").startswith("http")),
            f"https://doi.org/{doi}" if doi else "",
        )
        papers.append(Paper(
            title=title,
            authors=", ".join(authors) + (" et al." if len(item.get("author", [])) > 5 else ""),
            journal=(item.get("container-title") or [""])[0],
            date=date_str,
            abstract=item.get("abstract", "Abstract unavailable") or "Abstract unavailable",
            doi=doi,
            url=f"https://doi.org/{doi}" if doi else "",
            topic=topic,
            source="crossref",
            is_oa=is_oa or bool(item.get("is-referenced-by-count")),
            fulltext_url=fulltext_url,
        ))
    return papers


def search_semantic_scholar(query: str, topic: str, limit: int = 15) -> list[Paper]:
    params = {"query": query, "limit": limit, "fields": "title,authors,abstract,year,externalIds,openAccessPdf,journal"}
    resp = requests.get(S2_BASE, params=params, timeout=30)
    if resp.status_code == 429:
        return []
    resp.raise_for_status()
    data = resp.json().get("data", [])
    papers: list[Paper] = []
    for item in data:
        title = item.get("title", "")
        if not title:
            continue
        authors = ", ".join(a.get("name", "") for a in item.get("authors", [])[:5])
        if len(item.get("authors", [])) > 5:
            authors += " et al."
        ext = item.get("externalIds") or {}
        doi = ext.get("DOI", "")
        pmid = str(ext.get("PubMed", ""))
        oa_pdf = item.get("openAccessPdf") or {}
        oa_url = oa_pdf.get("url", "") if isinstance(oa_pdf, dict) else ""
        journal = item.get("journal", {}).get("name", "") if item.get("journal") else ""
        year = item.get("year")
        papers.append(Paper(
            title=title, authors=authors, journal=journal,
            date=str(year) if year else "",
            abstract=item.get("abstract") or "Abstract unavailable",
            doi=doi or "", pmid=pmid,
            url=f"https://www.semanticscholar.org/paper/{item.get('paperId', '')}",
            topic=topic, source="semantic_scholar",
            is_oa=bool(oa_url),
            fulltext_url=oa_url or (f"https://doi.org/{doi}" if doi else ""),
        ))
    return papers


def load_manual_papers(path: str) -> list[Paper]:
    import json
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    papers: list[Paper] = []
    for item in raw:
        papers.append(Paper(
            title=item.get("title", ""),
            authors=item.get("authors", ""),
            journal=item.get("journal", ""),
            date=item.get("date", ""),
            abstract=item.get("abstract", "Abstract unavailable"),
            doi=item.get("doi", ""),
            pmid=item.get("pmid", ""),
            url=item.get("url", ""),
            topic=item.get("topic", "Manual"),
            source="manual",
            fulltext_url=item.get("fulltext_url", "") or item.get("url", ""),
            title_zh=item.get("title_zh", ""),
            abstract_zh=item.get("abstract_zh", ""),
            highlight_zh=item.get("highlight_zh", ""),
        ))
    return papers


def dedupe_papers(papers: list[Paper]) -> list[Paper]:
    seen: set[str] = set()
    result: list[Paper] = []
    for paper in papers:
        key = paper.dedupe_key()
        if key in seen:
            continue
        seen.add(key)
        result.append(paper)
    return result


def filter_history(papers: list[Paper], history_keys: set[str]) -> tuple[list[Paper], int]:
    kept: list[Paper] = []
    skipped = 0
    for paper in papers:
        if paper.dedupe_key() in history_keys:
            skipped += 1
        else:
            kept.append(paper)
    return kept, skipped


def sort_papers(papers: list[Paper]) -> list[Paper]:
    return sorted(papers, key=lambda p: p.date or "0000", reverse=True)


def search_all(config: dict[str, Any]) -> tuple[list[Paper], SearchStats]:
    search_cfg = config.get("search", {})
    sources = search_cfg.get("sources", ["pubmed"])
    days_back = int(search_cfg.get("days_back", 1))
    max_papers = int(search_cfg.get("max_papers", 10))
    topics = config.get("topics", [])
    all_papers: list[Paper] = []
    stats = SearchStats()
    for topic_cfg in topics:
        name = topic_cfg.get("name", "Uncategorized")
        query = topic_cfg.get("query", "")
        if not query:
            continue
        topic_papers: list[Paper] = []
        if "pubmed" in sources:
            topic_papers.extend(search_pubmed(query, name, days_back))
        if "crossref" in sources:
            topic_papers.extend(search_crossref(query, name, days_back))
        if "semantic_scholar" in sources:
            topic_papers.extend(search_semantic_scholar(query, name))
        stats.topic_hits[name] = len(topic_papers)
        all_papers.extend(topic_papers)
        time.sleep(0.34)
    stats.total_raw = len(all_papers)
    all_papers = dedupe_papers(all_papers)
    all_papers = sort_papers(all_papers)[:max_papers]
    stats.total_after_dedupe = len(all_papers)
    return all_papers, stats


def translate_papers(papers: list[Paper], enabled: bool = True) -> None:
    if not enabled or not papers:
        return
    try:
        from translate import build_highlight, flush_cache, translate_abstract, translate_title
    except Exception as exc:
        print(f"[translate] Module unavailable: {exc}")
        return
    total = len(papers)
    for idx, paper in enumerate(papers, 1):
        if paper.title_zh and paper.abstract_zh:
            if not paper.highlight_zh:
                paper.highlight_zh = build_highlight(paper.title_zh, paper.abstract_zh)
            continue
        try:
            title_zh = translate_title(paper.title) if paper.title else ""
            abstract_zh = translate_abstract(paper.abstract)
            paper.title_zh = title_zh or paper.title
            paper.abstract_zh = abstract_zh or "Abstract unavailable"
            paper.highlight_zh = build_highlight(paper.title_zh, paper.abstract_zh)
        except Exception as exc:
            paper.title_zh = paper.title_zh or paper.title
            paper.abstract_zh = paper.abstract_zh or paper.abstract
            paper.highlight_zh = paper.highlight_zh or f"Topic: {paper.title_zh}"
    try:
        flush_cache()
    except Exception as exc:
        print(f"[translate] Cache write failed: {exc}")
