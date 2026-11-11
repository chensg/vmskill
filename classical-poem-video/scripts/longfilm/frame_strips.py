# -*- coding: utf-8 -*-
"""影片抽帧条：python -X utf8 抽帧.py G01 G03 ...（不给就抽 素材/影片/*.mp4 全部）
每条均匀抽 6 帧（首帧、尾帧都在内），拼成一行 → 素材/影片/_strips/<id>.jpg；再把所有行叠成 _strips/总表.jpg
"""
import os, subprocess, sys, json
sys.stdout.reconfigure(encoding="utf-8")
from PIL import Image, ImageDraw, ImageFont
HERE = os.path.dirname(os.path.abspath(__file__))
VID = os.path.join(os.path.dirname(HERE), "素材", "影片")
OUT = os.path.join(VID, "_strips"); os.makedirs(OUT, exist_ok=True)
ids = sys.argv[1:] or sorted(f[:-4] for f in os.listdir(VID) if f.endswith(".mp4"))
N, W, H = 6, 480, 270
font = ImageFont.truetype(r"C:\Windows\Fonts\msjh.ttc", 22)
rows = []
for id in ids:
    p = os.path.join(VID, id + ".mp4")
    dur = float(json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", p],
                                          capture_output=True, text=True).stdout)["format"]["duration"])
    row = Image.new("RGB", (N * W, H + 30), (20, 20, 20)); d = ImageDraw.Draw(row)
    for i in range(N):
        t = min(dur - 0.08, dur * i / (N - 1))
        f = os.path.join(OUT, "_tmp.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "%.3f" % t, "-i", p, "-frames:v", "1", "-q:v", "3", f], check=True)
        row.paste(Image.open(f).convert("RGB").resize((W, H), Image.LANCZOS), (i * W, 0))
        d.text((i * W + 6, H + 3), "%s  %.1fs" % (id, t), fill=(230, 220, 200), font=font)
    row.save(os.path.join(OUT, id + ".jpg"), quality=85); rows.append(row)
    print(id, "%.1fs" % dur)
os.remove(os.path.join(OUT, "_tmp.jpg"))
if len(rows) > 1:
    big = Image.new("RGB", (N * W, sum(r.height for r in rows)))
    y = 0
    for r in rows:
        big.paste(r, (0, y)); y += r.height
    big.save(os.path.join(OUT, "总表.jpg"), quality=80)
print("STRIPS_DONE")
