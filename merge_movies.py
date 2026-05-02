import os
import json

def merge_all_movies():
    # মেইন ফোল্ডারের নাম (আপনার রিপোজিটরি অনুযায়ী 'Movies')
    base_dir = 'Movies'
    all_merged_data = []

    print(f"--- Scanning started in: {base_dir} ---")

    if not os.path.exists(base_dir):
        print(f"❌ Error: '{base_dir}' folder not found!")
        return

    # Movies ফোল্ডারের ভেতর সব সাব-ফোল্ডার স্ক্যান করবে
    for root, dirs, files in os.walk(base_dir):
        for file in files:
            # শুধুমাত্র 'movies.json' নামের ফাইলগুলো খুঁজবে
            if file.lower() == 'movies.json':
                file_path = os.path.join(root, file)
                print(f"📂 Found movie file: {file_path}")
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        if not content:
                            continue
                            
                        data = json.loads(content)
                        
                        # যদি ডাটা লিস্ট [{}, {}] হয়
                        if isinstance(data, list):
                            all_merged_data.extend(data)
                            print(f"   ✅ Added {len(data)} movies")
                        # যদি ডাটা অবজেক্ট {} হয়
                        elif isinstance(data, dict):
                            # যদি অবজেক্টের ভেতরে 'movies' বা অন্য কোনো লিস্ট থাকে
                            found_list = False
                            for key in data:
                                if isinstance(data[key], list):
                                    all_merged_data.extend(data[key])
                                    print(f"   ✅ Added {len(data[key])} movies from '{key}'")
                                    found_list = True
                            
                            # যদি সরাসরি মুভি অবজেক্ট হয়
                            if not found_list:
                                all_merged_data.append(data)
                                print(f"   ✅ Added single movie object")
                                
                except Exception as e:
                    print(f"❌ Error reading {file_path}: {e}")

    # ফাইনাল আউটপুট ফাইল তৈরি
    output_file = 'all_movies.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_merged_data, f, indent=4, ensure_ascii=False)
        
    print(f"--- Summary: Total {len(all_merged_data)} movies merged into {output_file} ---")

if __name__ == "__main__":
    merge_all_movies()
