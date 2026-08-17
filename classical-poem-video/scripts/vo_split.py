# -*- coding: utf-8 -*-
"""把**一整条真人朗读**切成一句一个文件，供诗词模式的 VO 链路使用。

    python vo_split.py analyze 朗读.mp3 --n 11          # 先看切不切得开
    python vo_split.py split   朗读.mp3 --lines "东风夜放花千树|更吹落、星如雨|..."
    python vo_split.py split   朗读.mp3 --from-make-v   # 直接读 make_v.py 的 LINES
    python vo_split.py split   朗读.mp3 --n 11 --cuts 5.2,9.8,...   # 手工指定切点

======================== 为什么只做"切开"这一件事 ========================

流水线里**诵读那条链路已经是完整的**：落点按出声点排（不是文件起点，
TTS/真人每条头部静音都不一样）、不能跨转场、必须在字幕消失前读完、
音乐侧链躲闪 —— 这些 `make_v.py` 里的 `vo_plan` / `check_vo` / `vosync` 都做了，
但它们要求**一句一个文件**。

真人朗读拿到的是一整条。所以要补的只有"切开"，切完把文件名填进 `VO` 表，
下游一行都不用改。

======================== 怎么切才靠得住 ========================

**不要按"检测到几段静音就切几刀"。** 读七言常常是 4+3，句内自带停顿；
读到长句还会换气。按静音数切必然多切。

正确做法是**利用已知的句数 N**：把所有句间候选静音按时长排序，
取最长的 N−1 个当切点。句内的换气一定比句间的停顿短 —— 这是朗读的物理事实，
比任何阈值都稳。

**首尾都只留一点点留白**（头 0.12s、尾 0.20s），不留到停顿正中间。
留多了两头都出问题，见 `bounds_from()` 的注释 —— 一句话：`check_vo` 按**文件时长**
判"读不读得完"，而 `vo_plan` 的落点有个 `max` 钳位会被大的头静音顶住。
剪完实测每段时长和逐句原件只差 0.02~0.19s。

**切完必须验，而且要两层，因为两种错法的形状不一样**（都是造出来实测的）：

  一、**少数几段错**（句数给少了、两句被并成一段）：
      按 `时长 ≈ a×字数 + b` 拟合，看逐段残差。截距吸收每句的固定开销，
      所以短句不会天然显得慢 —— 这是纯"字/秒"比值的病根。
      残差要**相对（3 倍中位绝对残差）和绝对（0.8s）同时超标**才算数。

  二、**多数段都错**（句数给多了，从换气处多切一刀，之后全体错位）：
      这时 MAD 被自己抬高，**逐段残差谁都不显得离群** —— MAD 类判据的经典失效。
      所以再查拟合**本身**：斜率在不在合理区间、残差占平均时长多少。
      实测：正确 0.46 秒/字 · 3%；少切一句 0.77 · 13%；多切一句 0.25 · 14%。

第一版只做了"字/秒相对中位"，**漏掉第一种错法**（合并段是中位的 0.78 倍，
而带子下限是 0.55）。**只验"现在通过"等于没验** —— 两种错法都要造出来试过。
"""
import argparse
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 自动试的检测档位：从严到松。第一个能给出足够多句间候选的胜出。
TRIES = [(-45, 0.35), (-45, 0.25), (-40, 0.30), (-40, 0.22),
         (-35, 0.25), (-35, 0.18), (-30, 0.20)]
