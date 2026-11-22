# -*- coding: utf-8 -*-
"""__TITLE__ 的卡通出图配置，cartoon_jobs.py 读它。放在 <项目>/build/。规矩和翻车记录见 references/cartoon.md。

填法：
- REFS：每个有名有姓、要在多个镜头里认得出来的人，一张定妆描述（长相＋发型＋衣服，越具体越稳）。
  STYLE_SCENE 是一张**没有人**的画风样板，给「只借画风」的镜头当参考；别删。
- SHOTS：镜号 → (参考键, 画面)。参考键填 REFS 里的人，两三人同框写 "A+B"（各给一张定妆图，最多 3 张）；"" ＝只借画风（会用 STYLE_SCENE）。
  画面句写「谁、在哪、做什么、什么表情」，人用 "the young widow from the reference" 这种说法指参考图。
- T2I_SHOTS：**空镜**（没有主要人物的景、物、建筑、人群远景）一律列进来，走纯文生图，不给参考图。
"""
# 画风句：A 粗线漫画（2026-11-21《Why It's Hell to Be a Chaste Widow》定的）。换画风就三句一起换。
REF_STYLE = ("2D cartoon illustration in the style of a modern YouTube animated history explainer: thick uniform black outlines, "
             "completely flat bright colors with no gradients, simple shapes, big expressive cartoon eyes, webcomic look, not "
             "realistic, not painterly. Character reference sheet: one person (or the people named) standing, full body, front "
             "view, plain light grey background, nothing else in the picture. ")
EDIT_STYLE = ("Keep exactly the same 2D cartoon style as the reference images: thick uniform black outlines, flat bright colors, "
              "big expressive cartoon eyes. One single widescreen image, not a comic page, no panels. Historically accurate "
              "clothing, hairstyles and objects for the period; no modern objects. ")
T2I_SCENE = ("2D cartoon illustration in the style of a modern YouTube animated history explainer: thick uniform black outlines, "
             "completely flat bright colors with no gradients, simple shapes, big expressive cartoon eyes, webcomic look, not "
             "realistic, not painterly. One single widescreen image, not a comic page, no panels. Historically accurate clothing, "
             "buildings and objects for the period; no modern objects. ")
# ⚠ 画风句里别写照明（「只用蜡烛和油灯照明」→ 几乎每张都摆一排灯）；要灯就写进那一镜的画面句。

REFS = {
    "STYLE_SCENE": "An empty courtyard of a traditional Chinese house with grey tiled roofs, a wooden door and a potted plant; "
                   "no people. Wide view.",
    # "W": "A young Ming dynasty Chinese widow of eighteen: round face, large dark brown eyes, ... plain white hemp mourning robe.",
}

SHOTS = {
    # "01": ("W", "Close-up: the young widow from the reference sits at a wooden table at night, ... Candlelight."),
    # "07": ("", "A row of tall grey stone memorial archways on a village road at dusk, orange sky, no people."),
}

T2I_SHOTS = []            # 空镜，例：["07", "24"]；中国建筑要写 "Chinese ... with tiled roofs"，不然会出罗马拱门
T2I_SEED = {}             # 重出某张空镜：换种子，例 {"24": 22}
SHOT_SEED = {}            # 重出某张人物镜：换种子
REF_SEED = {}
REF_FILE = {}             # 参考键 → 外部图路径（比如关联 Short 里已经定好的人物），优先于 角色/<键>.png
