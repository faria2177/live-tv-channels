#!/usr/bin/env python3
"""
circleftp_series_scraper.py
============================
Advanced scraper for CircleFTP TV-series category pages.

It crawls these category trees:
    English_Tv_Series  -> /category/english-foreign-tv-series/   (pages 1-70)
    Dubbed_Tv_Series    -> /category/dubbed-tv-series-shows/      (pages 1-25)
    Hindi_Tv_Series     -> /category/hindi-tv-serials/             (pages 1-25)

For every series detail page it extracts:
    title, year, language, poster(s), and every episode/video link
    (season, episode, episode_title, url, added-date)

Results are merged (not overwritten) into:
    series/CF/English_Tv_Series.json
    series/CF/Dubbed_Tv_Series.json
    series/CF/Hindi_Tv_Series.json

so re-running the script only ADDS newly discovered series/episodes and
never deletes history. This is what makes it safe to run on a schedule
(see .github/workflows/circleftp-series-scan.yml) every 2 days.

Author: generated for faria2177/live-tv-channels
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

CF_DOMAIN = "circleftp.net"

CATEGORIES = {
    "English_Tv_Series": {
        "base_url": "http://main.circleftp.net/category/english-foreign-tv-series/",
        "max_pages": 70,
    },
    "Dubbed_Tv_Series": {
        "base_url": "http://main.circleftp.net/category/dubbed-tv-series-shows/",
        "max_pages": 25,
    },
    "Hindi_Tv_Series": {
        "base_url": "http://main.circleftp.net/category/hindi-tv-serials/",
        "max_pages": 25,
    },
}

OUTPUT_DIR = os.environ.get("CF_OUTPUT_DIR", "series/CF")
MAX_POSTERS_PER_SERIES = 8
REQUEST_TIMEOUT = 25
DEFAULT_WORKERS = 4
DEFAULT_DELAY = 0.6  # polite delay (seconds) between detail-page requests / thread

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
    "CircleFTP-Series-Bot/1.0 (+https://github.com/faria2177/live-tv-channels)"
)

VIDEO_RX = re.compile(
    r"\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v|ts|m3u8|mpg|mpeg|3gp|ogv|m3u|rmvb)([?#]|$)",
    re.IGNORECASE,
)
IMG_RX = re.compile(r"\.(jpg|jpeg|png|webp|gif|bmp|avif)([?#]|$)", re.IGNORECASE)
SERIES_HINT_RX = re.compile(
    r"\b(tv\s*series|web\s*series|series|show|shows|season\s*\d+|episode\s*\d+|"
    r"ep\.?\s*\d+|s\s*\d+\s*e\s*\d+|\d{1,2}x\d{1,3})\b",
    re.IGNORECASE,
)
CATEGORY_SERIES_RX = re.compile(
    r"tv-series|tv\s*series|web-series|web\s*series|series-shows|shows|season|episode",
    re.IGNORECASE,
)
DETAIL_SKIP_RX = re.compile(
    r"/(category|cat|tag|page|search|feed|wp-admin|wp-content|wp-json)/", re.IGNORECASE
)
CARD_CONTAINER_TAGS = {"article", "li", "div", "figure", "section", "tr"}
CARD_CONTAINER_CLASS_RX = re.compile(r"post|entry|card|item|thumb", re.IGNORECASE)

log = logging.getLogger("circleftp_scraper")


# --------------------------------------------------------------------------- #
# Small helpers (ported 1:1 from the browser-extension logic)
# --------------------------------------------------------------------------- #

def clean(value: str = "") -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def is_video_url(url: str) -> bool:
    return bool(VIDEO_RX.search(url or ""))


def is_image_url(url: str) -> bool:
    return bool(IMG_RX.search(url or ""))


def absolute(url: str, base: str) -> str:
    try:
        return urljoin(base, url)
    except Exception:
        return ""


def filename_of(url: str) -> str:
    try:
        return os.path.basename(urlparse(url).path)
    except Exception:
        return ""


def extract_year(text: str = "") -> str:
    match = re.search(r"\b(19|20)\d{2}\b", text or "")
    return match.group(0) if match else ""


def extract_language(text: str = "") -> str:
    scope = (text or "").lower()
    if re.search(r"hindi.?dual|dual.?audio|dual.?hindi", scope):
        return "Hindi Dual"
    if re.search(r"bangla|bengali", scope):
        return "Bangla"
    if re.search(r"hindi", scope):
        return "Hindi"
    if re.search(r"tamil", scope):
        return "Tamil"
    if re.search(r"telugu", scope):
        return "Telugu"
    if re.search(r"english", scope):
        return "English"
    return "English"


def parse_episode(text: str = ""):
    text = text or ""
    m = re.search(r"[Ss][:\s._-]?(\d{1,2})[\s._-]*[Ee][:\s._-]?(\d{1,3})", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"\b(\d{1,2})x(\d{1,3})\b", text, re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"season\s*(\d{1,2}).{0,20}?episode\s*(\d{1,3})", text, re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"\bep\.?\s*(\d{1,3})\b", text, re.IGNORECASE)
    if m:
        return 1, int(m.group(1))
    return None


def normalize_series_title(title: str = "") -> str:
    title = clean(title)
    title = re.sub(r"\b(tv\s*series|web\s*series)\b", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"[._|-]+", " ", title)
    return clean(title)


def normalize_key(title: str = "") -> str:
    """Key used to merge duplicate series across runs/pages (ignores case/season noise)."""
    title = normalize_series_title(title)
    title = re.sub(r"\b(season\s*\d+|episode\s*\d+|s\s*\d+\s*e\s*\d+)\b", " ", title, flags=re.IGNORECASE)
    return clean(title).lower() or "untitled"


def extract_episode_title(raw_text: str, series_title: str, season: int, episode: int) -> str:
    title = clean(raw_text)
    title = re.sub(r"https?://\S+", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\b(download|watch|play|copy|server\s*\d+)\b", "", title, flags=re.IGNORECASE)
    title = re.sub(
        r"\b(2160p?|1080p?|720p?|480p?|4k|uhd|webrip|web-dl|bluray|hdrip|x264|x265|hevc)\b",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = clean(title)
    if title and len(title) <= 140:
        return title
    return f"{series_title}.S:{season}E:{episode}"


# --------------------------------------------------------------------------- #
# HTTP session with retry/backoff
# --------------------------------------------------------------------------- #

def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=20)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.8,bn;q=0.6",
        }
    )
    return session


def fetch_soup(session: requests.Session, url: str) -> BeautifulSoup | None:
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        resp.encoding = resp.encoding or "utf-8"
        return BeautifulSoup(resp.text, "lxml")
    except requests.RequestException as exc:
        log.warning("fetch failed for %s: %s", url, exc)
        return None


# --------------------------------------------------------------------------- #
# Poster / title / episode extraction
# --------------------------------------------------------------------------- #

def get_meta(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and clean(tag.get("content", "")):
            return clean(tag.get("content", ""))
    return ""


def poster_score(url: str, marker: str, width: int = 0, height: int = 0) -> int:
    score = 0
    blob = f"{marker} {url}"
    if re.search(r"poster|cover|featured|thumb|thumbnail|banner|wp-post-image", blob, re.IGNORECASE):
        score += 4
    if height > width:
        score += 4
    if height >= 220:
        score += 3
    if width >= 140:
        score += 2
    if re.search(r"uploads|image|img", url, re.IGNORECASE):
        score += 1
    return score


def collect_poster_candidates(soup: BeautifulSoup, base_url: str) -> list[str]:
    candidates: list[tuple[str, int]] = []
    seen: set[str] = set()

    meta_poster = get_meta(soup, "og:image", "twitter:image")
    if meta_poster:
        url = absolute(meta_poster, base_url)
        if url:
            candidates.append((url, 100))
            seen.add(url)

    for img in soup.find_all("img"):
        for attr in ("src", "data-src", "data-lazy-src", "data-original"):
            raw = img.get(attr)
            if not raw:
                continue
            url = absolute(raw, base_url)
            if not url or url in seen or not is_image_url(url):
                continue
            seen.add(url)
            try:
                width = int(img.get("width", 0) or 0)
                height = int(img.get("height", 0) or 0)
            except ValueError:
                width, height = 0, 0
            marker = f"{img.get('alt', '')} {' '.join(img.get('class', []) or [])}"
            candidates.append((url, poster_score(url, marker, width, height)))

    candidates.sort(key=lambda item: item[1], reverse=True)
    ordered = []
    for url, _ in candidates:
        if url not in ordered:
            ordered.append(url)
    return ordered[:MAX_POSTERS_PER_SERIES]


def extract_series_title(soup: BeautifulSoup, fallback_title: str = "") -> str:
    candidates = []
    h1 = soup.find("h1")
    if h1:
        candidates.append(h1.get_text())
    for sel in (".entry-title", ".post-title", ".series-title", ".title", "h2"):
        el = soup.select_one(sel)
        if el:
            candidates.append(el.get_text())
            break
    candidates.append(get_meta(soup, "og:title", "twitter:title"))
    if soup.title:
        candidates.append(soup.title.get_text())
    candidates.append(fallback_title)

    for raw in candidates:
        normalized = normalize_series_title(raw or "")
        if normalized and 2 <= len(normalized) <= 180:
            return normalized
    return "Unknown Series"


def is_series_scoped_page(soup: BeautifulSoup, page_url: str) -> bool:
    body_text = clean(soup.body.get_text(" ") if soup.body else "")[:1800]
    scope = " ".join(
        [page_url, soup.title.get_text() if soup.title else "", get_meta(soup, "og:title"), body_text]
    )
    return bool(SERIES_HINT_RX.search(scope) or CATEGORY_SERIES_RX.search(scope))


def build_series_payload(soup: BeautifulSoup, page_url: str, seed: dict | None = None) -> dict | None:
    seed = seed or {}
    if not is_series_scoped_page(soup, page_url) and not seed.get("force"):
        return None

    title = extract_series_title(soup, seed.get("title", ""))
    poster_list = list(seed.get("posters") or [])
    if seed.get("poster"):
        poster_list.append(seed["poster"])
    poster_list += collect_poster_candidates(soup, page_url)
    posters = list(dict.fromkeys(p for p in poster_list if p))[:MAX_POSTERS_PER_SERIES]

    body_text = clean(soup.body.get_text(" ") if soup.body else "")[:800]
    year = seed.get("year") or extract_year(" ".join([title, soup.title.get_text() if soup.title else "", body_text]))
    language = seed.get("language") or extract_language(" ".join([title, soup.title.get_text() if soup.title else "", page_url]))
    season_match = re.search(r"season\s*(\d{1,2})|s\s*(\d{1,2})", " ".join([title, page_url]), re.IGNORECASE)
    page_season_hint = int(season_match.group(1) or season_match.group(2)) if season_match else 1

    links = []
    seen = set()
    fallback_episode = 1

    for a in soup.find_all("a", href=True):
        url = absolute(a["href"], page_url)
        if not url or not is_video_url(url):
            continue

        container = a.find_parent(["tr", "li", "div", "p", "article", "section"])
        context = clean(
            " | ".join(
                filter(
                    None,
                    [
                        a.get_text(),
                        a.get("title", ""),
                        a.get("aria-label", ""),
                        container.get_text(" ") if container else "",
                        filename_of(url),
                    ],
                )
            )
        )

        episode_info = parse_episode(context) or parse_episode(url)
        if not episode_info:
            episode_info = (page_season_hint or 1, fallback_episode)
        season, episode = episode_info

        dedupe_key = (season, episode, url)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        links.append(
            {
                "added": today(),
                "language": extract_language(f"{language} {context} {url}"),
                "season": season,
                "episode": episode,
                "episode_title": extract_episode_title(context, title, season, episode),
                "url": url,
            }
        )
        fallback_episode = max(fallback_episode + 1, episode + 1)

    if not links:
        return None

    links.sort(key=lambda x: (x["season"], x["episode"], x["url"]))

    return {
        "title": title,
        "year": year,
        "tvg_logo": posters[0] if posters else "",
        "posters": posters,
        "source_url": page_url,
        "links": links,
    }


def find_card_root(anchor):
    node = anchor
    for _ in range(4):
        parent = node.find_parent(list(CARD_CONTAINER_TAGS) + ["figure"])
        if parent is None:
            break
        node = parent
        classes = " ".join(node.get("class", []) or [])
        if CARD_CONTAINER_CLASS_RX.search(classes) or node.name in ("article", "li", "figure"):
            return node
    return anchor


def page_looks_like_series_category(soup: BeautifulSoup, page_url: str) -> bool:
    body_text = clean(soup.body.get_text(" ") if soup.body else "")[:1200]
    scope = " ".join([page_url, soup.title.get_text() if soup.title else "", body_text])
    return bool(CATEGORY_SERIES_RX.search(scope))


def collect_series_cards(soup: BeautifulSoup, page_url: str) -> list[dict]:
    results = []
    seen = set()
    category_like = page_looks_like_series_category(soup, page_url)

    for a in soup.find_all("a", href=True):
        detail_url = absolute(a["href"], page_url)
        if not detail_url or detail_url in seen:
            continue
        seen.add(detail_url)

        parsed = urlparse(detail_url)
        if CF_DOMAIN not in parsed.hostname.lower() if parsed.hostname else True:
            continue
        if DETAIL_SKIP_RX.search(parsed.path):
            continue
        if detail_url.endswith("#"):
            continue

        card_root = find_card_root(a)
        image = card_root.find("img") or a.find("img")
        if not image:
            continue

        heading = card_root.select_one("h1,h2,h3,h4,.title,.entry-title,.post-title,figcaption")
        title = normalize_series_title(
            (heading.get_text() if heading else "")
            or image.get("alt", "")
            or a.get("title", "")
            or a.get_text()
        )

        page_context = clean(" ".join([title, detail_url, card_root.get_text(" "), parsed.path]))
        if not title or not (SERIES_HINT_RX.search(page_context) or category_like):
            continue

        posters = collect_poster_candidates(card_root, page_url)
        results.append(
            {
                "title": title,
                "year": extract_year(page_context),
                "language": extract_language(page_context),
                "poster": posters[0] if posters else "",
                "posters": posters,
                "detail_url": detail_url,
            }
        )

    return results


# --------------------------------------------------------------------------- #
# Crawl orchestration
# --------------------------------------------------------------------------- #

@dataclass
class ScanStats:
    pages_scanned: int = 0
    cards_found: int = 0
    new_series: int = 0
    new_episodes: int = 0
    updated_series: int = 0
    lock: Lock = field(default_factory=Lock)

    def bump(self, **kwargs):
        with self.lock:
            for key, value in kwargs.items():
                setattr(self, key, getattr(self, key) + value)


def category_page_url(base_url: str, page: int) -> str:
    if page <= 1:
        return base_url
    return urljoin(base_url, f"page/{page}/")


def crawl_category(name: str, base_url: str, max_pages: int, session: requests.Session, delay: float) -> dict[str, dict]:
    """Returns detail_url -> card dict (deduplicated) for the whole category."""
    cards: dict[str, dict] = {}
    consecutive_empty = 0

    for page in range(1, max_pages + 1):
        url = category_page_url(base_url, page)
        soup = fetch_soup(session, url)
        time.sleep(delay)
        if soup is None:
            consecutive_empty += 1
            log.info("[%s] page %d/%d -> not reachable (skipping)", name, page, max_pages)
            if consecutive_empty >= 3:
                log.info("[%s] stopping early after 3 unreachable pages", name)
                break
            continue

        page_cards = collect_series_cards(soup, url)
        consecutive_empty = 0
        new_on_page = 0
        for card in page_cards:
            if card["detail_url"] not in cards:
                cards[card["detail_url"]] = card
                new_on_page += 1
        log.info("[%s] page %d/%d -> %d cards (%d new)", name, page, max_pages, len(page_cards), new_on_page)

        if page_cards and new_on_page == 0 and page > 1:
            # WordPress pagination often repeats the last page once max is exceeded
            log.info("[%s] page %d repeats previous results -> assuming end of category", name, page)
            break

    return cards


def fetch_series_detail(session: requests.Session, card: dict, delay: float) -> dict | None:
    soup = fetch_soup(session, card["detail_url"])
    time.sleep(delay)
    if soup is None:
        return None
    return build_series_payload(soup, card["detail_url"], {**card, "force": True})


def scrape_category(
    name: str,
    base_url: str,
    max_pages: int,
    session: requests.Session,
    workers: int,
    delay: float,
    stats: ScanStats,
) -> list[dict]:
    log.info("=== Scanning category %s (%s) ===", name, base_url)
    cards = crawl_category(name, base_url, max_pages, session, delay)
    stats.bump(cards_found=len(cards))
    log.info("[%s] %d unique series cards discovered, fetching details...", name, len(cards))

    payloads = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_series_detail, session, card, delay): card for card in cards.values()}
        for future in as_completed(futures):
            card = futures[future]
            try:
                payload = future.result()
            except Exception as exc:  # noqa: BLE001
                log.warning("[%s] failed detail fetch %s: %s", name, card["detail_url"], exc)
                continue
            if payload:
                payloads.append(payload)

    log.info("[%s] %d series payloads extracted", name, len(payloads))
    return payloads


# --------------------------------------------------------------------------- #
# Merge + persist
# --------------------------------------------------------------------------- #

def load_existing(path: str) -> dict:
    if not os.path.exists(path):
        return {"series": {}}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        data.setdefault("series", {})
        return data
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("could not read existing %s (%s) -> starting fresh", path, exc)
        return {"series": {}}


def merge_payloads(existing: dict, payloads: list[dict], stats: ScanStats) -> dict:
    buckets: dict[str, dict] = {}
    key_by_norm: dict[str, str] = {}

    for title, data in existing.get("series", {}).items():
        norm = normalize_key(title)
        buckets[norm] = data
        key_by_norm[norm] = title

    for payload in payloads:
        norm = normalize_key(payload["title"])
        bucket = buckets.get(norm)
        is_new_series = bucket is None
        if is_new_series:
            bucket = {
                "title": payload["title"],
                "year": str(payload.get("year") or ""),
                "tvg_logo": "",
                "posters": [],
                "source_url": payload.get("source_url", ""),
                "links": [],
                "updated_at": today(),
            }
            buckets[norm] = bucket
            stats.bump(new_series=1)

        if not bucket.get("year") and payload.get("year"):
            bucket["year"] = str(payload["year"])
        if payload.get("source_url"):
            bucket["source_url"] = payload["source_url"]

        for poster in [payload.get("tvg_logo")] + list(payload.get("posters") or []):
            if poster and poster not in bucket["posters"]:
                bucket["posters"].append(poster)
        bucket["posters"] = bucket["posters"][:MAX_POSTERS_PER_SERIES]
        if not bucket.get("tvg_logo") and bucket["posters"]:
            bucket["tvg_logo"] = bucket["posters"][0]

        existing_keys = {(l["season"], l["episode"], l["url"]) for l in bucket["links"]}
        added_here = 0
        for link in payload.get("links", []):
            dedupe_key = (link["season"], link["episode"], link["url"])
            if dedupe_key in existing_keys:
                continue
            existing_keys.add(dedupe_key)
            bucket["links"].append(link)
            added_here += 1

        if added_here:
            bucket["links"].sort(key=lambda x: (x["season"], x["episode"], x["url"]))
            bucket["updated_at"] = today()
            stats.bump(new_episodes=added_here)
            if not is_new_series:
                stats.bump(updated_series=1)

    series_out = {bucket["title"]: bucket for bucket in buckets.values()}
    return dict(sorted(series_out.items(), key=lambda kv: kv[0].lower()))


def atomic_write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


# --------------------------------------------------------------------------- #
# CLI entry point
# --------------------------------------------------------------------------- #

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CircleFTP TV series scraper")
    parser.add_argument(
        "--category",
        choices=list(CATEGORIES.keys()),
        action="append",
        help="Limit scan to one or more categories (default: all)",
    )
    parser.add_argument("--max-pages", type=int, help="Override max pages for every selected category")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Concurrent detail-page fetchers")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="Delay (s) between requests")
    parser.add_argument("--output-dir", default=OUTPUT_DIR, help="Where to write series/CF/*.json")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    selected = args.category or list(CATEGORIES.keys())
    session = build_session()
    overall_stats = ScanStats()
    changed_files = []

    for name in selected:
        conf = CATEGORIES[name]
        max_pages = args.max_pages or conf["max_pages"]
        stats = ScanStats()

        payloads = scrape_category(
            name, conf["base_url"], max_pages, session, args.workers, args.delay, stats
        )

        out_path = os.path.join(args.output_dir, f"{name}.json")
        existing = load_existing(out_path)
        merged_series = merge_payloads(existing, payloads, stats)

        output = {
            "category": name,
            "base_url": conf["base_url"],
            "pages_scanned": max_pages,
            "last_scan": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "series_count": len(merged_series),
            "episode_count": sum(len(s["links"]) for s in merged_series.values()),
            "series": merged_series,
        }

        if stats.new_series or stats.new_episodes:
            atomic_write_json(out_path, output)
            changed_files.append(out_path)
            log.info(
                "[%s] WROTE %s -> +%d series, +%d episodes (total %d series / %d episodes)",
                name, out_path, stats.new_series, stats.new_episodes,
                output["series_count"], output["episode_count"],
            )
        else:
            # still refresh metadata (last_scan) even with no content changes, but
            # only touch the file if it didn't already exist to avoid noisy diffs
            if not os.path.exists(out_path):
                atomic_write_json(out_path, output)
                changed_files.append(out_path)
            log.info("[%s] no new series/episodes found", name)

        overall_stats.bump(
            new_series=stats.new_series,
            new_episodes=stats.new_episodes,
            updated_series=stats.updated_series,
            cards_found=stats.cards_found,
        )

    log.info(
        "=== DONE: %d new series, %d new episodes across %d categories (%d files changed) ===",
        overall_stats.new_series, overall_stats.new_episodes, len(selected), len(changed_files),
    )

    # Emit a small machine-readable summary for the GitHub Actions step that
    # writes the commit message.
    summary_path = os.environ.get("CF_SUMMARY_PATH", "")
    if summary_path:
        with open(summary_path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "new_series": overall_stats.new_series,
                    "new_episodes": overall_stats.new_episodes,
                    "changed_files": changed_files,
                },
                fh,
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
