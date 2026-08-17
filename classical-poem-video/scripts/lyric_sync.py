# -*- coding: utf-8 -*-
"""把**一条带演唱的成品歌**和一份歌词对齐，出 MV 用的字幕时间轴。

    python lyric_sync.py probe 歌.mp3                     # 先看证据：起音、结构、谱图
    python lyric_sync.py snap 歌.mp3 --lines "枯藤老树昏鸦|..." --at "5.6,12.1,..."
    python lyric_sync.py lrc  歌.mp3 --lrc 歌.lrc          # 有现成时间戳就直接吃
    python lyric_sync.py proof 歌.mp3 --json sync.json     # 出验证物：打点混轨 + 预览片
    python lyric_sync.py check 歌.mp3 --json sync.json     # 结构自检

======================== 先说清楚这条链路不做什么 ========================

**它不猜哪一段是在唱。** 这不是偷懒，是量过之后的结论 ——
在《断肠人在天涯》(suno 生成，50.6s，吉他 + 演唱) 上试过三条纯 ffmpeg 的路，
三条都不成立：

  一、**中/边声道差**（人声居中、伴奏散开）：抽 FC 中心声道减去 side，
      整条曲子的差值在 +1.4 ~ +14.4 dB 之间摇摆，唱与不唱的段落**完全重叠**。
      原因很实在：民谣编制里吉他也在正中间，"居中"根本不是人声的特征。

  二、**谱通量找起音**：50.6s 里挑出 **132 个**起音峰，而全词只有 28 个字。
      拨弦每秒 2~3 下，每一下都是一个漂亮的起音 —— 起音检测分不出
      这一下是嗓子还是琴弦。

  三、**颤音检测**（人声长音有 4~8Hz 频率颤动，窄带里表现成同频调幅）：
      24 条 1/6 倍频程带做调制谱，颤音带能量占比在 0.05 ~ 6.96 之间，
      最高的几个窗口出现在 **−55 ~ −66 dB 的近乎静音处**（分母塌了），
      而肉眼在谱图上认得出的演唱段反而只有 0.3。判据本身是对的，
      信噪比不够就是不够。

真要做盲检得先做人声分离（demucs 那一类），那是另一个量级的依赖，
本地这条 ffmpeg 流水线扛不住。**所以时间从人来，机器只做三件它做得对的事：
吸附、推导、验证。**

======================== 时间从哪儿来（按可靠性排） ========================

  1. **现成时间戳**：平台导出的 LRC、或者自己在任何 LRC 编辑器里敲的。`lrc`
  2. **手打点**：听一遍，每句开口时敲一下，报 5 个数给 `snap`。
     **人手打点系统性偏晚**（反应时间 0.15~0.25s）—— 这条链路会自己量出
     这个滞后并整体校回去，见 `calibrate()`。所以打点只要**稳**，不要求准。
  3. 实在没有：`probe` 出谱图切片，人眼在谱图上认演唱段（人声是会抖的谐波堆，
     拨弦是笔直的衰减线），读出大概时刻，再走第 2 条。

三条路出来的都只是"大概时刻"。**吸附**把它挪到真实起音上（±10ms 级），
这一步机器做得比人准；**验证**必须回到耳朵，`proof` 出的东西就是给耳朵的。

======================== 吸附为什么敢做 ========================

起音检测分不出人声和琴弦，但这件事在**吸附**这个用法下不要紧：
唱句的开口处一定有一个起音峰（嗓子一出声就是个起音），
人手报的时刻附近 ±0.2s 内通常只有这一个强峰。
实测这支歌 132 个峰的相邻间隔中位数 0.29s、四分位 0.19/0.48s ——
所以吸附窗**不能大于 0.20s**，再大就会吸到隔壁那个字上去。
校准之后的残差实测 ≤0.08s（见 `snap` 打的表）。
"""
import argparse
import json
import math
import os
import re
import struct
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---- 起音检测 ----
# 11 条对数带当粗梅尔谱，10ms 一帧。带宽和帧长都不是随手定的：
# 带太宽（比如 3 条）拨弦和嗓子的通量混在一起，峰会糊；带太窄（1/6 倍频程 24 条）
# 单带信噪比掉下来，弱起音淹掉。11 条 / 10ms 在这支歌上给出的峰，
# 和谱图上肉眼可见的转折**逐个对得上**。
BAND_EDGES = [120, 170, 240, 340, 480, 680, 960, 1350, 1900, 2700, 3800, 5200]
FRAME_MS = 10
FLUX_LAG = 3            # 30ms 前后比，短于此拨弦的爬升期会被算成两个峰
PEAK_HALF = 6           # 局部极大的半窗（60ms）
PEAK_OVER = 8.0         # 高出滑动中位这么多 dB 才算峰
PEAK_WIN = 50           # 滑动中位的半窗（0.5s）
PEAK_MIN_GAP = 0.12     # 两个峰至少隔这么久

