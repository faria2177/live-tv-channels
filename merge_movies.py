import os
import json
import requests
from concurrent.futures import ThreadPoolExecutor

def check_link(item):
    """লিংক অনলাইন আছে কি না যাচাই করার ফাংশন"""
    url = item.get('url') or item.get('stream_url')
    if not url:
        return item, False
    try:
        # ৫ সেকেন্ড টাইমআউট
        response = requests.head(url, timeout=5, allow_redirects=True)
        return item, response.status_code == 200
    except:
        return item, False

def merge_process():
    # ফোল্ডারের নাম Movies বা movies যাই হোক তা খুঁজে বের করবে
    base_dir = 'Movies' if os.path.exists('Movies') else 'movies'
    all_unique_items = []
    seen_urls = set()

    print(f"--- 📂 স্ক্যানিং শুরু হচ্ছে: {base_dir} ---")

    if not os.path.exists(base_dir):
        print(f"❌ এরর: '{base_dir}' ফোল্ডারটি পাওয়া যায়নি!")
        # রুট ডিরেক্টরিতে কী কী আছে তা দেখাবে (ডিবাগিং এর জন্য)
        print(f"Root directories: {os.listdir('.')}")
        return

    # সব সাব-ফোল্ডার স্ক্যান করা
    for root, dirs, files in os.walk(base_dir):
        for file in files:
            # movies.json বা Movies.json যাই হোক পড়বে
            if file.lower() == 'movies.json':
                file_path = os.path.join(root, file)
                print(f"🔍 ফাইল পাওয়া গেছে: {file_path}")
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        if not content:
                            print(f"   ⚠️ ফাইলটি খালি: {file}")
                            continue
                        
                        data = json.loads(content)
                        items = []
                        
                        # ডাটা ফরম্যাট চেক করা (লিস্ট না কি ডিকশনারি)
                        if isinstance(data, list):
                            items = data
                        elif isinstance(data, dict):
                            # যদি ডিকশনারির ভেতরে 'movies' কী থাকে
                            if 'movies' in data and isinstance(data['movies'], list):
                                items = data['movies']
                            else:
                                items = [data] # একটি মাত্র মুভি অবজেক্ট হলে
                        
                        for item in items:
                            url = item.get('url') or item.get('stream_url')
                            if url and url not in seen_urls:
                                seen_urls.add(url)
                                all_unique_items.append(item)
                                
                except Exception as e:
                    print(f"❌ {file_path} পড়তে সমস্যা: {e}")

    print(f"✅ ডুপ্লিকেট ছাড়া মোট মুভি পাওয়া গেছে: {len(all_unique_items)}")

    online_movies = []
    offline_movies = []
    
    if all_unique_items:
        print("--- 🌐 লিঙ্ক অনলাইন চেক শুরু হচ্ছে ---")
        with ThreadPoolExecutor(max_workers=15) as executor:
            results = list(executor.map(check_link, all_unique_items))
            for item, is_online in results:
                if is_online:
                    online_movies.append(item)
                else:
                    offline_movies.append(item)
    else:
        print("⚠️ কোনো মুভি প্রসেস করার জন্য পাওয়া যায়নি!")

    # ফাইল দুটি সেভ করা (ডাটা না থাকলেও ফাইল তৈরি হবে)
    with open('all_movies.json', 'w', encoding='utf-8') as f:
        json.dump(online_movies, f, indent=4, ensure_ascii=False)
        
    with open('offline.json', 'w', encoding='utf-8') as f:
        json.dump(offline_movies, f, indent=4, ensure_ascii=False)

    print(f"🚀 সম্পন্ন! অনলাইন: {len(online_movies)}, অফলাইন: {len(offline_movies)}")

if __name__ == "__main__":
    merge_process()
