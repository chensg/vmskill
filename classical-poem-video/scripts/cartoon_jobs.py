# -*- coding: utf-8 -*-
"""卡通画风出图管线（本机 Qwen 两个模型，全 Apache-2.0）。配置是同目录的 cartoon_config.py（模板在 presets/）。

    python -X utf8 cartoon_jobs.py refs  [KEY ...]   角色定妆：Qwen-Image-2512 50 步竖版 → 素材/生成/角色/<KEY>.png
    python -X utf8 cartoon_jobs.py shots [镜号 ...]   各镜：有人物＝Qwen-Image-Edit-2511 拿定妆图当参考（Lightning 4 步）；
                                                     空镜（T2I_SHOTS）＝Qwen-Image-2512 纯文生图 50 步 → 素材/生成/原图/S<n>.png
    python -X utf8 cartoon_jobs.py up    [镜号 ...]   SeedVR2 静帧放大 → 素材/生成/S<n>.png（film.py 的 STILL_PAT）
    python -X utf8 cartoon_jobs.py sheet [refs]       拼联络表 ../_联络表_镜头_<k>.jpg（或定妆表），出完必须逐张看

已有的一律跳过：要重出哪张，先把它挪进 原图_废/ 再跑。为什么这样分工见 references/cartoon.md。
"""
import os, shutil, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
import qwen_edit as qe
import cartoon_config as C
cg = qe.cg

PROJ = getattr(C, "PROJ", None) or os.path.dirname(HERE)
GEN = os.path.join(PROJ, "素材", "生成")
REFD, RAWD = os.path.join(GEN, "角色"), os.path.join(GEN, "原图")
NOTEXT = getattr(C, "NOTEXT", " No text, no letters, no writing anywhere.")
SHOT_SIZE = getattr(C, "SHOT_SIZE", (1920, 1088))      # 编辑模型：16 的倍数
T2I_SIZE = getattr(C, "T2I_SIZE", (1664, 928))         # Qwen-2512 原生 16:9 档
REF_SIZE = getattr(C, "REF_SIZE", (1088, 1920))        # 定妆竖版全身
UP_TO = getattr(C, "UP_TO", "3840x2176")


def ref_path(k):
    """参考图：REF_FILE 里登记的外部图（比如关联 Short 的图）优先；键为空＝只借画风，用无人的 STYLE_SCENE 定妆图。"""
    return C.REF_FILE.get(k) or os.path.join(REFD, (k or "STYLE_SCENE") + ".png")


def start():
    cg.set_proj(PROJ)
    if not cg.alive():
        cg.cmd_start()
        for _ in range(90):
            if cg.alive():
                return
            time.sleep(5)
        sys.exit("!!! ComfyUI 没起来")


def do_refs(keys):
    os.makedirs(REFD, exist_ok=True)
    start()
    cg.ew.prompt = lambda n: C.REF_STYLE + C.REFS[n] + NOTEXT
    wf0 = cg.load_wf("qwen2512")
    for k in keys or C.REFS:
        out = os.path.join(REFD, k + ".png")
        if not os.path.exists(out):
            print("==> 定妆", k)
            cg._gen_image(k, 50, getattr(C, "REF_SEED", {}).get(k, 21), REF_SIZE[0], REF_SIZE[1], out, wf0, "定妆_" + k)


def do_shots(ns):
    os.makedirs(RAWD, exist_ok=True)
    start()
    ns = ns or list(C.SHOTS)
    t2i = [n for n in ns if n in C.T2I_SHOTS and not os.path.exists(os.path.join(RAWD, "S%s.png" % n))]
    if t2i:
        cg.ew.prompt = lambda n: C.T2I_SCENE + C.SHOTS[n][1] + NOTEXT
        wf0 = cg.load_wf("qwen2512")
        for n in t2i:
            cg._gen_image(n, 50, C.T2I_SEED.get(n, 21), T2I_SIZE[0], T2I_SIZE[1], os.path.join(RAWD, "S%s.png" % n), wf0, "S" + n)
    for n in ns:
        k, p = C.SHOTS[n]
        out = os.path.join(RAWD, "S%s.png" % n)
        if os.path.exists(out) or n in C.T2I_SHOTS:
            continue
        refs = [ref_path(x) for x in k.split("+")] if k else [ref_path("")]   # "A+B"：两人同框各给一张定妆图（最多 3 张）
        miss = [r for r in refs if not os.path.exists(r)]
        if miss:
            print("!! S%s 缺参考图 %s，先跑 refs" % (n, miss)); continue
        style_only = "" if k else " Use the reference image only for the art style (line work and colors), not for its place or content."
        wf = qe.build("gen", C.EDIT_STYLE + p + style_only + NOTEXT, refs[:3], True, SHOT_SIZE,
                      getattr(C, "SHOT_SEED", {}).get(n, 21))
        sec, peak = cg.run("qwen_edit", wf, out, "S" + n)
        cg.log(dict(kind="image_edit", model="Qwen-Image-Edit-2511 int8 + Lightning4", license="Apache-2.0", shot=n,
                    ref="+".join(os.path.basename(r) for r in refs), prompt=p, out=os.path.relpath(out, PROJ), sec=round(sec)))
        print("存 S%s（%.0f 秒）" % (n, sec))


def do_up(ns):
    todo = [n for n in (ns or C.SHOTS) if os.path.exists(os.path.join(RAWD, "S%s.png" % n))
            and not os.path.exists(os.path.join(GEN, "S%s.png" % n))]
    if not todo:
        print("没有要放大的"); return
    start()
    cg.cmd_upscale_image([os.path.join(RAWD, "S%s.png" % n) for n in todo], "seedvr2", UP_TO)
    for n in todo:
        made = os.path.join(RAWD, "S%s_%s.png" % (n, UP_TO))
        if os.path.exists(made):
            shutil.move(made, os.path.join(GEN, "S%s.png" % n))
            print("放大 S%s" % n)
        else:
            print("!! 没放大出来 S%s" % n)


def do_sheet(args):
    from PIL import Image, ImageDraw, ImageFont
    refs = args[:1] == ["refs"]
    if refs:
        items = [(k, os.path.join(REFD, k + ".png")) for k in C.REFS]
        tw, th, cols, per = 270, 480, 8, 24
    else:
        items = [(n, os.path.join(RAWD, "S%s.png" % n)) for n in C.SHOTS]
        tw, th, cols, per = 384, 216, 6, 30
    items = [x for x in items if os.path.exists(x[1])]
    try:
        font = ImageFont.truetype("arialbd.ttf", 26)
    except OSError:
        font = ImageFont.load_default()
    for page in range(0, len(items), per):
        chunk = items[page:page + per]
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * tw, rows * th), "black")
        for i, (lab, p) in enumerate(chunk):
            im = Image.open(p).convert("RGB")
            im.thumbnail((tw, th))
            x, y = (i % cols) * tw, (i // cols) * th
            sheet.paste(im, (x + (tw - im.width) // 2, y + (th - im.height) // 2))
            d = ImageDraw.Draw(sheet)
            d.rectangle([x, y, x + 64, y + 34], fill="black")
            d.text((x + 6, y + 3), lab, fill="yellow", font=font)
        out = os.path.join(PROJ, "_联络表_%s_%d.jpg" % ("定妆" if refs else "镜头", page // per + 1))
        sheet.save(out, quality=88)
        print("联络表", out)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("refs", "shots", "up", "sheet"):
        sys.exit(__doc__)
    {"refs": do_refs, "shots": do_shots, "up": do_up, "sheet": do_sheet}[sys.argv[1]](sys.argv[2:])
