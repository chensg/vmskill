# -*- coding: utf-8 -*-
"""横版长片合成：讲述稿 + 一句一条旁白 + 生成影片 / 静帧 / 外部素材 → 门禁二片、分部预览、全片、英文轨。

从《剩人》（成片_正式版.py / 英文轨.py）和《拙政園的山茶》（门禁二/render.py）收上来的：那两支每支各抄一套，
差别只有十来个常数和一张外部素材表。这里把常数和表放进 <项目>/build/film_config.py，流程只此一份。

    python film.py check                # 读稿、排时间轴，逐镜报画面从哪来；缺画面的标 !!。不渲染
    python film.py srt                  # 只出中文 SRT 和章节时间码（改了字幕切法不用重渲）
    python film.py tsv                  # build/_shots.tsv：镜号、标签、秒数、章、画面说明、旁白（写提示词、算帧数用）
    python film.py gate2                # 门禁二片：看稿画面 + 旁白 + 配乐 + 烧录字幕 → <项目>/门禁二/
    python film.py shots 05 37 116      # 调参：只渲这几镜 → 成片/_tmp_final/_check_<镜号>.mp4
    python film.py part 2               # 第 2 部分预览（部分 1＝冷开场＋第一章，部分 N＝第 N 章）
    python film.py final                # 全片 → 成片/<NAME>.mp4 + .srt + _章节时间码.txt
    python film.py en check | en        # 英文轨：对槽表 | <NAME>_音轨_eng.m4a + .en.srt + 英文章节时间码

    通用选项：--proj <项目目录>（缺省：当前目录，在 build/ 里跑就是上一级）
              --config <film_config.py>（缺省 <项目>/build/film_config.py）
              --out <目录>（缺省 <项目>/成片；gate2 缺省 <项目>/门禁二）
              --allow-missing（final / part 有镜缺画面时照样出，缺的用深底顶）

约定（两支长片都是这样的）：
  讲述稿    `## 章名` 分章；镜头行 `**镜号** [标签] 画面说明`，带 `＋[詩]` 的镜把旁白里引号内的诗句竖排在右侧。
            正文取 BODY[0] 到 BODY[1] 之间。无旁白的镜是卡：说明里有「片名卡」「章節卡」的出正中大字。
  旁白      <项目>/vo_lines.json：[{id, shot, txt, subs:[…]}]；音频 build/vo/<id>.mp3。时间轴归中文旁白。
  画面      [生…] → 素材/影片/<前缀><镜号>.mp4（CLIPS 可给一镜多条）；[推] → 静帧慢推；
            其余查 SPEC（kb / page / route / labels / clips / seq / quote）和 CARD_BG（卡的底图，压暗）。
  成品      成片/_tmp_final/NNN.mp4 + .wav + .key；.key 是这一镜的指纹，配方或源文件变了才重渲。
  配乐      素材/配乐/<前缀>_段N_k.mp3，每段接起来（不够长循环），段间 3 秒交叉，被旁白侧链压。

要 numpy、Pillow，ffmpeg / ffprobe 在 PATH 上。配置的写法见 references/long-film.md。
"""
import io
import json
import os
import re
import subprocess
import sys
import types

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

Image.MAX_IMAGE_PIXELS = None
for _s in (sys.stdout, sys.stderr):        # stderr 也转：sys.exit("中文") 走它
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

DEFAULTS = dict(
    NAME="成片_横版",                 # 交付物主干：<NAME>.mp4 / .srt / _音轨_eng.m4a
    GATE2_NAME=None,                  # 门禁二片的文件名主干，缺省 <NAME>_门禁二
    TITLE_BIG="",                     # 片名卡正中大字（ASS 文本，如 "剩人\\N{\\fs44}函可・盛京十一年"）
    SCRIPT=None,                      # 讲述稿文件名；缺省取最新的 讲述稿_v*.md
    BODY=("## 冷開場", "## 片名候選"),
    FIRST_SEG=("冷開場", "第一章"),   # 这些章并成部分 1；之后每章一个部分
    SHOT_RE=r"^\*\*(\d+[a-z]?)\*\* (?:⚠ )?\[([^\]]+)\](.*)$",
    VO_LINES="vo_lines.json", VO_DIR="build/vo", VO_EN_DIR="build/vo_en", SCRIPT_EN="讲述稿_en.md",
    SR=48000, FPS=24, W=1920, H=1080,
    GAP=0.7, CARD=3.0, ENDHOLD=5.0,   # 镜间、无旁白的卡停几秒、全片末镜停几秒
    TAIL=0.0,                         # 末镜之后再留白几秒
    MUS_DIR="素材/配乐", MUS_PREFIX="MM", SKIP=5.0,
    VO_LUFS=-16, MUS_DB=-24, AMB_DB=-32,
    FINAL_LUFS=-15.0,                 # 混完整体量一次、加一个固定增益到这个数；None = 不归一
    VID_DIR="素材/影片", VID_PREFIX="G", STILL_PAT="素材/生成/S{n}.png",
    CLIPS={}, SPEC={}, CARD_BG={}, DIM_CARD=0.36,
    MUTE_EXT=False,                   # True = SPEC / CARD_BG 里的外部影片不带原声（新闻素材带解说和配乐时用）
    END_POEM=None,                    # 末镜上竖排的一句，如 ["秖待水流石出"]
    LABEL_NOTE={},                    # labels 镜右下角的出处角注 {镜号: 文字}
    KAI=r"C:\Windows\Fonts\simkai.ttf", KAI_NAME="KaiTi", SUB_FONT="Microsoft JhengHei",
    CARD_EN={}, CHAPTER_EN={}, TEMPO_MAX=1.06, MARGIN=0.25,
)
C = types.SimpleNamespace()
CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
X264 = ["-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p"]


def die(msg):
    sys.exit("!!! " + msg)


def P(rel):
    return rel if os.path.isabs(rel) else os.path.join(C.PROJ, rel)


def load_config(path, proj):
    ns = {"os": os, "PROJ": proj, "HERE": os.path.dirname(os.path.abspath(path)), "__file__": path}
    exec(compile(io.open(path, encoding="utf-8").read(), path, "exec"), ns)
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in ns.items() if k in DEFAULTS})
    # 写错的键（MUTE_EXTS、CARDBG…）原来静默忽略，配置看着写了、渲出来没生效。只报和认得的键很像的，
    # 配置里自己起的辅助名（CM、EXT、GEN 这类）不报
    import difflib
    for k in sorted(ns):
        if k.isupper() and k not in DEFAULTS and not callable(ns[k]):
            near = difflib.get_close_matches(k, list(DEFAULTS), n=1, cutoff=0.75)
            if near:
                print("!! 配置里的 %s 不是 film.py 认的键，没生效 —— 是不是 %s？" % (k, near[0]))
    for k, v in cfg.items():
        setattr(C, k, v)
    C.PROJ, C.CONFIG = proj, path
    if not C.SCRIPT:
        c = [f for f in os.listdir(proj) if re.match(r"讲述稿(_v[\d.]+)?\.md$", f)]
        if not c:
            die("配置里没写 SCRIPT，项目里也没有 讲述稿.md / 讲述稿_v*.md")
        C.SCRIPT = max(c, key=lambda f: os.path.getmtime(os.path.join(proj, f)))
        print("讲述稿：%s（配置里没写 SCRIPT，取最新的）" % C.SCRIPT)


# ---------------- 小工具 ----------------
def dur(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p]))


def load(p, af=None):
    cmd = ["ffmpeg", "-v", "quiet", "-i", p] + (["-af", af] if af else []) + ["-ac", "1", "-ar", str(C.SR), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, dtype=np.float32)


