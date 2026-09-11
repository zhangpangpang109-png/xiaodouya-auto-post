import sys
import os
sys.path.insert(0, r"D:\Claude")
from video_utils import cut_concat_overlay

INPUT = r"D:\剪映粗剪\0505熊无敌\0505粗剪.mp4"
OUT = r"C:\Users\TU\Desktop\自动发布"

# Delete broken file if it exists
broken_file = os.path.join(OUT, "横扫千军持续一小时开了死亡减90打架不心疼TU.mp4")
if os.path.exists(broken_file):
    os.remove(broken_file)

print("Starting to cut and concat A3...")
cut_concat_overlay(
    title="横扫千军持续一小时开了死亡减90%打架不心疼TU", 
    segments=[("00:06:07", "00:06:50"), ("00:07:07", "00:07:50")], 
    input_path=INPUT, 
    overlay_text="开横扫千军一小时\n死亡少90%真没想到", 
    output_dir=OUT
)
print("Finished!")
