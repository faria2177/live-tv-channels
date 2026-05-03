import os
import json
import requests
from concurrent.futures import ThreadPoolExecutor

def check_link(item):
    """লিংকটি অনলাইন আছে কি না তা চেক করার ফাংশন"""
    url = item.get('url') or item.get('stream_url')
    if not url:
        return None
    try:
        # শুধুমাত্র হেডার চেক করবে যাতে সময় কম লাগে
        response = requests.head(url, timeout=5, allow_redirects=True)
        if response.status_code == 200:
            return item
    except:
        return None
    return None

def merge_and_clean_movies():
    base_dir = 'Movies'
    all_merged_data = []
    seen_urls = set()

    if not os.path.exists(base_dir):
        print(f"❌ Error: '{base_dir}' folder not found!")
        return

    print("--- 📂 ডাটা কালেকশন এবং ডুপ্লিকেট রিমুভ শুরু হচ্ছে ---")

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
                                all_merged_data.append(item)
                except Exception as e:
                    print(f"❌ Error reading {file_path}: {e}")

    print(f"✅ ডুপ্লিকেট রিমুভ করার পর মোট লিংক: {len(all_merged_data)}")
    print("--- 🌐 অফলাইন স্ট্রিম চেক করা হচ্ছে (এটি কিছুটা সময় নিতে পারে) ---")

    # দ্রুত চেক করার জন্য মাল্টি-থ্রেডিং ব্যবহার করা হয়েছে
    final_online_data = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(check_link, all_merged_data))
        final_online_data = [item for item in results if item is not None]

    output_file = 'all_movies.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(final_online_data, f, indent=4, ensure_ascii=False)
        
    print(f"--- 🚀 সম্পন্ন: {len(final_online_data)} টি অনলাইন মুভি পাওয়া গেছে ---")

if __name__ == "__main__":
    merge_and_clean_movies()
