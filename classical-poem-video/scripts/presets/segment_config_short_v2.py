# -*- coding: utf-8 -*-
"""__TITLE__ —— Short，新做法七条（2026-11-07），竖版 1080x1920、外挂 SRT、中英双语。

由 `episode.py new --type short` 生成，放在 <项目>/build/segment_config.py，模板 make_story_v.py 不用改。
带「填」的都要改；其余是这一型定下来的值，改之前先看 references/format-short-v2.md。
参数出自 2026-11-07 那批测试 Short（《他留給自己的》等四支）。
"""
import os

TITLE, SUBTITLE = "__TITLE__", ""           # 填：片名 / 一行副题（地点 · 年代）
SEG_NAME = "成片_竖版"
COVER_NAME = "封面_竖版.png"
COVER_FROM = 1                               # 封面用第几镜的图：先挑最好看的脸或景
CLAIMS = []                                  # 事实分级写在 ../查证记录.md

# ---- 旁白：一句一条。第一句就抛结局或最强的事实，再倒叙；收尾一句情绪总结，不对观众喊话 ----
NARR = [
    # {"vo": "VO_01a", "shot": 1, "txt": "中文一句，｜竖线是屏内换行", "en": "English line,｜same slot."},
    # 末句可以给 "post": 0.8 留一口气
]
VO_DIR = "vo"
HARD_LIMIT = 180                             # Shorts 硬线
PRE_DEF, POST_DEF = 0.03, 0.08               # 句内停顿
GAP_PRE, GAP_POST = 0.12, 0.20               # 镜间停顿
TIGHT_PACING = True                          # 0 秒开口、边说边切镜；放行「冷开场留白」「转场落静默」两条旧检查
EN_RATE = 2.8                                # 填：每支先量，不跨片子抄

# ---- 顶部常驻两行标题条：中途刷进来的人一眼知道在讲什么 ----
TOP_BAR = dict(lines=["填：第一行", "填：第二行"], y=250, gap=109, fs=(76, 62))
TITLE_CARD = None
ENDCARD = None
SHOT_LABELS = {}                             # AI 声明只写简介，不打角标

# ---- 配乐：轻，切掉 150Hz 以下；也可以不要 ----
MUSIC_MODE = "library"                       # 填：library / generated / none
MUSIC_FROM_LIBRARY = ""                      # 填：库里的文件名
MUSIC = ""                                   # 填：配乐文件的完整路径
MUSIC_GAIN = -21.0
MUSIC_HP = 150
MUSIC_IN = 0.0
MUSIC_CREDIT = {}
SFX = []

# ---- 画面：5~7 秒换一镜。图不够就一张图切远近两个景别（同一个 src，第二条给 zoom / cx / cy）----
PREP = (2160, 3840)
XFADE = 0.6
TAIL = 1.0
FADE_IN, FADE_OUT = 0.2, 2.0
VIGNETTE = ""
GRADE = ""
MOTION = "kenburns"
PLATE_COLOR = "black"
VIDEO_FIT = "crop"
SRC_NATIVE = None                            # 填：出图后按 ffprobe 量到的实际尺寸
IMG_SOURCE = "generated"
CREDITS = {}                                 # 找来的图每张登记：{"实物/x.jpg": {"title","source","holder","license","url"}}
CLIPS = [
    # {"src": "生成/01_名字_2160x3840.png"},
    # {"src": "生成/01_名字_2160x3840.png", "zoom": 1.5, "cx": 0.68, "cy": 0.55},   # 同一张图的近景
    # {"src": "实物/x.jpg", "fit": "plate"},                                          # 档案照片整张贴台纸
]
for c in CLIPS:
    c.setdefault("zoom", 1.00); c.setdefault("cx", 0.50); c.setdefault("cy", 0.50); c.setdefault("tweak", "")
STATIC_SHOTS = set()                         # 填：不运镜的镜号（贴纸镜）
SHOTS = []
for n in range(1, len(CLIPS) + 1):
    if n in STATIC_SHOTS:
        SHOTS.append(dict(motion="static", z=(1.0, 1.0), f0=(0.5, 0.5), f1=(0.5, 0.5)))
    elif n == len(CLIPS):
        SHOTS.append(dict(z=(1.10, 1.00), f0=(0.5, 0.5), f1=(0.5, 0.5)))      # 末镜拉开
    else:
        SHOTS.append(dict(z=(1.00, 1.10), f0=(0.5, 0.5), f1=(0.5, 0.5)))      # 其余缓推

# ---- 字幕与语言：外挂 SRT（烧录字幕和多语言音轨不能共存）----
SUB_MODE = "srt"
LANGS = ["zh", "en"]
SCRIM_ALPHA = 0.0
SUB_MAX_CHARS_EN = 48
LANG_BORROW = 0.30

# ---- 封面：Short 只有一张，做中英双语。lines 里是 (文字, 字号, y) ----
COVER_POLARITY = None
COVER_HEAVY = True
# COVER_TEXT = {"zh": dict(lines=[("中文小字", 96, 300), ("中文大字", 150, 470), ("English Title", 84, 1600)])}

# ---- 门禁：写人话，不写 True ----
GATE_SCRIPT_OK = ""      # 填：日期＋用户读过讲述稿之后的原话
GATE_PREVIEW_OK = ""     # 填：用户听过检查片的结论；按惯例不出检查片时，写清依据和拿什么顶替
