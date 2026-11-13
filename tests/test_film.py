"""回归：film.py（横版长片合成）。

    python tests/test_film.py

造一支九镜的小长片（影片镜、静帧慢推、片名卡、照片 kb、档案页、章节卡、路线图、末镜），把
check / srt / gate2 / final / part / en 全跑一遍。重点验三件踩过的事：

  1. **画面不漂**：各镜帧数加起来必须等于「片长 × 帧率」。《剩人》正式版每镜各自取整，画面比旁白
     累积晚了 1.48 秒，章节卡的大字压在上一镜的尾巴上。
  2. **缺画面要拦**：缺影片的镜 check 报出来、final 拒绝；加 --allow-missing 才用深底顶着出。
  3. **成品沿用要认源文件**：换了一张图，那一镜必须重渲（原脚本只和脚本自己的修改时间比）。

VMSKILL_SCRIPTS 指到改坏的副本可以验这套测试会不会红（比如把帧网格那行改回 `D = b - a`）。
要 ffmpeg / ffprobe、numpy、Pillow，约两三分钟。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.environ.get("VMSKILL_SCRIPTS") or os.path.join(ROOT, "classical-poem-video", "scripts")
FILM, EP = os.path.join(SCRIPTS, "film.py"), os.path.join(SCRIPTS, "episode.py")
FAILS = []

SCRIPT = """# 测试片

## 冷開場

**01** [生·影片] 一段生成影片。

**02** [推] 首幀：一張圖慢推。

**03** [卡] 片名卡。

## 第一章　開頭

**04** [實] 城門實拍。

**05** [檔＋動畫] 檔案頁，點亮兩行。＋[詩]

## 第二章　結尾

**06** [卡] 章節卡。

**07** [動畫] 路線圖。

**08** [生·影片] 又一段生成影片。

**09** [卡] 片尾，停住。

