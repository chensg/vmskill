# -*- coding: utf-8 -*-
"""把 素材/影片_720/*.mp4（G*、卡通片 S*）逐条用 FlashVSR+ Base tc2 放大 → 素材/影片/<同名>.mp4（1920×1080，带原片环境声；已有跳过）。
    python -X utf8 fvsr_batch.py [id…]      （长任务用 runlog.py 起）
FlashVSR+ 宽高要 128 的倍数：先出 2048×1152，再 lanczos 缩到 1920×1080（16:9 同比例，不拉伸）。
1280×704 不是 16:9：先居中裁成 1252×704 再进模型。11-19 用户定这一支改用 FlashVSR+ tc2。
"""
import os, subprocess, sys, time
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FV = r"D:\AI\FlashVSR_Plus"
PY = os.path.join(FV, ".venv", "Scripts", "python.exe")
IN = os.path.join(PROJ, "素材", "影片_720")
OUT = os.path.join(PROJ, "素材", "影片")
WORK = os.path.join(OUT, "_work")
os.makedirs(WORK, exist_ok=True)
ids = sys.argv[1:] or sorted(f[:-4] for f in os.listdir(IN) if f.endswith(".mp4"))   # 前缀不限：写实片 G、卡通片 S
t00 = time.time()
for n, id in enumerate(ids, 1):
    dst = os.path.join(OUT, id + ".mp4")
    if os.path.exists(dst):
        print("跳过 %s（已有）" % id); continue
    src = os.path.join(IN, id + ".mp4")
    print("== [%d/%d] %s" % (n, len(ids), id))
    t0 = time.time()
    try:
        inp = os.path.join(WORK, id + "_169.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-an", "-vf", "crop=1252:704,setsar=1",
                        "-c:v", "libx264", "-crf", "10", "-preset", "fast", "-pix_fmt", "yuv420p", inp], check=True)
        raw = os.path.join(WORK, id + "_fv.mp4")
        subprocess.run([PY, "-m", "inference.run_stream", "--input", inp, "--mode", "base", "--output", raw,
                        "--height", "1152", "--width", "2048", "--attn-kernel", "triton_block_sparse",
                        "--temporal-compression", "2"], cwd=FV, check=True,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1"))
        tmp = os.path.join(WORK, id + "_1080.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", raw, "-i", src, "-map", "0:v", "-map", "1:a?",
                        "-vf", "scale=1920:1080:flags=lanczos,setsar=1", "-shortest",
                        "-c:v", "libx264", "-crf", "14", "-preset", "slow", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                        tmp], check=True)
        os.replace(tmp, dst)
        for f in (inp, raw):
            os.remove(f)
    except Exception as e:
        print("!! %s 失败：%s，跳到下一条" % (id, str(e)[:300])); continue
    print("   %s 完成 %.1f 分钟（累计 %.0f 分钟）" % (id, (time.time() - t0) / 60, (time.time() - t00) / 60))
print("FVSR_BATCH_DONE")
