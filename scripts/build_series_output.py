import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

REPO_OWNER = "faria2177"
REPO_NAME = "live-tv-channels"
BRANCH = "main"
SERIES_DIR = "series"

GITHUB_CONTENTS_API = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{SERIES_DIR}"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{BRANCH}/{SERIES_DIR}"

OUTPUT_DIR = Path("generated_series")
TIMEOUT = 25

HEADERS = {
    "User-Agent": "series-json-builder/1.0"
}


def fetch_json(url: str):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def fetch_text(url: str):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def get_series_json_files():
    data = fetch_json(GITHUB_CONTENTS_API)
    files = []
    for item in data:
        if item.get("type") == "file" and item.get("name", "").endswith("_Tv_Series.json"):
            files.append(item["name"])
    return sorted(files)


def get_raw_file_url(filename: str):
    return f"{RAW_BASE}/{quote(filename)}"


def today_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def normalize_language(filename: str, source_obj: dict | None = None):
    if source_obj:
        category_name = str(source_obj.get("category_name", "")).strip()
        if category_name:
            if category_name.lower() == "indian tv series":
                return "Indian"
            return category_name.replace(" tv series", "").replace(" Tv Series", "").strip()

    lower = filename.lower()
    if "english" in lower:
        return "English"
    if "bangla" in lower:
        return "Bangla"
    if "indian" in lower:
        return "Indian"
    if "korean" in lower:
        return "Korean"
    if "turkish" in lower:
        return "Turkish"
    return "Unknown"


def extract_episode_candidates(text: str):
    found = {}

    # Pattern: S01E02
    for m in re.finditer(r"\bS(\d{1,2})E(\d{1,3})\b", text, flags=re.I):
        season = int(m.group(1))
        episode = int(m.group(2))
        found[(season, episode)] = f"S{season:02d}E{episode:02d}"

    # Pattern: Season 1 Episode 2
    for m in re.finditer(r"\bSeason\s*(\d{1,2})\s*Episode\s*(\d{1,3})\b", text, flags=re.I):
        season = int(m.group(1))
        episode = int(m.group(2))
        found[(season, episode)] = f"S{season:02d}E{episode:02d}"

    # Fallback: Episode 1 / EP 1 / E01
    if not found:
        episode_nums = set()

        for m in re.finditer(r"\bEpisode\s*(\d{1,3})\b", text, flags=re.I):
            episode_nums.add(int(m.group(1)))

        for m in re.finditer(r"\bEP\s*(\d{1,3})\b", text, flags=re.I):
            episode_nums.add(int(m.group(1)))

        for m in re.finditer(r"\bE(\d{1,3})\b", text, flags=re.I):
            episode_nums.add(int(m.group(1)))

        for ep in sorted(episode_nums):
            found[(1, ep)] = f"S01E{ep:02d}"

    items = []
    for (season, episode), short_code in sorted(found.items()):
        items.append({
            "season": season,
            "episode": episode,
            "short_code": short_code
        })

    return items


def extract_text_blocks(soup: BeautifulSoup):
    blocks = []

    page_text = soup.get_text("\n", strip=True)
    if page_text:
        blocks.append(page_text)

    for tag in soup.find_all(["a", "button", "li", "option", "span", "div", "script"]):
        txt = tag.get_text(" ", strip=True)
        if txt and len(txt) >= 2:
            blocks.append(txt)

    return "\n".join(blocks)


def scan_watch_page_for_episodes(watch_page: str):
    """
    watch_page থেকে episode count/labels detect করার চেষ্টা করে।
    direct video link extract করে না।
    """
    result = {
        "watch_page": watch_page,
        "episodes": [],
        "episode_count": 0,
        "status": "not_scanned"
    }

    if not watch_page:
        result["status"] = "missing_watch_page"
        return result

    try:
        html = fetch_text(watch_page)
    except Exception as e:
        result["status"] = f"fetch_failed: {e}"
        return result

    soup = BeautifulSoup(html, "html.parser")
    text_blob = extract_text_blocks(soup)
    episodes = extract_episode_candidates(text_blob)

    result["episodes"] = episodes
    result["episode_count"] = len(episodes)
    result["status"] = "ok" if episodes else "no_episode_detected"
    return result


def build_links(series_title: str, watch_page: str, language: str, added_date: str):
    scan_result = scan_watch_page_for_episodes(watch_page)
    links = []

    for ep in scan_result["episodes"]:
        season = ep["season"]
        episode = ep["episode"]
        links.append({
            "added": added_date,
            "language": language,
            "season": season,
            "episode": episode,
            "episode_title": f"{series_title} S{season}E{episode}",
            "watch_page": watch_page
        })

    return links, scan_result


def transform_source_file(source_data: dict, filename: str):
    output = {}
    items = source_data.get("items", {})
    language = normalize_language(filename, source_data)
    added_date = today_utc()

    for series_title, meta in items.items():
        year = str(meta.get("year", "")).strip()
        tvg_logo = meta.get("tvg_logo", "") or ""
        watch_page = meta.get("watch_page", "") or ""

        links, scan_result = build_links(
            series_title=series_title,
            watch_page=watch_page,
            language=language,
            added_date=added_date
        )

        output[series_title] = {
            "year": year,
            "tvg_logo": tvg_logo,
            "watch_page": watch_page,
            "episode_count": scan_result["episode_count"],
            "links": links
        }

        # polite delay
        time.sleep(0.4)

    return output


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    files = get_series_json_files()
    print("Found files:", files)

    for filename in files:
        raw_url = get_raw_file_url(filename)
        print(f"Processing: {filename}")

        try:
            source_data = fetch_json(raw_url)
            transformed = transform_source_file(source_data, filename)
        except Exception as e:
            print(f"Failed: {filename} -> {e}")
            continue

        out_path = OUTPUT_DIR / filename
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(transformed, f, ensure_ascii=False, indent=2)

        print(f"Saved: {out_path}")

    print("Done.")


if __name__ == "__main__":
    main()
