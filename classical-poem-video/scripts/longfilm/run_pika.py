# -*- coding: utf-8 -*-
"""按 vid_prompts.V 逐条跑 Pika 8 步 HD → SeedVR2 1080p，已有成品就跳过。
python -X utf8 run_pika.py G01 G03 ...   （不给就全跑；长任务用 runlog.py 起）
提示词和帧数来自同目录的 vid_prompts.py（每支片自己的，模板在 presets/vid_prompts.py）。
成品：素材/影片/<id>.mp4（1920×1080，带 H3 的环境声）；中间档在 素材/影片/_work/。
first="@L14b" ＝ 取那条成品的最后一帧当首帧（拆两条的长镜）。
"""
import os, shutil, subprocess, sys, time
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from vid_prompts import V, frames
IMG = os.path.join(PROJ, "素材", "生成", "1080")          # 首帧图：有 1080/ 用它，没有就用 素材/生成/
if not os.path.isdir(IMG):
    IMG = os.path.join(PROJ, "素材", "生成")
OUT = os.path.join(PROJ, "素材", "影片")
WORK = os.path.join(OUT, "_work")
PIKA = os.path.join(HERE, "pika_seedvr2.py")
os.makedirs(WORK, exist_ok=True)
ids = sys.argv[1:] or list(V)
t00 = time.time()
for n, id in enumerate(ids, 1):
    shot, first, last, prompt, _ = V[id]
    dst = os.path.join(OUT, id + ".mp4")
    if os.path.exists(dst):
        print("跳过 %s（已有）" % id); continue
    if first.startswith("@"):
        src = os.path.join(OUT, first[1:] + ".mp4")
        if not os.path.exists(src):
            print("!! %s 要接 %s 的尾帧，但它还没出，跳过" % (id, first[1:])); continue
        img = os.path.join(WORK, id + "_首帧.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-sseof", "-0.1", "-i", src, "-frames:v", "1", "-update", "1", img], check=True)
    else:
        img = os.path.join(IMG, first + ".png")
    pf = os.path.join(WORK, id + "_prompt.txt")
    open(pf, "w", encoding="utf-8").write(prompt)
    cmd = [sys.executable, "-X", "utf8", PIKA, img, pf, WORK, "--wf", "8hd", "--frames", str(frames(id)), "--seed", "42", "--name", id]
    if last:
        cmd += ["--last", os.path.join(IMG, last + ".png")]
    t0 = time.time()
    print("== [%d/%d] %s 鏡%s %d 幀%s" % (n, len(ids), id, shot, frames(id), "（首尾幀）" if last else ""))
    r = subprocess.run(cmd)
    if r.returncode:
        print("!! %s 失败（退出码 %d），跳到下一条" % (id, r.returncode)); continue
    shutil.copy2(os.path.join(WORK, id + "_pika8hd_1080.mp4"), dst)
    print("   %s 完成 %.0f 分钟（累计 %.0f 分钟）" % (id, (time.time() - t0) / 60, (time.time() - t00) / 60))
print("PIKA_BATCH_DONE")
