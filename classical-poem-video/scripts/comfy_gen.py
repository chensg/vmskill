# -*- coding: utf-8 -*-
"""本机 3090 出图 / 出影片 / 影片放大（ComfyUI HTTP API，不用开浏览器）。

    python comfy_gen.py start                       # 没开就把 ComfyUI 在后台拉起来（不弹浏览器）
    python comfy_gen.py check                       # 服务、显卡、功耗上限、队列、工作流节点
    python comfy_gen.py list                        # 任务书里的图和影片，已出的打 ✓
    python comfy_gen.py show <档名> [▶档名]          # 打印完整提示词（影片那张表的写 ▶档名）
    python comfy_gen.py image [档名...] --fast [--variants N] [--seed N]   # 候选：4 步，进 候选/<档名>/
    python comfy_gen.py image [档名...] [--variants N] [--seed N]          # 50 步；--variants 也进候选
    python comfy_gen.py image <档名> --trial [--size WxH]                  # 试验：50 步进候选，不盖定稿
    python comfy_gen.py image [档名...] --engine moss [--variants N]       # MOSS-Image：50 步约 75 秒（Qwen 的 1/4），只进候选
    python comfy_gen.py promote <档名> [候选文件名|序号]                  # 选定的候选转正成 <档名>.png
    python comfy_gen.py sheet [档名...] | sheet --cand <档名>              # 拼联络表（带档名）
    python comfy_gen.py video [档名...] [--res 480|768] [--turbo] [--seed N]   # 默认 480p
    python comfy_gen.py strip <档名>                # 影片 6 帧条 + 切镜检测
    python comfy_gen.py upscale <档名...> [--seedvr2|--lanczos] [--to WxH]
    python comfy_gen.py upscale --image <档名|图片路径...> [--lanczos] [--to WxH]   # 静帧，默认 SeedVR2 到 4K
    python comfy_gen.py music <名> --style "…" [--secs 180] [--plan 10 | --abc 谱.abc] [--lyrics-file f]   # YuE2 配乐 → ../素材/配乐/（默认纯音乐）
    python comfy_gen.py sfx <名> "<描述>" [--secs 5] [--kind SFX|One-shot] [--enhance]   # Stable Audio 3 → ../素材/音效/
    python comfy_gen.py tts-ref "<音色描述>" [--lang zh|en] [--variants 3]   # MOSS-TTS 出参考音候选 → ../素材/配音/参考音候选/
    python comfy_gen.py tts-ref pick <序号|文件名> [--lang zh|en]          # 选定 → ../素材/配音/参考音_<lang>.flac
    python comfy_gen.py tts [zh|en] [VO_001 ...] [--cps 4.5] [--seed N]   # MOSS-TTS 克隆参考音逐条出旁白 → vo/（同 el_tts gen）
    python comfy_gen.py notes                       # 素材/生成/生成记录.md（每个成品是怎么来的）
    python comfy_gen.py free                        # 卸模型、清显存/内存

全部落到 ../素材/生成/：
    图      <档名>.png（定稿）       候选/<档名>/<步数>s-<种子>.png（--fast / --variants）
    影片    <档名>.mp4 (768)   <档名>_480.mp4（试稿）
    放大    <档名>_1080.mp4    —— CLIPS 里写 dict(video="生成/<档名>_1080.mp4", ss=0, to="full")
    静帧放大 <档名>_3840x2160.png（给路径时放在原图旁边）
每一次生成都记进 ../素材/生成/comfy_log.jsonl（提示词、种子、步数、尺寸、耗时、功耗/温度峰值、切镜）。

==== 推荐顺序（2026-10-20《我想回家》复盘后定）====
  1. `image --fast` 全出一遍 → `sheet --cand` 或 `sheet` 看构图、道具、分格 → 改任务书再出
     （第一轮直接上 50 步，16 张里 8 张重出，白跑约 40 分钟）
  2. 只当影片首帧的图**不出 50 步**：`video` 发现首帧没出会自己补 4 步版（H3 会重新渲染首帧）
  3. 旁白定了先 `make_story_*.py vidplan write`，秒数由镜长算，别手抄
  4. `video`（默认 480p）→ `strip` 看帧条（切镜自动报）→ `upscale --seedvr2`。768p 要点名 `--res 768`：
     10-21 盲比（同镜 768p+SeedVR2 vs 480p+SeedVR2）1:1 —— 白天细节多的 01 选 768p，暗的水下 15 选 480p；
     768p 贵 4~5 倍，只给白天、细节多的关键镜
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
  图  Qwen-Image-2512（Apache-2.0）：默认直出 1088×1920，50 步约 4.7 分钟（928×1664 是 3.5 分钟）/ 4 步 10~20 秒
  影片 MiniMax H3（20 步）：480p 约 1 分钟/秒成片；768p 约 5.3 分钟/秒成片（12 秒 67 分钟）
      **发布说明要写「MiniMax H3 生成」并勾 AI 披露**；美/欧/英/韩不在它的免费商用范围
  放大 SeedVR2 3B（Apache-2.0）：约 70 秒/秒成片（480 或 768 进都差不多），显存约 10GB
      lanczos（ffmpeg）几秒，偏软。SeedVR2 给特写/关键镜/首尾/有线条文字的；lanczos 给过场、烟雾黑暗、试稿
      静帧 `upscale --image`：1664×928 → 3840×2160 约 20 秒/张、显存 7.3GB（10-22）；脸、招牌字都补出细节

  图  MOSS-Image SFT int8（Apache-2.0）：1920×1088 50 步 75 秒。真实感好、拉丁字母刺青字对，
      但**不守任务书的禁令**（10-26 皮特凯恩三镜：2/3 露正脸/侧脸，Qwen 1/3 半侧）→ 只当快速候选引擎，不默认
  旁白 MOSS-TTS v1.5 8B（Apache-2.0）：逐条克隆一段参考音（音色才一致）；~2 倍实时（9 秒一条 20 秒）；
      中文约 4.1 字/秒（豆包 4.5）——要对齐用 --cps；10-26 Whisper 核读六条无漏字增字
  影片 SANA-Video 2.0 没进技能：中文提示词读不懂、图生影片不照动作句做、没有声音（见 sourcing.md）

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
import urllib.error
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
    # 静帧版：seedvr2 的 LoadVideo/拆帧/CreateVideo/SaveVideo 换成 LoadImage/SaveImage，中间节点不动
    "seedvr2_image": dict(image=("73", "LoadImage"), mult=("66:57", "ResizeImageMaskNode"),
                          chunk=("66:105", "PrimitiveBoolean"), save=("76", "SaveImage")),
    # YuE2（ComfyUI 原生，int8）：33:24 写谱 → 33:30 开关（true＝用模型写的谱，false＝用 33:32 给的谱）→ 33:25 生成
    "yue2": dict(ckpt=("33:15", "CheckpointLoaderSimple"), plan=("33:24", "YuE2GenerateABC"),
                 preview=("33:14", "PreviewAny"), use_plan=("33:31", "PrimitiveBoolean"),
                 abc=("33:32", "PrimitiveString"), gen=("33:25", "YuE2GenerateMusic"), seed=("33:34", "SeedNode"),
                 style=("33:36", "PrimitiveStringMultiline"), lyrics=("33:37", "PrimitiveStringMultiline"),
                 save=("10", "SaveAudioAdvanced")),
    # Stable Audio 3 Medium：52:31 描述 →（52:35 true 时先过 52:28 的 LLM 改写，52:43 选 Music/Instrument/SFX/One-shot）
    "stable_audio3": dict(text=("52:31", "PrimitiveStringMultiline"), enhance=("52:35", "PrimitiveBoolean"),
                          kind=("52:43", "CustomCombo"), secs=("52:36", "PrimitiveFloat"),
                          sampler=("52:3", "KSampler"), neg=("52:7", "CLIPTextEncode"), save=("57", "SaveAudioAdvanced")),
    # MOSS-Image SFT（照 OpenMOSS 卡片：50 步、CFG 3、负向分支跳第 22 层；负向提示词默认空）
    "moss_image": dict(prompt=("4", "CLIPTextEncode"), neg=("5", "CLIPTextEncode"), latent=("6", "EmptyFlux2LatentImage"),
                       sampler=("8", "KSampler"), save=("10", "SaveImage")),
    # MOSS-TTS v1.5：参考音（LoadAudio）→ VoiceClone。参考音由 moss_tts_ref（GenerateSpeech＋音色描述）出
    "moss_tts": dict(ref=("2", "LoadAudio"), gen=("3", "MossTTSV15_VoiceClone"), save=("4", "SaveAudioAdvanced")),
    "moss_tts_ref": dict(gen=("2", "MossTTSV15_GenerateSpeech"), save=("4", "SaveAudioAdvanced")),
}
FAMILY = {"qwen2512": "image", "h3_t2v": "video", "h3_i2v": "video", "seedvr2": "upscale",
          "seedvr2_image": "upscale", "yue2": "music", "stable_audio3": "sfx", "moss_image": "image_moss",
          "moss_tts": "tts", "moss_tts_ref": "tts"}
TTS_LANG = {"zh": "Chinese", "en": "English"}
TTS_REF_TEXT = {"zh": "這座島，在海圖上找不到。十八年來，沒有一艘船靠近過它。",
                "en": "This island is not on any chart. For eighteen years, no ship came near it."}
YUE2_SKILL = os.path.expanduser("~/.claude/skills/yue2-music/instrumental/scripts/instrumental.py")
# 写谱用的曲式标签（不唱，只让模型排出段落、拉够长度）。官方纯音乐流程：模型写谱 → Vocal 音符挪到 Ins → 按谱生成。
PLAN_TAGS = "[Intro]\n\n[Verse]\n\n[Chorus]\n\n[Verse]\n\n[Chorus]\n\n[Bridge]\n\n[Chorus]\n\n[Outro]"


def plan_tags(n=None):
    """纯音乐的曲式标签。缺省 8 段（2026-10-21 实测 141 秒）；长度由段数定、--secs 只是上限，
    要更长就加段：在 [Bridge] 前面按 Verse/Chorus 交替插，首尾的 [Intro] [Outro] 不动。"""
    tags = PLAN_TAGS.split("\n\n")
    if not n or n == len(tags):
        return PLAN_TAGS
    if n < len(tags):
        return "\n\n".join(tags[:n - 1] + ["[Outro]"])
    mid = [("[Verse]" if k % 2 == 0 else "[Chorus]") for k in range(n - len(tags))]
    b = tags.index("[Bridge]")
    return "\n\n".join(tags[:b] + mid + tags[b:])
H3_SIZE = {480: (864, 480), 768: (1344, 768)}       # 横；竖版对调。都是 32 的倍数

# 预计耗时（秒）的缺省值：2026-10-20 实测；项目里有记录时用本项目的中位数。
ETA_DEFAULT = {("image", 50): 280, ("image", 4): 12, ("image", "moss"): 75, ("tts", None): 2.2, ("video", 480): 60, ("video", 768): 320,
               ("upscale", "seedvr2"): 71, ("upscale", "seedvr2_image"): 20}   # 静帧是秒/张（10-22 1664×928→4K 20 秒）
COLD = 70                    # 换模型后的首个任务多出来的加载时间


# ---------------------------------------------------------------- 路径
def proj():
    return os.path.dirname(os.path.abspath(ew.BRIEF))       # BRIEF 是 <项目>/出图任务书.md（10-26 前多套了一层，没人调用所以没露）


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
    h, sec, peak = submit(key, wf, label)
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
    return sec, peak


def submit(key, wf, label):
    """交一个 prompt，等它跑完。返回 (history 那一条, 秒, 峰值)。输出是文本（PreviewAny）时直接读 history。"""
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
            except urllib.error.URLError as e:
                # 2026-10-26：ComfyUI 进程没了时连接是瞬间被拒，旧版照样每 5 秒记 35 秒，45 秒就报「5 分钟没响应」
                if isinstance(getattr(e, "reason", None), ConnectionRefusedError) and not alive(5):
                    sys.exit("!!! %s：ComfyUI 进程没了（连接被拒）。python comfy_gen.py start 再重跑（已出的不会重出）" % label)
                dead += 35
                print("   ComfyUI %ds 没响应（%s）" % (dead, type(e).__name__), flush=True)
                if dead >= 300:
                    sys.exit("!!! %s：ComfyUI 5 分钟没响应。停掉吃内存的进程；还不行就重启 ComfyUI 再重跑" % label)
                continue
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
    return h, time.time() - t0, w.peak


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
        if kind == "image" and (r.get("engine") == "moss") == (key == "moss") and (key == "moss" or r.get("steps") == key):
            xs.append(r["sec"])
        elif kind == "video" and min([x for x in (r.get("size") or []) if x] or [0]) == key and r.get("dur"):
            xs.append(r["sec"] / r["dur"])
        elif kind == "upscale" and r.get("how") == key and r.get("dur"):
            xs.append(r["sec"] / r["dur"])
        elif kind == "upscale" and r.get("how") == key and r.get("image"):
            xs.append(r["sec"])
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
        m = re.match(r"\| ▶(\d{2,3}[a-z]?_[^ |]+) \| ([^|]+) \| ([\d.]+) \| (.+) \|$", line)   # 102a_：长片三位数镜号
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


def _gen_image(n, steps, sd, w, h, out, wf0, label, extra=None, engine="qwen"):
    wf = json.loads(json.dumps(wf0))
    p = ew.prompt(n)
    key = "moss_image" if engine == "moss" else "qwen2512"
    N = NODES[key]
    wf[N["prompt"][0]]["inputs"]["text"] = p
    wf[N["latent"][0]]["inputs"].update(width=w, height=h)
    if engine == "moss":
        wf[N["sampler"][0]]["inputs"]["steps"] = steps
    else:
        wf[N["fast"][0]]["inputs"]["value"] = steps == 4
    wf[N["sampler"][0]]["inputs"]["seed"] = sd
    wf[N["save"][0]]["inputs"]["filename_prefix"] = "vmskill/" + n
    sec, peak = run(key, wf, out, label)
    rec = dict(kind="image", name=n, model="MOSS-Image-SFT" if engine == "moss" else "Qwen-Image-2512",
               engine=engine, license="Apache-2.0", steps=steps,
               size=[w, h], seed=sd, prompt=p, out=os.path.relpath(out, dst()).replace("\\", "/"),
               sec=round(sec), peak=peak)
    rec.update(extra or {})
    log(rec)
    print("   存 %s（%.0f 秒，%s）" % (rec["out"], sec, _peak_txt(peak)))


def cmd_image(names, fast, seed, size, variants, trial=False, engine="qwen"):
    rows = ew._brief()[4]
    todo = names or [n for n in rows if not os.path.exists(os.path.join(dst(), n + ".png"))]
    if size:
        w, h = map(int, size.lower().split("x"))
    else:
        # 2026-10-21 试验：1088×1920 直出和 928×1664 同种子比，没有变形/重复/分格，细节略好，慢 40%（280s vs 200s）；
        # 换来的是成片尺寸以上 —— 不再需要每支都写 PP_ACCEPT_REASON 承认「静帧在放大」。
        w, h = (1088, 1920) if vertical() else (1920, 1088)
    if engine == "moss" and fast:
        sys.exit("!!! MOSS 没有 4 步版：--engine moss 本身就是快的那档（50 步约 75 秒）")
    if engine == "moss" and (w % 16 or h % 16):
        sys.exit("!!! MOSS 宽高要是 16 的倍数")
    steps = 4 if fast else 50
    to_cand = fast or variants > 1 or trial or engine == "moss"   # MOSS 不守禁令（露脸），一律进候选、人挑过才转正
    tag = ("-%dx%d" % (w, h)) if size else ""
    pre = "m" if engine == "moss" else ""
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
            out = (os.path.join(cand_dir(n), "%s%ds-%d%s.png" % (pre, steps, sd, tag)) if to_cand
                   else os.path.join(dst(), n + ".png"))
            if to_cand and os.path.exists(out):
                continue                      # 同种子同步数的候选已经有了
            jobs.append((n, sd, out))
    say_eta(sum(eta("image", "moss" if engine == "moss" else steps) for _ in jobs) + COLD, len(jobs))
    wf0 = load_wf("moss_image" if engine == "moss" else "qwen2512")
    for i, (n, sd, out) in enumerate(jobs, 1):
        print("[%d/%d] 图 %s  %s %dx%d  %d 步  seed=%d%s" % (i, len(jobs), n, engine, w, h, steps, sd,
                                                         "  → 候选" if to_cand else ""))
        _gen_image(n, steps, sd, w, h, out, wf0, n, engine=engine)
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
    m = re.match(r"m?(\d+)s-(\d+)(?:-\d+x\d+)?\.png$", pick)
    log(dict(kind="promote", name=name, src="候选/%s/%s" % (name, pick), out=name + ".png",
             engine="moss" if pick.startswith("m") else "qwen",
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
    fw, fh = (1088, 1920) if h > w else (1920, 1088)
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


def cmd_upscale_image(names, how, to):
    """静帧放大（默认到 4K：横 3840×2160、竖 2160×3840）。Qwen 直出 4K 会坏（训练约 1.6MP、显存已贴 23.6GB），
    所以走原生尺寸出图再放大。名字是任务书档名（读 <档名>.png）或任意图片路径（输出放在它旁边）。"""
    srcs = []
    for n in names:
        src = n if os.path.isfile(n) else os.path.join(dst(), n + ".png")
        if not os.path.exists(src):
            sys.exit("!!! 没有 %s（档名读 素材/生成/<档名>.png，或直接给图片路径）" % src)
        srcs.append(src)
    if how == "seedvr2":
        say_eta(sum(eta("upscale", "seedvr2_image") for _ in srcs) + COLD, len(srcs))
    for src in srcs:
        w, h, _ = probe(src)
        tw, th = map(int, to.lower().split("x")) if to else ((2160, 3840) if h > w else (3840, 2160))
        stem = os.path.splitext(os.path.basename(src))[0]
        out = os.path.join(os.path.dirname(os.path.abspath(src)), "%s_%dx%d.png" % (stem, tw, th))
        t0 = time.time()
        if how == "lanczos":
            _keep_old(out)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", _fit_vf(w, h, tw, th), out], check=True)
            peak = None
        else:
            wf = load_wf("seedvr2_image")
            N = NODES["seedvr2_image"]
            mult = max(tw / w, th / h) * 1.002          # 宁大一点，再裁
            wf[N["image"][0]]["inputs"]["image"] = upload(src)
            wf[N["mult"][0]]["inputs"]["resize_type.multiplier"] = round(mult, 4)
            wf[N["chunk"][0]]["inputs"]["value"] = False  # 单帧不用分段
            wf[N["save"][0]]["inputs"]["filename_prefix"] = "vmskill/" + stem + "_seedvr2"
            raw = os.path.join(os.path.dirname(out), "_%s_seedvr2_raw.png" % stem)
            print("upscale %s  %sx%s → ×%.4f → 裁 %dx%d（SeedVR2 静帧）" % (stem, w, h, mult, tw, th))
            _, peak = run("seedvr2_image", wf, raw, stem)
            rw, rh, _ = probe(raw)
            _keep_old(out)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", raw, "-vf", _fit_vf(rw, rh, tw, th), out], check=True)
            os.remove(raw)
        ow, oh, _ = probe(out)
        sec = time.time() - t0
        if os.path.isdir(dst()):                      # 不在项目里（随手给的路径、仓库里直接跑）就不记日志
            rel = os.path.relpath(out, dst()).replace("\\", "/")
            log(dict(kind="upscale", name=stem, how=how + "_image", image=True, src=os.path.basename(src),
                     size=[ow, oh], out=rel if not rel.startswith("..") else out, sec=round(sec), peak=peak))
        print("   存 %s  %sx%s（%.0f 秒%s）" % (out, ow, oh, sec, "，" + _peak_txt(peak) if peak else ""))


def _audio_dir(sub):
    return os.path.join(os.path.dirname(dst()), sub)


def _text_out(h, nid):
    """PreviewAny 的文本输出（history outputs 里通常是 {"text": [...]}）。"""
    o = h.get("outputs", {}).get(nid, {})
    for v in o.values():
        if isinstance(v, list) and v and isinstance(v[0], str):
            return v[0]
    return None


def cmd_music(name, style, secs, seed, lyrics_file, plan_n=None, abc_file=None):
    """YuE2 本地配乐（ComfyUI 原生 int8）。默认纯音乐，照官方 yue2-music 纯音乐流程：
    ① YuE2 按风格＋曲式标签写谱（ABC）② 官方 instrumental.py 把 Vocal 音符挪到 Ins（CPU）③ 按改好的谱生成。
    给 --lyrics-file 就是带人声的歌（跳过 ②，直接用模型写的谱）。产出 ../素材/配乐/<名>.mp3（另留 .flac）。
    授权：权重 CC BY-NC 4.0＋作者给个人创作者的变现许可（可变现、不收费，署名可选、鼓励写 YuE2）。"""
    out_dir = _audio_dir("配乐")
    work = os.path.join(out_dir, "_yue2_" + name)
    if os.path.exists(work):
        _keep_old(work)
    os.makedirs(work)
    sd = seed_of(name, seed)
    lyrics = open(lyrics_file, encoding="utf-8").read() if lyrics_file else plan_tags(plan_n)
    instrumental = not lyrics_file
    say_eta(60 + secs * 1.0 + COLD, 2)
    wf0 = load_wf("yue2")
    N = NODES["yue2"]
    # ① 只写谱：剪出 ckpt / 种子 / 风格 / 曲式 / 写谱 / 预览 六个节点
    keep = [N[k][0] for k in ("ckpt", "seed", "style", "lyrics", "plan", "preview")]
    plan = {k: json.loads(json.dumps(wf0[k])) for k in keep}
    plan[N["preview"][0]]["inputs"]["source"] = [N["plan"][0], 0]
    plan[N["style"][0]]["inputs"]["value"] = style
    plan[N["lyrics"][0]]["inputs"]["value"] = lyrics
    plan[N["seed"][0]]["inputs"]["seed"] = sd
    if abc_file:
        # 给了谱就不写谱：改谱（重复段落加长、删段）后按同一份谱重生成，调性/配器都接得上
        abc, sec1 = open(abc_file, encoding="utf-8").read(), 0
        print("① 用给定的谱 %s（不写谱）" % abc_file)
    else:
        print("① YuE2 写谱  seed=%d  %s" % (sd, "纯音乐" if instrumental else "带人声"))
        h, sec1, peak = submit("yue2", plan, name + " 写谱")
        abc = _text_out(h, N["preview"][0])
    if not abc or "X:" not in abc:
        sys.exit("!!! 写谱没拿到 ABC（%s）" % json.dumps(h.get("outputs", {}), ensure_ascii=False)[:300])
    open(os.path.join(work, "plan.abc"), "w", encoding="utf-8").write(abc)
    use_style, use_lyrics, use_abc = style, lyrics, abc
    if instrumental:
        # ② 官方脚本：Vocal → Ins，只用 CPU（给了 ABC 就不需要 GPU / 官方运行时）
        if not os.path.exists(YUE2_SKILL):
            sys.exit("!!! 找不到 yue2-music 技能（%s）：纯音乐要它把人声旋律挪到乐器声部" % YUE2_SKILL)
        r = subprocess.run([sys.executable, YUE2_SKILL, "run", "--abc", os.path.join(work, "plan.abc"),
                            "--style", style, "--empty-lyrics", "--prepare-only", "--output", os.path.join(work, "inst")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        prep = os.path.join(work, "inst", "prepared")
        if r.returncode != 0 or not os.path.exists(os.path.join(prep, "score.abc")):
            sys.exit("!!! 转纯乐器谱失败：%s" % (r.stderr or r.stdout)[-800:])
        use_abc = open(os.path.join(prep, "score.abc"), encoding="utf-8").read()
        use_style = open(os.path.join(prep, "style.txt"), encoding="utf-8").read().strip()
        use_lyrics = open(os.path.join(prep, "lyrics.txt"), encoding="utf-8").read()
        print("② 人声旋律已挪到乐器声部（官方 instrumental.py，见 %s）" % prep)
    # ③ 按谱生成
    wf = json.loads(json.dumps(wf0))
    wf[N["use_plan"][0]]["inputs"]["value"] = False
    wf[N["abc"][0]]["inputs"]["value"] = use_abc
    wf[N["style"][0]]["inputs"]["value"] = use_style
    wf[N["lyrics"][0]]["inputs"]["value"] = use_lyrics
    wf[N["seed"][0]]["inputs"]["seed"] = sd
    wf[N["gen"][0]]["inputs"]["max_duration"] = float(secs)
    wf[N["save"][0]]["inputs"]["filename_prefix"] = "vmskill/music_" + name
    flac = os.path.join(out_dir, name + ".flac")
    print("③ 按谱生成（上限 %d 秒）" % secs)
    sec2, peak2 = run("yue2", wf, flac, name + " 生成")
    mp3 = os.path.join(out_dir, name + ".mp3")
    _keep_old(mp3)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", flac, "-c:a", "libmp3lame", "-q:a", "0", mp3], check=True)
    _, _, dur = probe_audio(mp3)
    log(dict(kind="music", name=name, model="YuE2-3B (ComfyUI int8)", instrumental=instrumental,
             license="YuE2 权重 CC BY-NC 4.0＋个人创作者变现许可；署名可选（#YuE2）", style=style, seed=sd,
             secs=secs, dur=round(dur, 2), out="../配乐/" + name + ".mp3", sec=round(sec1 + sec2), peak=peak2))
    print("   存 配乐/%s.mp3  %.1f 秒（%.0f 秒，%s）—— **要人听**：有没有人声、有没有中段断掉" % (
        name, dur, sec1 + sec2, _peak_txt(peak2)))


def probe_audio(p):
    o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", p],
                       capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    return None, None, float(json.loads(o or "{}").get("format", {}).get("duration") or 0)


def cmd_sfx(name, text, secs, seed, kind, enhance):
    """Stable Audio 3 Medium 本地音效 → ../素材/音效/<名>.mp3。
    授权：Stability AI Community License —— 年收入 <100 万美元免费商用；**商用前要在 Stability AI 登记**；
    发布处要显著写「Powered by Stability AI」（publish.py check 会查）。"""
    wf = load_wf("stable_audio3")
    N = NODES["stable_audio3"]
    sd = seed_of(name, seed)
    wf[N["text"][0]]["inputs"]["value"] = text
    wf[N["enhance"][0]]["inputs"]["value"] = bool(enhance)
    combo = wf[N["kind"][0]]["inputs"]
    opts = [combo.get("option%d" % i) for i in range(1, 6)]
    if kind not in opts:
        sys.exit("!!! --kind 只能是 %s" % "/".join(o for o in opts if o))
    combo.update(choice=kind, index=opts.index(kind))
    wf[N["secs"][0]]["inputs"]["value"] = float(secs)
    wf[N["sampler"][0]]["inputs"]["seed"] = sd
    wf[N["save"][0]]["inputs"]["filename_prefix"] = "vmskill/sfx_" + name
    if not enhance:
        # 不改写就把 LLM 那条支路整个剪掉：ComfyUI 会校验图里每个加载节点的文件，剪了才不依赖 4.5GB 的 qwen3.5_2b
        pos = next(k for k, v in wf.items() if v["class_type"] == "CLIPTextEncode" and isinstance(v["inputs"].get("text"), list))
        wf[pos]["inputs"]["text"] = [N["text"][0], 0]
        for k in [k for k, v in wf.items() if v["class_type"] in ("TextGenerate", "StringReplace", "JsonExtractString",
                                                                  "ComfySwitchNode", "ComfyMathExpression", "PreviewAny",
                                                                  "CustomCombo", "PrimitiveBoolean")
                  or (v["class_type"] == "CLIPLoader" and "qwen" in v["inputs"].get("clip_name", ""))]:
            del wf[k]
        if any(isinstance(x, list) and x[0] not in wf for v in wf.values() for x in v["inputs"].values()):
            sys.exit("!!! 剪 LLM 支路后还有节点指向被删的节点 —— 模板变了，重新导出")
    out = os.path.join(_audio_dir("音效"), name + ".mp3")
    print("音效 %s  %g 秒  %s%s  seed=%d" % (name, secs, kind, "（LLM 改写提示词）" if enhance else "", sd))
    sec, peak = run("stable_audio3", wf, out, name)
    _, _, dur = probe_audio(out)
    log(dict(kind="sfx", name=name, model="Stable Audio 3 Medium",
             license="Stability AI Community（<$1M 免费；商用需登记；署 Powered by Stability AI）",
             text=text, sfx_kind=kind, enhance=bool(enhance), seed=sd, secs=secs, dur=round(dur, 2),
             out="../音效/" + name + ".mp3", sec=round(sec), peak=peak))
    print("   存 音效/%s.mp3  %.1f 秒（%.0f 秒，%s）—— 要人听" % (name, dur, sec, _peak_txt(peak)))


def _ref_dir():
    return _audio_dir("配音")


def _ref_path(lang):
    return os.path.join(_ref_dir(), "参考音_%s.flac" % lang)


def cmd_tts_ref(voice, lang, variants, seed):
    """出参考音候选：GenerateSpeech＋音色描述（MOSS-VoiceGenerator 没装，VoiceDesign 节点用不了）。
    同一段描述每次音色都不一样 —— 所以整片只用一段参考音、逐条克隆，音色才一致。"""
    wf0 = load_wf("moss_tts_ref")
    N = NODES["moss_tts_ref"]
    d = os.path.join(_ref_dir(), "参考音候选")
    base = seed if seed is not None else 7
    for j in range(max(1, variants)):
        sd = base + j
        wf = json.loads(json.dumps(wf0))
        wf[N["gen"][0]]["inputs"].update(text=TTS_REF_TEXT[lang], instruction=voice, language=TTS_LANG[lang], seed=sd)
        wf[N["save"][0]]["inputs"]["filename_prefix"] = "vmskill/ttsref_%s" % lang
        out = os.path.join(d, "%s_%d.flac" % (lang, sd))
        sec, peak = run("moss_tts_ref", wf, out, "参考音 %s seed=%d" % (lang, sd))
        log(dict(kind="tts_ref", lang=lang, voice=voice, seed=sd, out=os.path.relpath(out, dst()).replace("\\", "/"),
                 sec=round(sec), dur=round(probe_audio(out)[2], 2), peak=peak))
        print("   存 %s（%.0f 秒）" % (out, sec))
    print("**要人听**，选一条：python comfy_gen.py tts-ref pick <序号> --lang %s" % lang)


def cmd_tts_ref_pick(pick, lang):
    d = os.path.join(_ref_dir(), "参考音候选")
    cs = sorted(f for f in os.listdir(d) if f.startswith(lang + "_") and f.endswith(".flac")) if os.path.isdir(d) else []
    if not cs:
        sys.exit("!!! 没有 %s 的参考音候选（先 tts-ref \"<音色描述>\"）" % lang)
    f = cs[int(pick) - 1] if pick.isdigit() and int(pick) <= len(cs) else pick
    if f not in cs:
        sys.exit("!!! 候选：%s" % "  ".join("%d=%s" % (i, c) for i, c in enumerate(cs, 1)))
    out = _ref_path(lang)
    _keep_old(out)
    shutil.copyfile(os.path.join(d, f), out)
    print("参考音 ← %s（%s）。之后 tts %s 全片都克隆它；换参考音＝全片重出" % (f, out, lang))


def cmd_tts(lang, names, cps, seed):
    """MOSS-TTS 逐条克隆参考音出旁白，落到和 el_tts gen 一样的位置（build/vo/VO_xxx.mp3，44.1k mp3），
    后面照旧 el_tts asr → vo_trim apply → make_story_*.py sync。
    稿子、tts_fix.json 的 fix / seed 都和 el_tts 共用（import el_tts.lines）。"""
    import el_tts
    el_tts.HERE = os.path.join(proj(), "build")
    ref = _ref_path(lang)
    if not os.path.exists(ref):
        sys.exit("!!! 没有参考音 %s：先 tts-ref \"<音色描述>\" --lang %s，听过再 tts-ref pick" % (ref, lang))
    cfg = el_tts.fixes().get(lang, {})
    vo_dir, orig_dir, raw_dir = el_tts.DIRS[lang]
    rows = [(v, t) for v, t in el_tts.lines(lang)
            if ((v in names) if names else not os.path.exists(os.path.join(el_tts.HERE, vo_dir, v + ".mp3")))]
    if not rows:
        print("没有要出的（vo/ 都在；重出要点名）")
        return
    say_eta(sum(len(t) / 4.2 * eta("tts", None) for _, t in rows) + COLD, len(rows))
    wf0 = load_wf("moss_tts")
    N = NODES["moss_tts"]
    up = upload(ref)
    os.makedirs(os.path.join(el_tts.HERE, vo_dir), exist_ok=True)
    for i, (vo, txt) in enumerate(rows, 1):
        if names:                       # 重出：旧的 _orig/_raw 一起删，否则 vo_trim / langfit 会把旧录音写回来
            for d in (orig_dir, raw_dir):
                old = os.path.join(el_tts.HERE, d, vo + ".mp3")
                if os.path.exists(old):
                    os.remove(old)
        sd = cfg.get("seed", {}).get(vo, seed if seed is not None else 42)
        wf = json.loads(json.dumps(wf0))
        # target_tokens：12.5 帧/秒。给 --cps 就按字数定长（标点不算字）；0＝模型自己决定
        n_chars = len(re.sub(r"[\W_]", "", txt)) if lang == "zh" else len(txt.split())
        tgt = int(round(n_chars / cps * 12.5)) if cps else 0
        wf[N["ref"][0]]["inputs"]["audio"] = up
        wf[N["gen"][0]]["inputs"].update(text=txt, language=TTS_LANG[lang], seed=sd, target_tokens=tgt)
        wf[N["save"][0]]["inputs"]["filename_prefix"] = "vmskill/tts_" + vo
        flac = os.path.join(el_tts.HERE, vo_dir, "_" + vo + ".flac")
        sec, peak = run("moss_tts", wf, flac, vo)
        out = os.path.join(el_tts.HERE, vo_dir, vo + ".mp3")
        if os.path.exists(out):
            os.remove(out)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", flac, "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "128k", out],
                       check=True)
        os.remove(flac)
        d = probe_audio(out)[2]
        log(dict(kind="tts", name=vo, lang=lang, model="MOSS-TTS v1.5 8B", license="Apache-2.0",
                 ref=os.path.basename(ref), seed=sd, cps=cps, target_tokens=tgt, chars=n_chars, dur=round(d, 2),
                 out="../../build/%s/%s.mp3" % (vo_dir, vo), sec=round(sec), peak=peak))
        print("[%d/%d] %s  %.2f 秒  %.2f %s/秒（%.0f 秒）" % (i, len(rows), vo, d, n_chars / max(d, 0.01),
                                                       "字" if lang == "zh" else "词", sec), flush=True)
    print("下一步：python el_tts.py asr %s --local（本机 Whisper 核读）→ vo_trim.py apply" % lang)


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
            how = "%s %d 步 %s%s" % (r.get("model", "Qwen-Image-2512"), r["steps"], "×".join(map(str, r["size"])),
                                                  "（首帧专用）" if r.get("role") == "first_frame" else "")
        elif k == "promote":
            how = "候选转正：%s（%s%s 步）" % (r["src"], "MOSS-Image " if r.get("engine") == "moss" else "", r.get("steps"))
        elif k == "tts":
            how = "MOSS-TTS v1.5 克隆 %s %.1f 秒" % (r.get("ref"), r.get("dur", 0))
        elif k == "tts_ref":
            how = "MOSS-TTS v1.5 参考音候选：%s" % (r.get("voice") or "")[:40]
        elif k == "video":
            how = "MiniMax H3 %s %s %g 秒（首帧 %s）%s" % (
                r.get("mode"), "×".join(map(str, r["size"])), r.get("secs", 0), r.get("first_frame") or "—",
                ("  **切镜 %s**" % r["cuts"]) if r.get("cuts") else "")
        elif k == "upscale":
            how = "放大 %s ← %s" % (r.get("how"), r.get("src"))
        elif k == "music":
            how = "YuE2 %s %.0f 秒：%s" % ("纯音乐" if r.get("instrumental") else "带人声", r.get("dur", 0), (r.get("style") or "")[:40])
        elif k == "sfx":
            how = "Stable Audio 3 %s %.1f 秒：%s" % (r.get("sfx_kind"), r.get("dur", 0), (r.get("text") or "")[:40])
        else:
            how = k
        L.append("| %s | %s | %s | %s |" % (out, how, r.get("seed", ""), ("%ds" % r["sec"]) if r.get("sec") else ""))
    tot = sum(r.get("sec") or 0 for r in rs)
    by = {}
    for r in rs:
        by[r["kind"]] = by.get(r["kind"], 0) + (r.get("sec") or 0)
    L += ["", "显卡时间合计 %.1f 小时：%s" % (tot / 3600, "，".join("%s %.0f 分钟" % (k, v / 60) for k, v in by.items() if v)), "",
          "授权：Qwen-Image-2512 / MOSS-Image / MOSS-TTS / SeedVR2 Apache-2.0；MiniMax H3 要在说明里署名「MiniMax H3 生成」并勾 AI 披露；"
          "YuE2 个人创作者可变现（署名可选，鼓励写 YuE2）；Stable Audio 3 要先在 Stability AI 登记，说明里写「Powered by Stability AI」。"]
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
    ap.add_argument("--trial", action="store_true")      # 试验：50 步也进候选（不盖定稿），--size 会写进文件名
    ap.add_argument("--cand")
    ap.add_argument("--turbo", action="store_true")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--size")
    ap.add_argument("--res", type=int, default=480, choices=(480, 768))   # 10-21 盲比 1:1，768p 改成点名才出
    ap.add_argument("--seedvr2", action="store_const", const="seedvr2", dest="how")
    ap.add_argument("--lanczos", action="store_const", const="lanczos", dest="how")
    ap.add_argument("--to")
    ap.add_argument("--image", action="store_true")      # upscale 静帧（默认 SeedVR2 到 4K）
    ap.add_argument("--style")
    ap.add_argument("--secs", type=float)
    ap.add_argument("--lyrics-file")
    ap.add_argument("--abc")                            # music：直接用这份 ABC 谱（跳过写谱）
    ap.add_argument("--plan", type=int)                 # music 纯音乐的曲式段数（缺省 8 段≈141 秒；Shorts 要 ~180 秒给 10）
    ap.add_argument("--kind", default="SFX")
    ap.add_argument("--enhance", action="store_true")
    ap.add_argument("--engine", default="qwen", choices=("qwen", "moss"))   # image 用哪个模型
    ap.add_argument("--lang", default="zh", choices=("zh", "en"))          # tts-ref
    ap.add_argument("--cps", type=float)                # tts：目标语速（中文字/秒、英文词/秒），不给＝模型自己定
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
        cmd_image(a.names, a.fast, a.seed, a.size, a.variants, a.trial, a.engine)
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
        if a.image:
            cmd_upscale_image(a.names, a.how or "seedvr2", a.to)
        else:
            cmd_upscale(a.names, a.how or "lanczos", a.to)
    elif a.cmd == "music":
        if not a.names or not a.style:
            sys.exit('!!! music <名> --style "风格描述" [--secs 180] [--plan 10 | --abc 谱.abc] [--lyrics-file 歌词.txt]')
        cmd_music(a.names[0], a.style, a.secs or 180, a.seed, a.lyrics_file, a.plan, a.abc)
    elif a.cmd == "sfx":
        if len(a.names) < 2:
            sys.exit('!!! sfx <名> "<描述>" [--secs 5] [--kind SFX|One-shot|Music|Instrument] [--enhance]')
        cmd_sfx(a.names[0], " ".join(a.names[1:]), a.secs or 5, a.seed, a.kind, a.enhance)
    elif a.cmd == "tts-ref":
        if a.names[:1] == ["pick"] and len(a.names) == 2:
            cmd_tts_ref_pick(a.names[1], a.lang)
        elif len(a.names) == 1:
            cmd_tts_ref(a.names[0], a.lang, a.variants if a.variants > 1 else 3, a.seed)
        else:
            sys.exit('!!! tts-ref "<音色描述>" [--lang zh|en] [--variants 3]  |  tts-ref pick <序号> [--lang zh|en]')
    elif a.cmd == "tts":
        lang = a.names[0] if a.names[:1] in (["zh"], ["en"]) else "zh"
        cmd_tts(lang, [n for n in a.names if n not in ("zh", "en")], a.cps, a.seed)
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
