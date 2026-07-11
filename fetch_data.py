"""
FMFTP Movie & Series Scanner — v2 (হার্ডেনড ভার্সন)
=====================================================
বর্তমান সমস্যা যা ঠিক করা হয়েছে:
  1. Title-কলিশনের কারণে ডুপ্লিকেট-নাম মুভি/সিরিজ overwrite হয়ে হারিয়ে যাওয়া
  2. Page-fetch fail হলে retry ছাড়াই সেই page-এর সব আইটেম বাদ পড়া
  3. Title খালি থাকলে item পুরোপুরি স্কিপ হওয়া (id fallback ছিল না)
  4. Anti-bot/rate-limit-এর কারণে silent request drop (User-Agent/headers দুর্বল ছিল)
  5. "pages" মেটাডেটার উপর অন্ধ বিশ্বাস — mismatch হলে ভ্যালিডেট করার উপায় ছিল না
  6. একাধিক quality/download link থাকলে শুধু একটাই কালেক্ট হওয়া

আউটপুট JSON স্ট্রাকচার আগের মতোই রাখা হয়েছে (items/title-keyed) — শুধু
কলিশন হলে key-তে বাড়তি সাফিক্স যোগ হয়, ভেতরের ডেটা একই ফরম্যাটে থাকে।
"""

import json
import os
import random
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ─────────────────────────────────────────
ORIGIN = "https://fmftp.net"

MOVIE_FIELDS = (
    "id,title,genre,year,views,download,"
    "online_rating,release_date,poster_path,backdrop_path"
)
SERIES_FIELDS = (
    "id,title,genre,year,online_rating,release_date,poster_path,backdrop_path"
)

MOVIE_CATEGORIES = [
    {"id": 1,  "file": "Bollywood.json",     "label": "Bollywood"},
    {"id": 2,  "file": "Hollywood.json",     "label": "Hollywood"},
    {"id": 3,  "file": "Animation.json",     "label": "Animation"},
    {"id": 4,  "file": "Korean.json",        "label": "Korean Movies"},
    {"id": 5,  "file": "Hindi_dubbed.json",  "label": "Hindi Dubbed"},
    {"id": 6,  "file": "Horror.json",        "label": "Horror"},
    {"id": 7,  "file": "Indian_Bangla.json", "label": "Indian Bangla"},
    {"id": 8,  "file": "Tamil.json",         "label": "Tamil"},
    {"id": 14, "file": "foreign.json",       "label": "Foreign"},
]

SERIES_CATEGORIES = [
    {"id": 9,  "file": "English_Tv_Series.json",  "label": "English TV Series"},
    {"id": 10, "file": "Indian_Tv_Series.json",   "label": "Indian TV Series"},
    {"id": 11, "file": "Korean_Tv_Series.json",   "label": "Korean TV Series"},
    {"id": 12, "file": "Bangla_Tv_Series.json",   "label": "Bangla TV Series"},
    {"id": 13, "file": "Turkish_Tv_Series.json",  "label": "Turkish TV Series"},
]

TIMEOUT       = 30
MAX_WORKERS   = 4          # আগে ছিল ৫; একটু কম রাখা হয়েছে রেট-লিমিট এড়াতে
PAGE_RETRIES  = 4          # প্রতিটা page-এ কতবার retry হবে
RETRY_BACKOFF = 1.6        # exponential backoff base (seconds)
REQUEST_DELAY = (0.15, 0.4)  # প্রতিটা request-এর আগে ছোট্ট random delay (সেকেন্ড)

HEADERS = {
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,bn;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": f"{ORIGIN}/",
    "Origin":  ORIGIN,
}
# ─────────────────────────────────────────


def make_session():
    """Retry-adapter সহ একটা requests.Session তৈরি করে — connection-level
    error/৫xx/৪২৯-এর জন্য নিজে থেকেই backoff দিয়ে retry করবে।"""
    session = requests.Session()
    retry = Retry(
        total=PAGE_RETRIES,
        backoff_factor=RETRY_BACKOFF,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=MAX_WORKERS * 2)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(HEADERS)
    return session


SESSION = make_session()


