import os
import random
from pathlib import Path

def main():
    folder = Path(r"C:\Users\TU\Desktop\小红书麻将")
    
    titles = [
        "平凡日子里的小快乐，搓麻治愈所有不开心✨进 #全民天天麻将小游戏 🎮玩同款，打到雀神段位领竹叶青茶叶",
        "闲暇时光别虚度，一局麻将快乐十足🀄️进 #全民天天麻将小游戏 🎮玩同款，打到雀神段位领竹叶青茶叶",
        "当代年轻人解压方式，线上搓麻真的上瘾🥰进 #全民天天麻将小游戏 🎮玩同款，打到雀神段位领竹叶青茶叶",
        "无需线下凑局，随时随地轻松开局☀️进 #全民天天麻将小游戏 🎮玩同款，打到雀神段位领竹叶青茶叶",
        "生活琐碎太烦躁，麻将一玩全忘掉😌进 #全民天天麻将小游戏 🎮玩同款，打到雀神段位领竹叶青茶叶",
        "快乐不分时刻，指尖搓麻皆是欢喜💫进 #全民天天麻将小游戏 🎮玩同款，打到雀神段位领竹叶青茶叶",
        "慵懒宅家日常，麻将相伴惬意十足☕️进 #全民天天麻将小游戏 🎮玩同款，打到雀神段位领竹叶青茶叶",
        "治愈所有无聊时刻，休闲麻将刚刚好🎈进 #全民天天麻将小游戏 🎮玩同款，打到雀神段位领竹叶青茶叶",
        "没有复杂门槛，新手也能快乐搓麻🥳进 #全民天天麻将小游戏 🎮玩同款，打到雀神段位领竹叶青茶叶",
        "忙完工作放松一下，麻将真的超解乏🌟进 #全民天天麻将小游戏 🎮玩同款，打到雀神段位领竹叶青茶叶",
        "藏在日常里的小美好，一局麻将来解忧🌸进 #全民天天麻将小游戏 🎮玩同款，打到雀神段位领竹叶青茶叶",
        "碎片时间利用起来，轻松搓麻收获快乐🎊进 #全民天天麻将小游戏 🎮玩同款，打到雀神段位领竹叶青茶叶",
        "心态放松玩麻将，快乐自然不请自来🍃进 #全民天天麻将小游戏 🎮玩同款，打到雀神段位领竹叶青茶叶 @",
        "日常休闲小爱好，搓麻快乐很纯粹💖进 #全民天天麻将小游戏 🎮玩同款，打到雀神段位领竹叶青茶叶"
    ]
    
    # 过滤系统保留字符，防止文件重命名报错 (如: < > : " / \ | ? *)
    def sanitize_filename(name):
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '')
        return name

    titles = [sanitize_filename(t.strip()) for t in titles]
    random.shuffle(titles)
    
    video_extensions = {".mp4", ".mov", ".avi", ".mkv"}
    files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in video_extensions]
    
    if len(files) != len(titles):
        print(f"Warning: Number of files ({len(files)}) does not match number of titles ({len(titles)}).")
        
    num_to_rename = min(len(files), len(titles))
    files_to_rename = files[:num_to_rename]
    
    for i, f in enumerate(files_to_rename):
        new_name = titles[i] + f.suffix
        new_path = folder / new_name
        
        # 处理可能的同名冲突
        if new_path.exists():
            print(f"Skip: {new_name} already exists.")
            continue
            
        f.rename(new_path)
        print(f"Renamed:\n  [Old] {f.name}\n  [New] {new_name}\n")

if __name__ == '__main__':
    main()
