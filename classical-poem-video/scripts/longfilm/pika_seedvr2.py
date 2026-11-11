# -*- coding: utf-8 -*-
"""Pika H3 Flex 原版六步 图生视频 1280×704（720 档） → SeedVR2 放大到 1080p。

    python -X utf8 pika_seedvr2.py <首帧图> <提示词.txt> <输出目录> [--frames 124] [--seed 42]

工作流：D:\\MiniMax-H3\\workflows\\pika_original_api\\video_pika_h3_flex_original_i2v_6step.json（只改图、提示词、尺寸、帧数、种子）；
SeedVR2：D:\\ani\\吴兆骞\\build\\comfy\\seedvr2.api.json（倍率 1.5×1.002、分段开）。
"""
import argparse, json, os, subprocess, sys, time, urllib.parse, urllib.request, uuid

URL = "http://127.0.0.1:8188"
HERE = os.path.dirname(os.path.abspath(__file__))


def _wf(name, fallback):
    """工作流先在技能的 comfy/ 里找（脚本旁边，或上一级），找不到退回这台机器上原来的位置。"""
    for d in (os.path.join(HERE, "comfy"), os.path.join(HERE, "..", "comfy")):
        if os.path.isfile(os.path.join(d, name)):
            return os.path.join(d, name)
    return fallback


PIKA_WF = {"6": _wf("video_pika_h3_flex_original_i2v_6step.json",
                    r"D:\MiniMax-H3\workflows\pika_original_api\video_pika_h3_flex_original_i2v_6step.json"),
           "8hd": _wf("video_pika_h3_i2v_8step_hd.json",
                      r"D:\MiniMax-H3\workflows\pika_api\video_pika_h3_i2v_8step_hd.json")}   # 节点号相同
SVR_WF = _wf("seedvr2.api.json", r"D:\ani\吴兆骞\build\comfy\seedvr2.api.json")


def req(path, data=None, timeout=60):
    body = None if data is None else json.dumps(data).encode()
    r = urllib.request.Request(URL + path, data=body, method="POST" if body else "GET")
    if body:
        r.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(r, timeout=timeout) as f:
        raw = f.read()
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def upload(path):
    b = "----" + uuid.uuid4().hex
    name = os.path.basename(path)
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + open(path, "rb").read() + \
           f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{b}--\r\n".encode()
    r = urllib.request.Request(URL + "/upload/image", data=body, method="POST")
    r.add_header("Content-Type", "multipart/form-data; boundary=" + b)
    with urllib.request.urlopen(r, timeout=300) as f:
        return json.loads(f.read())["name"]


def run(wf, save_node, out, label):
    req("/free", {"unload_models": True, "free_memory": True})
    time.sleep(3)
    t0 = time.time()
    pid = req("/prompt", {"prompt": wf, "client_id": "pika_test"})["prompt_id"]
    last = -1
    while True:
        time.sleep(10)
        h = req("/history/" + pid).get(pid)
        if h:
            st = h.get("status", {})
            if st.get("status_str") == "error":
                sys.exit("!!! %s 失败：%s" % (label, json.dumps(st.get("messages"), ensure_ascii=False)[:1500]))
            break
        m = int(time.time() - t0) // 60
        if m != last:
            print("   … %s %d 分钟" % (label, m), flush=True)
            last = m
    files = [f for v in h["outputs"][save_node].values() if isinstance(v, list) for f in v if isinstance(f, dict)]
    f = files[0]
    q = urllib.parse.urlencode(dict(filename=f["filename"], subfolder=f.get("subfolder", ""), type=f.get("type", "output")))
    open(out, "wb").write(req("/view?" + q, timeout=600))
    print("%s 完成 %.0f 秒 → %s" % (label, time.time() - t0, out), flush=True)


ap = argparse.ArgumentParser()
ap.add_argument("image"); ap.add_argument("prompt"); ap.add_argument("outdir")
ap.add_argument("--frames", type=int, default=124); ap.add_argument("--seed", type=int, default=42)
ap.add_argument("--wf", choices=list(PIKA_WF), default="6")
ap.add_argument("--last", help="尾帧图（首尾帧生成）")
ap.add_argument("--name", help="输出档名（默认用首帧图档名；同一张首帧跑多个版本时必须给）")
a = ap.parse_args()
os.makedirs(a.outdir, exist_ok=True)
stem = a.name or os.path.splitext(os.path.basename(a.image))[0]
p720 = os.path.join(a.outdir, stem + "_pika%s_704.mp4" % a.wf)

if not os.path.exists(p720):
    wf = json.load(open(PIKA_WF[a.wf], encoding="utf-8"))
    ff = os.path.join(a.outdir, stem + "_1280x704.png")   # H3 要求宽高是 32 的倍数，720 会在采样时报 shape 错
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.image, "-vf",
                    "scale=1280:704:force_original_aspect_ratio=increase:flags=lanczos,crop=1280:704", ff], check=True)
    wf["17"]["inputs"]["image"] = upload(ff)
    if a.last:                                            # 首尾帧：尾帧同样裁好，接到 last_frame
        lf = os.path.join(a.outdir, stem + "_last_1280x704.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.last, "-vf",
                        "scale=1280:704:force_original_aspect_ratio=increase:flags=lanczos,crop=1280:704", lf], check=True)
        wf["18"] = {"class_type": "LoadImage", "inputs": {"image": upload(lf)}}
        wf["7"]["inputs"]["last_frame"] = ["18", 0]
    wf["7"]["inputs"].update(prompt=open(a.prompt, encoding="utf-8").read().strip(),
                             width=1280, height=704, length=a.frames)
    wf["8"]["inputs"]["noise_seed"] = a.seed
    wf["16"]["inputs"]["filename_prefix"] = "Pika_H3_Original/%s_%s" % (stem, a.wf)
    run(wf, "16", p720, "Pika %s 1280x704" % a.wf)

raw = os.path.join(a.outdir, stem + "_%s_seedvr2_raw.mp4" % a.wf)
wf = json.load(open(SVR_WF, encoding="utf-8"))
wf["73"]["inputs"]["file"] = upload(p720)
wf["66:57"]["inputs"]["resize_type.multiplier"] = round(1080 / 704 * 1.002, 4)
wf["66:105"]["inputs"]["value"] = True
wf["76"]["inputs"]["filename_prefix"] = "pika_test/" + stem + "_seedvr2"
run(wf, "76", raw, "SeedVR2 → 1080p")

out = os.path.join(a.outdir, stem + "_pika%s_1080.mp4" % a.wf)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", raw, "-i", p720, "-map", "0:v", "-map", "1:a?",
                "-vf", "scale=1920:1080:force_original_aspect_ratio=increase:flags=lanczos,crop=1920:1080,setsar=1",
                "-c:v", "libx264", "-crf", "14", "-preset", "slow", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                out], check=True)
os.remove(raw)
req("/free", {"unload_models": True, "free_memory": True})
print("DONE", out)
