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
OUT_NAME = "全片.mp4"
OUT_SRT = "全片.srt"


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


def loudness(path, ss=None, t=None):
    a = ["ffmpeg", "-hide_banner"]
    if ss is not None:
        a += ["-ss", "%.3f" % ss]
    if t is not None:
        a += ["-t", "%.3f" % t]
    a += ["-i", path, "-af", "loudnorm=print_format=json", "-f", "null", "-"]
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
    """找每段的段用 mp4 和 srt，并核对编码参数一致。"""
    segs, bad = [], []
    for d in seg_dirs:
        if not os.path.isdir(d):
            bad.append("目录不存在: " + d)
            continue
        name = os.path.basename(os.path.normpath(d))
        mp4 = os.path.join(d, "%s_段用.mp4" % name)
        srt = os.path.join(d, "%s.srt" % name)
        if not os.path.exists(mp4):
            bad.append("缺段用文件: " + mp4)
            continue
        if not os.path.exists(srt):
            print("   提示: %s 没有 srt，这一段不会有字幕" % name)
            srt = None
        segs.append(dict(name=name, mp4=mp4, srt=srt, dur=duration(mp4),
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
        li, tp = loudness(s["mp4"])
        # **不要按下标取 v[0]/v[1] 当宽高** —— ffprobe 按流定义顺序返回字段，
        # 不是按 -show_entries 里写的顺序。第一版就这么打成了 "h264x320"。
        # 比较用整个列表（各段同序）是对的，但打印必须单独问。
        wh = probe(s["mp4"], ["width", "height"])
        print("  %-6s %8.3fs = %8.1f 帧  %s  I=%6.1f LUFS  TP=%+5.2f dBTP%s"
              % (s["name"], s["dur"], fr, "x".join(wh) if len(wh) == 2 else "?",
                 li or 0, tp or 0, flag))
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
    run(["ffmpeg", "-y", "-v", "error", "-stats", "-f", "concat", "-safe", "0",
         "-i", lst, "-c", "copy", raw],
        "拼接 %d 段（视频 -c copy，不重编码）" % len(segs))
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
        if la is None or lb is None:
            bad.append("接缝 %.3fs 量不出响度" % off)
        else:
            step = abs(la - lb)
            print("     响度  前 %.1f / 后 %.1f LUFS，差 %.1f dB%s"
                  % (la, lb, step, "" if step <= SEAM_LOUD_STEP else "  << **台阶**"))
            if step > SEAM_LOUD_STEP:
                bad.append("接缝 %.3fs 响度差 %.1f dB（上限 %.1f）—— "
                           "多半是某一段渲染时自己归一过了；段用文件必须**不归一**"
                           % (off, step, SEAM_LOUD_STEP))
    return bad


def merge_srt(segs, out_path):
    """按**实际**段长累加偏移。用预算值差几十毫秒，到第五段就是明显错位。"""
    ev, off, n = [], 0.0, 0
    for s in segs:
        if s["srt"]:
            for st, en, body in parse_srt(s["srt"]):
                n += 1
                ev.append("%d\n%s --> %s\n%s\n"
                          % (n, srt_ts(st + off), srt_ts(en + off), body))
        off += s["dur"]
    with open(out_path, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(ev))
    print("\n合并字幕 %d 条 -> %s" % (n, out_path))
    return n


def normalize(raw, out):
    li, tp = loudness(raw)
    print("\n拼完整条实测 I=%.1f LUFS  TP=%+.2f dBTP" % (li, tp))
    run(["ffmpeg", "-y", "-v", "error", "-stats", "-i", raw,
         "-af", "loudnorm=I=%.1f:TP=%.1f:linear=true,aresample=48000"
         % (TARGET_I, TARGET_TP),
         "-c:v", "copy", "-c:a", "aac", "-b:a", "320k",
         "-movflags", "+faststart", out],
        "**一次**全局归一到 %.1f LUFS（视频 copy）-> %s" % (TARGET_I, out))


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


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
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
    out = os.path.join(work, OUT_NAME)
    normalize(raw, out)
    merge_srt(segs, os.path.join(work, OUT_SRT))
    total = duration(out)
    li, tp = loudness(out)
    print("\n=== 全片 ===")
    print("  %s" % out)
    print("  %.3fs = %d:%05.2f = %.0f 帧   I=%.1f LUFS  TP=%+.2f dBTP"
          % (total, int(total // 60), total % 60, total * FPS, li, tp))
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