def get_category_map():
    try:
        r = SESSION.get(f"{ORIGIN}/api/menus", timeout=TIMEOUT)
        r.raise_for_status()
        menus = r.json()
        cmap = {}
        for section in ("movie", "tv"):
            for item in menus.get("categories", {}).get(section, []):
                cmap[str(item["id"])] = item.get("name", "")
        return cmap
    except Exception as e:
        print(f"  [WARN] Could not load category map: {e}")
        return {}


def build_poster_url(path):
    if not path:
        return ""
    path = str(path).strip()
    sep = "" if path.startswith("/") else "/"
    return f"{ORIGIN}/content-images/movies/posters{sep}{path}"


def build_watch_url(item_id, content_type="MOVIE"):
    return f"{ORIGIN}/watch?type={content_type}&id={item_id}"


def build_stream_url(item_id, content_type="movies"):
    return f"{ORIGIN}/api/stream/video/stream?type={content_type}&id={item_id}"


# ─── Fetching (retry + jitter সহ) ────────

def fetch_page(url, page_label=""):
    """একটা page fetch করে — HTTPAdapter-এর Retry ছাড়াও, JSON-parse বা
    অপ্রত্যাশিত error হলে নিজে ম্যানুয়ালি আরও কয়েকবার চেষ্টা করে।"""
    last_err = None
    for attempt in range(1, PAGE_RETRIES + 1):
        try:
            time.sleep(random.uniform(*REQUEST_DELAY))
            r = SESSION.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
            return data
        except Exception as e:
            last_err = e
            wait = RETRY_BACKOFF * attempt + random.uniform(0, 0.5)
            print(f"    [RETRY {attempt}/{PAGE_RETRIES}] {page_label} failed "
                  f"({e}) — retrying in {wait:.1f}s")
            time.sleep(wait)
    raise RuntimeError(f"{page_label} permanently failed after "
                        f"{PAGE_RETRIES} attempts: {last_err}")


def fetch_remaining_pages(url_template, total_pages):
    """২ থেকে total_pages পর্যন্ত সব page fetch করে। কোনো page শেষ পর্যন্ত
    fail করলেও সেটা আলাদা তালিকায় রাখা হয় যাতে caller জানতে পারে কতগুলো
    page miss হয়েছে (আগের কোডে এটা silent ছিল)।"""
    items = []
    failed_pages = []
    pages = list(range(2, total_pages + 1))
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_page, url_template.format(page=p), f"page {p}"): p
            for p in pages
        }
        for future in as_completed(futures):
            page_num = futures[future]
            try:
                items.extend(future.result().get("data", []))
            except Exception as e:
                print(f"    [FAIL] Page {page_num} permanently failed: {e}")
                failed_pages.append(page_num)
    return items, failed_pages


# ─── Mapping ─────────────────────────────

def extract_download_links(item, item_id, category_name):
    """`download` field dict বা list দুই ফরম্যাটেই থাকতে পারে — একাধিক
    quality থাকলে সবগুলোকেই links[]-এ রাখা হয় (আগের কোড শুধু একটাই নিত)।"""
    download = item.get("download")
    entries = []
    if isinstance(download, list):
        entries = [d for d in download if isinstance(d, dict)]
    elif isinstance(download, dict):
        entries = [download]

    if not entries:
        return [{
            "url":        build_stream_url(item_id, "movies"),
            "language":   category_name,
            "quality":    "",
            "watch_page": build_watch_url(item_id, "MOVIE"),
        }]

    links = []
    for d in entries:
        links.append({
            "url":        d.get("url") or build_stream_url(item_id, "movies"),
            "language":   category_name,
            "quality":    d.get("quality", ""),
            "watch_page": build_watch_url(item_id, "MOVIE"),
        })
    return links


def map_movie_item(item, category_name):
    item_id = item.get("id")
    return {
        "year":     str(item.get("year", "")),
        "tvg_logo": build_poster_url(item.get("poster_path", "")),
        "rating":   float(item.get("online_rating") or 0),
        "genre":    [g.strip() for g in str(item.get("genre", "")).split(",") if g.strip()],
        "links":    extract_download_links(item, item_id, category_name),
    }


