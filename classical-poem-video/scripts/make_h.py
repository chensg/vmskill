# -*- coding: utf-8 -*-
"""
古诗词短片 · 横版构建脚本模板 (1920x1080)

命令：check / prep / probe / trace / a / motion / b / c / still / measure / cover / all
先跑 check，再跑 prep（自带 probe）和 trace，最后 a→b→c，
交付前 still（用眼睛看）、measure（量字幕底）、motion（量运动）都要跑。

三条开工前定死的轴（每条都有对应自检）：
  MOTION      运镜还是静帧，可逐镜覆盖 dict(..., motion="static")
  MUSIC_MODE  生成 / 公版 / 没有（横版没有音效轨，'none' = 成片无音轨）
  IMG_SOURCE  按任务书生成 / 自己找（找来的必须登记来源，check 会拦）

三个测量命令量的是**不同区域**，不能互相替代：
  probe  整张图 / 整条字幕带  —— 定位问题，报警常是误报
  trace  镜头真正经过的那一段 —— 出图阶段就能判，缺图会跳过
  measure 渲染出来的无字 master —— 成片阶段验，把上采样和转场都算进去

与竖版的三处结构差别：
  1. 字幕**横排在底部**，配底部暗渐变；竖版是右侧竖排
  2. 运镜以**左右横移和推拉**为主；竖版以上下摇为主
  3. 片尾诗文页八列竖排**居中**；竖版靠右
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ================= 这一支的内容 =================
TITLE, AUTHOR = "登高", "唐·杜甫"
OUT_NAME = "成片_横版.mp4"
COVER_NAME = "封面_横版.png"
COVER_FROM = 6

# ================= 明暗极性 =================
# 横版的图常常是"上白下暗"的结构，所以标题和正文用不同极性是常态：
# 标题落在亮处(墨色)、正文落在底部暗带(白字)。拿不准先跑 probe 看实测亮度。
POLARITY = "light_on_dark"          # 正文
TITLE_POLARITY = "dark_on_light"    # 标题

# 底部字幕带的暗渐变。probe 会报告每镜底部两行的亮度：
# 亮的镜头(白混凝土、惨白的天)可能到 180+，暗的只有 30 上下。
# 按最亮的那几镜定强度，配合不透明黑描边。
SCRIM_ALPHA, SCRIM_Y0, SCRIM_SOFT, SCRIM_POW = 0.72, 760, 320, 1.45

# ================= 全局参数 =================
W, H, FPS = 1920, 1080, 30
PREP = (3840, 2160)
UP = (5760, 3240)
XFADE = 1.2
FADE_IN, FADE_OUT = 2.0, 5.0
FADE_COLOR = "black"

SRC = os.path.join("..", "素材")
FONTS = os.path.join("..", "fonts")

# ================= 运动：运镜还是静帧 =================
# 全片默认，任何一镜可写 motion="static" / "kenburns" 覆盖。
# **静帧要显式声明，不能靠"z 起止写成一样"隐式表示** —— 那样的话"写了位移却
# 没给足缩放"这个最贵的 bug 就变成一个合法配置，check 再也拦不住它。
# check_moves 两边都拦（标 static 却有行程 / 标 kenburns 却原地不动），
# 渲完 motion 命令在成片上反过来验。
MOTION = "kenburns"
MOTION_MIN = 4.0            # 运镜镜的下限：渲出来的首尾帧平均绝对差
MOTION_STATIC_MAX = 0.6     # 静帧镜的上限：真静止应该接近 0

# ================= 配乐：生成 / 公版 / 没有 =================
# 见 references/music.md。**横版模板没有音效轨也没有旁白**，所以
# MUSIC_MODE='none' 在这里意味着成片完全无声（会出一条无音轨的 mp4）。
MUSIC_MODE = "generated"    # "generated" | "public_domain" | "none"
MUSIC = os.path.join(SRC, "00_music_main.mp3")
MUSIC_GAIN = -9.0
MUSIC_IN = 0.0              # 用 ebur128 量出配乐进入正常体量的时刻，从那里切入
MUSIC_FADE_IN = 0.8
# 公版录音必填：**录音权和作品权是两回事**，check 会拦。
MUSIC_CREDIT = dict(work="", performer="", source="", license="", url="")

# ================= 素材来源：任务书生成 / 自己找 =================
# "found" 时每张必须登记来源与授权，check 会拦。见 references/sourcing.md。
IMG_SOURCE = "generated"    # "generated" | "found"
CREDITS = {}                # {"img01.png": dict(title=, holder=, source=, license=, url=)}

TARGET_I, TARGET_TP = -15.0, -1.5
READ_PER_CHAR, READ_BASE = 0.45, 1.8

# 多摄影师的图库实拍必须重手统一(甚至黑白与彩色混杂)，否则串起来是 PPT 换页。
# 方向：往近单色推、冷调，但保住高光里的暖(夜里亮着的窗那类"体温"洗掉就没了)。
GRADE = (
    "eq=saturation=0.55:contrast=1.06:brightness=-0.012:gamma=1.01,"
    "colorbalance=rs=-0.020:gs=-0.006:bs=0.030:"
    "rm=-0.010:gm=-0.004:bm=0.018:rh=0.014:gh=0.004:bh=-0.010,"
    "curves=all='0/0.030 0.25/0.235 0.75/0.740 1/0.965'"
)

# zoom=1.0 表示用满原图宽度裁 16:9。裁后短边 ≥ 1620（成片 1080 的 1.5 倍）。
CLIPS = [
    dict(src="01_xxx.jpg", zoom=1.00, cx=0.50, cy=0.50, tweak=""),
]

# 焦点只能落在 [1/(2z), 1-1/(2z)]，走 d 的行程需 z >= 1/(1-d)。
# 横版尤其容易在横移上翻车：想横移 22% 就得 z>=1.32，1.30 都不够。
SHOTS = [
    dict(dur=14.0, z=(1.10, 1.30), f0=(0.50, 0.52), f1=(0.50, 0.46)),
]

LINES = [
    (1.6, 6.8, TITLE, "T"),
    (3.2, 6.8, AUTHOR, "TS"),
]

POEM = []
POEM_IN, POEM_OUT = 82.0, 93.6

SUB_Y = 972                 # 横排正文中心（离底边约 108）
SUB_ROW_GAP = 84            # 四言拆两行时的行距
TITLE_Y, TITLE_SUB_Y = 452, 606
POEM_GAP, POEM_CX, POEM_CY = 130, 960, 520

# 正文里写了逗号的，按逗号拆成**两行**（上行在前），逗号本身不上屏。
# 这是给四言用的：《观沧海》《短歌行》这类两句一组、一组一镜。
# 拆两行之后可读下限按含逗号的九字算 = 9*0.45+1.8 = 5.85 秒，
# 而且底部字幕带要留出两行的高度（比一行多约 SUB_ROW_GAP），选图时就得按这个留。


# ================= 以下一般不用改 =================
def run(args, desc):
    print("\n>>> " + desc)
    if subprocess.run(args).returncode != 0:
        sys.exit("!!! 失败: " + desc)


def motion_of(n):
    """镜 n(1 起) 是运镜还是静帧。逐镜的 motion= 覆盖全局 MOTION。"""
    return SHOTS[n - 1].get("motion", MOTION)


def is_static(n):
    return motion_of(n) == "static"


def music_on():
    return MUSIC_MODE != "none"


def xf(i):
    """镜 i(0 起) 转到下一镜用的溶解时长。某一镜写 xf=... 就覆盖全局 XFADE。

    转场时长不必是常数 —— 一支片子十几次一模一样的溶解会把节奏抹平。可以：
      组诗里首与首之间给 2.0~2.5s 长溶解当"翻页"；
      情绪陡转处(比如从最艳的花切到最冷的山)给 0.6s 短切；
      其余留 1.2s。
    不写 xf 时行为与原来完全一致。"""
    return SHOTS[i].get("xf", XFADE)


def total_len():
    return sum(s["dur"] for s in SHOTS) - sum(xf(i) for i in range(len(SHOTS) - 1))


def shot_starts():
    t, out = 0.0, []
    for i, s in enumerate(SHOTS):
        out.append(t); t += s["dur"] - xf(i)
    return out


def cut_points():
    st = shot_starts()
    return [st[i] + SHOTS[i]["dur"] - xf(i) / 2 for i in range(len(SHOTS) - 1)]


def shot_of(t):
    """时刻 t 落在第几镜(1 起)。"""
    n = 1
    for i, s in enumerate(shot_starts(), 1):
        if t >= s - 1e-6:
            n = i
    return n


def check_xfades():
    """转场时长本身的合法性。写了每镜 xf 之后这条才有意义。"""
    bad = []
    for i in range(len(SHOTS) - 1):
        x = xf(i)
        if x <= 0:
            bad.append("镜 %d 的转场 %.2fs 必须大于 0" % (i + 1, x))
        elif x > min(SHOTS[i]["dur"], SHOTS[i + 1]["dur"]) - 1e-6:
            bad.append("镜 %d 的转场 %.2fs 不短于相邻镜头(%.1fs/%.1fs)，xfade 会吃掉整镜"
                       % (i + 1, x, SHOTS[i]["dur"], SHOTS[i + 1]["dur"]))
    return bad


def trace():
    """量镜头**真正经过的区域** —— 补在 probe 和 measure 之间的那一步。

    为什么需要它：probe 量的是整张图/整条字幕带从左到右，而镜头只扫过其中一段，
    所以 probe 的报警**经常是误报**。measure 准，但要等 a+b 跑完才有 master.mp4。
    trace 在出图阶段就能判一张图能不能用。

    量两处：每条正文字幕实际扫过的那一块；每一镜**落幅那一帧**的平坦度
    （规则说的是落幅，不是整张图）。

    跑完拿它和 measure 对一遍：两者应该逐条只差几级。**对不上不是字幕的问题，
    是运镜没走在你以为的位置上**，那比字幕糊了严重得多。
    """
    starts = shot_starts()
    dark = POLARITY == "dark_on_light"
    ink = 40 if dark else 242
    GW, GH = 1288, 724
    cache = {}

    def gray(i):
        if i in cache:
            return cache[i]
        f = "img%02d.png" % i
        if not os.path.exists(f):                       # prep 还没跑就直接读原图
            f = os.path.join(SRC, CLIPS[i - 1]["src"])
            if not os.path.exists(f):
                cache[i] = None; return None
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", f, "-vf",
                              "scale=%d:%d:flags=area,format=gray" % (GW, GH),
                              "-f", "rawvideo", "-"], capture_output=True).stdout
        cache[i] = raw if len(raw) == GW * GH else None
        return cache[i]

    def box(n, tl, x0o, x1o, y0o, y1o):
        s = SHOTS[n - 1]
        p = min(1.0, max(0.0, tl / s["dur"]))
        z = s["z"][0] + (s["z"][1] - s["z"][0]) * p
        half = 1 / (2 * z)
        fx = min(max(s["f0"][0] + (s["f1"][0] - s["f0"][0]) * p, half), 1 - half)
        fy = min(max(s["f0"][1] + (s["f1"][1] - s["f0"][1]) * p, half), 1 - half)
        span = 1.0 / z
        return (fx - half + x0o / W * span, fx - half + x1o / W * span,
                fy - half + y0o / H * span, fy - half + y1o / H * span)

    def stat(raw, b):
        x0, x1 = int(b[0] * GW), max(int(b[0] * GW) + 1, int(b[1] * GW))
        y0, y1 = int(b[2] * GH), max(int(b[2] * GH) + 1, int(b[3] * GH))
        x0, x1, y0, y1 = max(0, x0), min(GW, x1), max(0, y0), min(GH, y1)
        v = sorted(raw[y * GW + x] for y in range(y0, y1) for x in range(x0, x1))
        return sum(v) / len(v), v[int(len(v) * 0.01)] if dark else v[int(len(v) * 0.99)]

    print("\n=== 字幕实走轨迹（起/中/止，均值/1%%分位；判据：离字色 %d 至少 50 级）===" % ink)
    worst = []
    for st, en, txt, sty in LINES:
        if sty != "M":
            continue
        n = shot_of((st + en) / 2)
        raw = gray(n)
        if raw is None:
            print("  %-11s 镜%-3d (缺图)" % (txt, n)); continue
        x0, x1, y0, y1 = sub_box(txt)
        out, xs = [], []
        for t in (st + 0.2, (st + en) / 2, en - 0.2):
            b = box(n, t - starts[n - 1], x0, x1, y0, y1)
            out.append(stat(raw, b)); xs.append((b[0], b[1]))
        w = min(o[1] for o in out) if dark else max(o[1] for o in out)
        worst.append((w, txt, n))
        flag = "" if abs(w - ink) >= 50 else "   << 不够，考虑改极性或换图"
        # 打**扫过的并集**：横版多是左右走的，只打"起帧框左→止帧框右"会低估行程
        print("  %-11s 镜%-3d 扫过 x %.3f~%.3f  " % (txt, n, min(a for a, _ in xs),
                                                     max(b for _, b in xs))
              + "  ".join("%3.0f/%3d" % o for o in out) + flag)
    if worst:
        m, who, n = min(worst) if dark else max(worst)
        print("\n  最差处的底 %d，出现在『%s』(镜 %d)，离字色 %d 差 %d 级 —— %s"
              % (m, who, n, ink, abs(m - ink), "够用" if abs(m - ink) >= 50 else "不够"))

    print("\n=== 落幅平坦度（只量镜头真正停住的那一帧，16x9 网格）===")
    for n in range(1, len(SHOTS) + 1):
        raw = gray(n)
        if raw is None:
            print("  镜%-3d (缺图)" % n); continue
        b = box(n, SHOTS[n - 1]["dur"], 0, W, 0, H)
        gx0, gx1 = int(b[0] * GW), int(b[1] * GW)
        gy0, gy1 = int(b[2] * GH), int(b[3] * GH)
        cells, flat = [], 0
        for r in range(9):
            row = []
            for c in range(16):
                sx0 = gx0 + (gx1 - gx0) * c // 16
                sx1 = max(sx0 + 1, gx0 + (gx1 - gx0) * (c + 1) // 16)
                sy0 = gy0 + (gy1 - gy0) * r // 9
                sy1 = max(sy0 + 1, gy0 + (gy1 - gy0) * (r + 1) // 9)
                v = [raw[y * GW + x] for y in range(sy0, min(GH, sy1))
                     for x in range(sx0, min(GW, sx1))]
                row.append(sum(v) / len(v))
            cells.append(row)
            if max(row) - min(row) < 12:
                flat += 1
        allv = [v for row in cells for v in row]
        rng = max(allv) - min(allv)
        note = ""
        if POEM and n == len(SHOTS):
            note = "  (诗文页，本来就该是空的且几乎静止 —— 不适用)"
        elif flat >= 3:
            note = "  << %d 行几乎无明暗变化，这一镜会像静止" % flat
        elif rng < 25:
            note = "  << 整帧极差只有 %.0f，运镜会看不出来" % rng
        print("  镜%-3d %-14s 整帧极差 %3.0f  平坦行 %2d/9%s"
              % (n, CLIPS[n - 1]["src"][:14], rng, flat, note))


def prep():
    for i, c in enumerate(CLIPS, 1):
        src = os.path.join(SRC, c["src"])
        if not os.path.exists(src):
            sys.exit("!!! 缺素材: " + src)
        z, cx, cy = c["zoom"], c["cx"], c["cy"]
        crop = ("crop=w='min(iw/%.6f,ih*16/9)':h='min(ih,iw/%.6f*9/16)':"
                "x='clip(%.6f*iw-out_w/2,0,iw-out_w)':"
                "y='clip(%.6f*ih-out_h/2,0,ih-out_h)'" % (z, z, cx, cy))
        vf = crop + "," + GRADE + ("," + c["tweak"] if c["tweak"] else "")
        vf += ",scale=%d:%d:flags=lanczos,setsar=1" % PREP
        run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", vf,
             "-frames:v", "1", "img%02d.png" % i],
            "prep %d/%d  %s" % (i, len(CLIPS), c["src"]))
    probe()


def probe():
    """16x9 亮度网格 + 底部字幕带 + 第一镜的标题位。"""
    print("\n=== 亮度网格 (0-255, 16 列 x 9 行) ===")
    for i in range(1, len(CLIPS) + 1):
        f = "img%02d.png" % i
        if not os.path.exists(f):
            print("%s  (未生成)" % f); continue
        p = subprocess.run(["ffmpeg", "-v", "error", "-i", f, "-vf",
                            "scale=16:9:flags=area,format=gray", "-f", "rawvideo", "-"],
                           capture_output=True)
        g = p.stdout[:144]
        if len(g) < 144:
            print("%s  (读取失败)" % f); continue
        print("\n%s  (%s)" % (f, CLIPS[i - 1]["src"]))
        for r in range(9):
            print("   " + " ".join("%3d" % v for v in g[r * 16:(r + 1) * 16]))
        band = [g[r * 16 + c] for r in (7, 8) for c in range(16)]
        avg, hi = sum(band) / len(band), max(band)
        note = "  << 偏亮，白字会糊" if (POLARITY == "light_on_dark" and hi > 190) else ""
        print("   底部字幕带 YAVG=%.0f  峰值=%d%s" % (avg, hi, note))
        if i == 1:
            mid = [g[r * 16 + c] for r in (3, 4, 5) for c in range(5, 11)]
            m_hi = max(mid)
            print("   片头标题位(中部) YAVG=%.0f  最亮=%d%s"
                  % (sum(mid) / len(mid), m_hi,
                     "  << 亮底，标题该用墨色" if m_hi > 190 else ""))
        flat = [r for r in range(9)
                if max(g[r * 16:(r + 1) * 16]) - min(g[r * 16:(r + 1) * 16]) < 12]
        if len(flat) >= 3:
            print("   注意：第 %s 行几乎无明暗变化，落幅别停在这里"
                  % ",".join(str(r) for r in flat))


def check_moves():
    bad = []
    for i, s in enumerate(SHOTS, 1):
        z0, z1 = s["z"]
        for (fx, fy), z, w in ((s["f0"], z0, "起"), (s["f1"], z1, "止")):
            lo, hi = 1 / (2 * z), 1 - 1 / (2 * z)
            for v, ax in ((fx, "x"), (fy, "y")):
                if not (lo - 1e-6 <= v <= hi + 1e-6):
                    bad.append("镜 %d %s幅 f%s=%.3f 超出 z=%.2f 的可达范围 [%.3f,%.3f]"
                               % (i, w, ax, v, z, lo, hi))
        want = abs(s["f1"][1] - s["f0"][1]) + abs(s["f1"][0] - s["f0"][0])
        zmax = max(z0, z1); can = max(0.0, 1 - 1 / zmax)

        # 运动方式和参数必须互相印证，不去猜哪个是真的
        m = motion_of(i)
        moving = want > 1e-6 or abs(z1 - z0) > 1e-6
        if m not in ("kenburns", "static"):
            bad.append("镜 %d 的 motion=%r 不认识，只能是 'kenburns' 或 'static'" % (i, m))
        elif m == "static" and moving:
            bad.append("镜 %d 标了 static 却写了行程 (z %.2f→%.2f, f %s→%s) —— "
                       "静帧镜的 z 和 f 起止必须完全一致"
                       % (i, z0, z1, s["f0"], s["f1"]))
        elif m == "kenburns" and not moving:
            bad.append("镜 %d 标了 kenburns 却起止完全一样，渲出来就是一张静帧 —— "
                       "要么给它行程，要么老实标 motion='static'" % i)

        if want > can + 1e-6:
            bad.append("镜 %d 想走 %.0f%% 行程，但 z 最大只到 %.2f，实际只能走 %.0f%% "
                       "(需要 z>=%.2f)" % (i, want * 100, zmax, can * 100,
                                           1 / max(1e-6, 1 - want)))
    return bad


def selftest_moves():
    """回归：每一类错误各造一个，检查必须报警。只验"现在通过"等于没验。"""
    if not SHOTS:
        return True
    keep = [dict(s) for s in SHOTS]
    base = len(check_moves())

    def case(name, i, patch):
        SHOTS[i - 1] = dict(keep[i - 1], **patch)
        n = len(check_moves())
        SHOTS[i - 1] = dict(keep[i - 1])
        print("回归自测: %-24s 多报 %d 条 —— %s"
              % (name, n - base, "对" if n > base else "**检查失效了**"))
        return n > base

    moving = next((i for i, s in enumerate(SHOTS, 1)
                   if abs(s["f1"][0] - s["f0"][0]) + abs(s["f1"][1] - s["f0"][1]) > 1e-6
                   or abs(s["z"][1] - s["z"][0]) > 1e-6), None)
    ok = []
    if moving:
        ok.append(case("有行程的镜标成 static", moving, dict(motion="static")))
    z, f = keep[0]["z"][0], keep[0]["f0"]
    ok.append(case("原地不动的镜标成 kenburns", 1,
                   dict(motion="kenburns", z=(z, z), f0=f, f1=f)))
    ok.append(case("motion 写错字", 1, dict(motion="ken_burns")))
    print("          当前配置 %d 条 —— %s" % (base, "对" if base == 0 else "有问题要处理"))
    return all(ok) and len(check_moves()) == base


def check_credits():
    """素材来源与授权的登记。**只对"自己找来的"素材是硬约束。**

    CC-BY 要求署名；"公有领域"对**作品**成立不等于对**某一次录音或翻拍**成立。
    这类错误成片、审核、发布都不会拦，要到被投诉才知道，所以放进 check。
    """
    bad = []
    need = ("title", "holder", "source", "license", "url")
    if IMG_SOURCE not in ("generated", "found"):
        bad.append("IMG_SOURCE=%r 不认识，只能是 'generated' 或 'found'" % IMG_SOURCE)
    elif IMG_SOURCE == "found":
        for c in CLIPS:
            e = CREDITS.get(c["src"])
            if not e:
                bad.append("素材 %s 没登记来源（IMG_SOURCE='found' 时每张都要）" % c["src"])
            else:
                miss = [k for k in need if not str(e.get(k, "")).strip()]
                if miss:
                    bad.append("素材 %s 的来源登记缺 %s" % (c["src"], "/".join(miss)))
    if MUSIC_MODE not in ("generated", "public_domain", "none"):
        bad.append("MUSIC_MODE=%r 不认识，只能是 'generated' / 'public_domain' / 'none'"
                   % MUSIC_MODE)
    elif MUSIC_MODE == "public_domain":
        miss = [k for k in ("work", "performer", "source", "license", "url")
                if not str(MUSIC_CREDIT.get(k, "")).strip()]
        if miss:
            bad.append("公版配乐的 MUSIC_CREDIT 缺 %s —— **录音权和作品权是两回事**"
                       % "/".join(miss))
    return bad


def selftest_credits():
    """回归：把登记抽掉，检查必须报警。"""
    global IMG_SOURCE, MUSIC_MODE, CREDITS, MUSIC_CREDIT
    ki, km, kc, kmc = IMG_SOURCE, MUSIC_MODE, CREDITS, MUSIC_CREDIT
    base = len(check_credits())
    IMG_SOURCE, CREDITS = "found", {}
    a = len(check_credits()) > base
    IMG_SOURCE, CREDITS = ki, kc
    MUSIC_MODE, MUSIC_CREDIT = "public_domain", dict(work="", performer="",
                                                     source="", license="", url="")
    b = len(check_credits()) > base
    MUSIC_MODE, MUSIC_CREDIT = km, kmc
    print("回归自测: 素材标 found 但没登记来源 —— %s" % ("对" if a else "**检查失效了**"))
    print("          配乐标 public_domain 但没填授权 —— %s" % ("对" if b else "**检查失效了**"))
    return a and b


def motion():
    """量每一镜**渲出来**的首尾帧差：运镜镜要看得出动，静帧镜要真的不动。

    trace 的落幅平坦度是出图阶段的筛子，对暗调图天生爱误报；真正要紧的是
    这一镜从头走到尾画面变了多少 —— 那只能在 shots/ 上量。
    静帧镜反过来判：标了 static 却在动，和运镜镜不动一样是错。
    读不出的镜头**不算通过** —— 跳过之后照样打印"全部对得上"就又造了一个
    不会报警的检查。
    """
    if not os.path.isdir("shots"):
        sys.exit("!!! 还没有 shots/，先跑 a")
    GW, GH = 171, 96

    def frame(f, t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "%.3f" % t, "-i", f,
                              "-frames:v", "1", "-vf",
                              "scale=%d:%d:flags=area,format=gray" % (GW, GH),
                              "-f", "rawvideo", "-"], capture_output=True).stdout
        return raw if len(raw) == GW * GH else None

    print("\n=== 运动实测（渲出来的首尾帧差）===")
    print("    运镜镜判据 均差 >= %.1f 级；静帧镜判据 均差 <= %.1f 级"
          % (MOTION_MIN, MOTION_STATIC_MAX))
    bad, drift, skipped, n_static = [], [], [], 0
    for i, s in enumerate(SHOTS, 1):
        f = "shots/shot%02d.mp4" % i
        if not os.path.exists(f):
            print("  镜%-3d (未渲染)" % i); skipped.append(i); continue
        a, b = frame(f, 0.05), frame(f, max(0.1, s["dur"] - 0.1))
        if a is None or b is None:
            print("  镜%-3d (读不出帧，可能还在渲)" % i); skipped.append(i); continue
        d = sorted(abs(a[k] - b[k]) for k in range(GW * GH))
        mean = sum(d) / len(d)
        flag, how = "", "静帧" if is_static(i) else "运镜"
        if is_static(i):
            n_static += 1
            if mean > MOTION_STATIC_MAX:
                flag = "  << 标了 static 却在动"
                drift.append(i)
        elif mean < MOTION_MIN:
            flag = "  << 肉眼看不出在动，加大 z 跨度或换一张有结构的图"
            bad.append(i)
        print("  镜%-3d %-18s %s 均差 %5.1f  中位 %3d  p90 %3d  最大 %3d%s"
              % (i, CLIPS[i - 1]["src"][:18], how, mean, d[len(d) // 2],
                 d[int(len(d) * 0.9)], d[-1], flag))
    if bad:
        print("\n  %d 镜运镜看不出来: %s" % (len(bad), ", ".join(str(i) for i in bad)))
    if drift:
        print("\n  %d 镜标了静帧却在动: %s" % (len(drift), ", ".join(str(i) for i in drift)))
    if skipped:
        print("\n  !! %d 镜没量到: %s —— **不算通过**，渲完再跑一次"
              % (len(skipped), ", ".join(str(i) for i in skipped)))
    if not bad and not drift and not skipped:
        print("\n  %d 镜全部对得上（运镜 %d 镜看得出动，静帧 %d 镜真的没动）。"
              % (len(SHOTS), len(SHOTS) - n_static, n_static))
    return not bad and not drift and not skipped


def check_timeline():
    total, cuts, starts = total_len(), cut_points(), shot_starts()
    bad, warn = [], []
    for st, en, txt, sty in LINES:
        if sty == "M":
            need = len(txt) * READ_PER_CHAR + READ_BASE
            if en - st < need - 1e-6:
                bad.append("字幕『%s』只有 %.1fs，不足可读下限 %.1fs" % (txt, en - st, need))
        for c in cuts:
            if st - 0.3 < c < en + 0.3:
                bad.append("转场 %.1fs 压到了字幕『%s』" % (c, txt))
        if en > total:
            bad.append("字幕『%s』超出片长" % txt)
    if POEM and POEM_IN < starts[-1]:
        bad.append("诗文页字块早于诗文页镜头起点")
    for c in CLIPS:
        if not os.path.exists(os.path.join(SRC, c["src"])):
            bad.append("缺素材: " + c["src"])
    if not music_on():
        print("配乐: 无（MUSIC_MODE='none'）—— 横版模板没有音效轨也没有旁白，"
              "所以成片会是一条**无音轨**的 mp4")
    elif not os.path.exists(MUSIC):
        warn.append("音乐还没就位")
    else:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "csv=p=0", MUSIC],
                           capture_output=True, text=True)
        try:
            mdur = float(p.stdout.strip()); need = MUSIC_IN + total
            if need > mdur + 1e-3:
                bad.append("音乐不够长: 从 %.1fs 切入需要到 %.1fs，全曲只有 %.1fs"
                           % (MUSIC_IN, need, mdur))
            else:
                print("配乐(%s): 全曲 %.1fs，从 %.1fs 切入，余 %.1fs"
                      % ("生成" if MUSIC_MODE == "generated" else "公版",
                         mdur, MUSIC_IN, mdur - need))
            # 切入余地 = 全曲 - 片长。生成的曲子几乎一定带一段爬坡，余地不够就躲不开。
            # 实测：177.9s 的曲子对 148.2s 的片子只剩 29.6s 余地，怎么挪都有要紧的
            # 落点撞进谷里；换成 245.1s(余 96.9s)之后同一套判据立刻挑得出好点。
            # 公版录音通常远长于片长，这条警不适用。
            if MUSIC_MODE == "generated" and mdur < total * 1.6:
                warn.append("音乐只比片长多 %.0fs（不到片长的 0.6 倍），切入点几乎没得挑。"
                            "下次生成时直接要 >= 片长 x 2.5 的时长" % (mdur - total))
            if MUSIC_MODE == "public_domain":
                warn.append("公版录音：切入点定完要听首尾（乐句边界量不出来），"
                            "底噪和带宽见 references/music.md")
        except ValueError:
            warn.append("读不出音乐时长")
    bad += check_xfades()
    bad += check_moves()
    bad += check_credits()
    ns = sum(1 for n in range(1, len(SHOTS) + 1) if is_static(n))
    print("片长 %.1fs (%d:%04.1f)  镜头 %d  字幕 %d 条  %dx%d"
          % (total, total // 60, total % 60, len(SHOTS), len(LINES), W, H))
    print("运动: %s（静帧 %d 镜 / 运镜 %d 镜）  配乐: %s  素材: %s"
          % ({"kenburns": "运镜", "static": "静帧"}.get(MOTION, MOTION),
             ns, len(SHOTS) - ns,
             {"generated": "生成", "public_domain": "公版", "none": "无"}.get(MUSIC_MODE),
             {"generated": "按任务书生成", "found": "自己找的"}.get(IMG_SOURCE)))
    selftest_moves()
    selftest_credits()
    print("转场落点: " + "  ".join("%.1f" % c for c in cuts))
    print("正文停留: " + "  ".join("%.1f" % (e - s) for s, e, _, t in LINES if t == "M"))
    for w in warn:
        print("提示: " + w)
    if bad:
        print("\n!! 时间轴问题:")
        for b in bad:
            print("   - " + b)
    else:
        print("\n时间轴自检通过。")
    return not bad


def static_vf(s):
    """静帧镜的滤镜链：按 z/f0 裁一个固定取景窗，缩到成片尺寸，不动。

    取景算法和 zoompan 一致（窗宽高各 1/z、窗心在 f、clip 在图内），
    否则 trace 反查的位置会和成片对不上。实测两条路径横向完全对齐、
    纵向差约半个像素（各自在 PREP / UP 尺度上取整），远细于 trace 的网格。
    """
    z, (fx_, fy_) = s["z"][0], s["f0"]
    crop = ("crop=w='iw/%.6f':h='ih/%.6f':"
            "x='clip(%.6f*iw-out_w/2,0,iw-out_w)':"
            "y='clip(%.6f*ih-out_h/2,0,ih-out_h)'" % (z, z, fx_, fy_))
    return (crop + ",scale=%d:%d:flags=lanczos," % (W, H)
            + "vignette=PI/5,setsar=1,format=yuv420p")


def pass_a():
    os.makedirs("shots", exist_ok=True)
    for i, s in enumerate(SHOTS, 1):
        if is_static(i):
            vf, how = static_vf(s), "静帧"
        else:
            d = max(1, int(round(s["dur"] * FPS)) - 1)
            z0, z1 = s["z"]; (x0, y0), (x1, y1) = s["f0"], s["f1"]
            ze = "%.6f+(%.6f)*on/%d" % (z0, z1 - z0, d)
            xe = ("max(0,min(iw-iw/zoom,(%.6f+(%.6f)*on/%d)*iw-(iw/zoom)/2))"
                  % (x0, x1 - x0, d))
            ye = ("max(0,min(ih-ih/zoom,(%.6f+(%.6f)*on/%d)*ih-(ih/zoom)/2))"
                  % (y0, y1 - y0, d))
            vf = ("scale=%d:%d:flags=lanczos," % UP
                  + "zoompan=z='%s':x='%s':y='%s':d=1:s=%dx%d:fps=%d,"
                    % (ze, xe, ye, W, H, FPS) + "vignette=PI/5,setsar=1,format=yuv420p")
            how = "运镜"
        run(["ffmpeg", "-y", "-v", "error", "-stats", "-loop", "1",
             "-framerate", str(FPS), "-t", "%.3f" % s["dur"],
             "-i", "img%02d.png" % i, "-vf", vf, "-c:v", "libx264", "-crf", "12",
             "-preset", "medium", "-pix_fmt", "yuv420p", "shots/shot%02d.mp4" % i],
            "镜头 %d/%d  %.1fs  %s" % (i, len(SHOTS), s["dur"], how))


def pass_b():
    ins = []
    for i in range(1, len(SHOTS) + 1):
        ins += ["-i", "shots/shot%02d.mp4" % i]
    parts, cur, off = [], "[0:v]", 0.0
    for i in range(1, len(SHOTS)):
        off += SHOTS[i - 1]["dur"] - xf(i - 1)
        parts.append("%s[%d:v]xfade=transition=fade:duration=%.3f:offset=%.3f[x%d]"
                     % (cur, i, xf(i - 1), off, i)); cur = "[x%d]" % i
    total = total_len()
    parts.append("%sfade=t=in:st=0:d=%.2f:c=%s,fade=t=out:st=%.3f:d=%.2f:c=%s[v]"
                 % (cur, FADE_IN, FADE_COLOR, total - FADE_OUT, FADE_OUT, FADE_COLOR))
    run(["ffmpeg", "-y", "-v", "error", "-stats"] + ins
        + ["-filter_complex", ";".join(parts), "-map", "[v]", "-c:v", "libx264",
           "-crf", "14", "-preset", "medium", "-pix_fmt", "yuv420p",
           "-r", str(FPS), "master.mp4"],
        "拼接 %d 镜  总长 %.1fs" % (len(SHOTS), total))


def _style(name, size, pol, spacing=0, is_title=False):
    if pol == "dark_on_light":
        pri, out, ol, sh = "&H00262A2D", "&H00EAF3F6", 4 if is_title else 3, 0
    else:
        pri, out, ol, sh = "&H00F2F2EC", "&H00000000", 3, 3
    return ("Style: %s,KaiTi,%d,%s,%s,%s,%s,0,0,0,0,100,100,%d,0,1,%d,%d,5,60,60,0,1"
            % (name, size, pri, pri, out, out, spacing, ol, sh))


def styles_block():
    return "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour," \
           "SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline," \
           "StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow," \
           "Alignment,MarginL,MarginR,MarginV,Encoding\n" \
           + "\n".join([_style("T", 128, TITLE_POLARITY, 14, True),
                        _style("TS", 52, TITLE_POLARITY, 10, True),
                        _style("M", 64, POLARITY, 6),
                        _style("PM", 46, POLARITY),
                        _style("SG", 36, POLARITY, 6)]) + "\n"


def ts(t):
    return "%d:%02d:%05.2f" % (t // 3600, t % 3600 // 60, t % 60)


def vtext(s):
    return r"\N".join(list(s))


def sub_rows(txt):
    """正文拆行：写了逗号的排两行(上行在前)，否则一行。返回 [(行心y, 这一行的字), ...]"""
    if "，" in txt:
        a, b = txt.split("，", 1)
        return [(SUB_Y - SUB_ROW_GAP // 2, a), (SUB_Y + SUB_ROW_GAP // 2, b)]
    return [(SUB_Y, txt)]


def sub_box(txt, pad=8):
    """字幕在画面上的外接矩形，用来量它压着的底。"""
    fs = 56                                          # 与 _style("M", 56, ...) 一致
    rows = sub_rows(txt)
    ys = [y for y, _ in rows]
    w = max(len(p) for _, p in rows) * fs
    return (max(0, int(960 - w / 2 - pad)), min(W, int(960 + w / 2 + pad)),
            max(0, int(min(ys) - fs / 2 - pad)), min(H, int(max(ys) + fs / 2 + pad)))


def make_ass():
    ev = []
    for st, en, txt, sty in LINES:
        if sty == "T":
            ev.append("Dialogue: 0,%s,%s,T,,0,0,0,,{\\pos(960,%d)}{\\fad(1200,1000)}%s"
                      % (ts(st), ts(en), TITLE_Y, txt))
        elif sty == "TS":
            ev.append("Dialogue: 0,%s,%s,TS,,0,0,0,,{\\pos(960,%d)}{\\fad(1200,1000)}%s"
                      % (ts(st), ts(en), TITLE_SUB_Y, txt))
        else:
            # 横排、底部居中；四言拆两行
            for y, part in sub_rows(txt):
                ev.append("Dialogue: 0,%s,%s,M,,0,0,0,,{\\pos(960,%d)}{\\fad(700,700)}%s"
                          % (ts(st), ts(en), y, part))
    for k, line in enumerate(POEM):
        x = int(POEM_CX + (len(POEM) / 2 - 0.5 - k) * POEM_GAP)
        ev.append("Dialogue: 0,%s,%s,PM,,0,0,0,,{\\pos(%d,%d)}{\\fad(1400,1200)}%s"
                  % (ts(POEM_IN), ts(POEM_OUT), x, POEM_CY, vtext(line)))
    if POEM:
        ev.append("Dialogue: 0,%s,%s,SG,,0,0,0,,{\\pos(360,880)}{\\fad(1400,1200)}%s"
                  % (ts(POEM_IN + 0.6), ts(POEM_OUT), AUTHOR))
    with open("sub.ass", "w", encoding="utf-8-sig") as f:
        f.write("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\n"
                "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n" % (W, H)
                + styles_block()
                + "\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,"
                  "MarginV,Effect,Text\n" + "\n".join(ev) + "\n")
    print("已生成 sub.ass")


def make_scrim():
    if SCRIM_ALPHA <= 0:
        return False
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         "color=c=black:s=%dx%d,format=rgba," % (W, H)
         + r"geq=r='0':g='0':b='0':a='clip(255*%.3f*pow(max(0\,(Y-%d))/%d\,%.2f),0,255)'"
         % (SCRIM_ALPHA, SCRIM_Y0, SCRIM_SOFT, SCRIM_POW),
         "-frames:v", "1", "scrim.png"], "生成底部 scrim")
    return True


def _chain(tag="[0:v]", scrim=False):
    fd = FONTS.replace("\\", "/")
    if scrim:
        return "%s[1:v]overlay=0:0:shortest=1[s];[s]subtitles=sub.ass:fontsdir=%s[v]" % (tag, fd)
    return "%ssubtitles=sub.ass:fontsdir=%s[v]" % (tag, fd)


def build_audio():
    total = total_len()
    if not music_on():
        # 没有音乐，而横版模板没有别的音源 —— **不产出静音轨**：
        # 静音轨会让 loudnorm 量到 −70、再把它乘上天文数字的增益去够 −15。
        print("   MUSIC_MODE='none' 且横版没有音效轨 —— 不生成 mix.wav，成片无音轨")
        if os.path.exists("mix.wav"):
            os.remove("mix.wav")
        return False
    run(["ffmpeg", "-y", "-v", "error", "-stats", "-i", MUSIC, "-filter_complex",
         "[0:a]aresample=48000,aformat=fltp:cl=stereo,"
         "atrim=start=%.3f:end=%.3f,asetpts=PTS-STARTPTS,volume=%.1fdB,"
         "apad,atrim=0:%.3f,afade=t=in:st=0:d=%.2f,afade=t=out:st=%.3f:d=6,"
         "alimiter=limit=0.95[a]"
         % (MUSIC_IN, MUSIC_IN + total, MUSIC_GAIN, total, MUSIC_FADE_IN, total - 6),
         "-map", "[a]", "-c:a", "pcm_s24le", "-t", "%.3f" % total, "mix.wav"],
        "混音(从 %.0fs 切入)" % MUSIC_IN)
    return True


def measure_loudness(path):
    import json
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af",
                        "loudnorm=I=%.1f:TP=%.1f:print_format=json" % (TARGET_I, TARGET_TP),
                        "-f", "null", "-"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    m = json.loads(p.stderr[p.stderr.rfind("{"):p.stderr.rfind("}") + 1])
    print("   实测 I=%s LUFS  TP=%s dBTP" % (m["input_i"], m["input_tp"]))
    return m


def pass_c():
    make_ass(); has = make_scrim(); total = total_len()
    got_audio = build_audio()
    ins = ["-i", "master.mp4"] + (["-loop", "1", "-i", "scrim.png"] if has else [])
    fc = ["[0:v]noise=alls=3:allf=t+u[g]", _chain("[g]", has)]
    amap, acodec, how = [], [], "**无音轨**"
    if got_audio:
        m = measure_loudness("mix.wav")
        norm = ("loudnorm=I=%.1f:TP=%.1f:LRA=%s:measured_I=%s:measured_TP=%s:"
                "measured_LRA=%s:measured_thresh=%s:offset=%s:linear=true,aresample=48000"
                % (TARGET_I, TARGET_TP, m["input_lra"], m["input_i"], m["input_tp"],
                   m["input_lra"], m["input_thresh"], m["target_offset"]))
        ins += ["-i", "mix.wav"]
        fc.append("[%d:a]" % (2 if has else 1) + norm + "[a]")
        amap, acodec = ["-map", "[a]"], ["-c:a", "aac", "-b:a", "320k"]
        how = "归一到 %.1f LUFS" % TARGET_I
    out = os.path.join("..", OUT_NAME)
    run(["ffmpeg", "-y", "-v", "error", "-stats"] + ins
        + ["-filter_complex", ";".join(fc), "-map", "[v]"] + amap
        + ["-c:v", "libx264", "-crf", "18", "-preset", "slow", "-pix_fmt", "yuv420p"]
        + acodec + ["-movflags", "+faststart", "-t", "%.3f" % total, out],
        "%s + 烧字幕 -> %s" % (how, out))
    print("\n完成: " + out)
    if not got_audio:
        print("这一支**没有音轨**。如果不是有意的，检查 MUSIC_MODE。")


def still():
    """先整片烧低码率预览再抽帧 —— -ss 在 -i 前会把 PTS 重置为 0，
    subtitles 滤镜就找不到字幕，抽出来一个字都没有。"""
    if not os.path.exists("master.mp4"):
        sys.exit("!!! 还没有 master.mp4，先跑 a + b")
    make_ass(); has = make_scrim(); os.makedirs("stills", exist_ok=True)
    ins = ["-i", "master.mp4"] + (["-loop", "1", "-i", "scrim.png"] if has else [])
    run(["ffmpeg", "-y", "-v", "error", "-stats"] + ins
        + ["-filter_complex", _chain("[0:v]", has), "-map", "[v]",
           "-c:v", "libx264", "-crf", "30", "-preset", "ultrafast",
           "-pix_fmt", "yuv420p", "-t", "%.3f" % total_len(), "preview.mp4"],
        "烧字幕预览")
    marks = [((s + e) / 2, t) for s, e, t, y in LINES if y == "M"]
    marks.insert(0, (4.2, "标题"))
    if POEM:
        marks.append(((POEM_IN + POEM_OUT) / 2, "诗文页"))
    for i, (t, txt) in enumerate(marks):
        run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % t, "-i", "preview.mp4",
             "-frames:v", "1", "stills/%02d_%.0fs.png" % (i, t)],
            "静帧 %.1fs  %s" % (t, txt))
    print("\n%d 张静帧在 stills/ —— 逐张打开看过再宣布完成" % len(marks))


def measure():
    """量每条字幕压着的底。

    **必须量无字的 master.mp4，不能量烧了字幕的 preview.mp4。**
    在烧过字的帧上框出字幕区求极值，量到的是字本身，不是它压着的底 ——
    每条字幕都会整整齐齐报同一个数，看起来像"条条都危险"，其实一条都没问题。
    这个错误骗过一次，而且骗得很像真的。

    起/中/止各量一次：横移会把字幕拖过明暗分界，只量中间那一帧会漏掉最差的时刻。
    """
    if not os.path.exists("master.mp4"):
        sys.exit("!!! 还没有 master.mp4，先跑 a + b")
    dark_ink = POLARITY == "dark_on_light"
    ink = 40 if dark_ink else 242
    # 判据用 1% 分位数，不用绝对极值：一两笔亮浪或一颗星就能把极值拉过头，
    # 据此判"不合格"会误伤，久了就没人再看这个检查。
    def pct(v, p):
        v = sorted(v)
        return v[max(0, min(len(v) - 1, int(len(v) * p)))]
    print("\n=== 字幕底实测（无字 master；每条 起 / 中 / 止）===")
    print("   每格 = 均值 / 1%分位 (极值)")
    worst = []
    for st, en, txt, sty in LINES:
        if sty != "M":
            continue
        x0, x1, y0, y1 = sub_box(txt)
        out = []
        for t in (st + 0.2, (st + en) / 2, en - 0.2):
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "%.2f" % t,
                            "-i", "master.mp4", "-frames:v", "1", "_m.png"],
                           capture_output=True)
            b = subprocess.run(["ffmpeg", "-v", "error", "-i", "_m.png", "-vf",
                                "format=gray", "-f", "rawvideo", "-"],
                               capture_output=True).stdout
            v = [b[y * W + x] for y in range(y0, y1) for x in range(x0, x1)]
            out.append((sum(v) / len(v),
                        pct(v, 0.01) if dark_ink else pct(v, 0.99),
                        min(v) if dark_ink else max(v)))
        worst.append(min(o[1] for o in out) if dark_ink else max(o[1] for o in out))
        print("  %-22s " % txt + "  ".join("%3.0f/%3d(%3d)" % o for o in out))
    if os.path.exists("_m.png"):
        os.remove("_m.png")
    if not worst:
        return
    m = min(worst) if dark_ink else max(worst)
    gap = abs(m - ink)
    print("\n  字幕色约 %d，最差处的底(1%%分位) %d，相差 %d 级 —— %s"
          % (ink, m, gap, "够用（>=50）" if gap >= 50
             else "不够，加重 scrim 或把这几镜换成反极性"))
    print("  注意这只是数字。还要跑 still 用眼睛看一遍：")
    print("  数值够但压在主体上（人脸、窗框、竖梃）是量不出来的。")


def cover():
    with open("cover.ass", "w", encoding="utf-8-sig") as f:
        f.write("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\n"
                "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n" % (W, H)
                + styles_block() + "\n[Events]\nFormat: Layer,Start,End,Style,Name,"
                "MarginL,MarginR,MarginV,Effect,Text\n"
                + "Dialogue: 0,0:00:00.00,0:00:10.00,T,,0,0,0,,"
                  "{\\pos(960,430)\\fs170}%s\n" % TITLE
                + "Dialogue: 0,0:00:00.00,0:00:10.00,TS,,0,0,0,,"
                  "{\\pos(960,600)\\fs60}%s\n" % AUTHOR)
    out = os.path.join("..", COVER_NAME)
    run(["ffmpeg", "-y", "-v", "error", "-i", "img%02d.png" % COVER_FROM,
         "-vf", "scale=%d:%d:flags=lanczos,subtitles=cover.ass:fontsdir=%s"
                % (W, H, FONTS.replace("\\", "/")), "-frames:v", "1", out],
        "封面 -> " + out)
    print("封面出好后记得打开看一眼：标题很容易压在人脸、窗框或其他主体上。")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("prep", "probe", "trace", "still", "measure", "cover", "motion"):
        {"prep": prep, "probe": probe, "trace": trace, "still": still,
         "measure": measure, "cover": cover, "motion": motion}[what]()
        sys.exit(0)
    ok = check_timeline()
    if what == "check":
        sys.exit(0 if ok else 1)
    if what in ("a", "all"):
        if what == "all":
            prep()
        pass_a()
    if what in ("b", "all"):
        pass_b()
    if what in ("c", "all"):
        pass_c()
