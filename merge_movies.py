import os
import json

def merge_all_movies():
    # ফোল্ডারের নাম 'Movies' না 'movies' সেটি চেক করে নেবে
    base_dir = 'Movies' if os.path.exists('Movies') else 'movies'
    all_merged_data = []

    print(f"--- Scanning started in: {base_dir} ---")

    if not os.path.exists(base_dir):
        print(f"❌ Error: '{base_dir}' folder not found!")
        return

    # Movies ফোল্ডারের সব সাব-ফোল্ডার চেক করবে
    for root, dirs, files in os.walk(base_dir):
        for file in files:
            file_path = os.path.join(root, file)
            
            # সব ফাইল চেক করবে (all_movies.json বাদে)
            if file == 'all_movies.json': continue
            
            print(f"📄 Checking file: {file}")
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if not content: continue
                    
                    # JSON হিসেবে পড়ার চেষ্টা করবে
                    try:
                        data = json.loads(content)
                        
                        # ১. যদি ডাটা একটি লিস্ট হয় [{}, {}]
                        if isinstance(data, list):
                            all_merged_data.extend(data)
                            print(f"   ✅ Added list of {len(data)} items")
                            
                        # ২. যদি ডাটা একটি অবজেক্ট হয় {}
                        elif isinstance(data, dict):
                            # যদি এটি নিজেই একটি মুভি হয়
                            if any(k in data for k in ["name", "title", "url", "stream_url"]):
                                all_merged_data.append(data)
                                print(f"   ✅ Added single movie object")
                            else:
                                # অবজেক্টের ভেতরে কোনো লিস্ট আছে কিনা দেখবে
                                for key in data:
                                    if isinstance(data[key], list):
                                        all_merged_data.extend(data[key])
                                        print(f"   ✅ Added {len(data[key])} items from key: {key}")
                    
                    except json.JSONDecodeError:
                        # যদি ফাইলটি JSON না হয়, তবে এটি M3U হতে পারে (আপনার অ্যাপের জন্য জরুরি)
                        if file.endswith('.m3u') or '#EXTM3U' in content:
                            print(f"   ℹ️ Processing as M3U file...")
                            # এখানে চাইলে M3U to JSON কনভার্টার যোগ করা যাবে
                        continue
                        
            except Exception as e:
                print(f"❌ Error reading {file}: {e}")

    # ফাইনাল ফাইল সেভ করা
    output_file = 'all_movies.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_merged_data, f, indent=4, ensure_ascii=False)
        
    print(f"--- Summary: Total {len(all_merged_data)} movies merged into {output_file} ---")

if __name__ == "__main__":
    merge_all_movies()
