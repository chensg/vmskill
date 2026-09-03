# -*- coding: utf-8 -*-
"""把分段渲好的片子拼成全片：视频 concat + **一次**全局响度归一 + SRT 合并 + 接缝校验。

  python join.py 段一 段二 ...          # 目录，按顺序
  python join.py --selftest             # 回归自测：造出错的段，检查必须报警

===== 为什么需要这个脚本，而不是直接 ffmpeg concat =====

分段制作的坑**全在接缝上**，而且大半不报警。这四条是设计时清出来的：

1. **逐段归一 = 每段一个增益 = 接缝处一个响度台阶。**
   loudnorm 的整合响度带门限，各段静默比例不同就会算出不同的增益。
   所以段内一律不归一（各段脚本的"段用"文件就是不归一的），
   **归一只在这里做一次**，对拼完的整条做。

2. **每段自带的黑场淡入淡出**会让接缝每隔几分钟黑一次，观众读作"结束了"。
   各段脚本里 FADE_IN 只给第一段、FADE_OUT 只给最后一段。
   这里再验一遍**输出**里真的没有黑场 —— 配置对不等于输出对。
   踩过：ffmpeg 的 fade 在 d=0 时会退回 nb_frames 默认的 25 帧，
   于是"不淡入"反而淡了 0.83s，而 check_seg 验的是配置，一声不吭。

3. **段长不是整帧**会让 concat 累积 A/V 漂移。各段脚本自动把段长吸到整帧，
   这里再验一遍。

4. **各段 SRT 的时间码都从 0 起。** 合并时必须按**实际拼接后的段起点**累加偏移，
   不能用预算值 —— 差几十毫秒，到第五段就是明显错位。

5. **多音轨的成片不能直接当上传件。**
   YouTube 的多语言音轨**不是**从上传文件里读第二条轨的 —— 上传的 MP4 里多余的音轨
   会被忽略，附加语言要在 Studio 里作为**独立音频文件**单独添加。
   （这一条 2026-08-31 由用户指出；此前整套双语实现建在"一条视频 + N 条音轨"
   这个错前提上。音频本身没问题，错的是交付形态。）
   所以 join 拼完之后**自动拆成三样**：
     - `全片.mp4`      视频 + **默认语言**一条音轨 —— 这个才是上传件
     - `全片_音轨_<code>.m4a`  每种附加语言一个独立音频，长度与画面严格一致
     - `全片_多音轨.mp4`      两条轨都在，留档 / 给支持多轨的场合
   三样全部由**流拷贝**得到，不多一代编码。

6. **多音轨的段用文件，concat 默认只会留下一条音轨。** ffmpeg 不给 -map 时按
   "每种类型挑最好的一条"选流，两条音轨的片子拼完只剩一条，**而且不报错**：
   出来的全片能播、时长对、中文轨也对，只有英文轨没了。所以这里显式 `-map 0`。
   归一同理 —— 每条轨**各自量、各自归**到同一个目标，拿中文的测量值去归英文，
   两条轨会差出一个台阶，而观众正是在切换音轨的那一刻听见它。
   段与段之间音轨条数或语言对不上时**直接拒绝拼**：那种片子拼出来只会更难查。

===== 为什么视频用 -c copy =====

各段的"段用"文件是同一套编码参数出来的（libx264 crf18 / yuv420p / 同尺寸同帧率），
所以视频可以直接 copy，不吃第二次编码损失。**音频必须重编**（要做全局归一），
但那只有一代损失，且是必要的。
"""
import json
import os
import re
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TARGET_I, TARGET_TP = -15.0, -1.5
FPS = 30
SEAM_LOUD_STEP = 3.0      # 接缝两侧响度差超过这么多就报警（dB）
SEAM_WIN = 4.0            # 接缝两侧各取多长来量响度
BLACK_MEAN = 8.0          # 平均亮度低于这个算黑场
OUT_NAME = "全片.mp4"                 # 上传件：视频 + 默认语言一条轨
OUT_MULTI = "全片_多音轨.mp4"          # 留档：所有语言都在一个文件里
OUT_AUDIO = "全片_音轨_%s.m4a"         # 每种附加语言一个独立音频，%s 是语言码
OUT_SRT = "全片%s.srt"      # %s 是语言后缀：中文是空串，英文是 ".en"


