import os
import json

def merge_all_movies():
    # আপনার রিপোজিটরিতে থাকা ফোল্ডারগুলোর সঠিক নাম
    target_folders = ['Bollywood', 'Hollywood', 'Private', 'SecretWorld', 'VOD', 'WorldCollection', 'Worldwide']
    all_merged_data = []

    for folder in target_folders:
        if os.path.exists(folder):
            for root, dirs, files in os.walk(folder):
                for file in files:
                    if file.endswith('.json'):
                        file_path = os.path.join(root, file)
                        try:
                            with open(file_path, 'r', encoding='utf-8') as f:
                                data = json.load(f)
                                # ডেটা যদি লিস্ট (Array) হয়
                                if isinstance(data, list):
                                    all_merged_data.extend(data)
                                # ডেটা যদি অবজেক্ট (Dictionary) হয়
                                elif isinstance(data, dict):
                                    for key, value in data.items():
                                        if isinstance(value, list):
                                            all_merged_data.extend(value)
                        except Exception as e:
                            print(f"Error reading {file_path}: {e}")

    # মার্জ করা ডেটা সেভ করার ফাইলের নাম
    output_file = 'all_movies.json'
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_merged_data, f, indent=4, ensure_ascii=False)
        
    print(f"✅ Successfully merged {len(all_merged_data)} movies into {output_file}")

if __name__ == "__main__":
    merge_all_movies()
