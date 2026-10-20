# -*- coding: utf-8 -*-
"""本机 3090 出图 / 出影片 / 影片放大（ComfyUI HTTP API，不用开浏览器）。

    python comfy_gen.py start                       # 没开就把 ComfyUI 在后台拉起来（不弹浏览器）
    python comfy_gen.py check                       # 服务、显卡、功耗上限、队列、工作流节点
    python comfy_gen.py list                        # 任务书里的图和影片，已出的打 ✓
    python comfy_gen.py show <档名> [▶档名]          # 打印完整提示词（影片那张表的写 ▶档名）
    python comfy_gen.py image [档名...] --fast [--variants N] [--seed N]   # 候选：4 步，进 候选/<档名>/
    python comfy_gen.py image [档名...] [--variants N] [--seed N]          # 50 步；--variants 也进候选
    python comfy_gen.py promote <档名> [候选文件名|序号]                  # 选定的候选转正成 <档名>.png
    python comfy_gen.py sheet [档名...] | sheet --cand <档名>              # 拼联络表（带档名）
    python comfy_gen.py video [档名...] [--res 480|768] [--turbo] [--seed N]
    python comfy_gen.py strip <档名>                # 影片 6 帧条 + 切镜检测
    python comfy_gen.py upscale <档名...> [--seedvr2|--lanczos] [--to WxH]
    python comfy_gen.py notes                       # 素材/生成/生成记录.md（每个成品是怎么来的）
    python comfy_gen.py free                        # 卸模型、清显存/内存

全部落到 ../素材/生成/：
    图      <档名>.png（定稿）       候选/<档名>/<步数>s-<种子>.png（--fast / --variants）
    影片    <档名>.mp4 (768)   <档名>_480.mp4（试稿）
    放大    <档名>_1080.mp4    —— CLIPS 里写 dict(video="生成/<档名>_1080.mp4", ss=0, to="full")
每一次生成都记进 ../素材/生成/comfy_log.jsonl（提示词、种子、步数、尺寸、耗时、功耗/温度峰值、切镜）。

==== 推荐顺序（2026-10-20《我想回家》复盘后定）====
  1. `image --fast` 全出一遍 → `sheet --cand` 或 `sheet` 看构图、道具、分格 → 改任务书再出
     （第一轮直接上 50 步，16 张里 8 张重出，白跑约 40 分钟）
  2. 只当影片首帧的图**不出 50 步**：`video` 发现首帧没出会自己补 4 步版（H3 会重新渲染首帧）
  3. 旁白定了先 `make_story_*.py vidplan write`，秒数由镜长算，别手抄
  4. `video --res 480` 试稿 → `strip` 看帧条（切镜自动报）→ 只给开场/白天细节多的关键镜上 768p
  5. 放大：关键镜 SeedVR2、暗/烟雾/过场 lanczos

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

==== 本机（实测，memory local-3090-model-licenses）====
  图  Qwen-Image-2512（Apache-2.0）：50 步 928×1664 约 3.5 分钟 / 4 步 10~20 秒（冷启动 70 秒）
  影片 MiniMax H3（20 步）：480p 约 1 分钟/秒成片；768p 约 5.3 分钟/秒成片（12 秒 67 分钟）
      **发布说明要写「MiniMax H3 生成」并勾 AI 披露**；美/欧/英/韩不在它的免费商用范围
  放大 SeedVR2 3B（Apache-2.0）：约 70 秒/秒成片（480 或 768 进都差不多），显存约 10GB
      lanczos（ffmpeg）几秒，偏软。SeedVR2 给特写/关键镜/首尾/有线条文字的；lanczos 给过场、烟雾黑暗、试稿

==== 硬件红线（脚本会拦）====
  - 3090 是矿卡：功耗上限必须 ≤ 336W（Afterburner 90%），负载下显存频率应 ≈ 9000MHz（-500）。
    提交前查上限；跑的时候每 3 秒采一次，功耗 > 345W 或显存频率 > 9150MHz 就 /interrupt 并退出。
  - 内存 32GB：图、影片、放大不能同时跑（CPU 上的 upscale.py/EDSR 也算，一张 10GB）。提交前队列必须是空的；
    换一类模型前先 POST /free（记在 %TEMP%/comfy_gen_family.txt）。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
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
COMFY_ROOT = os.environ.get("COMFY_ROOT", r"D:\MiniMax-H3")
WF_DIRS = [os.path.join(HERE, "comfy"),
           os.path.expanduser("~/.claude/skills/classical-poem-video/scripts/comfy")]
STATE = os.path.join(tempfile.gettempdir(), "comfy_gen_family.txt")

POWER_LIMIT_MAX = 336.0     # W，90% 功耗 = 333
POWER_DRAW_MAX = 345.0
MEMCLK_MAX = 9150           # MHz，-500 之后负载约 9000；没降就是 9500
TEMP_WARN = 83              # °C，核心温度；显存结温 nvidia-smi 读不到（要 HWiNFO）
CUT_THRESHOLD = 12          # ffmpeg scdet：10-20 实测抓到镜20 第 4.04 秒的自切，另三段零误报

# 节点号：从 ComfyUI 前端 app.graphToPrompt() 导出的 API 格式（comfy/*.api.json）。
# ComfyUI / 模板升级后节点号可能变 —— check 会核对 class_type，对不上就重新导出（见 references/sourcing.md）。
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

# 预计耗时（秒）的缺省值：2026-10-20 实测；项目里有记录时用本项目的中位数。
ETA_DEFAULT = {("image", 50): 205, ("image", 4): 12, ("video", 480): 60, ("video", 768): 320,
               ("upscale", "seedvr2"): 71}
COLD = 70                    # 换模型后的首个任务多出来的加载时间


# ---------------------------------------------------------------- 路径
def proj():
    return os.path.dirname(os.path.dirname(os.path.abspath(ew.BRIEF)))


def dst():
    return ew.DST


def cand_dir(name):
    return os.path.join(dst(), "候选", name)


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


def alive(timeout=3):
    try:
        return _req("/system_stats", timeout=timeout)
    except Exception:
        return None


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
    q = "name,power.limit,power.draw,clocks.mem,memory.used,memory.total,temperature.gpu"
    out = subprocess.run(["nvidia-smi", "--query-gpu=" + q, "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout.strip().splitlines()
    if not out:
        return None
    v = [x.strip() for x in out[0].split(",")] + ["0"]
    f = lambda s: float(s) if re.match(r"^[\d.]+$", s) else 0.0
    return dict(name=v[0], limit=f(v[1]), draw=f(v[2]), memclk=f(v[3]), used=f(v[4]), total=f(v[5]), temp=f(v[6]))


def guard_gpu():
    g = gpu()
    if not g or "3090" not in g["name"]:
        sys.exit("!!! 没看到 RTX 3090（%s）。3090 不在机上时别跑 ComfyUI 生成。" % (g or {}).get("name"))
    if g["limit"] > POWER_LIMIT_MAX:
        sys.exit("!!! 功耗上限 %.0fW > %.0fW：Afterburner 没设 90%%（矿卡，必须先设好再跑）。"
                 % (g["limit"], POWER_LIMIT_MAX))
    return g


class Watch(threading.Thread):
    """生成期间每 3 秒采一次功耗、显存频率、核心温度；功耗/频率越线就 /interrupt，温度只提示。"""

    def __init__(self):
        super().__init__(daemon=True)
        self.peak = dict(draw=0.0, memclk=0.0, used=0.0, temp=0.0)
        self.bad = None
        self.stop = threading.Event()

    def run(self):
        while not self.stop.wait(3):
            g = gpu()
            if not g:
                continue
            for k in self.peak:
                self.peak[k] = max(self.peak[k], g.get(k, 0.0))
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


def _peak_txt(peak):
    if not peak:
        return ""
    t = "峰值 %.0fW / %.0fMHz / %.0f°C" % (peak["draw"], peak["memclk"], peak.get("temp", 0))
    return t + ("  !! 核心温度超过 %d°C，看一眼风扇和显存结温（HWiNFO）" % TEMP_WARN if peak.get("temp", 0) > TEMP_WARN else "")


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
    dead = 0.0
    try:
        while True:
            time.sleep(5)
            if w.bad:
                sys.exit("!!! %s：%s，已中断。先检查 Afterburner 再重跑。" % (label, w.bad))
            try:
                h = _req("/history/" + pid, timeout=30).get(pid)
                dead = 0.0
            except Exception as e:
                # 2026-10-20：CPU 上同时跑 EDSR（upscale.py，一张 10GB），32GB 内存被挤爆，
                # ComfyUI 整个被换出到虚拟内存、HTTP 不响应，旧版在这里直接抛 TimeoutError 退出。
                dead += 35
                print("   ComfyUI %ds 没响应（%s）—— 多半是内存被别的进程挤爆、它被换出了；"
                      "看任务管理器里有没有在跑 upscale.py / 别的大进程" % (dead, type(e).__name__), flush=True)
                if dead >= 300:
                    sys.exit("!!! %s：ComfyUI 5 分钟没响应。停掉吃内存的进程；还不行就重启 ComfyUI 再重跑"
                             "（已出的不会重出）" % label)
                continue
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
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    open(out_path, "wb").write(data)
    return time.time() - t0, w.peak


def _keep_old(p):
    if os.path.exists(p):
        b, e = os.path.splitext(p)
        k = 1
        while os.path.exists("%s_v%d%s" % (b, k, e)):
            k += 1
        os.rename(p, "%s_v%d%s" % (b, k, e))


def logs():
    p = os.path.join(dst(), "comfy_log.jsonl")
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []


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
                       capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    j = json.loads(o or "{}")
    s = (j.get("streams") or [{}])[0]
    return s.get("width"), s.get("height"), float(j.get("format", {}).get("duration") or 0)


def cuts(path, thr=CUT_THRESHOLD):
    """影片里的硬切（ffmpeg scdet）。生成影片本该是一个连续镜头，有切 = H3 自己拍成了多镜。"""
    out = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-vf", "scdet=threshold=%g" % thr,
                          "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8",
                         errors="replace").stderr
    return [round(float(t), 2) for t in re.findall(r"lavfi\.scd\.time: ([\d.]+)", out)]


# ---------------------------------------------------------------- 预计耗时
def eta(kind, key, secs=1.0):
    """按本项目 comfy_log 的中位数估（没有记录用缺省）。影片和放大是「秒/秒成片」。"""
    xs = []
    for r in logs():
        if r.get("kind") != kind or not r.get("sec"):
            continue
        if kind == "image" and r.get("steps") == key:
            xs.append(r["sec"])
        elif kind == "video" and min([x for x in (r.get("size") or []) if x] or [0]) == key and r.get("dur"):
            xs.append(r["sec"] / r["dur"])
        elif kind == "upscale" and r.get("how") == key and r.get("dur"):
            xs.append(r["sec"] / r["dur"])
    per = sorted(xs)[len(xs) // 2] if len(xs) >= 2 else ETA_DEFAULT.get((kind, key), 60)
    return per * (secs if kind != "image" else 1)


def say_eta(total, n):
    m = total / 60.0
    print(">>> %d 个任务，预计 %s%s" % (n, ("%.0f 分钟" % m) if m < 90 else ("%.1f 小时" % (m / 60)),
                                       "（长任务，适合晚上跑：run_in_background 交出去等通知）" if m > 60 else ""))


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
def cmd_start():
    """照 Start-MiniMax-H3.ps1 的参数把 ComfyUI 拉起来，但**不弹浏览器**（那个脚本最后会打开默认浏览器）。"""
    if alive():
        print("ComfyUI 已经在跑：%s" % URL)
        return
    if os.name != "nt":
        sys.exit("!!! start 只写了 Windows 便携版；别的系统自己起 ComfyUI")
    port = os.path.join(COMFY_ROOT, "ComfyUI_windows_portable")
    py = os.path.join(port, "python_embeded", "python.exe")
    if not os.path.exists(py):
        sys.exit("!!! 找不到 %s（COMFY_ROOT 设对了没有）" % py)
    env = dict(os.environ, HF_HOME=os.path.join(COMFY_ROOT, "cache", "huggingface"),
               TORCH_HOME=os.path.join(COMFY_ROOT, "cache", "torch"), HF_HUB_OFFLINE="1",
               TRANSFORMERS_OFFLINE="1", TEMP=os.path.join(COMFY_ROOT, "temp"), TMP=os.path.join(COMFY_ROOT, "temp"))
    args = [py, "-s", os.path.join(port, "ComfyUI", "main.py"), "--windows-standalone-build", "--disable-auto-launch",
            "--offline", "--listen", "127.0.0.1", "--port", "8188", "--reserve-vram", "1.5",
            "--output-directory", os.path.join(COMFY_ROOT, "output"), "--temp-directory", env["TEMP"]]
    logs_dir = os.path.join(COMFY_ROOT, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    subprocess.Popen(args, cwd=port, env=env,
                     stdout=open(os.path.join(logs_dir, "comfyui-launch.log"), "w"),
                     stderr=open(os.path.join(logs_dir, "comfyui-launch-error.log"), "w"),
                     creationflags=0x00000008 | 0x08000000)       # DETACHED_PROCESS | CREATE_NO_WINDOW
    for i in range(90):
        time.sleep(2)
        if alive():
            print("ComfyUI 起来了（%d 秒）：%s" % ((i + 1) * 2, URL))
            return
    sys.exit("!!! 3 分钟没起来，看 %s\\comfyui-launch-error.log" % logs_dir)


def cmd_check():
    s = alive(5)
    if not s:
        sys.exit("!!! ComfyUI 没开：python comfy_gen.py start")
    g = gpu()
    print("ComfyUI %s  内存剩 %.1fGB" % (s["system"]["comfyui_version"], s["system"]["ram_free"] / 2 ** 30))
    if g:
        print("%s  功耗上限 %.0fW  当前 %.0fW  显存 %d/%dMB  显存频率 %dMHz  %d°C（空闲时频率低是正常的）"
              % (g["name"], g["limit"], g["draw"], g["used"], g["total"], g["memclk"], g["temp"]))
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
        c = len([f for f in os.listdir(cand_dir(n)) if f.endswith(".png")]) if os.path.isdir(cand_dir(n)) else 0
        print(("✓" if os.path.exists(os.path.join(d, n + ".png")) else "·"), "图  ", n, ("（候选 %d）" % c) if c else "")
    if os.path.exists(ew.BRIEF):
        for n, (ff, secs, _) in vbrief()[2].items():
            have = [s for s in ("", "_480", "_1080") if os.path.exists(os.path.join(d, n + s + ".mp4"))]
            print(("✓" if have else "·"), "影片", n, "首幀=%s %gs" % (ff or "（文生）", secs),
                  " ".join((s or "_768") for s in have))


def _gen_image(n, steps, sd, w, h, out, wf0, label, extra=None):
    wf = json.loads(json.dumps(wf0))
    p = ew.prompt(n)
    N = NODES["qwen2512"]
    wf[N["prompt"][0]]["inputs"]["text"] = p
    wf[N["latent"][0]]["inputs"].update(width=w, height=h)
    wf[N["fast"][0]]["inputs"]["value"] = steps == 4
    wf[N["sampler"][0]]["inputs"]["seed"] = sd
    wf[N["save"][0]]["inputs"]["filename_prefix"] = "vmskill/" + n
    sec, peak = run("qwen2512", wf, out, label)
    rec = dict(kind="image", name=n, model="Qwen-Image-2512", license="Apache-2.0", steps=steps,
               size=[w, h], seed=sd, prompt=p, out=os.path.relpath(out, dst()).replace("\\", "/"),
               sec=round(sec), peak=peak)
    rec.update(extra or {})
    log(rec)
    print("   存 %s（%.0f 秒，%s）" % (rec["out"], sec, _peak_txt(peak)))


def cmd_image(names, fast, seed, size, variants):
    rows = ew._brief()[4]
    todo = names or [n for n in rows if not os.path.exists(os.path.join(dst(), n + ".png"))]
    if size:
        w, h = map(int, size.lower().split("x"))
    else:
        w, h = (928, 1664) if vertical() else (1664, 928)
    steps = 4 if fast else 50
    to_cand = fast or variants > 1
    k = max(1, variants)
    jobs = []
    for n in todo:
        if n not in rows:
            sys.exit("!!! 任务书里没有 %s" % n)
        bad = ew.check(n)
        if bad:
            print("!! %s 拼出来有病句：%s" % (n, bad))
        base = seed_of(n, seed)
        for j in range(k):
            sd = base + j
            out = (os.path.join(cand_dir(n), "%ds-%d.png" % (steps, sd)) if to_cand
                   else os.path.join(dst(), n + ".png"))
            if to_cand and os.path.exists(out):
                continue                      # 同种子同步数的候选已经有了
            jobs.append((n, sd, out))
    say_eta(sum(eta("image", steps) for _ in jobs) + COLD, len(jobs))
    wf0 = load_wf("qwen2512")
    for i, (n, sd, out) in enumerate(jobs, 1):
        print("[%d/%d] 图 %s  %dx%d  %d 步  seed=%d%s" % (i, len(jobs), n, w, h, steps, sd, "  → 候选" if to_cand else ""))
        _gen_image(n, steps, sd, w, h, out, wf0, n)
    if to_cand and jobs:
        print("看候选：python comfy_gen.py sheet --cand <档名>；选定：python comfy_gen.py promote <档名> <序号>")


def _cands(name):
    d = cand_dir(name)
    return sorted(f for f in os.listdir(d) if f.endswith(".png") and not f.startswith("_")) if os.path.isdir(d) else []


def cmd_promote(name, pick):
    cs = _cands(name)
    if not cs:
        sys.exit("!!! %s 没有候选（先 image %s --fast 或 --variants N）" % (name, name))
    if pick is None:
        if len(cs) > 1:
            sys.exit("!!! %s 有 %d 张候选，点名一张：%s" % (name, len(cs), "  ".join("%d=%s" % (i, c) for i, c in enumerate(cs, 1))))
        pick = cs[0]
    elif pick.isdigit():
        pick = cs[int(pick) - 1]
    if pick not in cs:
        sys.exit("!!! 候选里没有 %s：%s" % (pick, cs))
    src = os.path.join(cand_dir(name), pick)
    out = os.path.join(dst(), name + ".png")
    _keep_old(out)
    shutil.copyfile(src, out)
    m = re.match(r"(\d+)s-(\d+)\.png$", pick)
    log(dict(kind="promote", name=name, src="候选/%s/%s" % (name, pick), out=name + ".png",
             steps=int(m.group(1)) if m else None, seed=int(m.group(2)) if m else None))
    print("转正 %s ← 候选/%s/%s" % (name + ".png", name, pick))


def _tile(paths, labels, out, thumb=240, cols=6):
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 18)
    except Exception:
        font = ImageFont.load_default()
    ims = []
    for p in paths:
        im = Image.open(p).convert("RGB")
        ims.append(im.resize((thumb, int(im.height * thumb / im.width))))
    th = max(i.height for i in ims) + 28           # 统一格高：拼不同尺寸不会只出一格（memory ffmpeg-tile）
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb, rows * th), (20, 20, 20))
    d = ImageDraw.Draw(sheet)
    for k, (im, lb) in enumerate(zip(ims, labels)):
        x, y = (k % cols) * thumb, (k // cols) * th
        sheet.paste(im, (x, y))
        d.text((x + 4, y + im.height + 3), lb, fill=(230, 230, 230), font=font)
    sheet.save(out)
    return out


def cmd_sheet(names, cand):
    if cand:
        cs = _cands(cand)
        if not cs:
            sys.exit("!!! %s 没有候选" % cand)
        out = _tile([os.path.join(cand_dir(cand), c) for c in cs], ["%d %s" % (i, c[:-4]) for i, c in enumerate(cs, 1)],
                    os.path.join(cand_dir(cand), "_联络表.png"))
    else:
        rows = ew._brief()[4]
        ns = [n for n in (names or rows) if os.path.exists(os.path.join(dst(), n + ".png"))]
        if not ns:
            sys.exit("!!! 一张定稿都还没有")
        out = _tile([os.path.join(dst(), n + ".png") for n in ns], ns, os.path.join(dst(), "_联络表.png"))
    print("联络表：%s（**逐张看**：构图、道具、分格、露没露正脸 —— 分格和水面线量不出来，只能看）" % out)


def _first_frame(ff, w, h):
    """首帧图没出就补一张 4 步版（H3 会重新渲染首帧，50 步是白花 3.5 分钟）。"""
    src = os.path.join(dst(), ff + ".png")
    if os.path.exists(src):
        return src
    rows = ew._brief()[4]
    if ff not in rows:
        sys.exit("!!! 首幀 %s 不在图的任务书里" % ff)
    fw, fh = (928, 1664) if h > w else (1664, 928)
    print("   首幀 %s 还没出 → 补一张 4 步版（只当首帧用，不用 50 步）" % ff)
    _gen_image(ff, 4, seed_of(ff, None), fw, fh, src, load_wf("qwen2512"), ff, dict(role="first_frame"))
    return src


def cmd_video(names, res, turbo, seed):
    _, _, rows = vbrief()
    suf = "" if res == 768 else "_%d" % res
    todo = names or [n for n in rows if not os.path.exists(os.path.join(dst(), n + suf + ".mp4"))]
    w, h = H3_SIZE[res]
    if vertical():
        w, h = h, w
    for n in todo:
        if n not in rows:
            sys.exit("!!! 任务书影片表里没有 ▶%s" % n)
        if rows[n][1] > 12:
            print("!! %s 要 %g 秒：H3 长于 12 秒容易自己切镜头（训练上限约 15 秒），拆镜或改静帧更稳" % (n, rows[n][1]))
    say_eta(sum(eta("video", res, rows[n][1]) for n in todo) + COLD, len(todo))
    for i, n in enumerate(todo, 1):
        ff, secs, _ = rows[n]
        key = "h3_i2v" if ff else "h3_t2v"
        src = _first_frame(ff, w, h) if ff else None
        wf = load_wf(key)
        N = NODES[key]
        p, sd = vprompt(n), seed_of(n, seed)
        g = wf[N["gen"][0]]["inputs"]
        g.update(prompt=p, width=w, height=h)     # 不走 ResolutionSelector：尺寸直接给死
        wf[N["secs"][0]]["inputs"]["value"] = float(secs)
        wf[N["seed"][0]]["inputs"]["noise_seed"] = sd
        wf[N["turbo"][0]]["inputs"]["value"] = bool(turbo)
        wf[N["save"][0]]["inputs"]["filename_prefix"] = "vmskill/" + n
        if src:
            fw, fh, _ = probe(src)
            if fw and (fw > fh) != (w > h):
                sys.exit("!!! 首幀 %s 是 %dx%d，和影片 %dx%d 横竖不一致" % (ff, fw, fh, w, h))
            wf[N["image"][0]]["inputs"]["image"] = upload(src)
        out = os.path.join(dst(), n + suf + ".mp4")
        print("[%d/%d] 影片 %s  %s  %dx%d  %g 秒  %s  seed=%d"
              % (i, len(todo), n, "图生（%s）" % ff if ff else "文生", w, h, secs,
                 "turbo 8 步" if turbo else "20 步", sd))
        sec, peak = run(key, wf, out, n)
        vw, vh, dur = probe(out)
        cs = cuts(out)
        log(dict(kind="video", name=n, model="MiniMax H3", license="MiniMax H3 community（署名＋AI 披露）",
                 mode="i2v" if ff else "t2v", first_frame=ff, steps=8 if turbo else 20, size=[vw, vh],
                 secs=secs, dur=round(dur, 2), seed=sd, prompt=p, out=os.path.basename(out),
                 sec=round(sec), peak=peak, cuts=cs))
        print("   存 %s  %sx%s %.2fs（%.0f 秒，%s）" % (os.path.basename(out), vw, vh, dur, sec, _peak_txt(peak)))
        if cs:
            print("   !! 第 %s 秒有硬切 —— H3 自己拍成了多镜头。看帧条（strip %s），换种子或缩短秒数重出" % (
                "、".join("%g" % t for t in cs), n))


def _video_of(name):
    for s in ("_1080", "", "_480"):
        p = os.path.join(dst(), name + s + ".mp4")
        if os.path.exists(p):
            return p
    sys.exit("!!! 没有 %s 的影片" % name)


def cmd_strip(name):
    src = _video_of(name)
    _, _, dur = probe(src)
    out = os.path.join(dst(), "_帧条_%s.png" % name)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-vf",
                    "fps=6/%.3f,scale=180:-1,tile=6x1" % max(dur, 0.1), "-frames:v", "1", out], check=True)
    cs = cuts(src)
    print("帧条：%s（%s，%.2fs）" % (out, os.path.basename(src), dur))
    print("   切镜：%s" % (("!! 第 %s 秒" % "、".join("%g" % t for t in cs)) if cs else "无"))


def _fit_vf(w, h, tw, th):
    """铺满再居中裁（cover）。"""
    return "scale=%d:%d:force_original_aspect_ratio=increase:flags=lanczos,crop=%d:%d,setsar=1" % (tw, th, tw, th)


def cmd_upscale(names, how, to):
    srcs = []
    for n in names:
        src = None
        for s in ("", "_480"):
            p = os.path.join(dst(), n + s + ".mp4")
            if os.path.exists(p):
                src = p
                break
        if not src:
            sys.exit("!!! 没有 %s.mp4 / %s_480.mp4" % (n, n))
        srcs.append((n, src))
    if how == "seedvr2":
        say_eta(sum(eta("upscale", "seedvr2", probe(s)[2]) for _, s in srcs) + COLD, len(srcs))
    for n, src in srcs:
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


def cmd_notes():
    """每个成品文件是怎么来的（最后一次产出它的记录），写 素材/生成/生成记录.md。
    手写的「为什么这样选」仍写在项目根的 素材处理说明.md；这一份可以随时重跑覆盖。"""
    rs = logs()
    if not rs:
        sys.exit("!!! 没有 comfy_log.jsonl")
    last = {}
    for r in rs:
        if r.get("out"):
            last[r["out"]] = r
    L = ["# 生成记录（comfy_gen.py notes 自动生成，别手改）", "",
         "| 文件 | 怎么来的 | 种子 | 耗时 |", "|---|---|---|---|"]
    for out in sorted(last):
        r = last[out]
        if "/" in out and out.startswith("候选/"):
            continue                                   # 候选不进表，转正的那条 promote 会写来源
        k = r["kind"]
        if k == "image":
            how = "Qwen-Image-2512 %d 步 %s%s" % (r["steps"], "×".join(map(str, r["size"])),
                                                  "（首帧专用）" if r.get("role") == "first_frame" else "")
        elif k == "promote":
            how = "候选转正：%s（%s 步）" % (r["src"], r.get("steps"))
        elif k == "video":
            how = "MiniMax H3 %s %s %g 秒（首帧 %s）%s" % (
                r.get("mode"), "×".join(map(str, r["size"])), r.get("secs", 0), r.get("first_frame") or "—",
                ("  **切镜 %s**" % r["cuts"]) if r.get("cuts") else "")
        elif k == "upscale":
            how = "放大 %s ← %s" % (r.get("how"), r.get("src"))
        else:
            how = k
        L.append("| %s | %s | %s | %s |" % (out, how, r.get("seed", ""), ("%ds" % r["sec"]) if r.get("sec") else ""))
    tot = sum(r.get("sec") or 0 for r in rs)
    by = {}
    for r in rs:
        by[r["kind"]] = by.get(r["kind"], 0) + (r.get("sec") or 0)
    L += ["", "显卡时间合计 %.1f 小时：%s" % (tot / 3600, "，".join("%s %.0f 分钟" % (k, v / 60) for k, v in by.items() if v)), "",
          "授权：Qwen-Image-2512 / SeedVR2 Apache-2.0；MiniMax H3 要在说明里署名「MiniMax H3 生成」并勾 AI 披露。"]
    p = os.path.join(dst(), "生成记录.md")
    open(p, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("写好 %s（%d 个文件）" % (p, len(L) - 4))


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("cmd", nargs="?")
    ap.add_argument("names", nargs="*")
    ap.add_argument("--proj")
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--variants", type=int, default=1)
    ap.add_argument("--cand")
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
    if a.cmd == "start":
        cmd_start()
    elif a.cmd == "check":
        cmd_check()
    elif a.cmd == "list":
        cmd_list()
    elif a.cmd == "show":
        for n in a.names:                       # 图和影片可以同名：影片那张表的写 ▶档名
            p = vprompt(n[1:]) if n.startswith("▶") else ew.prompt(n)
            print("== %s %d 字\n%s" % (n, len(p), p))
    elif a.cmd == "image":
        cmd_image(a.names, a.fast, a.seed, a.size, a.variants)
    elif a.cmd == "promote":
        if not a.names:
            sys.exit("!!! promote <档名> [候选文件名|序号]")
        cmd_promote(a.names[0], a.names[1] if len(a.names) > 1 else None)
    elif a.cmd == "sheet":
        cmd_sheet(a.names, a.cand)
    elif a.cmd == "video":
        cmd_video([n.lstrip("▶") for n in a.names], a.res, a.turbo, a.seed)
    elif a.cmd == "strip":
        for n in a.names:
            cmd_strip(n.lstrip("▶"))
    elif a.cmd == "upscale":
        if not a.names:
            sys.exit("!!! upscale 要点名（哪几镜用 SeedVR2、哪几镜用 lanczos 是逐镜判断的）")
        cmd_upscale(a.names, a.how or "lanczos", a.to)
    elif a.cmd == "notes":
        cmd_notes()
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