def run(args, desc):
    print("\n>>> " + desc)
    if subprocess.run(args).returncode != 0:
        sys.exit("!!! 失败: " + desc)


def probe(path, keys, stream="v:0"):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", stream,
                        "-show_entries", "stream=" + ",".join(keys),
                        "-of", "default=nw=1:nk=1", path],
                       capture_output=True, text=True)
    return [x.strip() for x in r.stdout.strip().splitlines()]


def audio_tracks(path):
    """每条音轨的语言码，按流顺序。没有 language 标签的返回 "und"。"""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                        "-show_entries", "stream_tags=language",
                        "-of", "default=nw=1:nk=1", path],
                       capture_output=True, text=True)
    out = [x.strip() or "und" for x in r.stdout.splitlines()]
    if out:
        return out
    # 有音轨但一条 language 都没有时上面会返回空 —— 那时按流数补 und，
    # **不能返回空列表**，否则"有 0 条音轨"和"有音轨但没标语言"混成一件事。
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                        "-show_entries", "stream=index", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    return ["und"] * len([x for x in r.stdout.splitlines() if x.strip()])


def srt_suffixes(d, name):
    """这一段有哪几份字幕：{后缀: 路径}。中文是 ""，英文是 ".en"。

    **两个地方都找：段目录，和它的上一级。**
    `make_story_h.py` 的 `c` 把 srt 和段用 mp4 写在**项目根**
    （`os.path.join("..", srt_name(lang))`），而这里原来只在段目录里找 ——
    两个脚本对不上。找不到的后果不是报错，是**合并出 0 条、再拿空文件
    盖掉好的那份**（2026-09-03 踩过：`全片.srt` 从 11671 字节变成 3 字节）。

    **后缀是从磁盘上读出来的，不是按语言码查表算的。** 查表要在这里和
    make_story_h.py 的 LANG_INFO 各写一份，迟早分叉；读文件不会。
    """
    out = {}
    for base in (d, os.path.dirname(os.path.abspath(d))):
        try:
            names = os.listdir(base)
        except OSError:
            continue
        for fn in names:
            if fn.startswith(name) and fn.lower().endswith(".srt"):
                out.setdefault(fn[len(name):-4], os.path.join(base, fn))
        if out:
            break
    return out


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def frame_mean(path, t):
    """t 秒那一帧的平均亮度。读不出返回 None —— **不能当成 0**，
    那会让"读不出"看起来像"是黑场"，是个会骗人的失败模式。"""
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", "%.3f" % t, "-i", path,
                        "-frames:v", "1", "-vf", "format=gray", "-f", "rawvideo", "-"],
                       capture_output=True)
    b = p.stdout
    return (sum(b) / len(b)) if b else None


