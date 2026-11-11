# -*- coding: utf-8 -*-
"""__TITLE__ 影片镜的动作提示词（本机 Pika H3 8 步 HD → SeedVR2）。由 `episode.py new --type long` 生成，放在 build/。

帧数 = 旁白秒数 + 0.5 秒、24fps，取 17k+5，124~362。秒数读 build/_shots.tsv（`python film.py tsv` 出）。
旁白超过 15 秒的镜拆两条：第二条从第一条成片的尾帧接着拍（first="@<第一条的 id>"），再在 film_config.py 的
CLIPS 里写 {"14": ["G14a", "G14b"]}。

    python -X utf8 vid_prompts.py     # 列清单 + 估时
    python -X utf8 run_pika.py [id…]  # 逐条跑，已有成品就跳过（长任务用 runlog.py 起）
"""
import io, math, os
HERE = os.path.dirname(os.path.abspath(__file__))
PREFIX = "G"          # 影片和首帧图的档名前缀：素材/影片/G<镜号>.mp4；和 film_config.py 的 VID_PREFIX 一致

END = (" Natural, small, restrained, realistic human motion; every person stays the same person, "
       "nobody's appearance or age changes; no new people appear. Anyone who walks moves forward in the direction they are facing; nobody walks backward.")
CAM = " The camera is almost still, a very slow gentle push in."
STILL = " The camera stays almost still."
EMPTY = " No person appears anywhere in the frame at any time."

V = {}  # id → (镜号, 首帧, 尾帧 or None, 提示词, 秒数覆盖 or None)


def add(shot, prompt, cam=CAM, id=None, first=None, secs=None, last=None):
    id = id or PREFIX + shot
    head = "Use <Picture 1> as the first frame and <Picture 2> as the last frame. " if last else "Use <Picture 1> as the first frame. "
    V[id] = (shot, first or PREFIX + shot, last, head + prompt + cam + END, secs)


# ---- 填：一镜一条。只写「动什么」，画面里有什么首帧图已经定了；声音写在 Audio: 后面 ----
# add("01", "The people kneeling along the road stay kneeling and still; their breath mists in the cold air. Audio: wind, distant hooves.")
# add("05", "Snow falls slowly over the empty courtyard." + EMPTY, cam=STILL)
# add("14", "…first half…", id="G14a")
# add("14", "…second half…", id="G14b", first="@G14a")


def frames(id):
    shot, _, _, _, secs = V[id]
    if secs is None:
        for ln in io.open(os.path.join(HERE, "_shots.tsv"), encoding="utf-8"):
            p = ln.split("\t")
            if p[0] == shot:
                secs = float(p[2])
    if secs is None:
        raise SystemExit("!!! _shots.tsv 里没有镜 %s —— 先跑 python film.py tsv" % shot)
    n = math.ceil((secs + 0.5) * 24)
    k = max(7, math.ceil((n - 5) / 17))
    return min(362, 17 * k + 5)


if __name__ == "__main__":
    import sys; sys.stdout.reconfigure(encoding="utf-8")
    tot = 0
    for i in V:
        f = frames(i); tot += f
        print(i, V[i][0], V[i][1], f, "首尾" if V[i][2] else "")
    # 估时：Pika 8HD 约 3.3 秒/帧 + SeedVR2 约 3 秒/帧（《剩人》实测 124 帧 ≈ 13 分钟）
    print("%d 条，%d 帧，估 %.0f 小时" % (len(V), tot, tot * 6.3 / 3600))
