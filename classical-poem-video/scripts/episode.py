# -*- coding: utf-8 -*-
"""一支片子的三件杂事。都**只看文件**，不 import、不 exec 引擎和配置，所以不走引擎的片子也能用。

    python episode.py new <项目目录> --type short|long [--title 片名]
    python episode.py status <项目目录>
    python episode.py deliver <项目目录> [--video 成片.mp4] [--type short|long] [--mono] [-v]

new      建 <项目>/build/ 和 素材/，从本脚本所在的 scripts/ 复制模板、引擎和常用工具；
         Short 另放一份 segment_config.py 预设（presets/）；生成讲述稿 / 查证记录 / 素材处理说明的骨架；
         记下引擎的提交号。**已有的文件一个都不覆盖。**
status   二十行左右：稿子、门禁、旁白、素材、中间件、交付物各到哪一步了。接手一支片先跑它。
deliver  交付前能用机器验的那些：封装、响度、片长、字幕、英文轨、封面、发布文案、章节时间码、门禁。
         **只打印没过的**，`-v` 连通过的一起打印；全过退出码 0。
         人才判得了的（好不好听、画面对不对）还在 references/checklist.md。

status / deliver 量时长和响度要 ffmpeg、ffprobe 在 PATH 上。
"""
import ast
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
AUD_EXT = (".mp3", ".wav", ".m4a")
# 这些名字的 mp4 不是上传件：留档件、检查片、段用文件、草稿
SKIP_VIDEO = re.compile(r"多音轨|预览|預覽|检查|檢查|草稿|分部|段用|480p|_tmp|check", re.I)
COMMON = ["story_core.py", "vo_trim.py", "publish.py", "runlog.py", "chatcut_dl.py", "narr_build.py",
          "comfy_gen.py", "el_web_image.py", "el_web_image.js", "upscale.py"]
BY_TYPE = {"short": ["make_story_v.py"], "long": ["make_story_h.py", "join.py"]}
SIZE = {"short": (1080, 1920), "long": (1920, 1080)}
COVER_MAX = 2 * 1024 * 1024          # YouTube 缩略图上限 2MB
LUFS_TARGET, LUFS_TOL = -15.0, 1.0   # 平台标准 −14~−16


# ---------------- 读文件的小工具 ----------------
def load_config(path):
    """从 segment_config.py 里捞**字面量**赋值（ast，不执行）。算出来的值（循环里拼的 SHOTS 之类）拿不到，也不需要。"""
    out = {}
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except (OSError, SyntaxError):
        return out
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        try:
            val = ast.literal_eval(node.value)
        except Exception:
            continue
        tgt = node.targets[0]
        if isinstance(tgt, ast.Name):
            out[tgt.id] = val
        elif isinstance(tgt, ast.Tuple) and isinstance(val, tuple) and len(tgt.elts) == len(val):
            for e, v in zip(tgt.elts, val):
                if isinstance(e, ast.Name):
                    out[e.id] = v
    return out


def find_configs(proj):
    """项目里的 segment_config.py：不分段的在 build/，分段的一段一个目录。"""
    hits = sorted(set(glob.glob(os.path.join(proj, "*", "segment_config.py"))))
    return [(os.path.dirname(p), load_config(p)) for p in hits]


def media(path):
    """(时长, streams)；读不了返回 (None, [])。"""
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        j = json.loads(p.stdout or "{}")
        return float(j["format"]["duration"]), j.get("streams", [])
    except (OSError, ValueError, KeyError):
        return None, []


def lufs(path):
    """整体响度，和引擎的 integrated_lufs 同一种量法。"""
    try:
        p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-map", "0:a:0", "-af",
                            "loudnorm=print_format=json", "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        return float(json.loads(p.stderr[p.stderr.rfind("{"):p.stderr.rfind("}") + 1])["input_i"])
    except (OSError, ValueError, KeyError):
        return None


def find_videos(proj):
    """候选上传件：项目根和 成片/ 里的 mp4，去掉留档件、检查片、草稿。新的在前。"""
    c = []
    for d in (proj, os.path.join(proj, "成片")):
        for p in glob.glob(os.path.join(d, "*.mp4")):
            n = os.path.basename(p)
            if not n.startswith("_") and not SKIP_VIDEO.search(n):
                c.append(p)
    return sorted(c, key=os.path.getmtime, reverse=True)


