"""回归：comfy_gen.py（本机 ComfyUI 出图/出影片/放大）——离线，不连 ComfyUI、不碰显卡。

    python tests/test_comfy_gen.py

验的是会静默出错的地方：
  - 图和影片同名时，影片那张表（▶）不能把图的画面句盖掉；
  - 交给 ComfyUI 的 prompt 改对了节点（提示词、尺寸、步数、种子、首幀、秒数）；
  - 横竖不一致的首幀、节点号变了的工作流、功耗/显存频率越线 —— 都要拦；
  - 放大到 1080 的倍率和裁切（SeedVR2 的后处理、lanczos）出来正好是目标尺寸。
每条拦截都做了变异：把被检查的东西拿掉，确认它不再报（或报了），不是只验「现在通过」。
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.environ.get("VMSKILL_SCRIPTS") or os.path.join(ROOT, "classical-poem-video", "scripts")
FAILS = []

BRIEF = """# 测试任务书

## 固定開頭

> 寫實電影劇照風格，豎構圖 9:16，海邊小鎮。

## 固定結尾 A（有人）

> 不要文字。人物只拍背影。

## 固定結尾 E（沒有人）

> 不要文字。沒有人。

## 分鏡

| 檔 | 鏡 | 結尾 | 畫面句 |
|---|---|---|---|
| 01_船 | 1 | A | 一艘白色小漁船，潛水員坐在船舷。 |
| 02_海 | 2 | E | 平靜的海面。 |

## 影片固定開頭

> 寫實電影鏡頭。

## 影片固定結尾

> 沒有音樂。

