import os
import json

def merge_all_movies():
    # ফোল্ডারের নাম 'Movies' (বড় হাতের M)
    base_dir = 'Movies'
    all_merged_data = []

    print(f"--- Scanning started ---")
    
    # বর্তমান ডিরেক্টরি চেক করা
    if not os.path.exists(base_dir):
        # যদি 'Movies' না থাকে তবে 'movies' (ছোট হাতের m) চেক করো
        if os.path.exists('movies'):
            base_dir = 'movies'
        else:
            print(f"❌ Error: '{base_dir}' folder not found!")
            print(f"Root contents: {os.listdir('.')}")
            return

    # Movies ফোল্ডারের ভেতর সব সাব-ফোল্ডার (Bollywood, Hollywood ইত্যাদি) চেক করা
    for root, dirs, files in os.walk(base_dir):
        for file in files:
            # all_movies.json ফাইলটি নিজে স্ক্যান থেকে বাদ যাবে
            if file == 'all_movies.json': continue
            
            file_path = os.path.join(root, file)
            print(f"🔍 Found: {file_path}")
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if not content:
                        print(f"   ⚠️ Skipping {file} (Empty file)")
                        continue
                    
                    # JSON ডাটা লোড করার চেষ্টা করা
                    data = json.loads(content)
                    
                    if isinstance(data, list):
                        all_merged_data.extend(data)
                        print(f"   ✅ Added {len(data)} items from list")
                    elif isinstance(data, dict):
                        # যদি ফাইলটি নিজেই একটি মুভি অবজেক্ট হয়
                        if any(k in data for k in ["name", "title", "url", "stream_url"]):
                            all_merged_data.append(data)
                            print(f"   ✅ Added 1 movie object")
                        else:
                            # ডিকশনারির ভেতরে কোথাও লিস্ট আছে কিনা দেখা
                            for key in data:
                                if isinstance(data[key], list):
                                    all_merged_data.extend(data[key])
                                    print(f"   ✅ Added {len(data[key])} items from '{key}' key")
                
            except json.JSONDecodeError:
                print(f"   ❌ Error: {file} is NOT a valid JSON file.")
            except Exception as e:
                print(f"   ❌ Could not process {file}: {e}")

    # ফাইনাল ফাইল সেভ করা
    output_file = 'all_movies.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_merged_data, f, indent=4, ensure_ascii=False)
        
    print(f"--- Success! Total {len(all_merged_data)} items merged into {output_file} ---")

if __name__ == "__main__":
    merge_all_movies()
