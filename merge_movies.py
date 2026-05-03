import os
import json
import requests
from concurrent.futures import ThreadPoolExecutor

def check_link(item):
    """লিঙ্ক চেক করার ফাংশন"""
    url = item.get('url') or item.get('stream_url')
    if not url:
        return item, False
    try:
        # ৫ সেকেন্ডের মধ্যে রেসপন্স না দিলে অফলাইন ধরবে
        response = requests.head(url, timeout=5, allow_redirects=True)
        return item, response.status_code == 200
    except:
        return item, False

def merge_process():
    # আপনার স্ক্রিনশট অনুযায়ী মেইন ফোল্ডার 'Movies'
    base_dir = 'Movies'
    all_unique_items = []
    seen_urls = set()

    print(f"--- 📂 স্ক্যানিং শুরু হচ্ছে: {base_dir} ---")

    if not os.path.exists(base_dir):
        print(f"❌ এরর: '{base_dir}' ফোল্ডারটি পাওয়া যায়নি!")
        return

    # সব সাব-ফোল্ডার থেকে movies.json ফাইল খোঁজা
    for root, dirs, files in os.walk(base_dir):
        for file in files:
            # ফাইলের নাম movies.json বা Movies.json যাই হোক না কেন তা পড়বে
            if file.lower() == 'movies.json':
                file_path = os.path.join(root, file)
                print(f"🔍 ফাইল পাওয়া গেছে: {file_path}")
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        items = data if isinstance(data, list) else [data]
                        for item in items:
                            url = item.get('url') or item.get('stream_url')
                            if url and url not in seen_urls:
                                seen_urls.add(url)
                                all_unique_items.append(item)
                except Exception as e:
                    print(f"❌ {file_path} পড়তে সমস্যা: {e}")

    if not all_unique_items:
        print("⚠️ কোনো মুভি ডাটা পাওয়া যায়নি! ফাইলগুলো ঠিকঠাক JSON কিনা চেক করুন।")
        return

    print(f"✅ ডুপ্লিকেট ছাড়া মোট মুভি পাওয়া গেছে: {len(all_unique_items)}")
    print("--- 🌐 লিঙ্ক অনলাইন আছে কি না যাচাই করা হচ্ছে ---")

    online_movies = []
    offline_movies = []
    
    # ১৫টি থ্রেড দিয়ে দ্রুত চেক করা হবে
    with ThreadPoolExecutor(max_workers=15) as executor:
        results = list(executor.map(check_link, all_unique_items))
        for item, is_online in results:
            if is_online:
                online_movies.append(item)
            else:
                offline_movies.append(item)

    # ফাইলগুলো সেভ করা
    with open('all_movies.json', 'w', encoding='utf-8') as f:
        json.dump(online_movies, f, indent=4, ensure_ascii=False)
        
    with open('offline.json', 'w', encoding='utf-8') as f:
        json.dump(offline_movies, f, indent=4, ensure_ascii=False)

    print(f"🚀 সম্পন্ন! অনলাইন: {len(online_movies)}, অফলাইন: {len(offline_movies)}")

if __name__ == "__main__":
    merge_process()