| 影片 | 首幀 | 秒 | 動作句 |
|---|---|---|---|
| ▶01_船 | 01_船 | 6 | 潛水員向後翻身落水。 |
| ▶03_空 | - | 5 | 海鷗飛過。 |
"""


def ok(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        FAILS.append(what)


def raises(fn):
    try:
        fn()
    except SystemExit as e:
        return str(e)
    return None


def ffmpeg_color(path, w, h, dur=None):
    args = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=%dx%d" % (w, h)]
    args += (["-t", str(dur), "-pix_fmt", "yuv420p", path] if dur else ["-frames:v", "1", path])
    subprocess.run(args, check=True)


def load():
    sys.path.insert(0, SCRIPTS)
    spec = importlib.util.spec_from_file_location("comfy_gen", os.path.join(SCRIPTS, "comfy_gen.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    cg = load()
    d = tempfile.mkdtemp()
    open(os.path.join(d, "出图任务书.md"), "w", encoding="utf-8").write(BRIEF)
    cg.set_proj(d)
    os.makedirs(cg.dst())

    print("== 任务书")
    rows = cg.ew._brief()[4]
    ok(rows.get("01_船", ("", ""))[1].startswith("一艘白色小漁船"), "同名的影片行（▶01_船）没盖掉图的画面句")
    vrows = cg.vbrief()[2]
    ok(vrows.get("01_船") == ("01_船", 6.0, "潛水員向後翻身落水。"), "影片表：首幀、秒、動作句 %r" % (vrows.get("01_船"),))
    ok(vrows.get("03_空", (1,))[0] is None, "首幀写 - ＝文生影片")
    ok(cg.vertical(), "固定開頭写 9:16 → 竖版")
    ok(cg.vprompt("01_船") == "寫實電影鏡頭。 潛水員向後翻身落水。 沒有音樂。", "影片提示词＝开头＋动作句＋结尾")
    # 变异：去掉 ▶，影片行就会被当成图的那张表读走（这就是 ▶ 存在的理由）
    open(os.path.join(d, "出图任务书.md"), "w", encoding="utf-8").write(BRIEF.replace("▶01_船", "01_船"))
    ok(cg.ew._brief()[4]["01_船"][1] == "潛水員向後翻身落水。", "变异：不加 ▶ 时图的画面句确实被盖掉（▶ 不是摆设）")
    open(os.path.join(d, "出图任务书.md"), "w", encoding="utf-8").write(BRIEF)

    # ---- 交出去的 prompt：截住 run()，只看改了哪些节点 ----
    sent = []

    def fake_run(key, wf, out, label):          # 截住 run()：记下交了什么，图就落一张小 PNG（promote/sheet 要用）
        sent.append((key, wf, out))
        if out.endswith(".png"):
            cg._keep_old(out)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            ffmpeg_color(out, 90, 160)
        return 1.0, dict(draw=0, memclk=0, used=0, temp=0)
    cg.run = fake_run
    cg.upload = lambda p: "up_" + os.path.basename(p)

    print("== image")
    cg.cmd_image(["01_船"], True, 7, None, 1)
    key, wf, out = sent[-1]
    N = cg.NODES["qwen2512"]
    ok(key == "qwen2512", "用 Qwen-Image-2512 工作流")
    ok(wf[N["prompt"][0]]["inputs"]["text"] == cg.ew.prompt("01_船"), "提示词写进 CLIPTextEncode")
    lat = wf[N["latent"][0]]["inputs"]
    ok((lat["width"], lat["height"]) == (1088, 1920), "竖版直出 1088×1920（实际 %sx%s）" % (lat["width"], lat["height"]))
    ok(wf[N["fast"][0]]["inputs"]["value"] is True, "--fast → Lightning 开关 true")
    ok(wf[N["sampler"][0]]["inputs"]["seed"] == 7, "--seed 7 写进 KSampler")
    ok(out.replace("\\", "/").endswith("候选/01_船/4s-7.png"), "--fast 进候选（候选/01_船/4s-7.png），不冒充定稿")
    ok(not os.path.exists(os.path.join(cg.dst(), "01_船.png")), "候选不会自己变成定稿")
    n0 = len(sent)
    cg.cmd_image(["01_船"], True, 7, None, 3)
    ok([s[1][N["sampler"][0]]["inputs"]["seed"] for s in sent[n0:]] == [8, 9], "--variants 3：种子 7 已有跳过，只出 8、9")
    ok("有 3 张候选" in (raises(lambda: cg.cmd_promote("01_船", None)) or ""), "三张候选不点名 promote → 拦")
    cg.cmd_promote("01_船", "2")
    ok(os.path.exists(os.path.join(cg.dst(), "01_船.png")), "promote 2 → 01_船.png")
    pr = [r for r in cg.logs() if r["kind"] == "promote"][-1]
    ok(pr["seed"] == 8 and pr["steps"] == 4, "promote 记下来源的步数和种子（%s）" % pr)
    cg.cmd_sheet([], "01_船")
    ok(os.path.exists(os.path.join(cg.cand_dir("01_船"), "_联络表.png")), "sheet --cand 出候选联络表")
    cg.cmd_sheet([], None)
    ok(os.path.exists(os.path.join(cg.dst(), "_联络表.png")), "sheet 出定稿联络表")
    cg.cmd_image(["01_船"], False, None, None, 1)
    s1 = sent[-1][1][N["sampler"][0]]["inputs"]["seed"]
    cg.cmd_image(["01_船"], False, None, None, 1)
    ok(sent[-1][1][N["sampler"][0]]["inputs"]["seed"] == s1, "不给 --seed 时种子由档名定（重跑可复现）")
    ok(sent[-1][2].endswith("01_船.png") and "候选" not in sent[-1][2], "不加 --fast 出 <档名>.png（50 步定稿）")
    ok(os.path.exists(os.path.join(cg.dst(), "01_船_v1.png")), "定稿重出时旧的改名 _v1")

    print("== video")
    ffmpeg_color(os.path.join(cg.dst(), "01_船.png"), 90, 160)
    cg.cmd_video(["01_船"], 480, False, None)
    key, wf, out = sent[-1]
    N = cg.NODES["h3_i2v"]
    g = wf[N["gen"][0]]["inputs"]
    ok(key == "h3_i2v", "有首幀 → 图生影片")
    ok((g["width"], g["height"]) == (480, 864), "竖版 480p＝480×864（实际 %sx%s）" % (g["width"], g["height"]))
    ok(wf[N["secs"][0]]["inputs"]["value"] == 6.0, "秒数写进时长节点")
    ok(wf[N["image"][0]]["inputs"]["image"] == "up_01_船.png", "首幀上传后写进 LoadImage")
    ok(wf[N["turbo"][0]]["inputs"]["value"] is False, "默认 20 步（不 turbo）")
    ok(out.endswith("01_船_480.mp4"), "480 试稿出 _480.mp4")
    cg.cmd_video(["03_空"], 768, True, None)
    key, wf, out = sent[-1]
    g = wf[cg.NODES["h3_t2v"]["gen"][0]]["inputs"]
    ok(key == "h3_t2v" and (g["width"], g["height"]) == (768, 1344), "首幀 - → 文生，768p＝768×1344")
    ok(out.endswith("03_空.mp4"), "768 定稿出 <档名>.mp4")
    # 横竖不一致的首幀要拦
    ffmpeg_color(os.path.join(cg.dst(), "01_船.png"), 160, 90)
    ok(raises(lambda: cg.cmd_video(["01_船"], 480, False, None)) is not None, "首幀是横的、影片是竖的 → 拦")
    for f in os.listdir(cg.dst()):
        if f.startswith("01_船") and f.endswith(".png"):
            os.remove(os.path.join(cg.dst(), f))
    n0 = len(sent)
    cg.cmd_video(["01_船"], 480, False, None)
    ks = [(s[0], s[1].get(cg.NODES["qwen2512"]["fast"][0], {}).get("inputs", {}).get("value")) for s in sent[n0:]]
    ok(ks == [("qwen2512", True), ("h3_i2v", None)], "首幀没出 → 先补 4 步版再出影片（实际 %s）" % ks)
    ff = [r for r in cg.logs() if r.get("role") == "first_frame"]
    ok(ff and ff[-1]["steps"] == 4, "补的首帧在日志里标 role=first_frame、4 步")

    print("== 切镜 / 帧条 / 记录")
    cut = os.path.join(d, "cut.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x202020:s=160x288:d=1.5",
                    "-f", "lavfi", "-i", "testsrc2=s=160x288:d=1.5", "-filter_complex", "[0][1]concat=n=2:v=1",
                    "-pix_fmt", "yuv420p", cut], check=True)
    smooth = os.path.join(d, "smooth.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x202020:s=160x288:d=3",
                    "-vf", "fade=in:0:60", "-pix_fmt", "yuv420p", smooth], check=True)
    c1, c2 = cg.cuts(cut), cg.cuts(smooth)
    ok(len(c1) == 1 and abs(c1[0] - 1.5) < 0.1, "硬切在 1.5 秒被抓到（%s）" % c1)
    ok(c2 == [], "慢慢淡入不算切镜（%s）" % c2)
    shutil.copy(cut, os.path.join(cg.dst(), "05_切_480.mp4"))
    cg.cmd_strip("05_切")
    ok(os.path.exists(os.path.join(cg.dst(), "_帧条_05_切.png")), "strip 出帧条")
    cg.cmd_notes()
    md = open(os.path.join(cg.dst(), "生成记录.md"), encoding="utf-8").read()
    ok("首帧专用" in md and "MiniMax H3" in md and "05_切" not in md.split("显卡时间")[0].replace("_帧条", ""),
       "notes：每个文件按最后一次产出写（01_船.png 最后是补的首帧）、影片写明 H3")

    print("== 工作流节点核对")
    wd = tempfile.mkdtemp()
    for k in cg.NODES:
        shutil.copy(os.path.join(SCRIPTS, "comfy", k + ".api.json"), wd)
    old = cg.WF_DIRS
    cg.WF_DIRS = [wd]
    ok(all(cg.load_wf(k) for k in cg.NODES), "仓库里的四份 API 工作流节点号都对得上")
    p = os.path.join(wd, "h3_i2v.api.json")
    j = json.load(open(p, encoding="utf-8"))
    j["114"]["class_type"] = "LoadImageMask"
    json.dump(j, open(p, "w", encoding="utf-8"))
    ok(raises(lambda: cg.load_wf("h3_i2v")) is not None, "变异：节点 class_type 变了 → 拦（不会把首幀塞错节点）")
    cg.WF_DIRS = old

    print("== 显卡红线")
    base = dict(name="NVIDIA GeForce RTX 3090", limit=333.0, draw=300.0, memclk=8999.0, used=1, total=24576)
    cg.gpu = lambda: dict(base)
    ok(raises(cg.guard_gpu) is None, "333W 上限放行")
    cg.gpu = lambda: dict(base, limit=370.0)
    ok(raises(cg.guard_gpu) is not None, "上限 370W（没设 90%）→ 拦")
    cg.gpu = lambda: dict(base, name="NVIDIA GeForce GT 710")
    ok(raises(cg.guard_gpu) is not None, "不是 3090 → 拦")
    calls = []
    cg._req = lambda path, *a, **k: calls.append(path) or {}
    cg.gpu = lambda: dict(base, memclk=9501.0)
    w = cg.Watch()
    w.run()
    ok(w.bad and "显存频率" in w.bad and "/interrupt" in calls, "负载下显存 9501MHz（-500 没生效）→ 中断")
    calls.clear()
    cg.gpu = lambda: dict(base)
    w = cg.Watch()
    w.start()
    time.sleep(3.6)
    w.stop.set()
    w.join()
    ok(w.bad is None and not calls and w.peak["draw"] == 300.0, "正常读数（采到一次 300W）不误杀")

    print("== upscale")
    src = os.path.join(cg.dst(), "01_船_480.mp4")
    ffmpeg_color(src, 480, 864, 0.5)

    def fake_run(key, wf, out, label):        # 假装 SeedVR2：按工作流里的倍率放大
        m = wf[cg.NODES["seedvr2"]["mult"][0]]["inputs"]["resize_type.multiplier"]
        sent.append((key, wf, out))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-vf",
                        "scale=%d:%d" % (round(480 * m / 2) * 2, round(864 * m / 2) * 2), out], check=True)
        return 1.0, None
    cg.run = fake_run
    cg.cmd_upscale(["01_船"], "seedvr2", None)
    m = sent[-1][1][cg.NODES["seedvr2"]["mult"][0]]["inputs"]["resize_type.multiplier"]
    ok(480 * m >= 1080 and 864 * m >= 1920, "SeedVR2 倍率 %.4f 两边都够 1080×1920" % m)
    ok(cg.probe(os.path.join(cg.dst(), "01_船_1080.mp4"))[:2] == (1080, 1920), "SeedVR2 之后裁成正好 1080×1920")
    ok(not os.path.exists(os.path.join(cg.dst(), "01_船_seedvr2_raw.mp4")), "中间件删掉了")
    cg.cmd_upscale(["01_船"], "lanczos", None)
    ok(cg.probe(os.path.join(cg.dst(), "01_船_1080.mp4"))[:2] == (1080, 1920), "lanczos 出正好 1080×1920")
    ok(os.path.exists(os.path.join(cg.dst(), "01_船_1080_v1.mp4")), "重出时旧的改名 _v1，不覆盖")

    print("== upscale --image（静帧）")
    still = os.path.join(cg.dst(), "01_船.png")
    ffmpeg_color(still, 90, 160)

    def fake_run_img(key, wf, out, label):    # 假装 SeedVR2 静帧：读 LoadImage 写的那张，按倍率放大
        N = cg.NODES[key]
        m = wf[N["mult"][0]]["inputs"]["resize_type.multiplier"]
        sent.append((key, wf, out))
        src_ = imgs[wf[N["image"][0]]["inputs"]["image"]]
        w_, h_, _ = cg.probe(src_)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src_, "-vf",
                        "scale=%d:%d" % (round(w_ * m), round(h_ * m)), out], check=True)
        return 1.0, None
    imgs = {}
    cg.upload = lambda p: imgs.setdefault("up_" + os.path.basename(p), p) and "up_" + os.path.basename(p)
    cg.run = fake_run_img
    cg.cmd_upscale_image(["01_船"], "seedvr2", None)
    key, wf, _ = sent[-1]
    ok(key == "seedvr2_image", "静帧走 seedvr2_image 工作流（不是视频那份）")
    ok(wf[cg.NODES["seedvr2_image"]["chunk"][0]]["inputs"]["value"] is False, "单帧不开分段")
    out4k = os.path.join(cg.dst(), "01_船_2160x3840.png")
    ok(cg.probe(out4k)[:2] == (2160, 3840), "竖图默认放大成正好 2160×3840（实际 %s）" % (cg.probe(out4k)[:2],))
    ok(not [f for f in os.listdir(cg.dst()) if "seedvr2_raw" in f], "中间件删掉了")
    r = [x for x in cg.logs() if x.get("image")][-1]
    ok(r["how"] == "seedvr2_image" and r["out"] == "01_船_2160x3840.png", "日志记成静帧放大（%s）" % r)
    ok(cg.eta("upscale", "seedvr2_image") == 20, "静帧 ETA：只有一条记录时用缺省 20 秒/张")
    loose = os.path.join(d, "封面.png")                 # 任意路径：输出放在原图旁边
    ffmpeg_color(loose, 166, 92)
    cg.cmd_upscale_image([loose], "lanczos", "3840x2160")
    ok(cg.probe(os.path.join(d, "封面_3840x2160.png"))[:2] == (3840, 2160), "给路径 + lanczos → 原图旁边出 3840×2160")
    ok(raises(lambda: cg.cmd_upscale_image(["99_没有"], "seedvr2", None)) is not None, "档名没有图 → 拦")
    # 变异：倍率不加余量（×1.0 正好对齐时 round 会少 1px）也必须靠最后的裁切补齐 —— 拿掉裁切，尺寸就会错
    real_fit = cg._fit_vf
    cg._fit_vf = lambda w, h, tw, th: "null"
    cg.cmd_upscale_image(["01_船"], "seedvr2", None)
    ok(cg.probe(out4k)[:2] != (2160, 3840), "变异：去掉裁切，输出不再是正好 2160×3840（裁切不是摆设）")
    cg._fit_vf = real_fit
    for s in (30, 40):
        cg.log(dict(kind="upscale", how="seedvr2_image", image=True, sec=s))
    ok(cg.eta("upscale", "seedvr2_image") == 40, "两条以上记录 → ETA 用本项目静帧记录的中位数（%s）"
       % cg.eta("upscale", "seedvr2_image"))

    logs = [json.loads(l) for l in open(os.path.join(cg.dst(), "comfy_log.jsonl"), encoding="utf-8")]
    ok({"image", "video", "upscale", "promote"} <= {r["kind"] for r in logs}, "图/影片/放大/转正都记进 comfy_log.jsonl")
    ok(any(r.get("model") == "MiniMax H3" for r in logs), "影片记录写明 MiniMax H3（publish.py check 靠它要求署名）")

    print("\n%s" % ("全部通过" if not FAILS else "**%d 条失败**" % len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