# ---- 吸附 ----
SNAP_W = 0.20           # 吸附窗（秒）。**上限由起音间隔中位数的一半定**，见文件头
COARSE_W = 0.60         # 校准阶段的粗窗：要能罩住人手的滞后，又不至于跨过一个字
LAG_MAX = 0.45          # 量出来的系统滞后超过这个数，多半是打点时数错了句
SPREAD_MAX = 0.15       # 各句偏移的中位绝对离差；超了说明打点不稳，吸附不可信

# ---- 由起点推终点 ----
SUB_GAP = 0.40          # 下一句出来之前，上一句至少提前这么久收掉
SUB_HOLD_MAX = 8.0      # 一句字幕最多挂这么久；超了多半是中间有间奏没算进来
SUB_TAIL = 1.20         # 末句：最后一个起音之后再留这么久
MIN_HOLD = 0.50         # 一句里**末字起音之后**字幕至少还要挂这么久
XF_PAD = 0.10           # 转场两头各留这么多，不许贴着唱句

CJK_SKIP = "，。：；、？！｜|「」《》·—…“”‘’ \t"


def _run(a, **kw):
    return subprocess.run(a, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kw)


def duration(p):
    r = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "csv=p=0", p])
    try:
        return float(r.stdout.strip())
    except ValueError:
        sys.exit("!!! 读不出时长: " + p)


def n_chars(s):
    return sum(1 for c in s if c not in CJK_SKIP)


# ============================ 起音 ============================
def band_levels(path):
    """[(t, [每带 dB])]。一趟 ffmpeg，多带并成多声道，astats 逐声道给 RMS。"""
    nb = len(BAND_EDGES) - 1
    hop = int(48000 * FRAME_MS / 1000)
    parts = ["[0:a]aformat=channel_layouts=stereo:sample_rates=48000,"
             "pan=mono|c0=0.5*c0+0.5*c1,asplit=%d%s"
             % (nb, "".join("[s%d]" % i for i in range(nb)))]
    for i in range(nb):
        # p=2 是 ffmpeg 的 highpass/lowpass 允许的最陡（p 只接受 1 或 2）
        parts.append("[s%d]highpass=f=%d:p=2,lowpass=f=%d:p=2[b%d]"
                     % (i, BAND_EDGES[i], BAND_EDGES[i + 1], i))
    parts.append("%samerge=inputs=%d,asetnsamples=n=%d:p=0,"
                 "astats=metadata=1:reset=1,ametadata=print:file=-"
                 % ("".join("[b%d]" % i for i in range(nb)), nb, hop))
    r = _run(["ffmpeg", "-v", "error", "-i", path, "-map", "0:a",
              "-filter_complex", ";".join(parts), "-f", "null", "-"])
    if r.returncode:
        sys.exit("!!! ffmpeg 抽包络失败\n" + r.stderr[-1500:])
    out, cur, t = [], None, 0.0
    for ln in r.stdout.splitlines():
        if ln.startswith("frame:"):
            if cur is not None:
                out.append((t, cur))
            cur = [-95.0] * nb
            m = re.search(r"pts_time:([\d.]+)", ln)
            t = float(m.group(1)) if m else 0.0
        elif ".RMS_level=" in ln:
            k, v = ln.strip().split("=", 1)
            ch = k.split(".")[2]
            if ch.isdigit():
                try:
                    x = float(v)
                except ValueError:
                    x = -95.0
                # astats 在全静音帧上给 -inf/nan，钳到 -95 —— 不钳的话
                # 静音后的第一帧会算出一个几十 dB 的假通量，静音起头的歌全中招
                cur[int(ch) - 1] = -95.0 if (x != x or x < -95.0) else x
    if cur is not None:
        out.append((t, cur))
    return out


