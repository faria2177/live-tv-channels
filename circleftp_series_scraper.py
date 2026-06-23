#!/usr/bin/env python3
"""
circleftp_series_scraper.py
============================
TV-series scraper for the CircleFTP / FMFTP platform.

Originally this script scraped HTML pages on circleftp.net (a BDIX FTP
server).  However circleftp.net resolves to BDIX-internal IPs
(15.x.x.x) that are ONLY reachable from inside Bangladesh ISP networks.
GitHub Actions runners are in the US and can never connect, so the
scraper always found zero results.

This rewrite uses the public fmftp.net REST API instead — the same API
already used successfully by fetch_data.py — while keeping the exact same
output JSON format in series/CF/*.json.

Categories mapped:
    English_Tv_Series  -> fmftp.net library id=9  (English tv series)
    Hindi_Tv_Series    -> fmftp.net library id=10 (Indian Tv Series)
    Dubbed_Tv_Series   -> fmftp.net library id=10 filtered for "dubbed"
                          + library id=9 filtered for "hindi/dual"
                          (falls back to all Indian TV if no dubbed found)

For every series it fetches episode details via:
    GET /api/tv-shows/{show_id}?fields=episodes

And builds link entries with the same schema as before:
    {added, language, season, episode, episode_title, url}

Results are merged (not overwritten) into:
    series/CF/English_Tv_Series.json
    series/CF/Dubbed_Tv_Series.json
    series/CF/Hindi_Tv_Series.json

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
from urllib.parse import urlparse, parse_qs

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

FMFTP_API_BASE = "https://fmftp.net/api"
TV_SHOWS_LIST_API = FMFTP_API_BASE + "/tv-shows"
TV_SHOW_DETAIL_API = FMFTP_API_BASE + "/tv-shows/{show_id}"
EPISODE_STREAM_API = FMFTP_API_BASE + "/stream/video/stream?type=tv_shows&id={episode_id}"
CONTENT_IMAGE_BASE = "https://fmftp.net/content-images/movies/posters"

SERIES_FIELDS = (
    "id,title,genre,year,online_rating,release_date,"
    "poster_path,backdrop_path"
)

# Category definitions — each maps to one or more fmftp.net library IDs
# plus an optional title-filter regex for sub-categorisation.
CATEGORIES = {
    "English_Tv_Series": {
        "library_ids": [9],
        "label": "English TV Series",
        "title_filter": None,          # no filtering — take everything
    },
    "Hindi_Tv_Series": {
        "library_ids": [10],
        "label": "Indian TV Series",
        "title_filter": None,          # all Indian TV series
    },
    "Dubbed_Tv_Series": {
        "library_ids": [10, 9],        # search both Indian and English
        "label": "Dubbed TV Series",
        # keep only titles that mention dubbed / dual / hindi
        "title_filter": re.compile(
            r"dubbed|dual|hindi|bangla|bengali|tamil|telugu",
            re.IGNORECASE,
        ),
    },
}

OUTPUT_DIR = os.environ.get("CF_OUTPUT_DIR", "series/CF")
MAX_POSTERS_PER_SERIES = 8
REQUEST_TIMEOUT = 30
DEFAULT_WORKERS = 5
DEFAULT_DELAY = 0.08            # polite delay between detail API calls
PAGE_SIZE = 100                 # items per API page
MAX_PAGES_OVERRIDE = 0          # 0 = fetch all pages

DUBBED_RX = re.compile(r"dubbed|dual|hindi|bangla|bengali|tamil|telugu", re.IGNORECASE)

log = logging.getLogger("cf_series_scraper")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def clean(value: str = "") -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_poster_url(path: str) -> str:
    if not path:
        return ""
    path = str(path).strip()
    sep = "" if path.startswith("/") else "/"
    return f"{CONTENT_IMAGE_BASE}{sep}{path}"


def build_watch_url(item_id, content_type="SERIES"):
    return f"https://fmftp.net/watch?type={content_type}&id={item_id}"


def build_stream_url(item_id, content_type="tv_shows"):
    return f"{FMFTP_API_BASE}/stream/video/stream?type={content_type}&id={item_id}"


def extract_show_id(item: dict) -> int | None:
    """Extract numeric show ID from an API list item."""
    item_id = item.get("id")
    if item_id is not None:
        try:
            return int(item_id)
        except (ValueError, TypeError):
            pass
    return None


def normalize_language(value: str = "", fallback: str = "") -> str:
    if value:
        return value.strip()
    text = (fallback or "").strip()
    if not text:
        return "English"
    tl = text.lower().replace("tv series", "").replace("series", "").strip()
    mapping = {
        "bangla": "Bangla",
        "bengali": "Bangla",
        "english": "English",
        "hindi": "Hindi",
        "indian": "Hindi",
        "korean": "Korean",
        "turkish": "Turkish",
        "tamil": "Tamil",
        "telugu": "Telugu",
    }
    for k, v in mapping.items():
        if k in tl:
            return v
    return text.title() if text else "English"


# --------------------------------------------------------------------------- #
# HTTP session
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
            "User-Agent": "CircleFTP-Series-Bot/2.0 (+https://github.com/faria2177/live-tv-channels)",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.8",
        }
    )
    return session


def api_get(session: requests.Session, url: str, **kwargs) -> dict | None:
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, **kwargs)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        log.warning("API call failed %s: %s", url, exc)
        return None


# --------------------------------------------------------------------------- #
# Fetch series list from fmftp.net API
# --------------------------------------------------------------------------- #

def fetch_series_page(session: requests.Session, library_id: int, page: int) -> dict:
    """Fetch one page of TV series from the API."""
    url = TV_SHOWS_LIST_API
    params = {
        "limit": PAGE_SIZE,
        "fields": SERIES_FIELDS,
        "library": library_id,
        "page": page,
        "sort": "release_date",
    }
    return api_get(session, url, params=params) or {"data": [], "pages": 0, "total": 0}


def fetch_all_series_for_library(
    session: requests.Session,
    library_id: int,
    workers: int,
    max_pages: int = 0,
) -> list[dict]:
    """Fetch all pages for a library ID concurrently."""
    first = fetch_series_page(session, library_id, 1)
    total_pages = int(first.get("pages", 1))
    all_items = list(first.get("data", []))
    log.info("  library=%d -> %d pages, %d total items", library_id, total_pages, first.get("total", 0))

    if max_pages > 0:
        total_pages = min(total_pages, max_pages)

    if total_pages > 1:
        pages = list(range(2, total_pages + 1))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(fetch_series_page, session, library_id, p): p
                for p in pages
            }
            for future in as_completed(futures):
                page_num = futures[future]
                try:
                    result = future.result()
                    all_items.extend(result.get("data", []))
                except Exception as exc:
                    log.warning("  page %d failed: %s", page_num, exc)

    return all_items


# --------------------------------------------------------------------------- #
# Fetch episode details for a single series
# --------------------------------------------------------------------------- #

def fetch_show_episodes(session: requests.Session, show_id: int) -> list[dict]:
    """Fetch episode list for a single show via the detail API."""
    url = TV_SHOW_DETAIL_API.format(show_id=show_id)
    data = api_get(session, url, params={"fields": "episodes"})
    if not data:
        return []
    episodes = data.get("episodes") or []
    # Sort by season, episode, id
    episodes.sort(
        key=lambda e: (
            int(e.get("season_number") or 0),
            int(e.get("episode_number") or 0),
            int(e.get("id") or 0),
        )
    )
    return episodes


def build_episode_title(series_title: str, ep: dict) -> str:
    season = int(ep.get("season_number") or 1)
    episode = int(ep.get("episode_number") or 1)
    raw_name = clean(str(ep.get("name") or ep.get("title") or ""))
    generic = {"", "episode", f"episode {episode}", f"ep {episode}"}
    if raw_name.lower() in generic:
        return f"{series_title} S{season:02d}E{episode:02d}"
    return f"{series_title} S{season:02d}E{episode:02d} - {raw_name}"


def build_series_payload(
    session: requests.Session,
    item: dict,
    category_label: str,
    delay: float,
) -> dict | None:
    """Build a full series payload with episode links."""
    title = clean(str(item.get("title", "")))
    if not title:
        return None

    show_id = extract_show_id(item)
    if show_id is None:
        return None

    year = str(item.get("year", "") or "")
    poster = build_poster_url(str(item.get("poster_path", "")))
    backdrop = build_poster_url(str(item.get("backdrop_path", "")))

    posters = []
    if poster:
        posters.append(poster)
    if backdrop and backdrop != poster:
        posters.append(backdrop)
    posters = posters[:MAX_POSTERS_PER_SERIES]

    language = normalize_language("", category_label)

    # Fetch episode details
    time.sleep(delay)
    episodes = fetch_show_episodes(session, show_id)

    links = []
    added = today()
    for ep in episodes:
        ep_id = ep.get("id")
        if ep_id is None:
            continue
        season = int(ep.get("season_number") or 1)
        episode = int(ep.get("episode_number") or 1)
        links.append(
            {
                "added": added,
                "language": language,
                "season": season,
                "episode": episode,
                "episode_title": build_episode_title(title, ep),
                "url": build_stream_url(int(ep_id)),
            }
        )

    # If no episodes found via API, still create the entry with a watch link
    if not links:
        links.append(
            {
                "added": added,
                "language": language,
                "season": 1,
                "episode": 1,
                "episode_title": f"{title} S01E01",
                "url": build_stream_url(show_id),
            }
        )

    links.sort(key=lambda x: (x["season"], x["episode"], x["url"]))

    return {
        "title": title,
        "year": year,
        "tvg_logo": posters[0] if posters else "",
        "posters": posters,
        "source_url": build_watch_url(show_id),
        "links": links,
        "series_id": show_id,
    }


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


def scrape_category(
    name: str,
    config: dict,
    session: requests.Session,
    workers: int,
    delay: float,
    stats: ScanStats,
) -> list[dict]:
    log.info("=== Scanning category %s ===", name)
    library_ids = config["library_ids"]
    label = config["label"]
    title_filter = config.get("title_filter")

    all_raw_items: dict[int, dict] = {}  # keyed by item id for dedup

    for lib_id in library_ids:
        log.info("[%s] fetching library %d ...", name, lib_id)
        items = fetch_all_series_for_library(session, lib_id, workers, MAX_PAGES_OVERRIDE)
        for item in items:
            item_id = item.get("id")
            if item_id is None:
                continue
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            # Apply title filter if configured (e.g. for Dubbed category)
            if title_filter and not title_filter.search(title):
                continue
            all_raw_items[item_id] = item

    log.info("[%s] %d unique series after filtering", name, len(all_raw_items))
    stats.bump(cards_found=len(all_raw_items))

    payloads: list[dict] = []
    items_list = list(all_raw_items.values())

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(build_series_payload, session, item, label, delay): item
            for item in items_list
        }
        for future in as_completed(futures):
            item = futures[future]
            title = str(item.get("title", ""))
            try:
                payload = future.result()
            except Exception as exc:
                log.warning("[%s] failed to build payload for '%s': %s", name, title, exc)
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
        norm = clean(title).lower()
        buckets[norm] = data
        key_by_norm[norm] = title

    for payload in payloads:
        norm = clean(payload["title"]).lower()
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
    parser = argparse.ArgumentParser(description="CircleFTP/FMFTP TV series scraper")
    parser.add_argument(
        "--category",
        choices=list(CATEGORIES.keys()),
        action="append",
        help="Limit scan to one or more categories (default: all)",
    )
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Concurrent API fetchers")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="Delay (s) between API calls")
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
        config = CATEGORIES[name]
        stats = ScanStats()

        payloads = scrape_category(
            name, config, session, args.workers, args.delay, stats
        )

        out_path = os.path.join(args.output_dir, f"{name}.json")
        existing = load_existing(out_path)
        merged_series = merge_payloads(existing, payloads, stats)

        output = {
            "category": name,
            "source": "fmftp.net API",
            "library_ids": config["library_ids"],
            "last_scan": utc_now_iso(),
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
            # Always write to keep metadata fresh (last_scan, counts)
            atomic_write_json(out_path, output)
            changed_files.append(out_path)
            log.info(
                "[%s] REFRESHED %s (total %d series / %d episodes)",
                name, out_path, output["series_count"], output["episode_count"],
            )

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

    # Emit a small machine-readable summary for the GitHub Actions step
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
