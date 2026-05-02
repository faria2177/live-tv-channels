import os
import json

def merge_all_movies():
    # ফোল্ডারগুলো যেহেতু এখন 'Movies' এর ভেতর, তাই আমরা সেখানে খুঁজবো
    base_dir = 'Movies'
    all_merged_data = []

    if not os.path.exists(base_dir):
        print(f"Error: '{base_dir}' folder not found!")
        return

    # Movies ফোল্ডার এবং এর ভেতরের সব সাব-ফোল্ডার ও ফাইল স্ক্যান করবে
    for root, dirs, files in os.walk(base_dir):
        for file in files:
            if file.endswith('.json'):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                        # ডেটা যদি সরাসরি লিস্ট [{}, {}] হয়
                        if isinstance(data, list):
                            all_merged_data.extend(data)
                        # ডেটা যদি ডিকশনারি বা অবজেক্ট হয় যার ভেতরে লিস্ট আছে
                        elif isinstance(data, dict):
                            for key in data:
                                if isinstance(data[key], list):
                                    all_merged_data.extend(data[key])
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")

    output_file = 'all_movies.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_merged_data, f, indent=4, ensure_ascii=False)
        
    print(f"✅ Successfully merged {len(all_merged_data)} items into {output_file}")

if __name__ == "__main__":
    merge_all_movies()
