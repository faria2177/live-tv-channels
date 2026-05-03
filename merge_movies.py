import os
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# =============================================
# কনফিগারেশন
# =============================================
BASE_DIRS = ['Movies', 'movies', 'Movie', 'movie']
VALID_JSON_NAMES = ['movies.json', 'Movies.json', 'data.json', 'movie.json']
TIMEOUT = 8
MAX_WORKERS = 20
OUTPUT_ONLINE = 'all_movies.json'
OUTPUT_OFFLINE = 'offline.json'

# =============================================
# ডিবাগ — ফোল্ডার স্ট্রাকচার দেখানো
# =============================================
def debug_scan():
    print("\n" + "="*60)
    print("🔎 DEBUG: রুট ডিরেক্টরিতে যা আছে:")
    for item in sorted(os.listdir('.')):
        size = ''
        if os.path.isfile(item):
            size = f"  ({os.path.getsize(item)} bytes)"
        kind = '📁' if os.path.isdir(item) else '📄'
        print(f"  {kind} {item}{size}")

    print("\n🔎 DEBUG: Movies ফোল্ডারের সম্পূর্ণ স্ট্রাকচার:")
    found_any = False
    for base in BASE_DIRS:
        if not os.path.exists(base):
            continue
        found_any = True
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            level = root.replace(base, '').count(os.sep)
            indent = '  ' * level
            print(f"{indent}📁 {os.path.basename(root)}/")
            for f in files:
                fpath = os.path.join(root, f)
                size = os.path.getsize(fpath)
                print(f"{indent}  📄 {f}  ({size} bytes)")
                if f.endswith('.json') and size > 0:
                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='replace') as fp:
                            preview = fp.read(150).replace('\n', ' ')
                        print(f"{indent}     👀 Preview: {preview!r}")
                    except Exception as e:
                        print(f"{indent}     ❌ পড়া যায়নি: {e}")
    if not found_any:
        print("  ❌ কোনো Movies ফোল্ডার পাওয়া যায়নি!")
    print("="*60 + "\n")

# =============================================
# স্ট্রিম URL চেক (HEAD + GET fallback)
# =============================================
def check_link(item):
    url = (item.get('url') or item.get('stream_url') or
           item.get('link') or item.get('src') or '').strip()
    if not url or not url.startswith('http'):
        return item, False, "no_url"

    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; StreamChecker/1.0)',
        'Accept': '*/*',
    }

    try:
        resp = requests.head(url, timeout=TIMEOUT, headers=headers, allow_redirects=True)
        if resp.status_code < 400:
            return item, True, resp.status_code

        resp = requests.get(
            url, timeout=TIMEOUT,
            headers={**headers, 'Range': 'bytes=0-0'},
            stream=True, allow_redirects=True
        )
        if resp.status_code in (200, 206):
            return item, True, resp.status_code
        return item, False, resp.status_code

    except requests.exceptions.SSLError:
        try:
            http_url = url.replace('https://', 'http://', 1)
            resp = requests.head(http_url, timeout=TIMEOUT, headers=headers,
                                 allow_redirects=True, verify=False)
            if resp.status_code < 400:
                return item, True, f"ssl_fallback_{resp.status_code}"
        except:
            pass
        return item, False, "ssl_error"

    except requests.exceptions.ConnectionError:
        return item, False, "connection_error"
    except requests.exceptions.Timeout:
        return item, False, "timeout"
    except Exception as e:
        return item, False, str(e)[:50]