def sidecars(video):
    """成片旁边的中文字幕、英文字幕、英文音轨。找不到的是 None。"""
    stem, d = os.path.splitext(video)[0], os.path.dirname(video)
    def first(cands):
        return next((p for p in cands if os.path.isfile(p)), None)
    zh = first([stem + ".srt", stem + ".zh.srt"])
    en = first([stem + ".en.srt", stem + "_en.srt", stem + ".eng.srt"]
               + [p for p in glob.glob(os.path.join(d, "*.srt")) if re.search(r"(?i)[._](en|eng)\.srt$", p)])
    au = first([stem + "_音轨_eng.m4a"]
               + [p for p in glob.glob(os.path.join(d, "*.m4a")) if re.search(r"(?i)eng|英文|[._]en[._]", os.path.basename(p))])
    return zh, en, au


TS = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{3})")


def srt_info(path):
    """(条数, 最后一条的结束秒)。"""
    try:
        t = open(path, encoding="utf-8-sig", errors="replace").read()
    except OSError:
        return 0, 0.0
    m = TS.findall(t)
    if not m:
        return 0, 0.0
    h, mi, s, ms = (int(x) for x in m[-1][4:])
    return len(m), h * 3600 + mi * 60 + s + ms / 1000.0


def covers(proj):
    out = []
    for d in (proj, os.path.join(proj, "成片"), os.path.join(proj, "封面")):
        out += [p for p in glob.glob(os.path.join(d, "*")) if "封面" in os.path.basename(p)
                and p.lower().endswith(IMG_EXT)]
    return sorted(set(out))


def chapter_runs(text):
    """简介里的章节时间码，按「时间又从头开始」切成几组（中文简介一组、英文简介一组）。"""
    runs, cur = [], []
    for m in re.finditer(r"(?m)^\s*[-*]?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s+\S", text):
        a, b, c = m.group(1), m.group(2), m.group(3)
        t = int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b)
        if cur and t <= cur[-1]:
            runs.append(cur); cur = []
        cur.append(t)
    if cur:
        runs.append(cur)
    return runs


def is_library_root(d):
    """底下有两个以上带 素材/ 或 build/ 的子目录 —— 这是片库根，不是一支片子。"""
    n = 0
    for s in os.listdir(d) if os.path.isdir(d) else []:
        p = os.path.join(d, s)
        if os.path.isdir(os.path.join(p, "素材")) or os.path.isdir(os.path.join(p, "build")):
            n += 1
    return n >= 2


def vo_have(cfgdir, cfg, sub):
    """NARR 里点到的旁白，在 <cfgdir>/<sub>/ 里到了几条。返回 (到了, 总数, 缺的)。"""
    want = [n["vo"] for n in cfg.get("NARR", []) if isinstance(n, dict) and "vo" in n]
    miss = []
    for v in want:
        base = os.path.splitext(v)[0] if v.lower().endswith(AUD_EXT) else v
        if not any(os.path.isfile(os.path.join(cfgdir, sub, base + e)) for e in AUD_EXT):
            miss.append(base)
    return len(want) - len(miss), len(want), miss


def clips_have(proj, cfg):
    want = []
    for c in cfg.get("CLIPS", []):
        if isinstance(c, dict):
            want += [c[k] for k in ("src", "video") if isinstance(c.get(k), str)]
    want = sorted(set(want))
    miss = [w for w in want if not os.path.isfile(os.path.join(proj, "素材", w))]
    return len(want) - len(miss), len(want), miss


def short_list(xs, n=4):
    return "、".join(xs[:n]) + ("…等 %d 个" % len(xs) if len(xs) > n else "")