PUNCT = "，。：；、？！｜|「」《》·—…“”‘’ \t"
# 离群判据：**不用"字/秒相对中位数"**。那个判据漏掉了最该抓的错误 ——
# 实测把 11 句错切成 10 句（末尾并了两句），合并段的字/秒是中位数的 0.78 倍，
# 而要抓住它得把下限收到 0.8，那就离"调常数迁就数据"只有一步了
# （`make_story_v.py` 的 check_pace 注释里骂过这种做法）。
#
# 改成**线性拟合的残差**：`时长 ≈ a×字数 + b`。截距 b 吸收每句的固定开销
# （起音、换气、句末余韵），所以短句不再天然显得"慢" —— 这正是纯比值的病根。
# 实测分得很开：正确切分最大残差 1.8 倍中位绝对残差，错切 3.7 倍。取 3.0。
#
# 顺带一个旁证：正确切分拟合出来是 **每字 0.43s + 固定 1.29s**，
# 而流水线的可读下限是 0.45 / 1.8 —— 真人朗读的节奏和它本来就对得上。
# **相对倍数还不够，要配一条绝对下限。** 把每段尾巴剪掉之后拟合紧了一倍
# （中位绝对残差 0.24s -> 0.10s），固定的 3 倍阈值立刻开始误报：
# 正确切分里有两段落在 3.3~3.9 倍，而它们只是读得略有起伏。
# 判据本身没错，是"相对倍数"这个形状在拟合很紧时会自己收窄。
#
# 绝对下限锚在**错误的物理尺度**上，不是调出来的：结构性切错意味着多了或少了
# 一整句 —— 合并段多一整句 + 一处停顿（3~5s），从换气处切断少半句（1.5~2s）。
# 而自然起伏实测 ≤0.4s。取 0.8s，两边都留了两倍余量。
RESID_K = 3.0
RESID_MIN = 0.8      # 秒。相对和绝对**同时**超标才算离群
MIN_FIT = 6          # 少于这么多句，拟合不稳，退回比值判据并说明
PACE_LO, PACE_HI = 0.55, 1.80        # 退化时用的比值区间

# ---- 还要查拟合**本身**成不成立 ----
# 残差判据只抓得住"少数几段错"。**切多了的时候是多数段都错**（从换气处多切一刀，
# 后面全体错位），这时 MAD 自己被抬高，没有哪一段显得离群 —— MAD 类判据的经典失效。
# 实测三种情形：
#   正确切分   斜率 0.43  中位绝对残差/平均时长 = 6%
#   少切一句   斜率 0.75  8%   （残差判据已经抓住）
#   多切一句   斜率 0.19  19%  （只有这一层抓得住）
# 斜率的合理区间锚在流水线自己的可读常数 READ_PER_CHAR=0.45 上，不是拍的；
# 6% 和 19% 之间有三倍差，取 12%。
SLOPE_LO, SLOPE_HI = 0.25, 0.70
MAD_RATIO_MAX = 0.12


def _run(a):
    return subprocess.run(a, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def duration(p):
    r = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "csv=p=0", p])
    try:
        return float(r.stdout.strip())
    except ValueError:
        sys.exit("!!! 读不出时长: " + p)


def silences(path, thr, mind):
    """[(起, 止), ...]。silencedetect 只给边界，要自己配对。"""
    r = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", path,
              "-af", "silencedetect=n=%ddB:d=%.2f" % (thr, mind), "-f", "null", "-"])
    out, st = [], None
    for ln in r.stderr.splitlines():
        if "silence_start:" in ln:
            try:
                st = float(ln.split("silence_start:")[1].split()[0])
            except (IndexError, ValueError):
                st = None
        elif "silence_end:" in ln and st is not None:
            try:
                out.append((st, float(ln.split("silence_end:")[1].split()[0])))
            except (IndexError, ValueError):
                pass
            st = None
    return out


def merge_blips(sils, blip=0.06):
    """把被"零长度有声"打断的相邻静音并回去。

    **这是真录音才有的坑，合成的测试文件不会有。** 实测一条真人朗读里，
    ffmpeg 在 3.587664 报 silence_end、又在 3.587778 报 silence_start ——
    中间 0.1 毫秒"有声"，是一声细微的咔哒或唇音。于是一段 2.32 秒的停顿
    被报成 0.63 + 1.22 + 0.47 三截。

    后果很重：整个切分靠的是"取最长的 N−1 处停顿"，而一段真正的长停顿
    被打碎之后，它的每一截都可能短于句内的换气 —— 排序整个失真。

    所以先把间隔小于 blip 的相邻静音并起来，再谈长短。
    """
    out = []
    for a, b in sils:
        if out and a - out[-1][1] < blip:
            out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def interior(sils, total, edge=0.05):
    """去掉贴着头尾的那两段 —— 它们是录音的前后留白，不是句间停顿。"""
    return [(a, b) for a, b in sils if a > edge and b < total - edge]


