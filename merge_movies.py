import os
import json

def merge_all_movies():
    base_dir = 'Movies'
    all_merged_data = []

    print(f"--- Scanning started in: {os.getcwd()} ---")

    if not os.path.exists(base_dir):
        print(f"❌ Error: '{base_dir}' folder not found! Directories present: {os.listdir('.')}")
        return

    # Movies ফোল্ডারের ভেতর কী কী আছে তা প্রিন্ট করবে
    for root, dirs, files in os.walk(base_dir):
        print(f"📂 Checking folder: {root}")
        for file in files:
            print(f"📄 Found file: {file}")
            
            # শুধুমাত্র .json ফাইল এবং যা 'all_movies.json' নয়
            if file.endswith('.json') and file != 'all_movies.json':
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        if not content:
                            print(f"⚠️ Warning: {file} is empty!")
                            continue
                            
                        data = json.loads(content)
                        
                        # ডেটা লিস্ট হলে সরাসরি যোগ করবে
                        if isinstance(data, list):
                            all_merged_data.extend(data)
                            print(f"✅ Added {len(data)} items from {file}")
                        # ডেটা অবজেক্ট হলে তার ভেতরের লিস্টগুলো খুঁজবে
                        elif isinstance(data, dict):
                            found_list = False
                            for key in data:
                                if isinstance(data[key], list):
                                    all_merged_data.extend(data[key])
                                    print(f"✅ Added {len(data[key])} items from key '{key}' in {file}")
                                    found_list = True
                            if not found_list:
                                print(f"❓ No lists found inside dictionary in {file}")
                except Exception as e:
                    print(f"❌ Error reading {file_path}: {e}")

    output_file = 'all_movies.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_merged_data, f, indent=4, ensure_ascii=False)
        
    print(f"--- Summary: Total {len(all_merged_data)} items merged into {output_file} ---")

if __name__ == "__main__":
    merge_all_movies()
