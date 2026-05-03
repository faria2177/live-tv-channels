import os
import json
import requests
from concurrent.futures import ThreadPoolExecutor

def check_link(item):
    url = item.get('url') or item.get('stream_url')
    if not url: return item, False
    try:
        response = requests.head(url, timeout=5, allow_redirects=True)
        return item, response.status_code == 200
    except:
        return item, False

def merge_process():
    base_dir = 'Movies'
    all_unique_items = []
    seen_urls = set()

    if not os.path.exists(base_dir):
        print(f"❌ Error: '{base_dir}' folder not found!")
        return

    for root, dirs, files in os.walk(base_dir):
        for file in files:
            if file.lower() == 'movies.json':
                file_path = os.path.join(root, file)
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
                    print(f"❌ Error reading {file_path}: {e}")

    online_movies = []
    offline_movies = []
    
    with ThreadPoolExecutor(max_workers=15) as executor:
        results = list(executor.map(check_link, all_unique_items))
        for item, is_online in results:
            if is_online: online_movies.append(item)
            else: offline_movies.append(item)

    # সচল এবং অচল ফাইলগুলো নিশ্চিতভাবে সেভ করা
    with open('all_movies.json', 'w', encoding='utf-8') as f:
        json.dump(online_movies, f, indent=4, ensure_ascii=False)
        
    with open('offline.json', 'w', encoding='utf-8') as f:
        json.dump(offline_movies, f, indent=4, ensure_ascii=False)

    print(f"Done! Online: {len(online_movies)}, Offline: {len(offline_movies)}")

if __name__ == "__main__":
    merge_process()
