# -*- coding: utf-8 -*-
"""MiniMax Music3（本机 ComfyUI 原生节点）出纯音乐配乐 → ../素材/配乐/MM_段N_k.mp3
python mm_music.py 1 2 3 4 5 [--k 1] [--seed 101] [--steps 30]
工作流照 ComfyUI/user/default/api/minimax_music3_text2music.json，lyrics 只给 [Instrumental]。
"""
import argparse, copy, json, os, shutil, sys, time, urllib.request

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "素材", "配乐")
ROOT = r"D:\MiniMax-H3"
URL = "http://127.0.0.1:8188"
WF = os.path.join(ROOT, "ComfyUI_windows_portable", "ComfyUI", "user", "default", "api", "minimax_music3_text2music.json")
sys.path.insert(0, HERE)
from music_prompts import CAP, SECS, TAIL      # 每支片自己的：各段的描述、秒数、共用的乐器与结构说明（模板在 presets/）
# 11-05：Verse/Bridge 這類段名會引出人聲，只用不帶唱的段名
LYR = "\n\n".join("[%s]\n[Instrumental]" % s for s in ["Intro", "Interlude", "Interlude", "Interlude", "Interlude", "Interlude", "Interlude", "Outro"])


def req(path, data=None):
    r = urllib.request.Request(URL + path, data=json.dumps(data).encode() if data is not None else None,
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=60).read() or b"{}")


ap = argparse.ArgumentParser()
ap.add_argument("segs", nargs="+", type=int)
ap.add_argument("--k", type=int, default=1)
ap.add_argument("--seed", type=int, default=101)
ap.add_argument("--steps", type=int, default=30)
a = ap.parse_args()
base = json.load(open(WF, encoding="utf-8"))
os.makedirs(OUT, exist_ok=True)
req("/free", {"unload_models": True, "free_memory": True})
for s in a.segs:
    wf = copy.deepcopy(base)
    seed = a.seed + s * 10 + a.k
    wf["13"]["inputs"].update(caption=CAP[s] + "\n" + TAIL, lyrics=LYR, seed=seed, max_duration=float(SECS[s]))
    wf["9"]["inputs"].update(seed=seed, steps=a.steps)
    name = "MM_段%d_%d" % (s, a.k)
    wf["35"]["inputs"]["filename_prefix"] = os.path.basename(os.path.dirname(HERE)) + "/" + name
    t0 = time.time()
    pid = req("/prompt", {"prompt": wf})["prompt_id"]
    while True:
        time.sleep(5)
        h = req("/history/" + pid)
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("status_str") == "error":
                sys.exit("!!! %s 出错：%s" % (name, json.dumps(st.get("messages"), ensure_ascii=False)[:800]))
            outs = [f for n in h[pid]["outputs"].values() for f in n.get("audio", [])]
            if outs:
                f = outs[0]
                src = os.path.join(ROOT, "output", f.get("subfolder", ""), f["filename"])
                dst = os.path.join(OUT, name + ".mp3")
                shutil.copy2(src, dst)
                print("存 %s（种子 %d，%.0f 秒生成）" % (dst, seed, time.time() - t0), flush=True)
                break
print("MMDONE", flush=True)
