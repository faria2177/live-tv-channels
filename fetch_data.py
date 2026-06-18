import requests
import json
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

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

HEADERS     = {"Accept": "application/json"}
TIMEOUT     = 30
MAX_WORKERS = 5
# ─────────────────────────────────────────


def get_category_map():
    try:
        r = requests.get(f"{ORIGIN}/api/menus", timeout=TIMEOUT, headers=HEADERS)
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


# ─── Fetching ────────────────────────────

def fetch_page(url):
    r = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
    r.raise_for_status()
    return r.json()

def fetch_remaining_pages(url_template, total_pages):
    items = []
    pages = list(range(2, total_pages + 1))
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_page, url_template.format(page=p)): p for p in pages}
        for future in as_completed(futures):
            page_num = futures[future]
            try:
                items.extend(future.result().get("data", []))
            except Exception as e:
                print(f"    [WARN] Page {page_num} failed: {e}")
    return items


# ─── Mapping ─────────────────────────────

def map_movie_item(item, category_name):
    download = item.get("download") or {}
    quality  = download.get("quality", "") if isinstance(download, dict) else ""
    item_id  = item.get("id")
    return {
        "year":     str(item.get("year", "")),
        "tvg_logo": build_poster_url(item.get("poster_path", "")),
        "rating":   float(item.get("online_rating") or 0),
        "genre":    [g.strip() for g in str(item.get("genre", "")).split(",") if g.strip()],
        "links": [{
            "url":        build_stream_url(item_id, "movies"),
            "language":   category_name,
            "quality":    quality,
            "watch_page": build_watch_url(item_id, "MOVIE"),
        }],
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


# ─── Collectors ──────────────────────────

def fetch_movie_category(cat_id, category_name):
    url_tpl = (
        f"{ORIGIN}/api/movies?limit=100"
        f"&fields={MOVIE_FIELDS}&library={cat_id}&page={{page}}&sort=release_date"
    )
    first       = fetch_page(url_tpl.format(page=1))
    total_pages = int(first.get("pages", 1))
    all_raw     = list(first.get("data", []))
    print(f"    Pages: {total_pages}")
    if total_pages > 1:
        all_raw.extend(fetch_remaining_pages(url_tpl, total_pages))

    items_obj = {}
    for item in all_raw:
        title = str(item.get("title", "")).strip()
        if title:
            items_obj[title] = map_movie_item(item, category_name)

    return {
        "type":          "category_collection",
        "source_url":    f"{ORIGIN}/movies?category={cat_id}",
        "category_id":   str(cat_id),
        "category_name": category_name,
        "total_items":   len(items_obj),
        "collected_at":  datetime.utcnow().isoformat() + "Z",
        "items":         items_obj,
    }

def fetch_series_category(cat_id, category_name):
    url_tpl = (
        f"{ORIGIN}/api/tv-shows?limit=100"
        f"&fields={SERIES_FIELDS}&library={cat_id}&page={{page}}&sort=release_date"
    )
    first       = fetch_page(url_tpl.format(page=1))
    total_pages = int(first.get("pages", 1))
    all_raw     = list(first.get("data", []))
    print(f"    Pages: {total_pages}")
    if total_pages > 1:
        all_raw.extend(fetch_remaining_pages(url_tpl, total_pages))

    items_obj = {}
    for item in all_raw:
        title = str(item.get("title", "")).strip()
        if title:
            items_obj[title] = map_series_item(item, category_name)

    return {
        "type":          "series_collection",
        "source_url":    f"{ORIGIN}/tv-shows?category={cat_id}",
        "category_id":   str(cat_id),
        "category_name": category_name,
        "total_items":   len(items_obj),
        "collected_at":  datetime.utcnow().isoformat() + "Z",
        "items":         items_obj,
    }


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
        return new_data, len(new_data.get("items", {})), 0
    existing_items = existing_data.get("items", {})
    new_items      = new_data.get("items", {})
    added = updated = 0
    for title, data in new_items.items():
        if title not in existing_items:
            existing_items[title] = data
            added += 1
        else:
            existing_items[title] = data
            updated += 1
    existing_data["items"]        = existing_items
    existing_data["total_items"]  = len(existing_items)
    existing_data["last_updated"] = new_data["collected_at"]
    return existing_data, added, updated

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─── Report Generator ────────────────────

def generate_report(movie_stats, series_stats, scan_time):
    """Build report.json — read by the dashboard HTML."""
    total_movies  = sum(s["count"] for s in movie_stats)
    total_series  = sum(s["count"] for s in series_stats)

    report = {
        "generated_at":   scan_time,
        "total_movies":   total_movies,
        "total_series":   total_series,
        "grand_total":    total_movies + total_series,
        "movies": {
            "total":      total_movies,
            "categories": movie_stats,
        },
        "series": {
            "total":      total_series,
            "categories": series_stats,
        },
    }
    save_json("report.json", report)
    print(f"\n  report.json saved — {total_movies} movies, {total_series} series")
    return report


# ─── Main ────────────────────────────────

def main():
    category_map = get_category_map()
    print(f"Category map: {len(category_map)} entries\n")

    scan_time    = datetime.utcnow().isoformat() + "Z"
    total_new    = 0
    movie_stats  = []
    series_stats = []

    # ── Movies ──────────────────────────
    print("=" * 50)
    print("  MOVIES")
    print("=" * 50)
    for cat in MOVIE_CATEGORIES:
        cat_id   = cat["id"]
        filename = cat["file"]
        label    = cat["label"]
        cat_name = category_map.get(str(cat_id), label)
        filepath = f"movies/{filename}"

        print(f"\n[{filename}]  category={cat_id}")
        try:
            new_data         = fetch_movie_category(cat_id, cat_name)
            existing         = load_existing(filepath)
            merged, added, _ = merge_data(new_data, existing)
            save_json(filepath, merged)

            count = merged["total_items"]
            print(f"    ✓  Total={count}  New={added}")
            total_new += added
            movie_stats.append({
                "label":       label,
                "category_id": str(cat_id),
                "file":        f"movies/{filename}",
                "count":       count,
                "new":         added,
            })
        except Exception as e:
            print(f"    ✗ FAILED: {e}")
            movie_stats.append({
                "label":       label,
                "category_id": str(cat_id),
                "file":        f"movies/{filename}",
                "count":       0,
                "new":         0,
                "error":       str(e),
            })

    # ── Series ──────────────────────────
    print("\n" + "=" * 50)
    print("  TV SERIES")
    print("=" * 50)
    for cat in SERIES_CATEGORIES:
        cat_id   = cat["id"]
        filename = cat["file"]
        label    = cat["label"]
        cat_name = category_map.get(str(cat_id), label)
        filepath = f"series/{filename}"

        print(f"\n[{filename}]  category={cat_id}")
        try:
            new_data         = fetch_series_category(cat_id, cat_name)
            existing         = load_existing(filepath)
            merged, added, _ = merge_data(new_data, existing)
            save_json(filepath, merged)

            count = merged["total_items"]
            print(f"    ✓  Total={count}  New={added}")
            total_new += added
            series_stats.append({
                "label":       label,
                "category_id": str(cat_id),
                "file":        f"series/{filename}",
                "count":       count,
                "new":         added,
            })
        except Exception as e:
            print(f"    ✗ FAILED: {e}")
            series_stats.append({
                "label":       label,
                "category_id": str(cat_id),
                "file":        f"series/{filename}",
                "count":       0,
                "new":         0,
                "error":       str(e),
            })

    # ── report.json ─────────────────────
    generate_report(movie_stats, series_stats, scan_time)

    # ── scan_summary.json ────────────────
    save_json("scan_summary.json", {
        "last_scan":       scan_time,
        "total_new_items": total_new,
        "movie_categories":  len(movie_stats),
        "series_categories": len(series_stats),
    })

    print(f"\n{'=' * 50}")
    print(f"  DONE — {total_new} new item(s) added")
    print(f"{'=' * 50}")
    return total_new


if __name__ == "__main__":
    main()
