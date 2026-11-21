"""回归：cartoon_jobs.py（卡通片出图分工）——离线，不连 ComfyUI、不碰显卡。

    python tests/test_cartoon_jobs.py

验的是会静默出错的地方（都是 2026-11-21 第二频道长片踩过的）：
  - 空镜（T2I_SHOTS）必须走纯文生图、不带参考图；把它从 T2I_SHOTS 拿掉，它就会去编辑模型 —— 测试要能看出来；
  - 有人物的镜拿对参考图；参考键为空＝只借画风，用 STYLE_SCENE，并在提示词里写「只借画风」；
  - REF_FILE 里登记的外部图优先于 角色/<键>.png；
  - 缺参考图的镜跳过并报出来，不能拿空参考去出；
  - 已有的图不重出。
"""
import importlib, os, shutil, sys, tempfile

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.environ.get("VMSKILL_SCRIPTS") or os.path.join(ROOT, "classical-poem-video", "scripts")
FAILS = []


def ok(c, msg):
    print(("  ok  " if c else "  FAIL ") + msg)
    if not c:
        FAILS.append(msg)


CONFIG = '''
REF_STYLE = "RS "
EDIT_STYLE = "ES "
T2I_SCENE = "TS "
REFS = {"STYLE_SCENE": "empty yard", "W": "a widow", "X": "someone never made"}
SHOTS = {"01": ("W", "widow cries"), "02": ("", "crowd of villagers"), "03": ("", "row of archways"),
         "04": ("OLD", "old woman in bed"), "05": ("X", "missing ref"), "06": ("W", "already made")}
T2I_SHOTS = %s
T2I_SEED = {"03": 22}
SHOT_SEED = {}
REF_FILE = {"OLD": %r}
'''


def load(tmp, t2i):
    build = os.path.join(tmp, "build")
    os.makedirs(build, exist_ok=True)
    ext = os.path.join(tmp, "外部_old.png")
    open(ext, "wb").write(b"x")
    open(os.path.join(build, "cartoon_config.py"), "w", encoding="utf-8").write(CONFIG % (t2i, ext))
    for f in ("cartoon_jobs.py", "qwen_edit.py", "comfy_gen.py"):
        shutil.copy(os.path.join(SCRIPTS, f), build)
    if os.path.isdir(os.path.join(SCRIPTS, "comfy")):
        shutil.copytree(os.path.join(SCRIPTS, "comfy"), os.path.join(build, "comfy"), dirs_exist_ok=True)
    for m in ("cartoon_jobs", "cartoon_config", "qwen_edit", "comfy_gen"):
        sys.modules.pop(m, None)
    sys.path.insert(0, build)
    cj = importlib.import_module("cartoon_jobs")
    sys.path.remove(build)
    gen = os.path.join(tmp, "素材", "生成")
    os.makedirs(os.path.join(gen, "角色"), exist_ok=True)
    os.makedirs(os.path.join(gen, "原图"), exist_ok=True)
    for k in ("W", "STYLE_SCENE"):
        open(os.path.join(gen, "角色", k + ".png"), "wb").write(b"x")
    open(os.path.join(gen, "原图", "S06.png"), "wb").write(b"x")
    calls = {"t2i": [], "edit": []}
    cj.start = lambda: None
    cj.cg.load_wf = lambda k: {}
    cj.cg.log = lambda r: None

    def fake_t2i(n, steps, sd, w, h, out, wf0, label, **kw):
        calls["t2i"].append((n, steps, sd, cj.cg.ew.prompt(n)))

    def fake_build(mode, prompt, refs, fast, size, seed):
        return dict(prompt=prompt, refs=refs, fast=fast, size=size)

    def fake_run(key, wf, out, label):
        calls["edit"].append((label, wf))
        return 1.0, None
    cj.cg._gen_image = fake_t2i
    cj.qe.build = fake_build
    cj.cg.run = fake_run
    return cj, calls, ext


def main():
    tmp = tempfile.mkdtemp()
    try:
        print("== 正常配置：03 是空镜")
        cj, calls, ext = load(tmp, '["03"]')
        cj.do_shots([])
        t2i = {c[0]: c for c in calls["t2i"]}
        edit = {c[0]: c[1] for c in calls["edit"]}
        ok(list(t2i) == ["03"], "只有空镜 03 走文生图（%s）" % list(t2i))
        ok(t2i["03"][1] == 50 and t2i["03"][2] == 22, "空镜 50 步、用 T2I_SEED 的种子")
        ok(t2i["03"][3].startswith("TS ") and "No text" in t2i["03"][3], "空镜提示词＝T2I_SCENE＋画面＋不要字")
        ok("S03" not in edit, "空镜不进编辑模型")
        ok(edit["S01"]["refs"][0].endswith(os.path.join("角色", "W.png")) and edit["S01"]["fast"],
           "人物镜 01 用 W 的定妆图、Lightning 4 步")
        ok(edit["S02"]["refs"][0].endswith("STYLE_SCENE.png") and "only for the art style" in edit["S02"]["prompt"],
           "参考键为空 → STYLE_SCENE ＋「只借画风」")
        ok(edit["S04"]["refs"][0] == ext, "REF_FILE 的外部图优先")
        ok("S05" not in edit, "缺参考图的 05 被跳过")
        ok("S06" not in edit, "已有的 06 不重出")
        ok(edit["S01"]["size"] == (1920, 1088), "人物镜默认 1920x1088（16 的倍数）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp()
    try:
        print("== 变异：T2I_SHOTS 拿掉 03")
        cj, calls, _ = load(tmp, '[]')
        cj.do_shots([])
        ok(not calls["t2i"] and any(c[0] == "S03" for c in calls["edit"]),
           "03 不在 T2I_SHOTS 时就会进编辑模型（测试分得出两条路）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("全部通过" if not FAILS else "**%d 条失败**" % len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
