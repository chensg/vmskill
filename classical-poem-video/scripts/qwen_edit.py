# -*- coding: utf-8 -*-
"""本机 Qwen-Image-Edit-2511（int8，Apache-2.0）。照官方模板 image_qwen_image_edit_2511_int8 手搭 API 图，走 comfy_gen 的
run()（功耗红线、换模型 /free、等队列都在里面）。

  python qwen_edit.py gen  <out.png> "<提示词>" <参考图1> [参考图2] [参考图3] [--fast] [--size 1664x928] [--seed N]
      拿参考图里的人物出新场景（空 latent，尺寸自定）
  python qwen_edit.py fix  <out.png> "<修改指令>" <原图> [--fast] [--seed N]
      在原图上改（latent＝原图编码，尺寸跟原图走 FluxKontextImageScale）

--fast＝Lightning 4 步 cfg 1；默认 40 步 cfg 4（模板默认）。11-21 卡通片实测 4 步比 40 步颜色鲜亮、更像目标画风，15 秒一张。
项目目录：在 <项目>/build/ 里跑就是上一级；别处跑加 --proj <项目目录>。批量出图用 cartoon_jobs.py，它 import 这个文件。"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.append(os.path.expanduser(r"~/.claude/skills/classical-poem-video/scripts"))
import comfy_gen as cg

UNET = "qwen_image_edit_2511_int8_convrot.safetensors"
LORA = "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors"
cg.NODES["qwen_edit"] = dict(save=("15", "SaveImage"))
cg.FAMILY["qwen_edit"] = "image_edit"


def build(mode, prompt, refs, fast, size, seed):
    wf = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.1}},
        "5": {"class_type": "CFGNorm", "inputs": {"model": ["4", 0], "strength": 1.0}},
    }
    model = ["5", 0]
    if fast:
        wf["6"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["5", 0], "lora_name": LORA, "strength_model": 1.0}}
        model = ["6", 0]
    imgs = {}
    for i, r in enumerate(refs[:3]):
        li, sc = str(20 + i), str(30 + i)
        wf[li] = {"class_type": "LoadImage", "inputs": {"image": cg.upload(r)}}
        wf[sc] = {"class_type": "FluxKontextImageScale", "inputs": {"image": [li, 0]}}
        imgs["image%d" % (i + 1)] = [sc, 0]
    wf["7"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": dict(clip=["2", 0], vae=["3", 0], prompt=prompt, **imgs)}
    wf["8"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": dict(clip=["2", 0], vae=["3", 0], prompt="", **imgs)}
    wf["9"] = {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {"conditioning": ["7", 0], "reference_latents_method": "index_timestep_zero"}}
    wf["10"] = {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {"conditioning": ["8", 0], "reference_latents_method": "index_timestep_zero"}}
    if mode == "fix":
        # 11-21：模板拿缩到 ~1MP 的图编码，1088x1920 改完变 752x1392。latent 改用原图（宽高都是 16 的倍数就行），条件图仍用缩过的
        wf["11"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["20", 0], "vae": ["3", 0]}}
    else:
        w, h = size
        wf["11"] = {"class_type": "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}}
    wf["12"] = {"class_type": "KSampler", "inputs": {"model": model, "seed": seed, "steps": 4 if fast else 40, "cfg": 1.0 if fast else 4.0,
                                                    "sampler_name": "euler", "scheduler": "simple", "positive": ["9", 0],
                                                    "negative": ["10", 0], "latent_image": ["11", 0], "denoise": 1.0}}
    wf["13"] = {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["3", 0]}}
    wf["15"] = {"class_type": "SaveImage", "inputs": {"images": ["13", 0], "filename_prefix": "vmskill/qwen_edit"}}
    return wf


def main():
    a = sys.argv[1:]
    fast = "--fast" in a
    seed = int(a[a.index("--seed") + 1]) if "--seed" in a else 21
    size = tuple(map(int, a[a.index("--size") + 1].split("x"))) if "--size" in a else (1664, 928)
    proj = a[a.index("--proj") + 1] if "--proj" in a else (
        os.path.dirname(os.getcwd()) if os.path.basename(os.getcwd()) == "build" else os.getcwd())
    pos = [x for i, x in enumerate(a) if not x.startswith("--") and not (i and a[i - 1] in ("--seed", "--size", "--proj"))]
    mode, out, prompt, refs = pos[0], pos[1], pos[2], pos[3:]
    assert mode in ("gen", "fix") and refs, __doc__
    cg.set_proj(proj)
    if not cg.alive():
        cg.cmd_start()
        for _ in range(90):
            if cg.alive():
                break
            time.sleep(5)
    wf = build(mode, prompt, refs, fast, size, seed)
    sec, peak = cg.run("qwen_edit", wf, os.path.abspath(out), os.path.basename(out))
    cg.log(dict(kind="image_edit", model="Qwen-Image-Edit-2511 int8" + (" + Lightning4" if fast else ""), license="Apache-2.0",
                mode=mode, seed=seed, prompt=prompt, refs=[os.path.basename(r) for r in refs], out=os.path.basename(out),
                sec=round(sec), peak=peak))
    print("存 %s（%.0f 秒）" % (out, sec))


if __name__ == "__main__":
    main()