def pick(path, n_lines):
    """选出 n_lines-1 个切点。返回 (选中的停顿区间, 用的档位, 候选数, 总长, 尾静音起点)。"""
    total = duration(path)
    need = n_lines - 1
    for thr, mind in TRIES:
        sils = merge_blips(silences(path, thr, mind))
        cand = interior(sils, total)
        if len(cand) >= need:
            # **按时长取最长的 need 个**：句内换气一定比句间停顿短，
            # 这是朗读的物理事实，比调阈值稳
            top = sorted(cand, key=lambda s: s[1] - s[0], reverse=True)[:need]
            gaps = sorted(top)
            # 录音首尾的留白（贴着开头/结尾那两段静音）
            head = next((b for a, b in sils if a <= 0.05), None)
            tail = next((a for a, b in sils if b >= total - 0.05), None)
            return gaps, (thr, mind), len(cand), total, (head, tail)
    return None, None, 0, total, (None, None)


def bounds_from(gaps, total, edges, head_pad, tail_pad):
    """由选中的停顿算每段的 [起, 止]。**首尾都只留一点点留白。**

    第一版留到停顿正中间，两头都出问题：

    **尾巴**：`check_vo` 的「必须在字幕消失前读完」是拿**文件时长**判的，
    尾巴上挂半截停顿会让它按虚长的时长判，白白收紧时间轴（实测每段多挂
    0.08~0.63s）。

    **头**：`vo_plan` 里落点是 `max(s, s + VO_LEAD - 出声点)` —— 出声点一旦
    超过 `VO_LEAD`（默认 0.5s）就会撞上那个 `max` 钳位，语音被推后。
    实测留到正中间时有 5 段的头静音在 0.57~0.76s，全都会撞。
    剪到 head_pad 之后出声点恒等于它，永远够不到钳位。

    留一点点而不是剪到零：太贴近起音会削掉辅音的头，而 `VO_FADE`(0.06s)
    的淡入也需要一点地方。
    """
    head, tail = edges
    first = max(0.0, (head if head else 0.0) - head_pad)
    starts = [first] + [max(0.0, b - head_pad) for a, b in gaps]
    ends = [min((a + b) / 2, a + tail_pad) for a, b in gaps]
    ends.append(min(total, (tail + tail_pad) if tail else total))
    return list(zip(starts, ends))


def n_chars(s):
    return sum(1 for c in s if c not in PUNCT)


