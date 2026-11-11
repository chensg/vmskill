# -*- coding: utf-8 -*-
"""torchaudio HDemucs（MUSDB-HQ+）把配乐拆成人声/伴奏：报每段人声占比，并存去人声版 → ../素材/配乐/去人声/<名>.wav
用 ComfyUI 的 python_embeded 跑（有 torch+torchaudio+CUDA）。"""
import os, sys, glob, subprocess
import torch, torchaudio
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
MUS = os.path.join(os.path.dirname(HERE), "素材", "配乐")
OUT = os.path.join(MUS, "去人声"); os.makedirs(OUT, exist_ok=True)
b = torchaudio.pipelines.HDEMUCS_HIGH_MUSDB_PLUS
model = b.get_model().cuda().eval()
SR = b.sample_rate
names = model.sources  # drums bass other vocals
def load(p):
    pcm = subprocess.run(["ffmpeg", "-v", "quiet", "-i", p, "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    import numpy as np
    return torch.from_numpy(np.frombuffer(pcm, dtype=np.float32).copy()).view(-1, 2).T
for p in sorted(glob.glob(os.path.join(MUS, sys.argv[1] if len(sys.argv) > 1 else "MM_*.mp3"))):
    w = load(p)
    ref = w.mean(0); m, s = ref.mean(), ref.std() + 1e-8
    x = ((w - m) / s)
    seg = SR * 10; ov = SR
    outs = torch.zeros(len(names), 2, w.shape[1])
    cnt = torch.zeros(w.shape[1])
    with torch.no_grad():
        i = 0
        while i < w.shape[1]:
            j = min(i + seg, w.shape[1])
            y = model(x[None, :, i:j].cuda())[0].cpu()
            outs[:, :, i:j] += y; cnt[i:j] += 1
            i += seg - ov
    outs = outs / cnt.clamp(min=1) * s + m / len(names)
    voc = outs[names.index("vocals")]
    inst = outs.sum(0) - voc
    # 每 1 秒一窗：人声能量 / 全部能量
    win = SR
    v = voc.pow(2).mean(0); a = w.pow(2).mean(0)
    n = v.shape[0] // win
    vr = (v[:n * win].view(n, win).mean(1) / (a[:n * win].view(n, win).mean(1) + 1e-9))
    hot = [k for k in range(n) if vr[k] > 0.15]
    name = os.path.splitext(os.path.basename(p))[0]
    raw = inst.clamp(-1, 1).T.contiguous().numpy().astype("float32").tobytes()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
                    os.path.join(OUT, name + ".wav")], input=raw, check=True)
    print("%s  人声占比 均值 %.3f  最大 %.2f  >15%% 的秒数 %d%s" % (name, vr.mean(), vr.max(), len(hot),
          ("  例：" + ",".join("%d:%02d" % divmod(k, 60) for k in hot[:8])) if hot else ""), flush=True)