def loudness(path, ss=None, t=None, ai=None):
    """整合响度。ai 给了就只量第 ai 条音轨 —— 多音轨时不指定会量到默认那条，
    于是"英文轨自己归一过"这种错永远查不出来。"""
    a = ["ffmpeg", "-hide_banner"]
    if ss is not None:
        a += ["-ss", "%.3f" % ss]
    if t is not None:
        a += ["-t", "%.3f" % t]
    a += ["-i", path]
    if ai is not None:
        a += ["-map", "0:a:%d" % ai]
    a += ["-af", "loudnorm=print_format=json", "-f", "null", "-"]
    p = subprocess.run(a, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    try:
        m = json.loads(p.stderr[p.stderr.rfind("{"):p.stderr.rfind("}") + 1])
        return float(m["input_i"]), float(m["input_tp"])
    except Exception:
        return None, None


def srt_ts(t):
    ms = int(round(t * 1000))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60,
                                    ms // 1000 % 60, ms % 1000)


def parse_srt(path):
    txt = open(path, encoding="utf-8-sig").read()
    out = []
    for blk in re.split(r"\n\s*\n", txt.strip()):
        lines = [x for x in blk.splitlines() if x.strip()]
        if len(lines) < 2:
            continue
        m = re.search(r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)", blk)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        st = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000.0
        en = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000.0
        body = lines[2:] if re.match(r"^\d+$", lines[0]) else lines[1:]
        out.append((st, en, "\n".join(body)))
    return out


def collect(seg_dirs):
    """找每段的段用 mp4 和各语言 srt，并核对编码参数、音轨条数与语言一致。"""
    segs, bad = [], []
    for d in seg_dirs:
        if not os.path.isdir(d):
            bad.append("目录不存在: " + d)
            continue
        name = os.path.basename(os.path.normpath(d))
        # 段目录里找不到就回退到上一级 —— `c` 写的是 `../<段名>_段用.mp4`
        mp4 = os.path.join(d, "%s_段用.mp4" % name)
        if not os.path.exists(mp4):
            alt = os.path.join(os.path.dirname(os.path.abspath(d)),
                               "%s_段用.mp4" % name)
            if os.path.exists(alt):
                mp4 = alt
            else:
                bad.append("缺段用文件（段目录和上一级都没有）: " + mp4)
                continue
        srts = srt_suffixes(d, name)
        if not srts:
            print("   提示: %s 没有 srt，这一段不会有字幕" % name)
        tracks = audio_tracks(mp4)
        segs.append(dict(name=name, mp4=mp4, srts=srts, tracks=tracks,
                         dur=duration(mp4),
                         v=probe(mp4, ["width", "height", "r_frame_rate",
                                       "pix_fmt", "codec_name"]),
                         a=probe(mp4, ["codec_name", "sample_rate", "channels"], "a:0")))
    if bad or not segs:
        return segs, bad
    ref = segs[0]
    for s in segs[1:]:
        if s["v"] != ref["v"]:
            bad.append("%s 的视频参数和 %s 不一致：%s vs %s —— "
                       "concat -c copy 要求完全一致，否则得整条重编码"
                       % (s["name"], ref["name"], s["v"], ref["v"]))
        if s["a"] != ref["a"]:
            bad.append("%s 的音频参数和 %s 不一致：%s vs %s"
                       % (s["name"], ref["name"], s["a"], ref["a"]))
        # **音轨对不上就不拼。** 条数不同 concat 会拼出一个流布局混乱的文件；
        # 条数相同而顺序不同（一段 zho/eng、另一段 eng/zho）更坏 ——
        # 拼出来能播、时长对，只有中间某一段说的是另一种语言。
        if s["tracks"] != ref["tracks"]:
            bad.append("%s 的音轨和 %s 对不上：%s vs %s —— "
                       "多音轨必须每段条数相同、顺序相同（同一段没开 LANGS？）"
                       % (s["name"], ref["name"], "/".join(s["tracks"]),
                          "/".join(ref["tracks"])))
        if set(s["srts"]) != set(ref["srts"]):
            bad.append("%s 的字幕份数和 %s 对不上：%s vs %s"
                       % (s["name"], ref["name"],
                          sorted(s["srts"]) or "无", sorted(ref["srts"]) or "无"))
    if len(ref["tracks"]) > 1 and len(ref["srts"]) < len(ref["tracks"]):
        # 不算错（有人就是只要一份字幕），但十有八九是漏了 —— 必须说出来
        print("   提示: 有 %d 条音轨却只有 %d 份字幕 —— 多音轨片子通常每种语言各一份"
              % (len(ref["tracks"]), len(ref["srts"])))
    return segs, bad


def check_segments(segs):
    bad = []
    print("\n=== 各段 ===")
    for s in segs:
        fr = s["dur"] * FPS
        off = abs(fr - round(fr))
        flag = "" if off < 1e-3 else "  << **不是整帧**（差 %.3f 帧）" % off
        if off >= 1e-3:
            bad.append("%s 段长 %.4fs = %.3f 帧，不是整帧 —— concat 会累积 A/V 漂移"
                       % (s["name"], s["dur"], fr))
        # 每条轨各量各的：只量默认轨的话，"英文轨自己归一过了"查不出来
        s["loud"] = [loudness(s["mp4"], ai=j)[0] for j in range(len(s["tracks"]))]
        li, tp = loudness(s["mp4"], ai=0)
        # **不要按下标取 v[0]/v[1] 当宽高** —— ffprobe 按流定义顺序返回字段，
        # 不是按 -show_entries 里写的顺序。第一版就这么打成了 "h264x320"。
        # 比较用整个列表（各段同序）是对的，但打印必须单独问。
        wh = probe(s["mp4"], ["width", "height"])
        print("  %-6s %8.3fs = %8.1f 帧  %s  I=%6.1f LUFS  TP=%+5.2f dBTP%s"
              % (s["name"], s["dur"], fr, "x".join(wh) if len(wh) == 2 else "?",
                 li or 0, tp or 0, flag))
        if len(s["tracks"]) > 1:
            print("         音轨 %d 条：%s"
                  % (len(s["tracks"]),
                     "  ".join("%s I=%.1f" % (c, l if l is not None else float("nan"))
                               for c, l in zip(s["tracks"], s["loud"]))))
        if tp is not None and tp > 0:
            print("         ** 真峰值顶到 0 以上：这一段渲染时限幅没留余量"
                  "（alimiter 要加 level=disabled，否则 limit 会被 level 抬回 0）")
    return bad


def concat_video(segs, work):
    lst = os.path.join(work, "_concat.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for s in segs:
            f.write("file '%s'\n" % os.path.abspath(s["mp4"]).replace("\\", "/"))
    raw = os.path.join(work, "_raw.mp4")
    # **-map 0 不能省。** 不给 -map 时 ffmpeg 每种类型只挑一条流，
    # 两条音轨的片子拼完只剩一条，而且不报错（见文件头第 5 条）。
    run(["ffmpeg", "-y", "-v", "error", "-stats", "-f", "concat", "-safe", "0",
         "-i", lst, "-map", "0", "-c", "copy", raw],
        "拼接 %d 段（视频 -c copy，%d 条音轨全带上）"
        % (len(segs), len(segs[0]["tracks"])))
    return raw, lst


def check_seams(raw, segs):
    """接缝两侧各验两件事：**有没有黑场**、**响度有没有台阶**。
    这两件都是"单看每一段完全正常、拼起来才坏"的那类，而且都不报错。"""
    bad = []
    print("\n=== 接缝 ===")
    off = 0.0
    for i, s in enumerate(segs[:-1]):
        off += s["dur"]
        got = []
        for dt in (-0.40, -0.15, -0.03, 0.03, 0.15, 0.40):
            m = frame_mean(raw, max(0.0, off + dt))
            if m is not None:
                got.append((dt, m))
        dark = [(dt, m) for dt, m in got if m < BLACK_MEAN]
        la, _ = loudness(raw, max(0.0, off - SEAM_WIN), SEAM_WIN)
        lb, _ = loudness(raw, off, SEAM_WIN)

        print("  %s → %s  @ %.3fs" % (s["name"], segs[i + 1]["name"], off))
        print("     亮度  " + "  ".join("%+.2fs:%3.0f" % (dt, m) for dt, m in got))
        if not got:
            bad.append("接缝 %.3fs 一帧都读不出来 —— 没量到不算通过" % off)
        elif dark:
            bad.append("接缝 %.3fs 有黑场（%s）—— 中间接缝不该有淡入淡出。"
                       "查各段的 FADE_IN/FADE_OUT，注意 **d=0 的 fade 会退回 25 帧默认值**"
                       % (off, "、".join("%+.2fs 亮度 %.0f" % (dt, m) for dt, m in dark)))
        # **要判的是"有没有哪一段自己归一过"，那要比整段响度，不是比接缝两侧的窗口。**
        # 窗口量到的是**内容**：段尾常常故意留静默（金句后的呼吸），下一段开口就说话，
        # 差个三四 dB 完全正常。第一版拿 4s 窗口当判据，在《经度》段一→段二上报了
        # 3.4 dB "台阶" —— 而两段的整段响度差只有 0.02 dB，根本没有增益差。
        # 那不是台阶，是写出来的呼吸。判错了会让人去改一个没有问题的东西。
        # **逐条音轨判。** 只判默认轨的话，"英文那段自己归一过了"会整条溜过去 ——
        # 而中文轨听起来完全正常，没人会去听英文轨找台阶。
        la_l, lb_l = s.get("loud") or [], segs[i + 1].get("loud") or []
        codes = s.get("tracks") or ["a:0"]
        if not la_l or not lb_l or len(la_l) != len(lb_l):
            bad.append("接缝 %.3fs 拿不到整段响度" % off)
        else:
            win = ("前 %.1f / 后 %.1f LUFS，差 %.1f dB" % (la, lb, abs(la - lb))
                   if (la is not None and lb is not None) else "量不出")
            for j, (sa, sb) in enumerate(zip(la_l, lb_l)):
                code = codes[j] if j < len(codes) else "a:%d" % j
                if sa is None or sb is None:
                    bad.append("接缝 %.3fs 的 %s 轨拿不到整段响度" % (off, code))
                    continue
                seg_step = abs(sa - sb)
                print("     整段响度[%s]  %s %.1f / %s %.1f LUFS，差 %.2f dB%s"
                      % (code, s["name"], sa, segs[i + 1]["name"], sb, seg_step,
                         "" if seg_step <= SEAM_LOUD_STEP else "  << **台阶**"))
                if seg_step > SEAM_LOUD_STEP:
                    bad.append("接缝 %.3fs 的 %s 轨两段整段响度差 %.2f dB（上限 %.1f）—— "
                               "多半是某一段渲染时自己归一过了；段用文件必须**不归一**"
                               % (off, code, seg_step, SEAM_LOUD_STEP))
            print("     接缝窗口  %s   （这一行是内容，不是判据）" % win)
    return bad


def merge_srt(segs, work):
    """按**实际**段长累加偏移，每种语言各合一份。
    用预算值差几十毫秒，到第五段就是明显错位。"""
    outs = []
    for suffix in sorted(set().union(*[set(s["srts"]) for s in segs]) or {""}):
        ev, off, n = [], 0.0, 0
        for s in segs:
            p = s["srts"].get(suffix)
            if p:
                for st, en, body in parse_srt(p):
                    n += 1
                    ev.append("%d\n%s --> %s\n%s\n"
                              % (n, srt_ts(st + off), srt_ts(en + off), body))
            off += s["dur"]
        out_path = os.path.join(work, OUT_SRT % suffix)
        # **0 条是错，不是「这一支没有字幕」。**
        # 原来照样把空文件写出去，于是一份好好的 srt 被 3 字节的空文件盖掉，
        # 而屏幕上只有一行「合并字幕 0 条」，看着像正常输出。
        # （2026-09-03《四大美女》踩过：全片.srt 从 11671 字节变成 3 字节。）
        if n == 0:
            sys.exit(
                "!!! 合并字幕 0 条 —— 不写 %s，免得盖掉已有的那份。\n"
                "    各段找到的 srt：%s\n"
                "    段用 mp4 和 srt 都是 `make_story_h.py c` 写的，而它写在"
                "**项目根**不是段目录；这里两处都会找，都没有就是真没生成 ——"
                "去段目录里跑一次 `python make_story_h.py srt`。"
                % (out_path,
                   "；".join("%s=%s" % (s2["name"], sorted(s2["srts"]) or "无")
                             for s2 in segs)))
        with open(out_path, "w", encoding="utf-8-sig") as f:
            f.write("\n".join(ev))
        print("合并字幕 %d 条 -> %s" % (n, out_path))
        outs.append((out_path, n))
    return outs


def normalize(raw, out, tracks):
    """**一次**全局归一（不是逐段），但**每条音轨各归各的**。

    两条轨的内容不一样（说话密度、静默比例都不同），整合响度天生不同。
    拿其中一条的测量值去归另一条，两条轨就差出一个固定的台阶 ——
    而观众正是在切换音轨的那一刻听见它。所以逐条量、逐条归到**同一个目标**。
    """
    fc, maps, meta = [], ["-map", "0:v:0"], []
    for j, code in enumerate(tracks):
        li, tp = loudness(raw, ai=j)
        print("拼完整条 [%s] 实测 I=%.1f LUFS  TP=%+.2f dBTP"
              % (code, li if li is not None else float("nan"),
                 tp if tp is not None else float("nan")))
        fc.append("[0:a:%d]loudnorm=I=%.1f:TP=%.1f:linear=true,aresample=48000[a%d]"
                  % (j, TARGET_I, TARGET_TP, j))
        maps += ["-map", "[a%d]" % j]
        # 语言元数据要在这里**重新写一遍**：concat 之后它不一定还在，
        # 而丢了的样子是 YouTube 上两条轨都叫"未定"，看不出是谁丢的。
        meta += ["-metadata:s:a:%d" % j, "language=%s" % code,
                 "-disposition:a:%d" % j, "default" if j == 0 else "0"]
    run(["ffmpeg", "-y", "-v", "error", "-stats", "-i", raw,
         "-filter_complex", ";".join(fc)] + maps
        + ["-c:v", "copy", "-c:a", "aac", "-b:a", "320k",
           "-movflags", "+faststart"] + meta + [out],
        "**一次**全局归一到 %.1f LUFS，%d 条音轨各归各的（视频 copy）-> %s"
        % (TARGET_I, len(tracks), out))


def split_tracks(multi, work, tracks):
    """把多音轨成片拆成可上传的形态。全部流拷贝，不重编码。

    **为什么不能直接传多音轨文件**：YouTube 只认上传件里的第一条/默认音轨，
    其余的会被丢掉；附加语言必须在 Studio 里作为独立音频文件添加。
    不拆的话，上传上去的样子是"英文轨没了"，而文件本身完全正常 ——
    又一个不报错的失败。

    返回 (上传件, [(语言码, 音频文件), ...])。
    """
    if len(tracks) <= 1:
        return multi, []
    upload = os.path.join(work, OUT_NAME)
    run(["ffmpeg", "-y", "-v", "error", "-i", multi,
         "-map", "0:v:0", "-map", "0:a:0", "-c", "copy",
         "-movflags", "+faststart", upload],
        "上传件：视频 + %s 一条音轨（流拷贝）-> %s" % (tracks[0], upload))
    auds = []
    for j, code in enumerate(tracks[1:], start=1):
        out = os.path.join(work, OUT_AUDIO % code)
        run(["ffmpeg", "-y", "-v", "error", "-i", multi,
             "-map", "0:a:%d" % j, "-c:a", "copy", out],
            "独立音频（%s）-> %s" % (code, out))
        auds.append((code, out))
    return upload, auds


def selftest():
    """造两段故意出错的片子：第二段自己压了 8dB（响度台阶）且带黑场淡入。
    两个检查都必须报警 —— 一个永远不报警的检查比没有检查更糟。"""
    work = tempfile.mkdtemp(prefix="joinselftest_")
    dirs = []
    for i, (vol, fade) in enumerate([("0dB", False), ("-8dB", True)]):
        d = os.path.join(work, "段%d" % (i + 1))
        os.makedirs(d)
        mp4 = os.path.join(d, "段%d_段用.mp4" % (i + 1))
        vf = "fade=t=in:st=0:d=0.8:c=black" if fade else "null"
        subprocess.run(["ffmpeg", "-y", "-v", "error",
                        "-f", "lavfi",
                        "-i", "testsrc2=size=320x180:rate=%d:duration=4" % FPS,
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                        "-vf", vf, "-af", "volume=" + vol,
                        "-c:v", "libx264", "-crf", "28", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "128k", "-t", "4", mp4], check=True)
        dirs.append(d)
    print("=== 回归自测（第二段自己压了 8dB，且带 0.8s 黑场淡入）===")
    segs, bad = collect(dirs)
    bad += check_segments(segs)
    raw, lst = concat_video(segs, work)
    bad += check_seams(raw, segs)
    hit_black = any("黑场" in b for b in bad)
    hit_step = any("响度差" in b for b in bad)
    print("\n黑场检查     —— %s" % ("对，报警了" if hit_black else "**失效了**"))
    print("响度台阶检查 —— %s" % ("对，报警了" if hit_step else "**失效了**"))
    return 0 if (hit_black and hit_step) else 1


def _mkseg(work, name, langs, srts, vol="0dB"):
    """造一段测试用的段用文件：langs 有几个就有几条音轨。"""
    d = os.path.join(work, name)
    os.makedirs(d)
    mp4 = os.path.join(d, "%s_段用.mp4" % name)
    a = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc2=size=320x180:rate=%d:duration=4" % FPS]
    for j, _ in enumerate(langs):
        a += ["-f", "lavfi", "-i", "sine=frequency=%d:duration=4" % (440 + j * 220)]
    a += ["-map", "0:v"]
    for j, _ in enumerate(langs):
        a += ["-map", "%d:a" % (j + 1)]
    for j, code in enumerate(langs):
        a += ["-metadata:s:a:%d" % j, "language=%s" % code]
    a += ["-af", "volume=" + vol,
          "-c:v", "libx264", "-crf", "28", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "128k", "-t", "4", mp4]
    subprocess.run(a, check=True)
    for suffix in srts:
        with open(os.path.join(d, "%s%s.srt" % (name, suffix)), "w",
                  encoding="utf-8-sig") as f:
            f.write("1\n00:00:00,500 --> 00:00:02,000\n%s%s\n" % (name, suffix or ".zh"))
    return d


def selftest_tracks():
    """回归：多音轨的三件事。

    第三件是这里唯一**会静默出错**的，所以它先把危险本身演一遍：
    同一条 concat 命令去掉 `-map 0`，两条音轨的片子拼完只剩一条，
    而且返回码是 0、能播、时长对。演完再验加上 `-map 0` 的那条留住了两条。
    一个"永远拼得出文件"的拼接脚本比没有脚本更糟。
    """
    work = tempfile.mkdtemp(prefix="jointracks_")
    ok = True
    print("\n=== 回归自测（多音轨）===")
    d1 = _mkseg(work, "双1", ["zho", "eng"], ["", ".en"])
    d2 = _mkseg(work, "双2", ["zho", "eng"], ["", ".en"])
    d3 = _mkseg(work, "单3", ["zho"], [""])

    segs, bad = collect([d1, d2])
    hit = (not bad) and segs[0]["tracks"] == ["zho", "eng"] \
        and set(segs[0]["srts"]) == {"", ".en"}
    print("两段都是双轨双字幕 —— %s" % ("对，认出来了" if hit else "**没认出来** %s" % bad))
    ok = ok and hit

    _, bad2 = collect([d1, d3])
    hit = any("音轨" in b for b in bad2)
    print("其中一段只有单轨   —— %s" % ("对，报警了" if hit else "**放行了**"))
    ok = ok and hit

    # ---- 先演一遍不加 -map 0 会怎样 ----
    lst = os.path.join(work, "_c.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for s in segs:
            f.write("file '%s'\n" % os.path.abspath(s["mp4"]).replace("\\", "/"))
    naive = os.path.join(work, "_naive.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", lst, "-c", "copy", naive], check=True)
    dropped = audio_tracks(naive)
    print("不加 -map 0 拼出来   —— %d 条音轨 %s，%s"
          % (len(dropped), dropped,
             "对，危险是真的" if len(dropped) == 1 else "**这版 ffmpeg 没丢轨，这条演示失效了**"))
    ok = ok and len(dropped) == 1

    raw, _ = concat_video(segs, work)
    kept = audio_tracks(raw)
    print("加了 -map 0 拼出来   —— %d 条音轨 %s，%s"
          % (len(kept), kept, "对，留住了" if kept == ["zho", "eng"] else "**丢轨了**"))
    ok = ok and kept == ["zho", "eng"]

    # 和 main() 走同一条路：双轨时归一写的是**留档件**，
    # 拆分再从它派生上传件。写成 OUT_NAME 会让 split_tracks 读写同一个文件。
    out = os.path.join(work, OUT_MULTI)
    normalize(raw, out, segs[0]["tracks"])
    after = audio_tracks(out)
    print("归一之后           —— %d 条音轨 %s，%s"
          % (len(after), after,
             "对，语言元数据还在" if after == ["zho", "eng"] else "**丢了**"))
    ok = ok and after == ["zho", "eng"]

    # ---- 拆成可上传的形态 ----
    upload, auds = split_tracks(out, work, ["zho", "eng"])
    up_tracks = audio_tracks(upload)
    hit = up_tracks == ["zho"]
    print("上传件               —— %d 条音轨 %s，%s"
          % (len(up_tracks), up_tracks,
             "对，只剩默认那条" if hit else "**没拆干净**"))
    ok = ok and hit

    vdur = duration(upload)
    for code, f in auds:
        a_t = audio_tracks(f)
        adur = duration(f)
        good = a_t == [code] and abs(adur - vdur) <= 0.05
        print("独立音频 %-5s        —— %s  %.3fs（画面 %.3fs），%s"
              % (code, a_t, adur, vdur,
                 "对，等长且语言码对" if good else "**对不上**"))
        ok = ok and good
    ok = ok and len(auds) == 1

    merge_srt(segs, work)
    got = []
    for suffix in ("", ".en"):
        p = os.path.join(work, OUT_SRT % suffix)
        got.append(os.path.exists(p) and len(parse_srt(p)) == 2)
    # 第二段那一条必须被推后一整段（4.0s）
    shifted = parse_srt(os.path.join(work, OUT_SRT % ""))[1][0]
    print("合并字幕           —— 中英各一份 %s，第二段偏移 %.2fs %s"
          % ("对" if all(got) else "**不对**", shifted,
             "对" if abs(shifted - 4.5) < 0.05 else "**没按实际段长累加**"))
    ok = ok and all(got) and abs(shifted - 4.5) < 0.05
    return ok


def main():
    if "--selftest" in sys.argv:
        a = selftest()
        b = selftest_tracks()
        sys.exit(0 if (a == 0 and b) else 1)
    args = sys.argv[1:]
    if not args:
        sys.exit("用法: python join.py 段一 段二 ...   或   python join.py --selftest")
    segs, bad = collect(args)
    if bad:
        print("\n!! 问题 %d 条:" % len(bad))
        for b in bad:
            print("   - " + b)
        sys.exit(1)
    bad += check_segments(segs)
    work = os.path.dirname(os.path.abspath(args[0])) or "."
    raw, lst = concat_video(segs, work)
    bad += check_seams(raw, segs)
    tracks = segs[0]["tracks"]
    out = os.path.join(work, OUT_MULTI if len(tracks) > 1 else OUT_NAME)
    normalize(raw, out, tracks)
    print("")
    merge_srt(segs, work)
    total = duration(out)
    li, tp = loudness(out)
    print("\n=== 全片 ===")
    print("  %s" % out)
    print("  %.3fs = %d:%05.2f = %.0f 帧   I=%.1f LUFS  TP=%+.2f dBTP"
          % (total, int(total // 60), total % 60, total * FPS, li, tp))
    got = audio_tracks(out)
    print("  音轨 %d 条：%s%s"
          % (len(got), " / ".join("a:%d=%s" % (j, c) for j, c in enumerate(got)),
             "" if got == segs[0]["tracks"]
             else "  << **和段用文件对不上**（%s）" % "/".join(segs[0]["tracks"])))
    if got != tracks:
        bad.append("全片的音轨 %s 和段用文件的 %s 不一致 —— concat 或归一把轨弄丢了"
                   % ("/".join(got), "/".join(tracks)))

    upload, auds = split_tracks(out, work, tracks)
    if auds:
        vdur = duration(upload)
        print("\n=== 可上传的形态 ===")
        print("  上传件  %s   视频 + %s" % (upload, tracks[0]))
        for code, f in auds:
            adur = duration(f)
            off = abs(adur - vdur)
            print("  独立音频 %s   %s  %.3fs（画面 %.3fs，差 %.3fs）%s"
                  % (f, code, adur, vdur, off,
                     "" if off <= 0.05 else "  << **和画面对不上**"))
            # 独立音频和画面差一点点就会整条错位，而它在文件里看不出来
            if off > 0.05:
                bad.append("独立音频 %s 比画面差 %.3fs —— 上传上去整条会错位" % (f, off))
            if audio_tracks(f) != [code]:
                bad.append("独立音频 %s 的语言码是 %s，应该是 %s"
                           % (f, "/".join(audio_tracks(f)) or "无", code))
        print("  留档    %s   %d 条轨都在" % (out, len(tracks)))
        print("\n  **上传 YouTube 时传上传件，再在 Studio 里逐个添加独立音频。**")
        print("  多音轨那个文件传上去只会保留第一条轨，其余的会被丢掉。")
    for p in (raw, lst):
        try:
            os.remove(p)
        except OSError:
            pass
    if bad:
        print("\n!! 接缝问题 %d 条:" % len(bad))
        for b in bad:
            print("   - " + b)
        sys.exit(1)
    print("\n接缝自检通过。")


if __name__ == "__main__":
    main()