def report(path, texts, segs, level, ncand, skip=()):
    print("")
    print("=== 切点 ===")
    if level:
        print("   检测档位 %ddB / %.2fs，句间候选 %d 处，取最长的 %d 处当切点"
              % (level[0], level[1], ncand, len(segs) - 1))
    rows, paces = [], []
    for i, (a, b) in enumerate(segs):
        t = texts[i] if i < len(texts) else ""
        c = n_chars(t)
        d = b - a
        pace = (c / d) if (c and d > 0.01) else None
        rows.append((i + 1, a, b, d, t, c, pace))
        if pace:
            paces.append(pace)
    med = sorted(paces)[len(paces) // 2] if paces else None
    resid, mad, fit = fit_residuals(rows, skip)
    batch_bad = False
    print("")
    if fit:
        print("  拟合：时长 ≈ %.2f×字数 + %.2f   中位绝对残差 %.2fs"
              % (fit[0], fit[1], mad))
    print("  段  起      止      时长   字数  字/秒   残差")
    bad, lone = [], []
    for k, (i, a, b, d, t, c, pace) in enumerate(rows):
        flag = ""
        if resid is not None and resid[k] is None:
            show = "（不进拟合）"
        elif resid is not None and mad > 1e-6:
            r = resid[k]
            show = "%+.2f(%.1fx)" % (r, abs(r) / mad)
            if abs(r) > RESID_K * mad and abs(r) > RESID_MIN:
                if paired(resid, k):
                    flag = "  << 离群，且邻段反向 —— **多半真的切错了**"
                    bad.append(i)
                else:
                    flag = "  << 偏差大但**孤立**（邻段没有反向），多半是朗读处理"
                    lone.append(i)
        else:
            rel = (pace / med) if (pace and med) else None
            show = "%.2f" % rel if rel else "—"
            if rel is not None and not (PACE_LO <= rel <= PACE_HI):
                flag = "  << 离群，多半切错了"
                bad.append(i)
        print("  %-3d %6.2f  %6.2f  %5.2f  %4d  %5s  %11s%s  %s"
              % (i, a, b, d, c, "%.1f" % pace if pace else "—", show, flag, t[:14]))
    if resid is None:
        print("")
        print("  （少于 %d 句，拟合不稳，退回「字/秒相对中位」的粗判据）" % MIN_FIT)
    elif fit:
        # 拟合本身成不成立。**这一层是给"多数段都错"准备的** ——
        # 那种情形下 MAD 被自己抬高，逐段残差谁都不显得离群。
        mean_d = sum(r[3] for r in rows) / len(rows)
        ratio = mad / mean_d if mean_d > 0.01 else 9.9
        why = []
        if not (SLOPE_LO <= fit[0] <= SLOPE_HI):
            why.append("斜率 %.2f 秒/字 不在合理区间 [%.2f, %.2f]"
                       % (fit[0], SLOPE_LO, SLOPE_HI))
        if ratio > MAD_RATIO_MAX:
            why.append("中位绝对残差占平均时长 %.0f%%（上限 %.0f%%）"
                       % (100 * ratio, 100 * MAD_RATIO_MAX))
        print("  拟合成色：斜率 %.2f 秒/字，残差占比 %.0f%%" % (fit[0], 100 * ratio))
        if why:
            print("")
            print("  !! **整体拟合不成立**：" + "；".join(why))
            print("     这不是某一段的问题，是**段和句子整体对不上** ——")
            print("     多半是句数给错了，从某处起全体错位。先确认句数，再看切点。")
            batch_bad = True
    if bad:
        print("")
        print("  !! %d 段离群：%s" % (len(bad), ", ".join(str(i) for i in bad)))
        print("     多半是两句被并成一段、或者从句子中间切断了。")
        print("     用 --cuts 手工指定切点重来，或者换个检测档位。")
    elif not batch_bad and not lone:
        print("")
        print("  没有离群段，整体拟合也成立。")
    if lone and not bad:
        print("")
        print("  %d 段偏差大但孤立：%s" % (len(lone), ", ".join(str(i) for i in lone)))
        print("     **切错一刀会把时间从一段搬到邻段，所以一定成对出现、一正一负。**")
        print("     这几段的邻居没有反向偏差，所以更像是朗读本身的处理")
        print("     （末句渐慢、某句加重最常见）。不拦，但值得听一遍那一段。")
    return segs, (bad or ([0] if batch_bad else []))


def paired(resid, k, frac=0.5):
    """段 k 的偏差**是不是结构性切错**：看相邻段有没有反号的、量级相当的偏差。

    这一条来自一个物理事实：**总时长是固定的**。切错一刀是把时间从一段搬到
    相邻那一段，所以结构性错误一定成对出现、一正一负。而朗读本身的处理
    （末句渐慢、某句加重）是**孤立的**单向偏差，邻居不动。

    实测的两种情形正好是这两个形状：
      - 把「蓦然回首」并进末句 -> 那一段 +1.28s，而它本该独立的邻居消失了
      - 「恰似一江春水向东流」读慢了 -> 那一段 +1.52s，邻居残差只有 +0.01s

    分不开的时候宁可说"分不开"，也不要靠调阈值把某一种压下去 ——
    两者的量级本来就一样（都是 1~2 秒），**光看大小是不可能分开的**。
    """
    r = resid[k]
    for j in (k - 1, k + 1):
        if 0 <= j < len(resid) and resid[j] is not None:
            if r * resid[j] < 0 and abs(resid[j]) >= frac * abs(r):
                return True
    return False


def fit_residuals(rows, skip=()):
    """按 `时长 ≈ a×字数 + b` 拟合，返回 (残差, 中位绝对残差, (a,b))。

    用带截距的线性拟合而不是"字/秒"：截距吸收每句的固定开销（起音、换气、
    句末余韵），短句才不会天然显得慢。理由见 RESID_K 处的注释。

    `skip` 是**不参与拟合**的段号（1 起）。**朗读带标题和作者时必须用它**：
    标题/作者是另一种说话方式，实测 1.8~2.9 字/秒，而诗正文是 1.2~1.6 ——
    混进同一个拟合会把斜率从 0.64 拽到 0.76，直接顶出合理区间，
    于是一个完全正确的切分被判成"整体对不上"。（《虞美人》那条真人朗读踩的）
    被 skip 的段照切照显示，只是不进拟合、也不判离群。
    """
    # **残差要逐行对齐**：过滤之后按下标取会错位，而错位的残差比没有残差更糟
    use = [(k, c, d) for k, (_, _, _, d, _, c, _) in enumerate(rows)
           if c > 0 and d > 0.01 and (k + 1) not in skip]
    if len(use) < MIN_FIT or len({c for _, c, _ in use}) < 2:
        return None, 0.0, None
    n = len(use)
    mc = sum(c for _, c, _ in use) / n
    md = sum(d for _, _, d in use) / n
    sxx = sum((c - mc) ** 2 for _, c, _ in use)
    if sxx < 1e-9:
        return None, 0.0, None
    a = sum((c - mc) * (d - md) for _, c, d in use) / sxx
    b = md - a * mc
    res = [None] * len(rows)
    for k, c, d in use:
        res[k] = d - (a * c + b)
    ar = sorted(abs(r) for r in res if r is not None)
    return res, ar[len(ar) // 2], (a, b)


def cmd_analyze(a):
    texts = get_texts(a)
    n = len(texts) if texts else a.n
    if not n:
        sys.exit("!!! 要么给 --lines / --from-make-v，要么给 --n")
    gaps, level, ncand, total, edges = pick(a.mp3, n)
    print("整条 %.2fs，要切成 %d 段" % (total, n))
    if gaps is None:
        print("")
        print("!! 所有档位都凑不够 %d 处句间停顿。" % (n - 1))
        print("   可能是：朗读连得太紧（句间没有明显停顿）、底噪太高、")
        print("   或者 --n 给多了。用 `--cuts` 手工指定切点。")
        sys.exit(1)
    report(a.mp3, texts, bounds_from(gaps, total, edges, a.head_pad, a.tail_pad),
           level, ncand, _skip(a))
    print("")
    print("  确认无误就跑 split。")


def cmd_split(a):
    texts = get_texts(a)
    n = len(texts) if texts else a.n
    if not n:
        sys.exit("!!! 要么给 --lines / --from-make-v，要么给 --n")
    total = duration(a.mp3)
    if a.cuts:
        cuts = sorted(float(x) for x in a.cuts.split(","))
        if len(cuts) != n - 1:
            sys.exit("!!! --cuts 给了 %d 个切点，但 %d 句需要 %d 个"
                     % (len(cuts), n, n - 1))
        # 手工切点是"在这一刻切开"，没有停顿区间可言，就直接首尾相接
        b = [0.0] + cuts + [total]
        segs, level, ncand = [(b[i], b[i + 1]) for i in range(len(b) - 1)], None, 0
    else:
        gaps, level, ncand, total, edges = pick(a.mp3, n)
        if gaps is None:
            sys.exit("!!! 凑不够切点，先跑 analyze 看看")
        segs = bounds_from(gaps, total, edges, a.head_pad, a.tail_pad)
    segs, bad = report(a.mp3, texts, segs, level, ncand, _skip(a))
    if bad and not a.force:
        sys.exit("\n!!! 有离群段，没有写文件。改 --cuts，或者确认没问题后加 --force")
    os.makedirs(a.out, exist_ok=True)
    for i, (s, e) in enumerate(segs, 1):
        dst = os.path.join(a.out, "VO_%02d.mp3" % i)
        # -ss 放在 -i **之前**是输入定位，这里是纯音频、没有字幕滤镜，
        # 所以不受"PTS 被重置"那个坑影响（那条只咬 subtitles 滤镜）。
        # 用 -c copy 会切到最近的帧边界、有几十毫秒误差，所以重编码。
        r = _run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % s,
                  "-to", "%.3f" % e, "-i", a.mp3,
                  "-c:a", "libmp3lame", "-q:a", "2", dst])
        if r.returncode != 0:
            sys.exit("!!! 切第 %d 段失败\n%s" % (i, r.stderr[-500:]))
    print("")
    print("%d 段 -> %s/VO_01..VO_%02d.mp3" % (len(segs), a.out, len(segs)))
    print("")
    print("接下来（下游一行都不用改，诵读链路本来就是按一句一文件设计的）：")
    print("  1. 把 VO 表填成 [(\"句子\", \"VO_01.mp3\"), ...]，顺序和 LINES 一致")
    print("  2. `python make_v.py vosync` —— 打落点表，看每句的出声点、余量、语速")
    print("  3. `python make_v.py check` —— 验不跨转场、且在字幕消失前读完")
    print("  4. 只重跑 `c`（诵读只进混音和字幕那一趟，a/b 不受影响）")


