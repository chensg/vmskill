# -*- coding: utf-8 -*-
"""
古诗词短片 · 竖版构建脚本模板 (1080x1920)

============================ 怎么用这份文件 ============================
里面**留着《雨霖铃·电影写实版》那一支的真实配置**，不是占位符。
这样你 copy 过去就能立刻 `python make_v.py check` 跑通、看见这套机器在做什么，
而不是对着一堆 `dict(...)  # ...` 猜。

换一支时**整块替换**下面这七处，其余逻辑一行都不用动：
    TITLE/AUTHOR/OUT_NAME/COVER_*、POLARITY/FLIP_SHOTS、CLIPS、SHOTS、
    LINES、POEMS、SFX（以及要不要粒子层）
替换完先跑 `check`，通过了再碰素材。**别保留上一支的诗句和分镜。**

这份是竖版。横版见 make_h.py —— 但注意 make_h.py 还是旧模板，
没有 check_safe / vig_factor / FLIP_SHOTS / 目标响度音效 / 粒子方向自验
这几样，做横版时要么先把它们移植过去，要么心里有数。
=======================================================================

  python make_v.py check   # 时间轴自检(可读性/转场落点/运镜行程/安全区/音乐)。永远先跑它
  python make_v.py prep    # 裁 9:16 + 统一调色 -> img01..img15，并自动 probe
  python make_v.py probe   # 只打亮度网格，不重新生成图
  python make_v.py trace   # 量镜头真正经过的区域（缺图会跳过），出图阶段就能判能不能用
  python make_v.py fx      # 生成残雨层 + 落叶层（纯 ffmpeg 合成，不用素材）
  python make_v.py pick    # 用 ebur128 + maximin 选音乐切入点
  python make_v.py a       # 每张图做 Ken Burns -> shots/
  python make_v.py b       # xfade 溶解转场 -> master.mp4（无字、无粒子）
  python make_v.py c       # 粒子层 + 混音 + 归一 + 烧字幕 -> 成片
  python make_v.py still   # 烧预览并抽静帧，用眼睛验字幕认不认得出
  python make_v.py measure # 从无字 master 量字幕底的亮度，用数字验它够不够
  python make_v.py cover   # 封面（单独的 img16）
  python make_v.py all     # prep + fx + a + b + c

留着的这一支是**暗调写实**，和纸本画种（水墨/工笔/水彩）**极性整个相反**：
白字 + 黑描边、黑场淡入淡出、pass_a 加 vignette、pass_c 留颗粒。
纸本画面里这三样都是"脏"，暗调实拍里它们是"对"。做纸本版时记得全部翻回去。
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ================= 这一支的内容 =================
TITLE, AUTHOR = "雨霖铃", "宋·柳永"
OUT_NAME = "雨霖铃·电影写实版_竖版.mp4"
COVER_NAME = "雨霖铃·电影写实版_竖版封面.png"
COVER_FROM = 16             # 封面单独出一张图(img16)，不从正片里取

# ================= 明暗极性 =================
# 电影写实：暮色、雨后、江上夜、拂晓残月。底子本来就是暗的，
# 所以和前六支**相反** —— 近白色字 + 不透明黑描边 + 右侧压暗 scrim。
#
# FLIP_SHOTS 是"极性和全局相反"的镜号(1 起)。这一支唯一的风险镜是 13
# （春日繁花楼台，全片最亮的一张）—— 但**不要先入为主**填进去，
# 《清平调》那次浓艳的重彩实测反而一条告警都没有。出图跑完 trace 再按实测填。
POLARITY = "light_on_dark"
TITLE_POLARITY = "light_on_dark"
FLIP_SHOTS = set()

# **量完关掉的。** 开工时按"写实照片右上难免有亮天/反光"默认开了 0.28，
# 但两张样图（镜5 最核心、镜13 最亮）实测字幕带只有 25~30，离白字 242 差 212 级 ——
# 判据只要 50。scrim 在这里加不了任何可读性，却会把 x 690~819 那一带**真的画面内容**
# 压暗两成。纯成本，关掉。
#
# 会让它重新开起来的条件只有一个：其余 13 张里有哪一镜 trace/measure 报到
# 字幕带 > 190。真出现了就把这里改回 0.25 左右，**只重跑 c**，a/b 不受影响。
SCRIM_ALPHA = 0.0
SCRIM_X0, SCRIM_SOFT, SCRIM_POW = 690, 340, 1.5

# ================= 全局参数 =================
W, H, FPS = 1080, 1920, 30
PREP = (2160, 3840)         # prep 输出(2x 成片)
UP = (3240, 5760)           # Ken Burns 上采样(3x 成片)
XFADE = 1.2                 # 默认转场；某一镜写 xf= 就覆盖它
FADE_IN, FADE_OUT = 2.0, 4.0
FADE_COLOR = "black"        # 暗调实拍用黑场（前六支纸本用的是白场）

# 镜头暗角。前六支是纸本画面，加了会像被烟熏过；暗调实拍里它是镜头本来就有的东西。
# **改了这里 trace 会自动跟着变** —— 见 _vig_map()。空字符串 = 不加。
VIGNETTE = "vignette=PI/5"

SRC = os.path.join("..", "素材")
# 楷体 simkai.ttf。按常见位置依次找，找不到就用第一个（烧字幕时会报字体缺失）。
FONTS = next((p for p in (os.path.join("..", "fonts"),
                          os.path.join("..", "..", "fonts"),
                          os.path.join("..", "..", "build", "fonts"))
              if os.path.isdir(p)), os.path.join("..", "fonts"))
MUSIC = os.path.join(SRC, "00_music_main.mp3")
MUSIC_GAIN = -10.0

# ---- 时长账 ----
# 全词 103 字，比《再别康桥》(213 字)少一半，所以片长压到 137.6s 而不是 164.8s。
# 这是**故意压的**：mureka 的封顶是 180~245s 之间随机（上一支实测），
# 按最坏的 180s 算，137.6s 的片子还剩 42.4s 切入余地；
# 若按前几支那样排到 165s，最坏情况只剩 15s，怎么挪都有要紧落点撞进谷里。
#
# 42.4s 仍不到技能里 "全曲 >= 片长 x 1.6" 的线(需要 220s)，check 会提醒 ——
# 那是对的，不用去改片长，拿到曲子再看：拿到 220s 以上就没事，
# 拿到 180s 就按 42.4s 的余地跑 pick，比上一支的 15.1s 宽裕得多。
# ---- 实际拿到的曲子 ----
# 提示词里写死了「至少 4 分 30 秒」，拿回来 **193.4s** —— 第三次印证 mureka 的封顶
# 是 180~245s 随机、提示词管不住。好在片长压到 137.6s，余地 55.7s（上一支只有 15.1s）。
#
# maximin 扫完 0~55.7s 的所有切入点，选出 49.5s。九个落点全落在 −13.2 ~ −16.6 的
# 三分贝带里，用到的这一段最深谷 −26.3。
# 量出来的另外两件事（都是这条曲子的运气好）：
#   - 全曲最低 −70.6 出现在 191.1~193.4s，那只是**结尾的自然收尾**，不是中段 breakdown。
#     上一支的候选 A 就是在 121~130s 藏了 1.7s 近乎静音，只能弃用 —— 这条没有
#   - 只有 9.5~9.9s 和 12.1~12.6s 两处 0.5 秒的浅坑（−26），都在前奏里，49.5s 切入全避开
# 成片用到 187.1s，离结尾淡出(191.1s)还差 4s，不会把收尾扫进来。
MUSIC_IN = 49.5
MUSIC_FADE_IN = 0.8

TARGET_I, TARGET_TP = -15.0, -1.5
READ_PER_CHAR, READ_BASE = 0.45, 1.8        # 无诵读时的可读下限

# ---- 这一支的调色是**量出来才改的**，别照抄前几支的"几乎不调" ----
#
# 技能里"一次生成的 AI 图几乎不要调"那条，是从纸本画种（浅底）总结出来的。
# 这一支的生成器交回来的是**技术上欠曝**的片子：两张样图实测
#   平均亮度 15.1 / 18.7，中位数 8 / 7，六到七成面积在 16 以下，
#   而且**全图最亮只有 133** —— 一处白都没有。
# 人脸落在 39~83，手机上开自动亮度基本是一团深灰。
#
# 更糟的是原来那句 `eq=contrast=1.06:saturation=0.92`：实测把平均从 15.1 压到 8.9、
# 中位数直接压成 0。**照搬前几支的调色在这里是帮倒忙**，不是"几乎不调"而是负的。
#
# 现在这一串分两步，顺序不能换：
#   1. colorlevels 把白点从 133 拉到 148 → 255，先让画面用满动态范围（不会削顶）
#   2. gamma 1.25 抬中间调，把脸从 39~83 抬到 89~163
# 实测结果：平均 41.2 / 47.2，中位数 27 / 26，最亮 232 / 237。
# 字幕带从 1~9 抬到约 27 —— 离白字(242) 还差 215 级，判据要 50，绰绰有余。
GRADE = ("colorlevels=rimax=0.58:gimax=0.58:bimax=0.58,"
         "eq=gamma=1.25:contrast=1.02:saturation=0.94")

# ================= 素材与裁切 =================
# 目标 2896x5152（正好 9:16），全部 zoom=1.00 不用裁。
CLIPS = [
    dict(src="img01.png", zoom=1.00, cx=0.50, cy=0.50, tweak=""),   # 长亭暮色·雨初歇
    dict(src="img02.png", zoom=1.00, cx=0.50, cy=0.50, tweak=""),   # 长亭飞檐·檐水
    dict(src="img03.png", zoom=1.00, cx=0.50, cy=0.50, tweak=""),   # 都门帐饮
    dict(src="img04.png", zoom=1.00, cx=0.50, cy=0.50, tweak=""),   # 兰舟催发
    dict(src="img05.png", zoom=1.00, cx=0.50, cy=0.50, tweak=""),   # 执手（全片核心）
    dict(src="img06.png", zoom=1.00, cx=0.50, cy=0.50, tweak=""),   # 凝噎（女主特写）
    dict(src="img07.png", zoom=1.00, cx=0.50, cy=0.50, tweak=""),   # 舟离岸·千里烟波
    dict(src="img08.png", zoom=1.00, cx=0.50, cy=0.50, tweak=""),   # 暮霭·楚天阔
    dict(src="img09.png", zoom=1.00, cx=0.50, cy=0.50, tweak=""),   # 空渡口（下阕起）
    dict(src="img10.png", zoom=1.00, cx=0.50, cy=0.50, tweak=""),   # 冷落清秋节 + 落叶
    dict(src="img11.png", zoom=1.00, cx=0.50, cy=0.50, tweak=""),   # 舟中酒醒
    dict(src="img12.png", zoom=1.00, cx=0.50, cy=0.50, tweak=""),   # 杨柳岸晓风残月
    dict(src="img13.png", zoom=1.00, cx=0.50, cy=0.50, tweak=""),   # 良辰美景虚设（春）
    dict(src="img14.png", zoom=1.00, cx=0.50, cy=0.50, tweak=""),   # 更与何人说（末镜）
    dict(src="img15.png", zoom=1.00, cx=0.50, cy=0.50, tweak=""),   # 诗文页底
]

# ================= 分镜 =================
# 缩放 z 时焦点只能落在 [1/(2z), 1-1/(2z)] 里，想走 d 的行程必须 z >= 1/(1-d)：
#   10%->1.12  20%->1.25  30%->1.43  40%->1.67
# 写了位移不给足缩放 = 原地微缩放，参数表上完全看不出来。check_moves() 会报警。
#
# 结构（一句一镜，十四镜 + 诗文页）：
#   上阕 长亭 -> 帐饮 -> 催发 -> 执手 -> 凝噎 -> 舟行 -> 楚天阔
#   下阕 空渡 -> 清秋 -> 酒醒 -> 残月 -> 良辰虚设 -> 更与何人说
#
# 转场不是常数：
#   **镜 8 -> 镜 9 给 2.2s 长溶解** = 上下阕之间的"翻片"，全片唯一一次段落感；
#   **镜 5 -> 镜 6 给 0.6s 短切**（执手 -> 凝噎）：两个特写之间，一记硬的最贴；
#   **镜 11 -> 镜 12 给 0.8s**（「今宵酒醒何处？」-> 「杨柳岸，晓风残月」）：
#     问和答之间，短一点才像答上了；
#   **镜 14 -> 诗文页 2.5s**，最后一次翻页；其余 1.2s。
SHOTS = [
    # 1  雨后黄昏的长亭外，积水映残霞，柳上一只寒蝉  [标题 + 寒蝉凄切]
    #    前 6.6s 只有标题，所以这一镜比其余长。缓推 + 微下移，走 8%
    #    起幅 z 是 1.14 不是 1.12：z=1.12 时焦点只能落在 [0.446,0.554] 里，
    #    fy=0.44 就已经出界了 —— 慢推镜的起幅 z 越小，能摆的余地越窄
    dict(dur=13.0, z=(1.14, 1.40), f0=(0.50, 0.44), f1=(0.50, 0.52)),
    # 2  长亭飞檐，檐角滴水成线，亭内一副未动的酒具  [对长亭晚｜骤雨初歇]
    #    由檐口下摇到石桌，走 24%（z 最大 1.44 能走 31%）
    dict(dur=9.0, z=(1.44, 1.40), f0=(0.50, 0.36), f1=(0.50, 0.60)),
    # 3  城门外青帷帐下，男女对坐，酒盏未动  [都门帐饮无绪]
    #    **全片第一次露脸**。极缓推，几乎不移，让观众看清人
    dict(dur=8.6, z=(1.14, 1.34), f0=(0.50, 0.50), f1=(0.50, 0.47)),
    # 4  岸边兰舟，船夫解缆回头催，女子立岸回望  [留恋处｜兰舟催发]
    #    全片唯一一次横移，跟着舟走 26%（左->右）
    dict(dur=8.8, z=(1.44, 1.40), f0=(0.37, 0.50), f1=(0.63, 0.50)),
    # 5  特写：两只手相握，焦外是两张脸  [执手相看泪眼]
    #    全片情绪核心。极缓推到手，走 6%
    dict(dur=9.5, z=(1.16, 1.46), f0=(0.50, 0.52), f1=(0.50, 0.46), xf=0.6),
    # 6  女子面部特写，泪光，唇启无声；男子侧脸在焦外  [竟无语凝噎]
    #    几乎不动（走 3%）。这一句写的就是"说不出来"，镜头也该停住。
    #    trace 的落幅平坦度会偏高，那是对的，不用去修
    dict(dur=8.5, z=(1.22, 1.30), f0=(0.50, 0.50), f1=(0.50, 0.53)),
    # 7  舟离岸，江面烟波，舟在画面下方渐小  [念去去｜千里烟波]
    #    缓拉 + 上移，走 22%
    dict(dur=8.8, z=(1.42, 1.30), f0=(0.50, 0.62), f1=(0.50, 0.40)),
    # 8  大远景：暮霭沉沉，天低江阔，一点孤帆  [暮霭沉沉楚天阔]
    #    全片幅度最大的一次拉开(1.58 -> 1.04)，收上阕
    dict(dur=11.0, z=(1.58, 1.04), f0=(0.50, 0.54), f1=(0.50, 0.50), xf=2.2),
    # 9  空了的渡口，两只酒盏，一只倒着；女子独立暮色里  [多情自古伤离别]
    #    缓推，走 7%
    dict(dur=9.8, z=(1.14, 1.42), f0=(0.50, 0.47), f1=(0.50, 0.54)),
    # 10 秋风萧瑟，黄叶满阶，女子独立庭中  [更那堪｜冷落清秋节] + 落叶层
    #    下摇到落叶堆，走 25%
    dict(dur=9.6, z=(1.46, 1.42), f0=(0.50, 0.37), f1=(0.50, 0.62)),
    # 11 舟舱中夜里酒醒，一盏残灯，酒壶倾倒，舱窗外是黑水  [今宵酒醒何处？]
    #    极缓推向灯，走 5%
    dict(dur=8.6, z=(1.18, 1.44), f0=(0.50, 0.51), f1=(0.50, 0.46), xf=0.8),
    # 12 拂晓，杨柳岸，一弯残月低悬，舟系柳下，男子立船头  [杨柳岸｜晓风残月]
    #    全词名句，给最长的停留。由柳梢上摇到残月，走 23%
    dict(dur=10.5, z=(1.44, 1.38), f0=(0.50, 0.60), f1=(0.50, 0.37)),
    # 13 春日繁花楼台，女子独立花下，满目春色而人独  [此去经年｜应是良辰美景虚设]
    #    全片最亮的一张，也是"帅哥美女 + 漂亮背景"最能发挥的一镜。
    #    用美景反衬"虚设"。缓推 + 微右移，走 9%
    dict(dur=11.0, z=(1.16, 1.44), f0=(0.48, 0.50), f1=(0.53, 0.46)),
    # 14 男子在千里外的江楼上凭栏，秋江空阔，无人  [便纵有千种风情｜更与何人说？]
    #    末镜长留：字幕出完之后还有 2.9s 的空画面。缓拉，走 6%
    dict(dur=14.0, z=(1.50, 1.10), f0=(0.50, 0.52), f1=(0.50, 0.48), xf=2.5),
    # 15 诗文页底：秋江晓雾，一带柳影，大片空
    dict(dur=15.0, z=(1.06, 1.03), f0=(0.50, 0.492), f1=(0.50, 0.508)),
]

# ================= 字幕 =================
# (起, 止, 文本, 样式)  T=标题 TS=作者 M=正文
#
# 正文用 `|` 分成两列（**右列在前，自右向左读**），分隔符本身不上屏。
# 不拿逗号当分隔符：这一首句内有该上屏的标点（「冷落清秋节！」的叹号、
# 「今宵酒醒何处？」「更与何人说？」的问号），逗号法会把它们吃掉。
#
# 左列延后 SUB_COL_DELAY 出现，两列一起留到句末。长短句本来就有停顿，
# 「留恋处」之后才「兰舟催发」，一列一列落下来比整块蹦出来贴得多。
SUB_SEP = "|"
SUB_COL_DELAY = 0.28

LINES = [
    (1.4,   5.6,  TITLE,  "T"),
    (2.8,   5.6,  AUTHOR, "TS"),
    (6.6,  11.0,  "寒蝉凄切",                 "M"),
    (13.3, 19.6,  "对长亭晚|骤雨初歇",         "M"),
    (21.0, 26.9,  "都门帐饮无绪",             "M"),
    (28.4, 34.5,  "留恋处|兰舟催发",           "M"),
    (36.0, 43.1,  "执手相看泪眼",             "M"),
    (44.6, 50.7,  "竟无语凝噎",               "M"),
    (52.2, 58.3,  "念去去|千里烟波",           "M"),
    (59.8, 66.6,  "暮霭沉沉楚天阔",           "M"),
    (69.4, 75.8,  "多情自古伤离别",           "M"),
    (77.2, 84.2,  "更那堪|冷落清秋节！",       "M"),
    (85.6, 91.6,  "今宵酒醒何处？",           "M"),
    (93.4, 100.4, "杨柳岸|晓风残月",           "M"),
    (102.7, 110.9, "此去经年|应是良辰美景虚设", "M"),
    (112.6, 121.0, "便纵有千种风情|更与何人说？", "M"),
]

# ================= 片尾诗文页 =================
# 这一支回到**竖排**（上一支《再别康桥》是横排）。理由很实在：现代诗有跨行，
# 竖排读起来别扭；词有明确的句读，八句排成八列自右向左，就是它本来的样子。
#
# 八列 x 最长 18 字（含标点，竖排里标点各占一格）。
# 列距 112、字号 46：右起第一列列心 x=892、右缘 915，**离操作栏(x>=929) 还差 14px** ——
# 所以整块的列心 POEM_CX 定在 500 而不是画心 540。这不是随手挪的，是算出来的。
POEM_CX, POEM_GAP, POEM_FS = 500, 112, 46
POEM_TOP = 600                           # 各列**顶端对齐**（列长不齐，居中会两头飘）
POEM_HEAD_FS, POEM_HEAD_Y = 72, 420      # 页首标题（横排，居中）
POEM_SIG_FS, POEM_SIG_X, POEM_SIG_Y = 34, 108, 1500   # 左下落款（竖排）
POEM_COL_STEP = 0.5                      # 逐列显：自右向左每列隔 0.5s

# 逐列显是技能里"还没做过"的那五件里的第 5 件。做在诗文页而不是正文上：
# 正文逐字显会牺牲可读性，诗文页本来就是给人从右往左读的，顺序一致反而更好读。
POEMS = [
    dict(t0=125.6, t1=134.6, head=TITLE,
         cols=["寒蝉凄切，对长亭晚，骤雨初歇。",
               "都门帐饮无绪，留恋处，兰舟催发。",
               "执手相看泪眼，竟无语凝噎。",
               "念去去，千里烟波，暮霭沉沉楚天阔。",
               "多情自古伤离别，更那堪，冷落清秋节！",
               "今宵酒醒何处？杨柳岸，晓风残月。",
               "此去经年，应是良辰美景虚设。",
               "便纵有千种风情，更与何人说？"],
         sig="柳永"),
]

# 正文：一列时列心 x；两列时右列心/左列心。字号 62。
SUB_X = 952
SUB_X_R, SUB_X_L = 970, 856
SUB_FS = 62

# ---- SUB_TOP ----
# 真机验过的结论：抖音/小红书右侧的头像/赞/评论/分享压在 x 0.86~1.00、y 0.45~0.85，
# 而字幕在 x 0.758~0.932 这同一条竖带上，所以**列底是硬约束**，
# 要往上移、不要往左移（往左移会挡住人脸，这一支尤其不能）。
#
# 这一支最长一列 **8 字**（「应是良辰美景虚设」）。290 + 8*62 = 786，
# 离操作栏上沿(864)还剩 78px；顶端 290 离顶部导航下沿(173)剩 117px。上下都够。
SUB_TOP = 290

# ================= 平台安全区（竖版）=================
# 2026-08-13 用《声声慢》在真机上比过的坐标。
SAFE_RAIL = (929, 864, 1080, 1632)       # 右侧操作栏 x0,y0,x1,y1
SAFE_TOP = 173                           # 顶部导航下沿

# ================= 粒子层 =================
# 技能里"画面里加一处真运动"那条，这一支做两处，都是纯 ffmpeg 合成、不用素材。
#
# 一、残雨（镜 1 ~ 镜 2）。「骤雨初歇」是**刚停**，不是没下过 ——
#    开场留最后几丝斜雨，随着「骤雨初歇」四个字落下来正好收干净，
#    是全片唯一一次让画面替字幕做了一件事。
#    雨是**淡色**的，只有在暗底上才立得住 —— 这一支全片暗调，正合适
#    （上一支在浅纸上试过，几乎看不见）。
RAIN_T0, RAIN_DUR = 1.2, 17.0       # 1.2 -> 18.2s，落在「骤雨初歇」(到 19.6)之前收干净
RAIN_OUT = 9.0                      # 局部 9.0s 起淡出，8s 淡完
RAIN_COLOR, RAIN_ALPHA = "0xDCE6EE", 0.42   # 极淡的青白，不是纯白；密度也压得很低

# 二、落叶（镜 10）。落在「更那堪，冷落清秋节」上 —— 全词最冷的一句。
#    叶色是**比底亮**的暖赭（上一支在浅纸上必须用比纸暗的赭石，这里反过来）。
LEAF_T0, LEAF_DUR = 76.4, 8.8       # 镜 10 (75.8~85.4) 内
LEAF_COLOR, LEAF_ALPHA = "0xC8A26A", 0.85
# 每片叶: (入画时刻, 那一刻的 x, 那一刻的 y, vx, vy, 摆幅, 摆频, 转速, 尺寸)
# **按入画时刻错开是必须的**：位置写死会让所有叶子同时飞出画外，一镜十秒里六秒是空的。
# 入画时刻为负 = 这一镜开始时它已经在画里了。
# vx 一律压在 45 以内：叶子飘到画右会横穿字幕带(x>=819)，这一支是白字，不能再添乱。
LEAVES = [
    (-1.5, 120,  200, 35, 210, 44, 0.50,  0.28, 66),
    (-0.4, 380,  -60, 45, 185, 36, 0.62, -0.24, 52),
    (0.9,  180, -120, 30, 235, 54, 0.44,  0.36, 72),
    (2.0,  520, -100, 40, 170, 30, 0.70, -0.30, 46),
    (3.2,  260, -140, 38, 200, 48, 0.52,  0.32, 58),
    (4.4,  600, -110, 28, 225, 40, 0.58, -0.26, 50),
    (5.6,  340, -130, 44, 190, 34, 0.66,  0.30, 62),
]

# ================= 音效 =================
# (文件, 片上起点, **目标响度LUFS**, 淡入, 淡出, **播放多长**)
#
# ---- 为什么第三列是目标响度而不是增益 dB ----
# 第一版写的是固定增益(−18 ~ −22 dB)，那是"素材大致归一"的假设。
# 实际生成回来的五条实测响度是：
#     寒蝉 −8.3   檐滴 −30.6   解缆 −14.8   江风 −53.5   晓风 −18.6
# **跨度 45 dB。** 同一个 −21 dB 加在寒蝉上是刺耳，加在江风上是 −74 LUFS、等于没有。
# 写死增益在这种素材上不可能对，而且错了在参数表上完全看不出来 ——
# 混音会"成功"，只是有的音效听不见、有的盖过音乐。
#
# 所以改成声明**目标**，增益由 build_audio() 按实测反算：gain = 目标 − 实测。
# 换一条音效、重生成一条，都不用再手算。
#
# 目标怎么定：音乐实测 −14.9，MUSIC_GAIN −10，所以音乐在混音里约 −24.9。
# 音效一律排在它下面 1~9 dB：动作声(解缆)最近，环境底(寒蝉/江风)最远。
#
# **每一条都必须写死播放长度**：让音效"放到自然结束"会互相盖掉。
# 一律 -stream_loop -1 进来再按长度裁 —— 不过这五条生成时就要得比播放长度长，
# 所以实际不会循环，也就没有接缝。
# 缺文件会跳过并提示，不会让 pass_c 挂掉 —— 音效是加分项，不是必需品。
SFX = [
    ("01_寒蝉.mp3",   2.5, -34.0, 2.5, 3.0,  9.5),   # 镜1 秋蝉，极轻的一层背景
    ("02_檐滴.mp3",  13.0, -28.0, 1.5, 2.5,  6.5),   # 镜2 雨后檐水，清晰的前景细节
    ("03_解缆.mp3",  28.5, -26.0, 0.3, 2.0,  5.5),   # 镜4 缆绳与桨，全片最靠前的一条
    ("04_江风.mp3",  59.5, -34.0, 3.0, 5.0,  9.0),   # 镜8 楚天阔，一层空阔的底
    ("05_晓风.mp3",  92.8, -32.0, 3.0, 4.5,  9.0),   # 镜12 晓风残月
]
SFX_GAIN_WARN = 12.0        # 需要提这么多 dB 以上，说明素材本身太轻，底噪会一起上来


# ================= 素材的原生尺寸 =================
# **文件尺寸会骗人。** 放大一下 941x1672 就变成 2896x5152，尺寸检查从此必然通过，
# 而细节还是 941 那么多 —— 有效分辨率只有下限的 0.65 倍，成片会软。
#
# 试过从像素上**自动**判"是不是放大的"，判不出来：把图降到恰好原生尺寸再放大回来，
# 残差 0.23~0.57 灰阶，而原生 4K 是 0.53~0.83 —— 一个量级，分不开
# （放大器不是简单重采样时尤其如此）。1:1 目视也不可靠：两张图的"软"可能只是画风。
# 唯一站得住的证据是**生成器吐出来的原始文件**。
#
# 所以这一条**只能靠记录，不能靠检测**：把生成器实际出的尺寸写在这里。
#   None       = 文件尺寸就是生成器出的尺寸
#   (941,1672) = 生成器只出到 941x1672，项目里的大图是放大上去的
SRC_NATIVE = None

# 运镜实测下限：渲出来的首尾帧平均绝对差。亮度可觉察差约 2~3 级，取 4。
MOTION_MIN = 4.0


# ================= 诵读（可选）=================
# **和讲述模式正好相反。** 讲述片的旁白是连着说的，时间轴由语音落点推出来；
# 词是一句一镜、句间大段的静，那个「密→疏」的结构本身就是内容 ——
# 让诵读去驱动它，结构就散了。所以这里是：**时间轴不动，语音放进去**。
#
# 落点也不用手写：每条诵读挂在它那句字幕上，字幕先出、语音后跟 VO_LEAD 秒。
# 手工在十几个偏移量上凑，一定会漏一两处，而漏掉的那处要到成片才听得出来。
#
# VO 留空 = 无诵读，整条链路自动跳过（前几支都是这么跑的）。
VO_DIR = "vo"
VO = [
    # ("东风夜放花千树", "VO_01.mp3"),
]
VO_LEAD = 0.5               # 字幕先出多久，语音才进来
VO_TAIL_MIN = 0.3           # 语音读完之后，字幕至少还要留这么久
VO_TARGET = -18.0           # 诵读比讲述旁白轻：它是画面的一部分，不是信息载体
VO_FADE = 0.06              # 极短淡入淡出，只为掐掉 TTS 的头尾爆音
# 音乐侧链躲闪。诵读稀疏，所以压得比讲述片浅、放得比讲述片慢。
VO_DUCK = dict(threshold=0.08, ratio=4, attack=40, release=600)
VO_CACHE = "vo_times.json"
_VO_CACHE = {}


# ================= 以下一般不用改 =================
def run(args, desc):
    print("\n>>> " + desc)
    if subprocess.run(args).returncode != 0:
        sys.exit("!!! 失败: " + desc)


def xf(i):
    """镜 i(0 起) 转到下一镜的溶解时长。写了 xf= 就覆盖全局 XFADE。"""
    return SHOTS[i].get("xf", XFADE)


def total_len():
    return sum(s["dur"] for s in SHOTS) - sum(xf(i) for i in range(len(SHOTS) - 1))


def shot_starts():
    t, out = 0.0, []
    for i, s in enumerate(SHOTS):
        out.append(t); t += s["dur"] - xf(i)
    return out


def cut_points():
    st = shot_starts()
    return [st[i] + SHOTS[i]["dur"] - xf(i) / 2 for i in range(len(SHOTS) - 1)]


def shot_of(t):
    n = 1
    for i, s in enumerate(shot_starts(), 1):
        if t >= s - 1e-6:
            n = i
    return n


def pol_of(n):
    """镜 n(1 起) 的字幕极性。FLIP_SHOTS 里的镜取全局的**反面**。

    上一支这个开关叫 NIGHT_SHOTS，只能从"浅底墨字"翻到"暗底白字"一个方向。
    这一支全局是暗底白字，风险镜(春日繁花)要翻的是另一个方向，
    所以写成对称的：翻的是极性本身，不是某一种画面。"""
    other = "dark_on_light" if POLARITY == "light_on_dark" else "light_on_dark"
    return other if n in FLIP_SHOTS else POLARITY


def ink_of(n):
    return 40 if pol_of(n) == "dark_on_light" else 242


def prep():
    for i, c in enumerate(CLIPS, 1):
        src = os.path.join(SRC, c["src"])
        if not os.path.exists(src):
            print("   跳过(缺素材): " + c["src"]); continue
        z, cx, cy = c["zoom"], c["cx"], c["cy"]
        crop = ("crop=w='min(iw,ih/%.6f*9/16)':h='min(ih/%.6f,iw*16/9)':"
                "x='clip(%.6f*iw-out_w/2,0,iw-out_w)':"
                "y='clip(%.6f*ih-out_h/2,0,ih-out_h)'" % (z, z, cx, cy))
        vf = crop + "," + GRADE + ("," + c["tweak"] if c["tweak"] else "")
        vf += ",scale=%d:%d:flags=lanczos,setsar=1" % PREP
        run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", vf,
             "-frames:v", "1", "img%02d.png" % i],
            "prep %d/%d  %s" % (i, len(CLIPS), c["src"]))
    probe()


def probe():
    """9x16 亮度网格 + 右侧字幕带。
    注意：它量的是**整张图**，而镜头只经过其中一段，所以报警经常是误报。
    以 trace 为准 —— 前几支里有两次只信 probe 就会换掉本来没问题的图。"""
    print("\n=== 亮度网格 (0-255, 9 列 x 16 行) 与字幕带 ===")
    for i in range(1, len(CLIPS) + 1):
        f = "img%02d.png" % i
        if not os.path.exists(f):
            print("%s  (未生成)" % f); continue
        p = subprocess.run(["ffmpeg", "-v", "error", "-i", f, "-vf",
                            "scale=9:16:flags=area,format=gray", "-f", "rawvideo", "-"],
                           capture_output=True)
        g = p.stdout[:144]
        if len(g) < 144:
            print("%s  (读取失败)" % f); continue
        print("\n%s  (%s)" % (f, CLIPS[i - 1]["src"]))
        for r in range(16):
            print("   " + " ".join("%3d" % v for v in g[r * 9:(r + 1) * 9]))
        col = [g[r * 9 + c] for r in range(16) for c in (6, 7, 8)]
        avg, lo, hi = sum(col) / len(col), min(col), max(col)
        pol = pol_of(i)
        note = ""
        if pol == "dark_on_light" and lo < 120:
            note = "  << 偏暗(可能误报，看 trace)"
        if pol == "light_on_dark" and hi > 190:
            note = "  << 偏亮，白字会糊(可能误报，看 trace)"
        print("   字幕带 YAVG=%.0f  最暗=%d  最亮=%d  (极性 %s)%s" % (avg, lo, hi, pol, note))
        flat = [r for r in range(16)
                if max(g[r * 9:(r + 1) * 9]) - min(g[r * 9:(r + 1) * 9]) < 12]
        if len(flat) >= 5:
            print("   注意：第 %s 行几乎无明暗变化，落幅别停在这里（同样可能误报）"
                  % ",".join(str(r) for r in flat))


_VIG_CACHE = {}


def vig_factor(x0, x1, y0, y1):
    """pass_a 里的 vignette 对**画面上**某个矩形的平均衰减系数（1.0 = 不衰减）。

    ---- 为什么必须有这个 ----
    trace 和 measure 这一支系统性对不上：measure 一律比 trace 低 5~31 级，
    而且越亮差得越多（比值稳定在 0.64~0.81）。
    验证方法是把 pass_a 的 vignette 关掉重渲镜 14 的落幅那一帧 ——
    同一个字幕框量到 **119**，而 trace 报 **118**，差 1 级。
    结论：**运镜完全正确，是 trace 少建模了暗角**，而字幕带正好在右上角、
    落在暗角最深的地方之一。

    技能里"trace 和 measure 对不上 = 运镜没走在你以为的位置上"那条判据，
    前提是两者建模同一条流水线。pass_a 多了一道 vignette，就得补进来 ——
    否则这个系统性偏差会一直挂在那儿，而那是全流水线**唯一**一处能自检运镜的地方，
    一个长期报假警的检查等于没有检查。

    做法：拿一张纯灰跑一遍 VIGNETTE，用**画心的值**归一（画心系数恒为 1），
    不依赖任何色彩范围换算的常数。改 VIGNETTE 或关掉它都会自动跟着变。
    """
    if not VIGNETTE:
        return 1.0
    if "map" not in _VIG_CACHE:
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi",
             "-i", "color=c=0xC8C8C8:s=%dx%d" % (W, H),
             "-vf", VIGNETTE + ",format=gray", "-frames:v", "1",
             "-f", "rawvideo", "-"], capture_output=True).stdout
        _VIG_CACHE["map"] = raw if len(raw) == W * H else None
    raw = _VIG_CACHE["map"]
    if not raw:
        return 1.0
    ctr = raw[(H // 2) * W + W // 2]
    if not ctr:
        return 1.0
    step = 8                        # 暗角变化极慢，每 8px 取一点足够
    v = [raw[y * W + x] for y in range(y0, y1, step) for x in range(x0, x1, step)]
    return (sum(v) / len(v)) / ctr


def trace():
    """量镜头**真正经过的区域**：字幕实走轨迹 + 每镜落幅那一帧的平坦度。
    出图阶段就能判一张图能不能用，比渲完再发现便宜得多。缺图会跳过。

    zoompan 的取景窗宽高各为 1/z、窗心在 (fx,fy) 且被 clip 在图内，于是
        src = (f - 1/(2z)) + (out/边长) * (1/z)
    """
    starts = shot_starts()
    GW, GH = 724, 1288
    cache = {}

    def gray(i):
        if i in cache:
            return cache[i]
        f = "img%02d.png" % i
        if not os.path.exists(f):
            f = os.path.join(SRC, CLIPS[i - 1]["src"])
            if not os.path.exists(f):
                cache[i] = None; return None
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", f, "-vf",
                              "scale=%d:%d:flags=area,format=gray" % (GW, GH),
                              "-f", "rawvideo", "-"], capture_output=True).stdout
        cache[i] = raw if len(raw) == GW * GH else None
        return cache[i]

    def box(n, tl, x0o, x1o, y0o, y1o):
        s = SHOTS[n - 1]
        p = min(1.0, max(0.0, tl / s["dur"]))
        z = s["z"][0] + (s["z"][1] - s["z"][0]) * p
        half = 1 / (2 * z)
        fx = min(max(s["f0"][0] + (s["f1"][0] - s["f0"][0]) * p, half), 1 - half)
        fy = min(max(s["f0"][1] + (s["f1"][1] - s["f0"][1]) * p, half), 1 - half)
        span = 1.0 / z
        return (fx - half + x0o / W * span, fx - half + x1o / W * span,
                fy - half + y0o / H * span, fy - half + y1o / H * span)

    def stat(raw, b, dark):
        x0, x1 = int(b[0] * GW), max(int(b[0] * GW) + 1, int(b[1] * GW))
        y0, y1 = int(b[2] * GH), max(int(b[2] * GH) + 1, int(b[3] * GH))
        x0, x1, y0, y1 = max(0, x0), min(GW, x1), max(0, y0), min(GH, y1)
        v = sorted(raw[y * GW + x] for y in range(y0, y1) for x in range(x0, x1))
        return sum(v) / len(v), v[int(len(v) * 0.01)] if dark else v[int(len(v) * 0.99)]

    print("\n=== 字幕实走轨迹（起/中/止，均值/分位；判据：离字色至少 50 级）===")
    worst = []
    for st, en, txt, sty in LINES:
        if sty != "M":
            continue
        n = shot_of((st + en) / 2)
        dark = pol_of(n) == "dark_on_light"
        ink = ink_of(n)
        raw = gray(n)
        if raw is None:
            print("  %-13s 镜%-3d (缺图)" % (txt, n)); continue
        x0, x1, y0, y1 = sub_box(txt)
        vig = vig_factor(x0, x1, y0, y1)        # 补上 pass_a 的暗角，否则和 measure 对不上
        out, ys = [], []
        for t in (st + 0.2, (st + en) / 2, en - 0.2):
            b = box(n, t - starts[n - 1], x0, x1, y0, y1)
            a_, q_ = stat(raw, b, dark)
            out.append((a_ * vig, q_ * vig)); ys.append((b[2], b[3]))
        w = min(o[1] for o in out) if dark else max(o[1] for o in out)
        worst.append((abs(w - ink), w, txt, n))
        flag = "" if abs(w - ink) >= 50 else "   << 不够，考虑加进 FLIP_SHOTS 或换图"
        # 打**扫过的并集**：上摇时落幅的框底在起幅框底之上，
        # 按"起帧框顶->止帧框底"打会把行程严重低估
        print("  %-13s 镜%-3d 扫过 y %.3f~%.3f  " % (txt, n, min(a for a, _ in ys),
                                                     max(b for _, b in ys))
              + "  ".join("%3.0f/%3.0f" % o for o in out) + flag)
    if worst:
        gap, m, who, n = min(worst)
        print("\n  最差处的底 %d，出现在『%s』(镜 %d)，离字色差 %d 级 —— %s"
              % (m, who, n, gap, "够用" if gap >= 50 else "不够"))

    print("\n=== 落幅平坦度（只量镜头真正停住的那一帧，9x16 网格）===")
    for n in range(1, len(SHOTS) + 1):
        raw = gray(n)
        if raw is None:
            print("  镜%-3d (缺图)" % n); continue
        b = box(n, SHOTS[n - 1]["dur"], 0, W, 0, H)
        gx0, gx1 = int(b[0] * GW), int(b[1] * GW)
        gy0, gy1 = int(b[2] * GH), int(b[3] * GH)
        cells, flat = [], 0
        for r in range(16):
            row = []
            for c in range(9):
                sx0 = gx0 + (gx1 - gx0) * c // 9
                sx1 = max(sx0 + 1, gx0 + (gx1 - gx0) * (c + 1) // 9)
                sy0 = gy0 + (gy1 - gy0) * r // 16
                sy1 = max(sy0 + 1, gy0 + (gy1 - gy0) * (r + 1) // 16)
                v = [raw[y * GW + x] for y in range(sy0, min(GH, sy1))
                     for x in range(sx0, min(GW, sx1))]
                row.append(sum(v) / len(v))
            cells.append(row)
            if max(row) - min(row) < 12:
                flat += 1
        allv = [v for row in cells for v in row]
        rng = max(allv) - min(allv)
        note = ""
        if n > len(SHOTS) - len(POEMS):
            note = "  (诗文页，本来就该空且几乎静止 —— 不适用)"
        elif n == 6:
            note = "  (镜6「竟无语凝噎」有意几乎不动，偏高是对的)"
        elif flat >= 5:
            note = "  << %d 行几乎无明暗变化，这一镜会像静止" % flat
        elif rng < 25:
            note = "  << 整帧极差只有 %.0f，运镜会看不出来" % rng
        print("  镜%-3d %-12s 整帧极差 %3.0f  平坦行 %2d/16%s"
              % (n, CLIPS[n - 1]["src"].replace(".png", ""), rng, flat, note))


def check_xfades():
    bad = []
    for i in range(len(SHOTS) - 1):
        x = xf(i)
        if x <= 0:
            bad.append("镜 %d 的转场 %.2fs 必须大于 0" % (i + 1, x))
        elif x > min(SHOTS[i]["dur"], SHOTS[i + 1]["dur"]) - 1e-6:
            bad.append("镜 %d 的转场 %.2fs 不短于相邻镜头(%.1fs/%.1fs)"
                       % (i + 1, x, SHOTS[i]["dur"], SHOTS[i + 1]["dur"]))
    return bad


def check_safe():
    """屏上文字有没有撞进平台的操作栏 / 顶部导航。

    这条是 2026-08-13 真机比过之后加的：在那之前字幕最长一列落到画高 59.1%，
    正好压在抖音右侧的赞和评论上。这类问题在成片文件里完全看不出来 ——
    只有把片子放进 App 才会发现，而那时十六张图早就出完了。所以拿来当自检。
    """
    rx0, ry0, rx1, ry1 = SAFE_RAIL
    bad = []

    # 参数顺序跟 sub_box 一致：**(x0, x1, y0, y1)**，不是 (x0, y0, x1, y1)。
    # 上一支第一版按后者解包，于是检查在旧的、确实撞了的位置上一声不吭。
    # **一个永远不报警的检查比没有检查更糟**，所以下面有回归自测。
    def hit(name, x0, x1, y0, y1):
        if y0 < SAFE_TOP:
            bad.append("%s 顶端 %d 进了顶部导航区(<%d)" % (name, y0, SAFE_TOP))
        if x1 > rx0 and x0 < rx1 and y1 > ry0 and y0 < ry1:
            bad.append("%s 的框 x %d~%d / y %d~%d 压进右侧操作栏(x>=%d, y %d~%d)，"
                       "**往上移**不要往左移" % (name, x0, x1, y0, y1, rx0, ry0, ry1))

    for st, en, txt, sty in LINES:
        if sty != "M":
            continue
        hit("字幕『%s』" % txt, *sub_box(txt))
    # 诗文页是**竖排**的，右起第一列离操作栏最近 —— 这才是要量的那一列。
    for p in POEMS:
        for k, col in enumerate(p["cols"]):
            x = poem_col_x(k, len(p["cols"]))
            hit("诗文页第%d列" % (k + 1), x - POEM_FS // 2, x + POEM_FS // 2,
                POEM_TOP, POEM_TOP + len(col) * POEM_FS)
        hw = len(p["head"]) * POEM_HEAD_FS
        hit("诗文页标题", POEM_CX - hw // 2, POEM_CX + hw // 2,
            POEM_HEAD_Y - POEM_HEAD_FS // 2, POEM_HEAD_Y + POEM_HEAD_FS // 2)
        hit("诗文页落款", POEM_SIG_X - POEM_SIG_FS // 2, POEM_SIG_X + POEM_SIG_FS // 2,
            POEM_SIG_Y, POEM_SIG_Y + len(p["sig"]) * POEM_SIG_FS)
    return bad


def selftest_safe():
    """回归：把字幕放回 2026-08-13 之前那个真机上撞了的位置，检查必须报警。"""
    global SUB_TOP
    keep, SUB_TOP = SUB_TOP, 700
    n = len(check_safe())
    SUB_TOP = keep
    ok_now = len(check_safe()) == 0
    print("回归自测: 旧位置(SUB_TOP=700) 报警 %d 条 —— %s" % (n, "对" if n else "**检查失效了**"))
    print("          当前位置(SUB_TOP=%d) 报警 %d 条 —— %s"
          % (SUB_TOP, 0 if ok_now else len(check_safe()), "对" if ok_now else "还在撞"))
    return n > 0 and ok_now


def check_moves():
    bad = []
    for i, s in enumerate(SHOTS, 1):
        z0, z1 = s["z"]
        for (fx_, fy_), z, w in ((s["f0"], z0, "起"), (s["f1"], z1, "止")):
            lo, hi = 1 / (2 * z), 1 - 1 / (2 * z)
            for v, ax in ((fx_, "x"), (fy_, "y")):
                if not (lo - 1e-6 <= v <= hi + 1e-6):
                    bad.append("镜 %d %s幅 f%s=%.3f 超出 z=%.2f 的可达范围 [%.3f,%.3f]"
                               % (i, w, ax, v, z, lo, hi))
        want = abs(s["f1"][1] - s["f0"][1]) + abs(s["f1"][0] - s["f0"][0])
        zmax = max(z0, z1); can = max(0.0, 1 - 1 / zmax)
        if want > can + 1e-6:
            bad.append("镜 %d 想走 %.0f%% 行程，但 z 最大只到 %.2f，实际只能走 %.0f%% "
                       "(需要 z>=%.2f)" % (i, want * 100, zmax, can * 100,
                                           1 / max(1e-6, 1 - want)))
    return bad


def check_fx():
    """粒子层的窗口不能跑到片长外，也不该压到不相干的镜头上。

    **叠加层"盖住了该盖的那一句"必须显式验。** 上一支踩过一次：
    星辉层的起点定得早了一点点，星星浮在大白天的河面上 ——
    参数上完全看不出来，只有抽静帧才发现。这里至少把窗口关系拦住。
    """
    bad, total = [], total_len()
    for name, t0, dur in (("残雨", RAIN_T0, RAIN_DUR), ("落叶", LEAF_T0, LEAF_DUR)):
        if t0 < 0 or t0 + dur > total + 1e-6:
            bad.append("%s层 %.1f~%.1fs 超出片长 %.1fs" % (name, t0, t0 + dur, total))
        print("   %s层 %.1f~%.1fs = 镜 %d 起，到镜 %d 收"
              % (name, t0, t0 + dur, shot_of(t0 + 0.05), shot_of(t0 + dur - 0.05)))
    if RAIN_OUT >= RAIN_DUR:
        bad.append("残雨淡出起点 %.1f 超过了它自己的长度 %.1f" % (RAIN_OUT, RAIN_DUR))
    # 残雨必须在「骤雨初歇」四个字落下来之前就已经在淡出，也必须在那一句结束前收干净 ——
    # 雨还在下着而字说"初歇"，是这一支唯一一处画面能替字幕做事的地方，做反了就白做
    xie = [(s, e) for s, e, t, y in LINES if y == "M" and "骤雨初歇" in t]
    for s, e in xie:
        if RAIN_T0 + RAIN_OUT > s:
            bad.append("残雨到 %.1fs 才开始淡出，晚于『骤雨初歇』出字(%.1fs)"
                       % (RAIN_T0 + RAIN_OUT, s))
        if RAIN_T0 + RAIN_DUR > e:
            bad.append("残雨到 %.1fs 才收干净，晚于『骤雨初歇』收字(%.1fs)"
                       % (RAIN_T0 + RAIN_DUR, e))
    # 落叶必须真的盖住「更那堪，冷落清秋节」那一句
    qiu = [(s, e) for s, e, t, y in LINES if y == "M" and "冷落清秋节" in t]
    for s, e in qiu:
        if LEAF_T0 > s or LEAF_T0 + LEAF_DUR < e:
            bad.append("落叶层 %.1f~%.1fs 没盖住『冷落清秋节』那一句(%.1f~%.1fs)"
                       % (LEAF_T0, LEAF_T0 + LEAF_DUR, s, e))
    # 音效互相盖：上一支的 18 秒秋风把后面的雁鸣整个埋掉，而混音本身是"成功"的
    ev = sorted((t, t + dur, f, tgt) for f, t, tgt, fi, fo, dur in SFX)
    for a, b in zip(ev, ev[1:]):
        if b[0] < a[1] - 1e-6 and min(a[3], b[3]) > -36:
            bad.append("音效重叠: %s(%.1f~%.1fs) 还没收，%s(%.1fs) 就进来了"
                       % (a[2], a[0], a[1], b[2], b[0]))
    for f, t, tgt, fi, fo, dur in SFX:
        if t + dur > total + 1e-6:
            bad.append("音效 %s 到 %.1fs，超出片长 %.1fs" % (f, t + dur, total))
        if fi + fo > dur + 1e-6:
            bad.append("音效 %s 的淡入%.1f+淡出%.1f 超过了它的播放长度 %.1f"
                       % (f, fi, fo, dur))
    print("   音效(目标响度): "
          + "  ".join("%s@%.1f~%.1f(%.0f LUFS)"
                      % (f.split("_")[-1].replace(".mp3", ""), t, t + dur, tgt)
                      for f, t, tgt, fi, fo, dur in SFX))
    return bad


def check_timeline():
    total, cuts, starts = total_len(), cut_points(), shot_starts()
    bad, warn = [], []
    for st, en, txt, sty in LINES:
        if sty == "M":
            # 分隔符不上屏，也就不用读 —— 不剔掉的话每句白得 0.45s 的虚假余量
            need = len(txt.replace(SUB_SEP, "")) * READ_PER_CHAR + READ_BASE
            if en - st < need - 1e-6:
                bad.append("字幕『%s』只有 %.1fs，不足可读下限 %.1fs" % (txt, en - st, need))
        for c in cuts:
            if st - 0.3 < c < en + 0.3:
                bad.append("转场 %.1fs 压到了字幕『%s』" % (c, txt))
        if en > total:
            bad.append("字幕『%s』结束于 %.1fs，超出片长 %.1fs" % (txt, en, total))
    first_poem_shot = len(SHOTS) - len(POEMS)
    for k, p in enumerate(POEMS):
        s0 = starts[first_poem_shot + k]
        if p["t0"] < s0:
            bad.append("诗文页(%.1fs) 早于它那一镜的起点 %.1fs" % (p["t0"], s0))
        if p["t1"] > total:
            bad.append("诗文页结束于 %.1fs，超出片长 %.1fs" % (p["t1"], total))
        for c in cuts:
            if p["t0"] - 0.3 < c < p["t1"] + 0.3:
                bad.append("转场 %.1fs 压到了诗文页" % c)
        # 竖排：宽是"列数 x 列距"，高是"最长一列的字数 x 字号"
        n = len(p["cols"])
        wide = n * POEM_GAP
        if wide > W - 120:
            bad.append("诗文页 %d 列 x 列距 %d = %d，超出 1080 的安全范围"
                       % (n, POEM_GAP, wide))
        if POEM_GAP < POEM_FS + 40:
            bad.append("诗文页列距 %d 对字号 %d 太挤（至少 %d）"
                       % (POEM_GAP, POEM_FS, POEM_FS + 40))
        tall = POEM_TOP + max(len(c) for c in p["cols"]) * POEM_FS
        if tall > H - 120:
            bad.append("诗文页最长一列到 %d，超出画底" % tall)
        if POEM_HEAD_Y + POEM_HEAD_FS > POEM_TOP - 20:
            bad.append("诗文页标题(%d)和正文首行(%d)挤在一起" % (POEM_HEAD_Y, POEM_TOP))
        if POEM_SIG_Y < tall + 40:
            bad.append("落款顶端 %d 和正文最长列的底(%d)挤在一起" % (POEM_SIG_Y, tall))
        if POEM_SIG_Y + len(p["sig"]) * POEM_SIG_FS > H - 80:
            bad.append("诗文页落款到 %d，超出画底"
                       % (POEM_SIG_Y + len(p["sig"]) * POEM_SIG_FS))
        # 逐列显的最后一列 + 落款必须在页子收掉之前出全
        last = p["t0"] + 0.6 + POEM_COL_STEP * n
        if last > p["t1"] - 2.0:
            bad.append("诗文页逐列显到 %.1fs 才出全，离收尾(%.1fs)不足 2s"
                       % (last, p["t1"]))
        if last > total - FADE_OUT - 1.0:
            bad.append("诗文页 %.1fs 才出全，片尾淡出已经从 %.1fs 开始了"
                       % (last, total - FADE_OUT))
    for c in CLIPS:
        if not os.path.exists(os.path.join(SRC, c["src"])):
            warn.append("缺素材: " + c["src"])
    if not os.path.exists(os.path.join(SRC, "img%02d.png" % COVER_FROM)):
        warn.append("缺封面原图: img%02d.png" % COVER_FROM)
    for f, t, g, fi, fo, lp in SFX:
        if not os.path.exists(os.path.join(SRC, f)):
            warn.append("音效还没就位（缺文件会自动跳过，不影响出片）")
            break
    for txt, f in VO:
        if not os.path.exists(vo_path(f)):
            warn.append("缺诵读: " + f)
    if not os.path.exists(MUSIC):
        warn.append("音乐还没就位")
    elif MUSIC_IN is None:
        # 判据用 `is None` 而不是 `<= 0`：上一支 maximin 真的选出了 0.0，
        # 拿 0 当"还没选"的哨兵会把一个合法结果误报成占位值。
        warn.append("MUSIC_IN 还没定 —— 跑 `python make_v.py pick` 用 maximin 选切入点")
    else:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "csv=p=0", MUSIC],
                           capture_output=True, text=True)
        try:
            mdur = float(p.stdout.strip()); need = MUSIC_IN + total
            if need > mdur + 1e-3:
                bad.append("音乐不够长: 从 %.1fs 切入需要到 %.1fs，全曲只有 %.1fs"
                           % (MUSIC_IN, need, mdur))
            else:
                print("音乐: 全曲 %.1fs，从 %.1fs 切入，用到 %.1fs，余 %.1fs"
                      % (mdur, MUSIC_IN, need, mdur - need))
            if mdur < total * 1.6:
                warn.append("音乐只比片长多 %.0fs（不到片长的 0.6 倍），切入点挑得比较紧"
                            % (mdur - total))
        except ValueError:
            warn.append("读不出音乐时长")
    bad += check_xfades()
    bad += check_moves()
    bad += check_resolution()
    bad += check_vo()
    bad += check_fx()
    bad += check_safe()
    print("\n片长 %.1fs (%d:%04.1f)  镜头 %d  字幕 %d 条  诗文页 %d 列  %dx%d"
          % (total, total // 60, total % 60, len(SHOTS), len(LINES),
             len(POEMS[0]["cols"]) if POEMS else 0, W, H))
    print("镜头起点: " + "  ".join("%.1f" % s for s in starts))
    print("转场落点: " + "  ".join("%.1f" % c for c in cuts))
    print("转场时长: " + "  ".join("%.1f" % xf(i) for i in range(len(SHOTS) - 1)))
    print("正文停留: " + "  ".join("%.1f" % (e - s) for s, e, _, t in LINES if t == "M"))
    print("成片中点: %.1fs (镜 %d)" % (total / 2, shot_of(total / 2)))
    selftest_safe()
    for w in warn:
        print("提示: " + w)
    if bad:
        print("\n!! 时间轴问题:")
        for b in bad:
            print("   - " + b)
    else:
        print("\n时间轴自检通过。")
    return not bad


# ================= 粒子层 =================
def make_fx():
    """残雨层 + 落叶层。都是灰度遮罩，颜色在 pass_c 里给 —— 调颜色不用重渲。"""
    # ---- 雨丝瓦片 ----
    # src_h 决定雨丝长度：拉伸倍数 = 1920/src_h，一个点被拉成那么长的一道。
    # 上下叠成两倍高再拉伸、取中间 1920，是为了让瓦片顶底接得上（滚动无缝）。
    # 密度比上一支再压一档：这是"刚停的雨"，不是雨中。
    for tag, seed, src_h, dens in (("A", 3, 150, 0.0016), ("B", 6, 115, 0.0008)):
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
             "-i", "color=c=black:s=%dx%d" % (W, src_h),
             "-filter_complex",
             "[0:v]format=gray,geq=lum='if(gt(random(%d),%.6f),255,0)',split[d1][d2];"
             "[d1][d2]vstack[dd];"
             "[dd]scale=%d:%d:flags=bilinear,gblur=sigma=0.55:sigmaV=1.6,"
             "crop=%d:%d:0:%d[v]" % (seed, 1 - dens, W, H * 2, W, H, H // 2),
             "-map", "[v]", "-frames:v", "1", "fx_tile%s.png" % tag],
            "雨丝瓦片 %s (丝长约 %d px)" % (tag, H // src_h))

    # ---- 滚动方向：**这里错过两支** ----
    # crop 的 y 是取景窗在源图上的位置。源图上某一行 S 会出现在画面的 (S - y) 行，
    # 所以 **y 递增 = 画面内容往上跑**。第一版照抄的写法是 `t*v mod H`（递增），
    # 雨就是往上飘的 —— 而这个错在**静帧上完全看不出来**（单帧雨丝没有方向），
    # 参数表上也看不出来，只有连续看才发现。所以它在系列里活了两支。
    #
    # 正确写法是让 y 从 H 递减到 0 再绕回：画面内容随之往下走。
    # 瓦片是上下叠成两倍高再裁中间的，顶底本来接得上，所以绕回处无缝。
    # 位移不用 mod()：filtergraph 里的逗号要转义，引号和反斜杠叠在一起容易被解析成别的。
    #
    # 改完**必须跑 _verify_fx_direction()**，别再靠眼睛看单帧。
    def scroll(v):
        return "%d-(t*%d-%d*floor(t*%d/%d))" % (H, v, H, v, H)

    # 两层从一开始就在（上一支是细->密，这一支要的是密->无），只做一次全局淡出。
    run(["ffmpeg", "-y", "-v", "error", "-stats",
         "-loop", "1", "-framerate", str(FPS), "-i", "fx_tileA.png",
         "-loop", "1", "-framerate", str(FPS), "-i", "fx_tileB.png",
         "-filter_complex",
         "[0:v]split[a1][a2];[a1][a2]vstack[ta];"
         "[ta]crop=%d:%d:0:'%s',format=gray,setsar=1[ra];"
         "[1:v]split[b1][b2];[b1][b2]vstack[tb];"
         "[tb]crop=%d:%d:0:'%s',format=gray,setsar=1[rb];"
         "[ra][rb]blend=all_mode=screen,fade=t=in:st=0:d=2.5,"
         "fade=t=out:st=%.2f:d=%.2f[v]"
         % (W, H, scroll(470), W, H, scroll(720), RAIN_OUT, RAIN_DUR - RAIN_OUT),
         "-map", "[v]", "-t", "%.3f" % RAIN_DUR, "-r", str(FPS),
         "-c:v", "libx264", "-crf", "18", "-preset", "medium",
         "-pix_fmt", "yuv420p", "fx_rain.mp4"],
        "残雨层 %.1fs" % RAIN_DUR)

    # ---- 叶子精灵 ----
    # 一枚尖卵形的叶：在高度 Y 处的半宽 = 42*sin(pi*(Y/S)^0.8)，两头收尖。
    # 中间压一道叶脉（alpha 降到四成）—— 少了这一道就是个纯剪影，一眼看出是贴上去的。
    # alpha 用 2.5px 的软边，不用 gblur（gblur 会把 alpha 一起糊掉，边缘发灰）。
    S = 160
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "color=c=white:s=%dx%d" % (S, S),
         "-vf", "format=rgba,geq=r='255':g='255':b='255':"
                "a='255*clip((42*sin(3.14159265*pow(Y/%d,0.8))-abs(X-%d))/2.5,0,1)"
                "*(1-0.6*exp(0-(X-%d)*(X-%d)/4))'" % (S, S // 2, S // 2, S // 2),
         "-frames:v", "1", "fx_leaf.png"], "叶子精灵")

    n = len(LEAVES)
    parts = ["[1:v]split=%d%s" % (n, "".join("[l%d]" % k for k in range(n)))]
    cur = "[0:v]"
    for k, (dl, xa, ya, vx, vy, amp, frq, rot, sz) in enumerate(LEAVES):
        x0, y0 = xa - vx * dl, ya - vy * dl      # 反推 t=0 时的位置
        pad = int(sz * 1.5)
        parts.append("[l%d]scale=%d:%d,rotate='%.3f+t*%.3f':c=none:ow=%d:oh=%d[r%d]"
                     % (k, sz, sz, k * 0.7 - rot * dl, rot, pad, pad, k))
        parts.append("%s[r%d]overlay=x='%.1f+%.1f*t+%d*sin(t*%.3f+%.2f)':"
                     "y='%.1f+%.1f*t':eval=frame[o%d]"
                     % (cur, k, x0, vx, amp, frq, k * 1.3, y0, vy, k))
        cur = "[o%d]" % k
    parts.append("%sformat=gray,fade=t=in:st=0:d=1.2,fade=t=out:st=%.2f:d=1.6[v]"
                 % (cur, LEAF_DUR - 1.6))
    run(["ffmpeg", "-y", "-v", "error", "-stats",
         "-f", "lavfi", "-i", "color=c=black:s=%dx%d:r=%d:d=%.3f" % (W, H, FPS, LEAF_DUR),
         "-loop", "1", "-framerate", str(FPS), "-i", "fx_leaf.png",
         "-filter_complex", ";".join(parts), "-map", "[v]",
         "-t", "%.3f" % LEAF_DUR, "-r", str(FPS), "-c:v", "libx264", "-crf", "16",
         "-preset", "medium", "-pix_fmt", "yuv420p", "fx_leaf.mp4"],
        "落叶层  %d 片叶  %.1fs" % (n, LEAF_DUR))
    _verify_fx_direction()
    print("\n粒子层就绪。改颜色/浓度只需重跑 fx + c，a/b 两趟不受影响。")


def _verify_fx_direction():
    """量粒子层到底是往下走还是往上走。**渲完必须跑，不能靠眼睛看单帧。**

    雨往上飘那个错在这个系列里活了两支，原因就是它在静帧上完全看不出来：
    单帧的雨丝是一道竖线，没有方向；参数表上 `t*v mod H` 看着也很正常。
    只有把两帧比一比才知道。所以做成自动检查，而不是"记得看一眼"。

    雨：满屏随机雨丝，用**垂直互相关**找两帧之间的最佳位移。
    叶：稀疏的亮斑，直接量**亮像素的平均 y**，比互相关稳。
    两者都是位移为正 = 往下。

    这里量的是粒子层本身（底是纯黑，帧里只有粒子），所以直接相关两帧就行。
    **要是想在成片上复验，必须用带符号的帧差 `f2-f1`，不能用绝对值差** ——
    一滴雨从 p 移到 p+k，`|f2-f1|` 在 p 和 p+k 两处都留能量，
    相邻两次帧差共享中间那一份，相关峰会恒定落在 0，看起来像"没在动"。
    带符号时 d2(y) = d1(y-k) 成立，峰才落在真实位移上（实测成片 +300~500 px/s）。
    """
    SW, SH = 48, 384                    # 降到这个尺寸够判方向，也够快

    def gray(f, t):
        return subprocess.run(["ffmpeg", "-v", "error", "-ss", "%.3f" % t, "-i", f,
                               "-frames:v", "1", "-vf",
                               "scale=%d:%d:flags=area,format=gray" % (SW, SH),
                               "-f", "rawvideo", "-"], capture_output=True).stdout

    ok = True
    # ---- 雨：互相关 ----
    dt = 0.10
    a, b = gray("fx_rain.mp4", 4.0), gray("fx_rain.mp4", 4.0 + dt)
    if len(a) == SW * SH and len(b) == SW * SH:
        best = None
        for s in range(-30, 31):        # b[y] ~ a[y-s]，s>0 = 内容往下走
            acc = n = 0
            for y in range(max(0, s), min(SH, SH + s)):
                for x in range(SW):
                    acc += a[(y - s) * SW + x] * b[y * SW + x]
                    n += 1
            if n and (best is None or acc / n > best[0]):
                best = (acc / n, s)
        shift = best[1] * (H / SH) / dt         # 换算回 成片px/秒
        good = best[1] > 0
        ok &= good
        print("   雨丝方向: %+.0f px/s  —— %s"
              % (shift, "往下，对" if good else "**往上，错了**（crop 的 y 偏移方向反了）"))
    # ---- 叶：亮像素平均 y ----
    def leaf_y(t):
        g = gray("fx_leaf.mp4", t)
        if len(g) != SW * SH:
            return None
        pts = [(y, g[y * SW + x]) for y in range(SH) for x in range(SW) if g[y * SW + x] > 40]
        return sum(y * w for y, w in pts) / sum(w for _, w in pts) if pts else None

    y0, y1 = leaf_y(3.0), leaf_y(4.2)
    if y0 is not None and y1 is not None:
        v = (y1 - y0) * (H / SH) / 1.2
        good = y1 > y0
        ok &= good
        print("   落叶方向: %+.0f px/s  —— %s"
              % (v, "往下，对" if good else "**往上，错了**"))
    if not ok:
        print("   !! 粒子方向不对，修 make_fx() 里的 scroll()/LEAVES 再重跑 fx")
    return ok


def fx_ready():
    return all(os.path.exists(f) for f in ("fx_rain.mp4", "fx_leaf.mp4"))


def fx_chain(base, first_idx):
    """把两个灰度遮罩上色后叠到 base 上。返回 (滤镜片段列表, 输出标签)。
    遮罩 -> tpad 补到片上正确的起点 -> 当 alpha 配一张纯色 -> overlay。

    **叠加层必须真的会结束**，上一支在这里踩了两次：落叶从第 20 秒起冻在画面上
    一路挂到片尾，而它是"正确地"叠在每一帧上的，看参数完全看不出来。
    根不在 overlay 的 eof_action（加了没用），在上一级：给 alphamerge 当底的
    `color=` 源是**无限长**的，alphamerge 又默认 repeatlast=1，于是遮罩结束后
    它拿最后一帧继续跟无限的纯色配对，永远不 EOF。
    所以三处一起收紧：纯色源给定长 d=、alphamerge 加 shortest=1:repeatlast=0、
    overlay 加 eof_action=pass:repeatlast=0。"""
    parts, cur, i = [], base, first_idx
    for tag, t0, dur, color, alpha in (
            ("rain", RAIN_T0, RAIN_DUR, RAIN_COLOR, RAIN_ALPHA),
            ("leaf", LEAF_T0, LEAF_DUR, LEAF_COLOR, LEAF_ALPHA)):
        parts.append("[%d:v]format=gray,tpad=start_duration=%.3f:start_mode=add:"
                     "color=black,setpts=PTS-STARTPTS[m_%s]" % (i, t0, tag))
        parts.append("color=c=%s:s=%dx%d:r=%d:d=%.3f[c_%s]"
                     % (color, W, H, FPS, t0 + dur, tag))
        parts.append("[c_%s][m_%s]alphamerge=shortest=1:repeatlast=0,"
                     "colorchannelmixer=aa=%.3f[p_%s]" % (tag, tag, alpha, tag))
        parts.append("%s[p_%s]overlay=0:0:eof_action=pass:repeatlast=0:"
                     "format=auto[fx%s]" % (cur, tag, tag))
        cur = "[fx%s]" % tag
        i += 1
    return parts, cur


# ================= 音频 =================
def pick_music_in():
    """用 ebur128 量整首的瞬时响度，按 maximin 选切入点。

    目标函数是"最大化全片要紧落点里最弱的那一个"，不是加权求和 ——
    加权和会把开场分拉满、却把成片中点和末句推进曲子最弱处（栽过一次）。
    这一支没有诵读，怕的就是某一处塌下去。"""
    if not os.path.exists(MUSIC):
        sys.exit("!!! 音乐还没就位: " + MUSIC)
    total = total_len()
    # framelog=info，不是 verbose：ffmpeg 8.x 里 verbose 的逐帧日志要配 -loglevel verbose
    # 才吐得出来，默认日志级别下只剩一段 Summary，解析器会一行都读不到。
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", MUSIC,
                        "-af", "ebur128=framelog=info", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    curve = []
    for ln in p.stderr.splitlines():
        if "t:" in ln and " M:" in ln:
            try:
                t = float(ln.split("t:")[1].split()[0])
                m = float(ln.split(" M:")[1].split()[0])
                if m > -70:
                    curve.append((t, m))
            except (IndexError, ValueError):
                pass
    if len(curve) < 50:
        sys.exit("!!! 读不出响度曲线")
    mdur = curve[-1][0]
    print("全曲 %.1fs，响度采样 %d 点，最低 %.1f / 最高 %.1f LUFS"
          % (mdur, len(curve), min(m for _, m in curve), max(m for _, m in curve)))

    starts = shot_starts()
    # 成片上真正要紧的窗口。**开场不放进来**：镜 1 的前 6.6s 只有标题在走、
    # 一个字幕都没有，曲子最弱的一段落在那儿反而合适。把开场让出来，
    # 剩下这八个才是真正不能塌的地方。
    keys = [("执手", starts[4], 9.0), ("凝噎", starts[5], 8.0),
            ("楚天阔", starts[7], 9.0), ("中点", total / 2 - 3, 6.0),
            ("下阕起", starts[8], 8.0), ("晓风残月", starts[11], 9.0),
            ("末句长留", starts[13], 10.0), ("诗文页", starts[14], 8.0),
            ("淡出", total - 5, 5.0)]

    def win_avg(off, a, d):
        v = [m for t, m in curve if off + a <= t <= off + a + d]
        return sum(v) / len(v) if v else -70.0

    best, room = None, mdur - total
    if room <= 0:
        sys.exit("!!! 音乐比片子还短")
    step, off = 0.5, 0.0
    while off <= room + 1e-6:
        scores = [win_avg(off, a, d) for _, a, d in keys]
        mn = min(scores)
        if best is None or mn > best[0]:
            best = (mn, off, scores)
        off += step
    mn, off, scores = best
    print("\nmaximin 选出切入点 %.1fs（余地 %.1fs，用到 %.1fs）" % (off, room, off + total))
    for (name, _, _), s in zip(keys, scores):
        print("   %-9s %.1f LUFS" % (name, s))
    print("   全片最弱落点 %.1f LUFS" % mn)
    lows = [m for t, m in curve if off <= t <= off + total]
    print("   这一段的最深谷 %.1f LUFS" % min(lows))
    print("\n把 MUSIC_IN 改成 %.1f" % off)


def integrated_lufs(path):
    """只读一条音频的整合响度，不打印。用来给音效反算增益。"""
    import json
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af",
                        "loudnorm=print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        m = json.loads(p.stderr[p.stderr.rfind("{"):p.stderr.rfind("}") + 1])
        return float(m["input_i"])
    except (ValueError, KeyError):
        return None


def vo_path(f):
    return os.path.join(VO_DIR, f if f.lower().endswith((".mp3", ".wav", ".m4a"))
                        else f + ".mp3")


def vo_dur(f):
    """量一条诵读的实测时长，按 (文件, mtime, 大小) 缓存。缺文件返回 None。"""
    p = vo_path(f)
    if not os.path.exists(p):
        return None
    st = os.stat(p)
    key = "%s|%d|%d" % (f, int(st.st_mtime), st.st_size)
    if not _VO_CACHE:
        try:
            _VO_CACHE.update(json.load(open(VO_CACHE, encoding="utf-8")))
        except (ValueError, OSError, IOError):
            pass
    if key not in _VO_CACHE:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "csv=p=0", p],
                           capture_output=True, text=True)
        try:
            _VO_CACHE[key] = float(r.stdout.strip())
        except ValueError:
            return None
        try:
            json.dump(_VO_CACHE, open(VO_CACHE, "w", encoding="utf-8"))
        except (OSError, IOError):
            pass
    return _VO_CACHE[key]


def vo_plan():
    """把 VO 表落到时间轴上。返回 [(文本, 文件, 语音起, 时长, 字幕起, 字幕止), ...]。

    落点由字幕推出来（字幕起 + VO_LEAD），不手写偏移量。缺文件的条目时长为 None。
    """
    out = []
    for txt, f in VO:
        hit = [(s, e) for s, e, t, y in LINES if y == "M" and t == txt]
        if not hit:
            sys.exit("!!! 诵读 %s 对不上任何一条正文字幕：%s" % (f, txt))
        s, e = hit[0]
        out.append((txt, f, s + VO_LEAD, vo_dur(f), s, e))
    return out


def check_vo():
    """诵读的两条硬约束：**不能跨转场**，**必须在字幕消失前读完**。

    跨转场的语音会在画面切开的瞬间被拦腰截断，听感上像卡带；
    读不完的语音会被下一句字幕压上去，两句叠在一起。
    这两样在参数表上都看不出来，而且只要漏一句就毁一处。
    """
    if not VO:
        return []
    bad, cuts = [], cut_points()
    for txt, f, vs, d, ls, le in vo_plan():
        if d is None:
            continue                       # 缺文件由 check_timeline 统一提示
        ve = vs + d
        if ve > le - VO_TAIL_MIN:
            bad.append("诵读『%s』%.2fs，到 %.1fs 才读完，而字幕 %.1fs 就收了"
                       % (txt, d, ve, le))
        for c in cuts:
            if vs - 0.15 < c < ve + 0.15:
                bad.append("诵读『%s』(%.1f~%.1fs) 被 %.1fs 的转场切开" % (txt, vs, ve, c))
    return bad


def vosync():
    """量诵读、打出落点表。改了配音先跑它（缓存按 mtime 自动失效）。"""
    if not VO:
        print("VO 表是空的 —— 这一支无诵读。")
        return
    if os.path.exists(VO_CACHE):
        os.remove(VO_CACHE)
    _VO_CACHE.clear()
    plan, miss = vo_plan(), 0
    print("")
    print("=== 诵读落点（字幕起 + VO_LEAD %.2fs）===" % VO_LEAD)
    print("   语速 = 字数 / 实测时长；古诗词诵读通行在 2.2~3.6 字/秒")
    tot = 0.0
    for txt, f, vs, d, ls, le in plan:
        if d is None:
            print("  %-12s %-12s (缺文件)" % (txt[:12], f)); miss += 1; continue
        n = sum(1 for ch in txt if ch not in "，。：；、？！|")
        tot += d
        slack = le - (vs + d)
        flag = "" if slack >= VO_TAIL_MIN else "  << 读不完，字幕先收了"
        print("  %-12s %-12s %5.2fs  %d字 %.1f字/秒  语音 %5.1f~%5.1f  "
              "字幕 %5.1f~%5.1f  余 %5.2fs%s"
              % (txt[:12], f, d, n, n / d, vs, vs + d, ls, le, slack, flag))
    print("")
    print("  诵读净时长 %.1fs，占片长 %.1fs 的 %.0f%%（词的诵读本来就该是稀的）"
          % (tot, total_len(), 100 * tot / max(1e-6, total_len())))
    if miss:
        print("  还缺 %d 条。" % miss)


def vo_bus(ins, parts, mixed, k, total):
    """把诵读接进混音链，并让音乐给它侧链躲闪。

    每条**单独**按实测响度归一到 VO_TARGET —— TTS 逐条的电平能差好几 dB，
    写死一个增益就会有的听不见、有的冒出来。
    """
    if not VO:
        return k
    plan = [p for p in vo_plan() if p[3] is not None]
    if not plan:
        print("   诵读文件一条都没有，跳过")
        return k
    bus = []
    print("")
    print("   诵读增益（逐条按实测反算到 %.1f LUFS）：" % VO_TARGET)
    for txt, f, vs, d, ls, le in plan:
        meas = integrated_lufs(vo_path(f))
        g = VO_TARGET - meas if meas is not None else 0.0
        print("     %-12s 实测 %6.1f → %+5.1f dB" % (f, meas if meas else 0, g))
        ins += ["-i", vo_path(f)]
        parts.append("[%d:a]aresample=48000,aformat=fltp:cl=stereo,volume=%.1fdB,"
                     "afade=t=in:st=0:d=%.2f,afade=t=out:st=%.3f:d=%.2f,"
                     "adelay=%d|%d,apad[v%d]"
                     % (k, g, VO_FADE, max(0.0, d - VO_FADE), VO_FADE,
                        int(vs * 1000), int(vs * 1000), k))
        bus.append("[v%d]" % k)
        k += 1
    parts.append("%samix=inputs=%d:normalize=0:dropout_transition=0,atrim=0:%.3f[vo]"
                 % ("".join(bus), len(bus), total))
    parts.append("[vo]asplit=2[voa][vosc]")
    parts.append("[m][vosc]sidechaincompress=threshold=%.3f:ratio=%d:attack=%d:"
                 "release=%d[md]" % (VO_DUCK["threshold"], VO_DUCK["ratio"],
                                     VO_DUCK["attack"], VO_DUCK["release"]))
    mixed[0] = "[md]"                       # 音乐换成躲闪之后的
    mixed.append("[voa]")
    return k


def build_audio():
    total = total_len()
    mi = MUSIC_IN or 0.0
    ins, parts, mixed = ["-i", MUSIC], [], []
    parts.append("[0:a]aresample=48000,aformat=fltp:cl=stereo,"
                 "atrim=start=%.3f:end=%.3f,asetpts=PTS-STARTPTS,volume=%.1fdB,"
                 "apad,atrim=0:%.3f,afade=t=in:st=0:d=%.2f,afade=t=out:st=%.3f:d=5[m]"
                 % (mi, mi + total, MUSIC_GAIN, total, MUSIC_FADE_IN, total - 5))
    mixed.append("[m]")
    k = 1
    k = vo_bus(ins, parts, mixed, k, total)
    for f, t, tgt, fi, fo, dur in SFX:
        path = os.path.join(SRC, f)
        if not os.path.exists(path):
            print("   跳过音效(缺文件): " + f); continue
        # 增益按**实测**反算，不写死 —— 生成的音效响度能差 45 dB，见 SFX 表上的注释
        meas = integrated_lufs(path)
        if meas is None:
            print("   !! 读不出 %s 的响度，按 −20 dB 保底" % f); g = -20.0
        else:
            g = tgt - meas
            flag = ""
            if g > SFX_GAIN_WARN:
                flag = "  << 提得太多，素材本身太轻，底噪会一起上来，建议重生成这一条"
            elif g < -40:
                flag = "  << 压得太多，素材本身太响，检查是不是生成错了"
            print("   %-12s 实测 %6.1f → 目标 %6.1f，增益 %+6.1f dB%s"
                  % (f, meas, tgt, g, flag))
        # 一律循环进来再按 dur 裁：短的自动接上，长的直接切断。
        # 让音效"放到自然结束"是错的 —— 上一支的秋风盖掉雁鸣就是这么来的。
        ins += ["-stream_loop", "-1", "-i", path]
        parts.append("[%d:a]aresample=48000,aformat=fltp:cl=stereo,"
                     "atrim=0:%.3f,asetpts=PTS-STARTPTS,volume=%.1fdB,"
                     "afade=t=in:st=0:d=%.2f,afade=t=out:st=%.3f:d=%.2f,"
                     "adelay=%d|%d,apad[s%d]"
                     % (k, dur, g, fi, max(0.0, dur - fo), fo,
                        int(t * 1000), int(t * 1000), k))
        mixed.append("[s%d]" % k)
        k += 1
    parts.append("%samix=inputs=%d:normalize=0:dropout_transition=0,"
                 "atrim=0:%.3f,alimiter=limit=0.95[a]"
                 % ("".join(mixed), len(mixed), total))
    run(["ffmpeg", "-y", "-v", "error", "-stats"] + ins
        + ["-filter_complex", ";".join(parts), "-map", "[a]",
           "-c:a", "pcm_s24le", "-t", "%.3f" % total, "mix.wav"],
        "混音: 音乐(从 %.1fs 切入%s) + %d 条音效"
        % (mi, "，侧链躲闪" if VO else "", len(SFX)))


def measure_loudness(path):
    import json
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af",
                        "loudnorm=I=%.1f:TP=%.1f:print_format=json" % (TARGET_I, TARGET_TP),
                        "-f", "null", "-"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    m = json.loads(p.stderr[p.stderr.rfind("{"):p.stderr.rfind("}") + 1])
    print("   实测 I=%s LUFS  TP=%s dBTP" % (m["input_i"], m["input_tp"]))
    return m


# ================= 渲染 =================
def pass_a():
    os.makedirs("shots", exist_ok=True)
    for i, s in enumerate(SHOTS, 1):
        if not os.path.exists("img%02d.png" % i):
            sys.exit("!!! 缺 img%02d.png，先跑 prep" % i)
        d = max(1, int(round(s["dur"] * FPS)) - 1)
        z0, z1 = s["z"]; (x0, y0), (x1, y1) = s["f0"], s["f1"]
        ze = "%.6f+(%.6f)*on/%d" % (z0, z1 - z0, d)
        xe = ("max(0,min(iw-iw/zoom,(%.6f+(%.6f)*on/%d)*iw-(iw/zoom)/2))"
              % (x0, x1 - x0, d))
        ye = ("max(0,min(ih-ih/zoom,(%.6f+(%.6f)*on/%d)*ih-(ih/zoom)/2))"
              % (y0, y1 - y0, d))
        # **这一支加回了 vignette。** 前六支是纸本画面，vignette 会像被烟熏过；
        # 暗调实拍里它是镜头本来就有的东西，而且顺手把右上角压暗一档，
        # 白字站得更稳 —— 一举两得，所以放在 zoompan 之后（暗角跟画框走，不跟内容走）。
        vf = ("scale=%d:%d:flags=lanczos," % UP
              + "zoompan=z='%s':x='%s':y='%s':d=1:s=%dx%d:fps=%d,"
                % (ze, xe, ye, W, H, FPS)
              + (VIGNETTE + "," if VIGNETTE else "") + "setsar=1,format=yuv420p")
        run(["ffmpeg", "-y", "-v", "error", "-stats", "-loop", "1",
             "-framerate", str(FPS), "-t", "%.3f" % s["dur"],
             "-i", "img%02d.png" % i, "-vf", vf, "-c:v", "libx264", "-crf", "12",
             "-preset", "medium", "-pix_fmt", "yuv420p", "shots/shot%02d.mp4" % i],
            "镜头 %d/%d  %.1fs" % (i, len(SHOTS), s["dur"]))


def native_factor(w, h):
    """源图的有效边长 / 文件边长。SRC_NATIVE 没写就是 1.0。"""
    if not SRC_NATIVE:
        return 1.0
    return min(SRC_NATIVE[0] / float(w), SRC_NATIVE[1] / float(h))


def img_dims(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return tuple(int(x) for x in r.stdout.strip().split(","))
    except ValueError:
        return None


def check_resolution():
    """裁后短边够不够 —— **按有效分辨率算，不按文件尺寸算**。

    规则：裁成目标比例之后短边至少是成片对应边的 1.5 倍（竖版即 >=1440）。
    低于这条线要么运镜做不动，要么成片发软。941x1672 那次是下限的 0.65 倍，
    而文件上写的是 2896x5152 —— 只查文件尺寸的检查对它一声不吭。
    """
    bad, rows = [], []
    zmax = max(max(s["z"]) for s in SHOTS) if SHOTS else 1.0
    for i, c in enumerate(CLIPS, 1):
        p = os.path.join(SRC, c["src"])
        if not os.path.exists(p):
            continue
        d = img_dims(p)
        if not d:
            continue
        w, h = d
        f = native_factor(w, h)
        cw = min(w, h * W / float(H)) / c["zoom"]      # 裁成成片比例、按 zoom 收紧后的短边
        eff = cw * f
        rows.append((i, c["src"], w, h, f, eff, eff / zmax / float(W)))
        if eff < W * 1.5 - 1:
            bad.append("%s 裁后有效短边 %.0f，不足下限 %d（成片对应边的 1.5 倍）"
                       % (c["src"], eff, int(W * 1.5)))
    if rows:
        print("")
        print("=== 素材分辨率（有效值）===")
        if SRC_NATIVE:
            print("   SRC_NATIVE=%dx%d —— 文件是放大上去的，下面按原生尺寸折算"
                  % SRC_NATIVE)
        else:
            print("   SRC_NATIVE 未设 —— 按文件尺寸算。"
                  "**如果图是放大上来的，这里的数字全是假的**")
        for i, s, w, h, f, eff, pp in rows:
            flag = "" if eff >= W * 1.5 - 1 else "  << 不足 %d" % int(W * 1.5)
            print("  %-2d %-20s 文件 %dx%d  x%.2f  裁后有效短边 %5.0f  "
                  "最紧取景 %.2f 源像素/输出像素%s" % (i, s[:20], w, h, f, eff, pp, flag))
    return bad


def pixels():
    """从每张源图裁 1:1 原始像素贴片拼一张，**用眼睛看有没有真细节**。

    自动判不出来（见 SRC_NATIVE 处的注释），所以做成必须看一眼的东西 ——
    和 still 之于字幕是同一个套路。放大上来的图在 1:1 下是平滑的插值面，
    没有逐像素的纹理和颗粒。

    但记住：**目视只是辅助**。要确认，去看生成器吐出来的原始文件的尺寸。
    """
    N, cols = 360, 4
    cells, missing = [], []
    for i, c in enumerate(CLIPS, 1):
        p = os.path.join(SRC, c["src"])
        if not os.path.exists(p):
            missing.append(c["src"]); continue
        d = img_dims(p)
        if not d:
            missing.append(c["src"]); continue
        w, h = d
        s = SHOTS[i - 1] if i <= len(SHOTS) else None
        fx, fy = s["f1"] if s else (0.5, 0.5)
        x = max(0, min(w - N, int(fx * w) - N // 2))
        y = max(0, min(h - N, int(fy * h) - N // 2))
        out = "_px%02d.png" % i
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", p,
                        "-vf", "crop=%d:%d:%d:%d" % (N, N, x, y),
                        "-frames:v", "1", out], capture_output=True)
        if os.path.exists(out):
            cells.append(out)
    if not cells:
        sys.exit("!!! 一张源图都没有")
    ins = []
    for f in cells:
        ins += ["-i", f]
    lay = []
    for k in range(len(cells)):
        cx = "0" if k % cols == 0 else "+".join("w%d" % j for j in range(k % cols))
        cy = "0" if k // cols == 0 else "+".join("h%d" % (j * cols) for j in range(k // cols))
        lay.append("%s_%s" % (cx, cy))
    fc = "".join("[%d:v]" % k for k in range(len(cells))) \
        + "xstack=inputs=%d:layout=%s:fill=black" % (len(cells), "|".join(lay))
    run(["ffmpeg", "-y", "-v", "error"] + ins
        + ["-filter_complex", fc, "-frames:v", "1", "_pixels.png"],
        "1:1 贴片联系表 %d 格" % len(cells))
    for f in cells:
        os.remove(f)
    print("")
    print("  _pixels.png —— 每格 %dx%d 原始像素，按 CLIPS 顺序，取各镜落幅焦点处。" % (N, N))
    print("  有逐像素的纹理和颗粒 = 真分辨率；平滑的插值面 = 放大上来的。")
    if missing:
        print("  缺图 %d 张：%s" % (len(missing), ", ".join(missing[:4])))


def motion():
    """量每一镜**渲出来**的首尾帧差 —— 运镜到底看不看得出来。

    trace 的落幅平坦度是出图阶段的筛子，对暗调图天生爱误报：大片夜空本来就是平的，
    整帧极差 147 的一张好图照样能报 8/16 行平坦。真正要紧的不是落幅那一帧长什么样，
    而是这一镜从头走到尾画面变了多少 —— 那个只能在 shots/ 上量。
    判据：首尾帧平均绝对差 >= MOTION_MIN（亮度可觉察差约 2~3 级，取 4）。

    读不出的镜头（还在写、moov atom 没落盘）**不算通过**：跳过之后照样打印
    "全部都看得出来"，就又造出一个不会报警的检查。
    """
    if not os.path.isdir("shots"):
        sys.exit("!!! 还没有 shots/，先跑 a")
    GW, GH = 96, 171

    def frame(f, t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "%.3f" % t, "-i", f,
                              "-frames:v", "1", "-vf",
                              "scale=%d:%d:flags=area,format=gray" % (GW, GH),
                              "-f", "rawvideo", "-"], capture_output=True).stdout
        return raw if len(raw) == GW * GH else None

    print("")
    print("=== 运镜实测（渲出来的首尾帧差，判据：均差 >= %.1f 级）===" % MOTION_MIN)
    bad, skipped = [], []
    for i, s in enumerate(SHOTS, 1):
        f = "shots/shot%02d.mp4" % i
        if not os.path.exists(f):
            print("  镜%-3d (未渲染)" % i); skipped.append(i); continue
        a, b = frame(f, 0.05), frame(f, max(0.1, s["dur"] - 0.1))
        if a is None or b is None:
            print("  镜%-3d (读不出帧，可能还在渲)" % i); skipped.append(i); continue
        d = sorted(abs(a[k] - b[k]) for k in range(GW * GH))
        mean = sum(d) / len(d)
        flag = ""
        if POEMS and i > len(SHOTS) - len(POEMS):
            flag = "  (诗文页，本来就该几乎静止 —— 不适用)"
        elif mean < MOTION_MIN:
            flag = "  << 肉眼看不出在动，加大 z 跨度或换一张有结构的图"
            bad.append(i)
        print("  镜%-3d %-18s 均差 %5.1f  中位 %3d  p90 %3d  最大 %3d%s"
              % (i, CLIPS[i - 1]["src"][:18], mean, d[len(d) // 2],
                 d[int(len(d) * 0.9)], d[-1], flag))
    if bad:
        print("")
        print("  %d 镜运镜看不出来: %s" % (len(bad), ", ".join(str(i) for i in bad)))
    if skipped:
        print("")
        print("  !! %d 镜没量到: %s —— **不算通过**，渲完再跑一次"
              % (len(skipped), ", ".join(str(i) for i in skipped)))
    if not bad and not skipped:
        print("")
        print("  %d 镜运镜全部看得出来。" % len(SHOTS))
    return not bad and not skipped


def pass_b():
    ins = []
    for i in range(1, len(SHOTS) + 1):
        ins += ["-i", "shots/shot%02d.mp4" % i]
    parts, cur, off = [], "[0:v]", 0.0
    for i in range(1, len(SHOTS)):
        off += SHOTS[i - 1]["dur"] - xf(i - 1)
        parts.append("%s[%d:v]xfade=transition=fade:duration=%.3f:offset=%.3f[x%d]"
                     % (cur, i, xf(i - 1), off, i)); cur = "[x%d]" % i
    total = total_len()
    parts.append("%sfade=t=in:st=0:d=%.2f:c=%s,fade=t=out:st=%.3f:d=%.2f:c=%s[v]"
                 % (cur, FADE_IN, FADE_COLOR, total - FADE_OUT, FADE_OUT, FADE_COLOR))
    run(["ffmpeg", "-y", "-v", "error", "-stats"] + ins
        + ["-filter_complex", ";".join(parts), "-map", "[v]", "-c:v", "libx264",
           "-crf", "14", "-preset", "medium", "-pix_fmt", "yuv420p",
           "-r", str(FPS), "master.mp4"],
        "拼接 %d 镜  总长 %.1fs" % (len(SHOTS), total))


# ================= 字幕 =================
def _style(name, size, pol, spacing=0, align=8):
    if pol == "dark_on_light":
        pri, out, ol, sh = "&H00262A2D", "&H00EAF1F4", 3, 0
    else:
        # 白字的描边必须是**不透明的黑**，不是半透明 —— 写实画面的底是花的，
        # 半透明描边在细节多的地方等于没有。再加一层投影托住。
        pri, out, ol, sh = "&H00F4F4EE", "&H00000000", 3, 3
    return ("Style: %s,KaiTi,%d,%s,%s,%s,%s,0,0,0,0,100,100,%d,0,1,%d,%d,%d,40,40,0,1"
            % (name, size, pri, pri, out, out, spacing, ol, sh, align))


def styles_block():
    other = "dark_on_light" if POLARITY == "light_on_dark" else "light_on_dark"
    return "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour," \
           "SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline," \
           "StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow," \
           "Alignment,MarginL,MarginR,MarginV,Encoding\n" \
           + "\n".join([_style("T", 126, TITLE_POLARITY, 16, 5),
                        _style("TS", 54, TITLE_POLARITY, 10, 5),
                        _style("M", SUB_FS, POLARITY),
                        _style("MF", SUB_FS, other),          # FLIP_SHOTS 里那几镜的正文
                        _style("PM", POEM_FS, POLARITY, 8),   # 诗文页正文(竖排，顶端对齐)
                        _style("PH", POEM_HEAD_FS, POLARITY, 14, 5),
                        _style("SG", POEM_SIG_FS, POLARITY, 8)]) + "\n"


def ts(t):
    return "%d:%02d:%05.2f" % (t // 3600, t % 3600 // 60, t % 60)


def vtext(s):
    return r"\N".join(list(s))          # libass 无原生 CJK 竖排，逐字换行最稳


def sub_cols(txt):
    """正文拆列：`|` 处拆两列(右列在前)，分隔符本身不上屏；否则一列。

    不拿逗号当分隔符 —— 这一首句内有该上屏的标点（「冷落清秋节！」的叹号、
    两处问号），逗号法会把它们吃掉。"""
    if SUB_SEP in txt:
        a, b = txt.split(SUB_SEP, 1)
        return [(SUB_X_R, a), (SUB_X_L, b)]
    return [(SUB_X, txt)]


def sub_box(txt, pad=6):
    """字幕在画面上的外接矩形（顶端对齐，所以从 SUB_TOP 往下量）。"""
    cols = sub_cols(txt)
    xs = [x for x, _ in cols]
    h = max(len(p) for _, p in cols) * SUB_FS
    return (max(0, int(min(xs) - SUB_FS / 2 - pad)), min(W, int(max(xs) + SUB_FS / 2 + pad)),
            max(0, int(SUB_TOP - pad)), min(H, int(SUB_TOP + h + pad)))


def poem_col_x(k, n):
    """诗文页第 k 列(0 起，自右向左)的列心 x。整块居中于 POEM_CX。"""
    return int(POEM_CX + (n / 2 - 0.5 - k) * POEM_GAP)


def make_ass():
    ev = []
    for st, en, txt, sty in LINES:
        if sty == "T":
            ev.append("Dialogue: 0,%s,%s,T,,0,0,0,,{\\pos(540,560)}{\\fad(1400,1100)}%s"
                      % (ts(st), ts(en), txt))
        elif sty == "TS":
            ev.append("Dialogue: 0,%s,%s,TS,,0,0,0,,{\\pos(540,706)}{\\fad(1400,1100)}%s"
                      % (ts(st), ts(en), txt))
        else:
            name = "MF" if shot_of((st + en) / 2) in FLIP_SHOTS else "M"
            # 左列（下一句）延后出现，两列一起留到句末。
            # 延后量按这一句的时长算，不写死秒数：长句慢一点、短句快一点。
            for k, (x, part) in enumerate(sub_cols(txt)):
                s = st + (en - st) * SUB_COL_DELAY if k else st
                ev.append("Dialogue: 0,%s,%s,%s,,0,0,0,,{\\pos(%d,%d)}{\\fad(800,800)}%s"
                          % (ts(s), ts(en), name, x, SUB_TOP, vtext(part)))
    # 诗文页：竖排八列，**自右向左逐列显**，跟真实阅读顺序一致
    for p in POEMS:
        t0, t1 = ts(p["t0"]), ts(p["t1"])
        n = len(p["cols"])
        ev.append("Dialogue: 0,%s,%s,PH,,0,0,0,,{\\pos(%d,%d)}{\\fad(1400,1200)}%s"
                  % (t0, t1, POEM_CX, POEM_HEAD_Y, p["head"]))
        for k, col in enumerate(p["cols"]):
            ev.append("Dialogue: 0,%s,%s,PM,,0,0,0,,{\\pos(%d,%d)}{\\fad(900,1200)}%s"
                      % (ts(p["t0"] + 0.6 + POEM_COL_STEP * k), t1,
                         poem_col_x(k, n), POEM_TOP, vtext(col)))
        ev.append("Dialogue: 0,%s,%s,SG,,0,0,0,,{\\pos(%d,%d)}{\\fad(1200,1200)}%s"
                  % (ts(p["t0"] + 0.6 + POEM_COL_STEP * n), t1,
                     POEM_SIG_X, POEM_SIG_Y, vtext(p["sig"])))
    with open("sub.ass", "w", encoding="utf-8-sig") as f:
        f.write("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\n"
                "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n" % (W, H)
                + styles_block()
                + "\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,"
                  "MarginV,Effect,Text\n" + "\n".join(ev) + "\n")
    print("已生成 sub.ass")


def make_scrim():
    if SCRIM_ALPHA <= 0:
        return False
    c = "white" if POLARITY == "dark_on_light" else "black"
    v = "255" if c == "white" else "0"
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         "color=c=%s:s=%dx%d,format=rgba," % (c, W, H)
         + r"geq=r='%s':g='%s':b='%s':a='clip(255*%.3f*pow(max(0\,(X-%d))/%d\,%.2f),0,255)'"
         % (v, v, v, SCRIM_ALPHA, SCRIM_X0, SCRIM_SOFT, SCRIM_POW),
         "-frames:v", "1", "scrim.png"], "生成右侧 scrim")
    return True


def video_chain(scrim, with_fx, grain=True):
    """master -> [轻微颗粒] -> [粒子层] -> [scrim] -> 烧字幕。
    返回 (滤镜片段列表, 额外输入参数列表, 下一个可用输入序号)。

    顺序有讲究：**粒子层在 scrim 之前**。反过来的话右上那条压暗会把雨丝和叶子
    一起压掉一档，而那正是它们最该被看见的地方。"""
    fd = FONTS.replace("\\", "/")
    parts, ins, cur, idx = [], [], "[0:v]", 1
    if grain:
        # 暗调实拍留一点颗粒是对的（纸本画面才不能加）：既防大片暮色出色带，
        # 也把 AI 生成那种过分干净的质感压掉一点
        parts.append("[0:v]noise=alls=3:allf=t[g]"); cur = "[g]"
    if with_fx:
        ins += ["-i", "fx_rain.mp4", "-i", "fx_leaf.mp4"]
        fxp, cur = fx_chain(cur, idx)
        parts += fxp; idx += 2
    if scrim:
        ins += ["-loop", "1", "-i", "scrim.png"]
        parts.append("%s[%d:v]overlay=0:0:shortest=1[sc]" % (cur, idx))
        cur = "[sc]"; idx += 1
    parts.append("%ssubtitles=sub.ass:fontsdir=%s[v]" % (cur, fd))
    return parts, ins, idx


def pass_c():
    if not os.path.exists("master.mp4"):
        sys.exit("!!! 还没有 master.mp4，先跑 a + b")
    make_ass(); has = make_scrim(); total = total_len()
    with_fx = fx_ready()
    if not with_fx:
        print("提示: 粒子层还没生成（跑 `python make_v.py fx`），这一版不带残雨和落叶")
    build_audio()
    m = measure_loudness("mix.wav")
    norm = ("loudnorm=I=%.1f:TP=%.1f:LRA=%s:measured_I=%s:measured_TP=%s:"
            "measured_LRA=%s:measured_thresh=%s:offset=%s:linear=true,aresample=48000"
            % (TARGET_I, TARGET_TP, m["input_lra"], m["input_i"], m["input_tp"],
               m["input_lra"], m["input_thresh"], m["target_offset"]))
    fc, extra, idx = video_chain(has, with_fx)
    ins = ["-i", "master.mp4"] + extra + ["-i", "mix.wav"]
    fc.append("[%d:a]%s[a]" % (idx, norm))
    out = os.path.join("..", OUT_NAME)
    run(["ffmpeg", "-y", "-v", "error", "-stats"] + ins
        + ["-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]",
           "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart",
           "-t", "%.3f" % total, out],
        "粒子层 + 归一到 %.1f LUFS + 烧字幕 -> %s" % (TARGET_I, out))
    print("\n完成: " + out)


def still():
    """先整片烧低码率预览再抽帧。
    不能对 master 直接 "-ss T -i" 抽帧再烧字幕 —— -ss 在 -i 前会把 PTS 重置为 0，
    subtitles 滤镜按 PTS 找字幕，结果每张都去找 0 秒那一刻，一个字都渲染不出来。"""
    if not os.path.exists("master.mp4"):
        sys.exit("!!! 还没有 master.mp4，先跑 a + b")
    make_ass(); has = make_scrim(); os.makedirs("stills", exist_ok=True)
    fc, extra, _ = video_chain(has, fx_ready())
    run(["ffmpeg", "-y", "-v", "error", "-stats", "-i", "master.mp4"] + extra
        + ["-filter_complex", ";".join(fc), "-map", "[v]",
           "-c:v", "libx264", "-crf", "30", "-preset", "ultrafast",
           "-pix_fmt", "yuv420p", "-t", "%.3f" % total_len(), "preview.mp4"],
        "烧字幕预览")
    marks = [((s + e) / 2, t.replace(SUB_SEP, "／")) for s, e, t, y in LINES if y == "M"]
    marks.insert(0, (3.6, "标题"))
    # 两列是错开出现的，所以要在**左列还没出来**的时刻也抽一帧，
    # 否则只看得到"两列都在"的状态，看不出延后到底合不合适
    s0, e0 = [(s, e) for s, e, t, y in LINES if y == "M" and SUB_SEP in t][0]
    marks.append((s0 + (e0 - s0) * SUB_COL_DELAY * 0.5, "只有右列(延后中)"))
    # 粒子层单独看一眼：静帧上很容易看不出来
    marks += [(RAIN_T0 + 4.0, "残雨·最盛"), (RAIN_T0 + RAIN_OUT + 4.0, "残雨·将收"),
              (LEAF_T0 + LEAF_DUR * 0.5, "落叶·最盛")]
    for p in POEMS:
        marks.append((p["t0"] + 0.6 + POEM_COL_STEP * 3, "诗文页(显到一半)"))
        marks.append((p["t0"] + 0.6 + POEM_COL_STEP * len(p["cols"]) + 1.5, "诗文页(出全)"))
    marks.sort()
    for i, (t, txt) in enumerate(marks):
        run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % t, "-i", "preview.mp4",
             "-frames:v", "1", "stills/%02d_%.0fs.png" % (i, t)],
            "静帧 %.1fs  %s" % (t, txt))
    print("\n%d 张静帧在 stills/ —— 逐张打开看过再宣布完成" % len(marks))


def measure():
    """量每条字幕压着的底。

    **必须量无字的 master.mp4，不能量烧了字幕的 preview.mp4。**
    在烧过字的帧上框出字幕区求极值，量到的是字本身，不是它压着的底 ——
    每条都会整整齐齐报同一个数，看起来条条危险，其实一条都没问题。

    跑完和 trace 逐条对一遍：两者应该只差几级。**对不上不是字幕的问题，
    是运镜没走在你以为的位置上**，那比字幕糊了严重得多。

    注意 master 里**没有 scrim、没有粒子层、没有 vignette 以外的东西**，
    所以这里量到的是最坏情况；scrim 只会让它更好，不会更差。
    """
    if not os.path.exists("master.mp4"):
        sys.exit("!!! 还没有 master.mp4，先跑 a + b")

    def pct(v, p):
        v = sorted(v)
        return v[max(0, min(len(v) - 1, int(len(v) * p)))]

    print("\n=== 字幕底实测（无字 master；起 / 中 / 止，均值/分位(极值)）===")
    worst = []
    for st, en, txt, sty in LINES:
        if sty != "M":
            continue
        n = shot_of((st + en) / 2)
        dark = pol_of(n) == "dark_on_light"
        ink = ink_of(n)
        x0, x1, y0, y1 = sub_box(txt)
        out = []
        for t in (st + 0.2, (st + en) / 2, en - 0.2):
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "%.2f" % t,
                            "-i", "master.mp4", "-frames:v", "1", "_m.png"],
                           capture_output=True)
            b = subprocess.run(["ffmpeg", "-v", "error", "-i", "_m.png", "-vf",
                                "format=gray", "-f", "rawvideo", "-"],
                               capture_output=True).stdout
            v = [b[y * W + x] for y in range(y0, y1) for x in range(x0, x1)]
            out.append((sum(v) / len(v), pct(v, 0.01) if dark else pct(v, 0.99),
                        min(v) if dark else max(v)))
        w = min(o[1] for o in out) if dark else max(o[1] for o in out)
        worst.append((abs(w - ink), w, txt))
        print("  %-14s 镜%-3d " % (txt, n) + "  ".join("%3.0f/%3d(%3d)" % o for o in out))
    if os.path.exists("_m.png"):
        os.remove("_m.png")
    if not worst:
        return
    gap, m, who = min(worst)
    print("\n  最差处的底(分位) %d 出现在『%s』，离字色差 %d 级 —— %s"
          % (m, who, gap, "够用（>=50）" if gap >= 50
             else "不够：先把 SCRIM_ALPHA 调高一档试(只重跑 c)，还不行再加进 FLIP_SHOTS"))
    print("  这只是数字。还要跑 still 用眼睛看一遍：")
    print("  这一支是写实人物，数值够但压在**人脸或发丝**上是量不出来的。")


def cover():
    # 封面是单独生成的一张(img16)，不在 CLIPS 里，所以 prep 不会碰它 ——
    # 这里直接从素材目录读原图，自己缩放和调色。
    raw = os.path.join(SRC, "img%02d.png" % COVER_FROM)
    if not os.path.exists(raw):
        sys.exit("!!! 缺封面原图: " + raw)
    with open("cover.ass", "w", encoding="utf-8-sig") as f:
        f.write("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\n"
                "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n" % (W, H)
                + styles_block() + "\n[Events]\nFormat: Layer,Start,End,Style,Name,"
                "MarginL,MarginR,MarginV,Effect,Text\n"
                + "Dialogue: 0,0:00:00.00,0:00:10.00,T,,0,0,0,,"
                  "{\\pos(540,400)\\fs168}%s\n" % TITLE
                + "Dialogue: 0,0:00:00.00,0:00:10.00,TS,,0,0,0,,"
                  "{\\pos(540,580)\\fs62}%s\n" % AUTHOR)
    out = os.path.join("..", COVER_NAME)
    run(["ffmpeg", "-y", "-v", "error", "-i", raw,
         "-vf", "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,%s,"
                "vignette=PI/5,subtitles=cover.ass:fontsdir=%s"
                % (W, H, W, H, GRADE, FONTS.replace("\\", "/")),
         "-frames:v", "1", out],
        "封面 -> " + out)
    print("封面出好后**一定要打开看一眼**：这一支封面上有人，")
    print("标题最容易压在脸上 —— 前面有一支的落款正压在人的头顶。")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("prep", "probe", "trace", "fx", "still", "measure", "cover",
                "pick", "pixels", "motion", "vosync"):
        {"prep": prep, "probe": probe, "trace": trace, "fx": make_fx, "still": still,
         "measure": measure, "cover": cover, "pick": pick_music_in,
         "pixels": pixels, "motion": motion,
         "vosync": vosync}[what]()
        sys.exit(0)
    ok = check_timeline()
    if what == "check":
        sys.exit(0 if ok else 1)
    if what in ("a", "all"):
        if what == "all":
            prep(); make_fx()
        pass_a()
    if what in ("b", "all"):
        pass_b()
    if what in ("c", "all"):
        pass_c()
