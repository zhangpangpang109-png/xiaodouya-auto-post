import os
from pathlib import Path

def main():
    folder = Path(r"C:\Users\TU\Desktop\小红书麻将")
    target_text = "进 #全民天天麻将小游戏 🎮玩同款，打到雀神段位领竹叶青茶叶"
    
    video_extensions = {".mp4", ".mov", ".avi", ".mkv"}
    
    count = 0
    for f in folder.iterdir():
        if f.is_file() and f.suffix.lower() in video_extensions:
            old_stem = f.stem
            if target_text in old_stem:
                # 替换掉目标文本，并去除头尾可能多余的空格或 @
                new_stem = old_stem.replace(target_text, "").strip(" @")
                new_name = new_stem + f.suffix
                new_path = folder / new_name
                
                # 如果存在重名则跳过
                if new_path.exists():
                    print(f"Skip: {new_name} already exists.")
                    continue
                    
                f.rename(new_path)
                count += 1
                print(f"Renamed:\n  [Old] {f.name}\n  [New] {new_name}\n")
                
    print(f"Total renamed: {count}")

if __name__ == '__main__':
    main()