def onsets(path):
    """[(t, 强度)]，按时间排。强度是上升沿逐带 dB 之和。"""
    lv = band_levels(path)
    nb = len(BAND_EDGES) - 1
    flux = [0.0] * len(lv)
    for i in range(FLUX_LAG, len(lv)):
        f = 0.0
        for b in range(nb):
            d = lv[i][1][b] - lv[i - FLUX_LAG][1][b]
            if d > 0:
                f += d
        flux[i] = f
    sm = flux[:]
    for i in range(2, len(flux) - 2):
        sm[i] = sum(flux[i - 2:i + 3]) / 5.0
    peaks = []
    for i in range(FLUX_LAG + 2, len(sm) - 2):
        a, b = max(0, i - PEAK_WIN), min(len(sm), i + PEAK_WIN + 1)
        med = sorted(sm[a:b])[(b - a) // 2]
        if sm[i] == max(sm[max(0, i - PEAK_HALF):i + PEAK_HALF + 1]) and sm[i] > med + PEAK_OVER:
            t = lv[i][0]
            if not peaks or t - peaks[-1][0] > PEAK_MIN_GAP:
                peaks.append((t, sm[i]))
            elif sm[i] > peaks[-1][1]:
                peaks[-1] = (t, sm[i])
    return peaks


def strong(peaks, keep=0.55):
    """只留强峰给吸附用。keep 是**分位**不是绝对阈值 ——
    不同的歌、不同的响度，绝对阈值没有可移植性。"""
    if not peaks:
        return []
    lim = sorted(p[1] for p in peaks)[int(len(peaks) * keep)]
    return [p for p in peaks if p[1] >= lim]


def ioi_stats(peaks):
    d = sorted(peaks[i + 1][0] - peaks[i][0] for i in range(len(peaks) - 1))
    if not d:
        return (0.0, 0.0, 0.0)
    return (d[len(d) // 4], d[len(d) // 2], d[3 * len(d) // 4])


# ============================ 吸附 ============================
def nearest(peaks, t, w):
    """窗内**最强**的峰；同强取近的。返回 (t, 强度) 或 None。

    取最强不取最近：人手报的时刻有 100ms 级的抖动，而"最近"会被一个
    弱起音（拨弦的余波、换气声）抢走 —— 唱句开口一定是窗内最强的那一个。
    """
    c = [p for p in peaks if abs(p[0] - t) <= w]
    if not c:
        return None
    m = max(x[1] for x in c)
    return min((p for p in c if p[1] >= m - 1e-9), key=lambda p: abs(p[0] - t))


def calibrate(peaks, taps):
    """量出人手打点的**系统滞后**并整体校回去。

    人对着音乐敲键盘，反应时间 0.15~0.25s，而且这个滞后**在一首歌里是稳定的** ——
    所以它是可以量、可以减掉的系统误差，不是噪声。做法：先用粗窗给每个点找
    最强峰，取偏移的**中位数**当滞后（中位数不怕某一句报错），
    再看**中位绝对离差**——离差小说明这批点整体只是晚了，减掉就好；
    离差大说明点本身就没敲稳，这时吸附不可信，宁可报出来让人重敲。

    返回 (lag, spread, 每点偏移)。lag 为负表示真实起音在报的时刻**之前**。
    """
    offs = []
    for t in taps:
        p = nearest(peaks, t, COARSE_W)
        offs.append(None if p is None else p[0] - t)
    got = [o for o in offs if o is not None]
    if not got:
        return 0.0, 0.0, offs
    lag = sorted(got)[len(got) // 2]
    dev = sorted(abs(o - lag) for o in got)
    return lag, dev[len(dev) // 2], offs


def snap_all(peaks, taps):
    """校准 + 吸附。返回 (吸附后的起点, 报告行, 有没有问题)。"""
    lag, spread, offs = calibrate(peaks, taps)
    rows, bad = [], []
    outs = []
    for i, t in enumerate(taps):
        t2 = t + lag
        p = nearest(peaks, t2, SNAP_W)
        if p is None:
            outs.append(t2)
            rows.append((i + 1, t, t2, None, None))
            bad.append("第 %d 句：校准后 %.2fs 的 ±%.2fs 内没有起音峰，"
                       "原样保留（听 proof 时重点验这一句）" % (i + 1, t2, SNAP_W))
        else:
            outs.append(p[0])
            rows.append((i + 1, t, t2, p[0], p[0] - t2))
    for i in range(1, len(outs)):
        if outs[i] <= outs[i - 1]:
            bad.append("第 %d 句吸附到 %.2fs，不晚于上一句的 %.2fs —— 打点顺序错了"
                       % (i + 1, outs[i], outs[i - 1]))
    if abs(lag) > LAG_MAX:
        bad.append("量出来的滞后 %.2fs 大得不正常（>%.2fs）—— 多半是漏了或多了一句，"
                   "整批点错位。核对句数再来" % (lag, LAG_MAX))
    if spread > SPREAD_MAX:
        bad.append("各句偏移的中位绝对离差 %.2fs（上限 %.2fs）—— 打点本身不稳，"
                   "吸附结果不可信。重敲一遍，或者改用 LRC" % (spread, SPREAD_MAX))
    return outs, (lag, spread, rows), bad


# ============================ 起止 ============================
def spans(starts, texts, total, peaks, end_last=None):
    """由起点推每句的 [起, 止]。

    规矩两条，撞上了取小的：
      - 下一句出来之前 SUB_GAP 收掉（不留重叠，两句同屏在竖排里是灾难）
      - 一句最多挂 SUB_HOLD_MAX；再长说明中间有间奏，字幕该先下去
    末句没有"下一句"，用最后一个起音 + SUB_TAIL，再钳进歌长。
    """
    out, tight = [], []
    st = strong(peaks)
    for i, s in enumerate(starts):
        if i + 1 < len(starts):
            e = min(starts[i + 1] - SUB_GAP, s + SUB_HOLD_MAX)
            # **末字还没唱完，字幕不能先走。** 一句的末字在最后一个强起音处起，
            # 之后还要拖一段腔；字幕收在它前面，观众会看见"字没了人还在唱"。
            # 两条要求撞上（句子贴得太紧）时保留空档、把冲突报出来 ——
            # 那说明这一处根本没有换镜余地，该合镜，不是该调数。
            last = max([p[0] for p in st if s - 0.05 <= p[0] < starts[i + 1] - 0.05] or [s])
            if e < last + MIN_HOLD - 1e-6:
                tight.append((i + 1, last, starts[i + 1] - last, e))
        elif end_last is not None:
            e = end_last
        else:
            # 末句尾巴要按**强峰**推。拿全部峰推会被片尾淡出里的噪声峰顶到歌末
            # （这支歌 50.21/50.42 各有一个弱峰，全曲才 50.64），
            # 于是字幕一直挂到最后一帧，尾奏一点余地都不剩
            last = max([p[0] for p in strong(peaks) if p[0] < total - 0.2] or [s])
            e = min(max(s + 2.0, last + SUB_TAIL), total)
        out.append((s, max(s + 0.6, e)))
    if tight:
        print("")
        print("  !! %d 处句子贴得太紧（末字起音之后不足 %.2fs 字幕就得收）：" % (len(tight), MIN_HOLD))
        for k, last, gap, e in tight:
            print("     第 %d→%d 句：末字起音 %.2f，下一句 %.2f，只隔 %.2fs"
                  % (k, k + 1, last, last + gap, gap))
        print("     **这些地方没有换镜余地，两句合一镜**（分镜少一个，不是把数调小）。")
    return out


def per_char(text, t0, t1, peaks):
    """行内逐字落点。**只有起音数和字数对得上才敢用**。

    汉字一字一音节，唱起来一字一起音（拖腔是把一个音拉长，不是多一个起音），
    所以"行内强起音数 == 字数"是一条可验的物理事实。对不上就说对不上，
    退回等分 —— 不去猜哪个起音是拨弦、哪个是嗓子，那正是本文件头说的做不到的事。
    """
    n = n_chars(text)
    ins = [p[0] for p in strong(peaks) if t0 - 0.05 <= p[0] < t1]
    if len(ins) == n and n > 0:
        return ins, "起音 %d = 字数 %d，逐字落点可用" % (len(ins), n)
    step = (t1 - t0) / max(n, 1)
    return [t0 + step * k for k in range(n)], \
        "起音 %d ≠ 字数 %d，退回等分（逐字沿用它会飘）" % (len(ins), n)


# ============================ 输出 ============================
def emit(path, texts, sp, extra=None):
    d = dict(song=os.path.basename(path), song_dur=round(duration(path), 3),
             lines=[dict(t0=round(a, 2), t1=round(b, 2), text=t)
                    for (a, b), t in zip(sp, texts)])
    if extra:
        d.update(extra)
    with open("sync.json", "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    print("")
    print("=== 粘进 make_v.py ===")
    print("MUSIC_MODE = \"song\"")
    print("MUSIC = os.path.join(SRC, \"%s\")" % os.path.basename(path))
    print("SUNG = [")
    for (a, b), t in zip(sp, texts):
        print("    (%6.2f, %6.2f, \"%s\")," % (a, b, t))
    print("]")
    print("")
    print("已写 sync.json。**先跑 proof 听一遍**，再谈渲染。")


def report(texts, sp, peaks, karaoke=False):
    print("")
    print("  句  起      止      挂屏   字数  字/秒")
    for i, ((a, b), t) in enumerate(zip(sp, texts), 1):
        c = n_chars(t)
        print("  %-3d %6.2f  %6.2f  %5.2f  %4d  %5.2f  %s"
              % (i, a, b, b - a, c, c / max(b - a, 0.01), t))
        if karaoke:
            ks, why = per_char(t, a, b, peaks)
            print("        逐字: %s" % why)
            print("        " + "  ".join("%.2f" % k for k in ks))


# ============================ 命令 ============================
def cmd_probe(a):
    total = duration(a.song)
    pk = onsets(a.song)
    st = strong(pk)
    q1, med, q3 = ioi_stats(pk)
    sq1, smed, sq3 = ioi_stats(st)
    print("全曲 %.2fs   起音峰 %d 个（强峰 %d）" % (total, len(pk), len(st)))
    print("全部峰间隔：四分位 %.2f / 中位 %.2f / 四分位 %.2f s" % (q1, med, q3))
    print("强峰间隔  ：四分位 %.2f / 中位 %.2f / 四分位 %.2f s" % (sq1, smed, sq3))
    # **要拿强峰的间隔去比，不是全部峰的**：吸附只在强峰里找，
    # 弱峰再密也吸不到。第一版拿全部峰比，在这支歌上把一个合法的 0.20s
    # 窗判成"偏大"（全部峰中位 0.30 vs 强峰中位 0.49）—— 判据用错了对象。
    print("吸附窗 %.2fs —— 必须小于**强峰**间隔中位数的一半(%.2fs)，"
          "否则会吸到隔壁那个字上" % (SNAP_W, smed / 2))
    if SNAP_W > smed / 2:
        print("  !! 这支歌起音太密，吸附窗偏大。要么调小 --snap-w，要么老实用 LRC")
    # 强峰之间的大空档就是**能换镜的地方**，也是句边界最可能的位置
    gaps = [(st[i][0], st[i + 1][0] - st[i][0]) for i in range(len(st) - 1)]
    gaps = [g for g in gaps if g[1] >= 0.9]
    print("")
    print("强峰之间 >=0.9s 的空档（句边界和换镜点都只会在这些地方）：")
    for k in range(0, len(gaps), 5):
        print("  " + "   ".join("%.2f 起空 %.2fs" % g for g in gaps[k:k + 5]))
    print("")
    print("强起音（吸附只认这些）：")
    for k in range(0, len(st), 8):
        print("  " + "  ".join("%6.2f" % p[0] for p in st[k:k + 8]))
    if a.spec:
        n = int(math.ceil(total / a.spec_len))
        for i in range(n):
            dst = "spec%02d.png" % i
            r = _run(["ffmpeg", "-y", "-v", "error", "-ss", "%.2f" % (i * a.spec_len),
                      "-t", "%.2f" % a.spec_len, "-i", a.song, "-filter_complex",
                      "[0:a]pan=mono|c0=0.5*c0+0.5*c1,showspectrumpic="
                      "s=1800x700:mode=combined:scale=log:start=120:stop=2000:"
                      "legend=1:gain=1.2[v]", "-map", "[v]", "-frames:v", "1", dst])
            if r.returncode == 0:
                print("  %s = %.0f~%.0fs" % (dst, i * a.spec_len, min(total, (i + 1) * a.spec_len)))
        print("")
        print("谱图怎么看：**人声是会抖的谐波堆**（一叠横条一起上下波浪，那是颤音），")
        print("拨弦是笔直的线加一条衰减尾。认出演唱段的头，读出时刻，去跑 snap。")


def cmd_snap(a):
    texts = [t for t in a.lines.split("|") if t.strip()]
    taps = [float(x) for x in a.at.replace("，", ",").split(",") if x.strip()]
    if len(texts) != len(taps):
        sys.exit("!!! %d 句词但给了 %d 个点" % (len(texts), len(taps)))
    global SNAP_W
    if a.snap_w:
        SNAP_W = a.snap_w
    total = duration(a.song)
    pk = onsets(a.song)
    st = strong(pk)
    outs, (lag, spread, rows), bad = snap_all(st, taps)
    print("全曲 %.2fs   起音峰 %d（强峰 %d）" % (total, len(pk), len(st)))
    print("")
    print("=== 校准 ===")
    print("  系统滞后 %+.3fs（人手打点偏晚是常态，整体校回）  各句离差中位 %.3fs"
          % (lag, spread))
    print("  句  你报的  校准后  吸到    残差")
    for i, t, t2, p, d in rows:
        print("  %-3d %6.2f  %6.2f  %s  %s"
              % (i, t, t2, "%6.2f" % p if p is not None else "  ——  ",
                 "%+.3f" % d if d is not None else "窗内无峰"))
    sp = spans(outs, texts, total, pk, a.end)
    report(texts, sp, pk, a.karaoke)
    for b in bad:
        print("  !! " + b)
    if bad and not a.force:
        sys.exit("\n!!! 有问题，没有写 sync.json。改点重来，或确认后加 --force")
    emit(a.song, texts, sp, dict(lag=round(lag, 3), spread=round(spread, 3),
                                 taps=taps, source="snap"))


def cmd_lrc(a):
    lines = []
    with open(a.lrc, encoding="utf-8-sig") as f:
        for ln in f:
            for m in re.finditer(r"\[(\d+):(\d+(?:[.:]\d+)?)\]", ln):
                txt = re.sub(r"\[[^\]]*\]", "", ln).strip()
                if txt:
                    s = m.group(2).replace(":", ".")
                    lines.append((int(m.group(1)) * 60 + float(s), txt))
    lines.sort()
    if not lines:
        sys.exit("!!! 这个 LRC 里没读出带时间戳的行")
    texts = [t for _, t in lines]
    if a.lines:
        given = [t for t in a.lines.split("|") if t.strip()]
        if len(given) != len(texts):
            sys.exit("!!! LRC 有 %d 行，--lines 给了 %d 句" % (len(texts), len(given)))
        texts = given          # 以自己给的文本为准，LRC 里的常有错别字
    total = duration(a.song)
    pk = onsets(a.song)
    starts = [t for t, _ in lines]
    if a.no_snap:
        outs, extra = starts, dict(source="lrc")
    else:
        # LRC 的时间戳也常有 50~200ms 的偏差（手敲的居多），照样吸附一遍，
        # 但**不做滞后校准** —— LRC 没有"人手反应时间"这个系统项
        outs, extra = [], dict(source="lrc+snap")
        st = strong(pk)
        for t in starts:
            p = nearest(st, t, SNAP_W)
            outs.append(p[0] if p else t)
    sp = spans(outs, texts, total, pk, a.end)
    report(texts, sp, pk, a.karaoke)
    emit(a.song, texts, sp, extra)


def click_wav(path, times, total, sr=48000):
    """打点轨。自己写 RIFF —— 比拼一串 ffmpeg 的 sine+adelay 好读，也不受
    滤镜图长度限制（一首歌几十个点，adelay 链会长到没法看）。"""
    n = int(total * sr) + sr
    buf = bytearray(n * 2)
    for t in times:
        i0 = int(t * sr)
        for k in range(int(0.045 * sr)):
            if i0 + k >= n:
                break
            v = int(16000 * math.exp(-k / (0.008 * sr)) * math.sin(2 * math.pi * 1400 * k / sr))
            struct.pack_into("<h", buf, (i0 + k) * 2, max(-32767, min(32767, v)))
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 36 + len(buf)) + b"WAVEfmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16))
        f.write(b"data" + struct.pack("<I", len(buf)) + bytes(buf))


def cmd_proof(a):
    d = json.load(open(a.json, encoding="utf-8"))
    total = duration(a.song)
    starts = [x["t0"] for x in d["lines"]]
    click_wav("click.wav", starts, total)
    r = _run(["ffmpeg", "-y", "-v", "error", "-i", a.song, "-i", "click.wav",
              "-filter_complex", "[0:a]volume=-4dB[m];[1:a]volume=-6dB[c];"
                                 "[m][c]amix=inputs=2:duration=first:normalize=0",
              "-c:a", "libmp3lame", "-q:a", "3", "proof_click.mp3"])
    if r.returncode:
        sys.exit("!!! 混打点轨失败\n" + r.stderr[-800:])
    print("proof_click.mp3 —— **每句开口处应该正好一声嗒**。")
    print("  嗒在字前面 = 报早了；嗒在字中间 = 报晚了；差多少就把那一句的点挪多少。")
    if not a.video:
        return
    ev = []
    for i, x in enumerate(d["lines"], 1):
        ev.append("Dialogue: 0,%s,%s,P,,0,0,0,,{\\an5\\pos(360,300)}%d. %s"
                  % (_ts(x["t0"]), _ts(x["t1"]), i, x["text"]))
    with open("proof.ass", "w", encoding="utf-8-sig") as f:
        f.write("[Script Info]\nScriptType: v4.00+\nPlayResX: 720\nPlayResY: 480\n"
                "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
                "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
                "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,"
                "ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,"
                "MarginR,MarginV,Encoding\n"
                "Style: P,KaiTi,56,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
                "0,0,0,0,100,100,4,0,1,3,0,5,20,20,20,1\n\n[Events]\n"
                "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
                + "\n".join(ev) + "\n")
    r = _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
              "color=c=black:s=720x480:r=25:d=%.2f" % total, "-i", "proof_click.mp3",
              "-vf", "subtitles=proof.ass,drawtext=fontfile=C\\\\:/Windows/Fonts/consola.ttf:"
                     "text='%{pts\\:hms}':x=20:y=430:fontsize=32:fontcolor=yellow",
              "-c:v", "libx264", "-crf", "26", "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-shortest", "proof.mp4"])
    if r.returncode:
        print("   (预览片没出来，光用 proof_click.mp3 也够验)\n" + r.stderr[-400:])
    else:
        print("proof.mp4 —— 黑底 + 字幕 + 打点 + 走秒。看一遍，按走秒报哪一句差多少。")


def _ts(t):
    return "%d:%02d:%05.2f" % (t // 3600, t % 3600 // 60, t % 60)


def cmd_check(a):
    d = json.load(open(a.json, encoding="utf-8"))
    total = duration(a.song)
    bad = []
    ln = d["lines"]
    for i, x in enumerate(ln):
        if x["t1"] <= x["t0"]:
            bad.append("第 %d 句止 %.2f 不晚于起 %.2f" % (i + 1, x["t1"], x["t0"]))
        if i and x["t0"] < ln[i - 1]["t1"]:
            bad.append("第 %d 句 %.2f 和上一句的尾 %.2f 重叠 —— 竖排两句同屏没法看"
                       % (i + 1, x["t0"], ln[i - 1]["t1"]))
        if x["t1"] > total + 1e-6:
            bad.append("第 %d 句结束于 %.2f，超出歌长 %.2f" % (i + 1, x["t1"], total))
        if x["t1"] - x["t0"] > SUB_HOLD_MAX + 1e-6:
            bad.append("第 %d 句挂屏 %.1fs（上限 %.1fs）—— 中间多半有段间奏，"
                       "该拆成两句或让字幕先下去"
                       % (i + 1, x["t1"] - x["t0"], SUB_HOLD_MAX))
    if ln and ln[0]["t0"] < 0.3:
        bad.append("第一句在 %.2fs 就上屏 —— 前奏还没起，字幕先到了" % ln[0]["t0"])
    print("歌长 %.2fs   %d 句   首句 %.2fs   末句收于 %.2fs"
          % (total, len(ln), ln[0]["t0"] if ln else 0, ln[-1]["t1"] if ln else 0))
    # ---- 换镜余地：**要按真实的唱句空档算，不是按字幕空档** ----
    # 字幕之间的空档是 SUB_GAP 强行留出来的（永远等于 0.40s），拿它当换镜余地
    # 会得出"哪儿都换不了"的错结论。真正的余地是
    # **上一句最后一个强起音 到 下一句起点** 之间那一段。
    st = strong(onsets(a.song))
    print("换镜余地：转场要放进**字幕收掉 到 下一句起点**这一段，两头各留 %.2fs" % XF_PAD)
    room = []
    for i in range(len(ln) - 1):
        prev = max([p[0] for p in st if p[0] < ln[i + 1]["t0"] - 0.05] or [ln[i]["t0"]])
        g = ln[i + 1]["t0"] - ln[i]["t1"]
        mx = max(0.0, g - 2 * XF_PAD)
        room.append(mx)
        print("  %d→%d  末字起音 %.2f   字幕空档 %.2fs   **最长溶解 %.2fs**%s"
              % (i + 1, i + 2, prev, g, mx,
                 "   << 放不下任何转场，这两句合一镜" if mx < 0.08 else ""))
    if room and max(room) < 1.2:
        print("  !! 最宽的一处也只放得下 %.2fs —— **这支歌不能用 XFADE=1.2 的默认值**。"
              % max(room))
        print("     慢速艺术歌曲的乐句几乎是连着的，MV 的转场余地比诗词模式小一个量级；")
        print("     0.2s 的溶解在 30fps 上就是 6 帧，看起来接近硬切 —— 那是对的，不是将就。")
    if bad:
        print("\n!! 问题:")
        for b in bad:
            print("   - " + b)
        return 1
    print("\n结构自检通过。**但结构对不等于同步对** —— 同步只有 proof 听得出来。")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    q = sub.add_parser("probe"); q.add_argument("song")
    q.add_argument("--spec", action="store_true", help="顺便出谱图切片")
    q.add_argument("--spec-len", type=float, default=10.0)
    for name in ("snap", "lrc"):
        q = sub.add_parser(name)
        q.add_argument("song")
        q.add_argument("--lines", help="用 | 分隔的歌词，顺序同演唱")
        q.add_argument("--end", type=float, help="末句收在哪儿（不给按最后一个起音推）")
        q.add_argument("--karaoke", action="store_true", help="顺便算行内逐字落点")
        if name == "snap":
            q.add_argument("--at", required=True, help="每句开口的大致时刻，逗号分隔")
            q.add_argument("--snap-w", type=float, help="吸附窗，默认 %.2f" % SNAP_W)
            q.add_argument("--force", action="store_true")
        else:
            q.add_argument("--lrc", required=True)
            q.add_argument("--no-snap", action="store_true", help="LRC 的时间戳一个字不改")
    q = sub.add_parser("proof"); q.add_argument("song")
    q.add_argument("--json", default="sync.json")
    q.add_argument("--video", action="store_true", help="连预览片一起出")
    q = sub.add_parser("check"); q.add_argument("song")
    q.add_argument("--json", default="sync.json")
    a = p.parse_args()
    if a.cmd == "probe":
        cmd_probe(a)
    elif a.cmd == "snap":
        cmd_snap(a)
    elif a.cmd == "lrc":
        cmd_lrc(a)
    elif a.cmd == "proof":
        cmd_proof(a)
    elif a.cmd == "check":
        sys.exit(cmd_check(a))
    else:
        p.print_help()
