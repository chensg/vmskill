# -*- coding: utf-8 -*-
"""配乐库的登记与检索工具。

    python music_index.py                       # 列出库里所有配乐
    python music_index.py rebuild               # 重量库里所有 mp3，重写 INDEX.md
    python music_index.py add <mp3> --name "..." --prompt "..." --used "《XXX》"
    python music_index.py find --dur 114 --mode story        # **最常用的**

============================ 为什么要有这个库 ============================

生成一条配乐要花额度，而且 **mureka 的封顶实测 180~245s 之间随机、提示词管不住**，
所以"再生成一条"既贵又不可控。而已经生成过的曲子里，有一大半是**落选的候选**——
付过费、量过、结构完全可用，只是当时那一支挑了另一条。

更要紧的是：**判一条曲子能不能用在某支片子上，靠的全是量出来的东西**——
够不够长、有没有中段 breakdown、前奏爬多久、底噪多大。这些量一次就够了，
存下来下次直接筛。只存 mp3 等于每次都要重走一遍。

所以库里存的是 **mp3 + 提示词 + 实测数据 + 用过哪几支**。

============================ 什么时候查库 ============================

**对音乐要求不高的片子先查库**：书评、故事、冷知识、科普——这类片子全程有旁白
盖着，音乐只在句间的缝里露出来，"贴不贴"的余地很大，库里现成的多半够用。

**诗词片多半要新生成**：没有旁白时音乐是唯一的音源，而且配器要跟着画种走
（英式水彩配大提琴、工笔重彩配琵琶），复用等于把上一支的气质搬过来。
但**落选候选值得先翻一遍**——同一个画种做第二支时，上一支的候选 B 常常正合适。

**同一个系列里不要重复用同一条。** 观众记得住。库里记了 `used`，`find` 会标出来。
"""
import argparse
import json
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
# 库放在**仓库外面**：音乐实测 188MB，进 git 会把每次 clone 和两处安装同步都拖垮
# （音效只有 2.7MB，本来可以进仓库，但索引和文件分家会造出"索引说有、文件没有"
# 这种最难查的状态，所以两个库放一起）。
# 默认落在 ani/ 下面（脚本跑在 <片子>/build/，所以 ../../ 就是 ani/）；
# 环境变量 VMSKILL_LIB 可以覆盖。
#
# 解析顺序（**不要按脚本位置算**：这个工具会被复制到各支片子的 build/ 下，
# 按脚本位置算会在每支片子旁边各造一个空库，而库必须只有一个）：
#   1. 环境变量 VMSKILL_LIB
#   2. 从当前目录往上找已经存在的 _素材库（跑在 <片子>/build/ 时会找到 ani/_素材库）
#   3. 从脚本目录往上找
#   4. 都没有 -> 用 <当前目录>/../../_素材库 并**明说**是新建的
def _find_lib():
    env = os.environ.get("VMSKILL_LIB")
    if env:
        return env, "环境变量 VMSKILL_LIB"
    for base, how in ((os.getcwd(), "当前目录往上"), (HERE, "脚本目录往上")):
        d = base
        for _ in range(6):
            c = os.path.join(d, "_素材库")
            if os.path.isdir(c):
                return c, how
            up = os.path.dirname(d)
            if up == d:
                break
            d = up
    return os.path.normpath(os.path.join(os.getcwd(), "..", "..", "_素材库")), "新建"


LIB, LIB_HOW = _find_lib()
MUSIC_DIR = os.path.join(LIB, "music")
INDEX = os.path.join(MUSIC_DIR, "INDEX.md")
META = os.path.join(MUSIC_DIR, "_meta.json")

BANDS = [("<120", "lowpass=f=120"),
         ("120-2k", "highpass=f=120,lowpass=f=2000"),
         ("2k-8k", "highpass=f=2000,lowpass=f=8000"),
         (">8k", "highpass=f=8000")]

