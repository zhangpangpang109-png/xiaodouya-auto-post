import random
import sys
from pathlib import Path

VIDEO_DIR = Path(r"C:\Users\TU\Desktop\小红书麻将")
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

TITLES = [
    "谁懂啊！搓麻真的是日常快乐天花板",
    "无聊续命神器，闲来一局快乐拉满",
    "当代年轻人专属解压休闲小乐趣",
    "平凡日常里，藏着搓麻的小欢喜",
    "不用凑局，随时随地开启快乐时光",
    "一入麻将深似海，快乐根本停不下来",
    "生活琐碎太多，搓麻治愈所有不开心",
    "碎片时间好去处，轻松开局超上头",
    "宅家无聊？一局麻将治愈所有慵懒",
    "快乐其实很简单，指尖搓麻就圆满",
    "休闲氛围感拉满，麻将真的太好耍",
    "抛开所有烦恼，沉浸式享受搓麻时光",
    "打麻将的快乐，真的没办法形容",
    "日常消遣小美好，闲来无事搓两把",
    "没有复杂规则，新手也能快乐开局",
    "治愈所有坏心情，麻将自带幸福感",
    "闲暇时刻小美好，一局皆可解忧",
]

INVALID_CHARS = '<>:"/\\|?*'

def sanitize(name: str) -> str:
    for ch in INVALID_CHARS:
        name = name.replace(ch, "_")
    return name

def main():
    videos = [p for p in VIDEO_DIR.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    if len(videos) < len(TITLES):
        print(f"视频文件数量不足：{len(videos)} 个，需要 {len(TITLES)} 个。")
        return

    random.shuffle(TITLES)
    assignments = list(zip(videos, TITLES))

    for video_path, title in assignments:
        new_stem = sanitize(title)
        new_name = new_stem + video_path.suffix.lower()
        new_path = video_path.parent / new_name
        if new_path.exists() and new_path != video_path:
            new_path = new_path.with_name(new_stem + "_" + video_path.stem[:4] + video_path.suffix.lower())
        video_path.rename(new_path)
        print(f"  {video_path.name!r:50s} -> {new_name!r}")

    print(f"\n重命名完成，共处理 {len(assignments)} 个文件。")

if __name__ == "__main__":
    main()