def map_series_item(item, category_name):
    item_id = item.get("id")
    return {
        "year":       str(item.get("year", "")),
        "tvg_logo":   build_poster_url(item.get("poster_path", "")),
        "rating":     float(item.get("online_rating") or 0),
        "genre":      [g.strip() for g in str(item.get("genre", "")).split(",") if g.strip()],
        "language":   category_name,
        "watch_page": build_watch_url(item_id, "SERIES"),
        "stream_url": build_stream_url(item_id, "tv-shows"),
    }


def safe_key(title, item_id, used_keys):
    """Title-key ব্যবহার করা হয় (JSON স্ট্রাকচার অপরিবর্তিত রাখতে), কিন্তু
    ডুপ্লিকেট title হলে id/counter সাফিক্স যোগ করে যাতে কোনো এন্ট্রি
    overwrite হয়ে হারিয়ে না যায়।"""
    title = title.strip() if title else ""
    if not title:
        title = f"Untitled-{item_id}" if item_id is not None else "Untitled"
    key = title
    if key in used_keys:
        key = f"{title} [{item_id}]" if item_id is not None else f"{title} #{len(used_keys)+1}"
        # তাও যদি কলিশন হয় (বিরল), আরও ইউনিক করে দাও
        n = 2
        base_key = key
        while key in used_keys:
            key = f"{base_key} ({n})"
            n += 1
    used_keys.add(key)
    return key


# ─── Collectors ──────────────────────────

def fetch_category_generic(cat_id, category_name, endpoint, fields, mapper):
    url_tpl = (
        f"{ORIGIN}/api/{endpoint}?limit=100"
        f"&fields={fields}&library={cat_id}&page={{page}}&sort=release_date"
    )
    first = fetch_page(url_tpl.format(page=1), "page 1")
    total_pages   = int(first.get("pages", 1) or 1)
    reported_total = first.get("total") or first.get("total_items")
    all_raw = list(first.get("data", []))

    print(f"    Pages: {total_pages}"
          + (f"  (API reports total={reported_total})" if reported_total else ""))

    failed_pages = []
    if total_pages > 1:
        more, failed_pages = fetch_remaining_pages(url_tpl, total_pages)
        all_raw.extend(more)

    # ── একবার failed pages retry করার চেষ্টা (transient error হলে সেকেন্ড পাসে ঠিক হয়ে যেতে পারে) ──
    if failed_pages:
        print(f"    [INFO] Retrying {len(failed_pages)} failed page(s) once more...")
        still_failed = []
        for p in failed_pages:
            try:
                data = fetch_page(url_tpl.format(page=p), f"retry-page {p}")
                all_raw.extend(data.get("data", []))
            except Exception as e:
                still_failed.append(p)
        if still_failed:
            print(f"    [WARN] Pages permanently unrecoverable: {still_failed}")

    # ── Dedupe-safe key দিয়ে items বানানো ──
    items_obj = {}
    used_keys = set()
    skipped_no_id = 0
    for item in all_raw:
        item_id = item.get("id")
        title = str(item.get("title", "")).strip()
        if not title and item_id is None:
            skipped_no_id += 1
            continue
        key = safe_key(title, item_id, used_keys)
        items_obj[key] = mapper(item, category_name)

    # ── ভ্যালিডেশন: API-র রিপোর্ট করা total vs আসলে যা fetch হলো ──
    collected = len(items_obj)
    if reported_total and collected < int(reported_total):
        gap = int(reported_total) - collected
        print(f"    [WARN] Expected ~{reported_total} items but collected "
              f"{collected} (gap: {gap}). দেখুন failed_pages/duplicate ids.")
    if skipped_no_id:
        print(f"    [WARN] Skipped {skipped_no_id} item(s) with no title and no id")

    return {
        "type":           "category_collection" if endpoint == "movies" else "series_collection",
        "source_url":     f"{ORIGIN}/{'movies' if endpoint=='movies' else 'tv-shows'}?category={cat_id}",
        "category_id":    str(cat_id),
        "category_name":  category_name,
        "total_items":    collected,
        "expected_total": int(reported_total) if reported_total else None,
        "failed_pages":   failed_pages if failed_pages else None,
        "collected_at":   datetime.utcnow().isoformat() + "Z",
        "items":          items_obj,
    }