VALLEY_THR, VALLEY_MIN = -25.0, 0.4     # 低谷的判定：低于这个响度、且持续这么久


def _run(args):
    return subprocess.run(args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def duration(path):
    r = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "csv=p=0", path])
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def curve(path):
    """瞬时响度曲线 [(t, M), ...]。

    framelog=info 不是 verbose —— ffmpeg 8.x 里 verbose 的逐帧日志要配
    -loglevel verbose 才吐得出来，默认级别下只剩一段 Summary，一行都读不到。
    """
    r = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", path,
              "-af", "ebur128=framelog=info", "-f", "null", "-"])
    out = []
    for ln in r.stderr.splitlines():
        if "t:" in ln and " M:" in ln:
            try:
                out.append((float(ln.split("t:")[1].split()[0]),
                            float(ln.split(" M:")[1].split()[0])))
            except (IndexError, ValueError):
                pass
    return out


def integrated(path):
    r = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", path,
              "-af", "ebur128=framelog=quiet", "-f", "null", "-"])
    m = re.findall(r"I:\s*(-?\d+\.\d+) LUFS", r.stderr)
    return float(m[-1]) if m else None


def rms_db(path, pre=None):
    """分频段用 RMS 不用 LUFS —— K 加权会把低频衰掉，那正是要避开的骗局。"""
    af = (pre + ",") if pre else ""
    r = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", path,
              "-af", af + "astats=metadata=1:reset=0", "-f", "null", "-"])
    m = re.findall(r"RMS level dB:\s*(-?\d+\.\d+|-inf)", r.stderr)
    if not m:
        return None
    return -99.0 if m[-1] == "-inf" else float(m[-1])


def valleys(c):
    """全曲低于 VALLEY_THR 的谷 [(起, 止), ...]。

    **判读的时候要分清两种谷**：结尾的自然收尾无所谓（片子那时已经在淡出），
    中段的 breakdown 才是弃用的理由。存位置就是为了下次能直接判。
    """
    segs, cur = [], None
    for t, m in c:
        if m < VALLEY_THR:
            cur = (cur[0], t) if cur else (t, t)
        elif cur:
            segs.append(cur); cur = None
    if cur:
        segs.append(cur)
    return [[round(a, 1), round(b, 1)] for a, b in segs if b - a >= VALLEY_MIN]


