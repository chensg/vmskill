"""讲述片引擎 —— 横版 make_story_h.py 和竖版 make_story_v.py **共用这一份**。

**不要直接跑这个文件。** 模板在配置块之后把它 `exec` 进自己的命名空间：

    _CORE = os.path.join(HERE, "story_core.py")
    exec(compile(open(_CORE, encoding="utf-8").read(), _CORE, "exec"))

于是这里的每个函数读的都是**模板自己的**全局变量（CLIPS、W、SUB_MODE ……）。
不用普通 `import` 是有原因的：import 进来的函数读的是引擎模块自己的全局，
`segment_config.py` 的覆盖、测试里的 `m.W = 320` 就都改了个寂寞 —— 而且不报错。

==== 为什么拆出来（2026-09-25）====
横竖两份原来是手抄副本。拆之前量过：112 个同名函数里 **50 个已经分叉**，
不少是一边修了 bug、另一边没跟上：
  - 竖版 pass_b 在淡场为 0 时照写 `fade d=0` —— ffmpeg 会退回 25 帧，塞进 0.83s 黑场
  - 竖版 alimiter 没写 `level=disabled` —— 限完又被抬回 0 dBFS，等于没限
  - 竖版 SFX 写绝对秒数 —— 改一条旁白后面全错位（横版早改成镜号＋偏移）
  - 竖版 preview / check_credits / check_reuse 不认视频镜，一遇到就 KeyError
  - 横版 check_resolution 修过的「拿长边当短边、pp 虚报 1.78 倍」那条，竖版的写法碰巧没错
现在引擎只有一份。横竖的差别写成**配置**（W/H → LAYOUT、SUB_MODE、SEG_*、HARD_LIMIT、
SAFE_*），在同一个函数里用 `if` 并排摆着 —— 改一边的时候另一边就在眼前。

==== 三条规矩 ====
1. 模板里**只放配置，不放函数**。`tests/test_intermediates.py` 会拦。
2. 引擎的可调常数一律用 `_default()` 声明：模板写了就用模板的，没写才用这里的。
   在这里直接赋值会把模板的配置**静默盖掉** —— 和 segment_config 放错位置是同一个坑。
3. 开新一支时 `story_core.py` 和模板**一起**复制进 `<项目>/build/`。
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time


def _default(name, value):
    """模板（或 segment_config）没写这个配置时才用引擎的缺省值。"""
    g = globals()
    if name not in g:
        g[name] = value
    return g[name]


# ================= 横竖两版各缺的配置：缺省值 =================
# 横版模板没有的（竖版才有）、竖版模板没有的（横版才有），都在这里补齐，
# 让每个函数都能假定这些名字存在，而不是到处 `globals().get(...)`。
_default("LAYOUT", "h" if W >= H else "v")      # 版式。一般不用写，按 W/H 推

# ---- 分段（横版长片才分段；竖版恒为单段）----
_default("SEG_NAME", "成片")
_default("SEG_INDEX", 1)
_default("SEG_TOTAL", 1)
_default("SEG_FIRST", SEG_INDEX == 1)
_default("SEG_LAST", SEG_INDEX == SEG_TOTAL)
_default("OUT_NAME", "%s_段用.mp4" % SEG_NAME)
_default("PREVIEW_NAME", "%s_预览.mp4" % SEG_NAME)
_default("CHECK_NAME", "%s_检查片.mp4" % SEG_NAME)
_default("RENDER_PREVIEW", False)
_default("PREVIEW_FADE_OUT", 1.5)

# ---- 字幕：烧录还是外挂 ----
# 横版一律外挂（YouTube / 电视，播放器渲染）；竖版默认烧录（抖音/小红书那一路）。
_default("SUB_MODE", "srt" if LAYOUT == "h" else "burn")
_default("SUB_MAX_W", int(W * 0.77))             # 烧录时一行的像素宽上限
_default("TITLE_CARD", None)                     # 开场标题字卡（烧进画面）
_default("SHOT_LABELS", {})                      # 画面角标 {镜号: 文字}

# ---- 竖版平台安全区（抖音/小红书真机比出来的）。横版不适用：None = 不查 ----
_default("SAFE_RAIL", None)
_default("SAFE_TOP", None)
_default("SAFE_BOTTOM", None)

# ---- 片长硬线（YouTube Shorts 180s）与 vofit ----
_default("HARD_LIMIT", None)
_default("LIMIT_SAFETY", 2.0)
_default("ATEMPO_MAX", 1.08)
_default("VO_RAW", "vo_raw")

# ---- 旁白估时：NARR 里的 est 可以不写，按字数推 ----
_default("EST_RATE", 4.24)

# ---- 音效目标响度的锚 ----
_default("SFX_ANCHOR", VO_TARGET)

# ---- 显式承认的妥协：**必须写理由**，理由每次 check 都打印 ----
_default("PP_ACCEPT_REASON", "")
_default("PP_ACCEPTED", None)       # 可选：pp 的硬地板。填了理由也不许低于它
_default("LANG_ACCEPT_REASON", "")

# ---- 出图前的两道门禁（留空 = 没签字，budget 会拦）----
_default("GATE_SCRIPT_OK", "")
_default("GATE_PREVIEW_OK", "")

# ---- 运镜自检的取样框（外挂字幕时 trace / measure 对账用）----
# 横版三块沿水平方向排（左 / 心 / 右），竖版沿竖直方向排（上 / 心 / 下）——
# 取样框要沿着画幅的长边分布，平移才量得出来。
_default("PROBE_BOXES", [
    ("左", 0.06, 0.28, 0.30, 0.70),
    ("心", 0.39, 0.61, 0.39, 0.61),
    ("右", 0.72, 0.94, 0.30, 0.70),
] if LAYOUT == "h" else [
    ("上", 0.30, 0.70, 0.06, 0.28),
    ("心", 0.39, 0.61, 0.39, 0.61),
    ("下", 0.30, 0.70, 0.72, 0.94),
])
_default("PROBE_TOL", 8.0)
_default("PROBE_EDGE", 0.05)


def _ratio():
    """成片宽高比的最简分数，拼进 ffmpeg 表达式用（1920x1080 -> (16, 9)）。"""
    from math import gcd
    g = gcd(W, H)
    return W // g, H // g


# ---- 运行时状态（不是配置）----
_default("VO_CACHE", "vo_times.json")
_default("_VO", {})                 # 按语言缓存：{lang: (durs_map, missing)}
_default("_VIG_CACHE", {})
_default("_SCRIM_CACHE", {})



# ================= 交付物放哪、叫什么；出图前的门禁（原来藏在横版模板的配置区里）=================
def out_dir():
    """交付物（成片 / SRT / 封面 / 素材来源表）落在哪 —— **跟着素材在哪走**。

      分段布局    项目/素材  +  项目/段N/脚本   -> SRC 指向上一级，交付物也往上一级写
      不分段布局  项目/素材  +  项目/脚本       -> SRC 就在手边，交付物**必须写在项目里**

    2026-09-19 踩到：不分段的《约翰斯敦》把 全片.mp4 / 全片.srt / 素材来源.md
    写到了片库根目录 ani/ 去 —— 整条流水线一句警告都没有，因为 ".." 永远存在。
    判据故意不用 SEG_TOTAL：有人可能把不分段的片子照样放在 段一/ 里。
    """
    d = "." if os.path.dirname(os.path.abspath(SRC)) == HERE else ".."
    _guard_library(d)
    return d


def final_name():
    """交付物叫什么。**分不分段是两回事**：

      分段   -> 段用文件，归一和拼接都由 join 做，这里出的是半成品。
      不分段 -> 没有 join，所以「归一」那一趟渲出来的**就是成片**：
                单语 `SEG_NAME.mp4`；多语 `*_多音轨.mp4`，再拆成上传件 + 独立音频。

    credits 表头也要印它 —— 原来印的是段用文件名，不分段时那个文件根本不存在。
    """
    if SEG_TOTAL > 1:
        return OUT_NAME
    return ("%s_多音轨.mp4" % SEG_NAME) if len(LANGS) > 1 else ("%s.mp4" % SEG_NAME)


def check_gates():
    """出图前的两道门禁。`budget` 末尾调用 —— 尺寸表照印，但不签字就不许拿去出图。

    **为什么拦在 budget 上**：budget 是"出图之前跑、把尺寸抄进任务书"的那一步，
    是流水线上最后一个还来得及改稿的位置。再往后就是花钱花时间的出图。

    **为什么是拦而不是提示**：这两件事被跳过的时候不会有任何症状 ——
    图出完了、片子渲出来了、一切检查全绿，只是稿子不好听、或者片长超了硬线。
    那时候再回头，前面所有的钱都白花。**一个只提示不拦的门禁等于没有门禁。**
    """
    me = os.path.basename(sys.argv[0])
    rows = [("讲述稿人工确认", GATE_SCRIPT_OK,
             "把%s讲述稿交给用户读一遍。稿子的毛病是检查判不出来的那一类。"
             % ("本段" if SEG_TOTAL > 1 else "")),
            ("检查片人工确认", GATE_PREVIEW_OK,
             "跑 `python %s preview` 出一支只有字幕+声音的片子，交给用户听。" % me)]
    print("")
    print("=== 出图前的两道门禁 ===")
    bad = []
    for name, val, how in rows:
        if val.strip():
            print("  [已签字] %s" % name)
            print("           %s" % val.strip())
        else:
            print("  [ 未过 ] %s" % name)
            print("           %s" % how)
            bad.append(name)
    if bad:
        print("")
        # 单独跑 `gates` 时上面没有尺寸表，别说一句不存在的东西
        from_budget = len(sys.argv) > 1 and sys.argv[1] == "budget"
        print("  %s**先不要出图**。还差 %d 道：%s"
              % ("上面的尺寸表" if from_budget else "", len(bad), "、".join(bad)))
        print("  确认完把结论写进脚本顶部的 GATE_SCRIPT_OK / GATE_PREVIEW_OK，")
        print("  **写人话，不要写 True** —— 半年后回看要知道当时确认了什么。")
        sys.exit(1)
    print("")
    print("  两道都过了，可以出图。")
    return True


def run(args, desc):
    print("\n>>> " + desc)
    if subprocess.run(args).returncode != 0:
        sys.exit("!!! 失败: " + desc)


# ================= 中间件对账：过期的 img / shot 不许往下游走 =================
# 下面三种事故都是**静默**的 —— 每镜单看都正常、退出码 0 —— 全部真踩过：
#   1. 改了镜数（中间插一镜）没重跑 prep：imgNN 还是旧 CLIPS 的产物，插入点之后
#      画面和旁白整体错一格（2026-09-16《他說他看反了羅盤》）。prep 遇到缺图只打
#      「跳过」、上一轮的同名 imgNN 照样被 a 拿去渲，是同一个洞。
#   2. 渲到一半被打断：shots/ 里留下 48 字节的 shotNN.mp4，名字对，b 照样拼进去
#      （2026-09-21）。
#   3. 改了 XF 或旁白（镜长跟着变）没重跑 a：旧 shot 长度不对，b 照样拼，
#      后面的转场整体错位。
# 所以 prep / a 每做完一件中间件就记一笔「按什么输入做的」，下游用之前先对账，
# 对不上就停。顺带让 a **只补过期的那几镜**，并且多进程并行 —— 串行的 a 在 70 镜的
# 横版上要 4 个多小时（zoompan 单线程，四核闲三核；2026-09-24《人工肾》）。

_default("PREP_KEYS", "prep_keys.json")
# a 并行渲几镜。zoompan 单线程，按核数开、留一核给系统。
# 想看 -stats 进度或内存吃紧时跑 `a 1`。
_default("JOBS", max(1, min(3, (os.cpu_count() or 2) - 1)))


def _sig(path):
    """文件签名：大小 + 修改时间。不读内容 —— 素材动辄几百 MB。"""
    try:
        st = os.stat(path)
        return [st.st_size, st.st_mtime_ns]
    except OSError:
        return None


def _key(*parts):
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _prep_keys():
    try:
        with open(PREP_KEYS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _set_prep_key(i, key):
    keys = _prep_keys()
    if key is None:
        keys.pop(str(i), None)
    else:
        keys[str(i)] = key
    with open(PREP_KEYS, "w", encoding="utf-8") as f:
        json.dump(keys, f, indent=1, sort_keys=True)


def stale_prep():
    """哪些镜的 imgNN 不是按**现在的** CLIPS 第 N 条做出来的。空 = 全对得上。"""
    keys = _prep_keys()
    return [i for i, c in enumerate(CLIPS, 1) if keys.get(str(i)) != prep_key(i, c)]


def shot_path(i):
    return os.path.join("shots", "shot%02d.mp4" % i)


def _shot_keyfile(i):
    return os.path.join("shots", "shot%02d.key" % i)


def media_dur(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def shot_key(i, argv):
    return _key("shot", argv, prep_key(i, CLIPS[i - 1]))


def shot_problem(i, dur, key):
    """shots/shotNN.mp4 能不能拿去拼。能 -> None；不能 -> 一句原因。

    印记是主判据（整条 ffmpeg 命令 + 这一镜 prep 的输入）；时长是第二道保险，
    容差 2 帧 —— 2026-09-24《人工肾》70 镜实测，正常渲出来的 shot 和时间轴镜长
    最多差 1.1 帧（0.037s @30fps）。
    """
    p = shot_path(i)
    if not os.path.exists(p):
        return "没渲"
    try:
        with open(_shot_keyfile(i), encoding="utf-8") as f:
            got = f.read().strip()
    except OSError:
        got = None
    if got is None:
        return "没有印记（渲到一半被打断过，或者是旧版脚本渲的）"
    if got != key:
        return "不是按现在的参数渲的（改过运镜 / 镜长 / 转场 / prep 之后没重跑 a）"
    d = media_dur(p)
    if d is None:
        return "读不出时长（文件坏了）"
    if abs(d - dur) > 2.0 / FPS:
        return "时长 %.3fs，时间轴要 %.3fs" % (d, dur)
    return None


def _drop_key(i):
    try:
        os.remove(_shot_keyfile(i))
    except OSError:
        pass


def _stamp(i, key, dur):
    """渲完盖印记，然后立刻按 shot_problem 复核一遍；复核不过就把印记撕掉。"""
    with open(_shot_keyfile(i), "w", encoding="utf-8") as f:
        f.write(key)
    why = shot_problem(i, dur, key)
    if why:
        _drop_key(i)
    return why


def pass_a(jobs=None, force=False):
    """每镜做运镜或静帧 -> shots/。**只渲过期的镜**：`a force` 全部重渲，`a 1` 串行。"""
    durs = timeline()[1]
    stale = stale_prep()
    if stale:
        sys.exit("!!! 镜 %s 的 imgNN 不是按现在的 CLIPS 做的 —— 改过镜数 / 裁切 / 调色 / "
                 "换过图，或者 prep 那一镜因为缺图跳过了。先跑 prep。"
                 % "/".join(map(str, stale)))
    os.makedirs("shots", exist_ok=True)
    todo = []
    for i in range(1, len(SHOTS) + 1):
        argv, desc, warn = shot_cmd(i, durs[i - 1])
        if warn:
            print(warn)
        key = shot_key(i, argv)
        if force or shot_problem(i, durs[i - 1], key):
            todo.append((i, argv, desc, key))
    if len(todo) < len(SHOTS):
        print("\n%d 镜已是最新，跳过%s" % (len(SHOTS) - len(todo),
                                         "" if todo else " —— 全部都是，这一趟不用渲"))
    if not todo:
        return
    jobs = JOBS if jobs is None else max(1, jobs)
    if jobs == 1 or len(todo) == 1:
        for i, argv, desc, key in todo:
            _drop_key(i)            # 先撕印记：渲到一半被打断，残文件就对不上账
            run(argv[:1] + ["-stats"] + argv[1:], desc)
            why = _stamp(i, key, durs[i - 1])
            if why:
                sys.exit("!!! 镜 %d 渲完了却对不上账：%s" % (i, why))
        return
    todo.sort(key=lambda t: (is_static(t[0]), -durs[t[0] - 1]))   # 慢的先开，免得拖尾
    _render_parallel(todo, jobs, durs)


def _render_parallel(todo, jobs, durs):
    """多进程渲 shots。子进程 stderr **写文件，不接管道** —— 管道写满 ffmpeg 就挂住，
    而且零报错（2026-09-24《人工肾》三个视频镜这样卡了两小时）。"""
    print("\n>>> 并行渲 %d 镜，%d 路（想串行看进度：`a 1`）" % (len(todo), jobs))
    queue, running, failed = list(todo), [], []
    t0 = time.time()
    try:
        while queue or running:
            while queue and len(running) < jobs:
                i, argv, desc, key = queue.pop(0)
                _drop_key(i)
                log = open(os.path.join("shots", "_err%02d.log" % i), "wb")
                running.append((i, key, desc, log, subprocess.Popen(
                    argv, stdout=subprocess.DEVNULL, stderr=log)))
            time.sleep(0.5)
            for r in list(running):
                i, key, desc, log, p = r
                if p.poll() is None:
                    continue
                running.remove(r)
                log.close()                     # Windows 下不关句柄就删不掉
                lp = os.path.join("shots", "_err%02d.log" % i)
                why = (("ffmpeg 退出码 %d" % p.returncode) if p.returncode
                       else _stamp(i, key, durs[i - 1]))
                if why:
                    with open(lp, "rb") as f:
                        err = f.read().decode("utf-8", "replace").strip()[-300:]
                    failed.append(i)
                    print("   !! %s —— %s%s" % (desc, why, ("\n      " + err) if err else ""))
                else:
                    os.remove(lp)
                    print("   ok %s  (%.1f min)" % (desc, (time.time() - t0) / 60))
    finally:
        for i, key, desc, log, p in running:    # Ctrl-C / 出错：别留下还在写文件的孤儿进程
            p.kill()
            p.wait()
            log.close()
    if failed:
        sys.exit("!!! 镜 %s 没渲成，日志在 shots/_errNN.log"
                 % "/".join(map(str, sorted(failed))))
    print("   %d 镜并行渲完  %.1f min" % (len(todo), (time.time() - t0) / 60))


def check_shots(durs):
    """b 之前：每个 shots/shotNN.mp4 都按现在的参数渲过、时长对得上。"""
    bad = []
    for i in range(1, len(SHOTS) + 1):
        why = shot_problem(i, durs[i - 1], shot_key(i, shot_cmd(i, durs[i - 1])[0]))
        if why:
            bad.append("镜%d %s" % (i, why))
    if bad:
        sys.exit("!!! 这些镜的 shots 不能拿去拼：\n    %s\n    —— 先跑 a（只会补这几镜）"
                 % "\n    ".join(bad))


GEN_MARK = ("<!-- 自动生成 sha1=%s ：手写内容别写在这份里，重跑会整份重写"
            "（被改过的会先备份成 .bak-时间戳） -->")


def write_generated(path, lines):
    """整份重写一个**自动生成**的交付物，但先确认它没被人手改过。

    `credits` 原来直接覆盖 素材来源.md，不提示、不备份 —— 2026-09-02 被吃过一次：
    配乐铺法、抽帧处理、调色决定都手写在那份里，重跑一次全没了。
    现在末尾带一行正文指纹。重写前对一下：对得上 = 没人动过，直接盖；
    对不上、没有指纹、或指纹后面还有字（被手改过 / 旧版脚本生成的）= 先备份再写，
    并大声说出来。**不拦** —— 拦了只会逼人手工删掉它，一样丢。
    """
    body = "\n".join(lines) + "\n"
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            old = f.read()
        m = re.search(r"<!-- 自动生成 sha1=([0-9a-f]+)", old)
        pristine = old == body or bool(
            m and hashlib.sha1(old[:m.start()].encode("utf-8")).hexdigest()[:12] == m.group(1)
            and old.rstrip() == (old[:m.start()] + GEN_MARK % m.group(1)).rstrip())
        if not pristine:
            bak = "%s.bak-%s" % (path, time.strftime("%Y%m%d-%H%M%S"))
            shutil.copy2(path, bak)
            print("!! %s 被手改过（或是旧版脚本生成的、没有指纹）—— 原文件先备份到 %s\n"
                  "   手写的内容请挪到别的文件（比如 素材处理说明.md），这一份随时会被重写。"
                  % (path, bak))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body + GEN_MARK % hashlib.sha1(body.encode("utf-8")).hexdigest()[:12] + "\n")



def _library_like(d):
    """d 底下有几个「自带 素材/ 或 build/ 的子目录」。两个以上 = 片库根，不是一支片子。"""
    n = 0
    for x in os.listdir(d):
        p = os.path.join(d, x)
        if os.path.isdir(os.path.join(p, "素材")) or os.path.isdir(os.path.join(p, "build")):
            n += 1
    return n


def _guard_library(d):
    """最后一道闸：交付物目录长得像片库根就停。

    光判"素材目录在不在"不够 —— ani/ 下本来就有一个历史遗留的 素材/，
    脚本错放在项目根时 ../素材 照样存在，out_dir 照样算出 ".."。
    """
    n = _library_like(d)
    if n >= 2:
        sys.exit("!!! 交付物要写到 %s，而它看起来是片库根（底下有 %d 个带 素材/ 或 build/ "
                 "的子目录）—— 写下去会和别的片子撞名、静默覆盖。\n"
                 "    脚本应该放在 <项目>/build/ 里，SRC 用默认的 ../素材"
                 % (os.path.abspath(d), n))


_default("VIDEO_FIT", "pillarbox")      # 视频镜怎么填满画框："pillarbox" 加黑边（默认）/ "crop" 裁掉
# 加黑边是默认，因为**裁掉画面会和"还剩多少"这类题材自相矛盾**，而且档案影像
# 本来就该看着像档案。要裁的片子逐镜写 fit="crop"。


_default("PLATE_COLOR", "black")       # 贴纸版式的台纸颜色。深色片子用 black，纸本画种要改浅


def is_plate(n):
    """镜 n 是不是贴纸版式（图不裁、整张贴在台纸上）。

    **它不是"省事"的那条，是"这张图本来就不该裁"的那条。** 竖构图的海报、
    小尺寸的目录版画、档案剧照 —— 裁成 16:9 要么把主体裁没，要么把 pp 拉到
    1.0 以下靠放大硬撑。贴纸把这两件事一起解决：整张都在，而且是 1:1 不放大。

    代价是运镜全取消（台纸不动），所以只在 static 镜上用 —— check 会拦。"""
    return (CLIPS[n - 1].get("fit") == "plate") if 0 < n <= len(CLIPS) else False


def plate_box(w, h):
    """一张 w x h 的图贴在成片画框上时的 (缩放后宽, 高, 缩放系数)。

    **系数取 min(1, ...) —— 永远不放大。** 这是贴纸版式存在的全部理由：
    放大就等于回到了它要解决的那个问题。比画框大的图照常缩到画框内。"""
    f = min(1.0, W / float(w), H / float(h))
    return (max(2, int(round(w * f)) // 2 * 2), max(2, int(round(h * f)) // 2 * 2), f)


def clip_key(c):
    """CLIPS 一条用的素材文件名。视频镜写 video=，静帧/运镜镜写 src=。

    登记来源、查重、报错都要用它 —— 直接写 c["src"] 的地方一旦遇到视频镜就 KeyError，
    而且是在跑到一半才炸。"""
    return c.get("video") or c.get("src") or ""


def is_video(n):
    """镜 n(1 起) 是不是视频镜。**判据放在 CLIPS 上，不放在 SHOTS 上** ——
    素材是什么由素材那一侧说了算，SHOTS 只管时间和运动。"""
    return bool(CLIPS[n - 1].get("video")) if 0 < n <= len(CLIPS) else False


def tc(v):
    """时间码 -> 秒。接受 12.5 / "20:10" / "20:10.5" / "1:02:03"。

    分镜表上写的是 20:10 这种给人读的形式，直接当浮点数用会得到 20.0 ——
    **不报错，只是取错了地方**，所以入口统一从这里过。"""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return 0.0
    parts = s.split(":")
    if len(parts) > 3:
        sys.exit("!!! 时间码 %r 认不出来" % v)
    sec = 0.0
    for x in parts:
        sec = sec * 60 + float(x)
    return sec


def probe_video(path):
    """(宽, 高, 时长秒, fps)。拿不到就返回 None —— 让调用处自己决定是拦还是跳过。"""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height,r_frame_rate",
                        "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", path],
                       capture_output=True, text=True)
    vals = [x.strip() for x in r.stdout.split() if x.strip()]
    if len(vals) < 4:
        return None
    try:
        w, h = int(vals[0]), int(vals[1])
        num, den = (vals[2].split("/") + ["1"])[:2]
        fps = float(num) / float(den or 1)
        dur = float(vals[3])
    except (ValueError, ZeroDivisionError):
        return None
    return (w, h, dur, fps)


def video_seg(n):
    """视频镜 n 声明的 (入点秒, 出点秒, 段长秒)。"""
    c = CLIPS[n - 1]
    a = tc(c.get("ss", 0))
    b = tc(c.get("to", 0))
    return a, b, max(0.0, b - a)


def video_fit_vf():
    """把源画幅装进成片画框的滤镜段。

    **黑边是加在 prep 这一层的，不是渲染时才补。** 放在这里的好处是
    `vidNN.mp4` 出来就已经是成片尺寸，pass_a 只管切时长，转场、字幕、调色
    全都和静帧镜走同一条路 —— 视频镜因此是"第三种镜"，不是一个图层。"""
    if VIDEO_FIT == "crop":
        return ("scale=%d:%d:force_original_aspect_ratio=increase:flags=lanczos,"
                "crop=%d:%d" % (W, H, W, H))
    return ("scale=%d:%d:force_original_aspect_ratio=decrease:flags=lanczos,"
            "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black" % (W, H, W, H))


def motion_of(n):
    """镜 n(1 起) 是运镜、静帧还是视频。逐镜的 motion= 覆盖全局 MOTION。

    **视频镜由 CLIPS 决定，不看 SHOTS 的 motion=** —— 素材是一段影片这件事
    不该靠两处配置对上口径才成立。"""
    if is_video(n):
        return "video"
    return SHOTS[n - 1].get("motion", MOTION)


def is_static(n):
    return motion_of(n) == "static"


OUT_SHORT = min(W, H)
PREP_SHORT = min(PREP)
# 实测曲线：pp -> 成片保住的顶层细节（两张真原生图库照片的平均，同一镜头走完整流水线）
_PP_CURVE = [(0.70, 68), (0.85, 83), (1.00, 92), (1.20, 98), (1.30, 99), (1.45, 100)]


def detail_pct(pp):
    if pp <= _PP_CURVE[0][0]:
        return _PP_CURVE[0][1]
    for (a, va), (b, vb) in zip(_PP_CURVE, _PP_CURVE[1:]):
        if pp <= b:
            return va + (vb - va) * (pp - a) / (b - a)
    return 100.0


def pp_target(n):
    if is_static(n):
        return PP_STATIC
    return PP_DETAIL if n in DETAIL_SHOTS else PP_KENBURNS


def required_native(n):
    """镜 n 要的源图短边（裁成成片比例之后）。返回 (需要多少, 有没有被 PREP 卡住)。
    不在这里 clamp —— 卡住是要被看见的事实：再买大图也没用，得改运镜或抬 PREP。"""
    s = SHOTS[n - 1]
    z = s["z"][0] if is_static(n) else max(s["z"])
    need = pp_target(n) * z * OUT_SHORT
    return need, need > PREP_SHORT + 1


def wh(short):
    """把「短边」按成片方向印成 宽x高。横版长边在前，竖版短边在前。
    印反了任务书上就是一串方向错的尺寸，而数字本身是对的 —— 看不出来。"""
    long_ = short * max(W, H) / float(min(W, H))
    return ("%.0f x %.0f" % (long_, short)) if W >= H else ("%.0f x %.0f" % (short, long_))


def budget():
    """出图之前跑：反推每一镜要多大的图，直接抄进出图任务书。

    以前是给所有镜头一个统一的 2896x5152，那是两头错的：对缓推镜多买一倍多的
    像素，对大推镜又不够（而 flat 判据还会放行）。尺寸算得出来，就不该拍脑袋。

    ---- 但这张表有个前提：**生成器肯照着尺寸出图** ----
    《经度》段二按这里的分档写了五档（3022x1700 ~ 3733x2100，"省 32%"），
    拿回来的 13 张**全部是 1672x941**，一档都没给。段一同一个生成器也是封顶
    1672x941，只不过那次它把文件放大到 4K 存盘、这次没放大 —— 有效信息量一样。

    **封顶的生成器上，分档表只是自我安慰。** 出图之前先拿一张试出生成器的实际上限，
    再决定：换生成器，还是按那个上限直接排运镜（降 z），而不是写一张漂亮的表。

    顺带一条：源图短边小于成片短边时（941 < 1080），**连"整幅铺满画面"都要放大**，
    pp 在这个输出尺寸上永远到不了 1.0，z 只决定软到什么程度。
    真要 pp>=1.0 只能降输出（720p：静帧 1.31、运镜 z<=1.30 时 1.0）。
    """
    print("")
    print("=== 出图尺寸（按每镜的运动反推）===")
    print("   判据 pp = 源像素/输出像素。实测 pp 1.0→92%，1.2→98%，1.3→99% 的顶层细节")
    print("   静帧 %.2f（恒等重采样）/ 运镜 %.2f / 细节镜 %.2f"
          % (PP_STATIC, PP_KENBURNS, PP_DETAIL))
    print("   **流水线天花板 PREP 短边 = %d**，要得再大也会在 prep 第一步被丢掉"
          % PREP_SHORT)
    print("")
    rows, capped, tiers = [], [], {}
    for n, s in enumerate(SHOTS, 1):
        if is_video(n) or is_plate(n):   # 视频镜和贴纸镜都不按 pp 反推尺寸
            continue
        need, over = required_native(n)
        z = s["z"][0] if is_static(n) else max(s["z"])
        zoom = CLIPS[n - 1]["zoom"] if n <= len(CLIPS) else 1.0
        gen = min(need, PREP_SHORT) * zoom
        rows.append((n, need, gen, z))
        if over:
            capped.append(n)
        # **向上取整，不能四舍五入** —— 舍小了整批图都不够用
        tiers.setdefault(int(-(-gen // 100) * 100), []).append(n)
        note = ("  << 被 PREP(%d) 卡住：买再大也没用，降 z 或抬 PREP" % PREP_SHORT
                if over else ("  (细节镜)" if n in DETAIL_SHOTS else ""))
        # **尺寸要按成片的方向印**：横版是「长 x 短」，竖版是「短 x 长」。
        # 印反了任务书上就是一串竖图尺寸，而数字本身是对的，看不出来。
        print("  镜%-3d %s  z最紧 %.2f  pp %.2f  需要短边 %4.0f  出图 %s%s"
              % (n, "静帧" if is_static(n) else "运镜", z, pp_target(n), need,
                 wh(gen), note))
    print("")
    print("=== 分档（出图任务书按这个写）===")
    for k in sorted(tiers, reverse=True):
        print("  %-12s %2d 镜：%s"
              % (wh(k), len(tiers[k]), ", ".join(str(i) for i in tiers[k])))
    tot = sum(r[2] ** 2 for r in rows)
    print("")
    print("  合计像素相对「一律 4K（短边 2160）」： %.0f%%（省 %.0f%%）"
          % (100.0 * tot / (len(rows) * 2160.0 ** 2),
             100 * (1 - tot / float(len(rows) * 2160.0 ** 2))))
    if capped:
        print("")
        print("  !! 镜 %s 的 z 超出 PREP 的能力。这不是素材问题，是流水线天花板："
              % ", ".join(str(i) for i in capped))
        print("     prep 把源图压到 %d，再大的源图也补不回来。" % PREP_SHORT)
    print("")
    print("  上面是**裁成成片比例之后**的尺寸要求，已按 CLIPS 的 zoom 折回。")
    if LAYOUT == "h":
        print("  生成器出不了 16:9 的话还要再除裁切损失（出 3:2 裁 16:9 只剩 89%）。")
    else:
        print("  生成器出不了 9:16 的话还要再除裁切损失（出 2:3 裁 9:16 只剩 84%）。")
    print("  **务必显式指定尺寸** —— 很多工具默认出 1K，那样只剩六成细节，这一条被坑过两次。")
    # **拦在这里，不拦在别处。** budget 是"出图之前跑、把尺寸抄进任务书"的那一步，
    # 也是流水线上最后一个还来得及改稿的位置。再往后就是花钱花时间的出图。
    check_gates()


def music_on():
    return MUSIC_MODE != "none"


def norm_mode():
    """成片的响度归一策略。

    loudnorm 的整合响度是**带门限**的（−70 绝对门 + 相对门），静音段会被剔掉，
    量到的是"出声段落的平均"。有连续音床时这正是要的；只剩几条稀疏音效时，
    门限会把整合响度变成那几条音效自己的响度，归一等于把 SFX 表里逐条写的
    目标响度全部作废，一层本该若有若无的环境声会被硬抬到 −15 LUFS。

    讲述片几乎总有旁白，所以基本走 loudnorm；这个分支是为"只剩音效"的
    极端配置留的，别让它悄悄走错。
    """
    return "loudnorm" if (music_on() or NARR) else "absolute"


def est_of(n):
    """这一条还没生成时的估算时长。

    **NARR 里的 est 是可选的，能不写就不写。** 手写 est 要人去数字数，而数字数
    要扣标点 —— 段二 37 条里手写错了 20 条，差值全是 ±1 个字（1/EST_RATE≈0.24s），
    积起来把段长算少了 2.1s。这是个不该存在的错误类别：**这个数是算得出来的。**
    写了就用写的（比如某条明知会读得特别慢），没写就按 EST_RATE 从文本推。
    """
    if n.get("est") is not None:
        return n["est"]
    return n_chars(n["txt"]) / EST_RATE


def n_words(txt):
    """英文按**词**数算，不按字符数 —— 换算「还得砍几个词」时要的是词。"""
    return len([w for w in re.split(r"\s+", " ".join(sub_lines(txt or ""))) if w])


def lang_text(n, lang):
    return n["txt"] if lang == DEFAULT_LANG else (n.get(lang) or "")


def srt_name(lang):
    return "%s%s.srt" % (SEG_NAME, LANG_INFO[lang]["srt_suffix"])


def vo_path(n, lang=None):
    lang = lang or DEFAULT_LANG
    f = n["vo"] if n["vo"].lower().endswith((".mp3", ".wav", ".m4a")) else n["vo"] + ".mp3"
    return os.path.join(VO_DIR_OF.get(lang, VO_DIR), f)


def vo_cache_of(lang):
    return VO_CACHE if lang == DEFAULT_LANG else "vo_times_%s.json" % lang


def est_of_lang(n, lang):
    """这一条还没生成时的估算时长。

    非默认语言只有量过语速（EN_RATE）之后才估得准；没量过就退回中文那一条的估算。
    **这个回退值不是给人拿去排片的** —— 缺文件这件事本身由 check_langs 报出来，
    这里只是让流水线在缺文件时还能跑完把表打出来。
    """
    if lang == DEFAULT_LANG:
        return est_of(n)
    if EN_RATE:
        return n_words(lang_text(n, lang)) / EN_RATE
    return est_of(n)


def vo_durs(lang=None):
    """量每条旁白的实测时长，按 (文件, mtime, 大小) 缓存。

    时间轴是**量出来的，不是排出来的** —— 换了配音重新生成，时间轴自动跟着变。
    手工回填一定会漏一条，而漏掉的那一条要到成片才听得出来。
    mp3 还没生成时回退到 est，并让 check 大字提醒时间轴是估算的。"""
    lang = lang or DEFAULT_LANG
    if lang in _VO:
        return _VO[lang]
    cache_path = vo_cache_of(lang)
    cache = {}
    if os.path.exists(cache_path):
        try:
            cache = json.load(open(cache_path, encoding="utf-8"))
        except (ValueError, OSError):
            cache = {}
    out, missing, dirty = {}, [], False
    for n in NARR:
        p = vo_path(n, lang)
        if not os.path.exists(p):
            missing.append(n["vo"]); out[n["vo"]] = (est_of_lang(n, lang), False); continue
        st = os.stat(p)
        key = "%s|%d|%d" % (n["vo"], int(st.st_mtime), st.st_size)
        if key not in cache:
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                "format=duration", "-of", "csv=p=0", p],
                               capture_output=True, text=True)
            try:
                cache[key] = float(r.stdout.strip())
            except ValueError:
                cache[key] = est_of_lang(n, lang)
            dirty = True
        out[n["vo"]] = (cache[key], True)
    if dirty:
        try:
            json.dump(cache, open(cache_path, "w", encoding="utf-8"))
        except OSError:
            pass
    _VO[lang] = (out, missing)
    return _VO[lang]


def per_shot():
    """每一镜下面挂着哪几条旁白（NARR 的下标）。timeline 和双语两边都要用它，
    抄成两份迟早会分叉。"""
    per = [[] for _ in range(len(SHOTS))]
    for k, n in enumerate(NARR):
        if not 1 <= n["shot"] <= len(SHOTS):
            sys.exit("!!! 旁白 %s 的 shot=%d 超出 %d 镜" % (n["vo"], n["shot"], len(SHOTS)))
        per[n["shot"] - 1].append(k)
    return per


def pads(k, per):
    """第 k 条旁白前后的静默。镜与镜之间的气口自动抬到 GAP_PRE / GAP_POST ——
    转场就落在这段静默的正中，于是永远压不到字幕。"""
    n = NARR[k]
    pre = n.get("pre", PRE_DEF)
    post = n.get("post", POST_DEF)
    if k == per[n["shot"] - 1][0]:
        pre = max(pre, GAP_PRE)
    if k == per[n["shot"] - 1][-1]:
        post = max(post, GAP_POST)
    return pre, post


def timeline():
    """由旁白实测时长推出整条时间轴。

    内容时间是连续的：镜 i 占 [S_i, S_i + D_i)，D_i = Σ(pre + 实测 + post)。
    **xfade 骑在边界正中**（起点 S_{i+1} − xf/2），所以每镜要渲的长度是

        dur_i = D_i + xf(i)/2 + xf(i−1)/2

    这样 total = Σdur − Σxf = ΣD，而转场中点恰好落在 S_{i+1} ——
    也就是两句旁白之间那段静默的正中。转场只挂在边界上、不去骑字幕，
    是讲述片和诗片最容易搞错的一处：诗片一句一镜，气口天然在句间；
    讲述片旁白是连着的，不把边界对准静默，十三个转场会条条压字。

    返回 (lines, durs, total, starts)：
      lines = [(字幕起, 字幕止, 文本, 镜号, 旁白起, 旁白时长), ...]
      starts = 每镜的**内容**起点 S_i（不是渲出来那段片子的起点，见 clip_starts）
    """
    durs_map, _ = vo_durs()
    n_shots = len(SHOTS)
    per = per_shot()
    D = []
    for i in range(n_shots):
        if per[i]:
            d = sum(sum(pads(k, per)) + durs_map[NARR[k]["vo"]][0] for k in per[i])
        else:
            d = SHOTS[i].get("dur", 3.0)        # 没有旁白的镜必须自己写 dur
        D.append(d + (TAIL if i == n_shots - 1 else 0.0))
    # ---- 段长吸到整帧 ----
    # 分段片 concat 时，每段差半帧就会累积成 A/V 漂移。
    # **但不要让人手工调 TAIL 去凑** —— 段长是旁白实测推出来的，换一次配音就得再凑一次，
    # 那是"靠不断调常数去迁就检查"，这条流水线明确反对。
    # TAIL 是软值（旁白收完之后多留一会儿），**向上**取整最多拉长不到一帧，听不出来，
    # 而且只加不减，不会把留白吃掉。check_seg 仍然验一遍，但那是复核不是要人动手。
    raw = sum(D)
    D[-1] += -(-raw * FPS // 1) / FPS - raw
    starts, t = [], 0.0
    for d in D:
        starts.append(t); t += d
    lines = []
    for i in range(n_shots):
        c = starts[i]
        for k in per[i]:
            n = NARR[k]
            pre, post = pads(k, per)
            vd = durs_map[n["vo"]][0]
            vs = c + pre
            # 字幕比声音早 0.10s 起、晚一点收 —— 早一点跟上，晚一点让人读完
            lines.append((max(0.0, vs - 0.10), vs + vd + min(post, 0.35),
                          n["txt"], i + 1, vs, vd))
            c = vs + vd + post
    durs = [D[i] + (xf(i) / 2 if i < n_shots - 1 else 0.0)
            + (xf(i - 1) / 2 if i > 0 else 0.0) for i in range(n_shots)]
    return lines, durs, sum(D), starts


def xf(i):
    """镜 i(0 起) 转到下一镜的溶解时长。转场是叙事标点，不该是常数：
    钩子后 0.4~0.5 硬切；段落翻页 1.8~2.2 长溶解；转折后 0.4 短切；金句 2.0 叠化。"""
    return SHOTS[i].get("xf", XFADE)


def total_len():
    return timeline()[2]


def shot_starts():
    return timeline()[3]


def clip_starts():
    """每镜渲出来那段片子在成片上的起点 = S_i − xf(i−1)/2（转场骑在边界正中）。
    trace 反查取景窗时要用它算镜内局部时刻，用 S_i 会偏半个转场。"""
    st = shot_starts()
    return [st[i] - (xf(i - 1) / 2 if i > 0 else 0.0) for i in range(len(SHOTS))]


def cut_points():
    """转场中点 = 内容边界 S_{i+1}，也就是两句旁白之间那段静默的正中。"""
    return shot_starts()[1:]


def lang_slots():
    """每一句留给别的语言的空间：(中文实测时长, 可借的静默)。

    **镜末那一句借不到东西。** 镜末的静默正中骑着转场（理由见 timeline 的注释），
    借了就是把话说到转场底下去 —— 而这件事在参数表和波形上都看不出来，
    要放出来听才发现。镜内的句子可以从后面那段气口里借一点，但最多借一半：
    剩下的一半是气口本身，把气口借光了英文那条轨会变成连珠炮。
    """
    zh, _ = vo_durs(DEFAULT_LANG)
    per = per_shot()
    out = []
    for k, n in enumerate(NARR):
        _, post = pads(k, per)
        grp = per[n["shot"] - 1]
        pos = grp.index(k)
        if pos == len(grp) - 1:
            # **镜末可以借到「转场开始之前」为止，不是一点都不能借。**
            # 原来写死 0.0，理由是"镜末的静默正中骑着转场"。那个理由只对了一半：
            # 转场骑在镜界正中、宽 xf，所以它是从 post 段里 (post - xf/2) 处才开始的，
            # 在那之前的静默是干净的。而且音频是一条**连续混音**，并不在镜界切开 ——
            # 说到转场底下去是编辑上的忌讳，不是技术上的错。
            # 借到转场起点为止，等于"话说完，画面才开始溶解"，这正是想要的。
            #
            # 这一条按**实际转场宽度**算，不是给一个固定的宽限：
            # 转场长的镜（比如时间跳跃用的 1.4s 长溶解）算出来仍然是 0，
            # 2026-08-31《四十二年》镜59→60 就是这种情况，实测 borrow=0.00。
            i = n["shot"] - 1
            half = (xf(i) / 2.0) if i < len(SHOTS) - 1 else 0.0
            borrow = max(0.0, min(LANG_BORROW, post - half - 0.02))
        else:
            gap = post + pads(grp[pos + 1], per)[0]
            borrow = min(LANG_BORROW, gap / 2.0)
        out.append((zh[n["vo"]][0], borrow))
    return out


def lang_lines(lang=None):
    """某条语言的字幕行，字段和 timeline() 的 lines 完全一样。

    **起点一律沿用中文定出来的槽** —— 画面只有一份，起点动了就不是多音轨了。
    只有收尾跟着这条语言自己的音频走：英文那句短一点，字幕就早一点收。
    """
    lang = lang or DEFAULT_LANG
    zh_lines = timeline()[0]
    if lang == DEFAULT_LANG:
        return zh_lines
    durs_map, _ = vo_durs(lang)
    per = per_shot()
    out = []
    for k, n in enumerate(NARR):
        _, post = pads(k, per)
        vs = zh_lines[k][4]
        vd = durs_map[n["vo"]][0]
        out.append((max(0.0, vs - 0.10), vs + vd + min(post, 0.35),
                    lang_text(n, lang), n["shot"], vs, vd))
    return out


def sfx_dur(e):
    """音效该放多长。**优先写 span（盖几镜），不要写死 dur。**

    写死秒数的毛病和当初手写 est 一模一样：旁白一改，镜长就变，
    而秒数不会跟着变 —— 它不报错，只是悄悄错位。段五头一版就踩了：
    照着 budget 打印的**渲染长**填 dur（每镜含两侧各半个 xfade，比内容长约 1s），
    于是镜 7~9 那条房间底噪多压了 3 秒进镜 10，盖在该由钟声独占的地方。
    参数表上完全看不出来，要把起止秒数打出来对才发现。

    span=n 表示从这一镜起盖 n 镜的**内容**，尾巴伸到最后那个转场的正中 ——
    也就是画面正好 50/50 的那一帧。声音在那里断，是断在切点上而不是切点后。
    """
    if e.get("dur") is not None:
        return e["dur"]
    st, total = shot_starts(), total_len()
    i = e["shot"] - 1
    j = min(i + e.get("span", 1), len(SHOTS))          # 末镜下标 +1
    # **不要再加 xf/2。** 转场骑在内容边界正中（见 cut_points），
    # 所以画面 50/50 的那一帧就是 st[j] 本身，加半个转场是往后多伸了。
    end = st[j] if j < len(SHOTS) else total
    # **起点要和混音处用同一个夹过的值。** 混音里是 max(0, st+off)，
    # 这里如果直接用 st+off，负的 off（镜 1 那种"提前进来"）就会把长度多算 |off|，
    # 尾巴越过切点 —— 半秒的事，听不出来，但它是错的。
    return max(0.1, end - max(0.0, st[i] + e.get("off", 0.0)))


def shot_of(t):
    n = 1
    for i, s in enumerate(shot_starts(), 1):
        if t >= s - 1e-6:
            n = i
    return n


def sub_lines(txt):
    """按手工断行符切。**每段都要 strip**：英文稿里写成 "a ｜ b" 是自然的，
    不 strip 的话第二行会顶着一个空格出现在 SRT 里 —— 中文稿看不出来
    （没人在 ｜ 两边加空格），英文稿每一条都中。"""
    return [q for q in (p.strip() for p in txt.split(SUB_SEP)) if q]


def text_w(s):
    """一行字的像素宽。按字形宽度算，不按字数 —— 数字和西文只有汉字的一半多一点，
    按字数判会把「1815 年 4 月，印尼松巴哇岛，」这种排得下的行误判成超标。"""
    return sum(ASCII_W if ord(c) < 0x2E80 else 1.0 for c in s) * SUB_FS


def sub_box(txt, pad=8):
    """字幕在画面上的外接矩形（x0, x1, y0, y1），用来量它压着的底、判安全区。"""
    parts = sub_lines(txt)
    w = max(text_w(p) for p in parts)
    top = SUB_BOT - len(parts) * SUB_LH
    return (max(0, int(SUB_CX - w / 2 - pad)), min(W, int(SUB_CX + w / 2 + pad)),
            max(0, int(top - pad)), min(H, int(SUB_BOT + pad)))


# ================= 渲染前的自检 =================
def check_claims():
    """讲历史唯一致命的错误是把推断说成史实。

    **分段片和单支片在这里不一样。** CLAIMS 是**全片**的表：假说可能在段二抛出、
    段五才自拆。所以"必须在片内自拆"这条只在 SEG_LAST 上验 ——
    否则前四段每一段都会报一条它根本无法满足的警，
    而一个长期报假警的检查等于没有检查（这条教训在 trace/vignette 上付过学费）。
    """
    bad = []
    print("\n=== 事实分级（全片表，本段 %d/%d）===" % (SEG_INDEX, SEG_TOTAL))
    for cid, lvl, what, note in CLAIMS:
        print("  %-4s %-4s %-34s %s" % (cid, lvl, what, note))
    hyp = [c for c in CLAIMS if c[1] == "假说"]
    if hyp and not SEG_LAST:
        print("  -> %d 条假说（%s）：本段不是最后一段，自拆检查留给段 %d"
              % (len(hyp), "/".join(c[0] for c in hyp), SEG_TOTAL))
    elif hyp:
        # 窗口是**尾板那一段**，不是"最后三句"。后者是按 13 镜的排法定的；
        # 镜数一多（21 镜时尾板会跨最后两镜），自拆句就掉出窗口，报假警。
        # 语义上要查的单位是尾板，不是一个固定的句数。
        last = NARR[-1]["shot"]
        tail = "".join(n["txt"] for n in NARR if n["shot"] >= last - 1)
        # "证明不了/说明不了" 和 "是主流推断" 一样是标准的自拆句式，原表里漏了。
        # ⚠️ 繁简两套都要列 —— 稿子是繁體时只列简体，这个检查永远不会报警。
        # 2026-09-16《他說他看反了羅盤》在竖版脚本上踩到，横版同源，一并补。
        hit = any(w in tail for w in ("推断", "假说", "存疑", "并没有", "没有这么", "不是",
                                      "证明不了", "说明不了", "没有定论", "只是一个解释",
                                      "一般认为",
                                      "推斷", "假說", "並沒有", "沒有這麼",
                                      "證明不了", "說明不了", "沒有定論", "只是一個解釋",
                                      "一般認為"))
        # ↑ 「没有定论 / 只是一个解释 / 一般认为」当年竖版补了、横版漏跟 ——
        # 两份手抄脚本各改各的，这张表就是这么漂的。现在只有这一份。
        # 第二条路：**画面角标**。这个检查的理由是"看简介的人不到十分之一"，
        # 而烧在画面上、跟着那几镜一直在的角标，比一句旁白更满足这个理由
        # （旁白只说一次，角标在整段展示期间都在）。
        # 但只认带披露词的角标，纯署名（"NASA/GSFC"）不算自拆。
        vis = [(sn, tx) for sn, tx in sorted(SHOT_LABELS.items())
               if any(w in tx for w in ("Reconstruction", "reconstruction",
                                        "Model", "model", "复原", "模型"))]
        if not hit and vis:
            hit = True
            print("  -> %d 条假说，靠画面角标披露：镜 %s"
                  % (len(hyp), "/".join(str(sn) for sn, _ in vis)))
        elif hit:
            print("  -> %d 条假说，结尾已自我拆解" % len(hyp))
        if not hit:
            bad.append("CLAIMS 里有 %d 条『假说』(%s)，尾板旁白里没有自我拆解，"
                       "画面上也没有带披露词的角标（SHOT_LABELS）。"
                       "假说必须**在片内**说出来或标出来 —— 看简介的人不到十分之一"
                       % (len(hyp), "/".join(c[0] for c in hyp)))
    return bad


def n_chars(txt):
    return sum(1 for ch in "".join(sub_lines(txt)) if ch not in "，。：；、？！—…「」《》 ")


def check_pace():
    """两件独立的事，分开量（为什么不用「VO 字/秒落在某个区间」见常数处的注释）：

    一、**字幕读不读得完** —— 字数 / 在屏时间，硬判据。
    二、**这一批里有没有离群的一条** —— 拿本批中位数当基准，不用绝对常数。
        同一个音色同一套参数，某条明显偏慢，多半是 TTS 卡在专名上了。
    """
    durs_map, _ = vo_durs()
    lines = timeline()[0]
    bad = []
    rows = []
    for n, ln in zip(NARR, lines):
        d, real = durs_map[n["vo"]]
        c = n_chars(n["txt"])
        rows.append((n["vo"], d, real, c, c / d if d else 0, ln[1] - ln[0]))
    pool = sorted(p for _, _, real, c, p, _ in rows if real and c >= PACE_MIN_CHARS)
    med = pool[len(pool) // 2] if pool else 0

    print("\n=== 旁白与字幕（本批中位语速 %.1f 字/秒）===" % med)
    print("   在屏 = 字幕停留时间；读速上限 %.1f 字/秒" % READ_MAX)
    for vo, d, real, c, p, on in rows:
        flag = ""
        if on > 0 and c / on > READ_MAX:
            flag = "  << 字幕读不完"
            bad.append("字幕『%s』%d 字只停 %.1fs（%.1f 字/秒），超过可读上限 %.1f"
                       % (vo, c, on, c / on, READ_MAX))
        elif real and c >= PACE_MIN_CHARS and med:
            r = p / med
            if not (PACE_OUTLIER_LO <= r <= PACE_OUTLIER_HI):
                flag = "  << 比本批中位%s %.0f%%，检查专名是否读不顺" % (
                    "慢" if r < 1 else "快", abs(1 - r) * 100)
        print("  %-11s %5.2fs %2d字  语速 %.1f  在屏 %4.1fs  读速 %.1f%s%s"
              % (vo, d, c, p, on, c / on if on else 0,
                 "" if real else "  (估算)", flag))
    return bad


def check_subs():
    bad = []
    for st, en, txt, _, _, vd in timeline()[0]:
        parts = sub_lines(txt)
        if len(parts) > 2:
            bad.append("字幕『%s』断成了 %d 行，一屏最多两行" % (txt, len(parts)))
        for p in parts:
            # 烧录按**像素宽**判（字号是我们定的）；外挂按**字数**判
            # （播放器的字号我们管不着，像素宽这个判据在那边不成立）
            if SUB_MODE == "burn":
                if text_w(p) > SUB_MAX_W:
                    bad.append("字幕行『%s』宽 %.0fpx，超过一行上限 %dpx —— "
                               "在稿子里用 %s 手工断行" % (p, text_w(p), SUB_MAX_W, SUB_SEP))
            elif len(p) > SUB_MAX_CHARS:
                bad.append("字幕行『%s』%d 字，超过一行上限 %d —— "
                           "在稿子里用 %s 手工断行" % (p, len(p), SUB_MAX_CHARS, SUB_SEP))
        if en - st < vd:
            bad.append("字幕『%s』在屏 %.1fs，短于它自己的旁白 %.1fs" % (txt, en - st, vd))
    return bad


def check_langs(quiet=False):
    """多音轨的自检。四件事，都是「单看中文那条轨完全正常」的那一类：

      一、每一条旁白有没有写英文
      二、英文音频齐不齐
      三、**逐句对不对得上槽** —— 量的是**磁盘上的文件**，不是 langfit 当时的结论
      四、英文字幕一行有没有超长

    第三条是这里唯一会**静默出错**的：英文音频长出槽去，不报错、不崩、
    波形上也看不出来，只会让那句话说到转场底下去 —— 而你手上放的是中文版，
    一切正常。所以它必须在每次 check 时从文件重新量，
    "改了翻译、重新生成、忘了跑 langfit" 就是靠这一条拦住的。
    """
    bad = []
    lang_warn = []
    if len(LANGS) <= 1:
        return bad
    slots = lang_slots()
    for lang in LANGS:
        if lang == DEFAULT_LANG:
            continue
        info = LANG_INFO.get(lang)
        if not info:
            bad.append("LANGS 里的 %r 在 LANG_INFO 里没有登记" % lang)
            continue
        no_txt = [x["vo"] for x in NARR if not x.get(lang)]
        if no_txt:
            bad.append("%d 条旁白没写 %s 文本（%s%s）"
                       % (len(no_txt), lang, ", ".join(no_txt[:3]),
                          "..." if len(no_txt) > 3 else ""))
        durs_map, missing = vo_durs(lang)
        if missing:
            bad.append("%s 轨还缺 %d 条音频（%s%s），要放在 %s/ 下"
                       % (info["name"], len(missing), ", ".join(missing[:3]),
                          "..." if len(missing) > 3 else "",
                          VO_DIR_OF.get(lang, lang)))
        over = []
        if not quiet:
            print("\n=== %s 轨逐句对槽（槽是中文定的，%s 塞进去）==="
                  % (info["name"], info["name"]))
        for k, x in enumerate(NARR):
            base, borrow = slots[k]
            room = base + borrow
            d, real = durs_map[x["vo"]][0], durs_map[x["vo"]][1]
            if not real:
                continue
            flag = ""
            if d > room + 0.02:
                flag = "  << 超 %.2fs" % (d - room)
                grp = per_shot()[x["shot"] - 1]
                at_end = grp.index(k) == len(grp) - 1
                over.append((x["vo"], d - room, at_end))
            if not quiet:
                print("  %-11s 槽 %5.2f(+%.2f 可借)  实测 %5.2f%s"
                      % (x["vo"], base, borrow, d, flag))
        # **镜末句和镜内句要分开判，不能一起放行。**
        # 镜内句超出的两三百毫秒吃的是后面那段气口；镜末句的静默正骑在转场上，
        # 超了就是把话说到溶解底下去 —— 那件事在参数表和波形上都看不出来。
        # 第一版的 LANG_ACCEPT_REASON 把两种一起降级，回归自测当场报
        # 「镜末那条英文超槽 → 多报 0 条 —— 检查失效了」：**开的口子太大**。
        ends = [z for z in over if z[2]]
        mids = [z for z in over if not z[2]]
        for grpz, tail, always_block in ((ends, "**镜末**", True), (mids, "镜内", False)):
            if not grpz:
                continue
            worst = max(grpz, key=lambda z: z[1])
            me = os.path.basename(sys.argv[0]) or "make_story_h.py"
            msg = ("%s 轨有 %d 条%s句塞不进%s的槽（最长的 %s 超 %.2fs）—— "
                   "跑 `python %s langfit %s`；"
                   "压不进去的那几句它会报出还得砍几个词"
                   % (info["name"], len(grpz), tail, LANG_INFO[DEFAULT_LANG]["name"],
                      worst[0], worst[1], me, lang))
            if always_block:
                bad.append(msg + " —— **镜末不接受妥协**：那段静默骑在转场上，"
                                 "超出去就是把话说到溶解底下")
                continue
            # **有时候砍不动。** "All true." 两个词已经是地板，砍掉 "All" 就丢了
            # 「那三个数**都**对」这个全部内容；核心数字那一句两个单位都不能省。
            # 强行砍是拿内容换一个判据过关，那不是修好。
            #
            # 所以和 REUSE_ACCEPT_REASON / PP_ACCEPT_REASON 一个形状：
            # **填了理由就降级成提示，空着照旧拦下，不给静默绕过的开关。**
            # 理由每次 check 都打印，交付时要照抄进制作说明的「哪几处是妥协的」。
            #
            # 判断该不该填，看**超的那几条在不在镜末**：镜内句超出的两三百毫秒
            # 吃的是气口；镜末句的静默正骑在转场上，超了就是把话说到溶解底下去。
            if str(LANG_ACCEPT_REASON).strip():
                lang_warn.append(msg)
            else:
                bad.append(msg)
        for x in NARR:
            parts = sub_lines(x.get(lang) or "")
            # **行数也要验。** 原来只验行长，于是「一条断成三行」整个溜过去 ——
            # 中文那一路 check_subs 一直验着这一条，非默认语言这边漏了。
            # 2026-08-31《四十二年》：英文 VO_08 写了两个 ｜＝三行字幕，check 照样通过。
            # 一屏两行是硬约束（`SUB_MAX_CHARS_EN` 是按两行算的），三行会被播放器截掉或压扁。
            if len(parts) > 2:
                bad.append("%s 字幕『%s』断成了 %d 行，一屏最多两行 —— 一条里只能有一个 %s"
                           % (info["name"], (x.get(lang) or "")[:30], len(parts), SUB_SEP))
            for p in parts:
                if len(p) > SUB_MAX_CHARS_EN:
                    bad.append("%s 字幕行『%s』%d 字，超过一行上限 %d —— 用 %s 手工断行"
                               % (info["name"], p[:34], len(p), SUB_MAX_CHARS_EN, SUB_SEP))
    if lang_warn:
        print("")
        print("=== 多音轨对槽（%d 处超出，**已显式承认**）===" % len(lang_warn))
        for w in lang_warn:
            print("  " + w)
        print("  理由：" + LANG_ACCEPT_REASON.strip())
        print("  交付时这一条要照抄进制作说明的「哪几处是妥协的」。")
    return bad


def selftest_langs():
    """回归：把双语的几种错法逐个造出来，检查必须报警。

    造错的办法是**换掉 NARR 和 vo_durs**，不去碰磁盘 —— 自测不该依赖
    这台机器上有没有英文配音文件，否则它会在没有文件的机器上"通过"。
    最后一条造的是竖版独有的那个危险配置：**烧录字幕 + 两种语言**。
    """
    global LANGS, NARR, SUB_MODE, vo_durs, _VO
    keep = (LANGS, NARR, SUB_MODE, vo_durs, _VO)
    base = [
        dict(vo="T1", shot=1, est=3.0, txt="第一句。", en="First line."),
        dict(vo="T2", shot=1, est=3.0, txt="第二句。", en="Second line."),
        dict(vo="T3", shot=2, est=3.0, txt="第三句。", en="Third line."),
    ]
    zh = {"T1": 3.0, "T2": 3.0, "T3": 3.0}

    def fake(en_map):
        def f(lang=None):
            m = zh if (lang or DEFAULT_LANG) == DEFAULT_LANG else en_map
            return ({x["vo"]: (m[x["vo"]], True) for x in NARR}, [])
        return f

    def count(narr, en_map):
        global NARR, vo_durs, _VO
        NARR, vo_durs, _VO = narr, fake(en_map), {}
        return len(check_langs(quiet=True))

    LANGS, SUB_MODE = ["zh", "en"], "srt"
    fit = {"T1": 3.0, "T2": 3.0, "T3": 3.0}
    # T3 是镜 2 里唯一一条 = 镜末，只能借到转场之前
    cases = [
        ("有一条没写英文", [base[0], base[1], dict(base[2], en="")], fit),
        ("镜末那条英文超槽", base, dict(fit, T3=4.2)),
        ("英文字幕一行超长", [dict(base[0], en="x" * (SUB_MAX_CHARS_EN + 5))] + base[1:], fit),
        ("英文字幕断成三行",
         [dict(base[0], en="aa%sbb%scc" % (SUB_SEP, SUB_SEP))] + base[1:], fit),
    ]
    results = [(name, count(narr, em)) for name, narr, em in cases]
    now = count(base, fit)
    SUB_MODE = "burn"                      # 竖版独有：烧录 + 双语 = 中文字压在英文轨上
    mode_bad = len(check_mode())
    LANGS, NARR, SUB_MODE, vo_durs, _VO = keep
    ok = True
    for name, c in results:
        print("回归自测: %s → 报警 %d 条 —— %s"
              % (name, c, "对" if c else "**检查失效了**"))
        ok = ok and c > 0
    print("          烧录字幕却配了两种语言 → 报警 %d 条 —— %s"
          % (mode_bad, "对" if mode_bad else "**检查失效了**"))
    print("          %d 条都合规 报警 %d 条 —— %s"
          % (len(cases), now, "对" if now == 0 else "**误报**"))
    return ok and mode_bad > 0 and now == 0


def check_seg(quiet=False):
    """分段片独有的自检。三条，都是「单看这一段完全正常、拼起来才坏」的那类。

    `quiet` 给回归自测用 —— 自测要连跑三遍，每遍都打一屏会把真正的输出淹掉。
    """
    bad = []
    total = total_len()
    say = (lambda *a: None) if quiet else (lambda s: print(s))
    say("\n=== 分段 %d/%d ===" % (SEG_INDEX, SEG_TOTAL))

    # 一、段长必须落在整帧上。差半帧看不出来，五段累加就是 A/V 漂移。
    # timeline() 已经自动吸过了，所以这里是**复核**：报警说明吸的逻辑坏了，
    # 不是要人去调 TAIL（手工凑常数，换一次配音就得再凑一次）。
    frames = total * FPS
    off = abs(frames - round(frames))
    if off > 1e-6:
        bad.append("段长 %.4fs = %.3f 帧，不是整帧（差 %.3f 帧）—— "
                   "timeline() 的整帧吸附失效了，查那一段，别手工调 TAIL"
                   % (total, frames, off))
    else:
        say("  段长 %.4fs = %d 帧，整帧对齐 ✓（TAIL 自动吸的，不用管）"
            % (total, round(frames)))

    # 二、淡场归属。中间段两头都不能有黑场，否则每三分钟黑一次。
    if SEG_FIRST and FADE_IN <= 0:
        bad.append("这是第一段，但 FADE_IN=0 —— 全片没有开场淡入")
    if not SEG_FIRST and FADE_IN > 0:
        bad.append("这不是第一段，但 FADE_IN=%.1f —— 接缝处会黑一次" % FADE_IN)
    if SEG_LAST and FADE_OUT <= 0:
        bad.append("这是最后一段，但 FADE_OUT=0 —— 全片没有收尾")
    if not SEG_LAST and FADE_OUT > 0:
        bad.append("这不是最后一段，但 FADE_OUT=%.1f —— 接缝处会黑一次" % FADE_OUT)
    say("  淡场: 入 %.1fs / 出 %.1fs（预览另加 %.1fs 淡出，不进段用文件）"
        % (FADE_IN, FADE_OUT, PREVIEW_FADE_OUT))

    # 三、尾板只属于最后一段
    if ENDCARD and not SEG_LAST:
        bad.append("非最后一段却有 ENDCARD —— 尾板会在片子中间出现")
    return bad


def selftest_seg():
    """回归：把三条分段规矩逐条弄错，检查必须报警。
    一个永远不报警的检查比没有检查更糟 —— 这条教训在 check_safe 的解包顺序上付过。"""
    global TAIL, FADE_OUT, SEG_LAST
    ok = True
    kt, kf, kl = TAIL, FADE_OUT, SEG_LAST

    # 整帧那一条现在由 timeline() 自动吸，所以造错要绕过吸附本身 —— 直接篡改
    # total_len 的返回值，检查必须发现"段长不是整帧"。这才是它真正要防的东西：
    # 吸附逻辑坏掉而没人知道。
    global total_len
    keep = total_len
    total_len = lambda: keep() + 0.0137
    n1 = len(check_seg(quiet=True))
    total_len = keep
    FADE_OUT = 3.0; SEG_LAST = False        # 非末段却有片尾淡出
    n2 = len(check_seg(quiet=True)); FADE_OUT, SEG_LAST = kf, kl
    now = len(check_seg(quiet=True))

    for name, n in (("段长错开半帧", n1), ("非末段加了片尾淡出", n2)):
        print("回归自测: %s → 报警 %d 条 —— %s"
              % (name, n, "对" if n else "**检查失效了**"))
        ok = ok and n > 0
    print("          当前配置 报警 %d 条 —— %s" % (now, "对" if now == 0 else "有问题"))
    return ok and now == 0


def _win(sh, p, clip=None):
    """镜 sh 在进度 p(0~1) 时的取景窗：(左, 右, 上, 下, 占画面比例)。

    **给了 clip 就换算到「源图」坐标系。** CLIPS 的 zoom/cx/cy 是 prep 阶段的裁切，
    prep 为每一镜产出它自己的 imgNN —— 所以相邻两镜共用同一张源图时，
    只比 SHOTS 的 z/f 会**漏掉这一层**：明明已经用 cx/cy 切到画面另一块去了，
    check_reuse 仍然报「取景没分开」，而且报的是 100.0% / 窗心移动 0.000
    （z 恒为 1 的静帧镜必然如此），看起来完全像配置写错了。

    这和 trace 少算 vignette / scrim 是同一个形状的坑：**筛子少建模了流水线里的
    一道，于是长期报假警。** 技能文档说的省图手段本来就是「CLIPS 里 cx/cy/zoom
    不同」，判据却只看 SHOTS —— 两边对不上，要补的是判据。
    （2026-08-25《潘多拉的瓮》：33 镜里 9 处假警，全部是已经切开了的。）
    """
    z = sh["z"][0] + (sh["z"][1] - sh["z"][0]) * p
    half = 1 / (2 * z)
    fx = min(max(sh["f0"][0] + (sh["f1"][0] - sh["f0"][0]) * p, half), 1 - half)
    fy = min(max(sh["f0"][1] + (sh["f1"][1] - sh["f0"][1]) * p, half), 1 - half)
    if clip is None:
        return (fx - half, fx + half, fy - half, fy + half, 1.0 / z)
    cz = clip.get("zoom", 1.0) or 1.0
    cx, cy = clip.get("cx", 0.5), clip.get("cy", 0.5)
    # prep 窗在源图上：中心 (cx,cy)、边长 1/cz；SHOTS 窗再在它里面取 1/z。
    h = half / cz
    return (cx + (fx - 0.5) / cz - h, cx + (fx - 0.5) / cz + h,
            cy + (fy - 0.5) / cz - h, cy + (fy - 0.5) / cz + h,
            1.0 / (z * cz))


_default("REUSE_TIGHTEN", 0.80)        # 后一镜的取景至少要收到前一镜的这个比例
_default("REUSE_SHIFT", 0.12)          # 或者窗心至少移动这么多（占画幅）
# 填了理由就降级成提示，空着照旧拦下。**不给静默绕过的开关** ——
# 那样下一支照抄配置时就再也不知道这里做过妥协了。理由会打印在每次 check 里。
_default("REUSE_ACCEPT_REASON", "")


def check_reuse():
    """**相邻两镜用同一张图时，第二镜必须真的换了取景。**

    「一图两镜」是这条流水线省图的主要手段，但它有个前提：两个取景窗要分得开。
    分不开就不是两镜，是**同一镜中间被硬切了一刀** —— 观众读作跳接，
    而那一镜的时长全部浪费掉。

    《经度》段二镜 6/7 就是这么坏的：镜 6 是木钟机芯全貌、镜 7 本该切进齿轮咬合，
    结果**镜 7 的起幅取景 76.9% 反而比镜 6 的落幅 74.6% 更宽** ——
    想切近，实际切远了。渲完看静帧才发现两镜几乎一模一样，12.8s 白花。

    参数表上完全看不出来：两镜的 z 都写着 1.3~1.5，看着"差不多"，
    而"差不多"正是问题本身。所以要算窗、不能看 z。

    判据（满足其一即可）：
      - 后一镜起幅的取景比例 <= 前一镜落幅的 REUSE_TIGHTEN 倍（真的切近了），或
      - 窗心移动 >= REUSE_SHIFT（切到画面另一块去了）

    **只查相邻的**。段二镜 12/15 也共用一张图，但中间隔着镜 13、14 二十多秒，
    那是"回到同一个地方"的设计，不是跳接。
    """
    bad, warn_reuse = [], []
    for i in range(len(SHOTS) - 1):
        if i + 1 >= len(CLIPS) or clip_key(CLIPS[i]) != clip_key(CLIPS[i + 1]):
            continue
        # 相邻两镜取同一段影片的**不同时间段**，本来就是两镜，不是一图两镜。
        # 分不分得开由 ss/to 决定，check_video 去管。
        if is_video(i + 1) or is_video(i + 2):
            continue
        a, b = _win(SHOTS[i], 1.0, CLIPS[i]), _win(SHOTS[i + 1], 0.0, CLIPS[i + 1])
        tighten = b[4] / a[4]
        shift = (((b[0] + b[1]) / 2 - (a[0] + a[1]) / 2) ** 2
                 + ((b[2] + b[3]) / 2 - (a[2] + a[3]) / 2) ** 2) ** 0.5
        if tighten > REUSE_TIGHTEN and shift < REUSE_SHIFT:
            (warn_reuse if REUSE_ACCEPT_REASON.strip() else bad).append(
                       "镜 %d/%d 共用 %s，但取景没分开："
                       "镜%d 落幅占画面 %.1f%%、镜%d 起幅 %.1f%%（%s），窗心只移了 %.3f。"
                       "读作跳接，不是两镜 —— 收紧镜%d 的 z，或让它切到画面另一块去"
                       % (i + 1, i + 2, clip_key(CLIPS[i]), i + 1, a[4] * 100,
                          i + 2, b[4] * 100,
                          "反而更宽" if tighten > 1 else "只收到 %.0f%%" % (tighten * 100),
                          shift, i + 2))
    if warn_reuse:
        print("")
        print("=== 一图两镜取景（%d 处低于判据，**已显式承认**）===" % len(warn_reuse))
        for w in warn_reuse:
            print("  " + w)
        print("  理由：" + REUSE_ACCEPT_REASON.strip())
        print("  交付时这一条要照抄进制作说明的「哪几处是妥协的」。")
    return bad


def selftest_reuse():
    """回归：造一个"两镜共用一张图但取景几乎相同"的配置，检查必须报警。"""
    if not any(clip_key(CLIPS[i]) == clip_key(CLIPS[i + 1])
               and not (is_video(i + 1) or is_video(i + 2))
               for i in range(len(CLIPS) - 1)):
        print("回归自测: 本段没有相邻共用图，check_reuse 不适用")
        return True
    # **自测必须绕过 REUSE_ACCEPT_REASON。** 填了理由之后 check_reuse 走降级路径、
    # 返回空 bad，自测就永远测不到拦截 —— 一个承认机制把自测一起关掉了。
    # 这一条是自测自己报"检查失效了"才发现的，它诚实地报了，而不是默默通过。
    global REUSE_ACCEPT_REASON
    reason_keep = REUSE_ACCEPT_REASON
    REUSE_ACCEPT_REASON = ""
    # **造错要挑一对相邻的静图镜，不能写死 0/1。**
    # 视频镜没有 `src` 键（它用 video=/ss=/to=），段首两镜正好是视频时这里会 KeyError
    # —— 视频镜是后加的，这个自测当初没跟上，直到一支 25 个视频镜的片子才炸出来。
    pair = next((i for i in range(len(CLIPS) - 1)
                 if not is_video(i + 1) and not is_video(i + 2)), None)
    if pair is None:
        REUSE_ACCEPT_REASON = reason_keep
        print("回归自测: 本段没有相邻的两个静图镜，check_reuse 自测不适用")
        return True
    a, b = pair, pair + 1
    keep = dict(SHOTS[b])
    SHOTS[b].update(z=SHOTS[a]["z"], f0=SHOTS[a]["f1"], f1=SHOTS[a]["f1"])
    src_keep = CLIPS[b]["src"]; CLIPS[b]["src"] = CLIPS[a]["src"]
    n = len(check_reuse())
    SHOTS[b].clear(); SHOTS[b].update(keep); CLIPS[b]["src"] = src_keep
    REUSE_ACCEPT_REASON = reason_keep
    now = len(check_reuse())
    print("回归自测: 相邻两镜共用图且取景相同 → 报警 %d 条 —— %s"
          % (n, "对" if n else "**检查失效了**"))
    print("          当前配置 报警 %d 条 —— %s" % (now, "对" if now == 0 else "有问题"))
    return n > 0 and now == 0


def check_xfades():
    starts = shot_starts()
    total = total_len()
    D = [(starts[i + 1] if i + 1 < len(starts) else total) - starts[i]
         for i in range(len(SHOTS))]
    bad = []
    for i in range(len(SHOTS) - 1):
        x = xf(i)
        if x <= 0:
            bad.append("镜 %d 的转场 %.2fs 必须大于 0" % (i + 1, x))
        elif x > min(D[i], D[i + 1]) - 1e-6:
            bad.append("镜 %d 的转场 %.2fs 不短于相邻镜的内容时长(%.1fs/%.1fs)"
                       % (i + 1, x, D[i], D[i + 1]))
    return bad


_default("VIDEO_HEADROOM", 0.5)        # 素材段至少要比旁白算出来的镜长再多这么多秒
_default("VIDEO_BLACK_MIN", 0.4)       # 连续黑帧超过这么久就算「卡」，不是转场自带的暗场


_default("BLACK_CACHE", "black_spans.json")


def black_spans(path):
    """`blackdetect` 扫出来的黑段 [(起, 止), ...]，**按 (大小, mtime) 缓存**。

    不缓存的话每跑一次 check 就要把十一个视频中间件整个解码一遍 ——
    判据是对的，代价放错了地方：check 应该是随时能跑的，慢到要等就没人跑，
    而不跑的判据等于没有。这和 vo_durs() 用 vo_times.json 缓 ffprobe 是同一件事。

    键里带 mtime 和大小，所以 prep 重出之后自动失效，不会拿旧结果糊弄。
    """
    try:
        st = os.stat(path)
    except OSError:
        return []
    key = "%s|%d|%d" % (os.path.basename(path), st.st_size, int(st.st_mtime))
    cache = {}
    if os.path.exists(BLACK_CACHE):
        try:
            cache = json.load(open(BLACK_CACHE, encoding="utf-8"))
        except Exception:
            cache = {}
    if key in cache:
        return [tuple(x) for x in cache[key]]
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", path, "-an",
                        "-vf", "blackdetect=d=%.2f:pic_th=0.98:pix_th=0.12"
                               % VIDEO_BLACK_MIN,
                        "-f", "null", "-"], capture_output=True, text=True)
    spans = [(float(m.group(1)), float(m.group(2)))
             for m in re.finditer(r"black_start:([\d.]+) black_end:([\d.]+)",
                                  r.stderr or "")]
    cache[key] = spans
    with open(BLACK_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    return spans


def check_video():
    """视频镜自己的判据。**静图那套判据一条都套不上它，所以要单独一张。**

    查五件事，前三件都是"不查就会在成片上静默出错"的那一类：

    1. **段够不够长。** 镜长由旁白算出来，素材段由 ss/to 声明，两者没有任何
       约束关系。段短了 pass_a 会冻结末帧补足 —— 画面会僵在那里好几秒，
       而 ffmpeg 退出码是 0、check 全绿、只有真的看片子才发现。
    2. **入点出点在源片里。** ss 写超过源片时长，ffmpeg 输出一段空的，也不报错。
    3. **同一份素材的相邻两镜段不能重叠。** 重叠就是同一段放了两遍，
       观众读作卡带。这是视频版的 check_reuse。
    4. 声明了 to 没有 —— 不声明出点，prep 会一路读到片尾，出一个几百兆的中间件。
    5. 时间码写成 20.10 这种（想写 20:10）—— 值合法、位置错，量不出来。
    """
    bad = []
    vids = [i for i in range(1, len(CLIPS) + 1) if is_video(i)]
    if not vids:
        return bad
    durs = timeline()[1]
    info_cache = {}
    for i in vids:
        c = CLIPS[i - 1]
        name = c["video"]
        if not c.get("to"):
            bad.append("镜 %d 是视频镜但没写 to= —— 出点不声明，prep 会一路读到片尾" % i)
            continue
        a, b, seg = video_seg(i)
        if seg <= 0:
            bad.append("镜 %d 的 ss=%r / to=%r 反了或相等" % (i, c.get("ss"), c.get("to")))
            continue
        path = os.path.join(SRC, name)
        if name not in info_cache:
            info_cache[name] = probe_video(path) if os.path.exists(path) else None
        info = info_cache[name]
        if info is None:
            continue                      # 缺素材由 check_timeline 的「缺素材」那条管
        src_dur = info[2]
        if b > src_dur + 1e-3:
            bad.append("镜 %d 的 to=%s（%.1fs）超出 %s 的时长 %.1fs —— "
                       "ffmpeg 会安静地少给你几秒" % (i, c.get("to"), b, name, src_dur))
        need = durs[i - 1] if i - 1 < len(durs) else 0.0
        if seg + 1e-3 < need:
            bad.append("镜 %d 的素材段只有 %.2fs，旁白要 %.2fs —— "
                       "pass_a 会冻结末帧补足，画面会僵住。把 to 往后放，"
                       "或者把这一镜的旁白挪一句走" % (i, seg, need))
        elif seg < need + VIDEO_HEADROOM:
            bad.append("镜 %d 的素材段 %.2fs 只比旁白 %.2fs 多 %.2fs —— "
                       "余量不足 %.1fs。旁白重新生成后镜长会变，现在刚好等于以后不够"
                       % (i, seg, need, seg - need, VIDEO_HEADROOM))
    # ---- 段**内部**有没有不能用的黑帧 ----
    # 这一条是踩出来的：档案影像里常夹着现代标题卡、机构水印黑卡、黑场。
    # 段够长、入出点合法、不重叠 —— 前三条全过，而金句那一镜开口三秒是一块
    # 写着 "NFSA 2006" 的黑屏。渲得出来、退出码 0、check 全绿，
    # 只有真看画面才发现，而看的时候还得刚好采到那一帧
    # （15 秒一帧的联络表就漏掉了它）。
    #
    # 用 blackdetect 一次解码扫完 vidNN.mp4，不逐帧 seek —— 逐帧 seek 在
    # 十分钟以上的源片上要几分钟，慢到没人会跑。
    for i in vids:
        vf = "vid%02d.mp4" % i
        if not os.path.exists(vf):
            continue          # 还没 prep，跳过；prep 之后再跑一次 check
        need = durs[i - 1] if i - 1 < len(durs) else 0.0
        for a, b in black_spans(vf):
            if a >= need:
                continue      # 落在这一镜用不到的那一段里，不管
            bad.append("镜 %d 的素材段内 %.1f~%.1fs 是黑帧（这一镜只用前 %.1fs，"
                       "所以它会**出现在成片上**）—— 多半是现代标题卡或机构水印卡，"
                       "换一段或把 ss 往后挪" % (i, a, min(b, need), need))

    # 相邻同源镜的段重叠
    for i in range(1, len(CLIPS)):
        if not (is_video(i) and is_video(i + 1)):
            continue
        if clip_key(CLIPS[i - 1]) != clip_key(CLIPS[i]):
            continue
        a1, b1, _ = video_seg(i)
        a2, b2, _ = video_seg(i + 1)
        if a2 < b1 - 1e-3 and a1 < b2 - 1e-3:
            bad.append("镜 %d/%d 共用 %s，但取的段重叠（%.1f~%.1f 和 %.1f~%.1f）—— "
                       "同一段放两遍，观众读作卡带"
                       % (i, i + 1, clip_key(CLIPS[i - 1]), a1, b1, a2, b2))
    return bad


def selftest_video():
    """回归：造三种错各一个，检查必须报警。没有视频镜时直接算过。

    **判据是「那一句话有没有出现」，不是「问题总数有没有变多」。**
    数量判会被自己骗：注入的错误常常**替换**掉同一镜上原有的那条问题——
    比如「余量不足 0.5s」被「ss/to 反了或相等」顶掉，总数一条没变，
    于是自测报「检查失效了」，而失效的是自测本身。
    （selftest_moves 早踩过同一个坑，那里的解法是换一镜；这里换镜没用，
    因为项目常常只有一个视频镜，所以改成认错误原文。）
    """
    if not any(is_video(i) for i in range(1, len(CLIPS) + 1)):
        return True
    print("回归自测: 视频镜 —— 段长为 0 / 没写 to / 出点超出源片，三种各造一个")
    i = next(i for i in range(1, len(CLIPS) + 1) if is_video(i))
    keep = dict(CLIPS[i - 1])
    base = len(check_video())

    def case(patch, drop, sig):
        CLIPS[i - 1].clear(); CLIPS[i - 1].update(keep)
        CLIPS[i - 1].update(patch)
        for k in drop:
            CLIPS[i - 1].pop(k, None)
        hit = any(("镜 %d " % i) in b and sig in b for b in check_video())
        CLIPS[i - 1].clear(); CLIPS[i - 1].update(keep)
        return hit

    ok = [case({"to": keep.get("ss", 0)}, (), "反了或相等"),
          case({}, ("to",), "没写 to="),
          case({"to": 99999}, (), "超出")]
    for nm, r in zip(("段长为 0", "没写 to", "出点超出源片"), ok):
        print("          %-14s %s" % (nm, "对" if r else "**检查失效了**"))
    print("          当前配置 %d 条 —— %s" % (base, "对" if base == 0 else "有问题要处理"))
    return all(ok) and len(check_video()) == base


def check_scrim():
    """守住 scrim_on() 那条守卫**本身**。

    这条守卫没有症状：把它拿掉，外挂字幕的片子会重新被白白压暗画面下三分之一，
    而全套检查一条都不会报 —— 成片只是"有点闷"。所以两头都钉一次：
    只测"外挂时关掉"的话，把 scrim_on 写成 `return False` 也能过，
    那会把烧录字幕的片子推进另一个坑（白字糊在亮底上）。
    """
    bad = []
    save = (globals()["SUB_MODE"], globals()["SCRIM_ALPHA"])
    try:
        globals()["SUB_MODE"], globals()["SCRIM_ALPHA"] = "srt", 0.30
        if scrim_on():
            bad.append("scrim_on() 在 SUB_MODE='srt' 下返回真 —— 外挂字幕由播放器渲染，"
                       "压暗带没有保护对象，留着只会白白压暗画面下三分之一。")
        globals()["SUB_MODE"] = "burn"
        if not scrim_on():
            bad.append("scrim_on() 在 SUB_MODE='burn' + SCRIM_ALPHA=0.30 下返回假 —— "
                       "烧录字幕没有压暗带，近白的字会糊在亮底上。")
    finally:
        globals()["SUB_MODE"], globals()["SCRIM_ALPHA"] = save
    if SCRIM_ALPHA > 0 and SUB_MODE != "burn":
        bad.append("SCRIM_ALPHA=%.2f 但 SUB_MODE=%r —— scrim_on() 已经把它挡掉了，"
                   "配置里请写成 0.0，别让下一个人以为画面底部压过一档。"
                   % (SCRIM_ALPHA, SUB_MODE))
    return bad


def check_moves():
    bad = []
    for i, s in enumerate(SHOTS, 1):
        # 视频镜没有取景窗，z/f 对它没有意义。不跳过的话它会被当成"标了 kenburns
        # 却起止一样"而长期报警 —— 判据少建模了一种镜，就会稳定地冤枉它。
        if is_video(i):
            continue
        z0, z1 = s["z"]
        for (fx, fy), z, w in ((s["f0"], z0, "起"), (s["f1"], z1, "止")):
            lo, hi = 1 / (2 * z), 1 - 1 / (2 * z)
            for v, ax in ((fx, "x"), (fy, "y")):
                if not (lo - 1e-6 <= v <= hi + 1e-6):
                    bad.append("镜 %d %s幅 f%s=%.3f 超出 z=%.2f 的可达范围 [%.3f,%.3f]"
                               % (i, w, ax, v, z, lo, hi))
        want = abs(s["f1"][1] - s["f0"][1]) + abs(s["f1"][0] - s["f0"][0])
        zmax = max(z0, z1); can = max(0.0, 1 - 1 / zmax)

        # 运动方式和参数必须互相印证。"起止不小心写成一样"正是那个最贵的 bug
        # 长出来的样子，所以两边都拦，不去猜哪个是真的。
        m = motion_of(i)
        moving = want > 1e-6 or abs(z1 - z0) > 1e-6
        if m not in ("kenburns", "static"):
            bad.append("镜 %d 的 motion=%r 不认识，只能是 'kenburns' / 'static'"
                       "（视频镜不用写 motion，CLIPS 里给了 video= 就是）" % (i, m))
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
    """回归：每一类错误各造一个，检查必须报警。理由同 selftest_safe()。"""
    if not SHOTS:
        return True
    keep = [dict(s) for s in SHOTS]
    base = len(check_moves())
    # **造错误的那一镜不能是视频镜。** check_moves 对视频镜整镜跳过（它没有取景窗），
    # 挑中视频镜时三个 case 全部"多报 0 条"，回归自测于是报「检查失效了」——
    # 而失效的其实是自测本身。视频镜自己的回归在 selftest_video()。
    plain = next((i for i in range(1, len(SHOTS) + 1) if not is_video(i)), None)
    if plain is None:
        print("回归自测: 全部是视频镜，check_moves 不适用")
        return True

    def case(name, i, patch):
        SHOTS[i - 1] = dict(keep[i - 1], **patch)
        n = len(check_moves())
        SHOTS[i - 1] = dict(keep[i - 1])
        print("回归自测: %-24s 多报 %d 条 —— %s"
              % (name, n - base, "对" if n > base else "**检查失效了**"))
        return n > base

    moving = next((i for i, s in enumerate(SHOTS, 1)
                   if not is_video(i)
                   and (abs(s["f1"][0] - s["f0"][0]) + abs(s["f1"][1] - s["f0"][1]) > 1e-6
                        or abs(s["z"][1] - s["z"][0]) > 1e-6)), None)
    ok = []
    if moving:
        ok.append(case("有行程的镜标成 static", moving, dict(motion="static")))
    z, f = keep[plain - 1]["z"][0], keep[plain - 1]["f0"]
    ok.append(case("原地不动的镜标成 kenburns", plain,
                   dict(motion="kenburns", z=(z, z), f0=f, f1=f)))
    ok.append(case("motion 写错字", plain, dict(motion="ken_burns")))
    print("          当前配置 %d 条 —— %s" % (base, "对" if base == 0 else "有问题要处理"))
    return all(ok) and len(check_moves()) == base


def check_credits():
    """素材来源与授权的登记。**只对"自己找来的"素材是硬约束。**

    自己生成的图没有第三方权利问题；从开放数据、图库、公版录音里拿来的不一样 ——
    CC-BY 要求署名，而"公有领域"对**作品**成立不等于对**某一次录音或翻拍**成立。
    这类错误成片、审核、发布全都不会拦，要到被投诉才知道，所以放进 check。
    """
    bad = []
    need = ("title", "holder", "source", "license", "url")
    if IMG_SOURCE not in ("generated", "found"):
        bad.append("IMG_SOURCE=%r 不认识，只能是 'generated' 或 'found'" % IMG_SOURCE)
    elif IMG_SOURCE == "found":
        seen = set()
        for c in CLIPS:
            k = clip_key(c)
            if k in seen:          # 一份素材用在多镜，登记一次就够
                continue
            seen.add(k)
            e = CREDITS.get(k)
            if not e:
                bad.append("素材 %s 没登记来源（IMG_SOURCE='found' 时每一份都要，"
                           "视频也算）" % k)
            else:
                miss = [k2 for k2 in need if not str(e.get(k2, "")).strip()]
                if miss:
                    bad.append("素材 %s 的来源登记缺 %s" % (k, "/".join(miss)))
    if IMG_SOURCE == "generated" and CREDITS:
        # 混用是常态，登记了就要登记全、而且要真的用在片子里 ——
        # 登记一个没人用的文件名等于没登记，而那正是最容易发生的写错方式。
        used = set(clip_key(c) for c in CLIPS)
        for k in sorted(CREDITS):
            e = CREDITS[k]
            if k not in used:
                bad.append("CREDITS 里登记了 %s，但没有任何一镜用它 —— "
                           "文件名写错了？这条登记不会出现在素材来源表里。" % k)
                continue
            miss = [k2 for k2 in need if not str(e.get(k2, "")).strip()]
            if miss:
                bad.append("素材 %s 的来源登记缺 %s" % (k, "/".join(miss)))
    if MUSIC_MODE not in ("generated", "public_domain", "library", "none"):
        bad.append("MUSIC_MODE=%r 不认识，只能是 'generated' / 'public_domain' / 'library' / 'none'"
                   % MUSIC_MODE)
    elif MUSIC_MODE == "library" and not str(MUSIC_FROM_LIBRARY).strip():
        bad.append("MUSIC_MODE='library' 却没填 MUSIC_FROM_LIBRARY —— "
                   "不记下用了库里哪一条，做完就没法回去 `add --used`，"
                   "下一支查库时会不知道它已经用过了")
    elif MUSIC_MODE == "public_domain":
        miss = [k for k in ("work", "performer", "source", "license", "url")
                if not str(MUSIC_CREDIT.get(k, "")).strip()]
        if miss:
            bad.append("公版配乐的 MUSIC_CREDIT 缺 %s —— **录音权和作品权是两回事**，"
                       "填不出来说明这条录音的授权还没查清楚" % "/".join(miss))
    return bad


def selftest_credits():
    """回归：把登记抽掉，检查必须报警。

    **两路各要一条自己的干净基线，不能共用"当前配置"的 base。**
    原来两路都拿 `base = len(check_credits())` 比，而 base 里可能已经有一条
    **别的**告警（实际撞上的是 `MUSIC_MODE='library'` 还没填 `MUSIC_FROM_LIBRARY`）：
    注入故障后条数不增，自测就报"**检查失效了**" —— 假警，而且偏偏是在
    检查本身好好的时候报。一个乱叫的自测和一个不叫的自测一样会被无视。

    修法：基线和注入只差**被测的那一维**，别的维度保持不动。
    """
    global IMG_SOURCE, MUSIC_MODE, CREDITS, MUSIC_CREDIT
    ki, km, kc, kmc = IMG_SOURCE, MUSIC_MODE, CREDITS, MUSIC_CREDIT
    empty = dict(work="", performer="", source="", license="", url="")

    IMG_SOURCE, CREDITS = "generated", {}                    # 素材那一路的干净基线
    base_i = len(check_credits())
    IMG_SOURCE, CREDITS = "found", {}
    a = len(check_credits()) > base_i
    IMG_SOURCE, CREDITS = ki, kc

    MUSIC_MODE, MUSIC_CREDIT = "none", kmc                   # 配乐那一路的干净基线
    base_m = len(check_credits())
    MUSIC_MODE, MUSIC_CREDIT = "public_domain", empty
    b = len(check_credits()) > base_m
    MUSIC_MODE, MUSIC_CREDIT = km, kmc

    # 第三条：**混用**。生成图里掺一张真档案，登记齐全 ——
    # 交付物里必须出现它。判据只能看 credits() 的**输出**：
    # 旧版这种配置下 check 一条都不报（它确实没错），错的是写出去的那份文件。
    IMG_SOURCE = "generated"
    CREDITS = {clip_key(CLIPS[0]): dict(title="T", holder="H", source="S",
                                        license="CC BY 4.0", url="U")}
    txt = "\n".join(credits(dry=True))
    c_ok = (clip_key(CLIPS[0]) in txt and "CC BY 4.0" in txt
            and "无第三方权利" not in txt.split("## 配乐")[0])
    IMG_SOURCE, CREDITS = ki, kc

    print("回归自测: 素材标 found 但没登记来源 —— %s" % ("对" if a else "**检查失效了**"))
    print("          配乐标 public_domain 但没填授权 —— %s" % ("对" if b else "**检查失效了**"))
    print("          生成图里掺了登记过的真档案 —— %s"
          % ("对" if c_ok else "**登记没写进素材来源表**"))
    return a and b and c_ok


def check_endcard():
    """**下集预告板不能指向本集自己。**

    换集时从上一支复制脚本，`ENDCARD` 会原样继承过来。《白衣女人》集二就这样
    带着集一的板子渲完了整片 —— 成片里写着「下一集 · 黑水园」，而黑水园就是这一集。
    `check_seg` 只验 ENDCARD 该不该存在，不验里面写了什么，所以一路全绿，
    **是用户看片的时候发现的**。

    判据很笨但够用：预告板的 head 里不许出现本集的 TITLE。

    **但 head 和 TITLE 完全相等不算**：竖版的 ENDCARD 是本片自己的片尾标题板
    （head=TITLE 是设计如此），合并成一份引擎之后这条会对每支竖版报假警。
    出过事的那种是「下一集 · 黑水园」—— 包含本集标题、但不等于它。
    """
    if not ENDCARD:
        return []
    head = ENDCARD.get("head", "")
    if TITLE and TITLE in head and head.strip() != TITLE.strip():
        return ["下集预告板写的是本集自己（TITLE=%r 出现在 ENDCARD.head=%r）—— "
                "换集时忘了重填？" % (TITLE, ENDCARD["head"])]
    return []


def check_template_leftovers():
    """模板里留着上一支的示例值，换片时最容易漏 —— 而且**一路都不会报错**。

    竖版在《按图选人》上真漏过：汉代片子的尾板上印着 "1816 · 无夏之年"。
    check 过了、渲染成功、响度对、字幕干净，**只有抽帧用眼睛看才看得见**。
    横版模板的示例是《经度》，TITLE_CARD 直接取 TITLE/SUBTITLE 烧进画面，同一个坑。

    两个模板的示例专名都列在这里（引擎只有一份，两边都得拦）。
    换模板示例时把 LEFTOVERS 换成新示例里的专名。
    """
    LEFTOVERS = ("经度", "一个木匠的四十年", "哈里森", "Harrison",            # 横版示例
                 "1816", "无夏之年", "坦博拉", "德莱斯", "没有夏天的那一年")   # 竖版示例
    fields = [("TITLE", TITLE), ("SUBTITLE", SUBTITLE), ("SEG_NAME", SEG_NAME),
              ("ENDCARD", str(ENDCARD or ""))]
    fields += [("SHOT_LABELS[%s]" % k, str(v)) for k, v in sorted(SHOT_LABELS.items())]
    return ["%s 里还留着模板示例 %r（值：%r）" % (name, x, val)
            for name, val in fields for x in LEFTOVERS if x in val]


def check_coldopen(lines):
    """**冷开场那句不能压在开场淡入里。**

    第二节写着「冷开场第一句的 pre 给 1.2~1.6s」，但不写也能跑、别的检查也不报，
    所以**连着两支都漏了**（《白衣女人》集一集二，第二支是在集一刚把这条写进技能之后）。
    光写进文档不管用，这里拦。

    判据：第一条旁白的**出声点**必须落在 FADE_IN 之后，且留 0.2s 余量。
    出声点 = 第一条字幕起点 + 0.10（字幕比声音早 0.10s 起，见 timeline()）。
    """
    if not SEG_FIRST or FADE_IN <= 0 or not lines:
        return []
    vs = lines[0][4]                      # 第一条旁白的落点
    if vs < FADE_IN + 0.2:
        return ["冷开场压在淡入里：旁白 %.2fs 出声，而 FADE_IN 要到 %.2fs 才走完 —— "
                "给第一条 NARR 写 pre=1.2~1.6（现在是 %.2f）"
                % (vs, FADE_IN, vs)]
    return []


# 「换项目必须清空」的清单。**以前它只活在注释里，于是漏过 SFX。**
# 放在这里是为了让它被打印出来 —— 一张没人看得见的清单等于没有清单。
# 每一项写成 (名字, 为什么危险)。check 每次都打，不判对错（对错只有人知道）。
_default("CARRY_OVER", [
    ("SFX",              "整表继承会指向上一支的文件和镜号；check_sfx 抓 shot 越界，但同名文件抓不到"),
    ("SRC_NATIVE",       "填成上一支的尺寸，分辨率判据就全部失真（文件尺寸会骗人，只能靠记录）"),
    ("PP_ACCEPT_REASON", "非空 = pp<1.0 的拦截被降成提示。**新项目必须留空**"),
    ("GATE_SCRIPT_OK",   "继承上一支的签字 = 这一支的门禁从没被人过过"),
    ("GATE_PREVIEW_OK",  "同上"),
    ("ENDCARD",          "尾板文字会带着上一支的片名和落款"),
    ("CREDITS",          "素材来源表指向上一支的图"),
    ("MUSIC_CREDIT",     "配乐授权写着上一支那首"),
    ("TITLE / SUBTITLE", "片头字卡是全片唯一烧进画面的字，错了要重渲整段"),
])



def print_carry_over():
    print("\n=== 换项目必须逐项过一遍（继承来的值不会报错，只会安静地错）===")
    for name, why in CARRY_OVER:
        print("  %-18s %s" % (name, why))


def check_sfx():
    """音效表在 `check` 里就要验，不能等到 pass_c。

    坑：从上一支复制脚本时 `SFX` 会**整表继承**过来，指向上一支的文件、上一支的镜号，
    而 `check` 一声不吭全绿，渲到 `pass_c` 才 `sys.exit`，前面 prep/a/b 三趟白跑。
    那张「换项目必须清空」的清单以前只写在这段注释里，所以漏过 SFX 自己 ——
    现在做成了模块级的 CARRY_OVER，check 每次都会打出来。

    **2026-09-25 拆共用模块时发现：这里原来读 `s.get("file")`，而 SFX 表的键是 `f`。**
    于是「缺文件」这一半从来没报过警 —— 自测造错时也写的 `file=`，自己跟自己对上了，
    照样打印「对」。自测的输入必须长得和真配置一样，否则它验的是另一个函数。
    """
    bad = []
    for s in SFX:
        f = s.get("f", "")
        if s.get("shot") and s["shot"] > len(SHOTS):
            bad.append("音效 %s 的 shot=%d 超出本段 %d 镜 —— **多半是从上一支继承来的 SFX 表**"
                       % (f, s["shot"], len(SHOTS)))
        p = os.path.join(SRC, f) if f else ""
        if f and not os.path.exists(p):
            bad.append("音效缺文件: %s —— 要么补素材，要么这一条本来就不该在表里" % f)
    return bad


def selftest_sfx():
    """回归：造一个越界镜号 + 一个不存在的文件，check_sfx 必须各报一条。"""
    global SFX
    keep = SFX
    # 键名和真配置一模一样（f / shot / off / tgt / fi / fo / dur）—— 原来写的是
    # file= / target=，check_sfx 读错键也照样"通过"，见 check_sfx 的说明
    SFX = [dict(f="__不存在的音效__.mp3", shot=len(SHOTS) + 99, off=0.0,
                tgt=-30.0, fi=0.1, fo=0.1, dur=1.0)]
    n = len(check_sfx())
    SFX = keep
    now = len(check_sfx())
    print("回归自测: 继承来的音效表（越界镜号 + 缺文件） → 报警 %d 条 —— %s"
          % (n, "对" if n >= 2 else "**检查失效了**"))
    print("          当前配置 报警 %d 条 —— %s" % (now, "对" if now == 0 else "有问题"))
    return n >= 2 and now == 0


def check_timeline():
    lines, durs, total, _ = timeline()
    _, missing = vo_durs()
    cuts = cut_points()
    bad, warn = [], []
    bad += check_claims()
    bad += check_pace()
    bad += check_mode()
    bad += check_subs()
    bad += check_safe()
    bad += check_seg()
    bad += check_reuse()
    bad += check_xfades()
    bad += check_moves()
    bad += check_scrim()
    bad += check_video()
    bad += check_resolution()
    bad += check_coldopen(lines)
    bad += check_endcard()
    bad += check_template_leftovers()
    bad += check_langs()
    bad += check_sfx()

    for st, en, txt, _, _, _ in lines:
        for c in cuts:
            if st - 0.25 < c < en + 0.25:
                bad.append("转场 %.1fs 压到了字幕『%s』" % (c, txt))
        if en > total + 1e-6:
            bad.append("字幕『%s』结束于 %.1fs，超出片长 %.1fs" % (txt, en, total))
    for c in CLIPS:
        if not os.path.exists(os.path.join(SRC, clip_key(c))):
            warn.append("缺素材: " + clip_key(c))
    if len(CLIPS) != len(SHOTS):
        bad.append("CLIPS %d 张对不上 SHOTS %d 镜" % (len(CLIPS), len(SHOTS)))

    if missing:
        warn.append("**时间轴是估算的** —— 还缺 %d 条旁白 (%s...)。"
                    "配音生成之后跑 sync 会自动重算" % (len(missing), missing[0]))
    bad += check_credits()
    if not music_on():
        # SFX 是 dict 列表，不是 tuple —— 写成 `for f, *_ in SFX` 会去解包字典的**键**，
        # 于是永远数出 0 条而不报错。没有音乐时音效是承重的，这个数不能骗人。
        miss = [s["f"] for s in SFX if not os.path.exists(os.path.join(SRC, s["f"]))]
        n = len(SFX) - len(miss)
        print("\n配乐: 无（MUSIC_MODE='none'）—— 音频是 %d 条旁白 + %d/%d 条音效"
              % (len(NARR), n, len(SFX)))
        for f in miss:
            warn.append("缺音效: " + f)
        print("      旁白本来就是连续的音床，所以归一化照常（norm_mode=%s）"
              % norm_mode())
    elif not os.path.exists(MUSIC):
        warn.append("音乐还没就位")
    else:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "csv=p=0", MUSIC],
                           capture_output=True, text=True)
        try:
            mdur = float(p.stdout.strip())
            if MUSIC_IN + total > mdur + 1e-3:
                bad.append("音乐不够长: 从 %.1fs 切入需要到 %.1fs，全曲只有 %.1fs"
                           % (MUSIC_IN, MUSIC_IN + total, mdur))
            else:
                print("\n配乐(%s): 全曲 %.1fs，从 %.1fs 切入，余地 %.1fs"
                      % ({"generated": "生成", "library": "库里挑的"}.get(MUSIC_MODE, "公版"),
                         mdur, MUSIC_IN, mdur - total))
            # 诗片的判据是 1.6 倍（音乐是唯一音源，某处塌下去就毁了）。
            # 讲述片全程有旁白盖着，音乐只在句间的缝里露出来，要挑的落点少得多，
            # 所以放宽到 1.4 倍。照抄诗片那条会一直报一个不需要处理的警。
            if MUSIC_MODE in ("generated", "library") and mdur < total * 1.4:
                warn.append("音乐只比片长多 %.0fs（不到片长的 0.4 倍），切入点几乎没得挑"
                            % (mdur - total))
            if MUSIC_MODE == "public_domain":
                warn.append("公版录音：`pick` 只挑响度、**挑不出乐句边界** —— "
                            "切入点定完要听首尾，另外跑 `mquality` 看底噪和带宽")
        except ValueError:
            warn.append("读不出音乐时长")

    if HARD_LIMIT and total > HARD_LIMIT - LIMIT_SAFETY:
        (bad if total > HARD_LIMIT else warn).append(
            "片长 %.1fs %s硬上限 %.0fs（余量 %.1fs）—— 配音齐了跑 `vofit`，"
            "它会算 atempo 倍率；倍率不够会告诉你还得砍多少字"
            % (total, "超过" if total > HARD_LIMIT else "逼近", HARD_LIMIT, LIMIT_SAFETY))

    ns = sum(1 for n in range(1, len(SHOTS) + 1) if is_static(n))
    nv = sum(1 for n in range(1, len(SHOTS) + 1) if is_video(n))
    print("\n片长 %.1fs (%d:%04.1f)  镜头 %d  旁白 %d 条  %dx%d"
          % (total, total // 60, total % 60, len(SHOTS), len(NARR), W, H))
    # **视频镜要单独数。** 不数的话它会被并进"运镜"，于是汇总上写着运镜 11 镜、
    # 实际一镜运镜都没有 —— 汇总是最常被照抄进制作说明的一行，错在这里传得最远。
    print("运动: %s（静帧 %d 镜 / 运镜 %d 镜 / 视频 %d 镜）  配乐: %s  素材: %s"
          % ({"kenburns": "运镜", "static": "静帧"}.get(MOTION, MOTION),
             ns, len(SHOTS) - ns - nv, nv,
             {"generated": "生成", "public_domain": "公版",
              "library": "库里挑的", "none": "无"}.get(MUSIC_MODE),
             {"generated": "按任务书生成", "found": "自己找的"}.get(IMG_SOURCE)))
    if SUB_MODE == "burn":
        print("字幕: **烧进画面**（抖音/小红书那一路）")
    else:
        print("字幕: **外挂 SRT**（%s），由播放器渲染；标题字卡/尾板烧进画面"
              % " / ".join(srt_name(l) for l in LANGS))
    if len(LANGS) > 1:
        print("音轨: %d 条（%s），默认 %s；上传件是单音轨 + 独立音频"
              % (len(LANGS), " / ".join(LANG_INFO[l]["name"] for l in LANGS),
                 LANG_INFO[DEFAULT_LANG]["name"]))
    print("每镜时长: " + "  ".join("%.1f" % d for d in durs))
    print("转场落点: " + "  ".join("%.1f" % c for c in cuts))
    selftest_seg()
    selftest_safe()
    selftest_reuse()
    selftest_sfx()
    selftest_moves()
    selftest_video()
    selftest_credits()
    selftest_langs()
    for w in warn:
        print("提示: " + w)
    print_carry_over()
    if bad:
        print("\n!! 问题 %d 条:" % len(bad))
        for b in bad:
            print("   - " + b)
    else:
        print("\n自检通过。")
    return not bad


def sync():
    """量旁白 -> 打出时间轴。改了配音先跑它（缓存会自动失效，不用手工清）。"""
    for lang in LANGS:
        p = vo_cache_of(lang)
        if os.path.exists(p):
            os.remove(p)
    global _VO
    _VO = {}
    lines, durs, total, _ = timeline()
    durs_map, missing = vo_durs()
    print("=== 旁白实测 ===")
    for n in NARR:
        d, real = durs_map[n["vo"]]
        print("  镜%-3d %-11s %6.2fs %s  %s"
              % (n["shot"], n["vo"], d, "" if real else "(估算)",
                 "".join(sub_lines(n["txt"]))[:24]))
    print("\n旁白净时长 %.1fs，加气口后片长 %.1fs" % (sum(durs_map[n["vo"]][0] for n in NARR), total))
    st = shot_starts()
    print("\n=== 每镜 ===")
    for i, d in enumerate(durs):
        print("  镜%-3d 起 %6.2f  dur %5.2f  xf %.2f"
              % (i + 1, st[i], d, xf(i) if i < len(SHOTS) - 1 else 0.0))
    if missing:
        print("\n还缺 %d 条旁白，上面带 (估算) 的是按 est 排的。" % len(missing))


def langfit(lang="en"):
    """把某条语言的旁白**逐句**压进中文定出来的槽里。

    ---- 为什么是逐句，不是整条一个倍率（竖版 vofit 那样）----
    vofit 解决的是"整片超硬线"，全片同一个倍率听不出来。这里解决的是
    "这一句和画面对不上"：各句超出的比例天差地别，拿全片平均倍率去压，
    短句被无谓地拉快、长句照样压不进去，**而且两头都听得出来**。

    ---- 倍率永远从原件算 ----
    原件在 VO_RAW_OF[lang]，第一次跑时自动备份。拿"已经压过一次"的文件算倍率
    再作用到原件上，第二次调整会走反方向，而且一声不吭（竖版 vofit 踩过）。

    ---- 压不进去的句子不压 ----
    报出这一句还得砍几个词，并且把文件**放回原速**（不是留着上一次压的结果 ——
    那会让磁盘上的状态取决于跑过几次，无法复现）。这时脚本 exit 1，
    但塞得下的那些句子已经压好了：逐句是彼此独立的，全盘拒绝只会让你多跑几趟。
    真正的安全网是 check_langs()，它每次 check 都从磁盘重验一遍。
    """
    if lang == DEFAULT_LANG:
        sys.exit("!!! langfit 是把别的语言压进 %s 的槽，不能对 %s 自己跑"
                 % (DEFAULT_LANG, DEFAULT_LANG))
    if lang not in LANGS:
        sys.exit("!!! LANGS 里没有 %r —— 先在「双语音轨」那一节把它打开" % lang)
    vdir = VO_DIR_OF.get(lang, lang)
    if not os.path.isdir(vdir):
        sys.exit("!!! 没有 %s/ —— %s 旁白还没就位" % (vdir, lang))
    raw_dir = VO_RAW_OF.get(lang, "vo_%s_raw" % lang)
    if not os.path.isdir(raw_dir):
        os.makedirs(raw_dir)
        for x in NARR:
            src = vo_path(x, lang)
            if os.path.exists(src):
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-c", "copy",
                                os.path.join(raw_dir, os.path.basename(src))], check=True)
        print("原件已备份到 %s/（以后每次都从这里重新推导，压不会叠加）" % raw_dir)

    slots = lang_slots()
    rows, missing = [], []
    for k, x in enumerate(NARR):
        dst = vo_path(x, lang)
        raw = os.path.join(raw_dir, os.path.basename(dst))
        if not os.path.exists(raw):
            missing.append(x["vo"]); continue
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "csv=p=0", raw],
                           capture_output=True, text=True)
        try:
            d = float(r.stdout.strip())
        except ValueError:
            missing.append(x["vo"]); continue
        base, borrow = slots[k]
        rows.append((x, dst, raw, d, base + borrow))
    if not rows:
        sys.exit("!!! %s/ 下一条原件都没量到" % raw_dir)

    # 换算"还得砍几个词"用的语速：EN_RATE 填了就用它，没填就用**本批实测**。
    # 用本批实测比填一个通行值靠谱 —— 语速取决于音色和表演方向，不是常数。
    words = sum(n_words(lang_text(x, lang)) for x, _, _, _, _ in rows)
    speech = sum(d for _, _, _, d, _ in rows)
    rate = EN_RATE or (words / speech if speech else 0.0)

    print("")
    print("=== langfit %s：中文定槽，逐句压（倍率上限 ×%.2f，可借静默 %.2fs）==="
          % (lang, LANG_TEMPO_MAX, LANG_BORROW))
    over, moved = [], 0
    for x, dst, raw, d, room in rows:
        if d <= room + 1e-3:
            act = "原速"
            cmd = ["ffmpeg", "-y", "-v", "error", "-i", raw, "-c", "copy", dst]
        else:
            tempo = d / room
            if tempo > LANG_TEMPO_MAX:
                over.append((x["vo"], d, room, tempo,
                             (d - room * LANG_TEMPO_MAX) * rate))
                act = "**压不进，已放回原速**"
                cmd = ["ffmpeg", "-y", "-v", "error", "-i", raw, "-c", "copy", dst]
            else:
                act = "×%.3f" % tempo
                moved += 1
                cmd = ["ffmpeg", "-y", "-v", "error", "-i", raw,
                       "-filter:a", "atempo=%.6f" % tempo, "-q:a", "2", dst]
        if subprocess.run(cmd).returncode != 0:
            sys.exit("!!! 处理 %s 失败" % x["vo"])
        print("  %-11s 槽 %5.2f  原件 %5.2f  %s" % (x["vo"], room, d, act))

    _VO.pop(lang, None)
    c = vo_cache_of(lang)
    if os.path.exists(c):
        os.remove(c)

    if missing:
        print("\n提示: %d 条没有原件（%s%s）—— 先把音频放进 %s/ 再跑一次"
              % (len(missing), ", ".join(missing[:3]),
                 "..." if len(missing) > 3 else "", vdir))
    print("\n本批 %s 实测语速 **%.2f 词/秒**（%d 词 / %.1fs）%s"
          % (lang, words / speech if speech else 0, words, speech,
             "" if EN_RATE else "  << EN_RATE 还是 None，把这个数填上去"))
    print("压了 %d 条，原速 %d 条。" % (moved, len(rows) - moved - len(over)))
    if over:
        print("\n!! %d 条压不进去（超过 ×%.2f 就不压了）：" % (len(over), LANG_TEMPO_MAX))
        for vo, d, room, tempo, cut in over:
            print("   %-11s 槽 %.2fs，现在 %.2fs，要 ×%.3f 才塞得下 —— "
                  "**还得砍约 %d 个词**" % (vo, room, d, tempo, int(-(-cut // 1))))
        print("\n   别把这活交给 atempo：听得出来的毛病换看不出来的错位，不是修好。")
        print("   要改的是英文稿，中文那条轨和画面一个字都不用动。")
        return False
    print("全部塞得进。**接着跑 check** —— 它会从磁盘上的文件再验一遍。")
    return True


# ================= 素材 =================
def prep():
    for i, c in enumerate(CLIPS, 1):
        _set_prep_key(i, None)      # 先撕印记：这一镜要是跳过了，a 会拦下来
        img = "img%02d.png" % i
        before = _sig(img)
        prep_one(i, c)
        after = _sig(img)
        if after and after != before:
            _set_prep_key(i, prep_key(i, c))
    probe()


def prep_one(i, c):
    if c.get("video"):
        return prep_video(i, c)
    src = os.path.join(SRC, c["src"])
    if not os.path.exists(src):
        print("   跳过(缺图): " + c["src"]); return
    if c.get("fit") == "plate":
        return prep_plate(i, c, src)
    z, cx, cy = c["zoom"], c["cx"], c["cy"]
    # 裁成成片比例（横版 16:9、竖版 9:16）。**两个分数都从 W/H 推**：
    # 两份手抄脚本时代这里各写死一套，翻漏一个就裁出细长条，而且不报错。
    rw, rh = _ratio()
    crop = ("crop=w='min(iw,ih/%.6f*%d/%d)':h='min(ih/%.6f,iw*%d/%d)':"
            "x='clip(%.6f*iw-out_w/2,0,iw-out_w)':"
            "y='clip(%.6f*ih-out_h/2,0,ih-out_h)'" % (z, rw, rh, z, rh, rw, cx, cy))
    # **空段要跳过**。GRADE="" 是合法状态（还没量直方图定调色，或这一支不需要），
    # 直接字符串拼接会拼出 "crop,,scale=" —— ffmpeg 报 `No such filter: ''`，
    # 而报错信息里完全看不出是哪个常数为空。
    _parts = [crop]
    if str(GRADE).strip():
        _parts.append(GRADE)
    if c["tweak"]:
        _parts.append(c["tweak"])
    _parts.append("scale=%d:%d:flags=lanczos" % PREP)
    _parts.append("setsar=1")
    vf = ",".join(_parts)
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", vf,
         "-frames:v", "1", "img%02d.png" % i],
        "prep %d/%d  %s" % (i, len(CLIPS), c["src"]))


def prep_key(i, c):
    """imgNN（视频镜还有 vidNN）由哪些输入做出来。任何一项变了，旧产物作废。"""
    src = os.path.join(SRC, c["video"] if c.get("video") else c["src"])
    return _key("prep", i, c, GRADE, PREP, W, H, PLATE_COLOR, VIDEO_FIT, FPS, _sig(src))


def prep_plate(i, c, src):
    """贴纸版式的 prep：整张图按 1:1（或缩小）贴在成片画框中央，四周补台纸。

    **不走 crop。** 走 crop 就等于承认要裁，而这条路的前提正是"这张不能裁"。

    出的是**成片尺寸**的 imgNN.png，不是 PREP 尺寸 —— 所以用贴纸版式的片子
    要把 PREP 设成成片尺寸，让 pass_a 的 static_vf 变成恒等重采样。
    PREP 还留在 3840x2160 的话，pass_a 会把整张台纸再缩一半，图就只有半幅大。
    check_resolution 会拦这个组合。
    """
    d = img_dims(src)
    if not d:
        print("   跳过(读不出尺寸): " + c["src"]); return
    w, h = d
    tw, th, f = plate_box(w, h)
    _parts = ["scale=%d:%d:flags=lanczos" % (tw, th)]
    if str(GRADE).strip():
        _parts.append(GRADE)
    if c.get("tweak"):
        _parts.append(c["tweak"])
    _parts.append("pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=%s" % (W, H, PLATE_COLOR))
    _parts.append("setsar=1")
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", ",".join(_parts),
         "-frames:v", "1", "img%02d.png" % i],
        "prep %d/%d  %s  贴纸 %dx%d -> %dx%d (x%.2f)"
        % (i, len(CLIPS), c["src"], w, h, tw, th, f))


def prep_video(i, c):
    """视频镜的 prep：把声明的那一段**归一成成片尺寸的 vidNN.mp4**，
    顺带出一张 imgNN.png 供缺图检查和封面用。

    和静帧镜的 prep 是同一件事 —— 都是"把素材整理成流水线能直接用的形状"。
    区别只在产物：静帧镜出一张 PREP 尺寸的大图留给 zoompan 取景，
    视频镜没有取景可言，直接出成片尺寸。

    ---- 三条实现上的取舍 ----
    1. **-ss 放在 -i 前面**（输入定位）。放后面是逐帧解到入点，20 分钟的片子
       每一镜都要重解一遍，十一镜就是十一次全解。放前面靠关键帧跳，
       代价是入点可能差几帧 —— 对档案影像完全可以接受。
    2. **fps 在这里就落到 FPS**。29.97 和 30 不统一，pass_c 的 concat
       会得到一段时间戳乱掉的片子，而且它**不报错**。
       这里用的是 fps 滤镜的丢/复帧，不是插值 —— 不要改成 minterpolate，
       默片本来就抖，插出来的中间帧会把抖动抹成糊的。
    3. **调色和 tweak 走和静帧镜同一套**，否则视频镜和静帧镜在成片里
       是两个色调，一眼看得出来。
    """
    src = os.path.join(SRC, c["video"])
    if not os.path.exists(src):
        print("   跳过(缺视频): " + c["video"]); return
    a, b, seg = video_seg(i)
    if seg <= 0:
        print("   跳过(镜%d 的 ss/to 没写或写反了): %s" % (i, c["video"])); return
    parts = [video_fit_vf()]
    if str(GRADE).strip():
        parts.append(GRADE)
    if c.get("tweak"):
        parts.append(c["tweak"])
    parts += ["fps=%d" % FPS, "setsar=1", "format=yuv420p"]
    vf = ",".join(parts)
    out = "vid%02d.mp4" % i
    run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % a, "-t", "%.3f" % seg,
         "-i", src, "-vf", vf, "-an", "-c:v", "libx264", "-crf", "12",
         "-preset", "medium", "-pix_fmt", "yuv420p", out],
        "prep %d/%d  %s  %s~%s (%.1fs)  %s"
        % (i, len(CLIPS), c["video"], c.get("ss"), c.get("to"), seg,
           "黑边" if VIDEO_FIT == "pillarbox" else "裁切"))
    # 出一张静帧：probe/trace/封面 都还按 imgNN.png 找素材，缺了会一路 KeyError。
    run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % a, "-i", src,
         "-vf", vf, "-frames:v", "1", "img%02d.png" % i],
        "     └ 代表帧 img%02d.png" % i)


def probe():
    """亮度网格（横版 16 列 x 9 行，竖版 9 列 x 16 行）。能发现两类错误：
    落幅摇进无特征区域；烧录字幕压在读不出的底上。
    **但它量的是整张图，而镜头只经过其中一段，所以报警经常是误报** —— 跑完一定要跑 trace。"""
    gc, gr = (16, 9) if LAYOUT == "h" else (9, 16)
    print("\n=== 亮度网格 (0-255, %d 列 x %d 行) ===" % (gc, gr))
    for i in range(1, len(CLIPS) + 1):
        f = "img%02d.png" % i
        if not os.path.exists(f):
            print("%s  (未生成)" % f); continue
        p = subprocess.run(["ffmpeg", "-v", "error", "-i", f, "-vf",
                            "scale=%d:%d:flags=area,format=gray" % (gc, gr),
                            "-f", "rawvideo", "-"], capture_output=True)
        raw = p.stdout
        if len(raw) != gc * gr:
            print("%s  (读不出)" % f); continue
        print("\n%s  %s" % (f, clip_key(CLIPS[i - 1])))
        for r in range(gr):
            print("   " + " ".join("%3d" % raw[r * gc + c] for c in range(gc)))


def vig_factor(x0, x1, y0, y1):
    """pass_a 里的 vignette 对画面上某矩形的平均衰减系数(1.0 = 不衰减)。

    **少了这个，trace 和 measure 会系统性对不上**，而"对不上 = 运镜没走在你以为的
    位置上"是全流水线唯一一处能自检运镜的判据 —— 一个长期报假警的检查等于没有检查。
    做法：拿一张纯灰跑一遍 VIGNETTE，用画心的值归一，改参数自动跟着变。"""
    if not VIGNETTE:
        return 1.0
    if "map" not in _VIG_CACHE:
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi",
             "-i", "color=c=0xC8C8C8:s=%dx%d" % (W, H),
             "-vf", VIGNETTE + ",format=gray", "-frames:v", "1",
             "-f", "rawvideo", "-"], capture_output=True).stdout
        _VIG_CACHE["map"] = raw if len(raw) == W * H else None
    raw = _VIG_CACHE["map"]
    if not raw:
        return 1.0
    ctr = raw[(H // 2) * W + W // 2]
    if not ctr:
        return 1.0
    step = 8
    v = [raw[y * W + x] for y in range(y0, y1, step) for x in range(x0, x1, step)]
    return (sum(v) / len(v)) / ctr


def scrim_on():
    """这一支到底要不要那层底部压暗。**唯一的判据，别在别处再判一次。**

    scrim 只为**烧录**正文字幕服务 —— 它的活是把字幕带底下的画面压暗，
    让近白的字在亮底上仍然读得出来。`SUB_MODE="srt"` 时字幕由播放器渲染
    （自带描边/底），这层压暗**保护不了任何东西**，只是白白把画面下三分之一
    压暗 SCRIM_ALPHA。标题字卡和尾板也不归它管（都在画面中上部，scrim 从
    SCRIM_Y0 才起步），所以"留着给尾板垫底"也不成立。横版一律外挂，所以横版恒不叠。

    原来靠 `SCRIM_ALPHA = 0.0` 这个配置值来关。《瓶子裡的金子》(2026-09-21) 证明
    那不够：外挂字幕 + SCRIM_ALPHA=0.30，成片暗部（<16）面积 22.7%，而 prep 之后
    的素材只有 3.3% —— 全套检查一条都没报。**判据要写进脚本，不能留成纪律。**
    """
    return SCRIM_ALPHA > 0 and SUB_MODE == "burn"


def scrim_factor(x0, x1, y0, y1):
    """pass_c 里那层 scrim 对画面上某矩形的平均透过率（1.0 = 没压）。

    和 vig_factor 是同一个道理，而且是同一个坑的第二只脚：**trace 必须和
    pass_a/pass_c 建模同一条流水线**。只补了 vignette 不补 scrim，
    trace 会系统性地比 measure 亮 —— 而"两者对不上 = 运镜没走对"
    是全流水线唯一一处能自检运镜的判据，一旦有系统性偏差就等于废了。

    做法同样是拿一张纯灰跑一遍真正的合成，按画心归一，改参数自动跟着变。
    """
    if not scrim_on():
        return 1.0
    if "map" not in _SCRIM_CACHE:
        if not os.path.exists("scrim.png"):
            make_scrim()
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi",
             "-i", "color=c=0xC8C8C8:s=%dx%d" % (W, H), "-i", "scrim.png",
             "-filter_complex", "[0:v][1:v]overlay=0:0:shortest=1,format=gray",
             "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True).stdout
        _SCRIM_CACHE["map"] = raw if len(raw) == W * H else None
    raw = _SCRIM_CACHE["map"]
    if not raw:
        return 1.0
    step = 8
    v = [raw[y * W + x] for y in range(y0, y1, step) for x in range(x0, x1, step)]
    return (sum(v) / len(v)) / 200.0          # 0xC8 = 200


def fade_factor(t, total):
    """pass_b 末尾那两道全局淡场在时刻 t 的亮度系数（1.0 = 没压）。

    **同一个坑的第三只脚。** vig_factor 补 pass_a 的暗角、scrim_factor 补 pass_c
    的 scrim，而淡场是 **pass_b** 加的 —— 而 measure 读的正是 pass_b 的产物
    master.mp4，不建模就在首尾两镜上系统性对不上。

    这一段代码上面那条注释里记的「镜 1 起幅量到 2/3/2 几乎全黑，而预测 31/51/31」
    就是这件事的另一种表现：那次是 d=0 退回 25 帧的 bug，修的是黑场本身；
    **正常的淡场同样要建模**，否则首尾两镜永远对不上。

    竖版 (`make_story_v.py`) 上实测过：150 个比对点里超差 3 个（最大 −24），
    补上之后 **0 个**，最大 4 级。ffmpeg 的 `fade` 默认线性，所以这里也线性。

    ⚠️ 横版这一路**还没有在真片子上验过**（改动时手上只有竖版工程）。
    下一支横版跑完 measure 之后，看首尾两镜的偏差是不是也收进 5 级以内。
    """
    f = 1.0
    if FADE_IN > 0 and t < FADE_IN:
        f = min(f, max(0.0, t) / FADE_IN)
    if FADE_OUT > 0 and t > total - FADE_OUT:
        f = min(f, max(0.0, total - t) / FADE_OUT)
    return max(0.0, min(1.0, f))


def _fade_selftest():
    """回归自测：写反或者退化成常数 1.0，这里立刻看得见。"""
    if FADE_IN <= 0 and FADE_OUT <= 0:
        return "回归自测: 本段没有淡场（中间段就该是这样），fade_factor 恒 1.0 —— 对"
    T = 100.0
    a = fade_factor(0.0, T)
    b = fade_factor(FADE_IN, T) if FADE_IN > 0 else 1.0
    c = fade_factor(T, T)
    ok = ((a <= 0.01) if FADE_IN > 0 else (a == 1.0)) \
        and abs(b - 1.0) < 1e-6 \
        and ((c <= 0.01) if FADE_OUT > 0 else (c == 1.0))
    return ("回归自测: 淡场建模 段头 %.2f / 淡入结束 %.2f / 段尾 %.2f —— %s"
            % (a, b, c, "对" if ok else "**反了或没生效**"))


def probe_times(n, durs):
    """镜 n 里可以取样的三个**镜内局部时刻**（起/中/止）。trace 和 measure 必须
    共用这一个函数 —— 各写一份就一定会漂。

    **必须躲开转场。** 每一镜渲出来那段片子的头尾各骑着半个转场（xfade 骑在内容
    边界正中），在 master.mp4 上那几帧是**两镜的混合帧**，而 trace 建模的是单镜的
    zoompan。第一版 measure 直接在 0.05s 和 dur−0.05s 上取样，于是 68 处超差，
    而**中间那一列严丝合缝** —— 静帧镜（画面本来不动）也照样报 ±72，
    那就只能是转场混合，不可能是运镜。

    干净区 = [进来的转场, dur − 出去的转场]，两端再各让开 PROBE_EDGE。
    """
    i = n - 1
    lo = xf(i - 1) if i > 0 else 0.0
    hi = durs[i] - (xf(i) if i < len(SHOTS) - 1 else 0.0)
    # **片头/片尾的黑场淡入淡出也要躲开**，理由和转场完全一样：它们加在 pass_b 上，
    # 而 trace 不建模。第一版只躲了转场，于是镜 1 的起幅量到 0/2/0（还在淡入的黑里），
    # 报 −45 级看着像运镜错了。淡场只压在第一镜的头和最后一镜的尾上。
    if i == 0:
        lo = max(lo, FADE_IN)
    if i == len(SHOTS) - 1 and FADE_OUT > 0:
        hi = min(hi, durs[i] - FADE_OUT)
    lo, hi = lo + PROBE_EDGE, hi - PROBE_EDGE
    if hi <= lo:                      # 极短的镜头：退回镜心
        lo = hi = durs[i] / 2.0
    return (lo, (lo + hi) / 2.0, hi)


def trace():
    """量镜头**真正经过的区域** —— 出图阶段就能判一张图能不能用，缺图会跳过。

    zoompan 的取景窗宽高各 1/z、窗心在 (fx,fy) 且被 clip 在图内，于是
        src = (f - 1/(2z)) + (out/边长) * (1/z)
    打扫过范围要取**并集**，不能打"起帧框顶→止帧框底"：上摇时落幅的框底在起幅框底
    之上，那样打出来会把行程严重低估。"""
    lines, durs, total, _ = timeline()
    starts = clip_starts()          # 镜内局部时刻要按**渲出来那段片子**的起点算
    dark = POLARITY == "dark_on_light"
    ink = 40 if dark else 242
    # 灰度网格跟着成片方向走：横版宽 > 高，竖版反过来。写反了 stat 会把框算到画外去，
    # 而它照样打印得很正常。
    GW, GH = (1288, 724) if LAYOUT == "h" else (724, 1288)
    cache = {}

    def gray(i):
        if i in cache:
            return cache[i]
        f = "img%02d.png" % i
        if not os.path.exists(f):
            f = os.path.join(SRC, clip_key(CLIPS[i - 1]))
            if not os.path.exists(f):
                cache[i] = None; return None
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", f, "-vf",
                              "scale=%d:%d:flags=area,format=gray" % (GW, GH),
                              "-f", "rawvideo", "-"], capture_output=True).stdout
        cache[i] = raw if len(raw) == GW * GH else None
        return cache[i]

    def box(n, tl, x0o, x1o, y0o, y1o):
        s = SHOTS[n - 1]
        p = min(1.0, max(0.0, tl / durs[n - 1]))
        z = s["z"][0] + (s["z"][1] - s["z"][0]) * p
        half = 1 / (2 * z)
        fx = min(max(s["f0"][0] + (s["f1"][0] - s["f0"][0]) * p, half), 1 - half)
        fy = min(max(s["f0"][1] + (s["f1"][1] - s["f0"][1]) * p, half), 1 - half)
        span = 1.0 / z
        return (fx - half + x0o / W * span, fx - half + x1o / W * span,
                fy - half + y0o / H * span, fy - half + y1o / H * span)

    def stat(raw, b, vig):
        x0, x1 = int(b[0] * GW), max(int(b[0] * GW) + 1, int(b[1] * GW))
        y0, y1 = int(b[2] * GH), max(int(b[2] * GH) + 1, int(b[3] * GH))
        x0, x1, y0, y1 = max(0, x0), min(GW, x1), max(0, y0), min(GH, y1)
        v = sorted(raw[y * GW + x] * vig for y in range(y0, y1) for x in range(x0, x1))
        # (均值, 离字色最近的那一端的 1% 分位)。取样框对账只用均值
        return sum(v) / len(v), v[int(len(v) * 0.01)] if dark else v[int(len(v) * 0.99)]

    if SUB_MODE == "burn":
        _trace_subs(lines, total, starts, gray, box, stat, dark, ink)
    else:
        _trace_probes(durs, total, starts, gray, box, stat)
    _trace_flat(durs, gray, box, GW, GH)


def _trace_subs(lines, total, starts, gray, box, stat, dark, ink):
    """烧录字幕：量每条字幕**实际扫过**的那块底（起/中/止），判离字色够不够 50 级。
    跑完拿它和 measure 逐条对：差 5 级以内才算运镜落点对。"""
    print("\n=== 字幕实走轨迹（起/中/止，均值/1%%分位；判据：离字色 %d 至少 50 级）===" % ink)
    print("    （已建模 vignette + scrim + 首尾淡场；跑完拿它和 measure 逐条对，"
          "差 5 级以内才算运镜对）")
    print("    " + _fade_selftest())
    worst = []
    for st, en, txt, n, _, _ in lines:
        raw = gray(n)
        if raw is None:
            print("  %-24s 镜%-3d (缺图)" % (txt, n)); continue
        x0, x1, y0, y1 = sub_box(txt)
        base = vig_factor(x0, x1, y0, y1) * scrim_factor(x0, x1, y0, y1)
        out, ys = [], []
        for t in (st + 0.2, (st + en) / 2, max(st + 0.3, en - 0.2)):
            b = box(n, t - starts[n - 1], x0, x1, y0, y1)
            # 淡场按**这一刻**算，不能像 vignette 那样一镜一个常数
            out.append(stat(raw, b, base * fade_factor(t, total))); ys.append((b[2], b[3]))
        w = min(o[1] for o in out) if dark else max(o[1] for o in out)
        worst.append((w, txt, n))
        flag = "" if abs(w - ink) >= 50 else "   << 不够，加 scrim 或换图"
        print("  %-24s 镜%-3d y %.3f~%.3f  " % ("".join(sub_lines(txt))[:12], n,
                                                min(a for a, _ in ys), max(b for _, b in ys))
              + "  ".join("%3.0f/%3.0f" % o for o in out) + flag)
    if worst:
        m, who, n = min(worst) if dark else max(worst)
        print("\n  最差处的底 %.0f，出现在『%s』(镜 %d)，离字色 %d 差 %.0f 级 —— %s"
              % (m, "".join(sub_lines(who))[:12], n, ink, abs(m - ink),
                 "够用" if abs(m - ink) >= 50 else "不够"))


def _trace_probes(durs, total, starts, gray, box, stat):
    """外挂字幕：字幕框没有了，但「trace 预测 vs measure 实测」这个运镜自检不能跟着丢，
    所以量 PROBE_BOXES 那三块固定取样框，预测值存进 trace_pred.json 给 measure 对账。"""
    print("\n=== 取样框预测亮度（三框 × 起/中/止）===")
    print("    这一节的用途**只有一个**：给 measure 对账，自检运镜有没有走在预期位置。")
    print("    字幕外挂之后不再有「字幕底」要判，但那个自检不能跟着丢。")
    print("    已建模 vignette + scrim + 首尾淡场。跑完 a+b 之后跑 measure，"
          "逐条差 %.0f 级以内才算对。" % PROBE_TOL)
    print("    " + _fade_selftest())
    pred = {}
    for n in range(1, len(SHOTS) + 1):
        raw = gray(n)
        if raw is None:
            print("  镜%-3d (缺图)" % n); continue
        cells = []
        for name, rx0, rx1, ry0, ry1 in PROBE_BOXES:
            x0, x1 = int(rx0 * W), int(rx1 * W)
            y0, y1 = int(ry0 * H), int(ry1 * H)
            base = vig_factor(x0, x1, y0, y1) * scrim_factor(x0, x1, y0, y1)
            vals = []
            for tl in probe_times(n, durs):
                b = box(n, tl, x0, x1, y0, y1)
                # 淡场按**这一刻在整段上的绝对时刻**算（镜内局部时刻 + 这一镜的起点），
                # 不能像 vignette 那样一镜一个常数
                vals.append(stat(raw, b, base * fade_factor(starts[n - 1] + tl, total))[0])
            pred[(n, name)] = vals
            cells.append("%s %3.0f/%3.0f/%3.0f" % (name, vals[0], vals[1], vals[2]))
        print("  镜%-3d %-14s %s" % (n, clip_key(CLIPS[n - 1])[:13], "   ".join(cells)))
    try:
        json.dump({"%d|%s" % k: v for k, v in pred.items()},
                  open("trace_pred.json", "w", encoding="utf-8"))
        print("\n  预测值存进 trace_pred.json —— measure 会读它对账。")
    except OSError:
        pass


def _trace_flat(durs, gray, box, GW, GH):
    print("\n=== 落幅平坦度（只量镜头真正停住的那一帧）===")
    # 横版 9 行 × 16 列，竖版 16 行 × 9 列。数的是**每一行内部的横向变化**，
    # 所以行列搞反了判据就变成另一回事了，而它照样会打印得很正常。
    # 报警线按行数折：9 行里 3 行平 ≈ 16 行里 5 行平（两份手抄时代各自定的，比例一致）。
    NR, NC = (9, 16) if LAYOUT == "h" else (16, 9)
    FLAT_MAX = 3 if LAYOUT == "h" else 5
    for n in range(1, len(SHOTS) + 1):
        raw = gray(n)
        if raw is None:
            print("  镜%-3d (缺图)" % n); continue
        b = box(n, durs[n - 1], 0, W, 0, H)
        gx0, gx1 = int(b[0] * GW), int(b[1] * GW)
        gy0, gy1 = int(b[2] * GH), int(b[3] * GH)
        cells, flat = [], 0
        for r in range(NR):
            row = []
            for c in range(NC):
                sx0 = gx0 + (gx1 - gx0) * c // NC
                sx1 = max(sx0 + 1, gx0 + (gx1 - gx0) * (c + 1) // NC)
                sy0 = gy0 + (gy1 - gy0) * r // NR
                sy1 = max(sy0 + 1, gy0 + (gy1 - gy0) * (r + 1) // NR)
                v = [raw[y * GW + x] for y in range(sy0, min(GH, sy1))
                     for x in range(sx0, min(GW, sx1))]
                row.append(sum(v) / len(v))
            cells.append(row)
            if max(row) - min(row) < 12:
                flat += 1
        allv = [v for row in cells for v in row]
        rng = max(allv) - min(allv)
        note = ""
        if is_static(n):
            # 静帧镜的这两个数换了含义：平坦行本来是在问"落幅停在这里会不会像静止"，
            # 而静帧镜本来就静止，那个问题不成立。剩下有意义的只有"这张停这么久
            # 够不够看"，所以只在整帧极差很低时提示，且只是提示。
            note = ("  << 静帧，整帧极差只有 %.0f，要停 %.1fs，会很空"
                    % (rng, durs[n - 1])) if rng < 25 else "  (静帧，平坦行不适用)"
        elif flat >= FLAT_MAX:
            note = "  << %d 行几乎无明暗变化，这一镜会像静止" % flat
        elif rng < 25:
            note = "  << 整帧极差只有 %.0f，运镜会看不出来" % rng
        print("  镜%-3d %-16s 整帧极差 %3.0f  平坦行 %2d/%d%s"
              % (n, clip_key(CLIPS[n - 1])[:16], rng, flat, NR, note))
    print("\n  平坦行对暗调图**结构性地误报**（大片夜空、暗海面本来就是平的）。")
    print("  真正要紧的是「这一镜从头走到尾画面变了多少」—— 渲完跑 motion 复核，")
    print("  判据均差 >= %.1f 级。别拿 trace 的平坦行去换图。" % MOTION_MIN)


# ================= 渲染 =================
def static_vf(s):
    """静帧镜的滤镜链：按 z/f0 裁一个固定取景窗，缩到成片尺寸，不动。

    取景算法和 zoompan 一致（窗宽高各 1/z、窗心在 f、clip 在图内），否则 trace
    反查的位置会和成片对不上 —— 那是全流水线唯一能自检取景的地方。
    实测过：同一个 z/f 两条路径渲出来做位移扫描，最小帧差落在 dx=0、dy 在 0~1 之间，
    即横向完全对齐、纵向差约半个像素（两条路在 PREP 和 UP 两种尺度上各自取整）。
    trace 用的是 724x1288 网格，一格比这粗五倍，不影响判断。

    不走 zoompan 还省掉 UP 那道 3 倍上采样（静帧不需要），且逐帧完全相同，
    x264 会压成一串 P 帧。
    """
    z, (fx_, fy_) = s["z"][0], s["f0"]
    crop = ("crop=w='iw/%.6f':h='ih/%.6f':"
            "x='clip(%.6f*iw-out_w/2,0,iw-out_w)':"
            "y='clip(%.6f*ih-out_h/2,0,ih-out_h)'" % (z, z, fx_, fy_))
    return (crop + ",scale=%d:%d:flags=lanczos," % (W, H)
            + (VIGNETTE + "," if VIGNETTE else "") + "setsar=1,format=yuv420p")


def shot_cmd(i, dur):
    """第 i 镜的 pass_a 命令（不含 -stats）。返回 (argv, 说明, 警告或 None)。
    pass_a 用它渲，pass_b 用它算印记对账 —— 同一份，不会漂。"""
    s = SHOTS[i - 1]
    if is_video(i):
        return video_shot_cmd(i, dur)
    if is_static(i):
        vf, how = static_vf(s), "静帧"
    else:
        d = max(1, int(round(dur * FPS)) - 1)
        z0, z1 = s["z"]; (x0, y0), (x1, y1) = s["f0"], s["f1"]
        ze = "%.6f+(%.6f)*on/%d" % (z0, z1 - z0, d)
        xe = ("max(0,min(iw-iw/zoom,(%.6f+(%.6f)*on/%d)*iw-(iw/zoom)/2))"
              % (x0, x1 - x0, d))
        ye = ("max(0,min(ih-ih/zoom,(%.6f+(%.6f)*on/%d)*ih-(ih/zoom)/2))"
              % (y0, y1 - y0, d))
        vf = ("scale=%d:%d:flags=lanczos," % UP
              + "zoompan=z='%s':x='%s':y='%s':d=1:s=%dx%d:fps=%d,"
                % (ze, xe, ye, W, H, FPS)
              + (VIGNETTE + "," if VIGNETTE else "") + "setsar=1,format=yuv420p")
        how = "运镜"
    return (["ffmpeg", "-y", "-v", "error", "-loop", "1",
             "-framerate", str(FPS), "-t", "%.3f" % dur,
             "-i", "img%02d.png" % i, "-vf", vf, "-c:v", "libx264", "-crf", "12",
             "-preset", "medium", "-pix_fmt", "yuv420p", shot_path(i)],
            "镜头 %d/%d  %.1fs  %s" % (i, len(SHOTS), dur, how), None)


def video_shot_cmd(i, dur):
    """视频镜的 pass_a 命令：从 vidNN.mp4 的头上取 dur 秒。

    `dur` 是旁白算出来的，和素材段本来就不一样长 —— 这条流水线里
    **时间永远由旁白说了算**，素材去迁就它，不是反过来。

    段比 dur 短时**冻结最后一帧补足**，并且报出来。不补的话 concat 会
    得到一段比时间轴短的片子，后面所有镜头整体前移，而且没有任何报错 ——
    这正是"不会报警的错"，所以宁可补上再喊一声。
    """
    src = "vid%02d.mp4" % i
    info = probe_video(src) if os.path.exists(src) else None   # 缺了由 stale_prep 拦
    have = info[2] if info else 0.0
    vf = "setsar=1,format=yuv420p"
    note, warn = "视频", None
    if have + 1e-3 < dur:
        vf = ("tpad=stop_mode=clone:stop_duration=%.3f," % (dur - have + 0.5)) + vf
        note = "视频(素材短 %.2fs，冻结末帧补足)" % (dur - have)
        warn = ("   !! 镜%d 的素材段只有 %.2fs，旁白要 %.2fs —— 已冻结末帧补足。"
                "要么把 to 往后放，要么把这一镜的旁白挪一句走" % (i, have, dur))
    return (["ffmpeg", "-y", "-v", "error", "-i", src,
             "-t", "%.3f" % dur, "-vf", vf, "-an",
             "-c:v", "libx264", "-crf", "12", "-preset", "medium",
             "-pix_fmt", "yuv420p", "-r", str(FPS), shot_path(i)],
            "镜头 %d/%d  %.1fs  %s" % (i, len(SHOTS), dur, note), warn)


def motion():
    """量每一镜**渲出来**的首尾帧差 —— 运镜到底看不看得出来。

    `trace` 的落幅平坦度是出图阶段的筛子，它数的是"有几行几乎没有明暗变化"。
    对暗调实拍它**天生爱误报**：大片夜空、暗地面本来就是平的，
    整帧极差 147 的一张好图照样能报 8/16 行平坦。

    真正要紧的不是落幅那一帧长什么样，而是**这一镜从头走到尾画面变了多少**。
    那个只能在 shots/ 上量 —— 和 measure 之于 probe 是同一个关系：
    筛子在源头上估，判据在流水线的真实输出上量。

    判据：首尾帧的平均绝对差 < MOTION_MIN 就是"肉眼看不出在动"
    （亮度的可觉察差约 2~3 级，取 4 作下限）。

    ---- 静帧镜是**反过来**判的 ----
    标了 static 的镜子首尾帧差必须 <= MOTION_STATIC_MAX。"静帧镜其实在动"
    和"运镜镜其实不动"一样是错。只判运镜那一边的话，静帧片跑 motion 会全绿，
    那又是一个不会报警的检查。
    """
    if not os.path.isdir("shots"):
        sys.exit("!!! 还没有 shots/，先跑 a")
    durs = timeline()[1]
    GW, GH = 96, 171
    # 视频镜两个方向都不判：它"动不动"由素材决定，不是配置错误。
    # 末段那种几乎全是化学斑的档案影像首尾帧差可能很小 —— 那是内容，不是缺陷。

    def frame(f, t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "%.3f" % t, "-i", f,
                              "-frames:v", "1", "-vf",
                              "scale=%d:%d:flags=area,format=gray" % (GW, GH),
                              "-f", "rawvideo", "-"], capture_output=True).stdout
        return raw if len(raw) == GW * GH else None

    print("\n=== 运动实测（渲出来的首尾帧差）===")
    print("    运镜镜判据 均差 >= %.1f 级；静帧镜判据 均差 <= %.1f 级"
          % (MOTION_MIN, MOTION_STATIC_MAX))
    bad, drift, skipped, n_static, n_video = [], [], [], 0, 0
    for i in range(1, len(SHOTS) + 1):
        f = "shots/shot%02d.mp4" % i
        if not os.path.exists(f):
            print("  镜%-3d (未渲染)" % i); skipped.append(i); continue
        a, b = frame(f, 0.05), frame(f, max(0.1, durs[i - 1] - 0.1))
        if a is None or b is None:
            # 读不出多半是这一镜还在写（ffmpeg 还没收尾，moov atom 没落盘）。
            # **不能当成通过。** 第一版跳过之后照样打印"全部都看得出来"，
            # 又造出一个不会报警的检查 —— 这一条是被自己坑了一次之后加的。
            print("  镜%-3d %-16s (读不出帧，可能还在渲)" % (i, clip_key(CLIPS[i - 1])[:16]))
            skipped.append(i); continue
        d = sorted(abs(a[k] - b[k]) for k in range(GW * GH))
        mean = sum(d) / len(d)
        flag, how = "", ("视频" if is_video(i) else "静帧" if is_static(i) else "运镜")
        if is_video(i):
            # 视频镜两个方向都不判：它动不动由素材决定，不是配置错误。
            # 末段那种几乎全是化学斑的档案影像首尾帧差可能极小 —— 那是内容，不是缺陷。
            n_video += 1
        elif is_static(i):
            n_static += 1
            if mean > MOTION_STATIC_MAX:
                flag = "  << 标了 static 却在动，检查 z/f 的起止和 pass_a 走了哪条路"
                drift.append(i)
        elif ENDCARD and i == len(SHOTS):
            flag = "  (尾板，本来就该几乎静止 —— 不适用)"
        elif mean < MOTION_MIN:
            flag = "  << 肉眼看不出在动，加大 z 跨度或换一张有结构的图"
            bad.append(i)
        print("  镜%-3d %-16s %s 均差 %5.1f  中位 %3d  p90 %3d  最大 %3d%s"
              % (i, clip_key(CLIPS[i - 1])[:16], how, mean, d[len(d) // 2],
                 d[int(len(d) * 0.9)], d[-1], flag))
    if bad:
        print("\n  %d 镜运镜看不出来: %s" % (len(bad), ", ".join(str(i) for i in bad)))
    if drift:
        print("\n  %d 镜标了静帧却在动: %s" % (len(drift), ", ".join(str(i) for i in drift)))
    if skipped:
        print("\n  !! %d 镜没量到: %s —— **不算通过**，渲完再跑一次"
              % (len(skipped), ", ".join(str(i) for i in skipped)))
    if not bad and not drift and not skipped:
        print("\n  %d 镜全部对得上（运镜 %d 镜看得出动，静帧 %d 镜真的没动，"
              "视频 %d 镜不判 —— 动不动由素材决定）。"
              % (len(SHOTS), len(SHOTS) - n_static - n_video, n_static, n_video))
    return not bad and not drift and not skipped


def native_factor(w, h):
    """源图的有效边长 / 文件边长。SRC_NATIVE 没写就是 1.0。"""
    if not SRC_NATIVE:
        return 1.0
    return min(SRC_NATIVE[0] / float(w), SRC_NATIVE[1] / float(h))


def img_dims(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return tuple(int(x) for x in r.stdout.strip().split(","))
    except ValueError:
        return None


def check_resolution():
    """裁后短边够不够 —— **按有效分辨率算，不按文件尺寸算**。

    规则：裁成成片比例之后的**短边**，按这一镜最紧的取景折算成 pp（源像素/输出像素）。
    pp 不够要么运镜做不动，要么成片发软。941x1672 那次是下限的 0.65 倍，
    而文件上写的是 2896x5152 —— 只查文件尺寸的检查对它一声不吭。

    ---- 静帧镜的门槛不一样，而且低得多 ----
    1.5 倍是**为运镜定的**：余量是给行程用的。静帧镜没有行程，取景窗从头到尾
    就那一个，只需要 eff/z >= W（窗里的源像素不少于输出像素）。低于 1 是在放大，
    1.0~1.25 之间能用但没余量。

    这不是放松检查，是这一镜本来只需要这么多 —— 而它有实际后果：档案馆的老照片、
    博物馆开放数据里的画作很多卡在 1.0~1.5 之间，按运镜那条线一刀切会全判死，
    而它们做静帧完全够用。讲述片尤其吃这个：历史题材的真实图像常常只有这个分辨率。
    """
    bad, rows, warn_pp, vrows, prows = [], [], [], [], []
    # **贴纸版式和 PREP 的组合会静默出错。** prep_plate 出的是成片尺寸的图，
    # 而 pass_a 的 static_vf 会把 PREP 尺寸缩到成片尺寸 —— PREP 还是 3840x2160
    # 时，那张已经是 1920x1080 的台纸会被再缩一半，成片上图只有半幅大而四周全是台纸。
    # 渲得出来、不报错、退出码 0，只有真看画面才发现。
    if any(c.get("fit") == "plate" for c in CLIPS) and tuple(PREP) != (W, H):
        bad.append("有贴纸版式的镜，但 PREP=%s 不等于成片尺寸 %dx%d —— "
                   "pass_a 会把台纸再缩一次，成片上图只有 %.0f%% 大小。"
                   "用贴纸版式就要把 PREP 设成 (%d, %d)"
                   % (tuple(PREP), W, H, W / float(PREP[0]) * 100, W, H))
    for i, c in enumerate(CLIPS, 1):
        if c.get("video"):
            # **视频镜不走 pp 判据。** 档案影像天生就低分辨率 —— 640x480 铺到
            # 1080 高是 2.25 倍放大，按 pp<1.0 那条线一刀切会把整支片子判死，
            # 而"糊"恰恰是这类素材的内容本身。所以只报事实，不拦。
            vp = os.path.join(SRC, c["video"])
            info = probe_video(vp) if os.path.exists(vp) else None
            if info:
                vw, vh, vdur, vfps = info
                if VIDEO_FIT == "crop":
                    up = max(W / float(vw), H / float(vh))
                    keep = min(1.0, (vw / float(vh)) / (W / float(H)))
                else:
                    up = min(W / float(vw), H / float(vh))
                    keep = 1.0
                vrows.append((i, c["video"], vw, vh, vfps, vdur, up, keep))
            continue
        # "最紧取景"要用**这一镜自己的** z，不是全片的 z 最大值。用全局值时，
        # 各镜 z 差不多还看不出来；一旦跨度大（比如 1.02~2.15），低 z 的镜头会被
        # 算成远低于实际的源像素比，让人去换一张本来完全没问题的图。
        st = is_static(i) if i - 1 < len(SHOTS) else False
        zmax = ((SHOTS[i - 1]["z"][0] if st else max(SHOTS[i - 1]["z"]))
                if i - 1 < len(SHOTS) else 1.0)
        p = os.path.join(SRC, c["src"])
        if not os.path.exists(p):
            continue
        d = img_dims(p)
        if not d:
            continue
        w, h = d
        if c.get("fit") == "plate":
            # 贴纸镜不裁、不放大，pp 按定义就是 1.00。要看的是**另一件事**：
            # 这张图在画框里占多大 —— 占得太小就成了一张邮票贴在大黑板上。
            tw, th, sf = plate_box(w, h)
            # **判据用 max(占宽, 占高)，不用面积比。** 面积比对竖构图是稳定的误报：
            # 一张 480x1180 的海报贴上去正好把画框的高占满（该有的样子），
            # 面积却只有 23% —— 按面积判会说它"像一张邮票贴在黑板上"，
            # 而真正的邮票（两个方向都小）反而混在同一档里看不出来。
            prows.append((i, c["src"], w, h, tw, th, sf,
                          max(tw / float(W), th / float(H))))
            if not (i - 1 < len(SHOTS) and is_static(i)):
                bad.append("镜 %d 用了贴纸版式却不是静帧镜 —— 台纸不动，"
                           "运镜在它上面没有意义（写 motion=\"static\"）" % i)
            continue
        f = native_factor(w, h)
        # 裁成成片比例之后的**短边**。竖版模板这里直接用了裁后宽度，因为竖版的宽就是短边；
        # 横版反过来（宽是长边），照抄会拿长边去比 OUT_SHORT，pp 被虚报 W/H = 1.78 倍 ——
        # 于是一张刚够用的 1920x1080 被算成 pp 1.78，检查全部放行而一声不吭。
        crop_w = min(w, h * W / float(H))
        crop_h = crop_w * H / float(W)
        cw = min(crop_w, crop_h) / c["zoom"]
        eff = cw * f
        pp = eff / zmax / float(OUT_SHORT)
        tgt = pp_target(i) if i - 1 < len(SHOTS) else PP_KENBURNS
        rows.append((i, c["src"], w, h, f, eff, pp, st, tgt))
        # 判据分两级：pp < 1.0 = **在放大**，是缺陷，拦；1.0~目标 = 顶层细节
        # 从 98% 掉到 92%，是取舍不是缺陷，提示。
        # 旧的 flat "eff >= 1.5 x W" 两头都不对：对缓推镜多要一倍多的像素，
        # 对大推镜反而放行。
        if pp < 1.0 - 1e-3:
            msg = ("%s 最紧取景只有 %.2f 源像素/输出像素（<1.0 = 在放大，成片会软）"
                   % (c["src"], pp))
            # 填了 PP_ACCEPT_REASON 就降级成提示 —— 但**必须写理由**，而且理由会打印出来。
            # 不给一个"静默放行"的开关：那样下一支照抄配置时就再也不知道这里做过妥协了。
            # PP_ACCEPTED 是竖版那边的做法（一个数字地板），合并后改成**理由之下的地板**：
            # 填了理由也不许低于它。只填数字不填理由不算承认 —— 数字是无痕的。
            floor = PP_ACCEPTED if PP_ACCEPTED is not None else 0.0
            if PP_ACCEPT_REASON.strip() and pp >= floor - 1e-3:
                warn_pp.append(msg)
            elif PP_ACCEPT_REASON.strip():
                bad.append(msg + " —— 已经低于 PP_ACCEPTED=%.2f 的地板，理由也不放行" % floor)
            elif PP_ACCEPTED is not None:
                bad.append(msg + " —— PP_ACCEPTED 填了但 PP_ACCEPT_REASON 空着："
                                 "只给数字不算承认，写上为什么接受")
            else:
                bad.append(msg)
    if prows:
        print("")
        print("=== 贴纸版式（%d 镜；不裁不放大，pp 恒为 1.00）===" % len(prows))
        print("   台纸 %s，看的是「图占画框多大」不是 pp" % PLATE_COLOR)
        for i, f_, w, h, tw, th, sf, frac in prows:
            flag = ""
            if frac < 0.60:
                flag = "  <- 两个方向都不满 60%，成片上会像一张邮票贴在黑板上"
            elif frac < 0.95:
                flag = "  <- 长边只到 %.0f%%" % (frac * 100)
            print("   镜%-3d %-22s %dx%d -> %dx%d  长边占画框 %.0f%%%s"
                  % (i, f_, w, h, tw, th, frac * 100, flag))
    if vrows:
        print("")
        print("=== 视频素材（%d 镜；**不参与 pp 判据**）===" % len(vrows))
        print("   填充方式：%s" % ("加黑边（保画幅完整）" if VIDEO_FIT == "pillarbox"
                                   else "裁切（填满画框）"))
        for i, f, vw, vh, vfps, vdur, up, keep in vrows:
            flag = ""
            if up > 3.0:
                flag = "  <- 放大超过 3 倍，成片上会很糊"
            elif keep < 0.999:
                flag = "  <- 裁掉了 %.0f%% 的画面" % ((1 - keep) * 100)
            print("   镜%-3d %-22s %dx%d  %.2ffps  源长 %.1fs  放大 %.2fx%s"
                  % (i, f, vw, vh, vfps, vdur, up, flag))
    if rows:
        print("")
        print("=== 素材分辨率（有效值）===")
        if SRC_NATIVE:
            print("   SRC_NATIVE=%dx%d —— 文件是放大上去的，下面按原生尺寸折算"
                  % SRC_NATIVE)
        elif IMG_SOURCE == "found":
            print("   IMG_SOURCE='found' —— 找来的图按文件尺寸算通常是对的，"
                  "但**网站给的常常是缩过的派生图**，能拿到原始档就拿原始档")
        else:
            print("   SRC_NATIVE 未设 —— 按文件尺寸算。"
                  "**如果图是放大上来的，这里的数字全是假的**")
        print("   判据：pp < 1.0 = 在放大（拦）；1.0 ~ 目标 = 顶层细节 92%~98%（提示）")
        if warn_pp:
            print("")
            print("   !! %d 镜低于 1.0，**已显式承认**（PP_ACCEPT_REASON 已填）：" % len(warn_pp))
            for ln in ("   " + PP_ACCEPT_REASON).split("。"):
                if ln.strip():
                    print("      " + ln.strip() + "。")
            print("      交付时这一条要照抄进制作说明的「哪几处是妥协的」。")
        for i, s, w, h, f, eff, pp, st, tgt in rows:
            if pp < 1.0 - 1e-3:
                flag = "  << 在放大"
            elif pp < tgt - 1e-3:
                flag = "  (够用，但低于目标 %.2f，顶层细节约 %.0f%%)" % (tgt, detail_pct(pp))
            else:
                flag = ""
            print("  %-2d %-20s 文件 %dx%d  x%.2f  裁后有效短边 %5.0f  %s"
                  "最紧取景 %.2f（目标 %.2f）%s"
                  % (i, s[:20], w, h, f, eff, "静帧 " if st else "运镜 ", pp, tgt, flag))
    return bad


def pixels():
    """从每张源图裁 1:1 原始像素贴片拼一张，**用眼睛看有没有真细节**。

    自动判不出来（见 SRC_NATIVE 处的注释），所以做成必须看一眼的东西 ——
    和 still 之于字幕是同一个套路。放大上来的图在 1:1 下是平滑的插值面，
    没有逐像素的纹理和颗粒。

    但记住：**目视只是辅助**。要确认，去看生成器吐出来的原始文件的尺寸。
    """
    N, cols = 360, 4
    cells, missing = [], []
    for i, c in enumerate(CLIPS, 1):
        if c.get("video"):        # 视频镜没有源图可以取原生像素样，不参与
            continue
        p = os.path.join(SRC, c["src"])
        if not os.path.exists(p):
            missing.append(c["src"]); continue
        d = img_dims(p)
        if not d:
            missing.append(c["src"]); continue
        w, h = d
        s = SHOTS[i - 1] if i <= len(SHOTS) else None
        fx, fy = s["f1"] if s else (0.5, 0.5)
        x = max(0, min(w - N, int(fx * w) - N // 2))
        y = max(0, min(h - N, int(fy * h) - N // 2))
        out = "_px%02d.png" % i
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", p,
                        "-vf", "crop=%d:%d:%d:%d" % (N, N, x, y),
                        "-frames:v", "1", out], capture_output=True)
        if os.path.exists(out):
            cells.append(out)
    if not cells:
        sys.exit("!!! 一张源图都没有")
    ins = []
    for f in cells:
        ins += ["-i", f]
    lay = []
    for k in range(len(cells)):
        cx = "0" if k % cols == 0 else "+".join("w%d" % j for j in range(k % cols))
        cy = "0" if k // cols == 0 else "+".join("h%d" % (j * cols) for j in range(k // cols))
        lay.append("%s_%s" % (cx, cy))
    fc = "".join("[%d:v]" % k for k in range(len(cells))) \
        + "xstack=inputs=%d:layout=%s:fill=black" % (len(cells), "|".join(lay))
    run(["ffmpeg", "-y", "-v", "error"] + ins
        + ["-filter_complex", fc, "-frames:v", "1", "_pixels.png"],
        "1:1 贴片联系表 %d 格" % len(cells))
    for f in cells:
        os.remove(f)
    print("")
    print("  _pixels.png —— 每格 %dx%d 原始像素，按 CLIPS 顺序，取各镜落幅焦点处。" % (N, N))
    print("  有逐像素的纹理和颗粒 = 真分辨率；平滑的插值面 = 放大上来的。")
    if missing:
        print("  缺图 %d 张：%s" % (len(missing), ", ".join(missing[:4])))


def pass_b():
    _, durs, total, _ = timeline()
    check_shots(durs)
    ins = []
    for i in range(1, len(SHOTS) + 1):
        ins += ["-i", "shots/shot%02d.mp4" % i]
    parts, cur, off = [], "[0:v]", 0.0
    for i in range(1, len(SHOTS)):
        off += durs[i - 1] - xf(i - 1)
        parts.append("%s[%d:v]xfade=transition=fade:duration=%.3f:offset=%.3f[x%d]"
                     % (cur, i, xf(i - 1), off, i)); cur = "[x%d]" % i
    # **d=0 的 fade 不是"不淡入"。** ffmpeg 的 fade 在 duration 为 0 时会退回
    # nb_frames 的默认值 **25 帧** —— 30fps 下就是 0.83s 的黑场。
    # 中间段 FADE_IN/FADE_OUT 都是 0，照写就等于给每一段的头尾各塞一段黑场，
    # 而这正是接缝规矩要防的东西。check_seg 也拦不住：它验的是**配置**里 FADE 为 0，
    # 不是输出里真的没有黑场。这一处是 measure 的运镜对账抓出来的
    # （镜 1 起幅量到 2/3/2 几乎全黑，而预测 31/51/31）。
    fades = []
    if FADE_IN > 0:
        fades.append("fade=t=in:st=0:d=%.2f:c=%s" % (FADE_IN, FADE_COLOR))
    if FADE_OUT > 0:
        fades.append("fade=t=out:st=%.3f:d=%.2f:c=%s" % (total - FADE_OUT, FADE_OUT, FADE_COLOR))
    parts.append("%s%s[v]" % (cur, ("" if not fades else ",".join(fades) + ",") + "null"))
    run(["ffmpeg", "-y", "-v", "error", "-stats"] + ins
        + ["-filter_complex", ";".join(parts), "-map", "[v]", "-c:v", "libx264",
           "-crf", "14", "-preset", "medium", "-pix_fmt", "yuv420p",
           "-r", str(FPS), "master.mp4"],
        "拼接 %d 镜  总长 %.1fs" % (len(SHOTS), total))


# ================= 音频 =================
def integrated_lufs(path):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af",
                        "loudnorm=print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        m = json.loads(p.stderr[p.stderr.rfind("{"):p.stderr.rfind("}") + 1])
        return float(m["input_i"])
    except (ValueError, KeyError):
        return None


def band_rms(path, pre=None):
    """某个频段的 RMS。**分频段一律用 RMS，不用 LUFS** —— K 加权会把低频衰掉，
    正是要避开的那个骗局；同一个陷阱在老录音上换个方向出现（高频没了，
    整体 LUFS 却可能正常）。"""
    af = (pre + ",") if pre else ""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path,
                        "-af", af + "astats=metadata=1:reset=0", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.findall(r"RMS level dB:\s*(-?\d+\.\d+|-inf)", r.stderr)
    if not m:
        return None
    return -99.0 if m[-1] == "-inf" else float(m[-1])


def mquality():
    """判一条配乐能不能用。**公版录音必跑。**

    生成的曲子交回来是干净的；找来的录音坏在三处，都能量：
    一、**底噪** —— 历史转录带一层持续嘶声，音乐压到 −25 dB 后它跟着被听见；
    二、**带宽** —— 老转录高频到 5kHz 就没了，和现代音效放一起显得蒙，
        而且它自己盖不住自己的嘶声；
    三、**头尾静音与杂音** —— 抓轨常带引子静音，MUSIC_IN 会被整体推偏。
    量不出来的那件事（这条演奏好不好、贴不贴）必须交回用户。
    """
    if not music_on():
        sys.exit("!!! MUSIC_MODE='none' —— 这一支不要背景音乐")
    if not os.path.exists(MUSIC):
        sys.exit("!!! 音乐还没就位: " + MUSIC)
    total = timeline()[2]
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration:stream=sample_rate,channels",
                        "-of", "default=nw=1", MUSIC], capture_output=True, text=True)
    print("\n=== %s ===" % MUSIC)
    print("   " + "  ".join(ln.strip() for ln in p.stdout.splitlines() if ln.strip()))
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", MUSIC,
                        "-af", "ebur128=framelog=info", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    curve = []
    for ln in r.stderr.splitlines():
        if "t:" in ln and " M:" in ln:
            try:
                curve.append((float(ln.split("t:")[1].split()[0]),
                              float(ln.split(" M:")[1].split()[0])))
            except (IndexError, ValueError):
                pass
    integ = integrated_lufs(MUSIC)
    print("\n   整合响度 %.1f LUFS" % (integ if integ is not None else -99))
    if curve:
        live = [m for _, m in curve if m > -70]
        floor = min(live) if live else -70.0
        gap = (integ - floor) if integ is not None else 0
        print("   全曲 %.1fs（片长 %.1fs，余地 %.1fs）" % (curve[-1][0], total,
                                                          curve[-1][0] - total))
        print("   最安静的一刻 %.1f LUFS，离整合响度 %.0f dB —— %s"
              % (floor, gap,
                 "生成的曲子一般 >40 dB；<30 dB 多半有一层持续嘶声" if gap < 30 else "够干净"))
    print("\n   分频段 RMS（判带宽）：")
    full = band_rms(MUSIC)
    for name, f in (("<120Hz", "lowpass=f=120"),
                    ("120-2k", "highpass=f=120,lowpass=f=2000"),
                    ("2k-8k", "highpass=f=2000,lowpass=f=8000"),
                    (">8kHz", "highpass=f=8000")):
        v = band_rms(MUSIC, f)
        rel = (v - full) if (v is not None and full is not None) else 0
        note = ("  << 8k 以上基本是空的 —— 老转录"
                if name == ">8kHz" and rel < -40 else "")
        print("      %-7s %6.1f dB  (相对全带 %+.1f)%s" % (name, v if v else -99, rel, note))
    diff = band_rms(MUSIC, "pan=mono|c0=0.5*c0-0.5*c1")
    if diff is not None and full is not None:
        print("      左右差信号 %.1f dB —— %s"
              % (diff, "单声道（不是毛病，知道就行）" if diff - full < -40 else "立体声"))
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", MUSIC,
                        "-af", "silencedetect=n=-45dB:d=0.4", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    head = [ln for ln in r.stderr.splitlines() if "silence_end:" in ln]
    if head and "silence_start: 0" in r.stderr.split("silence_end:")[0]:
        try:
            print("\n   头部静音 %.2fs —— **MUSIC_IN 要把它算进去**"
                  % float(head[0].split("silence_end:")[1].split()[0]))
        except (IndexError, ValueError):
            pass
    if MUSIC_MODE == "public_domain":
        miss = [k for k in ("work", "performer", "source", "license", "url")
                if not str(MUSIC_CREDIT.get(k, "")).strip()]
        print("\n   授权登记: " + ("**缺 %s**，check 会拦" % "/".join(miss) if miss
                                   else "齐了（%s）" % MUSIC_CREDIT["license"]))
    print("\n   量不出来的那件事：**这条演奏好不好、贴不贴这一支**。")
    print("   多留一条候选、把最终选择交回用户，比自己拍板诚实。")


def credits(dry=False):
    """导出素材来源表。用了找来的素材时，它是交付物的一部分。

    `dry=True` 只返回行、不落盘 —— selftest_credits() 要**看输出**才验得了
    "登记了有没有真的写进去"，光数 check 的条数看不出来。
    """
    lines = ["# %s · 素材来源" % TITLE, "", "成片：%s" % final_name(), "", "## 画面", ""]
    if IMG_SOURCE == "found":
        lines.append("| 镜 | 文件 | 类型 | 用到的段 | 作品 | 收藏/权利人 | 来源 | 授权 | 链接 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for i, c in enumerate(CLIPS, 1):
            k = clip_key(c)
            e = CREDITS.get(k, {})
            seg = ("%s–%s" % (c.get("ss"), c.get("to"))) if c.get("video") else "—"
            lines.append("| %d | %s | %s | %s | %s | %s | %s | %s | %s |"
                         % (i, k, "视频" if c.get("video") else "静图", seg,
                            e.get("title", "**缺**"), e.get("holder", "**缺**"),
                            e.get("source", "**缺**"), e.get("license", "**缺**"),
                            e.get("url", "**缺**")))
    else:
        # **不能一句"全部生成"带过。** IMG_SOURCE 是全片一个值，而"二十几张生成图
        # + 几张真档案"是讲述片的常态；那几张的登记就写在同一个脚本的 CREDITS 里。
        # 旧版只在 IMG_SOURCE=="found" 时读 CREDITS，于是**登记了也等于没登记**，
        # 交付物里断言"无第三方权利"。《瓶子裡的金子》(2026-09-21) 就这么交过一版：
        # 4 张 Commons 档案照，其中镜 7 是 **CC BY 4.0**，署名是硬要求。
        # 这是下面音效那条注释说的同一个坑的第二只脚。
        seen, reg = set(), []
        for c in CLIPS:
            k = clip_key(c)
            if k in seen:
                continue
            seen.add(k)
            if k in CREDITS:
                reg.append((k, c))
        if not reg:
            lines.append("按出图任务书生成（IMG_SOURCE='generated'），无第三方权利。")
        else:
            lines.append("%d 份素材按出图任务书生成，其中 **%d 份来自第三方**，"
                         "逐条登记如下。" % (len(seen) - len(reg), len(reg)))
            lines += ["", "| 文件 | 类型 | 用到的段 | 作品 | 收藏/权利人 | 来源 | 授权 | 链接 |",
                      "|---|---|---|---|---|---|---|---|"]
            for k, c in reg:
                e = CREDITS[k]
                seg = ("%s–%s" % (c.get("ss"), c.get("to"))) if c.get("video") else "—"
                lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |"
                             % (k, "视频" if c.get("video") else "静图", seg,
                                e.get("title", "**缺**"), e.get("holder", "**缺**"),
                                e.get("source", "**缺**"), e.get("license", "**缺**"),
                                e.get("url", "**缺**")))
    lines += ["", "## 配乐", ""]
    if not music_on():
        lines.append("无背景音乐（MUSIC_MODE='none'）。")
    elif MUSIC_MODE == "generated":
        lines.append("生成（ChatCut submit_music），无第三方权利。")
    elif MUSIC_MODE == "library":
        lines.append("从素材库复用：`%s`（原为自生成），无第三方权利。"
                     % (MUSIC_FROM_LIBRARY or "**没填 MUSIC_FROM_LIBRARY**"))
    else:
        for k, label in (("work", "作品"), ("performer", "演奏/录音"),
                         ("source", "来源"), ("license", "授权"), ("url", "链接")):
            lines.append("- %s：%s" % (label, MUSIC_CREDIT.get(k, "**缺**")))
        lines += ["", "> **录音权与作品权是两回事。** 上面登记的是**这一次录音**的授权，"
                      "不是作曲家去世多少年。"]
    lines += ["", "## 旁白与音效", "", "旁白 %d 条为 TTS 生成，无第三方权利。" % len(NARR)]
    # **音效不能一句"均为生成"带过。** 找来的音效有第三方权利，来源就写在同一个
    # 脚本的 SFX_CREDITS 里 —— 第一版的 credits 根本不读它，于是在交付物里
    # **断言了一件不成立的事**（"音效 N 条为生成，均无第三方权利"）。
    # 它不报错，只是把一句假话写进了要交出去的文件。四支片子都这么写过。
    used = []
    for e in SFX:
        if e["f"] not in used:
            used.append(e["f"])
    found = [f for f in used if f in SFX_CREDITS]
    if not found:
        lines.append("音效 %d 条（%d 个文件）全部为生成或自有素材库，无第三方权利。"
                     % (len(SFX), len(used)))
    else:
        lines.append("音效 %d 条，用到 %d 个文件，其中 **%d 个来自第三方**，逐条登记如下。"
                     % (len(SFX), len(used), len(found)))
        lines += ["", "| 文件 | 作品 | 作者 | 来源 | 授权 | 链接 |",
                  "|---|---|---|---|---|---|"]
        for f in found:
            e = SFX_CREDITS[f]
            lines.append("| %s | %s | %s | %s | %s | %s |"
                         % (f, e.get("title", "**缺**"), e.get("author", "**缺**"),
                            e.get("source", "**缺**"), e.get("license", "**缺**"),
                            e.get("url", "**缺**")))
        lines += ["", "其余 %d 个文件为生成或自有素材库，无第三方权利。" % (len(used) - len(found)),
                  "",
                  "> **署名一律给。** Pixabay 的 License Summary 说署名非强制，"
                  "但同一页也写着「certain Content may be subject to additional "
                  "intellectual property rights，**It is your responsibility to check**」——"
                  "而从 Freesound 转载的条目，原始授权可能是 CC-BY（要求署名）。"
                  "署名成本为零，不署名的风险不为零。"]
    if dry:
        return lines
    out = os.path.join(out_dir(), "素材来源.md")
    write_generated(out, lines)
    print("素材来源表 -> " + out)
    if "**缺**" in "\n".join(lines):
        print("!! 表里有**缺**的格子 —— 先把 CREDITS / MUSIC_CREDIT 填全（check 也会拦）")


def pick_music_in():
    """maximin 选音乐切入点。

    **讲述片的关键窗口和诗片不一样。** 诗片全程只有音乐，窗口取每句字幕的落点；
    讲述片全程有旁白盖着，音乐在那些地方本来就该退到后面 ——
    真正听得见音乐的是**旁白之间的缝**：冷开场、长转场、金句留白、尾板。
    照搬诗片那套窗口会选错点。

    公版录音多一件事：**真曲子有终止式**。除了 maximin 的解，这里还会单独评一个
    "让曲子的自然收束正好落在片尾"的候选。乐句边界本身量不出来，最终要听。"""
    if not music_on():
        sys.exit("!!! MUSIC_MODE='none' —— 这一支不要背景音乐，没有切入点可挑")
    if not os.path.exists(MUSIC):
        sys.exit("!!! 音乐还没就位: " + MUSIC)
    lines, durs, total, starts = timeline()
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", MUSIC,
                        "-af", "ebur128=framelog=info", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    curve = []
    for ln in p.stderr.splitlines():
        if "t:" in ln and " M:" in ln:
            try:
                t = float(ln.split("t:")[1].split()[0])
                m = float(ln.split(" M:")[1].split()[0])
                if m > -70:
                    curve.append((t, m))
            except (IndexError, ValueError):
                pass
    if len(curve) < 50:
        sys.exit("!!! 读不出响度曲线（ffmpeg 8.x 要 framelog=info，不是 verbose）")
    mdur = curve[-1][0]
    print("全曲 %.1fs，采样 %d 点，最低 %.1f / 最高 %.1f LUFS"
          % (mdur, len(curve), min(m for _, m in curve), max(m for _, m in curve)))

    keys = [("冷开场", 0.0, max(1.5, NARR[0]["pre"]))]
    for i in range(len(SHOTS) - 1):          # 每个长转场都是一处听得见音乐的缝
        if xf(i) >= 1.5:
            keys.append(("镜%d→%d 长转场" % (i + 1, i + 2),
                         max(0.0, starts[i + 1] - xf(i)), xf(i) + 1.5))
    gaps = []                                # 旁白之间 >=0.9s 的静默
    for a, b in zip(lines, lines[1:]):
        g = b[4] - (a[4] + a[5])
        if g >= 0.9:
            gaps.append((a[4] + a[5], g))
    gaps.sort(key=lambda x: -x[1])
    for t, g in gaps[:3]:
        keys.append(("留白 %.0fs" % t, t, g))
    keys.append(("尾板", starts[-1], min(6.0, durs[-1])))
    keys.append(("淡出", total - FADE_OUT, FADE_OUT))

    def win_avg(off, a, d):
        v = [m for t, m in curve if off + a <= t <= off + a + d]
        return sum(v) / len(v) if v else -70.0

    room = mdur - total
    if room <= 0:
        sys.exit("!!! 音乐比片子还短")
    best, off = None, 0.0
    while off <= room + 1e-6:
        scores = [win_avg(off, a, d) for _, a, d in keys]
        mn = min(scores)
        if best is None or mn > best[0]:
            best = (mn, off, scores)
        off += 0.5
    mn, off, scores = best
    print("\nmaximin 选出切入点 %.1fs（余地 %.1fs，用到 %.1fs）" % (off, room, off + total))
    for (name, _, _), s in zip(keys, scores):
        print("   %-16s %.1f LUFS" % (name, s))
    print("   全片最弱落点 %.1f LUFS" % mn)
    print("   这一段的最深谷 %.1f LUFS"
          % min(m for t, m in curve if off <= t <= off + total))
    valleys(curve, off, total, starts)
    if MUSIC_MODE == "public_domain":
        ts = [win_avg(room, a, d) for _, a, d in keys]
        print("\n另一个候选：切入点 %.1fs —— 曲子的自然收束正好落在片尾" % room)
        print("   全片最弱落点 %.1f LUFS（maximin 那个是 %.1f，差 %.1f dB）"
              % (min(ts), mn, min(ts) - mn))
        print("   **这两个哪个对要听。** 差在 2 dB 以内就选这个，"
              "让曲子有结尾比多两分贝值钱")
    print("\n把 MUSIC_IN 改成 %.1f" % off)


def valleys(curve, off, total, starts, thr=-25.0, minlen=0.4):
    """把用到的这一段里低于 thr 的谷全列出来，并说清它落在片子的哪一镜。

    "拿到曲子先翻一遍低谷再决定要不要第二条候选"原来是句手工提醒 —— 手工翻要看
    几百行响度采样，翻漏是必然的。上一支的候选 A 在 121~130s 藏了 1.7 秒近乎静音，
    是翻出来才弃用的；另一支的最低 −70.6 在 191s，那只是**结尾的自然收尾**、
    根本没用到。两者的区别决定要不要重新生成，所以值得自动化。
    """
    segs, cur = [], None
    for t, m in curve:
        if not (off <= t <= off + total):
            continue
        if m < thr:
            cur = (cur[0], t) if cur else (t, t)
        elif cur:
            segs.append(cur); cur = None
    if cur:
        segs.append(cur)
    segs = [s for s in segs if s[1] - s[0] >= minlen]
    print("")
    if not segs:
        print("   用到的这一段里没有低于 %.0f LUFS 的谷 —— 干净，不用发第二条候选" % thr)
        return
    print("   用到的这一段里有 %d 处低于 %.0f LUFS 的谷：" % (len(segs), thr))
    for a, b in segs:
        ta, tb = a - off, b - off
        n = sum(1 for s in starts if ta >= s - 1e-6)
        where = "片尾淡出里" if ta > total - FADE_OUT else "镜 %d" % max(1, n)
        print("      曲上 %6.1f~%6.1f  ->  片上 %6.1f~%6.1f (%.1fs)  %s"
              % (a, b, ta, tb, tb - ta, where))
    print("   落在片尾淡出里的不算问题；落在正片里的**中段 breakdown** 才是"
          "该换一条曲子的理由")


def mix_name(lang):
    return "mix_%s.wav" % lang


def build_audio(lang=None):
    """旁白 + 音乐(侧链躲闪) + 音效，混出**一条语言**的音床。

    音乐**必须侧链躲闪**，只调低音量是不够的：压到听不见音乐就没意义，
    压不够旁白就发浑。每条旁白**单独**归一到 VO_TARGET，顺带抹平 TTS 的忽大忽小。

    **多音轨时这个函数每种语言各跑一遍。** 音乐和音效是同一床、同样的切入点和增益，
    只有旁白换语言 —— 但侧链要按**各自的**旁白重算：英文的停顿位置和中文不一样，
    拿中文的包络去躲英文，音乐会在英文正在说话的地方抬起来。
    旁白的落点一律取中文定出来的 vs（画面只有一份），所以这里不重排时间轴。
    """
    lang = lang or DEFAULT_LANG
    lines, _, total, _ = timeline()
    durs_map, missing = vo_durs(lang)
    if missing:
        sys.exit("!!! %s 轨还缺 %d 条旁白，不能混音: %s"
                 % (LANG_INFO[lang]["name"], len(missing), ", ".join(missing[:3])))
    ins, parts, vbus, k = [], [], [], 0
    if music_on():
        ins += ["-i", MUSIC]
        parts.append("[0:a]aresample=48000,aformat=fltp:cl=stereo,"
                     "atrim=start=%.3f:end=%.3f,asetpts=PTS-STARTPTS,volume=%.1fdB,"
                     "apad,atrim=0:%.3f,afade=t=in:st=0:d=%.2f,afade=t=out:st=%.3f:d=3[m]"
                     % (MUSIC_IN, MUSIC_IN + total, MUSIC_GAIN, total,
                        MUSIC_FADE_IN, max(0.0, total - 3)))
        k = 1
    print("\n=== %s旁白增益（每条按实测反算到 %.1f LUFS）==="
          % (LANG_INFO[lang]["name"] + " " if len(LANGS) > 1 else "", VO_TARGET))
    # lines 与 NARR 严格同序（timeline 按镜号分组、组内保序，而 NARR 本来就按镜号排），
    # 所以按下标取起点，不要按文本去匹配 —— 两句话一字不差是很常见的
    for j, n in enumerate(NARR):
        path = vo_path(n, lang)
        meas = integrated_lufs(path)
        g = VO_TARGET - meas if meas is not None else 0.0
        print("   %-11s 实测 %6.1f → %+6.1f dB" % (n["vo"], meas if meas else 0, g))
        vs = lines[j][4]
        ins += ["-i", path]
        parts.append("[%d:a]aresample=48000,aformat=fltp:cl=stereo,volume=%.1fdB,"
                     "adelay=%d|%d,apad[v%d]" % (k, g, int(vs * 1000), int(vs * 1000), k))
        vbus.append("[v%d]" % k)
        k += 1
    parts.append("%samix=inputs=%d:normalize=0:dropout_transition=0,atrim=0:%.3f[vo]"
                 % ("".join(vbus), len(vbus), total))
    if music_on():
        parts.append("[vo]asplit=2[voa][vosc]")
        parts.append("[m][vosc]sidechaincompress=threshold=%.3f:ratio=%d:attack=%d:"
                     "release=%d[md]"
                     % (DUCK["threshold"], DUCK["ratio"], DUCK["attack"], DUCK["release"]))
        mixed = ["[md]", "[voa]"]
    else:
        # 没有音乐就没有要躲闪的东西 —— 侧链是"让音乐给旁白让路"，不是旁白的效果。
        # 照着有音乐那条路写下去会引用一个不存在的 [m]，filter_complex 直接报错。
        parts.append("[vo]anull[voa]")
        mixed = ["[voa]"]
    # 音效起点按**镜号 + 镜内偏移**解析成秒数。旁白一改，绝对秒数全错，
    # 而"在镜 3 开头进来"这个意图不变 —— 所以让脚本来算，不手写秒数。
    st_shots = shot_starts()
    print("\n=== 音效（目标响度锚在 VO_TARGET=%.1f 上，不是音乐）===" % SFX_ANCHOR)
    for s in SFX:
        f, tgt, fi, fo = s["f"], s["tgt"], s["fi"], s["fo"]
        dur = sfx_dur(s)
        if not 1 <= s["shot"] <= len(SHOTS):
            sys.exit("!!! 音效 %s 的 shot=%d 超出 %d 镜" % (f, s["shot"], len(SHOTS)))
        t = max(0.0, st_shots[s["shot"] - 1] + s["off"])
        if t + dur > total + 1e-6:
            print("   ** %s 从 %.1fs 放 %.1fs 会超出段长 %.1fs，已裁短" % (f, t, dur, total))
            dur = max(0.1, total - t)
        path = os.path.join(SRC, f)
        if not os.path.exists(path):
            print("   跳过音效(缺文件): " + f); continue
        meas = integrated_lufs(path)
        g = tgt - meas if meas is not None else -20.0
        flag = "  << 提得太多，底噪会一起上来，建议重生成" if g > SFX_GAIN_WARN else ""
        print("   %-14s 镜%-3d 起 %6.2fs 长 %5.1fs  实测 %6.1f → 目标 %6.1f（VO%+.0f），增益 %+6.1f dB%s"
              % (f, s["shot"], t, dur, meas or 0, tgt, tgt - SFX_ANCHOR, g, flag))
        ins += ["-stream_loop", "-1", "-i", path]
        parts.append("[%d:a]aresample=48000,aformat=fltp:cl=stereo,atrim=0:%.3f,"
                     "asetpts=PTS-STARTPTS,volume=%.1fdB,afade=t=in:st=0:d=%.2f,"
                     "afade=t=out:st=%.3f:d=%.2f,adelay=%d|%d,apad[s%d]"
                     % (k, dur, g, fi, max(0.0, dur - fo), fo, int(t * 1000), int(t * 1000), k))
        mixed.append("[s%d]" % k)
        k += 1
    # **`level=disabled` 比 `limit` 本身更要紧。**
    # alimiter 的 `level` 选项默认是开的，它会把输出**重新归一回 0 dBFS** ——
    # 于是 `limit=0.85` 限完又被抬回去，一点余量都不剩。实测同一条 mix：
    #     alimiter=limit=0.85                  样本峰值 -0.0 dB / 真峰值 +0.10 dBTP
    #     alimiter=limit=0.85:level=disabled   样本峰值 -1.4 dB / 真峰值 -1.32 dBTP
    # 之前把 0.95 改成 0.85 是白改的，从来没产生过余量 —— 参数写了但没生效，
    # 和运镜那个"写了位移却没给足缩放"是同一个形状：**参数表上完全看不出来。**
    #
    # 为什么要留余量：**段用文件是要交给 join 再编码一次的中间件**，顶在 0 dBTP 上
    # AAC 解码会漏一层失真。1.4 dB 是**所有段共用的常数**，不会变成逐段增益差。
    # 预览那一路照旧归一到 −15，看不出区别。
    parts.append("%samix=inputs=%d:normalize=0:dropout_transition=0,"
                 "atrim=0:%.3f,alimiter=limit=0.85:level=disabled[a]" % ("".join(mixed), len(mixed), total))
    out = mix_name(lang)
    run(["ffmpeg", "-y", "-v", "error", "-stats"] + ins
        + ["-filter_complex", ";".join(parts), "-map", "[a]",
           "-c:a", "pcm_s24le", "-t", "%.3f" % total, out],
        "混音(%s): 旁白 %d 条 + %s + 音效 %d 条 -> %s"
        % (LANG_INFO[lang]["name"], len(NARR),
           "音乐(从 %.1fs 切入，侧链躲闪)" % MUSIC_IN if music_on() else "无音乐",
           len(mixed) - (2 if music_on() else 1), out))
    return out


def measure_loudness(path):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af",
                        "loudnorm=I=%.1f:TP=%.1f:print_format=json" % (TARGET_I, TARGET_TP),
                        "-f", "null", "-"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    m = json.loads(p.stderr[p.stderr.rfind("{"):p.stderr.rfind("}") + 1])
    print("   实测 I=%s LUFS  TP=%s dBTP" % (m["input_i"], m["input_tp"]))
    return m


# ================= 字幕 =================
def _style(name, size, pol, spacing=0, align=5):
    # **第 4 个位置参数是字距，第 5 个才是对齐。**
    # 传 _style(..., 3) 想要右下对齐，实际设的是字距 3、对齐仍是默认的 5（居中），
    # 于是 \pos 变成以该点为中心，一半文字跑出画面 —— 而且渲得出来，不报错。
    if pol == "dark_on_light":
        pri, out, ol, sh = "&H00262A2D", "&H00EAF3F6", 3, 0
    else:
        pri, out, ol, sh = "&H00F2F2EC", "&H00000000", 3, 3
    return ("Style: %s,%s,%d,%s,%s,%s,%s,0,0,0,0,100,100,%d,0,1,%d,%d,%d,20,20,0,1"
            % (name, SUB_FONT, size, pri, pri, out, out, spacing, ol, sh, align))


def styles_block():
    return "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour," \
           "SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline," \
           "StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow," \
           "Alignment,MarginL,MarginR,MarginV,Encoding\n" \
           + "\n".join([_style("T", 88, TITLE_POLARITY, 6),
                        _style("TS", 44, TITLE_POLARITY, 8),
                        _style("CT", 88, COVER_POLARITY or TITLE_POLARITY, 6),
                        _style("CTS", 44, COVER_POLARITY or TITLE_POLARITY, 8),
                        _style("M", SUB_FS, POLARITY, 2),
                        _style("L", 26, POLARITY, 0, 3)]) + "\n"


def ts(t):
    return "%d:%02d:%05.2f" % (t // 3600, t % 3600 // 60, t % 60)


def srt_ts(t):
    """SRT 的时间码是 HH:MM:SS,mmm —— 毫秒用**逗号**，不是 ASS 的点。
    写成点号大多数播放器会整条丢掉而**不报错**，字幕就是"莫名其妙没有"。"""
    ms = int(round(t * 1000))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60,
                                    ms // 1000 % 60, ms % 1000)


def preview(lang=None):
    """出图之前的检查片：**占位画面 + 真旁白 + 真字幕**。门禁二靠它。

    多音轨时可以 `preview en` 单听英文那条 —— 英文塞得进槽是 langfit 算出来的，
    **听起来赶不赶只有放出来才知道**，而这时候图还没出，改稿最便宜。

    交给用户的是一支能听完的片子，不是一堆数字。它定死四件事，全在出图之前：
    旁白好不好听 · 断句与气口 · 字幕跟不跟得上 · **片长**。
    真图到了直接替换同名文件，CLIPS / SHOTS / NARR 一个字都不用动。

    ---- 三条实现上的讲究 ----

    1. **所有文字都走 ASS，一个 drawtext 都不用。** 带 drawtext 的 ffmpeg 在
       Git bash 下会 Fontconfig error + 段错误（见 references/codex.md），
       而 `subtitles=`（libass）这条路整条流水线天天在跑，是验过的。
       占位板上的镜号、文件名、画面描述因此全部当字幕烧，不画进图里。

    2. **背景只出一张，不是一镜一张。** 镜与镜的分界靠镜号标签变化看出来，
       够用；一镜一张要多跑 N 条 ffmpeg 换不来任何信息。

    3. **只有旁白，没有音效没有音乐。** 这一版要验的是"话说得对不对"，
       多铺一层会让人分神去听氛围。而且这时候音效多半还没找。

    ---- 这一版验不了什么（必须说清楚，别让它冒充通过）----

      motion            **结构性失效** —— 占位板是均匀灰，中位帧差恒为 0
      trace / measure   不适用 —— 量的是真实画面的明暗
      字幕排版          **有效** —— 断行/宽度只跟字号坐标有关，跟画面无关
    """
    lang = lang or DEFAULT_LANG
    _, durs, total, starts = timeline()
    lines = lang_lines(lang)
    durs_map, missing = vo_durs(lang)
    if missing:
        sys.exit("!!! %s 轨还缺 %d 条旁白，出不了检查片: %s"
                 % (LANG_INFO[lang]["name"], len(missing), ", ".join(missing[:5])))

    # ---- 背景：深灰 + 一条压暗的横带标出字幕位置 ----
    y0 = max(0, SUB_BOT - 2 * SUB_LH - 14)
    bh = min(H - y0, 2 * SUB_LH + 28)
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "color=c=0x2b2b2b:s=%dx%d" % (W, H),
         "-vf", "drawbox=x=0:y=%d:w=%d:h=%d:color=0x171717@1:t=fill" % (y0, W, bh),
         "-frames:v", "1", "_pv_bg.png"], "占位背景")

    # ---- 一份 ASS 装下全部文字：镜号 / 图名 / 描述 / 正文字幕 ----
    ev = []
    for i, c in enumerate(CLIPS):
        t0 = starts[i]
        t1 = starts[i + 1] if i + 1 < len(starts) else total
        desc = SHOTS[i].get("desc", "")
        head = "镜 %d / %d" % (i + 1, len(CLIPS))
        reuse = [j + 1 for j, d in enumerate(CLIPS) if clip_key(d) == clip_key(c)]
        if len(reuse) > 1:
            head += "   （%s 共用一张图）" % " / ".join("镜%d" % r for r in reuse)
        z0, z1 = SHOTS[i]["z"]
        move = ("静帧" if z0 == z1 and SHOTS[i]["f0"] == SHOTS[i]["f1"]
                else "推近" if z1 > z0 else "拉远" if z1 < z0 else "横移")
        head += "   %s z %.2f→%.2f   %.1fs" % (move, z0, z1, t1 - t0)
        for k, txt in enumerate([head, clip_key(c), desc]):
            if not txt:
                continue
            ev.append("Dialogue: 0,%s,%s,PV,,0,0,0,,{\\pos(%d,%d)}%s"
                      % (ts(t0), ts(t1), W // 2,
                         int(H * 0.16) + k * int(PV_FS * 1.7), txt))
    # **逐行堆叠，不要挤成一条。** 排版要和成片一模一样，
    # 否则「字幕跟不跟得上」这一项验的就不是真东西了。
    for st, en, txt, _, _, _ in lines:
        parts = sub_lines(txt)
        for j, q in enumerate(parts):
            y = SUB_BOT - (len(parts) - 1 - j) * SUB_LH - SUB_FS // 2
            ev.append("Dialogue: 1,%s,%s,M,,0,0,0,,{\\pos(%d,%d)}%s"
                      % (ts(st), ts(en), SUB_CX, y, q))
    with open("_pv.ass", "w", encoding="utf-8-sig") as f:
        f.write("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\n"
                "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n" % (W, H)
                + styles_block()[:-1] + "\n"
                + _style("PV", PV_FS, "light_on_dark", 2) + "\n"
                + "\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,"
                  "MarginV,Effect,Text\n" + "\n".join(ev) + "\n")

    # ---- 音频：只有旁白，每条按实测反算到 VO_TARGET ----
    ins, parts, bus = ["-loop", "1", "-i", "_pv_bg.png"], [], []
    for j, n in enumerate(NARR):
        path = vo_path(n, lang)
        meas = integrated_lufs(path)
        g = VO_TARGET - meas if meas is not None else 0.0
        vs = lines[j][4]
        ins += ["-i", path]
        parts.append("[%d:a]aresample=48000,aformat=fltp:cl=stereo,volume=%.1fdB,"
                     "adelay=%d|%d,apad[v%d]"
                     % (j + 1, g, int(vs * 1000), int(vs * 1000), j + 1))
        bus.append("[v%d]" % (j + 1))
    parts.append("%samix=inputs=%d:normalize=0:dropout_transition=0,"
                 "atrim=0:%.3f,alimiter=limit=0.85:level=disabled[a]"
                 % ("".join(bus), len(bus), total))
    parts.append("[0:v]fps=%d,format=yuv420p,subtitles=_pv.ass:fontsdir=%s[v]"
                 % (FPS, FONTS.replace("\\", "/")))

    out = os.path.join(out_dir(), CHECK_NAME if lang == DEFAULT_LANG
                       else CHECK_NAME.replace(".mp4", ".%s.mp4" % lang))
    run(["ffmpeg", "-y", "-v", "error", "-stats"] + ins
        + ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]",
           "-t", "%.3f" % total, "-c:v", "libx264", "-crf", "23",
           "-preset", "veryfast", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", out],
        "检查片(%s) %d 镜 / %d 条旁白 / %.1fs -> %s"
        % (LANG_INFO[lang]["name"], len(CLIPS), len(NARR), total, out))
    for f in ("_pv_bg.png", "_pv.ass"):
        if os.path.exists(f):
            os.remove(f)
    print("")
    print("  **这一版没有音效、没有音乐**，要验的是话说得对不对。")
    print("  片长 %.3fs = %.1f 分。%s"
          % (total, total / 60.0,
             "硬线 %ds，%s" % (HARD_LIMIT,
                              "还差 %.1fs" % (HARD_LIMIT - total) if total <= HARD_LIMIT
                              else "**已超 %.1fs**" % (total - HARD_LIMIT))
             if globals().get("HARD_LIMIT") else "没有硬线"))
    print("  交给用户听完，把结论写进 GATE_PREVIEW_OK，才允许出图。")
    print("  motion / trace / measure 对占位板**不适用**，这时候别跑。")
    return out


def make_srt(lang=None):
    """正文字幕 → 外挂 SRT。多音轨时每种语言各一份，文件名由 srt_name() 定。

    两处和烧录不一样：
      - 手工断行符 SUB_SEP 在 SRT 里就是真正的换行（烧录时是分行定位）
      - **相邻两条不能重叠**：烧录时重叠只是两行字同时在屏上，SRT 里
        重叠会让播放器行为不一致（有的堆叠、有的闪、有的丢）。所以硬性收尾。

    英文那份的**起点和中文完全一样**（槽是中文定的），只有收尾跟着英文音频走。
    """
    lang = lang or DEFAULT_LANG
    lines = lang_lines(lang)
    ev, fixed = [], 0
    for i, (st, en, txt, _, _, _) in enumerate(lines):
        if i + 1 < len(lines) and en > lines[i + 1][0] - 0.04:
            en = max(st + 0.4, lines[i + 1][0] - 0.04)
            fixed += 1
        ev.append("%d\n%s --> %s\n%s\n" % (len(ev) + 1, srt_ts(st), srt_ts(en),
                                           "\n".join(sub_lines(txt))))
    out = os.path.join(out_dir(), srt_name(lang))
    with open(out, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(ev))
    print("已生成 %s（%s，%d 条%s）"
          % (out, LANG_INFO[lang]["name"], len(ev),
             "，收掉 %d 处重叠" % fixed if fixed else ""))
    return out


def make_ass():
    """**烧进画面的字**：开场标题字卡、画面角标、尾板，以及 `SUB_MODE="burn"` 时的正文字幕。
    外挂时正文字幕不在这里 —— 它走 make_srt。什么都没有时返回 False，pass_c 会把
    整条 subtitles 滤镜省掉（挂一个空的 ASS 上去不报错，但白跑一道滤镜）。"""
    lines, _, _, starts = timeline()
    ev = []
    if SUB_MODE == "burn":
        for st, en, txt, _, _, _ in lines:
            parts = sub_lines(txt)
            for j, p in enumerate(parts):
                y = SUB_BOT - (len(parts) - 1 - j) * SUB_LH - SUB_FS // 2
                ev.append("Dialogue: 0,%s,%s,M,,0,0,0,,{\\pos(%d,%d)}{\\fad(200,200)}%s"
                          % (ts(st), ts(en), SUB_CX, y, p))
    if TITLE_CARD:
        ev.append("Dialogue: 0,%s,%s,T,,0,0,0,,{\\pos(%d,%d)}{\\fad(900,900)}%s"
                  % (ts(TITLE_CARD["t0"]), ts(TITLE_CARD["t1"]),
                     W // 2, TITLE_CARD["y"], TITLE_CARD["head"]))
        ev.append("Dialogue: 0,%s,%s,TS,,0,0,0,,{\\pos(%d,%d)}{\\fad(900,900)}%s"
                  % (ts(TITLE_CARD["t0"] + 0.6), ts(TITLE_CARD["t1"]),
                     W // 2, TITLE_CARD["y"] + 92, TITLE_CARD["sub"]))
    for _sn, _tx in sorted(SHOT_LABELS.items()):
        _i = _sn - 1
        if not (0 <= _i < len(starts)):
            sys.exit("!!! SHOT_LABELS 里的镜 %d 不存在" % _sn)
        _a = starts[_i] + 0.5
        _b = (starts[_i + 1] if _i + 1 < len(starts) else total_len()) - 0.3
        if _b - _a < 0.8:
            print("   角标跳过镜 %d：在屏不足 0.8s" % _sn)
            continue
        ev.append("Dialogue: 0,%s,%s,L,,0,0,0,,{\\an3\\pos(%d,%d)}{\\fad(400,400)}%s"
                  % (ts(_a), ts(_b), W - 40, H - 44, _tx))
    if ENDCARD:
        t0 = starts[-1] + ENDCARD["t0"]
        t1 = min(starts[-1] + ENDCARD["t1"], total_len())
        ev.append("Dialogue: 0,%s,%s,T,,0,0,0,,{\\pos(%d,%d)}{\\fad(900,800)}%s"
                  % (ts(t0), ts(t1), W // 2, ENDCARD["y"], ENDCARD["head"]))
        ev.append("Dialogue: 0,%s,%s,TS,,0,0,0,,{\\pos(%d,%d)}{\\fad(900,800)}%s"
                  % (ts(t0 + 0.5), ts(t1), W // 2, ENDCARD["y"] + 96, ENDCARD["sub"]))
    with open("sub.ass", "w", encoding="utf-8-sig") as f:
        f.write("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\n"
                "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n" % (W, H)
                + styles_block()
                + "\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,"
                  "MarginV,Effect,Text\n" + "\n".join(ev) + "\n")
    print("已生成 sub.ass（%d 条%s）"
          % (len(ev), "" if SUB_MODE == "burn" else "，只有标题/角标/尾板，正文字幕走 SRT"))
    return bool(ev)


def make_scrim():
    """字幕在**底部**，所以 scrim 压的是底部，不是诗片的右侧。

    要不要叠由 scrim_on() 说了算（横版恒不叠）—— pass_c / still / measure /
    scrim_factor 四处都调这个函数，守卫写在这里才不会四处走样。
    """
    if not scrim_on():
        return False
    c = "white" if POLARITY == "dark_on_light" else "black"
    v = "255" if c == "white" else "0"
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         "color=c=%s:s=%dx%d,format=rgba," % (c, W, H)
         + r"geq=r='%s':g='%s':b='%s':a='clip(255*%.3f*pow(max(0\,(Y-%d))/%d\,%.2f),0,255)'"
         % (v, v, v, SCRIM_ALPHA, SCRIM_Y0, SCRIM_SOFT, SCRIM_POW),
         "-frames:v", "1", "scrim.png"], "生成底部 scrim")
    return True


def video_chain(tag="[0:v]", scrim=False, grain=True, text=True):
    """画面链。`text` 是"这一支有没有烧进画面的字"（make_ass 的返回值）——
    画面上一个字都没有时（外挂字幕的中间段）整条 subtitles 滤镜要省掉，不要挂一个空的。"""
    fd = FONTS.replace("\\", "/")
    pre = "%snoise=alls=2:allf=t[g];" % tag if grain else ""
    base = "[g]" if grain else tag
    if scrim:
        pre += "%s[1:v]overlay=0:0:shortest=1[s];" % base
        base = "[s]"
    if text:
        return pre + "%ssubtitles=sub.ass:fontsdir=%s[v]" % (base, fd)
    return pre + "%snull[v]" % base


def audio_meta():
    """音轨的语言元数据。**不写就全是 und（未定）**，上传 YouTube 之后
    要在网页上一条条手点，而且看不出是缺了元数据还是平台没认出来。"""
    meta = []
    for j, lang in enumerate(LANGS):
        info = LANG_INFO[lang]
        meta += ["-metadata:s:a:%d" % j, "language=%s" % info["code"],
                 "-metadata:s:a:%d" % j, "title=%s" % info["name"],
                 "-disposition:a:%d" % j,
                 "default" if lang == DEFAULT_LANG else "0"]
    return meta


def verify_tracks(path):
    """渲完立刻验**输出**里的音轨，不是复述配置。

    和 join 里那条黑场检查同一个道理：**配置对不等于输出对**。
    filter_complex 或 -map 写错一个下标，ffmpeg 不一定报错 ——
    它会安安静静地少写一条轨，而文件能播、时长对、中文轨也对。
    这一条几乎不花时间，却是唯一能在段这一级发现丢轨的地方
    （到了 join 那里，每段都少一条就成了"各段一致"，看不出来）。
    """
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                        "-show_entries", "stream_tags=language",
                        "-of", "default=nw=1:nk=1", path],
                       capture_output=True, text=True)
    got = [x.strip() or "und" for x in r.stdout.splitlines()]
    want = [LANG_INFO[l]["code"] for l in LANGS]
    if got != want:
        sys.exit("!!! %s 的音轨是 %s，应该是 %s —— 渲染时把轨弄丢或弄乱了，"
                 "不要拿它去 join" % (path, "/".join(got) or "无", "/".join(want)))
    return got


def pass_c():
    has_text = make_ass(); has = make_scrim(); total = total_len()
    mixes, norms = {}, {}
    for lang in LANGS:
        mixes[lang] = build_audio(lang)
    for lang in LANGS:
        if len(LANGS) > 1:
            print("\n--- %s 轨 ---" % LANG_INFO[lang]["name"])
        m = measure_loudness(mixes[lang])
        if norm_mode() == "loudnorm":
            # **每条轨各自量、各自归一到同一个目标。** 拿中文那条的测量值去归英文，
            # 两条轨会差出一个台阶，而观众切换音轨时那个台阶特别明显。
            norms[lang] = ("loudnorm=I=%.1f:TP=%.1f:LRA=%s:measured_I=%s:measured_TP=%s:"
                           "measured_LRA=%s:measured_thresh=%s:offset=%s:linear=true,"
                           "aresample=48000"
                           % (TARGET_I, TARGET_TP, m["input_lra"], m["input_i"],
                              m["input_tp"], m["input_lra"], m["input_thresh"],
                              m["target_offset"]))
        else:
            # 既没有音乐也没有旁白，只剩稀疏音效 —— 归一会把 SFX 表里的目标响度
            # 全部作废（理由见 norm_mode()）。只过一道重采样。
            print("   **不归一**（只有音效，SFX 表里的目标响度就是成片响度）")
            norms[lang] = "aresample=48000"
    if SUB_MODE != "burn":          # 烧录时字幕已经在画面里，不出 SRT
        for lang in LANGS:
            make_srt(lang)
    ins = ["-i", "master.mp4"] + (["-loop", "1", "-i", "scrim.png"] if has else [])
    base = 2 if has else 1
    for lang in LANGS:
        ins += ["-i", mixes[lang]]
    amaps = []
    for lang in LANGS:
        amaps += ["-map", "[a_%s]" % lang]
    ameta = audio_meta()
    enc = ["-c:v", "libx264", "-crf", "18", "-preset", "slow", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart",
           "-r", str(FPS), "-t", "%.3f" % total]

    # ---- 输出几个文件、叫什么，取决于**分不分段** ------------------------------
    # 分段（SEG_TOTAL > 1）：
    #   段用 **不归一**。逐段归一 = 每段一个增益 = 接缝处一个响度台阶，而且不报警
    #   （loudnorm 的整合响度带门限，各段静默比例不同就会算出不同的增益）。
    #   归一由 join 在拼完之后做一次。淡场按 SEG_FIRST/SEG_LAST 决定，已在 pass_b 里做完。
    #   `*_预览.mp4` 只为单看这一段，**默认不渲**，不要拿它去拼片。
    #
    # 不分段（SEG_TOTAL == 1）：**没有 join。**
    #   于是「归一」那一趟渲出来的**就是成片**，不是预览 —— 所以它不再叫 `*_预览.mp4`
    #   （见 final_name）。段用文件同时也没人要了：它唯一的下游就是 join。
    #   **那一整趟编码跳过**，`c` 因此快一倍。
    #
    #   2026-09-19 用户：「预览片默认不要，上次还是生成了」。上次生成的其实是成片，
    #   只是名字长得像预览 —— 交付物是归一过的那个，段用那个没归一。
    #   所以**能省的是段用和那个名字，归一那一趟不能省**。
    single = (SEG_TOTAL == 1)
    seg = os.path.join(out_dir(), OUT_NAME)
    if single:
        print("")
        print(">>> 不分段：**段用文件跳过**（它唯一的下游是 join）。归一那一趟就是成片。")
    else:
        fc = [video_chain("[0:v]", has, text=has_text)]
        fc += ["[%d:a]aresample=48000[a_%s]" % (base + j, l) for j, l in enumerate(LANGS)]
        run(["ffmpeg", "-y", "-v", "error", "-stats"] + ins
            + ["-filter_complex", ";".join(fc), "-map", "[v]"] + amaps + enc + ameta + [seg],
            "段用（**不归一**，%d 条音轨，给 join 拼片）-> %s" % (len(LANGS), seg))

    prev = os.path.join(out_dir(), final_name())
    want_prev = single or RENDER_PREVIEW or (len(sys.argv) > 2 and sys.argv[2] == "preview")
    if not want_prev:
        # 跳过的是**一整趟全长编码**，不是一个小步骤。段用文件已经出来了，
        # 单看这一段直接开它就行 —— 只是没归一、没尾部淡出。
        print("\n>>> 预览片**跳过**（RENDER_PREVIEW=False）。单看这一段开 %s；"
              "要归一版就跑 `c preview`" % seg)
    vf = video_chain("[0:v]", has, text=has_text)
    if PREVIEW_FADE_OUT > 0 and not SEG_LAST:
        vf = vf.replace("[v]", "[vp]") + \
            ";[vp]fade=t=out:st=%.3f:d=%.2f:c=%s[v]" \
            % (total - PREVIEW_FADE_OUT, PREVIEW_FADE_OUT, FADE_COLOR)
    fcp = [vf]
    fcp += ["[%d:a]%s[a_%s]" % (base + j, norms[l], l) for j, l in enumerate(LANGS)]
    if want_prev:
        run(["ffmpeg", "-y", "-v", "error", "-stats"] + ins
            + ["-filter_complex", ";".join(fcp), "-map", "[v]"] + amaps + enc + ameta + [prev],
            ("成片（归一到 %.1f LUFS）-> %s" if single
             else "预览（归一到 %.1f LUFS + 尾部淡出，给人看）-> %s") % (TARGET_I, prev))

    if not single:
        verify_tracks(seg)
    if want_prev:
        verify_tracks(prev)

    # ---- 多音轨要拆成可上传的形态 ----
    # **单段片子不走 join.py，于是原来永远拿不到这一步。** 多段的由 join 拆，
    # 单段的走完 c 就交付了 —— 交出去的是一个"能播、时长对、中文轨也对，
    # 只有英文轨没了"的上传件，而文件本身完全正常。2026-09-04《剩下的二九六公尺》踩到。
    up = multi = None
    auds = []
    if len(LANGS) > 1 and single:
        # 不分段时 want_prev 恒为 True（那一趟就是成片）。万一有人手改了开关，
        # 这里要炸得明白，不要拆出一个空文件。
        assert want_prev, "单段多音轨片必须渲成片才能拆上传件"
        # 归一那一趟**已经直接渲成 `*_多音轨.mp4`**（见 final_name），不再多复制一份
        multi = prev
        up, auds = split_tracks(multi)

    print("")
    print("完成：")
    if not single:
        print("  段用   %s   **不归一**，给 join；单看这一段也开它" % seg)
        if want_prev:
            print("  预览   %s   归一 + 淡出" % prev)
        else:
            print("  预览   **没渲**（默认行为）。要归一版跑 `c preview`")
    elif len(LANGS) == 1:
        print("  成片   %s   归一到 %.1f LUFS，**这就是交付物**" % (prev, TARGET_I))
    if SUB_MODE == "burn":
        print("  字幕   烧进画面（抖音/小红书那一路），没有 SRT")
    else:
        print("  字幕   %s   外挂，播放器渲染，跟着成片一起发"
              % " / ".join(os.path.join(out_dir(), srt_name(l)) for l in LANGS))
    if len(LANGS) > 1 and SEG_TOTAL > 1:
        print("  留档   本段是多音轨的 %s，**上传件和独立音频由 join.py 出**，"
              "这里不再逐段拆" % seg)
    if len(LANGS) > 1 and single:
        print("  上传件 %s   **只有 %s 一条轨，传这个**"
              % (up, LANG_INFO[LANGS[0]]["code"]))
        for code, a in auds:
            print("  附加音频 %s   在 Studio 里作为独立音频添加" % a)
        print("  留档   %s   两条轨都在，**不要拿它当上传件**" % multi)


def _still_shots():
    """抽静帧用眼睛看。

    **和竖版模板抽的东西不一样。** 那边一条字幕抽一张，因为要验字幕压在什么底上；
    这一支字幕外挂，没有那个问题了，要验的变成**画种在运镜下立不立得住** ——
    所以改成**每镜抽首/中/尾三帧**：一张看构图，三张连起来看镜头走了多远、
    落幅停在哪儿。这两件都是量不出来、只能看的。

    仍然先烧一版低码率预览再抽帧，不直接对 master 用 "-ss T -i"：
    标题字卡是烧进画面的，而 -ss 放在 -i 前会把 PTS 重置为 0，
    subtitles 滤镜按 PTS 找事件，字卡那几帧会一个字都渲不出来 —— 画面却是正常的，
    很容易误判成字卡样式有问题。
    """
    if not os.path.exists("master.mp4"):
        sys.exit("!!! 还没有 master.mp4，先跑 a + b")
    has_text = make_ass(); has = make_scrim(); os.makedirs("stills", exist_ok=True)
    ins = ["-i", "master.mp4"] + (["-loop", "1", "-i", "scrim.png"] if has else [])
    run(["ffmpeg", "-y", "-v", "error", "-stats"] + ins
        + ["-filter_complex", video_chain("[0:v]", has, grain=False, text=has_text),
           "-map", "[v]", "-c:v", "libx264", "-crf", "30", "-preset", "ultrafast",
           "-pix_fmt", "yuv420p", "-t", "%.3f" % total_len(), "preview.mp4"],
        "烧预览（含标题字卡）")
    durs, cst = timeline()[1], clip_starts()
    k = 0
    for n in range(1, len(SHOTS) + 1):
        # 用 probe_times 而不是 6%/50%/94% —— 后者会把起/尾帧取在转场里，
        # 于是一半静帧是**两镜的混合**（镜 2 的尾帧上能看见下一镜的船）。
        # 混合帧看不出这一镜自己走了多远，而"起→尾连起来看行程"正是这一趟的主要用途。
        for tag, tl in zip(("起", "中", "尾"), probe_times(n, durs)):
            t = cst[n - 1] + tl
            run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % t, "-i", "preview.mp4",
                 "-frames:v", "1", "stills/%02d%s_%.0fs.png" % (n, tag, t)],
                "静帧 镜%-3d %s  %.1fs  %s" % (n, tag, t, clip_key(CLIPS[n - 1])[:14]))
            k += 1
    print("\n%d 张静帧在 stills/（每镜 起/中/尾）" % k)
    print("要看三件事，都是量不出来的：")
    print("  1. 构图和内容对不对 —— 别信文件名，看画面")
    print("  2. 起→尾连起来，镜头是不是真的走了那么远")
    print("  3. 落幅那一帧停在哪儿 —— 停在人脸、发丝、窗框上都不行")


def _measure_probes():
    """**运镜对账** —— 拿 trace 的取样框预测和成片上实测的同一批框逐条对。

    ==== 为什么这个命令还在 ====

    竖版模板里 measure 量的是"每条字幕压着的底"，而它真正的价值不在字幕：
    它和 trace 一个在源图上算、一个在成片上量，**两者对得上是全流水线唯一一处
    能自检运镜的地方**。对不上说明镜头没走在你以为的位置上 —— 那比字幕糊了严重得多，
    而且没有别的办法能发现它（`motion` 只能证明画面变了，证明不了它变到了哪儿）。

    这一支字幕外挂，字幕框没有了。**但那个自检不能跟着丢**，所以把量的对象换成
    PROBE_BOXES 那三块固定取样框，其余机制一字不动。

    ==== 对不上的时候，先怀疑建模不一致，再怀疑运镜 ====

    历史上这个坑有三只脚，都是"pass_a / pass_c 加了一道影响亮度的滤镜，
    而 trace 那边没跟着补"：
      - vignette 加在 pass_a，trace 不补 → measure 一律低 5~31 级，越亮差得越多
      - scrim 加在 pass_c，trace 不补 → trace 一律偏亮
      - scrim 加在 pass_c，measure 抽帧后不叠回 → measure 一律偏亮（差 26 级）
    所以每加一道滤镜，**trace 和 measure 两边都得跟着补**。
    这一支 SCRIM_ALPHA=0，第二三只脚不存在；vignette 由 vig_factor() 建模。
    """
    if not os.path.exists("master.mp4"):
        sys.exit("!!! 还没有 master.mp4，先跑 a + b")
    if not os.path.exists("trace_pred.json"):
        sys.exit("!!! 没有 trace_pred.json —— 先跑 trace，它会把预测值存下来")
    raw_pred = json.load(open("trace_pred.json", encoding="utf-8"))
    pred = {}
    for k, v in raw_pred.items():
        a, b = k.split("|")
        pred[(int(a), b)] = v
    has_scrim = make_scrim()
    durs = timeline()[1]
    cst = clip_starts()

    print("\n=== 运镜对账（trace 预测 vs 成片实测，三框 × 起/中/止）===")
    print("    判据：逐条差 <= %.0f 级。差得多而且**越亮差得越多**，" % PROBE_TOL)
    print("    先查 pass_a/pass_c 有没有 trace 没建模的滤镜，再怀疑运镜。")
    worst, nbad, bias = 0.0, 0, {}
    for n in range(1, len(SHOTS) + 1):
        if (n, PROBE_BOXES[0][0]) not in pred:
            print("  镜%-3d (trace 当时缺图，跳过)" % n); continue
        cells = []
        # 取样时刻和 trace 共用 probe_times() —— 各写一份必漂，而且会漂在转场上
        for pi, tl in enumerate(probe_times(n, durs)):
            t = cst[n - 1] + tl
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % t,
                            "-i", "master.mp4", "-frames:v", "1", "_m.png"],
                           capture_output=True)
            args = ["ffmpeg", "-v", "error", "-i", "_m.png"]
            if has_scrim:
                args += ["-i", "scrim.png", "-filter_complex",
                         "[0:v][1:v]overlay=0:0:shortest=1,format=gray"]
            else:
                args += ["-vf", "format=gray"]
            b = subprocess.run(args + ["-f", "rawvideo", "-"], capture_output=True).stdout
            if len(b) < W * H:
                cells.append("  (读不出帧)"); continue
            for name, rx0, rx1, ry0, ry1 in PROBE_BOXES:
                x0, x1 = int(rx0 * W), int(rx1 * W)
                y0, y1 = int(ry0 * H), int(ry1 * H)
                v = [b[y * W + x] for y in range(y0, y1, 4) for x in range(x0, x1, 4)]
                got = sum(v) / len(v)
                exp = pred[(n, name)][pi]
                d = abs(got - exp)
                worst = max(worst, d)
                bias.setdefault(name, []).append(got - exp)
                if d > PROBE_TOL:
                    nbad += 1
                cells.append("%s%s %3.0f/%3.0f(%+.0f)%s"
                             % (name, "起中止"[pi], exp, got, got - exp,
                                "!" if d > PROBE_TOL else ""))
        print("  镜%-3d %s" % (n, "  ".join(cells)))
    if os.path.exists("_m.png"):
        os.remove("_m.png")
    if bias:
        print("")
        print("  每框平均偏差（成片 − 预测）：" + "   ".join(
            "%s %+.1f" % (k, sum(v) / len(v)) for k, v in bias.items()))
        print("  全框同向的小偏差 = 建模精度（多半是暗角），**某一镜跳变才是运镜出错**。")
    print("\n  最大偏差 %.1f 级，超出 %.0f 级的有 %d 处 —— %s"
          % (worst, PROBE_TOL, nbad,
             "运镜走在预期位置上" if nbad == 0 else "**对不上，先查滤镜建模再查运镜**"))
    print("  这只是数字，还要跑 still 用眼睛看：数值对但落幅停在人脸上是量不出来的。")


def check_cover_text(shot_png, bare_png):
    """量封面文字**笔画底下**的底够不够暗/够不够亮。

    ==== 为什么要有这一条 ====
    封面是全片唯一一处"文字压在没有为它留白的画面上"的地方：正文字幕有 measure 兜着，
    封面没有。而它恰恰是观众第一眼看到的东西。

    ==== 量法：文字掩膜，不是框一个矩形 ====
    拿**有字**和**无字**两张图逐像素比，差得多的就是文字覆盖的像素，再回到无字那张
    量这些位置的底。框矩形去量会被大片浅色稀释 —— 实测同一处矩形量出 94、掩膜量出 84，
    而真正决定看不看得清的是笔画底下那些像素。（《给蛾子盖的礼堂》英文封面上踩的）

    判据和正文字幕同一条：**离字色至少 50 级**，用 1%/99% 分位不用绝对极值。
    """
    def gray(p):
        return subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-vf", "format=gray",
                               "-frames:v", "1", "-f", "rawvideo", "-"],
                              capture_output=True).stdout
    a, b = gray(bare_png), gray(shot_png)
    if len(a) < W * H or len(b) < W * H:
        print("   (读不出帧，跳过封面对比度检查)"); return True
    dark_ink = (COVER_POLARITY or TITLE_POLARITY) == "dark_on_light"
    ink = 40 if dark_ink else 242
    under = sorted(a[i] for i in range(W * H) if abs(a[i] - b[i]) > 30)
    if len(under) < 200:
        print("   (几乎没量到文字像素，跳过)"); return True
    v = under[max(0, int(len(under) * 0.01))] if dark_ink \
        else under[min(len(under) - 1, int(len(under) * 0.99))]
    gap = abs(v - ink)
    print("   文字覆盖 %d 像素，底的%s分位 %d，离字色 %d 级 —— %s"
          % (len(under), "1%" if dark_ink else "99%", v, gap,
             "够用" if gap >= 50 else "**不够，换位置或收字号**"))
    if gap < 50:
        print("   注意：**先扫一遍再挪**。不够常常不是高度不对而是宽度太宽 ——")
        print("   一行字横出去两端压在暗处，中间那段其实是干净的。收字号比挪位置对。")
    return gap >= 50


def cover(lang=None):
    """封面。`cover en` 出英文那张（文件名后缀 _en）。

    双语片**每种语言各一张**，见 COVER_TEXT 上面那段。
    """
    lang = lang or DEFAULT_LANG
    if lang not in COVER_TEXT:
        sys.exit("!!! COVER_TEXT 里没有 %r —— 双语片每种语言都要写一份封面文案" % lang)
    t = COVER_TEXT[lang]
    ev = []
    for txt, fs, y in t["lines"]:
        ev.append("Dialogue: 0,0:00:00.00,0:00:10.00,CT,,0,0,0,,"
                  "{\\pos(%d,%d)\\fs%d}%s" % (W // 2, y, fs, txt))
    stxt, sfs, sy = t["sub"]
    ev.append("Dialogue: 0,0:00:00.00,0:00:10.00,CTS,,0,0,0,,"
              "{\\pos(%d,%d)\\fs%d}%s" % (W // 2, sy, sfs, stxt))
    with open("cover.ass", "w", encoding="utf-8-sig") as f:
        f.write("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\n"
                "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n" % (W, H)
                + styles_block() + "\n[Events]\nFormat: Layer,Start,End,Style,Name,"
                "MarginL,MarginR,MarginV,Effect,Text\n" + "\n".join(ev) + "\n")
    src = "img%02d.png" % COVER_FROM
    if not os.path.exists(src):
        sys.exit("!!! 缺 " + src + "，先跑 prep")
    out = os.path.join(out_dir(), COVER_NAME if lang == DEFAULT_LANG
                       else COVER_NAME.replace(".png", "_%s.png" % lang))
    base = "scale=%d:%d:flags=lanczos%s" % (W, H, "," + VIGNETTE if VIGNETTE else "")
    run(["ffmpeg", "-y", "-v", "error", "-i", src,
         "-vf", base + ",subtitles=cover.ass:fontsdir=%s" % FONTS.replace("\\", "/"),
         "-frames:v", "1", out], "封面(%s) -> %s" % (LANG_INFO[lang]["name"], out))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", base,
                    "-frames:v", "1", "_cover_bare.png"], capture_output=True)
    check_cover_text(out, "_cover_bare.png")
    if os.path.exists("_cover_bare.png"):
        os.remove("_cover_bare.png")
    print("   数值够了还要打开看一眼：标题很容易压在人脸或主体上，那是量不出来的。")
    if len(LANGS) > 1 and lang == DEFAULT_LANG:
        print("   **双语片记得再跑一次** `cover %s`。"
              % [l for l in LANGS if l != DEFAULT_LANG][0])
        print("   注意 YouTube 的多语言**不覆盖缩略图**（只有标题/简介/音轨/字幕），")
        print("   一个视频只有一张封面 —— 另一张是给别处用的（分享图、社媒）。")


def _measure_subs():
    """量每条字幕压着的底。

    **必须量无字的 master.mp4，不能量烧了字幕的 preview.mp4。**
    在烧过字的帧上框出字幕区求最小值，量到的是字本身，不是它压着的底 ——
    每条都会整整齐齐报同一个数，看起来像"条条都危险"，其实一条都没问题。

    起/中/止各量一次：摇镜会把字幕拖过明暗分界，只量中间那一帧会漏掉最差的时刻。
    跑完和 trace 逐条对：**对不上不是字幕的问题，是运镜没走在你以为的位置上**。

    ---- 但要先把 scrim 补回来 ----
    `master.mp4` 是 pass_b 的产物，**不含 scrim**（scrim 是 pass_c 才叠的）。
    直接量它，量到的是"没压过的底"，会比成片亮一截 ——
    实测 trace 报 166、measure 报 192，差 26 级，看起来像运镜错了，其实是
    两边建模的流水线又不一样了（给 trace 补了 scrim，却没给 measure 补）。

    scrim 和文字无关，所以可以放心地叠回来：抽帧之后 overlay 一次 scrim.png，
    量到的就是成片里字幕真正压着的那个底。这是 vignette / scrim 那条教训的第三只脚。
    """
    if not os.path.exists("master.mp4"):
        sys.exit("!!! 还没有 master.mp4，先跑 a + b")
    dark_ink = POLARITY == "dark_on_light"
    ink = 40 if dark_ink else 242
    has_scrim = make_scrim()

    def pct(v, p):      # 用 1% 分位不用绝对极值：一两个亮点就能把 min 拉到很低
        v = sorted(v)
        return v[max(0, min(len(v) - 1, int(len(v) * p)))]

    print("\n=== 字幕底实测（无字 master；每条 起 / 中 / 止）===")
    print("   每格 = 均值 / 1%分位 (极值)")
    if SUB_MODE != "burn":
        # 这一趟不因为外挂就作废：量的仍然是**画面底部那一带**的明暗，
        # 而播放器的字就落在那儿；同时它还是全流水线唯一一处能和 trace 对账、
        # 反过来自检运镜的地方（横版模板里这一段的说明写得更细）。
        print("   字幕外挂 —— 量的是播放器将要落字的那一带，判据放宽着看；")
        print("   这一趟真正不能丢的用途是**和 trace 对账**：对不上是运镜错了，不是字幕。")
    worst = []
    for st, en, txt, n, _, _ in timeline()[0]:
        x0, x1, y0, y1 = sub_box(txt)
        out = []
        for t in (st + 0.2, (st + en) / 2, max(st + 0.3, en - 0.2)):
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "%.2f" % t,
                            "-i", "master.mp4", "-frames:v", "1", "_m.png"],
                           capture_output=True)
            # 把 pass_c 才叠的 scrim 补回来，否则量到的是没压过的底
            args = ["ffmpeg", "-v", "error", "-i", "_m.png"]
            if has_scrim:
                args += ["-i", "scrim.png", "-filter_complex",
                         "[0:v][1:v]overlay=0:0:shortest=1,format=gray"]
            else:
                args += ["-vf", "format=gray"]
            b = subprocess.run(args + ["-f", "rawvideo", "-"], capture_output=True).stdout
            if len(b) < W * H:
                continue
            v = [b[y * W + x] for y in range(y0, y1) for x in range(x0, x1)]
            out.append((sum(v) / len(v), pct(v, 0.01) if dark_ink else pct(v, 0.99),
                        min(v) if dark_ink else max(v)))
        if not out:
            continue
        worst.append(min(o[1] for o in out) if dark_ink else max(o[1] for o in out))
        print("  镜%-3d %-22s " % (n, "".join(sub_lines(txt))[:11])
              + "  ".join("%3.0f/%3d(%3d)" % o for o in out))
    if os.path.exists("_m.png"):
        os.remove("_m.png")
    if not worst:
        return
    m = min(worst) if dark_ink else max(worst)
    print("\n  字幕色约 %d，最差处的底(1%%分位) %d，相差 %d 级 —— %s"
          % (ink, m, abs(m - ink), "够用（>=50）" if abs(m - ink) >= 50 else "不够，加 scrim"))
    print("  这只是数字，还要跑 still 用眼睛看：数值够但压在主体上是量不出来的。")


def _still_subs():
    """先整片烧低码率预览再抽帧。
    不能对 master 直接 "-ss T -i" 抽帧再烧字幕 —— -ss 在 -i 前会把 PTS 重置为 0，
    subtitles 滤镜按 PTS 找字幕，结果每张都去找 0 秒那一刻，一个字都渲染不出来。"""
    if not os.path.exists("master.mp4"):
        sys.exit("!!! 还没有 master.mp4，先跑 a + b")
    has_text = make_ass(); has = make_scrim(); os.makedirs("stills", exist_ok=True)
    ins = ["-i", "master.mp4"] + (["-loop", "1", "-i", "scrim.png"] if has else [])
    run(["ffmpeg", "-y", "-v", "error", "-stats"] + ins
        + ["-filter_complex", video_chain("[0:v]", has, grain=False, text=has_text),
           "-map", "[v]",
           "-c:v", "libx264", "-crf", "30", "-preset", "ultrafast",
           "-pix_fmt", "yuv420p", "-t", "%.3f" % total_len(), "preview.mp4"],
        "烧字幕预览" if SUB_MODE == "burn" else "预览（字幕外挂，画面上只有尾板）")
    lines = timeline()[0]
    for i, (st, en, txt, n, _, _) in enumerate(lines):
        t = (st + en) / 2
        run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % t, "-i", "preview.mp4",
             "-frames:v", "1", "stills/%02d_%.0fs.png" % (i, t)],
            "静帧 %.1fs  镜%d  %s" % (t, n, "".join(sub_lines(txt))[:14]))
    print("\n%d 张静帧在 stills/ —— 逐张打开看过再宣布完成" % len(lines))
    if SUB_MODE != "burn":
        print("字幕外挂，画面上没有字 —— 这一趟看的是**构图和落幅**，不是字幕压着什么。")


# ================= 竖版带过来的：安全区 / 字幕形态 / 片长硬线 / 拆音轨 =================


def check_mode():
    """字幕形态和语言数是**一对配置**，配错了没有任何症状。

    `SUB_MODE="burn"` + 两种语言 = 英文音轨带着满屏中文字播。文件能播、
    时长对、中文版一切正常 —— 而你手上放的正是中文版，所以自己永远发现不了。
    这是加竖版双语时唯一一个真正危险的配置，所以拦在这里。
    """
    bad = []
    if SUB_MODE not in ("burn", "srt"):
        bad.append("SUB_MODE=%r 不认识，只能是 'burn'（烧进画面）或 'srt'（外挂）" % SUB_MODE)
    if DEFAULT_LANG not in LANGS:
        bad.append("DEFAULT_LANG=%r 不在 LANGS=%r 里 —— 定时间轴的那条语言必须在场"
                   % (DEFAULT_LANG, LANGS))
    for l in LANGS:
        if l not in LANG_INFO:
            bad.append("LANGS 里的 %r 在 LANG_INFO 里没有登记" % l)
    if len(LANGS) > 1 and SUB_MODE != "srt":
        bad.append("配了 %d 种语言却还在烧字幕（SUB_MODE=%r）—— 烧进画面的%s字幕会"
                   "跟着别的语言那条轨一起播。要双语就把 SUB_MODE 改成 'srt'，"
                   "只发抖音/小红书就把 LANGS 收回 ['%s']"
                   % (len(LANGS), SUB_MODE, LANG_INFO[DEFAULT_LANG]["name"], DEFAULT_LANG))
    return bad


def check_safe():
    """**烧进画面的字**有没有撞进平台的操作栏 / 顶部导航 / 底部发布文案区。
    这类问题在成片文件里完全看不出来，只有把片子放进 App 才会发现 ——
    而那时图早就出完了。所以拿来当自检。

    `SUB_MODE="srt"` 时正文字幕由播放器渲染（播放器自己会避开自己的控件），
    这里就只剩尾板要判 —— **但这一条不是"关掉检查"**：尾板还是烧进画面的，
    照样能掉进操作栏里。

    横版（YouTube / 电视）没有这套操作栏，SAFE_RAIL 缺省是 None —— 不查。
    横版唯一要留意的是标题字卡别放到底部 y>1000（会被进度条压住），模板里已放在画心偏上。"""
    if SAFE_RAIL is None:
        return []
    rx0, ry0, rx1, ry1 = SAFE_RAIL
    bad = []

    def hit(name, x0, x1, y0, y1):     # 参数顺序跟 sub_box 一致：(x0, x1, y0, y1)
        if y0 < SAFE_TOP:
            bad.append("%s 顶端 %d 进了顶部导航区(<%d)" % (name, y0, SAFE_TOP))
        if y1 > SAFE_BOTTOM:
            bad.append("%s 底端 %d 进了底部发布文案区(>%d)，把 SUB_BOT 往上收"
                       % (name, y1, SAFE_BOTTOM))
        if x1 > rx0 and x0 < rx1 and y1 > ry0 and y0 < ry1:
            bad.append("%s 的框 x %d~%d / y %d~%d 压进右侧操作栏(x>=%d, y %d~%d)，"
                       "**收窄 SUB_MAX_W 或左移 SUB_CX**" % (name, x0, x1, y0, y1, rx0, ry0, ry1))

    if SUB_MODE == "burn":
        for _, _, txt, _, _, _ in timeline()[0]:
            hit("字幕『%s』" % txt, *sub_box(txt))
    if ENDCARD:
        hw = text_w(ENDCARD["head"]) / SUB_FS * 88
        hit("尾板标题", W // 2 - hw // 2, W // 2 + hw // 2,
            ENDCARD["y"] - 42, ENDCARD["y"] + 42)
    return bad


def selftest_safe():
    """回归：把字幕放回会撞的位置，检查必须报警。
    一个永远不报警的检查比没有检查更糟。

    **第一版的注入位置是 (CX=540, BOT=1500)，那是错的 —— 它依赖这一支的文案。**
    在那个位置撞操作栏的条件是 x1 = 540 + 宽/2 > 929，也就是**这一支恰好有一条
    宽度 > 778px 的字幕**。《下午三点的小人》把两条长句断行之后最宽只剩 700 出头，
    自测立刻报 0 条、打印「检查失效了」—— 而 check_safe 本身完全是好的。

    换句话说，**这个自测在任何字幕都不太长的片子上都不成立**，
    它自己就是它要防的那种"永远不报警的检查"。凡是写自测，都要问一句：
    它的触发条件里有没有混进这一支的内容。

    所以改成两个和文案无关的注入，每个只触发一条规则，缺一条都算失效：
      A 右移到 CX=900 —— 只要字幕非空，x1 必然越过操作栏左沿 929
      B 下压到 BOT=1700 —— 必然越过底部文案区上沿 SAFE_BOTTOM

    **外挂字幕时这两个注入都不成立** —— 正文字幕根本不在画面上，动 SUB_CX/SUB_BOT
    什么也不会发生，自测会一路报"检查失效了"。那不是检查坏了，是注入对象错了：
    那种模式下唯一烧进画面的是尾板，所以注入改成压尾板（上顶 / 下沉各一条）。
    连尾板都没有的片子是**画面上一个字都没有**，这时如实说"不适用"，
    不要让一个无从注入的自测冒充通过。
    """
    if SAFE_RAIL is None:
        print("回归自测: 没有平台安全区（SAFE_RAIL=None，横版）—— check_safe **不适用**")
        return True
    if SUB_MODE != "burn":
        if not ENDCARD:
            print("回归自测: 外挂字幕且没有尾板 —— 画面上一个字都没有，安全区检查**不适用**")
            return True
        keep_y = ENDCARD["y"]
        ENDCARD["y"] = 30                 # A：尾板顶进顶部导航区
        a = len(check_safe())
        ENDCARD["y"] = 1700               # B：尾板沉进底部发布文案区
        b = len(check_safe())
        ENDCARD["y"] = keep_y
        now = len(check_safe())
        print("回归自测: 注入A 尾板上顶撞导航(y=30) 报警 %d 条 —— %s"
              % (a, "对" if a else "**检查失效了**"))
        print("          注入B 尾板下沉撞文案区(y=1700) 报警 %d 条 —— %s"
              % (b, "对" if b else "**检查失效了**"))
        print("          当前位置(尾板 y=%d) 报警 %d 条 —— %s"
              % (keep_y, now, "对" if now == 0 else "还在撞"))
        print("          正文字幕外挂，由播放器渲染 —— 不在这条检查的范围里")
        return a > 0 and b > 0 and now == 0
    global SUB_CX, SUB_BOT
    kx, kb = SUB_CX, SUB_BOT
    SUB_CX, SUB_BOT = 900, 1500       # A：任何宽度的字幕都会压进右侧操作栏
    a = len(check_safe())
    SUB_CX, SUB_BOT = kx, 1700        # B：任何字幕都会掉进底部发布文案区
    b = len(check_safe())
    SUB_CX, SUB_BOT = kx, kb
    now = len(check_safe())
    print("回归自测: 注入A 右移撞操作栏(CX=900) 报警 %d 条 —— %s"
          % (a, "对" if a else "**检查失效了**"))
    print("          注入B 下压撞文案区(BOT=1700) 报警 %d 条 —— %s"
          % (b, "对" if b else "**检查失效了**"))
    print("          当前位置(CX=%d,BOT=%d) 报警 %d 条 —— %s"
          % (SUB_CX, SUB_BOT, now, "对" if now == 0 else "还在撞"))
    return a > 0 and b > 0 and now == 0


def vofit(target=None):
    """把成片压到硬上限以内 —— **靠拉伸旁白，不靠祈祷 TTS 说得快**。

    静默和转场是排定的，动它们就是动节奏；能安全动的只有语速。
    atempo 不变调，1.06 以内听不出来（语音上 1.08 开始有"赶"的感觉）。

    做法：量实测旁白总长 speech、静默总长 silence = total − speech，
    要压到 target 就要 speech2 = target − silence，倍率 = speech / speech2。

    **倍率超过 ATEMPO_MAX 时拒绝执行**，并换算成"还得砍多少汉字"。
    这一条很要紧：把 1.2 倍的活交给 atempo，等于用一个听得出来的毛病
    换一个看不出来的超时 —— 那不是修好，是藏起来。

    原件备份在 VO_RAW，每次都从备份重新推导，所以反复跑不会把拉伸叠上去。
    """
    durs_map, missing = vo_durs()
    if missing:
        sys.exit("!!! 还缺 %d 条旁白，vofit 要实测时长才能算" % len(missing))
    if target is None:
        if not HARD_LIMIT:
            sys.exit("!!! 没有 HARD_LIMIT，也没给目标片长")
        target = HARD_LIMIT - LIMIT_SAFETY

    total = total_len()
    speech = sum(durs_map[n["vo"]][0] for n in NARR)
    silence = total - speech
    print("")
    print("=== vofit ===")
    print("  现在   片长 %.1fs = 旁白 %.1fs + 静默与转场 %.1fs" % (total, speech, silence))
    print("  目标   片长 %.1fs%s" % (target,
          ("（硬线 %.0fs − 余量 %.1fs）" % (HARD_LIMIT, LIMIT_SAFETY)) if HARD_LIMIT else ""))
    # **先把原件的总长拿到手**，一切都按它算 —— 拉伸永远作用在 VO_RAW 上，
    # 所以分子必须也是原件。拿"已经拉过一次"的时长算倍率、再作用到原件上，
    # 第二次调整会走反方向：实测第二次目标 18.0s 反而从 18.6s 变成 18.8s，而且一声不吭。
    raw_speech = speech
    if os.path.isdir(VO_RAW):
        raw_speech = 0.0
        for n in NARR:
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                "format=duration", "-of", "csv=p=0",
                                os.path.join(VO_RAW, os.path.basename(vo_path(n)))],
                               capture_output=True, text=True)
            raw_speech += float(r.stdout.strip())
        if abs(raw_speech - speech) > 0.05:
            print("  原件   旁白 %.1fs（现在这版是拉伸过的，倍率一律按原件算）" % raw_speech)

    # 原速就装得下 —— 把上一轮的拉伸放回去，不要让它永远留着。
    # （这一条让 vofit 收敛到"刚好够的倍率"，而不是"历史上最紧的那一次"。）
    if silence + raw_speech <= target + 1e-6:
        if os.path.isdir(VO_RAW) and abs(raw_speech - speech) > 0.05:
            for n in NARR:
                dst = vo_path(n)
                run(["ffmpeg", "-y", "-v", "error", "-i",
                     os.path.join(VO_RAW, os.path.basename(dst)), "-c", "copy", dst],
                    "还原 " + n["vo"])
            global _VO
            _VO = {}
            print("  原速就在目标以内 —— 已放回原速，片长 %.1fs" % total_len())
        else:
            print("  已经在目标以内，不用动。")
        return True

    want = target - silence
    if want <= 0:
        sys.exit("!!! 光静默和转场就有 %.1fs，已经超过目标 %.1fs —— 拉伸救不了，"
                 "要减镜数或缩转场" % (silence, target))

    factor = raw_speech / want
    chars = sum(n_chars(n["txt"]) for n in NARR)
    rate = chars / raw_speech
    if factor > ATEMPO_MAX:
        saved = raw_speech - (raw_speech / ATEMPO_MAX)
        short = (silence + raw_speech - target) - saved
        print("  !! 要 %.3f 倍才压得进 %.1fs，超过 ATEMPO_MAX=%.2f" % (factor, target, ATEMPO_MAX))
        print("     拉到 %.2f 倍最多省 %.1fs，还差 %.1fs" % (ATEMPO_MAX, saved, short))
        print("     按本批实测语速 %.2f 字/秒，**还得砍掉约 %d 个汉字**"
              % (rate, int(-(-short * rate // 1))))
        sys.exit("     别把这活交给 atempo：听得出来的毛病换看不出来的超时，不是修好。")

    if not os.path.isdir(VO_RAW):
        os.makedirs(VO_RAW)
        for n in NARR:
            src = vo_path(n)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-c", "copy",
                            os.path.join(VO_RAW, os.path.basename(src))], check=True)
        print("  原件已备份到 %s/（以后每次都从这里重新推导）" % VO_RAW)

    print("  倍率 %.3f（上限 %.2f）—— 逐条拉伸，不变调" % (factor, ATEMPO_MAX))
    for n in NARR:
        dst = vo_path(n)
        raw = os.path.join(VO_RAW, os.path.basename(dst))
        run(["ffmpeg", "-y", "-v", "error", "-i", raw,
             "-filter:a", "atempo=%.6f" % factor, "-q:a", "2", dst],
            "拉伸 " + n["vo"])
    _VO = {}
    print("  拉伸后 片长 %.1fs（语速 %.2f -> %.2f 字/秒）"
          % (total_len(), chars / raw_speech, chars / raw_speech * factor))
    if len(LANGS) > 1:
        # 槽是中文定的，中文被整体拉快，所有的槽就都变短了 —— 上一次 langfit
        # 的结果**全部作废**，而这件事不报错：英文文件还在、长度也没变，
        # 只是它们现在长出槽去了。check 会从磁盘重量一遍拦住，这里先提醒一句。
        print("  **中文的槽变了 —— 再跑一遍 `langfit`**，%s 那几条是按旧槽压的。"
              % " / ".join(LANG_INFO[l]["name"] for l in LANGS if l != DEFAULT_LANG))
    return True


def split_tracks(multi):
    """把多音轨成片拆成**可上传的形态**。全部流拷贝，不重编码。

    **为什么不能直接传多音轨文件**：YouTube 只认上传件里的第一条/默认音轨，
    其余的会被丢掉；附加语言必须在 Studio 里作为独立音频文件添加。
    不拆的后果是不报错的 —— 传上去能播、时长对、中文轨也对，只有英文轨没了。

    返回 (上传件, [(语言码, 音频文件), ...])。

    只有**不分段**的片子在这里拆。分段的由 join.py 拆 —— 每段都拆一遍是纯浪费，
    那些产物 join 之后一个都用不上（2026-09-09 用户提的）。
    """
    base = out_base()
    upload = os.path.join(out_dir(), "%s.mp4" % base)
    # 上传件那条轨按 DEFAULT_LANG 的**位置**取，不写死 0:a:0 ——
    # 两份手抄时代都假定默认语言排第一，LANGS 换个顺序上传件就是英文的，而且不报错。
    d = LANGS.index(DEFAULT_LANG)
    run(["ffmpeg", "-y", "-v", "error", "-i", multi,
         "-map", "0:v:0", "-map", "0:a:%d" % d, "-c", "copy",
         "-movflags", "+faststart", upload],
        "上传件：视频 + %s 一条音轨（流拷贝）-> %s"
        % (LANG_INFO[DEFAULT_LANG]["name"], upload))
    na = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                         "-show_entries", "stream=index", "-of", "csv=p=0", upload],
                        capture_output=True, text=True).stdout.split()
    if len(na) != 1:
        sys.exit("!!! 上传件里有 %d 条音轨，应该只有 1 条" % len(na))
    vdur = None
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", upload], capture_output=True, text=True)
    try:
        vdur = float(r.stdout.strip())
    except ValueError:
        pass
    auds = []
    for j, lang in enumerate(LANGS):
        if lang == DEFAULT_LANG:
            continue
        code = LANG_INFO[lang]["code"]
        out = os.path.join(out_dir(), "%s_音轨_%s.m4a" % (base, code))
        run(["ffmpeg", "-y", "-v", "error", "-i", multi,
             "-map", "0:a:%d" % j, "-c:a", "copy", out],
            "独立音频（%s）-> %s" % (code, out))
        # 独立音频和画面差一点点就是整条错位，而这在文件里看不出来 —— 所以量一次
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", out], capture_output=True, text=True)
        try:
            adur = float(r.stdout.strip())
        except ValueError:
            adur = None
        if vdur and adur and abs(adur - vdur) > 0.05:
            sys.exit("!!! %s 长 %.3fs，画面 %.3fs，差 %.3fs —— 加到 Studio 里会整条错位"
                     % (out, adur, vdur, adur - vdur))
        auds.append((code, out))
    return upload, auds


def out_base():
    """交付物文件名的主干 —— 成片、字幕、独立音频、留档件都从它派生。
    横版原来叫 SEG_NAME、竖版原来从 OUT_NAME 去扩展名，合并后统一是 SEG_NAME。"""
    return SEG_NAME


# ================= 按字幕形态分派：量什么、抽什么 =================
def measure():
    """成片上实测，和 trace 的预测逐条对 —— **全流水线唯一能自检运镜落点的地方**
    （`motion` 只能证明画面动了，证明不了它动到了哪儿）。

    烧录字幕：量每条字幕压着的底（`_measure_subs`），同时判离字色够不够 50 级。
    外挂字幕：字幕框没有了，改量 PROBE_BOXES 三块固定取样框（`_measure_probes`），
              读 trace_pred.json 逐条对账。**关判据不等于关测量。**

    对不上时先怀疑建模不一致（pass_a / pass_c 加了一道 trace 没补的滤镜：
    vignette、scrim、淡场都踩过），再怀疑运镜。
    """
    return _measure_subs() if SUB_MODE == "burn" else _measure_probes()


def still():
    """抽静帧用眼睛看。

    烧录字幕：一条字幕抽一张（`_still_subs`）—— 要验的是字压在什么底上。
    外挂字幕：每镜抽起/中/尾三帧（`_still_shots`）—— 画面上没有正文字幕，要验的是
              构图、镜头走了多远、落幅停在哪儿。这两件都是量不出来、只能看的。

    两路都先烧一版低码率预览再抽帧，不对 master 直接 "-ss T -i"：-ss 在 -i 前会把
    PTS 重置为 0，subtitles 滤镜按 PTS 找事件，烧进画面的字会一个都渲不出来。
    """
    return _still_subs() if SUB_MODE == "burn" else _still_shots()


# ================= 命令行 =================
def main():
    if len(sys.argv) < 2:
        # 不带参数**不再等于 all**：2026-09-21 误跑过一次，整条流水线从 prep 重来，
        # 打断之后 shots/ 里留下哑弹。all 要明说。
        sys.exit("用法: python %s <命令>\n"
                 "  流水线  sync -> check -> prep -> a -> b -> c    （all = prep+a+b+c）\n"
                 "  a 只补过期的镜；`a force` 全部重渲；`a 1` 串行（默认 %d 路并行）\n"
                 "  有片长硬线（HARD_LIMIT）时配音齐了先跑 vofit，再 langfit"
                 % (os.path.basename(sys.argv[0]), JOBS))
    what = sys.argv[1]
    if what == "vofit":
        vofit(float(sys.argv[2]) if len(sys.argv) > 2 else None)
        sys.exit(0)
    # `preview` 和 `budget` 都必须在**没有图**的时候跑得起来 —— 那正是它们的位置。
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    if what in ("sync", "prep", "probe", "trace", "still", "measure", "cover",
                "pick", "motion", "pixels", "mquality", "credits", "budget",
                "srt", "preview", "gates", "langfit"):
        if what == "langfit":
            # 逐句把别的语言压进中文的槽。压不进去的会报出还得砍几个词。
            sys.exit(0 if langfit(arg or "en") else 1)
        if what == "cover":
            cover(arg)                         # `cover en` 出英文封面（双语片两张都要）
        elif what == "preview":
            preview(arg)                       # `preview en` 单听英文那条
        elif what == "srt":
            if SUB_MODE == "burn":
                sys.exit("!!! SUB_MODE='burn' —— 这一支的字幕是烧进画面的，没有 SRT。"
                         "要外挂字幕就把 SUB_MODE 改成 'srt' 再重跑 `c`")
            for l in LANGS:
                make_srt(l)                    # 每种语言各一份
        else:
            {"sync": sync, "prep": prep, "probe": probe, "trace": trace, "still": still,
             "measure": measure, "pick": pick_music_in,
             "motion": motion, "pixels": pixels,
             "mquality": mquality, "credits": credits, "budget": budget,
             "gates": check_gates}[what]()
        sys.exit(0)
    ok = check_timeline()
    if what == "check":
        sys.exit(0 if ok else 1)
    if not ok:
        sys.exit("!!! 自检没过，先修上面的问题")
    if what in ("a", "all"):
        if what == "all":
            prep()
        rest = sys.argv[2:]
        pass_a(jobs=next((int(x) for x in rest if x.isdigit()), None), force="force" in rest)
    if what in ("b", "all"):
        pass_b()
    if what in ("c", "all"):
        pass_c()
