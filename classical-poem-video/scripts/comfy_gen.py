# -*- coding: utf-8 -*-
"""本机 3090 出图 / 出影片 / 影片放大（ComfyUI HTTP API，不用开浏览器）。

    python comfy_gen.py check                       # 服务、显卡、功耗上限、队列
    python comfy_gen.py list                        # 任务书里的图和影片，已出的打 ✓
    python comfy_gen.py show <档名> [▶档名]          # 打印完整提示词（影片那张表的写 ▶档名）
    python comfy_gen.py image [档名...] [--fast] [--seed N] [--size WxH]
    python comfy_gen.py video [档名...] [--res 480|768] [--turbo] [--seed N]
    python comfy_gen.py upscale <档名...> [--seedvr2|--lanczos] [--to WxH]
    python comfy_gen.py free                        # 卸模型、清显存/内存

不给档名＝还没出的全部（已有的跳过；点名的会重出，旧的改名 _v1）。全部落到 ../素材/生成/：
    图      <档名>.png         （--fast 出 <档名>_fast.png，只看构图，不进片）
    影片    <档名>.mp4 (768)   <档名>_480.mp4（试稿）
    放大    <档名>_1080.mp4    —— CLIPS 里写 dict(video="生成/<档名>_1080.mp4", ss=0, to=<秒>)
每一次生成都记进 ../素材/生成/comfy_log.jsonl（提示词、种子、步数、尺寸、耗时、功耗峰值）。

==== 任务书（和 el_web_image 同一份 出图任务书.md，换引擎不用改稿）====
图：沿用 el_web_image 的格式（固定開頭 / 固定結尾 A、E / | 檔 | 鏡 | 結尾 | 畫面句 |）。
影片：另加一张表，档名前加 ▶（不加会被当成图的那张表读走）：
    ## 影片固定開頭
    > ……（画风、年代、镜头不动/慢推，这类整片一样的话）
    ## 影片固定結尾
    > ……（不要文字、不要正脸、不要切镜头）
    | 影片 | 首幀 | 秒 | 動作句 |
    | ▶01_翻身 | 01_翻身 | 6 | 潛水員坐在船舷，向後翻身落進海裡…… |
首幀写图的档名＝图生影片（先出图、再让它动，构图最可控）；写 - ＝文生影片。

==== 本机（2026-10-20 实测，memory local-3090-model-licenses）====
  图  Qwen-Image-2512（Apache-2.0）：50 步约 3.5 分钟 / 4 步 Lightning 15~20 秒；中文字渲染正确
  影片 MiniMax H3（20 步）：480p 5 秒≈3 分钟、8 秒≈7 分钟；768p 8 秒≈30 分钟。原生上限 1344×768
      **发布说明要写「MiniMax H3 生成」并勾 AI 披露**；美/欧/英/韩不在它的免费商用范围
  放大 SeedVR2 3B（Apache-2.0）：768p 8 秒→1080p 约 9 分钟、显存约 10GB，锐、不闪
      lanczos（ffmpeg）几秒，偏软。SeedVR2 给特写/关键镜/首尾/有线条文字的；lanczos 给过场、烟雾黑暗、试稿
  流程：480p 试稿 → 768p 定稿 → 关键镜 SeedVR2、其余 lanczos

==== 硬件红线（脚本会拦）====
  - 3090 是矿卡：功耗上限必须 ≤ 336W（Afterburner 90%），负载下显存频率应 ≈ 9000MHz（-500）。
    提交前查上限；跑的时候每 3 秒采一次，功耗 > 345W 或显存频率 > 9150MHz 就 /interrupt 并退出。
  - 内存 32GB：图、影片、放大不能同时跑。提交前队列必须是空的（有别的任务就等）；
    换一类模型前先 POST /free（记在 %TEMP%/comfy_gen_family.txt）。
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import el_web_image as ew  # noqa: E402  任务书解析共用

URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
WF_DIRS = [os.path.join(HERE, "comfy"),
           os.path.expanduser("~/.claude/skills/classical-poem-video/scripts/comfy")]
STATE = os.path.join(tempfile.gettempdir(), "comfy_gen_family.txt")

POWER_LIMIT_MAX = 336.0     # W，90% 功耗 = 333
POWER_DRAW_MAX = 345.0
MEMCLK_MAX = 9150           # MHz，-500 之后负载约 9000；没降就是 9500

# 节点号：从 ComfyUI 前端 app.graphToPrompt() 导出的 API 格式（comfy/*.api.json）。
# ComfyUI / 模板升级后节点号可能变 —— check 会核对 class_type，对不上就重新导出（见 references/visuals.md）。
NODES = {
    "qwen2512": dict(prompt=("238:227", "CLIPTextEncode"), latent=("238:232", "EmptySD3LatentImage"),
                     fast=("238:229", "PrimitiveBoolean"), sampler=("238:230", "KSampler"),
                     save=("60", "SaveImage")),
    "h3_t2v": dict(gen=("140:131", "MiniMaxH3ImageToVideo"), secs=("140:133", "PrimitiveFloat"),
                   seed=("140:129", "RandomNoise"), turbo=("140:139", "PrimitiveBoolean"),
                   save=("92", "SaveVideo")),
    "h3_i2v": dict(gen=("105:104", "MiniMaxH3ImageToVideo"), secs=("105:111", "PrimitiveFloat"),
                   seed=("105:15", "RandomNoise"), turbo=("105:126", "PrimitiveBoolean"),
                   image=("114", "LoadImage"), save=("92", "SaveVideo")),
    "seedvr2": dict(video=("73", "LoadVideo"), mult=("66:57", "ResizeImageMaskNode"),
                    chunk=("66:105", "PrimitiveBoolean"), save=("76", "SaveVideo")),
}
FAMILY = {"qwen2512": "image", "h3_t2v": "video", "h3_i2v": "video", "seedvr2": "upscale"}
H3_SIZE = {480: (864, 480), 768: (1344, 768)}       # 横；竖版对调。都是 32 的倍数


# ---------------------------------------------------------------- 路径
def proj():
    return os.path.dirname(os.path.dirname(os.path.abspath(ew.BRIEF)))


def dst():
    return ew.DST


def set_proj(p):
    """--proj：脚本不在 <项目>/build/ 里时（测试、从仓库直接跑）指定项目根。"""
    ew.BRIEF = os.path.join(p, "出图任务书.md")
    ew.DST = os.path.join(p, "素材", "生成")


# ---------------------------------------------------------------- HTTP
def _req(path, data=None, method=None, timeout=60, ctype="application/json"):
    body = data if (data is None or isinstance(data, bytes)) else json.dumps(data).encode("utf-8")
    r = urllib.request.Request(URL + path, data=body, method=method or ("POST" if body is not None else "GET"))
    if body is not None:
        r.add_header("Content-Type", ctype)
    with urllib.request.urlopen(r, timeout=timeout) as f:
        raw = f.read()
    try:
        return json.loads(raw)
    except Exception:
        return raw


def upload(path):
    """把本地文件传进 ComfyUI 的 input/（LoadImage、LoadVideo 都从那里读）。名字带内容哈希，不撞名。"""
    blob = open(path, "rb").read()
    name = "vm_%s_%s" % (hashlib.sha1(blob).hexdigest()[:10], re.sub(r"[^\w.\-]", "_", os.path.basename(path)))
    b = uuid.uuid4().hex
    parts = [("--%s\r\nContent-Disposition: form-data; name=\"image\"; filename=\"%s\"\r\n"
              "Content-Type: application/octet-stream\r\n\r\n" % (b, name)).encode("utf-8"), blob,
             ("\r\n--%s\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue"
              "\r\n--%s--\r\n" % (b, b)).encode("utf-8")]
    r = _req("/upload/image", b"".join(parts), ctype="multipart/form-data; boundary=" + b, timeout=300)
    return (r.get("subfolder") + "/" if r.get("subfolder") else "") + r["name"]


# ---------------------------------------------------------------- 显卡
def gpu():
    q = "name,power.limit,power.draw,clocks.mem,memory.used,memory.total"
    out = subprocess.run(["nvidia-smi", "--query-gpu=" + q, "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout.strip().splitlines()
    if not out:
        return None
    v = [x.strip() for x in out[0].split(",")]
    f = lambda s: float(s) if re.match(r"^[\d.]+$", s) else 0.0
    return dict(name=v[0], limit=f(v[1]), draw=f(v[2]), memclk=f(v[3]), used=f(v[4]), total=f(v[5]))


def guard_gpu():
    g = gpu()
    if not g or "3090" not in g["name"]:
        sys.exit("!!! 没看到 RTX 3090（%s）。3090 不在机上时别跑 ComfyUI 生成。" % (g or {}).get("name"))
    if g["limit"] > POWER_LIMIT_MAX:
        sys.exit("!!! 功耗上限 %.0fW > %.0fW：Afterburner 没设 90%%（矿卡，必须先设好再跑）。"
                 % (g["limit"], POWER_LIMIT_MAX))
    return g


class Watch(threading.Thread):
    """生成期间每 3 秒采一次功耗和显存频率；越线就 /interrupt。"""

    def __init__(self):
        super().__init__(daemon=True)
        self.peak = dict(draw=0.0, memclk=0.0, used=0.0)
        self.bad = None
        self.stop = threading.Event()

    def run(self):
        while not self.stop.wait(3):
            g = gpu()
            if not g:
                continue
            for k in self.peak:
                self.peak[k] = max(self.peak[k], g[k])
            if g["draw"] > POWER_DRAW_MAX:
                self.bad = "功耗 %.0fW > %.0fW" % (g["draw"], POWER_DRAW_MAX)
            elif g["memclk"] > MEMCLK_MAX:
                self.bad = "显存频率 %.0fMHz > %d（Afterburner 显存 -500 没生效）" % (g["memclk"], MEMCLK_MAX)
            if self.bad:
                try:
                    _req("/interrupt", {})
                except Exception:
                    pass
                return


# ---------------------------------------------------------------- 队列与执行
def wait_idle():
    t0 = time.time()
    while True:
        q = _req("/queue")
        n = len(q.get("queue_running", [])) + len(q.get("queue_pending", []))
        if not n:
            return
        if time.time() - t0 < 1:
            print("   ComfyUI 队列里还有 %d 个任务（别的会话或界面上点的），等它跑完再交 —— 两类模型同时跑会爆 32GB 内存" % n)
        time.sleep(10)


def switch_family(fam):
    last = open(STATE).read().strip() if os.path.exists(STATE) else ""
    if last != fam:
        _req("/free", {"unload_models": True, "free_memory": True})
        print("   /free（%s → %s）" % (last or "?", fam))
        time.sleep(3)
    open(STATE, "w").write(fam)


def load_wf(key):
    for d in WF_DIRS:
        p = os.path.join(d, key + ".api.json")
        if os.path.exists(p):
            wf = json.load(open(p, encoding="utf-8"))
            for role, (nid, ct) in NODES[key].items():
                got = wf.get(nid, {}).get("class_type")
                if got != ct:
                    sys.exit("!!! %s 的节点 %s（%s）应是 %s，实际 %s —— 工作流变了，重新导出 API 格式"
                             % (key, nid, role, ct, got))
            return wf
    sys.exit("!!! 找不到 comfy/%s.api.json" % key)


def run(key, wf, out_path, label):
    """交一个 prompt，等它跑完，把输出存到 out_path。返回 (秒, 峰值)。"""
    guard_gpu()
    wait_idle()
    switch_family(FAMILY[key])
    t0 = time.time()
    pid = _req("/prompt", {"prompt": wf, "client_id": "vmskill"})["prompt_id"]
    w = Watch()
    w.start()
    last = ""
    try:
        while True:
            time.sleep(5)
            if w.bad:
                sys.exit("!!! %s：%s，已中断。先检查 Afterburner 再重跑。" % (label, w.bad))
            h = _req("/history/" + pid).get(pid)
            if h:
                st = h.get("status", {})
                if st.get("status_str") == "error" or not st.get("completed", True):
                    msg = [m for m in st.get("messages", []) if m[0] == "execution_error"]
                    sys.exit("!!! %s 失败：%s" % (label, json.dumps(msg, ensure_ascii=False)[:800]))
                break
            el = int(time.time() - t0) // 60
            if el != last:                       # 一分钟报一次，别刷屏
                print("   … %s %d 分钟" % (label, el), flush=True)
                last = el
    finally:
        w.stop.set()
    save = NODES[key]["save"][0]
    files = [f for v in h["outputs"].get(save, {}).values() if isinstance(v, list)
             for f in v if isinstance(f, dict) and f.get("filename")]
    if not files:
        sys.exit("!!! %s 跑完了但节点 %s 没有输出" % (label, save))
    f = files[0]
    q = urllib.parse.urlencode(dict(filename=f["filename"], subfolder=f.get("subfolder", ""),
                                    type=f.get("type", "output")))
    data = _req("/view?" + q, timeout=600)
    _keep_old(out_path)
    open(out_path, "wb").write(data)
    return time.time() - t0, w.peak


def _keep_old(p):
    if os.path.exists(p):
        b, e = os.path.splitext(p)
        k = 1
        while os.path.exists("%s_v%d%s" % (b, k, e)):
            k += 1
        os.rename(p, "%s_v%d%s" % (b, k, e))


def log(rec):
    os.makedirs(dst(), exist_ok=True)
    rec["date"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join(dst(), "comfy_log.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def seed_of(name, seed):
    return seed if seed is not None else int(hashlib.sha1(name.encode("utf-8")).hexdigest()[:12], 16)


def probe(p):
    o = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height:format=duration", "-of", "json", p],
                       capture_output=True, text=True).stdout
    j = json.loads(o or "{}")
    s = (j.get("streams") or [{}])[0]
    return s.get("width"), s.get("height"), float(j.get("format", {}).get("duration") or 0)


# ---------------------------------------------------------------- 任务书
def vertical():
    head = ew._brief()[0]
    return bool(re.search(r"9:16|豎構圖|竖构图|豎版|竖版", head))


def vbrief():
    md = open(ew.BRIEF, encoding="utf-8").read()

    def block(t):
        m = re.search(r"## " + re.escape(t) + r"[^\n]*\n\n> (.+?)\n", md)
        return m.group(1).replace("**", "").strip() if m else ""

    rows = {}
    for line in md.split("\n"):
        m = re.match(r"\| ▶(\d\d[a-z]?_[^ |]+) \| ([^|]+) \| ([\d.]+) \| (.+) \|$", line)
        if m:
            ff = m.group(2).strip()
            rows[m.group(1)] = (None if ff in ("-", "—", "") else ff, float(m.group(3)), m.group(4).strip())
    return block("影片固定開頭"), block("影片固定結尾"), rows


def vprompt(name):
    head, tail, rows = vbrief()
    return " ".join(x for x in (head, rows[name][2], tail) if x)


# ---------------------------------------------------------------- 命令
def cmd_check():
    try:
        s = _req("/system_stats", timeout=5)
    except Exception as e:
        sys.exit("!!! ComfyUI 没开（%s）：双击 D:\\MiniMax-H3\\Start-MiniMax-H3.cmd" % e)
    g = gpu()
    print("ComfyUI %s  内存剩 %.1fGB" % (s["system"]["comfyui_version"], s["system"]["ram_free"] / 2 ** 30))
    if g:
        print("%s  功耗上限 %.0fW  当前 %.0fW  显存 %d/%dMB  显存频率 %dMHz（空闲时低是正常的）"
              % (g["name"], g["limit"], g["draw"], g["used"], g["total"], g["memclk"]))
    guard_gpu()
    q = _req("/queue")
    print("队列：在跑 %d，排队 %d" % (len(q["queue_running"]), len(q["queue_pending"])))
    for k in NODES:
        load_wf(k)
    print("工作流节点核对通过：", ", ".join(NODES))


def cmd_list():
    head, ends, extra, desc, rows = ew._brief()
    d = dst()
    for n in rows:
        print(("✓" if os.path.exists(os.path.join(d, n + ".png")) else "·"), "图  ", n)
    if os.path.exists(ew.BRIEF):
        for n, (ff, secs, _) in vbrief()[2].items():
            have = [s for s in ("", "_480", "_1080") if os.path.exists(os.path.join(d, n + s + ".mp4"))]
            print(("✓" if have else "·"), "影片", n, "首幀=%s %.0fs" % (ff or "（文生）", secs),
                  " ".join((s or "_768") for s in have))


def cmd_image(names, fast, seed, size):
    rows = ew._brief()[4]
    todo = names or [n for n in rows if not os.path.exists(os.path.join(dst(), n + ".png"))]
    if size:
        w, h = map(int, size.lower().split("x"))
    else:
        w, h = (928, 1664) if vertical() else (1664, 928)
    wf0 = load_wf("qwen2512")
    for i, n in enumerate(todo, 1):
        if n not in rows:
            sys.exit("!!! 任务书里没有 %s" % n)
        bad = ew.check(n)
        if bad:
            print("!! %s 拼出来有病句：%s" % (n, bad))
        wf = json.loads(json.dumps(wf0))
        p, sd = ew.prompt(n), seed_of(n, seed)
        N = NODES["qwen2512"]
        wf[N["prompt"][0]]["inputs"]["text"] = p
        wf[N["latent"][0]]["inputs"].update(width=w, height=h)
        wf[N["fast"][0]]["inputs"]["value"] = bool(fast)
        wf[N["sampler"][0]]["inputs"]["seed"] = sd
        wf[N["save"][0]]["inputs"]["filename_prefix"] = "vmskill/" + n
        out = os.path.join(dst(), n + ("_fast" if fast else "") + ".png")
        os.makedirs(dst(), exist_ok=True)
        print("[%d/%d] 图 %s  %dx%d  %s  seed=%d" % (i, len(todo), n, w, h, "4 步" if fast else "50 步", sd))
        sec, peak = run("qwen2512", wf, out, n)
        log(dict(kind="image", name=n, model="Qwen-Image-2512", license="Apache-2.0", steps=4 if fast else 50,
                 size=[w, h], seed=sd, prompt=p, out=os.path.basename(out), sec=round(sec), peak=peak))
        print("   存 %s（%.0f 秒，峰值 %.0fW / %.0fMHz）" % (os.path.basename(out), sec, peak["draw"], peak["memclk"]))


def cmd_video(names, res, turbo, seed):
    _, _, rows = vbrief()
    suf = "" if res == 768 else "_%d" % res
    todo = names or [n for n in rows if not os.path.exists(os.path.join(dst(), n + suf + ".mp4"))]
    w, h = H3_SIZE[res]
    if vertical():
        w, h = h, w
    for i, n in enumerate(todo, 1):
        if n not in rows:
            sys.exit("!!! 任务书影片表里没有 ▶%s" % n)
        ff, secs, _ = rows[n]
        key = "h3_i2v" if ff else "h3_t2v"
        wf = load_wf(key)
        N = NODES[key]
        p, sd = vprompt(n), seed_of(n, seed)
        g = wf[N["gen"][0]]["inputs"]
        g.update(prompt=p, width=w, height=h)     # 不走 ResolutionSelector：尺寸直接给死
        wf[N["secs"][0]]["inputs"]["value"] = float(secs)
        wf[N["seed"][0]]["inputs"]["noise_seed"] = sd
        wf[N["turbo"][0]]["inputs"]["value"] = bool(turbo)
        wf[N["save"][0]]["inputs"]["filename_prefix"] = "vmskill/" + n
        if ff:
            src = os.path.join(dst(), ff + ".png")
            if not os.path.exists(src):
                sys.exit("!!! %s 的首幀 %s.png 还没出（先 image %s）" % (n, ff, ff))
            fw, fh, _ = probe(src)
            if fw and (fw > fh) != (w > h):
                sys.exit("!!! 首幀 %s 是 %dx%d，和影片 %dx%d 横竖不一致" % (ff, fw, fh, w, h))
            wf[N["image"][0]]["inputs"]["image"] = upload(src)
        out = os.path.join(dst(), n + suf + ".mp4")
        print("[%d/%d] 影片 %s  %s  %dx%d  %.0f 秒  %s  seed=%d"
              % (i, len(todo), n, "图生（%s）" % ff if ff else "文生", w, h, secs,
                 "turbo 8 步" if turbo else "20 步", sd))
        sec, peak = run(key, wf, out, n)
        vw, vh, dur = probe(out)
        log(dict(kind="video", name=n, model="MiniMax H3", license="MiniMax H3 community（署名＋AI 披露）",
                 mode="i2v" if ff else "t2v", first_frame=ff, steps=8 if turbo else 20, size=[vw, vh],
                 secs=secs, dur=round(dur, 2), seed=sd, prompt=p, out=os.path.basename(out),
                 sec=round(sec), peak=peak))
        print("   存 %s  %sx%s %.2fs（%.0f 秒，峰值 %.0fW / %.0fMHz）"
              % (os.path.basename(out), vw, vh, dur, sec, peak["draw"], peak["memclk"]))


def _fit_vf(w, h, tw, th):
    """铺满再居中裁（cover）。"""
    return "scale=%d:%d:force_original_aspect_ratio=increase:flags=lanczos,crop=%d:%d,setsar=1" % (tw, th, tw, th)


def cmd_upscale(names, how, to):
    for n in names:
        src = None
        for s in ("", "_480"):
            p = os.path.join(dst(), n + s + ".mp4")
            if os.path.exists(p):
                src = p
                break
        if not src:
            sys.exit("!!! 没有 %s.mp4 / %s_480.mp4" % (n, n))
        w, h, dur = probe(src)
        tw, th = map(int, to.lower().split("x")) if to else ((1080, 1920) if h > w else (1920, 1080))
        out = os.path.join(dst(), n + "_1080.mp4")
        t0 = time.time()
        if how == "lanczos":
            _keep_old(out)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", _fit_vf(w, h, tw, th),
                            "-c:v", "libx264", "-crf", "14", "-preset", "slow", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-b:a", "192k", out], check=True)
            peak = None
        else:
            wf = load_wf("seedvr2")
            N = NODES["seedvr2"]
            mult = max(tw / w, th / h) * 1.002          # 宁大一点，再裁
            wf[N["video"][0]]["inputs"]["file"] = upload(src)
            wf[N["mult"][0]]["inputs"]["resize_type.multiplier"] = round(mult, 4)
            wf[N["chunk"][0]]["inputs"]["value"] = True  # 分段处理，防爆内存
            wf[N["save"][0]]["inputs"]["filename_prefix"] = "vmskill/" + n + "_seedvr2"
            raw = os.path.join(dst(), n + "_seedvr2_raw.mp4")
            print("upscale %s  %sx%s → ×%.4f → 裁 %dx%d（SeedVR2）" % (n, w, h, mult, tw, th))
            _, peak = run("seedvr2", wf, raw, n)
            rw, rh, _ = probe(raw)
            _keep_old(out)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", raw, "-vf", _fit_vf(rw, rh, tw, th),
                            "-c:v", "libx264", "-crf", "14", "-preset", "slow", "-pix_fmt", "yuv420p",
                            "-c:a", "copy", out], check=True)
            os.remove(raw)
        ow, oh, odur = probe(out)
        sec = time.time() - t0
        log(dict(kind="upscale", name=n, how=how, src=os.path.basename(src), size=[ow, oh],
                 dur=round(odur, 2), out=os.path.basename(out), sec=round(sec), peak=peak))
        print("   存 %s  %sx%s %.2fs（%.0f 秒）" % (os.path.basename(out), ow, oh, odur, sec))


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("cmd", nargs="?")
    ap.add_argument("names", nargs="*")
    ap.add_argument("--proj")
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--turbo", action="store_true")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--size")
    ap.add_argument("--res", type=int, default=768, choices=(480, 768))
    ap.add_argument("--seedvr2", action="store_const", const="seedvr2", dest="how")
    ap.add_argument("--lanczos", action="store_const", const="lanczos", dest="how")
    ap.add_argument("--to")
    a = ap.parse_args()
    if a.proj:
        set_proj(os.path.abspath(a.proj))
    if a.cmd == "check":
        cmd_check()
    elif a.cmd == "list":
        cmd_list()
    elif a.cmd == "show":
        for n in a.names:                       # 图和影片可以同名：影片那张表的写 ▶档名
            p = vprompt(n[1:]) if n.startswith("▶") else ew.prompt(n)
            print("== %s %d 字\n%s" % (n, len(p), p))
    elif a.cmd == "image":
        cmd_image(a.names, a.fast, a.seed, a.size)
    elif a.cmd == "video":
        cmd_video([n.lstrip("▶") for n in a.names], a.res, a.turbo, a.seed)
    elif a.cmd == "upscale":
        if not a.names:
            sys.exit("!!! upscale 要点名（哪几镜用 SeedVR2、哪几镜用 lanczos 是逐镜判断的）")
        cmd_upscale(a.names, a.how or "lanczos", a.to)
    elif a.cmd == "free":
        _req("/free", {"unload_models": True, "free_memory": True})
        if os.path.exists(STATE):
            os.remove(STATE)
        print("已 /free")
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