def _skip(a):
    return {int(x) for x in (a.fit_skip or "").split(",") if x.strip()}


def get_texts(a):
    if a.lines:
        return [t for t in a.lines.split("|") if t.strip()]
    if getattr(a, "from_make_v", False):
        sys.path.insert(0, os.getcwd())
        try:
            import make_v as M
        except ImportError:
            sys.exit("!!! 当前目录没有 make_v.py")
        return [t for _, _, t, sty in M.LINES if sty == "M"]
    return []


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    for name in ("analyze", "split"):
        s = sub.add_parser(name)
        s.add_argument("mp3")
        s.add_argument("--n", type=int, help="句数（不给 --lines 时用）")
        s.add_argument("--lines", help="用 | 分隔的句子，顺序同 LINES")
        s.add_argument("--from-make-v", action="store_true",
                       help="从当前目录的 make_v.py 读 LINES 里样式为 M 的句子")
        s.add_argument("--cuts", help="手工指定切点，逗号分隔（秒）")
        s.add_argument("--out", default="vo")
        s.add_argument("--tail-pad", type=float, default=0.20,
                       help="每段末尾留多少秒余韵（默认 0.20）")
        s.add_argument("--head-pad", type=float, default=0.12,
                       help="每段开头留多少秒（默认 0.12，必须小于 VO_LEAD）")
        s.add_argument("--fit-skip", default="",
                       help="不参与拟合的段号，逗号分隔。**朗读带标题/作者时要用**："
                            "它们的语速和正文不是一回事，混进拟合会把斜率带偏")
        s.add_argument("--force", action="store_true", help="有离群段也照切")
    a = p.parse_args()
    if a.cmd == "split":
        cmd_split(a)
    elif a.cmd == "analyze":
        cmd_analyze(a)
    else:
        p.print_help()