def run(args):
    subprocess.run(["ffmpeg", "-v", "error", "-y"] + args, check=True)


def ts(t, srt=False):
    h, r = divmod(t, 3600); m, s = divmod(r, 60)
    if srt:
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s % 1) * 1000)) % 1000:03d}"
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def esc(t):
    return t.replace("{", "｛").replace("}", "｝").replace("\n", "\\N")


def chunk(x, mx=24):
    """一条字幕 ≤mx 字：先按句末标点切，再按逗号顿号切，引号不拆开算。"""
    out, buf = [], ""
    for piece in re.findall(r"[^。；：！？，、」』]*[。；：！？，、]?[」』]?", x):
        if not piece:
            continue
        if buf and len(buf) + len(piece) > mx:
            out.append(buf); buf = ""
        buf += piece
        if piece.rstrip("」』")[-1:] in "。；！？" and len(buf) >= mx * 0.5:
            out.append(buf); buf = ""
    if buf:
        out.append(buf)
    return [o.rstrip("，、；") for o in out if o.strip()]


# ---------------- 读稿、排时间轴 ----------------
def read_shots():
    src = io.open(P(C.SCRIPT), encoding="utf-8").read()
    try:
        body = src[src.index(C.BODY[0]):src.index(C.BODY[1])]
    except ValueError:
        die("讲述稿里找不到正文的起止标记 %s … %s" % C.BODY)
    if not os.path.isfile(P(C.VO_LINES)):
        die("缺旁白表 %s —— 一句一条：[{\"id\": \"VO_001\", \"shot\": \"01\", \"txt\": 全句, \"subs\": [分好的字幕句…]}, …]" % P(C.VO_LINES))
    vo = {v["shot"]: v for v in json.load(io.open(P(C.VO_LINES), encoding="utf-8"))}
    shots, chap, seg = [], None, 0
    for ln in body.splitlines():
        if ln.startswith("## "):
            chap = ln[3:].strip()
            seg = 1 if any(chap == f or chap.startswith(f) for f in C.FIRST_SEG) else seg + 1
            continue
        m = re.match(C.SHOT_RE, ln)
        if m:
            shots.append({"n": m.group(1), "tag": m.group(2), "chapter": chap, "seg": seg, "poem": "＋[詩]" in ln,
                          "desc": m.group(3).replace("＋[詩]", "").strip(), "vo": vo.get(m.group(1))})
    if not shots:
        die("讲述稿正文里一镜都没读到（镜头行要写成 **镜号** [标签] 说明）")
    lost = sorted(set(vo) - {s["n"] for s in shots})
    if lost:
        die("vo_lines.json 里这些镜号稿子里没有：%s" % "、".join(lost[:10]))
    return shots


def timeline(shots, need_audio=True):
    """排全片。返回 SimpleNamespace：total / spans / subs / centers / poems / chapters / segspan / audio / info / items。"""
    T = types.SimpleNamespace(audio=[], subs=[], centers=[], poems=[], spans=[], chapters=[], segspan={}, info=[], items=[])
    t, last_ch = 0.0, None
    for s in shots:
        start = t
        if s["chapter"] != last_ch:
            T.chapters.append((start, s["chapter"])); last_ch = s["chapter"]
        if not s["vo"]:
            end = s is shots[-1]
            hold = C.ENDHOLD if end else C.CARD
            T.audio.append(np.zeros(int(hold * C.SR), np.float32)); t += hold
            s["secs"] = hold
            if end and C.END_POEM:
                T.poems.append((start + 0.8, t, list(C.END_POEM)))
            if "片名卡" in s["desc"]:
                if C.TITLE_BIG:
                    T.centers.append((start, t, C.TITLE_BIG))
            elif "章節卡" in s["desc"] or "章节卡" in s["desc"]:
                c = s["chapter"].split("　")
                T.centers.append((start, t, "{\\fs50}" + c[0] + "\\N{\\fs110}" + (c[1] if len(c) > 1 else "")))
        else:
            p = os.path.join(P(C.VO_DIR), s["vo"]["id"] + ".mp3")
            if not os.path.isfile(p):
                die("缺旁白 %s（镜 %s）" % (p, s["n"]))
            a = load(p)
            L = len(a) / C.SR
            s["secs"] = L
            parts = [c for x in s["vo"]["subs"] for c in chunk(x)]
            wts = [max(1, len(CJK.findall(x))) for x in parts]
            acc, sub_t = t, []
            for x, k in zip(parts, wts):
                d = L * k / sum(wts)
                T.subs.append((acc, acc + d, x)); sub_t.append((acc, x)); acc += d
            T.audio += [a, np.zeros(int(C.GAP * C.SR), np.float32)]
            T.items.append({"id": s["vo"]["id"], "n": s["n"], "start": start})
            t += L + C.GAP
            if s["tag"].startswith("卡") and "字卡" in s["desc"]:
                q = re.findall(r"「([^」]+)」", s["desc"])
                if q:
                    big = q[0].split("｜")
                    T.centers.append((start, t, f"{{\\fs{110 if len(big) == 1 else 76}}}" + "\\N".join(big)))
            if s["poem"]:
                first = next((a0 for a0, x in sub_t if "「" in x or "『" in x), start)
                cols = []
                for q in re.findall(r"[「『]([^」』]+)[」』]", s["vo"]["txt"]):
                    cols += [c for c in re.split(r"[，。、；：！？]", q) if c]
                if cols:
                    T.poems.append((first, t - 0.2, cols))
        T.spans.append((s, start, t))
        T.info.append((start, t, f"{s['chapter']}｜鏡 {s['n']}　[{s['tag']}]{'＋[詩]' if s['poem'] else ''}", s["desc"]))
        T.segspan.setdefault(s["seg"], [start, t])[1] = t
    if C.TAIL:
        T.audio.append(np.zeros(int(C.TAIL * C.SR), np.float32)); t += C.TAIL
    T.total = t
    print(f"全片 {T.total / 60:.2f} 分钟（{T.total:.2f}s），{len(shots)} 镜；段：" +
          "、".join(f"段{k} {b - a:.0f}s" for k, (a, b) in sorted(T.segspan.items())))
    return T


def write_srt(path, subs):
    with io.open(path, "w", encoding="utf-8") as f:
        for i, (a, b, line) in enumerate(subs, 1):
            f.write(f"{i}\n{ts(a, True)} --> {ts(b, True)}\n{line}\n\n")


def write_chapters(path, chapters, names=None):
    with io.open(path, "w", encoding="utf-8") as f:
        for a, ch in chapters:
            m, s_ = divmod(int(a), 60)
            f.write(f"{m}:{s_:02d} {(names or {}).get(ch, ch.replace(chr(0x3000), ' '))}\n")


# ---------------- 帧生成器 ----------------
class Writer:
    def __init__(self, path):
        self.p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{C.W}x{C.H}",
                                   "-r", str(C.FPS), "-i", "-"] + X264 + [path], stdin=subprocess.PIPE)

    def put(self, im):
        self.p.stdin.write(im.convert("RGB").tobytes())

    def close(self):
        self.p.stdin.close(); self.p.wait()


def ease(x):
    return x * x * (3 - 2 * x)


