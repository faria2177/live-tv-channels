import os
import re
import json
import time
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

# =========================
# CONFIG
# =========================
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/faria2177/live-tv-channels/main/series"
OUTPUT_DIR = Path("output_series")
TIMEOUT = 20

# আপনার repo-র series folder-এ থাকা ৫টি file name এখানে দিন
JSON_FILES = [
    "English_Tv_Series.json",
    "Hindi_Tv_Series.json",
    "Bangla_Tv_Series.json",
    "Korean_Tv_Series.json",
    "Turkish_Tv_Series.json",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SeriesIndexer/1.0)"
}


# =========================
# HELPERS
# =========================
def fetch_json(url: str):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def fetch_html(url: str):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def normalize_year(value):
    if value is None:
        return ""
    return str(value).strip()


def today_str():
    from datetime import datetime
    return datetime.utcnow().strftime("%Y-%m-%d")


def find_watch_page(obj):
    """
    Nested dict/list থেকে watch_page বের করার চেষ্টা
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.lower() == "watch_page" and isinstance(v, str):
                return v
            found = find_watch_page(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_watch_page(item)
            if found:
                return found
    return None


def find_logo(obj):
    """
    সম্ভাব্য poster/logo key খোঁজা
    """
    candidate_keys = ["tvg_logo", "poster", "image", "thumb", "thumbnail"]
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in candidate_keys and isinstance(v, str):
                return v
        for _, v in obj.items():
            found = find_logo(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_logo(item)
            if found:
                return found
    return ""


def find_year(obj):
    """
    year key বের করার চেষ্টা
    """
    if isinstance(obj, dict):
        if "year" in obj:
            return normalize_year(obj["year"])
        for _, v in obj.items():
            found = find_year(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_year(item)
            if found:
                return found
    return ""


def extract_episode_candidates_from_text(text):
    """
    HTML text থেকে S01E01, Episode 1 ইত্যাদি detect
    """
    found = []

    patterns = [
        r"S(\d{1,2})E(\d{1,3})",
        r"Season\s*(\d{1,2})\s*Episode\s*(\d{1,3})",
        r"Episode\s*(\d{1,3})"
    ]

    # S01E01
    for m in re.finditer(patterns[0], text, flags=re.I):
        season = int(m.group(1))
        episode = int(m.group(2))
        found.append((season, episode, f"S{season:02d}E{episode:02d}"))

    # Season 1 Episode 2
    for m in re.finditer(patterns[1], text, flags=re.I):
        season = int(m.group(1))
        episode = int(m.group(2))
        found.append((season, episode, f"S{season:02d}E{episode:02d}"))

    # Episode 3
    for m in re.finditer(patterns[2], text, flags=re.I):
        episode = int(m.group(1))
        found.append((1, episode, f"S01E{episode:02d}"))

    # unique
    uniq = []
    seen = set()
    for item in found:
        key = (item[0], item[1])
        if key not in seen:
            seen.add(key)
            uniq.append(item)

    uniq.sort(key=lambda x: (x[0], x[1]))
    return uniq


def parse_watch_page(watch_url):
    """
    direct stream URL বের না করে episode count ও episode labels detect করার চেষ্টা।
    """
    result = {
        "watch_page": watch_url,
        "episode_count": 0,
        "episodes": []
    }

    try:
        html = fetch_html(watch_url)
    except Exception as e:
        result["error"] = str(e)
        return result

    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text("\n", strip=True)

    # 1) text-based detect
    episodes = extract_episode_candidates_from_text(page_text)

    # 2) links/buttons থেকেও detect করার চেষ্টা
    clickable_texts = []
    for tag in soup.find_all(["a", "button", "option", "li", "div", "span"]):
        txt = tag.get_text(" ", strip=True)
        if txt:
            clickable_texts.append(txt)

    joined_clickable = "\n".join(clickable_texts)
    more_episodes = extract_episode_candidates_from_text(joined_clickable)

    merged = {}
    for s, e, title in episodes + more_episodes:
        merged[(s, e)] = title

    final_eps = []
    for (season, episode), short_title in sorted(merged.items()):
        final_eps.append({
            "season": season,
            "episode": episode,
            "episode_title": short_title
        })

    # fallback: শুধু Episode 1, 2, 3 detect
    if not final_eps:
        ep_nums = sorted(set(
            int(x) for x in re.findall(r"Episode\s*(\d{1,3})", page_text, flags=re.I)
        ))
        for ep in ep_nums:
            final_eps.append({
                "season": 1,
                "episode": ep,
                "episode_title": f"S01E{ep:02d}"
            })

    result["episodes"] = final_eps
    result["episode_count"] = len(final_eps)
    return result


def build_output_for_file(source_data, default_language="English"):
    """
    Input JSON থেকে target structure বানানো
    """
    output = {}
    added_date = today_str()

    for series_title, payload in source_data.items():
        year = find_year(payload)
        logo = find_logo(payload)
        watch_page = find_watch_page(payload)

        if not watch_page:
            output[series_title] = {
                "year": year,
                "tvg_logo": logo,
                "links": []
            }
            continue

        watch_info = parse_watch_page(watch_page)

        links = []
        for ep in watch_info.get("episodes", []):
            season = ep["season"]
            episode = ep["episode"]
            episode_title = f"{series_title} S{season}E{episode}"

            links.append({
                "added": added_date,
                "language": default_language,
                "season": season,
                "episode": episode,
                "episode_title": episode_title,
                "watch_page": watch_page
            })

        output[series_title] = {
            "year": year,
            "tvg_logo": logo,
            "links": links
        }

        time.sleep(0.7)

    return output


def infer_language_from_filename(filename: str):
    name = filename.lower()
    if "english" in name:
        return "English"
    if "hindi" in name:
        return "Hindi"
    if "bangla" in name:
        return "Bangla"
    if "korean" in name:
        return "Korean"
    if "turkish" in name:
        return "Turkish"
    return "Unknown"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for file_name in JSON_FILES:
        raw_url = f"{GITHUB_RAW_BASE}/{quote(file_name)}"
        print(f"Processing: {raw_url}")

        try:
            data = fetch_json(raw_url)
        except Exception as e:
            print(f"Failed to load {file_name}: {e}")
            continue

        language = infer_language_from_filename(file_name)
        processed = build_output_for_file(data, default_language=language)

        out_path = OUTPUT_DIR / file_name
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(processed, f, ensure_ascii=False, indent=2)

        print(f"Saved: {out_path}")

    print("Done.")


if __name__ == "__main__":
    main()