def fetch_movie_category(cat_id, category_name):
    return fetch_category_generic(cat_id, category_name, "movies", MOVIE_FIELDS, map_movie_item)


def fetch_series_category(cat_id, category_name):
    return fetch_category_generic(cat_id, category_name, "tv-shows", SERIES_FIELDS, map_series_item)


# ─── Merge ───────────────────────────────

def load_existing(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def merge_data(new_data, existing_data):
    if not existing_data:
        # প্রথমবার হলে ডায়াগনস্টিক ফিল্ড বাদে বাকি সব রাখো
        return new_data, len(new_data.get("items", {})), 0

    existing_items = existing_data.get("items", {})
    new_items      = new_data.get("items", {})
    added = updated = 0
    for key, data in new_items.items():
        if key not in existing_items:
            existing_items[key] = data
            added += 1
        else:
            existing_items[key] = data
            updated += 1

    existing_data["items"]          = existing_items
    existing_data["total_items"]    = len(existing_items)
    existing_data["expected_total"] = new_data.get("expected_total")
    existing_data["failed_pages"]   = new_data.get("failed_pages")
    existing_data["last_updated"]   = new_data["collected_at"]
    return existing_data, added, updated


def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─── Report Generator ────────────────────

def generate_report(movie_stats, series_stats, scan_time):
    total_movies = sum(s["count"] for s in movie_stats)
    total_series = sum(s["count"] for s in series_stats)

    report = {
        "generated_at": scan_time,
        "total_movies": total_movies,
        "total_series": total_series,
        "grand_total":  total_movies + total_series,
        "movies": {"total": total_movies, "categories": movie_stats},
        "series": {"total": total_series, "categories": series_stats},
    }
    save_json("report.json", report)
    print(f"\n  report.json saved — {total_movies} movies, {total_series} series")
    return report


# ─── Main ────────────────────────────────

def process_categories(categories, kind, fetch_fn, category_map, stats_list):
    for cat in categories:
        cat_id   = cat["id"]
        filename = cat["file"]
        label    = cat["label"]
        cat_name = category_map.get(str(cat_id), label)
        filepath = f"{kind}/{filename}"

        print(f"\n[{filename}]  category={cat_id}")
        try:
            new_data         = fetch_fn(cat_id, cat_name)
            existing         = load_existing(filepath)
            merged, added, _ = merge_data(new_data, existing)
            save_json(filepath, merged)

            count = merged["total_items"]
            gap_note = ""
            if merged.get("expected_total") and count < merged["expected_total"]:
                gap_note = f"  ⚠ expected~{merged['expected_total']}"
            print(f"    ✓  Total={count}  New={added}{gap_note}")
            stats_list.append({
                "label":       label,
                "category_id": str(cat_id),
                "file":        filepath,
                "count":       count,
                "new":         added,
            })
        except Exception as e:
            print(f"    ✗ FAILED: {e}")
            stats_list.append({
                "label":       label,
                "category_id": str(cat_id),
                "file":        filepath,
                "count":       0,
                "new":         0,
                "error":       str(e),
            })


def main():
    category_map = get_category_map()
    print(f"Category map: {len(category_map)} entries\n")

    scan_time    = datetime.utcnow().isoformat() + "Z"
    movie_stats  = []
    series_stats = []

    print("=" * 50)
    print("  MOVIES")
    print("=" * 50)
    process_categories(MOVIE_CATEGORIES, "movies", fetch_movie_category, category_map, movie_stats)

    print("\n" + "=" * 50)
    print("  TV SERIES")
    print("=" * 50)
    process_categories(SERIES_CATEGORIES, "series", fetch_series_category, category_map, series_stats)

    total_new = sum(s.get("new", 0) for s in movie_stats + series_stats)

    generate_report(movie_stats, series_stats, scan_time)

    save_json("scan_summary.json", {
        "last_scan":         scan_time,
        "total_new_items":   total_new,
        "movie_categories":  len(movie_stats),
        "series_categories": len(series_stats),
    })

    print(f"\n{'=' * 50}")
    print(f"  DONE — {total_new} new item(s) added")
    print(f"{'=' * 50}")
    return total_new


if __name__ == "__main__":
    main()
