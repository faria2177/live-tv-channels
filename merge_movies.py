import os
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# =============================================
# কনফিগারেশন
# =============================================
BASE_DIRS = ['Movies', 'movies', 'Movie', 'movie']  # সব সম্ভাব্য ফোল্ডার নাম
VALID_JSON_NAMES = ['movies.json', 'Movies.json', 'data.json', 'movie.json']
TIMEOUT = 8
MAX_WORKERS = 20
OUTPUT_ONLINE = 'all_movies.json'
OUTPUT_OFFLINE = 'offline.json'

# =============================================
# স্ট্রিম URL চেক করা (HEAD + GET fallback)
# =============================================
def check_link(item):
    url = item.get('url') or item.get('stream_url') or item.get('link') or item.get('src')
    if not url or not url.startswith('http'):
        return item, False, "no_url"

    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; StreamChecker/1.0)',
        'Accept': '*/*',
    }

    try:
        # প্রথমে HEAD চেষ্টা
        resp = requests.head(url, timeout=TIMEOUT, headers=headers, allow_redirects=True)
        if resp.status_code < 400:
            return item, True, resp.status_code

        # HEAD কাজ না করলে GET দিয়ে চেক (শুধু প্রথম ১ বাইট)
        resp = requests.get(
            url, timeout=TIMEOUT, headers={**headers, 'Range': 'bytes=0-0'},
            stream=True, allow_redirects=True
        )
        if resp.status_code in (200, 206):
            return item, True, resp.status_code
        return item, False, resp.status_code

    except requests.exceptions.SSLError:
        # SSL error হলে HTTP দিয়ে retry
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
# JSON ফাইল থেকে আইটেম বের করা
# =============================================
def extract_items(data):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        # সাধারণ কী নামগুলো চেক করা
        for key in ['movies', 'items', 'data', 'channels', 'list', 'results']:
            if key in data and isinstance(data[key], list):
                return data[key]
        # যদি নিজেই একটা মুভি অবজেক্ট হয়
        if any(k in data for k in ['url', 'stream_url', 'link', 'title', 'name']):
            return [data]

    return []

# =============================================
# মূল প্রসেস
# =============================================
def merge_process():
    # সঠিক বেস ডিরেক্টরি খোঁজা
    base_dir = None
    for d in BASE_DIRS:
        if os.path.exists(d) and os.path.isdir(d):
            base_dir = d
            break

    if not base_dir:
        print(f"❌ কোনো Movies ফোল্ডার পাওয়া যায়নি!")
        print(f"📁 বর্তমান ডিরেক্টরিতে যা আছে: {sorted(os.listdir('.'))}")
        # খালি ফাইল তৈরি করা যাতে workflow ভাঙে না
        for f in [OUTPUT_ONLINE, OUTPUT_OFFLINE]:
            with open(f, 'w', encoding='utf-8') as fp:
                json.dump([], fp)
        return

    print(f"📂 স্ক্যান শুরু: '{base_dir}' ফোল্ডার")
    print(f"{'='*50}")

    all_items = []
    seen_urls = set()
    scanned_files = 0

    # সব সাবফোল্ডার ও ফাইল স্ক্যান
    for root, dirs, files in os.walk(base_dir):
        # লুকানো ফোল্ডার স্কিপ
        dirs[:] = [d for d in dirs if not d.startswith('.')]

        for file in files:
            if file.lower() not in [n.lower() for n in VALID_JSON_NAMES]:
                continue

            file_path = os.path.join(root, file)
            scanned_files += 1
            print(f"  🔍 [{scanned_files}] পড়ছি: {file_path}")

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()

                if not content:
                    print(f"      ⚠️  ফাইলটি খালি — স্কিপ করা হলো")
                    continue

                # BOM থাকলে সরানো
                if content.startswith('\ufeff'):
                    content = content[1:]

                try:
                    data = json.loads(content)
                except json.JSONDecodeError as e:
                    print(f"      ❌ JSON পার্স ত্রুটি: {e}")
                    continue

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

                print(f"      ✅ {new_count} নতুন আইটেম যোগ হলো (ফাইলে মোট: {len(items)})")

            except Exception as e:
                print(f"      ❌ পড়তে সমস্যা: {e}")

    print(f"\n{'='*50}")
    print(f"📊 মোট অনন্য আইটেম: {len(all_items)} (ডুপ্লিকেট বাদে)")

    if not all_items:
        print("\n⚠️  কোনো আইটেম পাওয়া যায়নি!")
        print(f"   সম্ভাব্য কারণ:")
        print(f"   - JSON ফাইলের নাম {VALID_JSON_NAMES} এর মধ্যে নেই")
        print(f"   - JSON ফাইলে url/stream_url ফিল্ড নেই")
        print(f"   Movies ফোল্ডারের স্ট্রাকচার:")
        for root, dirs, files in os.walk(base_dir):
            level = root.replace(base_dir, '').count(os.sep)
            indent = '  ' * level
            print(f"   {indent}📁 {os.path.basename(root)}/")
            for f in files:
                print(f"   {indent}  📄 {f}")

        for fname in [OUTPUT_ONLINE, OUTPUT_OFFLINE]:
            with open(fname, 'w', encoding='utf-8') as fp:
                json.dump([], fp)
        return

    # =============================================
    # লিঙ্ক চেক করা (Parallel)
    # =============================================
    print(f"\n🌐 লিঙ্ক অনলাইন চেক করছি ({len(all_items)}টি)...")
    print(f"   (সময় লাগতে পারে — {MAX_WORKERS}টি থ্রেড ব্যবহার করছি)")

    online_movies = []
    offline_movies = []
    errors = {}
    checked = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(check_link, item): item for item in all_items}
        for future in as_completed(futures):
            checked += 1
            if checked % 10 == 0 or checked == len(all_items):
                print(f"   ⏳ চেক করা হয়েছে: {checked}/{len(all_items)}")
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

    # =============================================
    # ফলাফল সেভ করা
    # =============================================
    with open(OUTPUT_ONLINE, 'w', encoding='utf-8') as f:
        json.dump(online_movies, f, indent=2, ensure_ascii=False)

    with open(OUTPUT_OFFLINE, 'w', encoding='utf-8') as f:
        json.dump(offline_movies, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*50}")
    print(f"🎉 সম্পন্ন!")
    print(f"   ✅ অনলাইন  : {len(online_movies)} টি → {OUTPUT_ONLINE}")
    print(f"   ❌ অফলাইন  : {len(offline_movies)} টি → {OUTPUT_OFFLINE}")
    if errors:
        print(f"   📋 ত্রুটির ধরন:")
        for err, count in sorted(errors.items(), key=lambda x: -x[1]):
            print(f"      {err}: {count}টি")

if __name__ == "__main__":
    merge_process()