# ---------------- new ----------------
DOCS = {
    "讲述稿.md": "# {title}\n\n> 片型：{kind}。写完交给用户读一遍（门禁一），签字写进 build/segment_config.py 的 GATE_SCRIPT_OK。\n"
                 "> 做法见 references/{fmt}。\n\n| 句号 | 旁白 | 画面 |\n|---|---|---|\n\n## 来源与待核\n",
    "查证记录.md": "# {title}：查证记录\n\n> 越具体越要查。只认论文、专著、机构页、原始文献；查不到的写进「存疑」，不进稿子。\n\n"
                   "## 来源\n\n## 事实（说法｜出处｜级别）\n\n## 存疑 / 没查到\n\n## 不能说的\n",
    "素材处理说明.md": "# {title}：素材处理说明\n\n> 手写。`素材来源.md` 由 `credits` 自动生成、会被重写，处理过程写在这里。\n\n"
                       "## 这一支的三条轴\n\n- 运镜：\n- 配乐：\n- 图从哪儿来：\n\n## 逐镜处理\n\n## 妥协与留的口子\n",
}


def cmd_new(proj, kind, title):
    proj = os.path.abspath(proj)
    if is_library_root(proj):
        sys.exit("!!! %s 看起来是片库根（底下有两个以上带 素材/ 或 build/ 的子目录）。给一个新的子目录。" % proj)
    title = title or os.path.basename(proj)
    build = os.path.join(proj, "build")
    for d in (build, os.path.join(proj, "素材", "生成"), os.path.join(proj, "素材", "实物")):
        os.makedirs(d, exist_ok=True)
    made, kept = [], []

    def put(dst, write):
        if os.path.exists(dst):
            kept.append(os.path.relpath(dst, proj)); return
        write(dst); made.append(os.path.relpath(dst, proj))

    for f in COMMON + BY_TYPE[kind]:
        src = os.path.join(HERE, f)
        if os.path.isfile(src):
            put(os.path.join(build, f), lambda d, s=src: shutil.copyfile(s, d))
    if os.path.isdir(os.path.join(HERE, "comfy")):
        put(os.path.join(build, "comfy"), lambda d: shutil.copytree(os.path.join(HERE, "comfy"), d))
    preset = os.path.join(HERE, "presets", "segment_config_%s.py" % ("short_v2" if kind == "short" else "long"))
    if os.path.isfile(preset):
        text = open(preset, encoding="utf-8").read().replace("__TITLE__", title)
        put(os.path.join(build, "segment_config.py"),
            lambda d: open(d, "w", encoding="utf-8", newline="\n").write(text))
    fmt = "format-short-v2.md" if kind == "short" else "format-long-chapters.md"
    for name, body in DOCS.items():
        text = body.format(title=title, kind="Short（竖版）" if kind == "short" else "横版长片", fmt=fmt)
        put(os.path.join(proj, name), lambda d, t=text: open(d, "w", encoding="utf-8", newline="\n").write(t))
    try:
        rev = subprocess.run(["git", "-C", HERE, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True).stdout.strip() or "unknown"
    except OSError:
        rev = "unknown"
    put(os.path.join(build, "ENGINE_COMMIT.txt"),
        lambda d: open(d, "w", encoding="utf-8", newline="\n").write(
            "%s  %s  type=%s\n" % (rev, datetime.date.today().isoformat(), kind)))
    print("新建 %d 个：%s" % (len(made), short_list(made, 30)))
    if kept:
        print("已存在、没动 %d 个：%s" % (len(kept), short_list(kept, 8)))
    if kind == "long":
        print("长片没有 segment_config 预设：章节卡、档案页、路线图这些成镜目前每支各写各的，"
              "规矩和两条现成的路见 references/format-long-chapters.md")
    print("下一步：写 查证记录.md → 讲述稿.md → 门禁一。做法见 references/%s" % fmt)


# ---------------- status ----------------
def cmd_status(proj):
    proj = os.path.abspath(proj)
    if not os.path.isdir(proj):
        sys.exit("!!! 没有这个目录：%s" % proj)
    cfgs = find_configs(proj)
    nxt = []
    title = next((c.get("TITLE") for _, c in cfgs if c.get("TITLE")), None) or os.path.basename(proj)
    rev = os.path.join(proj, "build", "ENGINE_COMMIT.txt")
    print("《%s》  %s%s" % (title, proj, "  引擎 " + open(rev, encoding="utf-8").read().split()[0]
                           if os.path.isfile(rev) else ""))

    docs = sorted(glob.glob(os.path.join(proj, "讲述稿*.md")), key=os.path.getmtime, reverse=True)
    docs = [p for p in docs if not re.search(r"(?i)_en\.md$", p)] or docs      # 英文稿不算「最新的稿子」
    def stamp(p):
        return datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%m-%d %H:%M")
    print("稿子    %s；查证记录 %s" % (
        ("%s（%s，共 %d 份）" % (os.path.basename(docs[0]), stamp(docs[0]), len(docs))) if docs else "没有讲述稿",
        "有" if os.path.isfile(os.path.join(proj, "查证记录.md")) else "没有"))
    if not docs:
        nxt.append("写讲述稿")

    if not cfgs:
        print("配置    没有 segment_config.py（这一支不走引擎，或还没开工）")
    for d, c in cfgs:
        tag = os.path.relpath(d, proj)
        g1, g2 = str(c.get("GATE_SCRIPT_OK", "")).strip(), str(c.get("GATE_PREVIEW_OK", "")).strip()
        print("[%s] 门禁一 %s；门禁二 %s" % (tag, ("已签：" + g1[:36]) if g1 else "未签",
                                           ("已签：" + g2[:36]) if g2 else "未签"))
        if not g1:
            nxt.append("门禁一（%s）" % tag)
        langs = c.get("LANGS") or ["zh"]
        parts = []
        for lg in langs:
            sub = c.get("VO_DIR", "vo") if lg == langs[0] else "%s_%s" % (c.get("VO_DIR", "vo"), lg)
            have, tot, miss = vo_have(d, c, sub)
            parts.append("%s %d/%d%s" % (lg, have, tot, ("（缺 %s）" % short_list(miss)) if miss else ""))
            if tot and miss:
                nxt.append("补旁白 %s（%s）" % (lg, tag))
        print("        旁白 %s" % "，".join(parts))
        have, tot, miss = clips_have(proj, c)
        print("        素材 %d/%d%s" % (have, tot, ("（缺 %s）" % short_list(miss, 3)) if miss else ""))
        if tot == 0:
            nxt.append("填 CLIPS（%s）" % tag)
        elif miss:
            nxt.append("补素材（%s）" % tag)
        imgs = len([p for p in os.listdir(d) if re.match(r"img\d+\.(png|jpg)$", p)])
        shots = len(glob.glob(os.path.join(d, "shots", "shot*.mp4")))
        print("        中间件 img %d，shots %d，master %s" % (
            imgs, shots, "有" if os.path.isfile(os.path.join(d, "master.mp4")) else "没有"))

    gen = os.path.join(proj, "素材")
    if os.path.isdir(gen):
        subs = []
        for s in sorted(os.listdir(gen)):
            p = os.path.join(gen, s)
            if os.path.isdir(p):
                subs.append("%s %d" % (s, sum(len(fs) for _, _, fs in os.walk(p))))
        print("素材/   %s" % ("，".join(subs) if subs else "空"))

    vids = find_videos(proj)
    if not vids:
        print("成片    没有")
        nxt.append("出片")
    for v in vids[:3]:
        dur, st = media(v)
        zh, en, au = sidecars(v)
        vs = next((s for s in st if s.get("codec_type") == "video"), {})
        print("成片    %s  %s  %sx%s  %s  字幕 %s%s  英文轨 %s" % (
            os.path.relpath(v, proj), ("%.1fs" % dur) if dur else "读不了", vs.get("width", "?"),
            vs.get("height", "?"), stamp(v), "中" if zh else "无", "英" if en else "", "有" if au else "无"))
    if len(vids) > 3:
        print("        …另有 %d 个 mp4 候选" % (len(vids) - 3))
    cv = covers(proj)
    pub = os.path.isfile(os.path.join(proj, "发布文案.md"))
    print("交付    封面 %d 张；发布文案 %s；素材来源 %s" % (
        len(cv), "有" if pub else "没有", "有" if os.path.isfile(os.path.join(proj, "素材来源.md")) else "没有"))
    if vids and not cv:
        nxt.append("出封面")
    if vids and not pub:
        nxt.append("写发布文案")
    if vids and cv and pub and not nxt:
        nxt.append("跑 episode.py deliver，过了交给用户看片 / 上传")
    print("下一步（按缺什么推的，不是结论）：%s" % ("；".join(nxt[:4]) if nxt else "看不出来"))


# ---------------- deliver ----------------
def cmd_deliver(proj, video, kind, mono, verbose):
    proj = os.path.abspath(proj)
    res = []                                    # (级别, 项, 说明)；级别：ok / FAIL / 提醒

    def add(ok, key, good, bad):
        res.append(("ok" if ok else "FAIL", key, good if ok else bad))

    vids = [os.path.abspath(video)] if video else find_videos(proj)
    if not vids or not os.path.isfile(vids[0]):
        print("FAIL [成片] 找不到上传件（项目根或 成片/ 里的 mp4；留档件、检查片不算）。用 --video 指定。")
        sys.exit(1)
    v = vids[0]
    if len(vids) > 1:
        res.append(("提醒", "成片", "有 %d 个候选，验的是最新的 %s；不对就用 --video 指定" % (len(vids), os.path.basename(v))))
    dur, st = media(v)
    vs = [s for s in st if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") != 1]
    au = [s for s in st if s.get("codec_type") == "audio"]
    w, h = (vs[0].get("width"), vs[0].get("height")) if vs else (None, None)
    if not kind and w and h:
        kind = "short" if h > w else "long"

    add(bool(vs) and vs[0].get("codec_name") == "h264", "封装", "视频 H.264",
        "视频不是 H.264（%s）" % (vs[0].get("codec_name") if vs else "没有视频流"))
    add(len(au) == 1, "封装", "上传件单音轨",
        "上传件有 %d 条音轨 —— 多音轨文件直接传，附加语言会被静默丢掉；上传件只留中文一条" % len(au))
    if au:
        a = au[0]
        good = a.get("codec_name") == "aac" and str(a.get("sample_rate")) == "48000" and a.get("channels") == 2
        add(good, "封装", "音频 AAC 48k 立体声",
            "音频是 %s / %s Hz / %s 声道，要 AAC / 48000 / 2" % (a.get("codec_name"), a.get("sample_rate"), a.get("channels")))
    if kind in SIZE:
        add((w, h) == SIZE[kind], "封装", "画面 %dx%d" % SIZE[kind], "画面 %sx%s，%s 要 %dx%d" % ((w, h, kind) + SIZE[kind]))
    if kind == "short":
        add(dur is not None and dur <= 180.0, "片长", "%.1fs ≤ 180s" % (dur or 0),
            "%.1fs，超过 Shorts 的 180s 硬线" % (dur or 0))
    i = lufs(v)
    add(i is not None and abs(i - LUFS_TARGET) <= LUFS_TOL, "响度", "%.1f LUFS" % (i or 0),
        ("%.1f LUFS，要 %.0f±%.0f" % (i, LUFS_TARGET, LUFS_TOL)) if i is not None else "量不出响度")

    zh, en, eng = sidecars(v)
    for key, p, need in (("字幕zh", zh, True), ("字幕en", en, not mono)):
        if not need:
            continue
        if not p:
            add(False, key, "", "成片旁边没有这份 SRT"); continue
        n, end = srt_info(p)
        add(n > 0 and dur is not None and end <= dur + 0.5, key, "%d 条，收在 %.1fs" % (n, end),
            "%s：%d 条，最后一条收在 %.1fs，片长 %.1fs" % (os.path.basename(p), n, end, dur or 0))
    if not mono:
        if not eng:
            add(False, "英文轨", "", "成片旁边没有独立的英文音频（*_音轨_eng.m4a）；只做中文就加 --mono")
        else:
            d2, _ = media(eng)
            add(d2 is not None and dur is not None and abs(d2 - dur) <= 1.0, "英文轨", "%.1fs，和画面等长" % (d2 or 0),
                "%s 长 %.1fs，画面 %.1fs，差了 %.1fs" % (os.path.basename(eng), d2 or 0, dur or 0, abs((d2 or 0) - (dur or 0))))

    cv = covers(proj)
    small = [p for p in cv if os.path.getsize(p) <= COVER_MAX]
    add(bool(small), "封面", "%d 张，%d 张在 2MB 以内" % (len(cv), len(small)),
        "没有封面" if not cv else "封面都超过 2MB（YouTube 上限），另存一张 jpg")
    if kind == "long" and not mono and cv:
        add(any(re.search(r"(?i)en|英", os.path.splitext(os.path.basename(p))[0].replace("封面", "")) for p in cv),
            "封面", "有英文封面", "长片每种语言各一张封面，没找到英文那张（文件名带 en）")

    cfgs = find_configs(proj)
    pub = os.path.join(proj, "发布文案.md")
    if not os.path.isfile(pub):
        add(False, "发布文案", "", "没有 发布文案.md —— 它是交付物")
    else:
        text = open(pub, encoding="utf-8", errors="replace").read()
        found = any(c.get("CREDITS") for _, c in cfgs)
        chk = os.path.join(HERE, "publish.py")
        if os.path.isfile(chk):
            r = subprocess.run([sys.executable, chk, "check", pub] + (["--mono"] if mono else [])
                               + (["--found"] if found else []),
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            tail = " / ".join(l.strip() for l in (r.stdout + r.stderr).splitlines() if l.strip())[-300:]
            add(r.returncode == 0, "发布文案", "publish.py check 通过", "publish.py check 没过：…%s" % tail)
        if kind == "long":
            runs = chapter_runs(text)
            good = bool(runs) and all(
                len(r) >= 3 and r[0] == 0 and all(b - a >= 10 for a, b in zip(r, r[1:]))
                and (dur is None or r[-1] < dur) for r in runs)
            add(good, "章节", "章节时间码 %s 组，各 %s 条" % (len(runs), "/".join(str(len(r)) for r in runs)),
                "简介里的章节时间码不合规：要从 0:00 起、至少 3 条、每段 ≥10 秒、不超过片长（现在 %s）"
                % (["%d 条，起于 %ds" % (len(r), r[0]) for r in runs] or "一条都没有"))
    need_credit = any(c.get("CREDITS") or c.get("MUSIC_MODE") == "public_domain" for _, c in cfgs)
    if need_credit:
        add(os.path.isfile(os.path.join(proj, "素材来源.md")), "素材来源", "有 素材来源.md",
            "用了找来的素材，却没有 素材来源.md —— 跑 credits 导出，署名要跟着片子走")
    for d, c in cfgs:
        for k, name in (("GATE_SCRIPT_OK", "门禁一"), ("GATE_PREVIEW_OK", "门禁二")):
            add(bool(str(c.get(k, "")).strip()), "门禁", "%s 已签（%s）" % (name, os.path.relpath(d, proj)),
                "%s 没签字（%s 的 %s 是空的）" % (name, os.path.relpath(d, proj), k))

    fails = [r for r in res if r[0] == "FAIL"]
    for lv, key, msg in res:
        if lv != "ok" or verbose:
            print("%-4s [%s] %s" % (lv, key, msg))
    print("%s：%s，%d 项里 %d 项没过。人判的那些看 references/checklist.md。" % (
        "没过" if fails else "机器能验的都过了", os.path.relpath(v, proj), len([r for r in res if r[0] != "提醒"]), len(fails)))
    sys.exit(1 if fails else 0)


def main(argv):
    if len(argv) < 2 or argv[0] not in ("new", "status", "deliver"):
        sys.exit(__doc__)
    what, proj, rest = argv[0], argv[1], argv[2:]

    def opt(name):
        return rest[rest.index(name) + 1] if name in rest and rest.index(name) + 1 < len(rest) else None
    kind = opt("--type")
    if kind and kind not in SIZE:
        sys.exit("--type 只有 short / long")
    if what == "new":
        if not kind:
            sys.exit("new 要写明 --type short 或 --type long")
        cmd_new(proj, kind, opt("--title"))
    elif what == "status":
        cmd_status(proj)
    else:
        cmd_deliver(proj, opt("--video"), kind, "--mono" in rest, "-v" in rest)


if __name__ == "__main__":
    main(sys.argv[1:])