## 片名候選（不寫進稿）
"""
# 旁白时长故意取成「(时长 + 镜间 0.7s) × 24 帧 = 整数 + 0.4」：各镜自己取整每镜少 0.4 帧，六镜下来差两帧；
# 按帧网格取就一帧不差。这样「画面不漂」那条在帧网格被改坏时必然变红，不靠运气。
def _d(k):
    return (k + 0.4) / 24 - 0.7


VO = [("01", "VO_001", "第一句話，講城門口。", _d(72)), ("02", "VO_002", "第二句話，一隻手遞上木牌。", _d(85)),
      ("04", "VO_003", "第三句話，城門還在。", _d(69)), ("05", "VO_004", "他寫道：「床前明月光，疑是地上霜。」", _d(96)),
      ("07", "VO_005", "第五句話，一路向北。", _d(79)), ("08", "VO_006", "第六句話，到了。", _d(63))]
CONFIG = '''NAME = "测试片"
TITLE_BIG = "测试片\\\\N{\\\\fs44}副题"
SKIP = 0.5
END_POEM = ["水流石出"]
EXT = os.path.join(PROJ, "素材", "外部")
SPEC = {
    "04": ("kb", os.path.join(EXT, "gate.jpg"), (0.50, 0.40, 0.80), (0.50, 0.38, 0.66)),
    "05": ("page", os.path.join(EXT, "page.jpg"), (0.1, 0.1, 0.9, 0.9), [(0.2, 0.2, 0.3, 0.8, 0.1), (0.5, 0.2, 0.6, 0.8, 0.5)]),
    "07": ("route", os.path.join(EXT, "map.jpg"), (0.5, 0.5, 0.9), (0.5, 0.5, 0.8), [(0.3, 0.7), (0.5, 0.5), (0.7, 0.3)], {0: "甲", 2: "乙"}, True),
}
CARD_BG = {"03": ("kb", os.path.join(EXT, "gate.jpg"), (0.5, 0.5, 0.9), (0.5, 0.5, 0.85)),
           "06": ("clips", [(os.path.join(PROJ, "素材", "影片", "G01.mp4"), 0.5, 1.0)]),     # 整支影片只取一段
           "09": ("kb", os.path.join(EXT, "map.jpg"), (0.5, 0.5, 1.0), (0.5, 0.5, 0.9))}
CARD_EN = {"03": "TEST FILM", "06": "Chapter Two"}
CHAPTER_EN = {"冷開場": "Cold Open"}
'''


def ok(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        FAILS.append(what)


def ff(*a):
    subprocess.run(["ffmpeg", "-v", "error", "-y"] + list(a), check=True)


def probe(path, entries, stream="v:0"):
    return subprocess.run(["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", entries, "-of", "csv=p=0", path],
                          capture_output=True, text=True).stdout.strip()


def dur(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                capture_output=True, text=True).stdout)


def rgb(path, t):
    """t 秒那一帧缩到 480x270 的平均 RGB 和最亮通道的最大值。"""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "%.3f" % t, "-i", path, "-frames:v", "1", "-vf", "scale=480:270",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    n = len(raw) // 3 or 1
    return tuple(sum(raw[k::3]) / n for k in range(3)), max(raw) if raw else 0


def film(p, *a):
    r = subprocess.run([sys.executable, FILM] + list(a) + ["--proj", p], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, r.stdout + r.stderr


def build(tmp):
    p = os.path.join(tmp, "小长片")
    for d in ("build/vo", "build/vo_en", "素材/影片", "素材/生成", "素材/外部", "素材/配乐"):
        os.makedirs(os.path.join(p, d))
    open(os.path.join(p, "讲述稿_v1.md"), "w", encoding="utf-8").write(SCRIPT)
    json.dump([{"id": i, "shot": n, "txt": t, "subs": [t]} for n, i, t, _ in VO],
              open(os.path.join(p, "vo_lines.json"), "w", encoding="utf-8"), ensure_ascii=False)
    for n, i, t, d in VO:
        # 内容是 WAV（时长精确到采样），只是文件名按约定叫 .mp3；ffmpeg 按内容认格式
        ff("-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=%.6f" % d, "-ac", "1", "-f", "wav",
           os.path.join(p, "build/vo", i + ".mp3"))
        ff("-f", "lavfi", "-i", "sine=frequency=330:duration=%.2f" % (d * 0.6), "-ac", "1", "-ar", "44100", os.path.join(p, "build/vo_en", i + ".mp3"))
    open(os.path.join(p, "讲述稿_en.md"), "w", encoding="utf-8").write(
        "# en\n---\n" + "".join("%s. English line number %s.\n" % (i[3:], i[3:]) for _, i, _, _ in VO))
    for g in ("G01", "G08"):
        ff("-f", "lavfi", "-i", "testsrc=s=640x360:r=24:d=2", "-f", "lavfi", "-i", "sine=frequency=110:duration=2",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", os.path.join(p, "素材/影片", g + ".mp4"))
    ff("-f", "lavfi", "-i", "testsrc2=s=1920x1080", "-frames:v", "1", os.path.join(p, "素材/生成/S02.png"))
    for f in ("gate.jpg", "page.jpg", "map.jpg"):
        ff("-f", "lavfi", "-i", "testsrc2=s=2400x1600", "-frames:v", "1", os.path.join(p, "素材/外部", f))
    for k in (1, 2):
        ff("-f", "lavfi", "-i", "sine=frequency=%d:duration=30" % (440 * k), os.path.join(p, "素材/配乐", "MM_段%d_1.mp3" % k))
    open(os.path.join(p, "build/film_config.py"), "w", encoding="utf-8").write(CONFIG)
    return p


def main():
    tmp = tempfile.mkdtemp(prefix="film_")
    try:
        p = build(tmp)
        out, t = os.path.join(p, "成片"), os.path.join(p, "成片", "_tmp_final")

        print("check / srt")
        rc, o = film(p, "check")
        ok(rc == 0 and "没有缺的" in o and len(re.findall(r"(?m)^\s*鏡", o)) == 9, "check：九镜都有画面")
        ok("片名卡" not in o and "卡底 kb" in o and "SPEC route" in o and "静帧慢推" in o and "影片 G01" in o, "check：每镜的画面来源都认对了")
        total = float(re.search(r"（([\d.]+)s）", o).group(1))
        st = subprocess.run([sys.executable, EP, "status", p], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
        ok("9 镜，缺画面 0 镜" in st, "episode.py status：长片报几镜、缺几镜（问的是 film.py check）")
        rc, o = film(p, "srt")
        srt = open(os.path.join(out, "测试片.srt"), encoding="utf-8").read()
        ch = open(os.path.join(out, "测试片_章节时间码.txt"), encoding="utf-8").read().splitlines()
        ok(srt.count("-->") >= 6 and "床前明月光" in srt, "srt：字幕出来了")
        ok(len(ch) == 3 and ch[0] == "0:00 冷開場" and ch[1].endswith("第一章 開頭"), "章节时间码：三条，从 0:00 起，全角空格换成半角")

        rc, o = film(p, "tsv")
        rows = [l.split("\t") for l in open(os.path.join(p, "build", "_shots.tsv"), encoding="utf-8").read().splitlines()]
        ok(len(rows) == 9 and rows[0][:3] == ["01", "生·影片", "2.3"] and rows[2][2] == "3.0" and rows[4][4].endswith("（詩）"),
           "tsv：九行，旁白镜记旁白秒数、卡记停留秒数、诗镜有标记")
        shutil.copyfile(os.path.join(SCRIPTS, "presets", "vid_prompts.py"), os.path.join(p, "build", "vid_prompts.py"))
        open(os.path.join(p, "build", "vid_prompts.py"), "a", encoding="utf-8").write("\n".join([
            "", "add('01', 'x')", "add('77', 'y')", "print('F01', frames('G01'))",
            "try:", "    frames('G77')", "except SystemExit as e:", "    print('NO77', e)", ""]))
        v = subprocess.run([sys.executable, "vid_prompts.py"], cwd=os.path.join(p, "build"), capture_output=True, text=True,
                           encoding="utf-8", errors="replace").stdout
        ok("F01 124" in v and "NO77" in v and "film.py tsv" in v, "vid_prompts 预设：按 _shots.tsv 算帧数（124），镜号不在表里说人话")

        print("final")
        rc, o = film(p, "final")
        mp4 = os.path.join(out, "测试片.mp4")
        ok(rc == 0 and os.path.isfile(mp4), "final 出片")
        frames = sum(int(probe(os.path.join(t, "%03d.mp4" % i), "stream=nb_frames")) for i in range(9))
        ok(frames == round(total * 24), "画面不漂：九镜帧数合计 %d = 片长 %.2fs × 24 = %d" % (frames, total, round(total * 24)))
        vd, ad = float(probe(mp4, "stream=duration")), float(probe(mp4, "stream=duration", "a:0"))
        ok(abs(vd - total) < 0.06 and abs(ad - total) < 0.06, "成片的画面 %.2fs、声音 %.2fs 都等于时间轴 %.2fs" % (vd, ad, total))
        ok(probe(mp4, "stream=width,height") == "1920,1080", "1920x1080")
        d = subprocess.run([sys.executable, EP, "deliver", p, "--mono", "-v"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
        ok(not re.search(r"FAIL \[(封装|响度|字幕zh)\]", d), "deliver：封装、响度（−15±1）、中文字幕都过")

        print("沿用与重渲")
        rc, o = film(p, "final")
        ok(o.count("（沿用）") == 9, "再跑一次 final：九镜全部沿用")
        time.sleep(1.1)
        ff("-f", "lavfi", "-i", "testsrc=s=1920x1080", "-frames:v", "1", os.path.join(p, "素材/生成/S02.png"))
        rc, o = film(p, "final")
        ok(o.count("（沿用）") == 8 and "S02.png 慢推" in o, "换了镜 02 的图：只有那一镜重渲")
        # 成品沿用按每镜自己的配方（SPEC / CARD_BG 那一条 + 源文件）做指纹，不看整个配置文件的修改时间。
        # 原来改配置里任何一处，全片都要重渲 —— 徐燦 95 镜换两张图要渲一个多小时（2026-11-13）。
        cfg_p = os.path.join(p, "build/film_config.py")
        cfg0 = open(cfg_p, encoding="utf-8").read()
        time.sleep(1.1)
        open(cfg_p, "w", encoding="utf-8").write(cfg0 + "\n# 只加一行注释\n")
        rc, o = film(p, "final")
        ok(o.count("（沿用）") == 9, "配置里只加了一行注释：九镜全部沿用（实得 %d）" % o.count("（沿用）"))
        open(cfg_p, "w", encoding="utf-8").write(cfg0.replace("(0.50, 0.38, 0.66)", "(0.50, 0.40, 0.60)"))
        rc, o = film(p, "final")
        ok(o.count("（沿用）") == 8, "只改了镜 04 的 SPEC：只有那一镜重渲（沿用 %d）" % o.count("（沿用）"))
        open(cfg_p, "w", encoding="utf-8").write(cfg0)

        print("part / gate2 / shots")
        rc, o = film(p, "part", "2")
        pv = os.path.join(out, "测试片_第2部分_预览.mp4")
        ok(rc == 0 and os.path.isfile(pv) and "（沿用）" in o, "part 2 出预览，沿用全片渲好的镜")
        rc, o = film(p, "part", "9")
        ok(rc != 0 and "没有第 9 部分" in o, "part 9：说没有这一部分")
        rc, o = film(p, "gate2")
        g2 = os.path.join(p, "门禁二", "测试片_门禁二.mp4")
        ok(rc == 0 and os.path.isfile(g2) and abs(dur(g2) - total) < 0.5, "gate2 出门禁二片，长度等于时间轴")
        rc, o = film(p, "shots", "05", "07")
        ok(rc == 0 and all(os.path.isfile(os.path.join(t, "_check_%s.mp4" % n)) for n in ("05", "07")), "shots：只渲点名的两镜")
        rc, o = film(p, "shots", "77")
        ok(rc != 0 and "77" in o, "shots 给了不存在的镜号：报出来")

        print("英文轨")
        rc, o = film(p, "en", "check")
        ok(rc == 0 and o.count("VO_00") >= 6, "en check：六条都在槽里")
        rc, o = film(p, "en")
        m4a = os.path.join(out, "测试片_音轨_eng.m4a")
        ok(rc == 0 and abs(dur(m4a) - total) < 0.2, "en：英文轨和全片等长")
        en = open(os.path.join(out, "测试片.en.srt"), encoding="utf-8").read()
        ok("English line number 001" in en and "TEST FILM" in en and "Chapter Two" in en, "英文字幕：旁白和卡上的字都有")
        ok(open(os.path.join(out, "测试片_章节时间码_en.txt"), encoding="utf-8").read().startswith("0:00 Cold Open"), "英文章节时间码")
        ff("-f", "lavfi", "-i", "sine=frequency=330:duration=9", "-ac", "1", os.path.join(p, "build/vo_en/VO_002.mp3"))
        rc, o = film(p, "en", "check")
        ok(rc == 1 and "VO_002 超" in o, "英文比槽长：报出哪一条、超多少")

        print("外部影片截段 / 源文件不在")
        sys.path.insert(0, SCRIPTS)
        import film as F
        g01 = os.path.join(p, "素材/影片/G01.mp4")
        ok(abs(F.clip_dur((g01, 0.5, 1.0)) - 1.0) < 1e-6 and abs(F.clip_dur((g01, 1.5, 9.0)) - 0.5) < 0.1 and abs(F.clip_dur(g01) - 2.0) < 0.1,
           "clips 的 (路径, 起点, 秒数)：按写的取，超出片尾的按剩下的算")
        ok(F.spec_sources(("clips", [(g01, 0.5, 1.0)])) == [g01], "截段写法的源文件还是那支影片（沿用判断要用）")
        cfg_p = os.path.join(p, "build/film_config.py")
        cfg0 = open(cfg_p, encoding="utf-8").read()
        open(cfg_p, "w", encoding="utf-8").write(cfg0 + '\nSPEC["04"] = ("kb", os.path.join(EXT, "nope.jpg"), (0.5, 0.5, 0.8), (0.5, 0.5, 0.7))\n')
        rc, o = film(p, "check")
        ok(rc == 1 and "源文件不在：nope.jpg" in o, "SPEC 里的路径写错：check 点名哪个文件不在")
        open(cfg_p, "w", encoding="utf-8").write(cfg0 + "\nMUTE_EXT = True\n")
        rc, o = film(p, "shots", "06")
        vol = subprocess.run(["ffmpeg", "-v", "info", "-i", os.path.join(t, "_check_06.wav"), "-af", "volumedetect", "-f", "null", "-"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
        ok(rc == 0 and re.search(r"max_volume: -(9\d|inf)", vol) is not None, "MUTE_EXT：外部影片的原声不进成片")
        open(cfg_p, "w", encoding="utf-8").write(cfg0)

        print("引文板 / seq 两张照片 / 写错的键")
        open(cfg_p, "w", encoding="utf-8").write(cfg0 + '\nSKIPP = 1.0\nCARD_EN["77"] = "x"\n')
        rc, o = film(p, "check")
        ok("SKIPP" in o and "SKIP？" in o, "配置里写成 SKIPP：check 说它没生效、是不是 SKIP")
        ok(re.search(r"CARD_EN 里这些镜号稿子里没有：77", o) is not None, "CARD_EN 里有稿子没有的镜号 77：check 报出来")
        ff("-f", "lavfi", "-i", "color=c=red:s=2400x1600", "-frames:v", "1", os.path.join(p, "素材/外部/red.jpg"))
        open(cfg_p, "w", encoding="utf-8").write(cfg0 + '\nSPEC["05"] = ("quote", "臣謹奏｜家人俱在", "《某實錄》")\n'
            'SPEC["04"] = ("seq", [("kb", os.path.join(EXT, "gate.jpg"), (0.5, 0.5, 0.9), (0.5, 0.5, 0.85)),\n'
            '                      ("kb", os.path.join(EXT, "red.jpg"), (0.5, 0.5, 0.9), (0.5, 0.5, 0.85))])\n')
        rc, o = film(p, "shots", "04", "05")
        q, s4 = os.path.join(t, "_check_05.mp4"), os.path.join(t, "_check_04.mp4")
        ok(rc == 0 and os.path.isfile(q), "SPEC 写 quote（引文板）：渲得出来")
        if rc == 0 and os.path.isfile(q):
            (mr, mg, mb), top = rgb(q, dur(q) * 0.9)
            ok(max(mr, mg, mb) < 90 and top > 150, "引文板：深底（均值 %.0f）上有亮字（最亮 %d）" % (max(mr, mg, mb), top))
        if rc == 0 and os.path.isfile(s4):
            (r0, g0, b0), _ = rgb(s4, dur(s4) * 0.75)
            ok(r0 > 150 and g0 < 80 and b0 < 80, "seq 里两张照片：后半镜是第二张（红图，实得 %.0f/%.0f/%.0f）" % (r0, g0, b0))
        else:
            ok(False, "seq 里两张照片：渲得出来")
        open(cfg_p, "w", encoding="utf-8").write(cfg0)

        print("缺东西")
        os.remove(os.path.join(p, "素材/影片/G08.mp4"))
        rc, o = film(p, "check")
        ok(rc == 1 and re.search(r"鏡\s+08 .*!! 没有画面", o) is not None, "缺影片：check 点名镜 08")
        st = subprocess.run([sys.executable, EP, "status", p], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
        ok("缺画面 1 镜（08）" in st and "补画面 1 镜" in st, "episode.py status：缺影片时点名镜 08，下一步写补画面")
        rc, o = film(p, "final")
        ok(rc != 0 and "08" in o and "没有画面" in o, "缺影片：final 拒绝")
        rc, o = film(p, "final", "--allow-missing")
        ok(rc == 0, "--allow-missing：照样出")
        os.remove(os.path.join(p, "素材/配乐/MM_段2_1.mp3"))
        rc, o = film(p, "check")
        ok(rc == 1 and "段2" in o, "缺配乐：check 报段 2")
        os.remove(os.path.join(p, "build/vo/VO_003.mp3"))
        rc, o = film(p, "check")
        ok(rc != 0 and "缺旁白" in o and "VO_003" in o, "缺旁白：说缺哪一条")
        ff("-f", "lavfi", "-i", "sine=frequency=220:duration=2", "-ac", "1", os.path.join(p, "build/vo/VO_003.mp3"))
        v = json.load(open(os.path.join(p, "vo_lines.json"), encoding="utf-8")) + [{"id": "VO_099", "shot": "99", "txt": "x", "subs": ["x"]}]
        json.dump(v, open(os.path.join(p, "vo_lines.json"), "w", encoding="utf-8"), ensure_ascii=False)
        rc, o = film(p, "check")
        ok(rc != 0 and "99" in o, "vo_lines 里有稿子里没有的镜号：报出来")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("")
    print("全部通过" if not FAILS else "%d 条没过：\n  - %s" % (len(FAILS), "\n  - ".join(FAILS)))
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