def lerp(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def prep(src, boxes, limit=2.6):
    """把原图先缩到「最小框 × limit 倍输出」够用的大小，省每帧的运算。"""
    im = Image.open(src).convert("RGB")
    s = min(1.0, C.W * limit / min(b[2] for b in boxes) / im.width)
    if s < 1:
        im = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
    return im


def kb_frame(im, b):
    """框 b＝(中心x, 中心y, 宽)，都是原图的比例；高按画幅比自动算。"""
    cx, cy, w = b
    pw = w * im.width; ph = pw / (C.W / C.H)
    x0 = min(max(cx * im.width - pw / 2, 0), im.width - pw); y0 = min(max(cy * im.height - ph / 2, 0), im.height - ph)
    return im.transform((C.W, C.H), Image.EXTENT, (x0, y0, x0 + pw, y0 + ph), Image.BICUBIC), (x0, y0, pw, ph)


def r_kb(w, D, src, b0, b1, dim=1.0):
    im = prep(src, [b0, b1]); N = int(round(D * C.FPS))
    for i in range(N):
        fr, _ = kb_frame(im, lerp(b0, b1, ease(i / max(1, N - 1))))
        w.put(ImageEnhance.Brightness(fr).enhance(dim) if dim < 1 else fr)


def r_page(w, D, src, region, rects, base_dim=0.55):
    """档案页：取 region 放进画面（深底、纸色），慢推 1.0→1.05；rects＝(x0,y0,x1,y1,t0) 按 t0 依次亮起。"""
    full = Image.open(src).convert("RGB"); fw, fh = full.size
    rx0, ry0, rx1, ry1 = region
    crop = full.crop((int(rx0 * fw), int(ry0 * fh), int(rx1 * fw), int(ry1 * fh)))
    cw, ch = crop.size
    s = min((C.H - 40) / ch, (C.W - 120) / cw)
    pg = crop.resize((int(cw * s * 1.06), int(ch * s * 1.06)), Image.LANCZOS)      # 留出推近余量
    pg = ImageOps.colorize(pg.convert("L"), black=(34, 24, 16), white=(238, 226, 200))
    base = ImageEnhance.Brightness(pg).enhance(base_dim)
    warm = Image.new("RGB", pg.size, (255, 214, 140))
    bg = Image.new("RGB", (C.W, C.H), (22, 19, 16))
    N = int(round(D * C.FPS))
    boxes = []
    for x0, y0, x1, y1, t0 in rects:
        bx0 = (x0 - rx0) / (rx1 - rx0) * pg.width; bx1 = (x1 - rx0) / (rx1 - rx0) * pg.width
        by0 = (y0 - ry0) / (ry1 - ry0) * pg.height; by1 = (y1 - ry0) / (ry1 - ry0) * pg.height
        boxes.append((int(bx0), int(by0), int(bx1), int(by1), t0))
    lit = Image.blend(pg, warm, 0.10)
    if boxes:
        fx = sum((b[0] + b[2]) / 2 for b in boxes) / len(boxes) / pg.width
        fy = sum((b[1] + b[3]) / 2 for b in boxes) / len(boxes) / pg.height
    else:
        fx = fy = 0.5
    sw, sh = pg.width / 1.06, pg.height / 1.06
    for i in range(N):
        t = i / max(1, N - 1)
        fr = base.copy()
        for bx0, by0, bx1, by1, t0 in boxes:
            a = min(1.0, max(0.0, (t - t0) / 0.06))
            if a <= 0:
                continue
            fr.paste(Image.blend(fr.crop((bx0, by0, bx1, by1)), lit.crop((bx0, by0, bx1, by1)), a), (bx0, by0))
        z = 1.0 + 0.05 * ease(t)
        cx = pg.width / 2 + (fx - 0.5) * (pg.width - sw) * ease(t)
        cy = pg.height / 2 + (fy - 0.5) * (pg.height - sh) * ease(t)
        view = fr.crop((int(cx - sw / 2), int(cy - sh / 2), int(cx + sw / 2), int(cy + sh / 2))).resize((int(sw * z), int(sh * z)), Image.BICUBIC)
        out = bg.copy(); out.paste(view, ((C.W - view.width) // 2, (C.H - view.height) // 2))
        w.put(out)


def label(draw, xy, text, size=44, anchor="mm", fill=(120, 22, 18)):
    try:
        f = ImageFont.truetype(C.KAI, size)
    except OSError:
        f = ImageFont.load_default()
        anchor = None
    draw.text(xy, text, font=f, fill=fill, anchor=anchor, stroke_width=4, stroke_fill=(248, 238, 214))


def r_route(w, D, src, b0, b1, pts, names, back=False):
    """地图上画路线：pts 是原图比例坐标；names＝{点序号: 地名}，线画到了才出名字；back 再画一条回程。"""
    im = prep(src, [b0, b1], 2.2); N = int(round(D * C.FPS))
    Pt = [(x * im.width, y * im.height) for x, y in pts]
    seg = [np.hypot(Pt[k + 1][0] - Pt[k][0], Pt[k + 1][1] - Pt[k][1]) for k in range(len(Pt) - 1)]
    tot = sum(seg)

    def walk(points, segs, L, tp):
        acc, out = 0, [tp(points[0])]
        for k, s in enumerate(segs):
            if acc + s <= L:
                out.append(tp(points[k + 1])); acc += s
            else:
                r = (L - acc) / s if s else 0
                out.append(tp((points[k][0] + (points[k + 1][0] - points[k][0]) * r,
                               points[k][1] + (points[k + 1][1] - points[k][1]) * r))); break
        return out
    for i in range(N):
        t = i / max(1, N - 1)
        fr, (x0, y0, pw, ph) = kb_frame(im, lerp(b0, b1, ease(t)))
        sc = C.W / pw
        tp = lambda p: ((p[0] - x0) * sc, (p[1] - y0) * sc)
        go = min(1, max(0, (t - 0.08) / (0.54 if back else 0.77)))
        d = ImageDraw.Draw(fr)
        L = go * tot
        line = walk(Pt, seg, L, tp)
        if len(line) > 1:
            d.line(line, fill=(150, 24, 20), width=7, joint="curve")
        if back and t > 0.65:
            rev = walk(list(reversed(Pt)), list(reversed(seg)), min(1, (t - 0.65) / 0.30) * tot, tp)
            off = [(x + 9, y + 9) for x, y in rev]
            if len(off) > 1:
                d.line(off, fill=(70, 40, 30), width=4)
        acc = 0
        for k, p in enumerate(Pt):
            if k > 0:
                acc += seg[k - 1]
            if k in names and (k == 0 or acc <= L + 1):
                x, y = tp(p); d.ellipse((x - 9, y - 9, x + 9, y + 9), fill=(150, 24, 20), outline=(248, 238, 214), width=3)
                label(d, (x + 16, y - 34), names[k], 46, "lm")
        w.put(fr)


def r_labels(w, D, src, b0, b1, items, note=None):
    """地图上依次亮出地名：items＝[((x, y), 名字), …]；note 是右下角的出处角注。"""
    im = prep(src, [b0, b1], 2.2); N = int(round(D * C.FPS)); n = len(items)
    for i in range(N):
        t = i / max(1, N - 1)
        fr, (x0, y0, pw, ph) = kb_frame(im, lerp(b0, b1, ease(t)))
        sc = C.W / pw; d = ImageDraw.Draw(fr)
        for k, ((px, py), name) in enumerate(items):
            if t < 0.06 + k * (0.80 / n):
                continue
            x, y = (px * im.width - x0) * sc, (py * im.height - y0) * sc
            d.ellipse((x - 10, y - 10, x + 10, y + 10), fill=(150, 24, 20), outline=(248, 238, 214), width=3)
            label(d, (x, y - 40), name, 50)
        if note:
            label(d, (C.W - 60, C.H - 50), note, 28, "rm", (60, 40, 30))
        w.put(fr)


def r_clips(path_v, path_a, D, clips, dim=1.0):
    """影片镜：几条接起来，短了先放慢（最多 15%）再定格；带原片的环境声。返回放慢到的倍率。"""
    n = len(clips)
    ins = sum((["-i", c] if isinstance(c, str) else ["-ss", f"{float(c[1]):.3f}", "-t", f"{clip_dur(c):.3f}", "-i", c[0]] for c in clips), [])
    has_a = [bool(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", clip_path(c)],
                                 capture_output=True, text=True).stdout.strip()) for c in clips]
    pre = "".join(f"[{k}:v]scale={C.W}:{C.H},fps={C.FPS},setsar=1[v{k}];" for k in range(n))
    pre += "".join((f"[{k}:a]aresample={C.SR},aformat=channel_layouts=mono[a{k}];" if has_a[k] else
                    f"anullsrc=r={C.SR}:cl=mono,atrim=duration={clip_dur(clips[k]):.3f}[a{k}];") for k in range(n))
    cat = "".join(f"[v{k}][a{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=1[cv0][ca0];"
    T = sum(clip_dur(c) for c in clips)
    rate = max(T / D, 0.85) if T < D - 0.4 else 1.0
    slow = (f"[cv0]setpts=PTS/{rate:.4f},fps={C.FPS}[cv];[ca0]atempo={rate:.4f}[ca];" if rate < 1 else "[cv0]null[cv];[ca0]anull[ca];")
    dimf = f",lutyuv=y=val*{dim:.3f}:u=128+(val-128)*0.7:v=128+(val-128)*0.7" if dim < 1 else ""
    fc = pre + cat + slow + (f"[cv]tpad=stop_mode=clone:stop_duration={D + 1:.3f},trim=duration={D + 0.5:.3f},setpts=PTS-STARTPTS{dimf}[v];"
                             f"[ca]apad,atrim=duration={D:.3f}[a]")
    # 帧数写死：trim 按时间截会多出或少出一帧，一百多镜累积下来画面比旁白晚一秒多（《剩人》正式版实测 +1.48s）
    run(ins + ["-filter_complex", fc, "-map", "[v]"] + X264 + ["-r", str(C.FPS), "-frames:v", str(int(round(D * C.FPS))), path_v,
               "-map", "[a]", "-ac", "1", "-ar", str(C.SR), path_a])
    return rate


def clip_path(c):
    """clips 里的一条：路径，或 (路径, 起点秒, 取几秒) —— 整支下载的外部影片只用其中一段。"""
    return c if isinstance(c, str) else c[0]


def clip_dur(c):
    if isinstance(c, str):
        return dur(c)
    return min(float(c[2]), max(0.0, dur(c[0]) - float(c[1])))


def silent(path_a, D):
    run(["-f", "lavfi", "-i", f"anullsrc=r={C.SR}:cl=mono", "-t", f"{D:.3f}", path_a])


def spec_sources(spec):
    if spec[0] in ("clips",):
        return [clip_path(c) for c in spec[1]]
    if spec[0] == "seq":
        return sum((spec_sources(s) for s in spec[1]), [])
    if spec[0] == "quote":
        return [spec[3]] if len(spec) > 3 and spec[3] else []
    return [spec[1]]


def r_quote(w, D, text, source=None, bg=None):
    """引文板：深底（或压暗的底图）上居中排一段引文，一行一行淡入，末尾出处小字；整体 1.00→1.03 慢推。
    text 用「｜」或换行分行；没分行的按 16 字一行自动折，分了行但一行超过 24 字（54 号字排不下）的也折。"""
    lines = [x for x in re.split(r"[｜\n]", text) if x.strip()]
    if len(lines) == 1 and len(lines[0]) > 16:
        s = lines[0]; lines = [s[k:k + 16] for k in range(0, len(s), 16)]
    lines = [ln[k:k + 24] for ln in lines for k in range(0, len(ln), 24)]
    try:
        f = ImageFont.truetype(C.KAI, 64 if max(len(x) for x in lines) <= 14 else 54)
        fs = ImageFont.truetype(C.KAI, 34)
    except OSError:
        f = fs = ImageFont.load_default()
    if bg:
        base = ImageEnhance.Brightness(kb_frame(prep(bg, [(0.5, 0.5, 1.0)]), (0.5, 0.5, 1.0))[0]).enhance(0.28)
    else:
        base = Image.new("RGB", (C.W, C.H), (22, 19, 16))
    lh = int(f.size * 1.75)
    y0 = C.H / 2 - (len(lines) * lh + (70 if source else 0)) / 2
    N = int(round(D * C.FPS))
    for i in range(N):
        t = i / max(1, N - 1)
        fr = base.copy(); d = ImageDraw.Draw(fr)
        for k, ln in enumerate(lines):
            a = min(1.0, max(0.0, (t - 0.04 - k * 0.55 / len(lines)) / 0.08))
            if a > 0:
                c = int(236 * a + 22 * (1 - a))
                d.text((C.W / 2, y0 + k * lh + lh / 2), ln, font=f, fill=(c, int(c * 0.95), int(c * 0.86)), anchor="mm")
        if source and t > 0.62:
            a = min(1.0, (t - 0.62) / 0.08); c = int(150 * a + 22 * (1 - a))
            d.text((C.W / 2 + 360, y0 + len(lines) * lh + 40), "—— " + source, font=fs, fill=(c, c, c), anchor="rm")
        z = 1.0 + 0.03 * ease(t)
        if z > 1.0005:
            cw, ch = C.W / z, C.H / z
            fr = fr.crop((int((C.W - cw) / 2), int((C.H - ch) / 2), int((C.W + cw) / 2), int((C.H + ch) / 2))).resize((C.W, C.H), Image.BICUBIC)
        w.put(fr)


def render_spec(spec, D, f_v, f_a, dim=1.0, note=None):
    kind = spec[0]
    if kind == "clips":
        r = r_clips(f_v, f_a, D, spec[1], dim)
        if C.MUTE_EXT:
            silent(f_a, D)
        return "外部影片" + ("（放慢 %d%%）" % round(r * 100) if r < 1 else "")
    if kind == "seq":
        parts = []
        # 影片段按自己的长度，其余（照片、地图、引文板）平分剩下的、每段至少 4 秒；最后按比例缩到正好 D。
        # 原来照片段每段都拿「D − 影片总长」，两张照片（没有影片）就各要整镜长，第二张只剩 1 帧。
        clip_len = [sum(clip_dur(c) for c in s[1]) if s[0] == "clips" else 0.0 for s in spec[1]]
        n_still = sum(s[0] != "clips" for s in spec[1])
        still_D = max(4.0, (D - sum(clip_len)) / n_still) if n_still else 0.0
        want = [clip_len[k] if s[0] == "clips" else still_D for k, s in enumerate(spec[1])]
        if n_still and len(spec[1]) > n_still:            # 照片＋影片：照片先占够，影片拿剩下的（至少 0.5 秒）
            room = max(0.5 * (len(spec[1]) - n_still), D - still_D * n_still)
            ct = sum(clip_len) or 1.0
            want = [x * room / ct if s[0] == "clips" else x for x, s in zip(want, spec[1])]
        want = [x * D / sum(want) for x in want]
        # 各小段的帧数加起来必须等于这一镜的帧数：前几段按累计时间取整，最后一段拿剩下的
        total_f, used, frames = int(round(D * C.FPS)), 0, []
        for k, d_ in enumerate(want):
            f_ = total_f - used if k == len(want) - 1 else int(round(sum(want[:k + 1]) * C.FPS)) - used
            frames.append(max(1, f_)); used += frames[-1]
        for k, s in enumerate(spec[1]):
            pv, pa = f_v[:-4] + f"_s{k}.mp4", f_a[:-4] + f"_s{k}.wav"
            d_ = frames[k] / C.FPS
            if s[0] == "clips":
                r_clips(pv, pa, d_, s[1], dim)
                if C.MUTE_EXT:
                    silent(pa, d_)
            else:
                render_spec(s, d_, pv, pa, dim, note)
            parts.append((pv, pa))
        with io.open(f_v + ".txt", "w", encoding="utf-8") as f:
            f.writelines(f"file '{p}'\n" for p, _ in parts)
        run(["-f", "concat", "-safe", "0", "-i", f_v + ".txt", "-c", "copy", f_v])
        run(sum((["-i", a] for _, a in parts), []) + ["-filter_complex", "".join(f"[{k}]" for k in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1", f_a])
        return "组合"
    wtr = Writer(f_v)
    if kind == "kb":
        r_kb(wtr, D, spec[1], spec[2], spec[3], dim)
    elif kind == "page":
        r_page(wtr, D, spec[1], spec[2], spec[3], spec[4] if len(spec) > 4 else 0.55)
    elif kind == "route":
        r_route(wtr, D, spec[1], spec[2], spec[3], spec[4], spec[5], spec[6] if len(spec) > 6 else False)
    elif kind == "labels":
        r_labels(wtr, D, spec[1], spec[2], spec[3], spec[4], spec[5] if len(spec) > 5 else note)
    elif kind == "quote":
        r_quote(wtr, D, spec[1], spec[2] if len(spec) > 2 else None, spec[3] if len(spec) > 3 else None)
    else:
        wtr.close(); die("SPEC 里不认识的类型 %r" % kind)
    wtr.close(); silent(f_a, D)
    return kind


def plan(s, T):
    """这一镜的画面从哪来。返回 (说明, [源文件], 渲染函数或 None)；None＝没有画面，只能用深底顶。"""
    n = s["n"]
    ids = C.CLIPS.get(n, [C.VID_PREFIX + n])
    clips = [os.path.join(P(C.VID_DIR), x + ".mp4") for x in ids]
    still = P(C.STILL_PAT.format(n=n))
    # SPEC 写了就用 SPEC，哪怕这一镜的生成影片也在：弃用一条影片（手坏了、走进现代人）就是在 SPEC 里改写这一镜。
    # 原来影片优先，SPEC 被静默忽略 —— 2026-11-14 徐燦 L71 写了 4K 慢推，成片里还是那条手坏了的影片。
    if n in C.SPEC:
        sp = C.SPEC[n]
        return "SPEC " + sp[0], spec_sources(sp), lambda D, fv, fa: render_spec(sp, D, fv, fa, 1.0, C.LABEL_NOTE.get(n))
    if s["tag"].startswith("生") and all(os.path.exists(c) for c in clips):
        def go(D, fv, fa):
            r = r_clips(fv, fa, D, clips)
            return "+".join(ids) + (f"（放慢 {r:.0%}）" if r < 1 else "")
        return "影片 " + "+".join(ids), clips, go
    if n in C.CARD_BG:
        sp = C.CARD_BG[n]
        return "卡底 " + sp[0], spec_sources(sp), lambda D, fv, fa: "卡底：" + render_spec(sp, D, fv, fa, C.DIM_CARD)
    if s["tag"] == "推" and os.path.exists(still):
        def go(D, fv, fa):
            wtr = Writer(fv); r_kb(wtr, D, still, (0.5, 0.5, 1.0), (0.5, 0.5, 1 / 1.06)); wtr.close(); silent(fa, D)
            return os.path.basename(still) + " 慢推"
        return "静帧慢推", [still], go
    start = next(a for x, a, b in T.spans if x is s)
    if any(c[0] == start for c in T.centers):
        return "深底（字卡）", [], "dark"
    want = ("影片 " + "、".join(os.path.basename(c) for c in clips if not os.path.exists(c))) if s["tag"].startswith("生") else \
           (os.path.basename(still) if s["tag"] == "推" else "SPEC / CARD_BG 里没有这一镜")
    return "!! 没有画面（缺 %s）" % want, [], None


RENDER_VER = 2      # 渲染函数改了出画结果时加一，旧成品全部作废


def shot_sig(s, T):
    """这一镜「怎么渲」的全部输入，和 plan() 走同样的分支。只改了别的镜的 SPEC，这一镜的指纹不变，成品照旧沿用。"""
    n = s["n"]
    what, srcs, fn = plan(s, T)
    if n in C.SPEC and what.startswith("SPEC"):
        recipe = ["spec", repr(C.SPEC[n]), C.LABEL_NOTE.get(n), C.MUTE_EXT]
    elif n in C.CARD_BG and what.startswith("卡底"):
        recipe = ["card", repr(C.CARD_BG[n]), C.DIM_CARD, C.MUTE_EXT]
    else:
        recipe = ["plain", what]
    files = [[os.path.abspath(x), os.path.getsize(x), int(os.path.getmtime(x))] for x in srcs if os.path.exists(x)]
    return [RENDER_VER, C.W, C.H, C.FPS, C.SR, recipe, files]


def shot_key(s, T, D):
    import hashlib
    return hashlib.sha1(json.dumps(shot_sig(s, T) + [int(round(D * C.FPS))], ensure_ascii=False).encode("utf-8")).hexdigest()


def dark(D, f_v, f_a):
    run(["-f", "lavfi", "-i", f"color=c=0x16130f:s={C.W}x{C.H}:r={C.FPS}:d={D + 1:.3f}"] + X264
        + ["-frames:v", str(int(round(D * C.FPS))), f_v]); silent(f_a, D)


def render_shots(T, pick, tmp, check_names=False, allow_missing=False, t0=0.0):
    """渲 pick 选中的镜，返回 [(画面, 环境声)]。成品旁边的 .key 和这一镜现在的指纹（shot_sig：配方＋源文件大小和时间＋帧数）
    一样就沿用。原来拿成品和整份 film_config.py 的修改时间比，改一镜的 SPEC，全片九十多镜全部重渲（《拙政園的山茶》一次一个多小时）。
    没有 .key 的旧成品：按旧规则（比配置和源文件都新）认一次，补写 .key。

    **每镜的帧数按帧网格取**：round(止 × FPS) − round(起 × FPS)，而不是 round(镜长 × FPS)。
    后者每镜差零点几帧，一百多镜累积起来画面比旁白晚一秒多，章节卡的大字会压在上一镜的尾巴上。"""
    todo = [(i, s, a, b, plan(s, T)) for i, (s, a, b) in enumerate(T.spans) if pick(s)]
    miss = [s["n"] for _, s, _, _, pl in todo if pl[2] is None]
    if miss and not allow_missing:
        die("这些镜没有画面：%s。先补齐，或者加 --allow-missing 用深底顶着出。" % "、".join(miss))
    out, cfg_m = [], os.path.getmtime(C.CONFIG)
    for i, s, a, b, (what, srcs, fn) in todo:
        D = (int(round((b - t0) * C.FPS)) - int(round((a - t0) * C.FPS))) / C.FPS
        stem = os.path.join(tmp, f"_check_{s['n']}" if check_names else f"{i:03d}")
        f_v, f_a, f_k = stem + ".mp4", stem + ".wav", stem + ".key"
        key = shot_key(s, T, D)
        have = not check_names and os.path.exists(f_v) and os.path.exists(f_a)
        old = io.open(f_k, encoding="utf-8").read().strip() if have and os.path.exists(f_k) else None
        if have and old is None:
            newest = max([cfg_m] + [os.path.getmtime(x) for x in srcs if os.path.exists(x)])
            if os.path.getmtime(f_v) > newest and abs(dur(f_v) - D) < 0.06:
                old = key
        if have and old == key:
            kind = "（沿用）"
        else:
            if os.path.exists(f_k):
                os.remove(f_k)
            if fn in (None, "dark"):
                dark(D, f_v, f_a); kind = what
            else:
                kind = fn(D, f_v, f_a)
        if not check_names:            # 缺画面用深底顶的也记：补上画面后 plan 的说明变了，指纹跟着变，会重渲
            io.open(f_k, "w", encoding="utf-8").write(key)
        out.append((f_v, f_a))
        print(f"  鏡{s['n']:>4} [{s['tag']}] {D:5.1f}s → {kind}", flush=True)
    return out


# ---------------- 配乐床、混音 ----------------
def beds(segspan, total_end):
    """每段把候选接起来（不够长就循环），段间 3 秒交叉。返回 (ffmpeg 输入, 滤镜, 末标签, 下一个输入序号)。"""
    mus = P(C.MUS_DIR)
    ins, fc, labs, idx = [], [], [], 0
    ks = sorted(segspan)
    for k in ks:
        a, b = segspan[k]
        need = b - a + 3
        pieces = sorted(f for f in (os.listdir(mus) if os.path.isdir(mus) else [])
                        if re.match(r"%s_段%d_\d+\.mp3$" % (re.escape(C.MUS_PREFIX), k), f))
        if not pieces:
            die("段 %d 没有配乐（%s 里要有 %s_段%d_1.mp3 这样的文件）" % (k, mus, C.MUS_PREFIX, k))
        chain, have = [], 0.0
        while have < need:
            for f in pieces:
                chain.append(f); have += dur(os.path.join(mus, f)) - C.SKIP - (6 if len(chain) > 1 else 0)
                if have >= need:
                    break
        lab = []
        for f in chain:
            ins += ["-ss", str(C.SKIP), "-i", os.path.join(mus, f)]
            fc.append(f"[{idx}]loudnorm=I={C.MUS_DB}:TP=-3:LRA=11,aresample={C.SR},aformat=channel_layouts=mono[m{idx}]")
            lab.append(f"m{idx}"); idx += 1
        c = lab[0]
        for j, l in enumerate(lab[1:], 1):
            fc.append(f"[{c}][{l}]acrossfade=d=6[s{k}x{j}]"); c = f"s{k}x{j}"
        Lk = b - a + (3 if k != ks[-1] else total_end - b)
        fin = "afade=t=in:d=2," if k == ks[0] else ""
        fout = f",afade=t=out:st={Lk - 4:.2f}:d=4" if k == ks[-1] else ""
        fc.append(f"[{c}]atrim=0:{Lk:.2f},{fin}anull{fout}[bed{k}]")
        labs.append(f"bed{k}")
    c = labs[0]
    for j, l in enumerate(labs[1:], 1):
        fc.append(f"[{c}][{l}]acrossfade=d=3[bb{j}]"); c = f"bb{j}"
    return ins, fc, c, idx


def mix(vo_f32, amb, segspan, total_end, out_m4a, bitrate="256k"):
    ins, fc, c, idx = beds(segspan, total_end)
    ins += ["-f", "f32le", "-ar", str(C.SR), "-ac", "1", "-i", vo_f32]
    fc.append(f"[{idx}]loudnorm=I={C.VO_LUFS}:TP=-1.5:LRA=11,aresample={C.SR},asplit=2[vo1][vo2]")
    fc.append(f"[{c}][vo2]sidechaincompress=threshold=0.02:ratio=6:attack=40:release=700[duck]")
    if amb:
        ins += ["-i", amb]
        fc.append(f"[{idx + 1}]loudnorm=I={C.AMB_DB}:TP=-6:LRA=15,aresample={C.SR}[amb]")
        fc.append("[vo1][duck][amb]amix=inputs=3:duration=first:normalize=0,alimiter=limit=0.95[out]")
    else:
        fc.append("[vo1][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[out]")
    if C.FINAL_LUFS is None:
        run(ins + ["-filter_complex", ";".join(fc), "-map", "[out]", "-ac", "2", "-b:a", bitrate, out_m4a])
        return None
    raw = out_m4a + ".raw.wav"
    run(ins + ["-filter_complex", ";".join(fc), "-map", "[out]", "-ac", "2", raw])
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", raw, "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    i = float(json.loads(p.stderr[p.stderr.rfind("{"):p.stderr.rfind("}") + 1])["input_i"])
    g = C.FINAL_LUFS - i
    run(["-i", raw, "-af", f"volume={g:.2f}dB,alimiter=limit=0.95", "-ac", "2", "-ar", str(C.SR), "-b:a", bitrate, out_m4a])
    os.remove(raw)
    print(f"  响度：混完 {i:.1f} LUFS，加 {g:+.1f} dB 到 {C.FINAL_LUFS:.0f}")
    return g


ASS_HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: %d
PlayResY: %d
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
%s

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def overlay_events(T, t0=0.0, t1=None):
    """卡上的大字和竖排诗。t0/t1 是窗口：只留窗口里的，并把时间平移到从 0 起。"""
    t1 = T.total if t1 is None else t1
    ev = []
    for a, b, big in T.centers:
        if t0 - 1e-6 <= a < t1:
            ev.append(f"Dialogue: 1,{ts(a - t0)},{ts(b - t0)},Big,,0,0,0,,{{\\fad(400,400)}}{big}")
    for a, b, cols in T.poems:
        if not (t0 - 1e-6 <= a < t1):
            continue
        for j, col in enumerate(cols):
            st = min(a + j * 0.9, b - 0.3)
            ev.append(f"Dialogue: 3,{ts(st - t0)},{ts(b - t0)},Poem,,0,0,0,,{{\\pos({C.W - 130 - j * 92},150)\\fad(500,500)}}" + "\\N".join(col))
    return ev


# ---------------- 命令 ----------------
def cmd_check(T):
    bad = 0
    names = {s["n"] for s, _, _ in T.spans}
    for tab in ("SPEC", "CARD_BG", "CLIPS", "LABEL_NOTE", "CARD_EN"):
        stray = sorted(k for k in getattr(C, tab) if k not in names)
        if stray:                     # SPEC["5"] 写成了 "5"，稿子里是 "05"：原来静默不生效
            print("  !! %s 里这些镜号稿子里没有：%s" % (tab, "、".join(map(str, stray)))); bad += 1
    for s, a, b in T.spans:
        what, srcs, fn = plan(s, T)
        bad += fn is None
        gone = [os.path.basename(x) for x in srcs if not os.path.exists(x)]      # SPEC 里路径写错，不拦的话要到渲染那一镜才炸
        if gone:
            what += "  !! 源文件不在：" + "、".join(gone); bad += 1
        print(f"  鏡{s['n']:>4} [{s['tag']}] {ts(a)} {b - a:5.1f}s  {what}")
    mus = P(C.MUS_DIR)
    for k in sorted(T.segspan):
        n = len([f for f in (os.listdir(mus) if os.path.isdir(mus) else [])
                 if re.match(r"%s_段%d_\d+\.mp3$" % (re.escape(C.MUS_PREFIX), k), f)])
        print(f"  配乐 段{k}：{n} 条" + ("  !! 没有" if not n else ""))
        bad += not n
    print("章节：" + "；".join(f"{int(a) // 60}:{int(a) % 60:02d} {ch}" for a, ch in T.chapters))
    print("没有缺的。" if not bad else "!! 有 %d 处缺东西，见上面带 !! 的行。" % bad)
    sys.exit(1 if bad else 0)


def cmd_srt(T, out):
    write_srt(os.path.join(out, C.NAME + ".srt"), T.subs)
    write_chapters(os.path.join(out, C.NAME + "_章节时间码.txt"), T.chapters)
    print("SRT %d 条、章节 %d 条 → %s" % (len(T.subs), len(T.chapters), out))


def cmd_tsv(shots):
    p = os.path.join(C.PROJ, "build", "_shots.tsv")
    with io.open(p, "w", encoding="utf-8") as f:
        for s in shots:
            row = [s["n"], s["tag"], "%.1f" % s["secs"], s["chapter"] or "",
                   s["desc"] + ("（詩）" if s["poem"] else ""), s["vo"]["txt"] if s["vo"] else ""]
            f.write("\t".join(row) + "\n")
    print("%d 镜 → %s" % (len(shots), p))


def cmd_gate2(T, out):
    name = C.GATE2_NAME or C.NAME + "_门禁二"
    vo = os.path.join(out, "_vo.f32")
    np.concatenate(T.audio).tofile(vo)
    keep, C.FINAL_LUFS = C.FINAL_LUFS, None
    mix(vo, None, T.segspan, T.total, os.path.join(out, name + ".m4a"), "192k")
    C.FINAL_LUFS = keep
    os.remove(vo)
    styles = "\n".join([
        f"Style: Info,{C.SUB_FONT},34,&H00A0A0A0,&H00A0A0A0,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,0,0,7,90,90,70,1",
        f"Style: Desc,{C.SUB_FONT},30,&H00787878,&H00787878,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,90,860,125,1",
        f"Style: Big,{C.KAI_NAME},96,&H00E6E6E6,&H00E6E6E6,&H00000000,&H00000000,0,0,0,0,100,100,6,0,1,0,0,5,200,200,0,1",
        f"Style: Sub,{C.SUB_FONT},54,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,0,2,200,200,90,1",
        f"Style: Poem,{C.KAI_NAME},70,&H00F2F2F2,&H00F2F2F2,&H00303030,&H00000000,0,0,0,0,100,100,0,0,1,1.5,0,8,0,0,0,1"])
    ev = []
    for a, b, top, d in T.info:
        ev.append(f"Dialogue: 0,{ts(a)},{ts(b)},Info,,0,0,0,,{esc(top)}")
        ev.append(f"Dialogue: 0,{ts(a)},{ts(b)},Desc,,0,0,0,,{esc(d)}")
    ev += overlay_events(T)
    ev += [f"Dialogue: 2,{ts(a)},{ts(b)},Sub,,0,0,0,,{esc(line)}" for a, b, line in T.subs]
    io.open(os.path.join(out, "_g2.ass"), "w", encoding="utf-8-sig").write(ASS_HEAD % (C.W, C.H, styles) + "\n".join(ev) + "\n")
    write_srt(os.path.join(out, name + ".srt"), T.subs)
    write_chapters(os.path.join(out, "章节时间码.txt"), T.chapters)
    os.chdir(out)
    run(["-f", "lavfi", "-i", f"color=c=0x141414:s={C.W}x{C.H}:r=10:d={T.total:.2f}", "-i", name + ".m4a", "-vf", "ass=_g2.ass",
         "-c:v", "libx264", "-preset", "fast", "-crf", "26", "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", name + ".mp4"])
    print("GATE2_DONE →", os.path.join(out, name + ".mp4"))


def cmd_render(T, out, part=None, allow_missing=False):
    """part=None 出全片；part=k 出第 k 部分预览。镜的成品两者共用 _tmp_final/。"""
    tmp = os.path.join(out, "_tmp_final")
    os.makedirs(tmp, exist_ok=True)
    if part is None:
        t0, t1, segspan, name, tag = 0.0, T.total, T.segspan, C.NAME, "final"
        pick = lambda s: True
    else:
        if part not in T.segspan:
            die("没有第 %d 部分（有：%s）" % (part, "、".join(str(k) for k in sorted(T.segspan))))
        t0, t1 = T.segspan[part]
        segspan, name, tag = {part: [t0, t1]}, "%s_第%d部分_预览" % (C.NAME, part), "part%d" % part
        pick = lambda s: s["seg"] == part
    segs = render_shots(T, pick, tmp, allow_missing=allow_missing, t0=0.0)   # 全片的帧网格，分部预览和全片共用同一份成品
    for kind, col in (("v", 0), ("a", 1)):
        with io.open(os.path.join(tmp, f"{tag}_{kind}.txt"), "w", encoding="utf-8") as f:
            f.writelines("file '%s'\n" % x[col].replace("\\", "/") for x in segs)
    run(["-f", "concat", "-safe", "0", "-i", os.path.join(tmp, tag + "_v.txt"), "-c", "copy", os.path.join(tmp, tag + "_v.mp4")])
    amb = os.path.join(tmp, tag + "_amb.wav")
    run(["-f", "concat", "-safe", "0", "-i", os.path.join(tmp, tag + "_a.txt"), "-c", "pcm_s16le", amb])
    vo = os.path.join(tmp, tag + "_vo.f32")
    np.concatenate(T.audio)[int(round(t0 * C.SR)):int(round(t1 * C.SR))].tofile(vo)
    m4a = os.path.join(tmp, tag + "_mix.m4a")
    mix(vo, amb, segspan, t1, m4a)
    styles = "\n".join([
        f"Style: Big,{C.KAI_NAME},96,&H00E6E6E6,&H00E6E6E6,&H00000000,&H00000000,0,0,0,0,100,100,6,0,1,0,0,5,200,200,0,1",
        f"Style: Poem,{C.KAI_NAME},70,&H00F2F2F2,&H00F2F2F2,&H00141414,&H96000000,0,0,0,0,100,100,0,0,1,3.2,2.5,8,0,0,0,1"])
    io.open(os.path.join(tmp, tag + ".ass"), "w", encoding="utf-8-sig").write(
        ASS_HEAD % (C.W, C.H, styles) + "\n".join(overlay_events(T, t0, t1)) + "\n")
    write_srt(os.path.join(out, name + ".srt"), [(a - t0, b - t0, x) for a, b, x in T.subs if t0 - 1e-6 <= a < t1])
    if part is None:
        write_chapters(os.path.join(out, name + "_章节时间码.txt"), T.chapters)
    final = os.path.join(out, name + ".mp4")
    os.chdir(tmp)
    run(["-i", tag + "_v.mp4", "-i", tag + "_mix.m4a", "-vf", "ass=%s.ass" % tag, "-c:v", "libx264", "-preset", "slow", "-crf", "18",
         "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", "-movflags", "+faststart", final])
    print("FINAL_DONE →" if part is None else "PART_DONE →", final)


EN_TRIM = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,"
           "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.12,areverse")


def en_chunks(text, mx=84):
    """按句切，过长的句子在逗号/分号处再切；每块 ≤ mx 字符（两行字幕）。"""
    out = []
    for s in (x.strip() for x in re.findall(r'[^.?!:;]+[.?!:;]+["”]?\s*|[^.?!:;]+$', text)):
        if not s:
            continue
        if out and len(out[-1]) + 1 + len(s) <= 42:
            out[-1] += " " + s; continue
        while len(s) > mx:
            cut = max(s.rfind(", ", 0, mx), s.rfind("; ", 0, mx), s.rfind(" — ", 0, mx))
            if cut < 20:
                cut = s.rfind(" ", 0, mx)
            out.append(s[:cut + 1].strip()); s = s[cut + 1:].strip()
        out.append(s)
    j = 0
    while j < len(out):                      # 太短的块并进下一块，免得一闪而过
        if len(out[j]) < 16 and j + 1 < len(out) and len(out[j]) + 1 + len(out[j + 1]) <= mx:
            out[j:j + 2] = [out[j] + " " + out[j + 1]]
        else:
            j += 1
    if len(out) > 1 and len(out[-1]) < 16 and len(out[-2]) + 1 + len(out[-1]) <= mx:
        out[-2:] = [out[-2] + " " + out[-1]]
    return out


def wrap2(s, w=42):
    if len(s) <= w or " " not in s:
        return s
    i = min((k for k, c in enumerate(s) if c == " "), key=lambda k: abs(k - len(s) // 2))
    return s[:i] + "\n" + s[i + 1:]


def cmd_en(T, shots, out, check_only):
    """英文轨：只碰音频。每条英文从同一镜中文旁白的起点开始念，可用长度＝到下一条中文起点前 MARGIN 秒；
    超了先 atempo（≤TEMPO_MAX），再超就报出来改稿。配乐、环境声、侧链、响度都和中文轨同一套。"""
    en_src = io.open(P(C.SCRIPT_EN), encoding="utf-8").read()
    en_src = en_src.split("---", 1)[1] if "---" in en_src else en_src
    en_txt = {"VO_" + k if not k.startswith("VO_") else k: t for k, t in re.findall(r"^(\w+)\.\s+(.+\S)\s*$", en_src, re.M)}
    items = T.items
    for i, it in enumerate(items):
        nxt = items[i + 1]["start"] if i + 1 < len(items) else T.total - 1.5
        it["room"] = nxt - it["start"] - C.MARGIN
    bad, rows = [], []
    for it in items:
        p = os.path.join(P(C.VO_EN_DIR), it["id"] + ".mp3")
        if not os.path.exists(p):
            bad.append(it["id"] + " 缺音频"); continue
        if it["id"] not in en_txt:
            bad.append(it["id"] + " 英文稿里没有这一条"); continue
        a = load(p, EN_TRIM); L = len(a) / C.SR
        r = L / it["room"]
        it.update(audio=a, len=L, ratio=r)
        rows.append(f"{it['id']} 镜{it['n']:>4} 槽 {it['room']:5.2f}s 英 {L:5.2f}s ×{r:.3f} "
                    + ("" if r <= 1 else ("atempo" if r <= C.TEMPO_MAX else "!! 超槽，改稿")))
        if r > C.TEMPO_MAX:
            bad.append(f"{it['id']} 超 {L - it['room'] * C.TEMPO_MAX:.2f}s（{len(en_txt[it['id']].split())} 词）")
    if check_only or bad:
        print("\n".join(rows))
        rs = [it["ratio"] for it in items if "ratio" in it]
        if rs:
            print(f"\n全片 {T.total:.1f}s；英文 {sum(it.get('len', 0) for it in items):.1f}s / 槽 {sum(it['room'] for it in items):.1f}s；"
                  f"中位 ×{np.median(rs):.3f}，>1 的 {sum(r > 1 for r in rs)} 条")
        if bad:
            print("要改：\n  " + "\n  ".join(bad))
        sys.exit(1 if bad else 0)
    tmp = os.path.join(out, "_tmp_final")
    amb = os.path.join(tmp, "final_amb.wav")
    if not os.path.isfile(amb):
        die("没有 %s —— 英文轨借全片的环境声，先跑 final" % amb)
    buf = np.zeros(int(T.total * C.SR) + C.SR, np.float32)
    subs = []
    for it in items:
        a = it["audio"]
        if it["ratio"] > 1:
            w = os.path.join(tmp, "_en_tmp.wav")
            a.astype(np.float32).tofile(w + ".f32")
            run(["-f", "f32le", "-ar", str(C.SR), "-ac", "1", "-i", w + ".f32", "-af", f"atempo={it['ratio']:.4f}", w])
            a = load(w); os.remove(w); os.remove(w + ".f32")
        i0 = int(it["start"] * C.SR)
        buf[i0:i0 + len(a)] += a
        L = len(a) / C.SR
        parts = en_chunks(en_txt[it["id"]])
        w = [max(8, len(x)) for x in parts]
        acc = it["start"]
        for x, k in zip(parts, w):
            d = L * k / sum(w)
            subs.append((acc, acc + d, wrap2(x))); acc += d
    vo = os.path.join(tmp, "final_vo_en.f32")
    buf[:int(T.total * C.SR)].tofile(vo)
    m4a = os.path.join(out, C.NAME + "_音轨_eng.m4a")
    mix(vo, amb, T.segspan, T.total, m4a)
    cards = []
    for s, a, b in T.spans:
        if s["n"] in C.CARD_EN:
            cards.append((a + (0.8 if s is shots[-1] else 0.3), b - 0.3, C.CARD_EN[s["n"]]))
    write_srt(os.path.join(out, C.NAME + ".en.srt"), sorted(subs + cards))
    write_chapters(os.path.join(out, C.NAME + "_章节时间码_en.txt"), T.chapters, C.CHAPTER_EN)
    print("EN_DONE", m4a, f"{dur(m4a):.3f}s", "字幕", len(subs) + len(cards), "条")


def main(argv):
    def opt(name):
        if name in argv:
            i = argv.index(name); v = argv[i + 1]; del argv[i:i + 2]; return v
        return None
    proj, cfg, out = opt("--proj"), opt("--config"), opt("--out")
    allow = "--allow-missing" in argv
    argv = [a for a in argv if a != "--allow-missing"]
    if not argv or argv[0] not in ("check", "srt", "tsv", "gate2", "shots", "part", "final", "en"):
        sys.exit(__doc__)
    what, rest = argv[0], argv[1:]
    if not proj:
        cwd = os.getcwd()
        proj = os.path.dirname(cwd) if os.path.basename(cwd) == "build" else cwd
    proj = os.path.abspath(proj)
    cfg = os.path.abspath(cfg or os.path.join(proj, "build", "film_config.py"))
    if not os.path.isfile(cfg):
        die("没有配置 %s（照 references/long-film.md 写一份，或用 episode.py new --type long 铺）" % cfg)
    load_config(cfg, proj)
    out = os.path.abspath(out or os.path.join(proj, "门禁二" if what == "gate2" else "成片"))
    if what not in ("check", "tsv"):
        os.makedirs(out, exist_ok=True)
    shots = read_shots()
    T = timeline(shots)
    if what == "check":
        cmd_check(T)
    elif what == "srt":
        cmd_srt(T, out)
    elif what == "tsv":
        cmd_tsv(shots)
    elif what == "gate2":
        cmd_gate2(T, out)
    elif what == "shots":
        if not rest:
            die("shots 后面给镜号")
        unknown = set(rest) - {s["n"] for s in shots}
        if unknown:
            die("稿子里没有这些镜号：%s" % "、".join(sorted(unknown)))
        tmp = os.path.join(out, "_tmp_final"); os.makedirs(tmp, exist_ok=True)
        render_shots(T, lambda s: s["n"] in rest, tmp, check_names=True, allow_missing=True)
        print("CHECK_DONE →", tmp)
    elif what == "part":
        if not rest or not rest[0].isdigit():
            die("part 后面给部分号")
        cmd_render(T, out, int(rest[0]), allow)
    elif what == "final":
        cmd_render(T, out, None, allow)
    else:
        cmd_en(T, shots, out, bool(rest) and rest[0] == "check")


if __name__ == "__main__":
    main(sys.argv[1:])
