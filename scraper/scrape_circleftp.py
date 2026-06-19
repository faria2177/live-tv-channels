#!/usr/bin/env python3
"""
CircleFTP TV Series Scraper
============================
Scrapes English, Dubbed, and Hindi TV Series from CircleFTP
and saves them as JSON files in series/CF/ folder.

Categories:
  - English TV Series  : /category/english-foreign-tv-series/  (page 1–70)
  - Dubbed TV Series   : /category/dubbed-tv-series-shows/     (page 1–25)
  - Hindi TV Series    : /category/hindi-tv-serials/           (page 1–25)
"""

import os
import re
import json
import time
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# ── Logging setup ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("circleftp")

# ── Constants ──────────────────────────────────────────────────────────────────
BASE_URL   = "https://main.circleftp.net"
OUTPUT_DIR = Path("series/CF")

CATEGORIES = [
    {
        "name":     "English_Tv_Series",
        "url":      "/category/english-foreign-tv-series/page/{page}/",
        "max_page": 70,
        "label":    "English TV Series",
    },
    {
        "name":     "Dubbed_Tv_Series",
        "url":      "/category/dubbed-tv-series-shows/page/{page}/",
        "max_page": 25,
        "label":    "Dubbed TV Series",
    },
    {
        "name":     "Hindi_Tv_Series",
        "url":      "/category/hindi-tv-serials/page/{page}/",
        "max_page": 25,
        "label":    "Hindi TV Series",
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

REQUEST_DELAY   = 1.5   # seconds between requests
REQUEST_TIMEOUT = 20    # seconds
MAX_RETRIES     = 3

# ── Helpers ────────────────────────────────────────────────────────────────────

def clean(text: str) -> str:
    """Strip and collapse whitespace."""
    return re.sub(r"\s+", " ", (text or "").strip())


def extract_year(text: str) -> str:
    """Pull a 4-digit year (1980–2029) from any string."""
    m = re.search(r"\b(19[89]\d|20[0-2]\d)\b", text or "")
    return m.group(1) if m else ""


def fetch(url: str, session: requests.Session) -> BeautifulSoup | None:
    """Fetch a URL with retry logic; return BeautifulSoup or None on failure."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 404:
                log.debug("404 → %s", url)
                return None
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as exc:
            log.warning("Attempt %d/%d failed for %s — %s", attempt, MAX_RETRIES, url, exc)
            if attempt < MAX_RETRIES:
                time.sleep(3 * attempt)
    log.error("Giving up on %s", url)
    return None


def get_poster(card) -> str:
    """Extract poster/thumbnail URL from a card element."""
    for attr in ("src", "data-src", "data-lazy-src", "data-original"):
        img = card.find("img", attrs={attr: True})
        if img:
            src = img.get(attr, "").strip()
            if src and not src.endswith(".gif") and "icon" not in src.lower():
                return src
    # fallback: any img
    img = card.find("img")
    if img:
        return img.get("src", "").strip()
    return ""


def get_title(card, detail_url: str = "") -> str:
    """Extract series title from a card element."""
    # 1. img alt text
    img = card.find("img")
    if img and img.get("alt", "").strip():
        t = clean(img["alt"])
        if len(t) > 2:
            return t
    # 2. heading tags
    for tag in ["h1", "h2", "h3", "h4"]:
        el = card.find(tag)
        if el:
            t = clean(el.get_text())
            if len(t) > 2:
                return t
    # 3. .entry-title / .title class
    for cls in ["entry-title", "post-title", "title", "movie-title"]:
        el = card.find(class_=cls)
        if el:
            t = clean(el.get_text())
            if len(t) > 2:
                return t
    # 4. anchor text
    a = card.find("a", href=True)
    if a:
        t = clean(a.get_text())
        if len(t) > 2:
            return t
    # 5. slug from URL
    if detail_url:
        try:
            slug = urlparse(detail_url).path.rstrip("/").split("/")[-1]
            return slug.replace("-", " ").title()
        except Exception:
            pass
    return ""


def parse_category_page(soup: BeautifulSoup, category_label: str) -> list[dict]:
    """
    Parse one listing page and return a list of series card dicts.
    Each dict: { title, url, poster, year, category, scraped_at }
    """
    results = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # CircleFTP uses WordPress — articles / .post elements
    card_selectors = [
        "article",
        ".post",
        ".item",
        ".entry",
        ".card",
        ".thumb",
        ".postbox",
    ]

    cards = []
    for sel in card_selectors:
        found = soup.select(sel)
        if found:
            cards = found
            break

    # fallback: grab all anchor+img combos from main content
    if not cards:
        main = soup.find("main") or soup.find("div", id="main") or soup.body
        if main:
            cards = [a.parent for a in main.find_all("a", href=True) if a.find("img")]

    seen = set()
    for card in cards:
        # find detail link
        a = card.find("a", href=True)
        if not a:
            continue
        href = a["href"].strip()
        if not href.startswith("http"):
            href = urljoin(BASE_URL, href)

        # skip pagination, category, tag links
        parsed = urlparse(href)
        if not parsed.netloc or "circleftp.net" not in parsed.netloc:
            continue
        path_parts = [p for p in parsed.path.split("/") if p]
        skip_keywords = {"category", "cat", "tag", "page", "search", "feed", "wp-"}
        if any(k in parsed.path for k in skip_keywords):
            continue
        if len(path_parts) < 1:
            continue

        if href in seen:
            continue
        seen.add(href)

        title  = get_title(card, href)
        poster = get_poster(card)
        year   = extract_year(title + " " + href)

        if not title or len(title) < 2:
            continue

        results.append({
            "title":      title,
            "url":        href,
            "poster":     poster,
            "year":       year,
            "category":   category_label,
            "scraped_at": today,
        })

    return results


def scrape_category(cat: dict, session: requests.Session) -> list[dict]:
    """Scrape all pages of one category and return deduplicated series list."""
    all_items: list[dict] = []
    seen_urls: set[str]   = set()
    name      = cat["name"]
    label     = cat["label"]
    max_page  = cat["max_page"]

    log.info("━━━ Starting: %s (pages 1–%d) ━━━", label, max_page)

    for page_num in range(1, max_page + 1):
        url = BASE_URL + cat["url"].format(page=page_num)
        log.info("  [%s] Page %d/%d → %s", name, page_num, max_page, url)

        soup = fetch(url, session)
        if soup is None:
            log.warning("  Skipping page %d (fetch failed)", page_num)
            time.sleep(REQUEST_DELAY)
            continue

        # detect last page (WordPress returns 404 or redirects to page 1)
        canonical = soup.find("link", {"rel": "canonical"})
        if canonical:
            canon_url = canonical.get("href", "")
            # if canonical points to page 1 and we're not on page 1 → end of pages
            if page_num > 1 and f"/page/{page_num}/" not in canon_url:
                log.info("  Reached last page at page %d — stopping.", page_num)
                break

        items = parse_category_page(soup, label)
        new_count = 0
        for item in items:
            if item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                all_items.append(item)
                new_count += 1

        log.info("  Page %d → %d new items (total so far: %d)", page_num, new_count, len(all_items))

        if page_num < max_page:
            time.sleep(REQUEST_DELAY)

    log.info("  ✅ %s done — %d series collected", label, len(all_items))
    return all_items


# ── Merge with existing JSON (detect new entries) ──────────────────────────────

def load_existing(path: Path) -> tuple[list[dict], set[str]]:
    """Load existing JSON file; return (items, url_set)."""
    if not path.exists():
        return [], set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else []
        return items, {it["url"] for it in items if "url" in it}
    except Exception as exc:
        log.warning("Could not read %s: %s", path, exc)
        return [], set()


def merge(existing: list[dict], fresh: list[dict], existing_urls: set[str]) -> tuple[list[dict], int]:
    """
    Merge fresh items into existing list.
    Returns (merged_list, new_count).
    New items are prepended so latest appear first.
    """
    new_items = [it for it in fresh if it["url"] not in existing_urls]
    merged    = new_items + existing
    return merged, len(new_items)


# ── Summary JSON (metadata across all categories) ─────────────────────────────

def write_summary(output_dir: Path, stats: list[dict]) -> None:
    summary = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "categories":   stats,
    }
    path = output_dir / "summary.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("📋 Summary written → %s", path)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="CircleFTP TV Series Scraper")
    parser.add_argument(
        "--force-full",
        action="store_true",
        help="Ignore existing JSON and do a full fresh scrape",
    )
    parser.add_argument(
        "--category",
        choices=["english", "dubbed", "hindi", "all"],
        default="all",
        help="Which category to scrape (default: all)",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(HEADERS)

    stats   = []
    total_new = 0

    cats_to_run = {
        "english": ["English_Tv_Series"],
        "dubbed":  ["Dubbed_Tv_Series"],
        "hindi":   ["Hindi_Tv_Series"],
        "all":     ["English_Tv_Series", "Dubbed_Tv_Series", "Hindi_Tv_Series"],
    }[args.category]

    for cat in CATEGORIES:
        if cat["name"] not in cats_to_run:
            continue

        out_path = OUTPUT_DIR / f"{cat['name']}.json"

        # scrape fresh data
        fresh = scrape_category(cat, session)

        if args.force_full:
            merged, new_count = fresh, len(fresh)
        else:
            existing, existing_urls = load_existing(out_path)
            merged, new_count       = merge(existing, fresh, existing_urls)

        # write JSON
        out_path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("💾 Saved %d items → %s  (%d new)", len(merged), out_path, new_count)

        stats.append({
            "name":      cat["name"],
            "label":     cat["label"],
            "total":     len(merged),
            "new_added": new_count,
        })
        total_new += new_count

    write_summary(OUTPUT_DIR, stats)

    log.info("")
    log.info("═══════════════════════════════════")
    log.info("  ✅  Scrape complete!")
    log.info("  📦  Total new series added: %d", total_new)
    for s in stats:
        log.info("  %-25s → %4d total  (%d new)", s["label"], s["total"], s["new_added"])
    log.info("═══════════════════════════════════")

    # Exit code 0 even if no new items (GitHub Actions won't fail)


if __name__ == "__main__":
    main()