# =============================================
# JSON থেকে আইটেম বের করা
# =============================================
def extract_items(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ['movies', 'items', 'data', 'channels', 'list', 'results']:
            if key in data and isinstance(data[key], list):
                return data[key]
        if any(k in data for k in ['url', 'stream_url', 'link', 'title', 'name']):
            return [data]
    return []

# =============================================
# মূল প্রসেস
# =============================================
def merge_process():
    # প্রথমেই ডিবাগ স্ক্যান চালানো
    debug_scan()

    # বেস ডিরেক্টরি খোঁজা
    base_dir = None
    for d in BASE_DIRS:
        if os.path.exists(d) and os.path.isdir(d):
            base_dir = d
            break

    if not base_dir:
        print("❌ কোনো Movies ফোল্ডার পাওয়া যায়নি!")
        for f in [OUTPUT_ONLINE, OUTPUT_OFFLINE]:
            with open(f, 'w', encoding='utf-8') as fp:
                json.dump([], fp)
        return

    print(f"📂 স্ক্যান শুরু: '{base_dir}' ফোল্ডার")
    print("="*50)

    all_items = []
    seen_urls = set()
    scanned_files = 0

    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for file in files:
            if file.lower() not in [n.lower() for n in VALID_JSON_NAMES]:
                print(f"  ⏭️  স্কিপ (নাম মিলছে না): {os.path.join(root, file)}")
                continue

            file_path = os.path.join(root, file)
            scanned_files += 1
            print(f"  🔍 [{scanned_files}] পড়ছি: {file_path}")

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()

                if not content:
                    print(f"      ⚠️  ফাইলটি খালি — স্কিপ")
                    continue

                if content.startswith('\ufeff'):
                    content = content[1:]

                data = json.loads(content)
                items = extract_items(data)
                new_count = 0

                for item in items:
                    if not isinstance(item, dict):
                        continue
                    url = (item.get('url') or item.get('stream_url') or
                           item.get('link') or item.get('src') or '').strip()
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_items.append(item)
                        new_count += 1

                print(f"      ✅ {new_count} নতুন আইটেম (ফাইলে মোট: {len(items)})")

            except json.JSONDecodeError as e:
                print(f"      ❌ JSON ত্রুটি: {e}")
            except Exception as e:
                print(f"      ❌ সমস্যা: {e}")

    print(f"\n{'='*50}")
    print(f"📊 মোট অনন্য আইটেম: {len(all_items)}")

    if not all_items:
        print("\n⚠️  কোনো আইটেম পাওয়া যায়নি!")
        print(f"   ➡️  JSON ফাইলের নাম এগুলোর মধ্যে একটি হতে হবে: {VALID_JSON_NAMES}")
        print(f"   ➡️  JSON এ 'url' বা 'stream_url' ফিল্ড থাকতে হবে")
        for fname in [OUTPUT_ONLINE, OUTPUT_OFFLINE]:
            with open(fname, 'w', encoding='utf-8') as fp:
                json.dump([], fp)
        return

    # লিঙ্ক চেক
    print(f"\n🌐 লিঙ্ক চেক করছি ({len(all_items)}টি) — {MAX_WORKERS} থ্রেড...")
    online_movies = []
    offline_movies = []
    errors = {}
    checked = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(check_link, item): item for item in all_items}
        for future in as_completed(futures):
            checked += 1
            if checked % 10 == 0 or checked == len(all_items):
                print(f"   ⏳ {checked}/{len(all_items)} চেক হয়েছে")
            try:
                item, is_online, status = future.result()
                if is_online:
                    online_movies.append(item)
                else:
                    offline_movies.append(item)
                    err_key = str(status)
                    errors[err_key] = errors.get(err_key, 0) + 1
            except Exception as e:
                offline_movies.append(futures[future])

    # সেভ করা
    with open(OUTPUT_ONLINE, 'w', encoding='utf-8') as f:
        json.dump(online_movies, f, indent=2, ensure_ascii=False)

    with open(OUTPUT_OFFLINE, 'w', encoding='utf-8') as f:
        json.dump(offline_movies, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*50}")
    print(f"🎉 সম্পন্ন!")
    print(f"   ✅ অনলাইন : {len(online_movies)} → {OUTPUT_ONLINE}")
    print(f"   ❌ অফলাইন : {len(offline_movies)} → {OUTPUT_OFFLINE}")
    if errors:
        print(f"   📋 ত্রুটির ধরন:")
        for err, count in sorted(errors.items(), key=lambda x: -x[1]):
            print(f"      {err}: {count}টি")

if __name__ == "__main__":
    merge_process()
