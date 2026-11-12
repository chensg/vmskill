"""回归：episode.py 的 new / status / deliver。

    python tests/test_episode.py

deliver 是一组检查，所以照这个仓库的规矩验两头：造一支齐全的假片子，它不该报；
再**逐条把被检查的东西弄坏**，它必须报，而且报的是那一项。只验「现在通过」等于没验。
new 验三件事：铺下来的预设引擎读得进去、重跑不覆盖已有文件、不往片库根里铺。

VMSKILL_SCRIPTS 指到一份故意改坏的副本，可以验这套测试自己会不会红
（比如把 episode.py 的 LUFS_TOL 改成 100，「响度」那条必须红）。

要 ffmpeg / ffprobe 在 PATH 上，约一分钟。
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.environ.get("VMSKILL_SCRIPTS") or os.path.join(ROOT, "classical-poem-video", "scripts")
EP = os.path.join(SCRIPTS, "episode.py")
FAILS = []
CORE = {"封装", "片长", "响度", "字幕zh", "字幕en", "英文轨", "封面", "门禁", "章节"}


def ok(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        FAILS.append(what)


def ff(*a):
    subprocess.run(["ffmpeg", "-v", "error", "-y"] + list(a), check=True)


def video(path, w, h, dur, ch=2, lufs=-15, tracks=1):
    """灰底 + 440Hz，H.264 + AAC 48k。r=2 是为了快。"""
    a = ["-f", "lavfi", "-i", "color=c=gray:s=%dx%d:r=2:d=%.2f" % (w, h, dur),
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=%.2f" % dur,
         "-map", "0:v"] + ["-map", "1:a"] * tracks + [
         "-af", "loudnorm=I=%d:TP=-1.5:LRA=11" % lufs, "-ac", str(ch), "-ar", "48000",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path]
    ff(*a)


def audio(path, dur):
    ff("-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=%.2f" % dur, "-ac", "2", "-c:a", "aac", path)


def srt(path, end):
    stamp = "%02d:%02d:%06.3f" % (end // 3600, end % 3600 // 60, end % 60)
    open(path, "w", encoding="utf-8").write(
        "1\n00:00:00,500 --> 00:00:02,000\n第一句\n\n2\n00:00:02,200 --> %s\n第二句\n" % stamp.replace(".", ","))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8", newline="\n").write(text)


CFG = ('TITLE, SUBTITLE = "假片", ""\nNARR = [{"vo": "VO_01a", "shot": 1, "txt": "一"}, {"vo": "VO_01b", "shot": 1, "txt": "二"}]\n'
       'CLIPS = [{"src": "生成/a.png"}]\nLANGS = ["zh", "en"]\n'
       'GATE_SCRIPT_OK = "2026-01-01 用户：过"\nGATE_PREVIEW_OK = "豁免：默认不出检查片"\n')
CHAPTERS = "0:00 冷开场\n1:30 第二章\n3:10 第三章\n"


def project(tmp, name, kind="short", dur=6.0):
    p = os.path.join(tmp, name)
    w, h = (1080, 1920) if kind == "short" else (1920, 1080)
    stem = os.path.join(p, "成片_竖版" if kind == "short" else "成片_横版")
    os.makedirs(p)
    video(stem + ".mp4", w, h, dur)
    srt(stem + ".srt", dur - 1.0)
    srt(stem + ".en.srt", dur - 1.0)
    audio(stem + "_音轨_eng.m4a", dur)
    ff("-f", "lavfi", "-i", "color=c=navy:s=320x180", "-frames:v", "1", os.path.join(p, "封面.jpg"))
    if kind == "long":
        shutil.copyfile(os.path.join(p, "封面.jpg"), os.path.join(p, "封面_en.jpg"))
    write(os.path.join(p, "发布文案.md"), "# 假片\n\n## YouTube\n- 标题：假\n\n" + (CHAPTERS if kind == "long" else ""))
    write(os.path.join(p, "build", "segment_config.py"), CFG)
    return p, stem


def deliver(p, *extra):
    r = subprocess.run([sys.executable, EP, "deliver", p] + list(extra), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    fails = set(re.findall(r"(?m)^FAIL \[(.+?)\]", r.stdout))
    return fails, r.returncode, r.stdout + r.stderr


def expect(p, key, what, *extra):
    f, rc, out = deliver(p, *extra)
    ok(key in f and rc == 1, "%s → 报 [%s]（实际报了 %s）" % (what, key, sorted(f) or "无"))


def test_deliver(tmp):
    print("deliver：Short")
    p, stem = project(tmp, "短片")
    f, rc, out = deliver(p)
    ok(not (f & CORE), "齐全的片子：封装/片长/响度/字幕/英文轨/封面/门禁 都不报（报了 %s）" % sorted(f & CORE))
    ok("Traceback" not in out, "没有崩")

    os.rename(stem + ".en.srt", stem + ".en.bak")
    expect(p, "字幕en", "删掉英文字幕")
    f, _, _ = deliver(p, "--mono")
    ok("字幕en" not in f and "英文轨" not in f, "--mono：不要英文字幕和英文轨")
    os.rename(stem + ".en.bak", stem + ".en.srt")

    srt(stem + ".srt", 9.0)
    expect(p, "字幕zh", "中文字幕最后一条超出片长")
    srt(stem + ".srt", 5.0)

    audio(stem + "_音轨_eng.m4a", 3.0)
    expect(p, "英文轨", "英文轨比画面短 3 秒")
    os.remove(stem + "_音轨_eng.m4a")
    expect(p, "英文轨", "没有英文轨")
    audio(stem + "_音轨_eng.m4a", 6.0)

    keep = stem + ".keep"
    os.rename(stem + ".mp4", keep)
    for what, key, kw in (("单声道", "封装", dict(ch=1)), ("两条音轨的文件当上传件", "封装", dict(tracks=2)),
                          ("响度 −9 LUFS", "响度", dict(lufs=-9)), ("响度 −22 LUFS", "响度", dict(lufs=-22))):
        video(stem + ".mp4", 1080, 1920, 6.0, **kw)
        expect(p, key, what)
    video(stem + ".mp4", 1920, 1080, 6.0)
    expect(p, "封装", "--type short 却是横版画面", "--type", "short")
    video(stem + ".mp4", 1080, 1920, 185.0)
    srt(stem + ".srt", 5.0)
    expect(p, "片长", "Short 185 秒")
    os.remove(stem + ".mp4")
    expect(p, "成片", "没有成片")
    os.rename(keep, stem + ".mp4")

    cv = os.path.join(p, "封面.jpg")
    small = open(cv, "rb").read()
    open(cv, "wb").write(small + b"\0" * (3 * 1024 * 1024))
    expect(p, "封面", "封面 3MB")
    os.remove(cv)
    expect(p, "封面", "没有封面")
    open(cv, "wb").write(small)

    write(os.path.join(p, "build", "segment_config.py"), CFG.replace('"2026-01-01 用户：过"', '""'))
    expect(p, "门禁", "门禁一没签")
    write(os.path.join(p, "build", "segment_config.py"), CFG)

    os.remove(os.path.join(p, "发布文案.md"))
    expect(p, "发布文案", "没有发布文案")

    f, rc, _ = deliver(p, "--video", stem + ".mp4")
    ok("成片" not in f, "--video 指定成片")

    print("deliver：长片")
    p, stem = project(tmp, "长片", "long", dur=240.0)
    f, rc, out = deliver(p)
    ok(not (f & CORE), "齐全的长片：含章节时间码都不报（报了 %s）" % sorted(f & CORE))
    pub = os.path.join(p, "发布文案.md")
    for what, text in (("只有两条章节", "0:00 冷开场\n1:30 第二章\n"), ("第一条不是 0:00", "0:05 一\n1:30 二\n3:10 三\n"),
                       ("有一段不到 10 秒", "0:00 一\n0:06 二\n3:10 三\n"), ("时间码超过片长", "0:00 一\n1:30 二\n9:10 三\n"),
                       ("没有章节", "")):
        write(pub, "# 假片\n\n## YouTube\n- 标题：假\n\n" + text)
        expect(p, "章节", "长片" + what)
    write(pub, "# 假片\n\n" + CHAPTERS + "\n## YouTube (EN)\n\n" + CHAPTERS)
    f, _, _ = deliver(p)
    ok("章节" not in f, "中英两组章节时间码：不报")
    os.remove(os.path.join(p, "封面_en.jpg"))
    expect(p, "封面", "长片没有英文封面")


def test_status(tmp):
    print("status")
    p, stem = project(tmp, "看状态")
    r = subprocess.run([sys.executable, EP, "status", p], capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = r.stdout
    ok(r.returncode == 0 and "Traceback" not in out + r.stderr, "跑得完")
    ok(len(out.splitlines()) <= 25, "不超过 25 行（%d 行）" % len(out.splitlines()))
    ok("门禁一 已签" in out, "读得出门禁签字")
    ok("zh 0/2" in out and "VO_01a" in out, "旁白没到：报 0/2 并点名缺哪条")
    ok("素材 0/1" in out, "素材没到：报 0/1")
    ok("6.0s" in out and "1080x1920" in out, "成片的时长和尺寸")
    os.makedirs(os.path.join(p, "build", "vo"))
    for v in ("VO_01a", "VO_01b"):
        audio(os.path.join(p, "build", "vo", v + ".m4a"), 1.0)
    write(os.path.join(p, "素材", "生成", "a.png"), "x")
    out = subprocess.run([sys.executable, EP, "status", p], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    ok("zh 2/2" in out and "素材 1/1" in out, "补齐之后：2/2、1/1")


def test_new(tmp):
    print("new")
    p = os.path.join(tmp, "新片")
    r = subprocess.run([sys.executable, EP, "new", p, "--type", "short", "--title", "测试片"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    b = os.path.join(p, "build")
    ok(r.returncode == 0 and all(os.path.isfile(os.path.join(b, f)) for f in
                                 ("make_story_v.py", "story_core.py", "segment_config.py", "ENGINE_COMMIT.txt")),
       "铺出模板、引擎、预设、提交号")
    ok("测试片" in open(os.path.join(b, "segment_config.py"), encoding="utf-8").read(), "预设里填了片名")
    g = subprocess.run([sys.executable, "make_story_v.py", "gates"], cwd=b, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    ok("未过" in g.stdout and "Traceback" not in g.stdout + g.stderr and g.returncode == 1,
       "预设引擎读得进去：gates 报两道门禁未过、不崩")
    c = subprocess.run([sys.executable, "make_story_v.py", "check"], cwd=b, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    ok("还是空的" in c.stdout + c.stderr and "Traceback" not in c.stdout + c.stderr, "旁白和镜头表没填时 check 说人话，不掉 IndexError")
    ok("没有夏天" not in open(os.path.join(b, "segment_config.py"), encoding="utf-8").read(), "预设里没有别的片子的内容")

    doc = os.path.join(p, "讲述稿.md")
    open(doc, "a", encoding="utf-8").write("我写的稿子\n")
    open(os.path.join(b, "segment_config.py"), "a", encoding="utf-8").write("# 我改过\n")
    subprocess.run([sys.executable, EP, "new", p, "--type", "short"], capture_output=True)
    ok("我写的稿子" in open(doc, encoding="utf-8").read()
       and "我改过" in open(os.path.join(b, "segment_config.py"), encoding="utf-8").read(), "重跑 new：已有的文件不覆盖")

    lib = os.path.join(tmp, "片库")
    for s in ("甲", "乙"):
        os.makedirs(os.path.join(lib, s, "素材"))
    r = subprocess.run([sys.executable, EP, "new", lib, "--type", "short"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    ok(r.returncode != 0 and not os.path.isdir(os.path.join(lib, "build")), "片库根：拒绝，不往里铺")

    p2 = os.path.join(tmp, "新长片")
    r = subprocess.run([sys.executable, EP, "new", p2, "--type", "long"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    b2 = os.path.join(p2, "build")
    ok(all(os.path.isfile(os.path.join(b2, f)) for f in ("film.py", "film_config.py", "vid_prompts.py", "music_prompts.py",
                                                         "run_pika.py", "pika_seedvr2.py", "mm_music.py"))
       and os.path.isfile(os.path.join(b2, "comfy", "video_pika_h3_i2v_8step_hd.json"))
       and not os.path.isfile(os.path.join(b2, "segment_config.py")) and not os.path.isfile(os.path.join(b2, "story_core.py")),
       "长片：铺 film.py、三份预设、生成工具和工作流，不铺讲述引擎")
    c = subprocess.run([sys.executable, "film.py", "check"], cwd=b2, capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok("Traceback" not in c.stdout + c.stderr and "vo_lines.json" in c.stdout + c.stderr or "缺" in c.stdout + c.stderr,
       "长片骨架上跑 film.py check：读得到稿子骨架，说缺什么，不崩")
    v = subprocess.run([sys.executable, "vid_prompts.py"], cwd=b2, capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok(v.returncode == 0 and "0 条" in v.stdout, "vid_prompts.py 预设能跑")
    s = subprocess.run([sys.executable, EP, "status", p2], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    ok("film_config.py" in s, "status 认得长片配置")
    ok("film.py check 还跑不通" in s and "Traceback" not in s, "长片骨架的 status：说 check 还跑不通，不崩、不乱报镜数")


def main():
    tmp = tempfile.mkdtemp(prefix="episode_")
    try:
        test_new(tmp)
        test_status(tmp)
        test_deliver(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("")
    print("全部通过" if not FAILS else "%d 条没过：\n  - %s" % (len(FAILS), "\n  - ".join(FAILS)))
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
