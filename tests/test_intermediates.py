"""回归：中间件对账 / 并行 a / credits 备份 / 交付物目录守卫 / 模板残留。

    python tests/test_intermediates.py

在临时目录里搭一个迷你片库（两张小图、两镜、320x180），直接 import 真脚本、
把尺寸和时间轴换成小的，然后**逐条把被检查的东西弄坏，看它报不报警**。
只验「现在通过」等于没验 —— 很容易把检查改成永远不报警的样子。

要 ffmpeg / ffprobe 在 PATH 上。整套跑一遍几十秒。
"""
import ast
import contextlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# VMSKILL_SCRIPTS 指到一份故意改坏的副本，可以验这套测试自己会不会红
SCRIPTS = os.environ.get("VMSKILL_SCRIPTS") or os.path.join(ROOT, "classical-poem-video", "scripts")
FAILS = []


def ok(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        FAILS.append(what)


def quiet(fn, *a, **k):
    """跑 fn，吞掉它的打印；返回 (是否 SystemExit, 打印内容)。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), open(os.devnull, "w") as dn, \
            contextlib.redirect_stderr(dn):
        try:
            fn(*a, **k)
        except SystemExit as e:
            return True, buf.getvalue() + str(e.code)
    return False, buf.getvalue()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    argv, sys.argv = sys.argv, [path]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            spec.loader.exec_module(m)
    finally:
        sys.argv = argv
    return m


def mtime(p):
    return os.stat(p).st_mtime_ns


def build_library(tmp):
    lib = os.path.join(tmp, "lib")
    for other in ("旧片甲", "旧片乙"):           # 片库根下的别的片子
        os.makedirs(os.path.join(lib, other, "素材"))
    os.makedirs(os.path.join(lib, "素材"))        # ani/ 下真有一个历史遗留的 素材/
    proj = os.path.join(lib, "新片")
    os.makedirs(os.path.join(proj, "素材"))
    os.makedirs(os.path.join(proj, "build"))
    for name, src in (("a.png", "testsrc2=size=1200x1200"), ("b.png", "mandelbrot=size=1200x1200")):
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", src, "-frames:v", "1",
                        os.path.join(proj, "素材", name)], check=True)
    return lib, proj


def scenario(script, lib, proj, wh):
    tag = script.replace(".py", "")
    print("\n== " + tag)
    build = os.path.join(proj, "build")
    dst = os.path.join(build, script)
    shutil.copy(os.path.join(SCRIPTS, script), dst)
    # 引擎和模板一起复制 —— 开新一支时也是这么做的
    shutil.copy(os.path.join(SCRIPTS, "story_core.py"), os.path.join(build, "story_core.py"))
    os.chdir(build)
    for d in ("shots",):
        shutil.rmtree(d, ignore_errors=True)
    for f in os.listdir("."):
        if f.startswith("img") or f == "prep_keys.json":
            os.remove(f)
    M = load(dst, tag)

    # 不带参数不再等于 all
    r = subprocess.run([sys.executable, dst], capture_output=True, text=True, encoding="utf-8")
    ok(r.returncode != 0 and "用法" in r.stderr, "不带参数 -> 打印用法退出，不跑 all")

    W, H = wh
    M.W, M.H, M.PREP, M.UP, M.FPS, M.GRADE = W, H, (W * 2, H * 2), (W * 3, H * 3), 30, ""
    M.CLIPS = [dict(src="a.png", zoom=1.0, cx=0.5, cy=0.5, tweak=""),
               dict(src="b.png", zoom=1.0, cx=0.5, cy=0.5, tweak="")]
    M.SHOTS = [dict(z=(1.0, 1.15), f0=(0.5, 0.5), f1=(0.55, 0.5)),
               dict(z=(1.1, 1.1), f0=(0.5, 0.5), f1=(0.5, 0.5), motion="static")]
    durs = [1.0, 1.2]
    M.timeline = lambda: (None, list(durs), sum(durs), None)
    M.probe = lambda: None
    s1, s2 = M.shot_path(1), M.shot_path(2)

    # ---- 基线
    quiet(M.prep)
    ok(M.stale_prep() == [], "prep 之后 stale_prep 为空")
    ex, _ = quiet(M.pass_a, jobs=2)
    ok(not ex and os.path.exists(s1) and os.path.exists(s2), "并行 a 渲出两镜")
    ok(not quiet(M.check_shots, durs)[0], "b 前对账：刚渲完的能过")
    ok("全部都是" in quiet(M.pass_a)[1], "再跑 a：全部跳过")

    # ---- 1. 改了 CLIPS 没重跑 prep
    M.CLIPS[1]["cx"] = 0.4
    ok(M.stale_prep() == [2], "改了镜 2 的裁切 -> stale_prep 报镜 2")
    ok(quiet(M.pass_a)[0], "  -> a 拒绝开渲")
    ok(quiet(M.check_shots, durs)[0], "  -> b 拒绝拼")
    t1 = mtime(s1)
    quiet(M.prep)
    quiet(M.pass_a, jobs=2)
    ok(mtime(s1) == t1 and not quiet(M.check_shots, durs)[0], "重跑 prep + a：只补镜 2，镜 1 没动")

    # ---- 1b. 插一镜（镜数变了）
    M.CLIPS.insert(1, dict(src="a.png", zoom=1.2, cx=0.3, cy=0.5, tweak=""))
    ok(M.stale_prep() == [2, 3], "中间插一镜 -> 插入点之后全部报过期")
    M.CLIPS.pop(1)

    # ---- 1c. prep 时缺图（跳过），留下上一轮的同名 img
    os.rename(os.path.join(proj, "素材", "b.png"), os.path.join(proj, "b.png"))
    quiet(M.prep)
    ok(os.path.exists("img02.png") and M.stale_prep() == [2], "缺图跳过 -> 旧 img02 还在，但报过期")
    ok(quiet(M.pass_a)[0], "  -> a 拒绝开渲")
    os.rename(os.path.join(proj, "b.png"), os.path.join(proj, "素材", "b.png"))
    quiet(M.prep)
    ok(M.stale_prep() == [], "图放回去、重跑 prep -> 对上")

    # ---- 2. 渲到一半被打断：48 字节残文件
    with open(s1, "wb") as f:
        f.write(b"\0" * 48)
    ex, msg = quiet(M.check_shots, durs)
    ok(ex and "镜1" in msg, "48 字节残文件（印记还在）-> b 拒绝拼")
    quiet(M.pass_a, jobs=1)
    ok(not quiet(M.check_shots, durs)[0], "  -> 串行 a 自动补上")

    # ---- 2b. 印记没了
    os.remove(os.path.join("shots", "shot02.key"))
    ok(quiet(M.check_shots, durs)[0], "印记被撕（渲到一半被打断）-> b 拒绝拼")
    quiet(M.pass_a)

    # ---- 3. 镜长变了（改 XF / 换旁白）没重跑 a
    durs[0] = 1.5
    ok(quiet(M.check_shots, durs)[0], "镜 1 变长 -> b 拒绝拼")
    quiet(M.pass_a)
    ok(not quiet(M.check_shots, durs)[0], "  -> a 补渲后对上")

    # ---- 3b. 只有时长那道保险拦得住的：印记对得上，文件却被别的顶替了
    shutil.copy(s2, s1)
    ok(quiet(M.check_shots, durs)[0], "shot01 被 shot02 顶替（印记对得上、时长不对）-> b 拒绝拼")
    quiet(M.pass_a)

    # ---- 1d. 只有「prep 先撕印记」拦得住的：ffmpeg 写坏了 img 然后退出，输入一个没变
    real_run = M.run

    def bad_run(args, desc):
        if args[-1] == "img02.png":
            with open("img02.png", "wb") as f:
                f.write(b"\0" * 10)
            sys.exit("!!! 失败: " + desc)
        return real_run(args, desc)
    M.run = bad_run
    quiet(M.prep)
    M.run = real_run
    ok(2 in M.stale_prep(), "prep 中途失败、img02 写坏了 -> 报过期")
    quiet(M.prep)

    # ---- force
    t1, t2 = mtime(s1), mtime(s2)
    quiet(M.pass_a, force=True)
    ok(mtime(s1) != t1 and mtime(s2) != t2, "a force：全部重渲")

    # ---- 交付物目录
    ok(M.out_dir() == "..", "标准布局（项目/build/脚本）-> 交付物写 ..")
    here, src = M.HERE, M.SRC
    os.chdir(proj)
    M.HERE, M.SRC = proj, os.path.join("..", "素材")    # 脚本错放在项目根、SRC 没改
    ok(quiet(M.out_dir)[0], "脚本错放在项目根 -> ../素材 存在也拦（.. 是片库根）")
    M.SRC = "素材"
    ok(M.out_dir() == ".", "平铺布局（项目/脚本 + SRC=素材）-> 写 .")
    M.HERE, M.SRC = here, src
    os.chdir(build)

    # ---- credits 不再无声覆盖
    p = os.path.join(proj, "_gen_%s.md" % tag)

    def baks():
        return [f for f in os.listdir(proj) if f.startswith(os.path.basename(p) + ".bak-")]
    quiet(M.write_generated, p, ["# 表", "a"])
    quiet(M.write_generated, p, ["# 表", "b"])
    ok(baks() == [], "没人动过 -> 直接重写，不备份")
    with open(p, "a", encoding="utf-8") as f:
        f.write("手写的配乐铺法\n")
    _, msg = quiet(M.write_generated, p, ["# 表", "c"])
    ok(len(baks()) == 1 and "被手改过" in msg, "指纹后面追加了手写 -> 先备份")
    time.sleep(1.1)
    with open(p, encoding="utf-8") as f:
        s = f.read()
    with open(p, "w", encoding="utf-8") as f:
        f.write(s.replace("c\n", "c 手改\n"))
    quiet(M.write_generated, p, ["# 表", "d"])
    ok(len(baks()) == 2, "正文被改 -> 备份")
    time.sleep(1.1)
    with open(p, "w", encoding="utf-8") as f:
        f.write("# 表\nd\n")
    quiet(M.write_generated, p, ["# 表", "d"])
    ok(len(baks()) == 2, "旧版生成、内容没变 -> 不备份")
    with open(p, "w", encoding="utf-8") as f:
        f.write("# 表\n旧版手写\n")
    quiet(M.write_generated, p, ["# 表", "e"])
    ok(len(baks()) == 3, "旧版生成、没有指纹、内容不同 -> 备份")
    return M


def engine_checks(H, V, proj):
    """共用引擎本身的回归：缺省值不许盖配置、版式推得对、拆出来时修的那几个 bug 不回潮。"""
    print("\n== 共用引擎")
    ok(H.LAYOUT == "h" and V.LAYOUT == "v", "版式按 W/H 推：横版 h、竖版 v")
    ok(H.SUB_MODE == "srt", "横版模板没写 SUB_MODE -> 引擎缺省外挂")
    ok(V.SUB_MODE == "burn", "竖版模板写了 burn -> 引擎不许盖掉")
    ok(H.scrim_on() is False, "横版外挂 -> 不叠 scrim")

    # _default 必须让模板配置赢：造一份在配置区改了 VIDEO_FIT / JOBS 的模板
    build = os.path.join(proj, "build")
    src = open(os.path.join(build, "make_story_v.py"), encoding="utf-8").read()
    mark = "\n# ================= 以下是引擎"
    assert mark in src
    alt = os.path.join(build, "make_story_alt.py")
    with open(alt, "w", encoding="utf-8") as f:
        f.write(src.replace(mark, '\nVIDEO_FIT = "crop"\nJOBS = 1\n' + mark, 1))
    A = load(alt, "make_story_alt")
    ok(A.VIDEO_FIT == "crop" and A.JOBS == 1,
       "模板配置了引擎也有缺省值的 VIDEO_FIT/JOBS -> 模板的赢")
    os.remove(alt)

    # check_sfx 原来读错键（file= 而表里是 f=），缺文件那一半从来不报警
    for M in (H, V):
        keep = M.SFX
        M.SFX = [dict(f="__不存在__.mp3", shot=1, off=0.0, tgt=-30.0, fi=0.1, fo=0.1, dur=1.0)]
        got = M.check_sfx()
        M.SFX = keep
        ok(any("缺文件" in x for x in got), "%s: 音效表指向不存在的文件 -> check_sfx 报警" % M.__name__)

    # 预告板误报：竖版片尾板 head=TITLE 是设计如此，只有「包含但不等于」才报
    keep = V.ENDCARD
    V.ENDCARD = dict(head=V.TITLE, sub="x", t0=1.0, t1=5.0, y=560)
    ok(V.check_endcard() == [], "片尾标题板 head == TITLE -> 不报")
    V.ENDCARD = dict(head="下一集 · " + V.TITLE, sub="x", t0=1.0, t1=5.0, y=560)
    ok(len(V.check_endcard()) == 1, "预告板写了本集标题 -> 报")
    V.ENDCARD = keep

    # 裁切比例按 W/H 推：横 16:9、竖 9:16（两份手抄时代各写死一套）
    Hw, Hh, Vw, Vh = H.W, H.H, V.W, V.H
    H.W, H.H, V.W, V.H = 1920, 1080, 1080, 1920
    ok(H._ratio() == (16, 9) and V._ratio() == (9, 16), "_ratio 横 16:9 / 竖 9:16")
    H.W, H.H, V.W, V.H = Hw, Hh, Vw, Vh


def plate_scenario(M, proj):
    """贴纸镜和运镜镜同片：PREP=2×成片时，贴纸镜在成片上仍是 1:1（不缩成半幅）。

    2026-10-18 之前 prep_plate 出成片尺寸的台纸，PREP≠成片时被 pass_a 再缩一半；
    check 只能要求 PREP＝成片，于是运镜镜全片发软。这里验新行为，并验旧行为会被抓到。"""
    print("")
    print("== 贴纸镜 + 运镜镜同片")
    small = os.path.join(proj, "素材", "small.png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=white:size=100x80",
                    "-frames:v", "1", small], check=True)
    W, H = M.W, M.H
    M.PREP = (W * 2, H * 2)
    M.CLIPS = [dict(src="a.png", zoom=1.0, cx=0.5, cy=0.5, tweak=""),
               dict(src="small.png", fit="plate", tweak="")]
    M.SHOTS = [dict(z=(1.0, 1.15), f0=(0.5, 0.5), f1=(0.55, 0.5)),
               dict(z=(1.0, 1.0), f0=(0.5, 0.5), f1=(0.5, 0.5), motion="static")]
    durs = [1.0, 1.0]
    M.timeline = lambda: (None, list(durs), sum(durs), None)
    quiet(M.prep)
    quiet(M.pass_a, jobs=1)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", M.shot_path(2), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    cols = [x for x in range(W) if any(raw[y * W + x] > 128 for y in range(H))]
    rows = [y for y in range(H) if any(raw[y * W + x] > 128 for x in range(W))]
    bw = (cols[-1] - cols[0] + 1) if cols else 0
    bh = (rows[-1] - rows[0] + 1) if rows else 0
    ok(abs(bw - 100) <= 3 and abs(bh - 80) <= 3, "PREP=2×成片：贴纸镜在成片上 %dx%d（应 100x80，1:1 不缩不放）" % (bw, bh))
    dims = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0",
                           "img02.png"], capture_output=True, text=True).stdout.strip()
    ok(dims == "%d,%d" % M.PREP, "贴纸镜的 img02 是 PREP 尺寸（%s），和运镜镜同一尺寸" % dims)
    res = []
    quiet(lambda: res.extend(M.check_resolution() or []))
    bad = [b for b in res if "贴纸版式" in b and "PREP" in b]
    ok(not bad, "PREP=2×成片且同比例 -> check 不再拦贴纸镜")


def title_checks(M):
    """TITLE_CARD before= 按时间轴推窗口；压到旁白 / 太短都报。"""
    print("")
    print("== 片名字卡挂在某句前面（before=）")
    M.NARR = [dict(vo="VO_001", shot=1, txt="甲"), dict(vo="VO_002", shot=2, txt="乙")]
    lines = [(0.9, 4.2, "甲", 1, 1.0, 3.0), (8.9, 11.2, "乙", 2, 9.0, 2.0)]
    M.timeline = lambda: (lines, [5.0, 6.0], 11.0, [0.0, 5.0])
    M.TITLE_CARD = dict(head="片名", sub="副题", before="VO_002", y=400)
    t0, t1 = M.title_window()
    ok(abs(t0 - 5.3) < 1e-6 and abs(t1 - 8.7) < 1e-6, "before=VO_002 -> 窗口 %.2f~%.2f（镜 2 起点 +0.3 到出声前 0.3）" % (t0, t1))
    ok(M.check_title(lines) == [], "  窗口落在静默里、3.4s -> 不报")
    M.TITLE_CARD = dict(head="片名", sub="副题", t0=2.0, t1=6.0, y=400)
    ok(any("压在旁白上" in b for b in M.check_title(lines)), "手填 t0/t1 压到第一句 -> 报")
    M.TITLE_CARD = dict(head="片名", sub="副题", t0=7.0, t1=8.5, y=400)
    ok(any("只在屏" in b for b in M.check_title(lines)), "手填只有 1.5s -> 报")
    M.TITLE_CARD = None


def cue_checks(M, proj):
    """长句分屏：SUB_CUE 换屏、每屏 ≤2 行；SRT 一屏一条，时间按字数分。"""
    print("")
    print("== 长句分屏（SUB_CUE）")
    C, S_ = M.SUB_CUE, M.SUB_SEP
    long_ = "一二三四五" + S_ + "六七八九十" + C + "甲乙丙丁戊"
    lines = [(0.0, 6.0, long_, 1, 0.1, 5.5)]
    M.NARR = [dict(vo="VO_001", shot=1, txt=long_)]
    M.timeline = lambda: (lines, [6.0], 6.0, [0.0])
    ct = M.cue_times(0.0, 6.0, long_)
    ok(len(ct) == 2 and abs(ct[0][1] - 4.0) < 1e-6, "两屏按字数分：10 字 / 5 字 -> 0~4.0 / 4.0~6.0（实得 %s）" % [round(x[1], 2) for x in ct])
    ok(not [b for b in M.check_subs() if "最多两行" in b], "每屏两行以内 -> check_subs 不报（旧判据数总行数 3 会报）")
    lines[:] = [(0.0, 6.0, "一" + S_ + "二" + S_ + "三", 1, 0.1, 5.5)]
    ok([b for b in M.check_subs() if "最多两行" in b], "一屏三行 -> 仍然报")
    lines[:] = [(0.0, 1.5, "一二" + C + "三四", 1, 0.1, 1.4)]
    ok(M.cue_times(0.0, 1.5, "一二" + C + "三四")[0][1] == 0.75, "总长不够 2×CUE_MIN -> 平分")
    lines[:] = [(0.0, 6.0, long_, 1, 0.1, 5.5)]
    M.LANGS, M.DEFAULT_LANG = ["zh"], "zh"
    out = M.make_srt("zh")
    body = open(out, encoding="utf-8-sig").read()
    ok(body.count(" --> ") == 2 and "甲乙丙丁戊" in body, "SRT：一条旁白出两条字幕")
    os.remove(out)


def main():
    tmp = tempfile.mkdtemp(prefix="vmskill_test_")
    cwd = os.getcwd()
    try:
        lib, proj = build_library(tmp)
        H = scenario("make_story_h.py", lib, proj, (320, 180))
        leftovers = H.check_template_leftovers()
        ok(any("经度" in x for x in leftovers), "横版模板原样 -> 报《经度》残留")
        H.TITLE, H.SUBTITLE = "新题", "新副题"
        ok(H.check_template_leftovers() == [], "  换掉之后 -> 不报")
        V = scenario("make_story_v.py", lib, proj, (180, 320))
        engine_checks(H, V, proj)
        os.chdir(os.path.join(proj, "build"))
        plate_scenario(H, proj)
        title_checks(H)
        cue_checks(H, proj)
    finally:
        os.chdir(cwd)
        shutil.rmtree(tmp, ignore_errors=True)

    # 模板里**不许有函数** —— 横竖两份手抄脚本分叉（50/112 个同名函数）就是从
    # "在模板里改一个函数"开始的。引擎只有 story_core.py 一份。
    print("\n== 模板只放配置")
    for f in ("make_story_h.py", "make_story_v.py"):
        t = ast.parse(open(os.path.join(SCRIPTS, f), encoding="utf-8").read())
        defs = [n.name for n in t.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
        ok(not defs, "%s 没有函数定义%s" % (f, "" if not defs else "（有：%s）" % defs))

    # write_generated 在引擎和诗词模板里各一份，必须一字不差
    print("\n== 副本一致")
    srcs = {}
    for f in ("story_core.py", "make_v.py"):
        t = open(os.path.join(SCRIPTS, f), encoding="utf-8").read()
        for n in ast.parse(t).body:
            if isinstance(n, ast.FunctionDef) and n.name == "write_generated":
                srcs[f] = ast.get_source_segment(t, n)
    ok(len(srcs) == 2 and len(set(srcs.values())) == 1, "write_generated 两份一致（引擎 / make_v）")

    print("\n%s" % ("全部通过" if not FAILS else "失败 %d 条：%s" % (len(FAILS), FAILS)))
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
