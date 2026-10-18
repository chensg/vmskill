# -*- coding: utf-8 -*-
"""档案照片 ×2 超分（OpenCV dnn_superres · EDSR，纯 CPU）。

    python upscale.py <源目录> <输出目录> [模型.pb] [文件名 ...]
    python upscale.py ../素材/照片 ../素材/照片_x2                     # 模型默认 ../../EDSR_x2.pb（片库根）

海军历史中心、国会图书馆的线上图常只有 600~740px 宽，贴台纸（fit="plate"）铺 1080 高要放大 1.5 倍以上。
EDSR ×2 之后再缩到画框里，比直接 lanczos 放大干净（字、缆绳、铆钉不糊成一片）。

==== 2026-10-18《海底四十小時》实测（Ryzen 9 5900X，12 核 24 线程，无 GPU）====
  740×565 一张 **38 秒**，76 张单进程约 50 分钟。
  **别开多进程**：OpenCV 的 DNN 自己就吃满全部线程，3 路并行时每张 280~360 秒，总吞吐反而慢 3 倍。
  FSRCNN_x2.pb 快十几倍但细节差，只在赶时间时用。

==== 两个坑 ====
  - **cv2.imread / imwrite 不认中文路径**：读回 None、不报错，到 upsample 才炸（assert inp.total()）。
    一律 np.fromfile + imdecode / imencode + tofile。
  - 输出用 PNG：再存 JPG 会把超分出来的细节压掉一层。
"""
import glob
import json
import os
import sys
import time

import cv2
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main():
    if len(sys.argv) < 3:
        print(__doc__); return 1
    src, dst = sys.argv[1], sys.argv[2]
    rest = sys.argv[3:]
    here = os.path.dirname(os.path.abspath(__file__))
    model = rest.pop(0) if rest and rest[0].lower().endswith(".pb") else os.path.join(here, "..", "..", "EDSR_x2.pb")
    if not os.path.exists(model):
        print("!!! 找不到模型 %s（EDSR_x2.pb / FSRCNN_x2.pb，OpenCV dnn_superres 的预训练模型）" % model); return 1
    only = set(rest)
    os.makedirs(dst, exist_ok=True)
    sr = cv2.dnn_superres.DnnSuperResImpl_create()
    sr.readModel(model)
    sr.setModel("edsr" if "EDSR" in os.path.basename(model).upper() else "fsrcnn", 2)
    files = [f for f in sorted(glob.glob(os.path.join(src, "*.jpg")) + glob.glob(os.path.join(src, "*.png")))
             if not only or os.path.basename(f) in only]
    log, t0 = [], time.time()
    for f in files:
        out = os.path.join(dst, os.path.splitext(os.path.basename(f))[0] + ".png")
        if os.path.exists(out):
            continue
        img = cv2.imdecode(np.fromfile(f, np.uint8), cv2.IMREAD_COLOR)    # 中文路径
        if img is None:
            print("   读不出：%s" % f); continue
        t = time.time()
        up = sr.upsample(img)
        cv2.imencode(".png", up)[1].tofile(out)
        log.append(dict(f=os.path.basename(f), w=img.shape[1], h=img.shape[0], s=round(time.time() - t, 1)))
        print("%-24s %4dx%-4d → %4dx%-4d  %.1fs" % (log[-1]["f"], img.shape[1], img.shape[0], up.shape[1], up.shape[0], log[-1]["s"]), flush=True)
    json.dump(dict(total_s=round(time.time() - t0, 1), n=len(log), items=log),
              open(os.path.join(dst, "_timing.json"), "w"), indent=1)
    print("共 %d 张，%.0f 秒" % (len(log), time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