def intro_ramp(c):
    """前奏爬多久：曲子第一次进入"正常体量"（中位响度 −3dB 以内）的时刻。

    生成的配乐几乎一定自带一段弱前奏或爬坡，再叠一个长淡入，成片开头七八秒
    基本是静音。这个数直接告诉你 MUSIC_IN 至少要躲开多少。
    """
    if not c:
        return None
    live = sorted(m for _, m in c if m > -70)
    if not live:
        return None
    med = live[len(live) // 2]
    for t, m in c:
        if m >= med - 3.0:
            return round(t, 1)
    return round(c[-1][0], 1)


def measure(path):
    c = curve(path)
    live = [m for _, m in c if m > -70]
    d = duration(path)
    integ = integrated(path)
    floor = min(live) if live else None
    return {
        "duration": round(d, 1) if d else None,
        "lufs": integ,
        "floor": round(floor, 1) if floor is not None else None,
        # 底噪余量 = 整合响度 − 最安静的一刻。生成的曲子一般 >40dB；
        # <30dB 多半有一层持续的嘶声（老转录常见），音乐压到 −25dB 后它会跟着上来
        "floor_gap": (round(integ - floor, 1)
                      if (integ is not None and floor is not None) else None),
        "intro": intro_ramp(c),
        "valleys": valleys(c),
        "bands": {n: rms_db(path, f) for n, f in BANDS},
    }


def load_meta():
    if os.path.exists(META):
        with open(META, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_meta(m):
    os.makedirs(MUSIC_DIR, exist_ok=True)
    with open(META, "w", encoding="utf-8", newline="\n") as f:
        json.dump(m, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def mid_valleys(e):
    """真正要紧的那些谷：**既不在前奏里、也不在收尾里**的。

    第一版把"末尾 6 秒以外"的全算进来，于是每条曲子都背着三四个假的中段谷 ——
    因为生成的配乐**几乎一定**自带一段弱前奏，那一段本来就低于 −25 LUFS。
    而 `MUSIC_IN` 无论如何都会跳过前奏（`pick` 就是干这个的），
    把它算成缺陷等于按"每条曲子都有的毛病"去排序，排出来的名次是假的。

    所以两头都掐掉：前奏爬坡之前的不算，最后 6 秒（片尾淡出会盖住）的不算。
    """
    d = e.get("duration") or 0
    intro = e.get("intro") or 0.0
    return [v for v in (e.get("valleys") or [])
            if v[1] > intro + 0.2 and v[1] < d - 6.0]


def unavoidable(e, dur):
    """**躲不开的谷**：给定片长 dur，无论切入点选在哪都会落进正片的那些。

    这才是 find 该问的问题。片子可以从 [0, 余地] 里的任何一点切入，
    所以曲上时刻 v 的谷：
      - v 在余地之前（v < room）  -> 切晚一点就躲开了
      - v 在片长之后（v > dur）   -> 切早一点（从 0 开始）就够不到
      - 两者都不是                -> **每一个切入点都会撞上它**，这才是硬伤

    第一版按"不在前奏、不在末尾 6 秒"数，那是个和片长无关的粗筛，
    会把"从 0 秒切入就永远够不到"的收尾谷也算成缺陷（声声慢 220s 处那个），
    于是一条完全可用的曲子被排到后面去。
    """
    d = e.get("duration") or 0
    room = max(0.0, d - dur)
    return [v for v in (e.get("valleys") or []) if v[0] >= room and v[1] <= dur]


def write_index(meta):
    rows = ["# 配乐库\n",
            "生成一条配乐要花额度，而 **mureka 的封顶实测 180~245s 随机、提示词管不住**，",
            "所以「再生成一条」既贵又不可控。库里一大半是**落选的候选**——",
            "付过费、量过、结构可用，只是当时那一支挑了别的。\n",
            "查库：`python music_index.py find --dur <片长> --mode story|poem`\n",
            "## 怎么读这张表\n",
            "- **余地 = 全曲 − 片长**，是这条曲子好不好用的第一判据。",
            "  诗词片要 ≥ 片长的 0.6 倍，讲述片 ≥ 0.4 倍（全程有旁白盖着，要挑的落点少）。",
            "- **中段谷**：落在曲子末尾的是自然收尾，不算问题；",
            "  落在中间的 breakdown 才是弃用的理由。",
            "- **前奏**：曲子进入正常体量的时刻。`MUSIC_IN` 至少要躲开它。",
            "- **底噪余量**：整合响度 − 最安静的一刻。<30dB 多半有持续嘶声。",
            "- 音色贴不贴**量不出来**，最终要听。这张表只负责把不可能的排除掉。\n",
            "| 文件 | 名称 | 时长 | LUFS | 前奏 | 底噪余量 | 谷(中段/全部) | 用过 |",
            "|---|---|---|---|---|---|---|---|"]
    for fn in sorted(meta):
        e = meta[fn]
        used = "；".join(e.get("used", [])) or "—"
        rows.append("| `%s` | %s | %.0fs | %s | %s | %s | %d/%d | %s |" % (
            fn, e.get("name", ""), e.get("duration") or 0,
            "%.1f" % e["lufs"] if e.get("lufs") is not None else "—",
            "%.1fs" % e["intro"] if e.get("intro") is not None else "—",
            "%.0fdB" % e["floor_gap"] if e.get("floor_gap") is not None else "—",
            len(mid_valleys(e)), len(e.get("valleys") or []),
            used))
    rows.append("")
    for fn in sorted(meta):
        e = meta[fn]
        rows.append("### `%s` — %s\n" % (fn, e.get("name", "")))
        if e.get("tags"):
            rows.append("标签：%s\n" % " ".join(e["tags"]))
        if e.get("valleys"):
            rows.append("低谷段（< %.0f LUFS）：%s\n"
                        % (VALLEY_THR,
                           "  ".join("%.1f~%.1fs" % (a, b) for a, b in e["valleys"])))
        b = e.get("bands") or {}
        if any(v is not None for v in b.values()):
            rows.append("频段 RMS：%s\n"
                        % "  ".join("%s %.1f" % (k, v) for k, v in b.items()
                                    if v is not None))
        if e.get("prompt"):
            rows.append("生成提示词：\n")
            rows.append("```\n%s\n```\n" % e["prompt"].strip())
        if e.get("used"):
            rows.append("用过：%s\n" % "；".join(e["used"]))
        if e.get("note"):
            rows.append("> %s\n" % e["note"])
    os.makedirs(MUSIC_DIR, exist_ok=True)
    with open(INDEX, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(rows))


def cmd_rebuild(a):
    meta = load_meta()
    if not os.path.isdir(MUSIC_DIR):
        sys.exit("!!! 库还不存在: " + MUSIC_DIR)
    seen = set()
    for fn in sorted(os.listdir(MUSIC_DIR)):
        if not fn.lower().endswith((".mp3", ".wav", ".m4a")):
            continue
        seen.add(fn)
        e = meta.setdefault(fn, {})
        if a.only_new and e.get("duration"):
            continue
        e.update(measure(os.path.join(MUSIC_DIR, fn)))
        print("量过 %-34s %5.0fs  LUFS %6.1f  前奏 %5s  底噪余量 %5s  谷 %d"
              % (fn[:34], e["duration"] or 0, e["lufs"] or -99,
                 e["intro"], e["floor_gap"], len(e["valleys"])))
    for fn in [k for k in meta if k not in seen]:
        print("!! %s 在 _meta.json 里但文件不在了" % fn)
    save_meta(meta)
    write_index(meta)
    print("\nINDEX.md 已重写，共 %d 条" % len(seen))


def cmd_add(a):
    fn = os.path.basename(a.mp3)
    os.makedirs(MUSIC_DIR, exist_ok=True)
    dst = os.path.join(MUSIC_DIR, fn)
    if os.path.abspath(a.mp3) != os.path.abspath(dst):
        with open(a.mp3, "rb") as s, open(dst, "wb") as d:
            d.write(s.read())
    meta = load_meta()
    e = meta.setdefault(fn, {})
    e.update(measure(dst))
    for k in ("name", "prompt", "note"):
        if getattr(a, k):
            e[k] = getattr(a, k)
    if a.tags:
        e["tags"] = [t for t in a.tags.split(",") if t]
    if a.used:
        e.setdefault("used", [])
        if a.used not in e["used"]:
            e["used"].append(a.used)
    save_meta(meta)
    write_index(meta)
    print("已登记 %s" % fn)


def cmd_list(a):
    meta = load_meta()
    if not meta:
        print("库是空的。先跑 rebuild 或 add")
        return
    print("%-34s %-16s %6s %7s %7s %8s %6s" %
          ("文件", "名称", "时长", "LUFS", "前奏", "底噪余量", "中段谷"))
    for fn in sorted(meta):
        e = meta[fn]
        print("%-34s %-16s %5.0fs %7.1f %6ss %7sdB %6d"
              % (fn[:34], (e.get("name") or "")[:16], e.get("duration") or 0,
                 e.get("lufs") or -99, e.get("intro"), e.get("floor_gap"),
                 len(mid_valleys(e))))


def cmd_find(a):
    """给定片长，把库里能用的排出来。**排序是机械的，最终要听。**

    硬过滤只有一条：余地够不够。其余都只打分不淘汰 —— 因为"中段有谷"这件事
    是否致命，取决于切入点，而切入点要跑 pick 才知道。
    """
    meta = load_meta()
    if not meta:
        sys.exit("库是空的。先跑 rebuild")
    # 余地的推荐值：诗片 0.6 倍（没有旁白，音乐是唯一音源，更怕某处塌下去），
    # 讲述片 0.4 倍。**但这只是推荐，不是硬过滤** —— 第一版拿它当硬门槛，
    # 160s 的片子要求全曲 ≥224s，19 条里只剩 3 条，等于把库废掉一多半。
    # 真正的硬条件只有一条：曲子得够长。余地紧不紧，标出来让人自己权衡。
    need = 0.6 if a.mode == "poem" else 0.4
    print("")
    print("=== 片长 %.0fs / %s模式 ===" % (a.dur, "诗词" if a.mode == "poem" else "讲述"))
    print("    硬条件：全曲 ≥ 片长。余地推荐 ≥ %.0fs（片长的 %.1f 倍），"
          "不够的会标出来" % (a.dur * need, need))
    cand = []
    for fn, e in meta.items():
        d = e.get("duration") or 0
        room = d - a.dur
        if room < 0:
            continue
        if a.tag and a.tag not in (e.get("tags") or []):
            continue
        if a.exclude_used and any(a.exclude_used in u for u in e.get("used", [])):
            continue
        mid = unavoidable(e, a.dur)
        cand.append((len(mid), -room, fn, e, room, mid))
    if not cand:
        print("  没有符合的。放宽 --dur 或者去生成一条新的。")
        return
    cand.sort()
    print("")
    print("  %-32s %6s %6s %6s %8s %s" % ("文件", "全曲", "余地", "前奏", "躲不开的谷", "用过"))
    for _, _, fn, e, room, mid in cand:
        used = "；".join(e.get("used", [])) or "—"
        tight = " 余地紧" if room < a.dur * need else ""
        print("  %-32s %5.0fs %5.0fs%-4s %5.1fs %6d %s"
              % (fn[:32], e.get("duration") or 0, room, tight,
                 e.get("intro") or 0, len(mid), used[:26]))
        if mid:
            print("       躲不开的谷：%s"
                  % "  ".join("%.1f~%.1fs" % (x[0], x[1]) for x in mid[:4]))
    print("")
    print("  排在前面 = 躲不开的谷少、余地大。**这是机械排序，不是推荐**：")
    print("  音色贴不贴量不出来。挑 2~3 条给用户听，最终选择交回去。")
    print("  选定之后把它复制成 素材/00_music_main.mp3，跑 pick 选切入点，")
    print("  再回来 `add` 一次记上 --used，下次才知道它用过了。")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    pr = sub.add_parser("rebuild")
    pr.add_argument("--only-new", action="store_true", help="只量还没量过的")
    pa = sub.add_parser("add")
    pa.add_argument("mp3")
    for opt in ("--name", "--prompt", "--note", "--tags", "--used"):
        pa.add_argument(opt)
    pf = sub.add_parser("find")
    pf.add_argument("--dur", type=float, required=True, help="片长（秒）")
    pf.add_argument("--mode", choices=("poem", "story"), default="story")
    pf.add_argument("--tag")
    pf.add_argument("--exclude-used", help="排除用过某个系列的（避免同系列重复）")
    a = p.parse_args()
    print("库: %s  (%s)" % (MUSIC_DIR, LIB_HOW))
    if LIB_HOW == "新建" and a.cmd not in ("rebuild", "add"):
        print("**没找到已有的库。** 要么设 VMSKILL_LIB，要么先 add / rebuild 建起来。")
    {"rebuild": cmd_rebuild, "add": cmd_add, "find": cmd_find}.get(
        a.cmd, cmd_list)(a)
