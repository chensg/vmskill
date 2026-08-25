# -*- coding: utf-8 -*-
"""把 TTS 每条 mp3 头尾的边缘静音剪掉，让**文件边界重新等于说话边界**。

  python vo_trim.py measure    # 只量，不动文件
  python vo_trim.py apply      # 剪，原件备份到 vo_orig/

===== 为什么要剪 =====

豆包 TTS 每条自带约 0.44s 头 + 0.43s 尾的静音（《白衣女人》121 条实测 0.879s/条）。
脚本按**文件边界**排时间轴，然后在每条前后再加 GAP_PRE / GAP_POST ——
于是每句实际被两层静音包着，片长白白涨一大截，而听感是"说不出哪里拖"。

**不要靠折算 GAP_* 来补偿**（踩过）：脚本的下限判据（GAP_POST > 0.60 /
GAP_PRE >= 0.35）守的正是文件边界，折掉的那一截恰恰是判据赖以成立的那一截，
结果是每一个镜界都报「转场压到了字幕」。

正确做法是把静音从文件里剪掉。剪完 GAP_* 直接填**想要的可听值**，
下游全部计算（字幕落点、转场位置、镜长、片长）自动全对。

===== 量法 =====

`silencedetect` 在这里**一条都判不出来** —— TTS 全程有底噪，连 -65dB 都不触发。
所以按 0.05s 窗取 RMS 包络，高于 SPEAK_DB 的窗算"在说话"，
头尾各取第一个 / 最后一个说话窗的位置。本机只有 ffmpeg，够用。
"""
import io
import os
import re
import shutil
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
VO_DIR = os.path.join(HERE, "vo")
ORIG_DIR = os.path.join(HERE, "vo_orig")

WIN = 0.05          # RMS 窗长（秒）
SPEAK_DB = -40.0    # 高于这个算在说话。**这个数要为每个音色重新量**：
                    # yuanboxiaoshu 这批实测 说话中位 -25.6dB / 底噪峰值 -44.8dB，
                    # 沿用文档里为 zhixingnv 定的 -45 会把底噪峰当成说话。
KEEP_HEAD = 0.06    # 说话点之前保留一点点，避免削掉爆破音的起始
KEEP_TAIL = 0.10    # 说话止点之后保留一点，避免把尾音切秃


SR = 44100          # 统一重采样到这个率，好让"帧数"能换算成秒


def rms_envelope(path):
    """返回 [(t, rms_db), ...]，每 WIN 秒一个点。

    **astats 的 reset 单位是「帧数」，不是秒。** 直接写 reset=0.05 会被当成 0，
    也就是**从不重置** —— 拿到的是**累积平均**而不是瞬时包络：
    开头从 -105dB 一路缓慢爬升，结尾恒定在全曲平均值附近（实测 -22.7dB），
    **永远不会掉回静音**，于是尾部静音一条都检不出来，而脚本还报"量完了"。
    （2026-08-25《潘多拉的瓮》踩过：44 条只"剪"出 9.1s，且每条的说话止
    都恰好等于文件总长 —— 那个整整齐齐的巧合就是它坏掉的样子。）

    正确做法是先用 asetnsamples 把每一帧固定成 WIN 秒，再 reset=1。
    """
    n = int(SR * WIN)
    cmd = ["ffmpeg", "-v", "error", "-i", path,
           "-af", "aresample=%d,asetnsamples=n=%d:p=0,"
                  "astats=metadata=1:reset=1,ametadata=print:"
                  "key=lavfi.astats.Overall.RMS_level:file=-" % (SR, n),
           "-f", "null", "-"]
    out = subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    pts, cur = [], None
    for line in out.splitlines():
        m = re.match(r"frame:\d+\s+pts:\d+\s+pts_time:([0-9.]+)", line)
        if m:
            cur = float(m.group(1))
            continue
        m = re.search(r"RMS_level=(-?[0-9.]+|-inf)", line)
        if m and cur is not None:
            v = m.group(1)
            pts.append((cur, -120.0 if v == "-inf" else float(v)))
            cur = None
    return pts


def speech_span(path):
    """(说话起, 说话止, 总时长)。判不出说话时返回 (None, None, dur)。"""
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout.strip() or 0)
    env = rms_envelope(path)
    talk = [t for t, db in env if db > SPEAK_DB]
    if not talk:
        return None, None, dur
    return talk[0], min(talk[-1] + WIN, dur), dur


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "measure"
    if mode not in ("measure", "apply"):
        print("用法: python vo_trim.py [measure|apply]"); return 1
    if not os.path.isdir(VO_DIR):
        print("没有 %s —— 先把 mp3 下载并归位（sort_downloads.py）" % VO_DIR); return 1

    files = sorted(f for f in os.listdir(VO_DIR)
                   if f.lower().endswith(".mp3") and f.startswith("VO_"))
    if not files:
        print("vo/ 里没有 VO_*.mp3"); return 1

    if mode == "apply":
        os.makedirs(ORIG_DIR, exist_ok=True)

    tot_cut = tot_dur = 0.0
    bad = []
    print("%-12s %8s %8s %8s %8s  %s" % ("文件", "原长", "说话起", "说话止", "剪掉", ""))
    for f in files:
        src = os.path.join(VO_DIR, f)
        a, b, dur = speech_span(src)
        tot_dur += dur
        if a is None:
            bad.append((f, "整条都在 %.0fdB 以下，判不出说话" % SPEAK_DB))
            print("%-12s %8.3f %8s %8s %8s  !! 判不出" % (f, dur, "-", "-", "-"))
            continue
        a = max(0.0, a - KEEP_HEAD)
        b = min(dur, b + KEEP_TAIL)
        cut = dur - (b - a)
        tot_cut += cut
        flag = ""
        if b - a < 0.25:
            bad.append((f, "剪完只剩 %.2fs，太短，没动" % (b - a))); flag = "  !! 太短，跳过"
        elif cut > 2.0:
            bad.append((f, "要剪掉 %.2fs，异常多，没动" % cut)); flag = "  !! 剪太多，跳过"
        print("%-12s %8.3f %8.3f %8.3f %8.3f%s" % (f, dur, a, b, cut, flag))
        if mode == "apply" and not flag:
            shutil.copy2(src, os.path.join(ORIG_DIR, f))
            tmp = src + ".tmp.mp3"
            r = subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-i", src,
                 "-ss", "%.3f" % a, "-to", "%.3f" % b,
                 "-c:a", "libmp3lame", "-q:a", "2", tmp],
                capture_output=True, text=True)
            if r.returncode or not os.path.exists(tmp):
                bad.append((f, "ffmpeg 失败: %s" % r.stderr.strip()[:80]))
                if os.path.exists(tmp):
                    os.remove(tmp)
            else:
                os.replace(tmp, src)

    print()
    print("条数        : %d" % len(files))
    print("总时长      : %.1fs" % tot_dur)
    print("可剪掉      : %.1fs  (%.1f%%)" % (tot_cut, 100 * tot_cut / tot_dur if tot_dur else 0))
    print("平均每条    : %.3fs" % (tot_cut / len(files) if files else 0))
    if bad:
        print()
        print("!! 需要人看一眼的 %d 条：" % len(bad))
        for f, why in bad:
            print("   %-12s %s" % (f, why))
    if mode == "measure":
        print()
        print("这是干量。要真剪：python vo_trim.py apply（原件备份到 vo_orig/）")
    else:
        print()
        print("剪完了。原件在 vo_orig/。")
        print("现在 GAP_PRE/GAP_POST 填的就是**可听气口**，不用再折算。")
        print("接着跑：python make_story_v.py sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
