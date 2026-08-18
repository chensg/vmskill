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

  python make_v.py check   # 时间轴自检(可读性/转场落点/运镜行程/安全区/音乐/授权)。永远先跑它
  python make_v.py budget  # **出图之前跑**：按每镜的运动反推要多大的图，分档抄进任务书
  python make_v.py prep    # 裁 9:16 + 统一调色 -> img01..img15，并自动 probe
  python make_v.py probe   # 只打亮度网格，不重新生成图
  python make_v.py trace   # 量镜头真正经过的区域（缺图会跳过），出图阶段就能判能不能用
  python make_v.py fx      # 生成残雨层 + 落叶层（纯 ffmpeg 合成，不用素材）
  python make_v.py pick    # 用 ebur128 + maximin 选音乐切入点
  python make_v.py mquality# 量一条配乐能不能用：底噪、低谷、频段、声道、头尾静音
  python make_v.py a       # 每张图做 Ken Burns（或按 MOTION 出静帧）-> shots/
  python make_v.py b       # xfade 溶解转场 -> master.mp4（无字、无粒子）
  python make_v.py c       # 粒子层 + 混音 + 归一 + 烧字幕 -> 成片
  python make_v.py still   # 烧预览并抽静帧，用眼睛验字幕认不认得出
  python make_v.py measure # 从无字 master 量字幕底的亮度，用数字验它够不够
  python make_v.py motion  # 量每镜渲出来的首尾帧差：运镜镜要看得出动，静帧镜要真的不动
  python make_v.py credits # 导出素材来源表（用公版/图库素材时是交付物的一部分）
  python make_v.py cover   # 封面（单独的 img16）
  python make_v.py all     # prep + fx + a + b + c

三条**开工前就要定死**的轴（都在下面的配置区，每一条都有对应的自检）：
  MOTION      运镜还是静帧。可以逐镜覆盖 —— dict(..., motion="static")
  MUSIC_MODE  配乐是生成的、公版的、还是**没有**；`song` 是 MV（见下）
  IMG_SOURCE  图是照任务书生成的，还是从公版/图库找来的（找来的必须登记来源）

**MV（拿一条带演唱的成品歌来做片子）**：MUSIC_MODE="song" + 填 SUNG 表。
它不是第四种模式，是诗词模式**换了个时间轴的主人** —— 不再由"读得完"定，
而是由唱腔定：片长 = 歌长，字幕起止 = 唱句起止，换镜只能落在句间空档。
SUNG 表不要手写，跑 `lyric_sync.py` 出，那边有整套吸附和验证。

留着的这一支是**暗调写实**，和纸本画种（水墨/工笔/水彩）**极性整个相反**：
白字 + 黑描边、黑场淡入淡出、pass_a 加 vignette、pass_c 留颗粒。
纸本画面里这三样都是"脏"，暗调实拍里它们是"对"。做纸本版时记得全部翻回去。
"""
import json
import os
import re
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
# ---- 颗粒：**跟着画种走，不是跟着习惯走** ----
# 暗调实拍留一点颗粒是对的（防大片暮色出色带、压掉 AI 那种过分干净的质感）；
# 纸本画种（水墨/工笔/水彩/宋人淡设色）**一律不加** —— 纸自己有纤维纹理，
# 叠一层噪声上去就是脏。技能文档里「纸本 → 写实要翻五处」那张表的最后一行
# 说的就是这件事，但模板一直把 grain 写死成 True，做纸本时全靠人记得去改
# —— 那正是"文档写了但代码不拦"的典型缺口，所以提成一个开关。
GRAIN = True

SRC = os.path.join("..", "素材")
# 楷体 simkai.ttf。按常见位置依次找，找不到就用第一个（烧字幕时会报字体缺失）。
FONTS = next((p for p in (os.path.join("..", "fonts"),
                          os.path.join("..", "..", "fonts"),
                          os.path.join("..", "..", "build", "fonts"))
              if os.path.isdir(p)), os.path.join("..", "fonts"))

# ================= 运动：运镜还是静帧 =================
# 全片默认。任何一镜都可以写 motion="static" / "kenburns" 单独覆盖。
#   "kenburns"  每张图做缓推缓摇（这一支、以及此前所有交付的片子）
#   "static"    一镜一张静止的画，画面完全不动，节奏全靠转场和声音
#
# **静帧不是"把 z 写成一样"就完了，它要显式声明。** 理由是这条流水线最贵的一个
# 错误就是"写了位移却没给足缩放 = 原地微缩放"——参数表上完全看不出来，
# 一个系列里拦下过十一镜。如果允许"z 起止相同"隐式表示静帧，那个 bug 从此
# 变成一个合法配置，check 再也拦不住它。所以：
#   - 标了 static 却写了行程   -> check_moves 报错
#   - 标了 kenburns 却起止全同 -> check_moves 报错（这正是那个 bug 的样子）
#   - 渲完 motion 命令反过来验：运镜镜首尾帧差要 >= MOTION_MIN，
#     静帧镜要 <= MOTION_STATIC_MAX（**静帧镜"在动"和运镜镜"不动"一样是错**）
#
# 静帧模式连带三件事（见 SKILL.md「静帧模式」）：素材分辨率门槛从 1.5 倍降到
# 1.0 倍、每镜停留要缩短、粒子层从加分项变成全片唯一的真运动。
MOTION = "kenburns"
MOTION_MIN = 4.0            # 运镜镜的下限：渲出来的首尾帧平均绝对差（可觉察差约 2~3 级）
MOTION_STATIC_MAX = 0.6     # 静帧镜的上限：真静止应该接近 0，留一点编码噪声的余量

# ================= 配乐：生成 / 公版 / 没有 =================
#   "generated"      ChatCut submit_music 生成的（此前每一支都是）。
#                    封顶实测 180~245s 随机、提示词管不住，所以片长要倒着从 180s 排。
#   "public_domain"  自己找来的公版或开放授权录音。全曲通常远长于片长，切入余地不是
#                    问题；换来的是三件生成配乐没有的麻烦，见 references/music.md：
#                    **录音权和作品权是两回事**（贝多芬是公版，某乐团 2010 年的录音不是）、
#                    历史转录有底噪和带宽损失、真曲子有乐句和终止式，乱切听得出来。
#                    走这一路 MUSIC_CREDIT 必须填全，check 会拦。
#   "library"        **从素材库里挑一条已有的**。对音乐要求不高的片子（书评、故事、
#                    冷知识、科普）**先走这一条** —— 全程有旁白盖着，音乐只在句间的
#                    缝里露出来，库里现成的多半够用，而生成一条要花额度、
#                    且封顶 180~245s 随机不可控。
#                    做法：`python music_index.py find --dur <片长> --mode story`，
#                    挑 2~3 条给用户听，定了复制成 素材/00_music_main.mp3，
#                    最后回去 `add --used` 记一笔。授权上等同 generated（自己生成的）。
#   "none"           不要背景音乐。片子只剩音效（和诵读，如果有）。
#                    这不是"少做一步"，它会改归一化策略，见 norm_mode()。
#   "song"           **MV**：一条带演唱的成品歌，歌是主角不是垫底。
#                    它改的东西比另外三种都多：MUSIC_IN 恒为 0（歌有自己的头，
#                    不存在"挑切入点"）、不做 5 秒硬淡出（歌有自己的收尾）、
#                    MUSIC_GAIN 不该压（压了就成了"背景音乐"）、
#                    **片长必须等于歌长**。见 song_mode() 和 check_sung()。
MUSIC_MODE = "generated"
MUSIC = os.path.join(SRC, "00_music_main.mp3")      # MUSIC_MODE="none" 时整条链路忽略它
MUSIC_GAIN = -10.0
# 公版录音必填。不是形式主义：CC-BY 要求署名，而"我以为它是公版"是这条路上
# 唯一一个交付之后才会爆的错误。credits 命令会把它写进素材来源表。
MUSIC_CREDIT = dict(work="", performer="", source="", license="", url="")
# `pick` 的打分窗口里**唯一要逐支声明的**：情绪核心是哪几镜（1 起）。
# 其余窗口（长转场、成片中点、末句、诗文页、片尾淡出）都由时间轴推出来。
MUSIC_KEY_SHOTS = []
# MUSIC_MODE="library" 时填库里的文件名。**记它是为了两件事**：
# 交付时说清这条曲子是复用的；以及做完之后回去 `music_index.py add --used`，
# 否则下一支查库时不知道它已经用过了 —— **同一个系列里重复用同一条，观众记得住**。
MUSIC_FROM_LIBRARY = ""

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

# ================= MV：唱句表 =================
# 只有 MUSIC_MODE="song" 时才填。(起, 止, 文本)，**整块从 lyric_sync.py 的输出粘过来**，
# 不要手敲：手敲的时间戳和真实起音差 100ms 级，而 MV 里这 100ms 是看得出来的。
#
# 填了之后 LINES 里的正文就从这里来（见下面 LINES 的拼法），
# 于是"字幕时间"和"唱腔时间"在这份文件里**只有一个来源**，不可能改歪一处。
SUNG = []
SUNG_XF_PAD = 0.10      # 转场两头各留这么多，不许贴着唱句的头尾

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

# MV 模式：正文由 SUNG 表生成，覆盖上面那张手排的表。
# **不是"追加"是"覆盖"** —— 留着上一支的句子和唱句混在一起，
# check 会同时按两套时间轴判，报出一堆看不懂的冲突。
if SUNG:
    LINES = [l for l in LINES if l[3] != "M"] + [(a, b, t, "M") for a, b, t in SUNG]

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

# ---- 片名竖排 ----
# **横排片名要占满画宽，而画宽上很难找到一条干净的底。**
# 《天净沙·秋思》的开场是一棵枯藤老树，枝子横穿整幅：量下来 y 从 200 到 1400
# 每隔 100 取一次，836px 宽的标题带 10 分位始终在 32~58 之间（墨色字要差 50 级），
# **没有一个 y 放得下**。而右侧那条给正文留的素纸，同一时刻 10 分位 180~232。
#
# 所以竖排不是"风格选择"，是**浅底纸本片子的默认解**：片名和正文用同一条竖带，
# 既保证认得出，又正好是中国画题款本来的样子（题在右，落款在其左下，字更小）。
# 横排片名只在"画面上部确有大片空"时才用（《雨霖铃》那种暗调实拍多半有）。
TITLE_VERTICAL = False
TITLE_FS_V = 80                      # 竖排片名字号
TITLE_X_V, TITLE_TOP_V = SUB_X, SUB_TOP
TITLE_SIG_FS_V, TITLE_SIG_X_V = 46, 864      # 作者：左边一列，字更小，起点更低
TITLE_SIG_DROP = 3                   # 作者从片名的第几个字往下起（题款的样子）

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

# ================= 素材来源：任务书生成 / 自己找 =================
#   "generated"  写一份自包含的出图任务书交给用户去生成（此前每一支都是，
#                做法见 references/sourcing.md）。构图可以按需要定制，
#                所以"右侧留白/留暗"这类硬要求提得出来。
#   "found"      从公版博物馆开放数据、图库里找现成的。**流水线的方向反过来**：
#                不再是"分镜提要求、图去满足"，而是"先看有什么图、分镜跟着图走"，
#                因为一张宋画的留白位置是不可能改的。连带三件事：
#                  - 每张必须登记来源与授权（CREDITS），check 会拦，credits 命令导出
#                  - 裁切参数（zoom/cx/cy）变成主要工作量，而 zoom 会吃掉有效分辨率
#                  - 字幕极性多半要一镜一议，FLIP_SHOTS 会真的用上
IMG_SOURCE = "generated"
# ---- 出图尺寸按运动反推，不要写死一个"越大越好"的数 ----
#
# **实测的拐点（真原生图库照片，一密一疏，两条曲线几乎重合）：**
#   pp（源像素/输出像素）  0.70   0.85   1.00   1.20   1.30   1.45
#   成片顶层细节            67%    83%    92%    98%    99%   100%
# 拐点在 1.2~1.3，**和画面类型无关** —— 密和疏差不到两个百分点。
# 所以尺寸只由**运动**决定；画面类型改的是"最后几个百分点值不值得买"。
#
# 静帧那一档不要余量：pp=1.0 时裁出来的窗正好等于输出尺寸，是**恒等重采样**，
# 根本不过滤波器。运镜要 1.2 是因为 zoompan 每帧都在非整数倍率上重采样。
#
# **上限是 PREP，不是钱包。** prep 第一步就 scale 到 PREP，源图短边超过 PREP
# 短边的部分在流水线第一步就被丢掉 —— 2896 交给流水线的实际是 2160，
# 白付 26% 的线性分辨率。budget 命令会把超出的部分直接标出来。
PP_STATIC = 1.00        # 静帧镜：恒等重采样，不需要余量
PP_KENBURNS = 1.20      # 运镜镜：实测 98%，性价比最高的一档
PP_DETAIL = 1.30        # 细节就是内容的那几镜：实测 99%
DETAIL_SHOTS = set()    # 镜号(1 起)。工笔的织物、人脸特写、市井细节、封面那一类
# IMG_SOURCE="found" 时逐张填，键是 CLIPS 里的文件名。五项都不能空。
# 例：CREDITS = {"img01.png": dict(
#         title="谿山行旅图（局部）", holder="国立故宫博物院",
#         source="Open Data 專區", license="公有领域",
#         url="https://theme.npm.edu.tw/opendata/...")}
CREDITS = {}


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


def motion_of(n):
    """镜 n(1 起) 是运镜还是静帧。逐镜的 motion= 覆盖全局 MOTION。"""
    return SHOTS[n - 1].get("motion", MOTION)


def is_static(n):
    return motion_of(n) == "static"


def all_static():
    return all(is_static(n) for n in range(1, len(SHOTS) + 1))


OUT_SHORT = min(W, H)           # 成片短边（竖版 1080 宽 / 横版 1080 高，都是 1080）
PREP_SHORT = min(PREP)          # 流水线的实际天花板：prep 第一步就 scale 到这里


# 实测曲线：pp -> 成片保住的顶层细节。两张真原生图库照片（一密一疏）的平均，
# 同一个镜头(z 1.16->1.46)走完整流水线，量落幅帧的最高倍频程 RMS。
# 两条曲线几乎重合（差不到 2 个百分点）——**拐点和画面类型无关**。
_PP_CURVE = [(0.70, 68), (0.85, 83), (1.00, 92), (1.20, 98), (1.30, 99), (1.45, 100)]


def detail_pct(pp):
    """按实测曲线插值。超出量程就夹住，不外推。"""
    if pp <= _PP_CURVE[0][0]:
        return _PP_CURVE[0][1]
    for (a, va), (b, vb) in zip(_PP_CURVE, _PP_CURVE[1:]):
        if pp <= b:
            return va + (vb - va) * (pp - a) / (b - a)
    return 100.0


def pp_target(n):
    """镜 n(1 起) 要的源像素/输出像素。见 PP_* 处的实测曲线。"""
    if is_static(n):
        return PP_STATIC
    return PP_DETAIL if n in DETAIL_SHOTS else PP_KENBURNS


def required_native(n):
    """镜 n 要的**源图短边**（裁成成片比例之后的）。

    = pp目标 x 这一镜最紧的 z x 成片短边。静帧用起幅 z（它没有别的 z）。

    返回 (需要多少, 有没有被 PREP 卡住)。**不在这里 clamp 到 PREP** ——
    卡住是一个要被看见的事实：它说明这一镜的 z 太大，
    再买更大的图也没用，得改运镜或者抬 PREP。
    """
    s = SHOTS[n - 1]
    z = s["z"][0] if is_static(n) else max(s["z"])
    need = pp_target(n) * z * OUT_SHORT
    return need, need > PREP_SHORT + 1


def budget():
    """出图之前跑：反推每一镜要多大的图，直接抄进出图任务书。

    **这条流水线以前的做法是给所有镜头一个统一的 2896x5152**，那是两头错的：
    对缓推镜多买了一倍多的像素，对大推镜又不够（而 flat 判据还会放行）。
    尺寸是算得出来的，就不该拍脑袋。
    """
    print("")
    print("=== 出图尺寸（按每镜的运动反推）===")
    print("   判据 pp = 源像素/输出像素。实测：pp 1.0→92%，1.2→98%，1.3→99% 的顶层细节")
    print("   静帧 %.2f（恒等重采样，不需要余量） / 运镜 %.2f / 细节镜 %.2f"
          % (PP_STATIC, PP_KENBURNS, PP_DETAIL))
    print("   **流水线天花板 PREP 短边 = %d**，要得再大也会在 prep 第一步被丢掉"
          % PREP_SHORT)
    print("")
    rows, capped = [], []
    for n, s in enumerate(SHOTS, 1):
        need, over = required_native(n)
        z = s["z"][0] if is_static(n) else max(s["z"])
        ask = min(need, PREP_SHORT)
        # 出图任务书里要写的是**生成尺寸**。CLIPS 的 zoom 是事后再裁一刀，
        # 要把它折回去，否则按需要量出图、裁完就不够了。
        zoom = CLIPS[n - 1]["zoom"] if n <= len(CLIPS) else 1.0
        gen = ask * zoom
        rows.append((n, "静帧" if is_static(n) else "运镜", z, pp_target(n),
                     need, ask, gen, zoom))
        if over:
            capped.append(n)
    for n, how, z, pp, need, ask, gen, zoom in rows:
        note = ""
        if need > PREP_SHORT + 1:
            note = "  << 被 PREP(%d) 卡住：买再大也没用，要么降 z 要么抬 PREP" % PREP_SHORT
        elif n in DETAIL_SHOTS:
            note = "  (细节镜)"
        print("  镜%-3d %s  z最紧 %.2f  pp %.2f  需要短边 %4.0f  出图 %4.0f x %4.0f%s"
              % (n, how, z, pp, need, gen, gen * 16 / 9.0, note))
    # 分档汇总：出图任务书按档写，比逐镜写好用
    tiers = {}
    for n, how, z, pp, need, ask, gen, zoom in rows:
        # **向上取整，不能四舍五入** —— 1737 舍成 1700 就比需求还小，
        # 而这张表是直接抄进出图任务书的，舍错了整批图都不够用。
        k = int(-(-gen // 100) * 100)
        tiers.setdefault(k, []).append(n)
    print("")
    print("=== 分档（出图任务书按这个写）===")
    for k in sorted(tiers, reverse=True):
        ns = tiers[k]
        print("  %4d x %4d   %2d 镜：%s" % (k, k * 16 / 9.0, len(ns),
                                            ", ".join(str(i) for i in ns)))
    old = 2896
    tot_new = sum(min(r[6], PREP_SHORT * r[7]) ** 2 * 16 / 9.0 for r in rows)
    tot_old = len(rows) * old ** 2 * 16 / 9.0
    print("")
    print("  合计像素相对「统一 2896x5152」： %.0f%%（省 %.0f%%）"
          % (100.0 * tot_new / tot_old, 100 * (1 - tot_new / tot_old)))
    if capped:
        print("")
        print("  !! 镜 %s 的 z 已经超出 PREP 的能力（需要 > %d）。"
              % (", ".join(str(i) for i in capped), PREP_SHORT))
        print("     这不是素材的问题，是**流水线的天花板**：prep 把源图压到 %d，"
              "再大的源图也补不回来。降 z、改静帧、或者把 PREP 抬上去。" % PREP_SHORT)
    print("")
    print("  注意：上面是**裁成成片比例之后**的短边要求，已按 CLIPS 的 zoom 折回。")
    print("  如果生成器出不了 9:16，还要再除以裁切损失（出 2:3 裁 9:16 只剩 84%）。")


def music_on():
    return MUSIC_MODE != "none"


def song_mode():
    """MV：音频是一条带演唱的成品歌。**歌不是垫在下面的，是片子的骨架。**"""
    return MUSIC_MODE == "song"


def music_dur():
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", MUSIC], capture_output=True, text=True)
    try:
        return float(p.stdout.strip())
    except ValueError:
        return None


def sung_spans():
    return [(a, b) for a, b, _ in SUNG]


def norm_mode():
    """成片的响度归一策略 —— **没有音乐时不能照抄 −15 LUFS**。

    loudnorm 的整合响度是**带门限**的：−70 LUFS 绝对门 + 相对门把静音段整个剔掉，
    量到的其实是"出声的那些段落的平均"。片子里有连续的音乐底（或连续的旁白）时，
    这正是我们要的，归一到 −15 就是平台标准。

    但如果音频只剩几条稀疏的音效——比如全片 137s 只有 5 条共 40s 的环境声——
    门限会把那 97s 的静音全剔掉，于是"整合响度"变成了那几条音效自己的响度，
    归一化会把一层本该若有若无的蝉声硬抬到 −15 LUFS，比原本的意图响 15~20 dB。
    音效表里逐条写的目标响度是**绝对值**，归一化会把它们全部作废。

    所以：有音乐或有诵读 -> 归一（TARGET_I 有意义）；只有音效 -> 不归一，
    只过一道限幅，让 SFX 表里的目标响度就是成片上的响度。
    """
    if music_on() or VO:
        return "loudnorm"
    return "absolute"


def audio_sources():
    """成片到底有没有声音。三样全空时 pass_c 会出一条**无音轨**的片子。"""
    n = 0
    if music_on():
        n += 1
    n += len(VO)
    n += sum(1 for f, *_ in SFX if os.path.exists(os.path.join(SRC, f)))
    return n


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


def travel_of(n):
    """镜 n(1 起) 想走的行程（横纵之和，占画面的比例）。"""
    s = SHOTS[n - 1]
    return abs(s["f1"][0] - s["f0"][0]) + abs(s["f1"][1] - s["f0"][1])


def still_by_design(n, thr=0.05):
    """这一镜是不是**有意**几乎不动 —— 行程极小但仍然标着 kenburns。

    这类镜头（「竟无语凝噎」「问君能有几多愁」那种"说不出来/停住"的句子）
    落幅平坦度必然偏高，那是对的，不该报警。
    """
    return not is_static(n) and travel_of(n) < thr


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
        elif is_static(n):
            # 静帧镜的这两个数**换了含义**：平坦行原本是在问"落幅停在这里会不会
            # 像静止"，而静帧镜本来就静止，那个问题不成立。剩下有意义的只有一个：
            # 这张画停 %.1f 秒够不够看。所以只在整帧极差很低时提示，且只是提示。
            if rng < 25:
                note = ("  << 静帧，整帧极差只有 %.0f —— 这张要停 %.1fs，会很空"
                        % (rng, SHOTS[n - 1]["dur"]))
            else:
                note = "  (静帧，平坦行不适用)"
        elif still_by_design(n):
            # **不要把"哪一镜有意不动"写死成镜号。** 第一版写的是
            # `n == 6` 配《雨霖铃》「竟无语凝噎」那句，换一支就在错的镜头上
            # 打错的文本。行程本来就在参数里，推出来即可。
            note = "  (行程只有 %.0f%%，有意几乎不动，偏高是对的)" % (travel_of(n) * 100)
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


def check_sung(shots=None, sung=None):
    """MV 专用自检。**唱腔是时间轴的主人，画和字都得让着它。**

    三条，都是量得出来的：

    一、**片长必须等于歌长。** 短了歌被切断，长了片尾挂一段静音。
        诗词模式里片长是自由的（配乐可以任意切入、任意淡出），MV 里不是 ——
        这是 song 模式和另外三种最根本的区别。

    二、**转场整段不许压在唱句上。** 注意是"整段"不是"中点"：
        上面 check_timeline 里那条通用的检查只看转场中心 ±0.3s，
        而一个 1.2 秒的溶解实际横跨 c±0.6 —— 拿中心判会漏掉两头。
        MV 里画换到一半而人还在唱同一句，字和画一起断，最难看。
        实测这条最咬人：《断肠人在天涯》五句之间的空档只有 0.15~0.96s，
        默认的 1.2s 溶解**一处都放不下**，必须按最窄的空档压到 0.6 或改硬切。

    三、**一句唱腔不许跨镜。** 二成立时它自动成立，单独列出来是因为
        报错信息不一样：跨镜要改的是分镜，不是转场时长。

    `shots` / `sung` 只有 selftest 才传，正常调用读全局；传了就不比歌长
    （selftest 造的是一条 28 秒的假时间轴，拿真歌去比必然误报）。
    """
    S, U = (shots if shots is not None else SHOTS), (sung if sung is not None else SUNG)
    if not U:
        return []
    U = [(u[0], u[1]) for u in U]           # SUNG 是三元组，selftest 传的是二元组
    bad = []
    _xf = lambda i: S[i].get("xf", XFADE)
    total = sum(s["dur"] for s in S) - sum(_xf(i) for i in range(len(S) - 1))
    st, t = [], 0.0
    for i, s in enumerate(S):
        st.append(t); t += s["dur"] - _xf(i)
    if shots is None and song_mode() and os.path.exists(MUSIC):
        md = music_dur()
        if md is not None and abs(md - total) > 0.05:
            bad.append("片长 %.2fs 和歌长 %.2fs 差 %+.2fs —— MV 里这两个必须相等"
                       % (total, md, total - md))
    for i in range(len(S) - 1):
        c = st[i] + S[i]["dur"] - _xf(i) / 2
        a, b = c - _xf(i) / 2 - SUNG_XF_PAD, c + _xf(i) / 2 + SUNG_XF_PAD
        for k, (u0, u1) in enumerate(U, 1):
            if a < u1 and b > u0:
                bad.append("镜 %d→%d 的转场覆盖 %.2f~%.2fs，压在第 %d 句唱腔"
                           "(%.2f~%.2fs)上 —— 把 xf 压到 %.2fs 以内，或者挪分镜"
                           % (i + 1, i + 2, a, b, k, u0, u1,
                              max(0.0, _xf(i) - 2 * max(b - u0, u1 - a))))
    for k, (u0, u1) in enumerate(U, 1):
        n0 = max(i for i, s in enumerate(st) if u0 >= s - 1e-6)
        n1 = max(i for i, s in enumerate(st) if u1 >= s - 1e-6)
        if n0 != n1:
            bad.append("第 %d 句唱腔(%.2f~%.2fs)横跨镜 %d 和镜 %d —— "
                       "一句唱完之前不能换镜，改分镜的 dur" % (k, u0, u1, n0 + 1, n1 + 1))
    return bad


def selftest_sung():
    """造两个错，两条都必须报出来。**只验"现在通过"等于没验。**"""
    # 镜起点 0 / 8.8 / 18.2，转场覆盖 8.8~10.0 和 18.2~18.8（再各留 0.1 的余量）
    shots = [dict(dur=10.0), dict(dur=10.0, xf=0.6), dict(dur=10.0)]
    ok = [(1.0, 8.5), (11.0, 17.9)]                 # 两处换镜都落在空档里
    if check_sung(shots, ok):
        print("!! selftest_sung: 正常的排法被误报了")
        return
    if not any("压在" in b for b in check_sung(shots, [(1.0, 8.75), (11.0, 17.9)])):
        print("!! selftest_sung: 转场压在唱句上没有报出来")
        return
    if not any("横跨" in b for b in check_sung(shots, [(1.0, 8.5), (8.6, 12.0)])):
        print("!! selftest_sung: 唱句跨镜没有报出来")
        return
    print("自测(唱腔): 正常排法不报，压唱句和跨镜都报得出来。")


def check_paper():
    """纸本画种 → 写实要翻的那五处，代码这边只拦得住三处，就把这三处拦住。

    技能文档里那张「纸本 vs 暗调写实」的表列了五处要翻：字幕极性、scrim、
    淡入淡出色、vignette/颗粒、出图任务书的留白还是留暗。
    **前两处和最后一处代码管不了**（极性本来就是配置项，任务书在文档里），
    但淡场色、vignette、颗粒这三处是纯参数，照抄上一支就会错，
    而且错了在参数表上一点看不出来 —— 正是该由 check 兜住的那一类。

    只报提示不拦：这三样都是**看得见**的错（片头闪一下黑、纸面发灰），
    不像留白留暗那样要到交付才发现。拦死了反而挡住有意为之的例外。
    """
    warn = []
    if POLARITY == "dark_on_light":       # 浅底墨字 = 纸本
        if GRAIN:
            warn.append("纸本画种还开着颗粒(GRAIN=True) —— 纸自己有纤维纹理，"
                        "叠噪声上去就是脏。改成 GRAIN=False")
        if VIGNETTE:
            warn.append("纸本画种还开着 vignette(%s) —— 四角压暗在纸上是"
                        "「这张纸脏了」，不是「有氛围」" % VIGNETTE)
        if FADE_COLOR != "white":
            warn.append("纸本画种的淡入淡出用的是 %s 场 —— 浅底片子首尾闪黑，"
                        "改成 white" % FADE_COLOR)
    else:                                  # 暗调写实
        if not GRAIN:
            warn.append("暗调写实关掉了颗粒 —— 大片暮色容易出色带，"
                        "而且 AI 生成的实拍质感过分干净。确认是有意的")
        if FADE_COLOR == "white":
            warn.append("暗调片子用白场淡入淡出 —— 首尾会闪白，改成 black")
    return warn


def selftest_paper():
    """回归：把三处参数翻到画种的反面，检查必须逐条报出来。"""
    global POLARITY, GRAIN, VIGNETTE, FADE_COLOR
    kp, kg, kv, kf = POLARITY, GRAIN, VIGNETTE, FADE_COLOR
    base = len(check_paper())
    POLARITY, GRAIN, VIGNETTE, FADE_COLOR = "dark_on_light", True, "vignette=PI/5", "black"
    n = len(check_paper())
    POLARITY, GRAIN, VIGNETTE, FADE_COLOR = kp, kg, kv, kf
    print("回归自测: 纸本画种照抄了写实的颗粒/vignette/黑场 —— 报 %d 条 —— %s"
          % (n, "对" if n >= 3 else "**检查失效了**"))
    return n >= 3


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
            # **竖排片名也要验。** 横排片名居中、离操作栏远，所以原来这里
            # 直接跳过所有非正文行；竖排之后片名和正文在同一条竖带上，
            # 跳过等于把新加的那两行放进了检查的盲区
            if TITLE_VERTICAL and sty in ("T", "TS"):
                fs = TITLE_FS_V if sty == "T" else TITLE_SIG_FS_V
                x = TITLE_X_V if sty == "T" else TITLE_SIG_X_V
                y0 = TITLE_TOP_V + (0 if sty == "T" else TITLE_SIG_DROP * TITLE_FS_V)
                hit("竖排%s『%s』" % ("片名" if sty == "T" else "落款", txt),
                    int(x - fs / 2 - 6), int(x + fs / 2 + 6), y0 - 6,
                    y0 + len(txt) * fs + 6)
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

        # ---- 运动方式和参数必须**互相印证** ----
        # 静帧和运镜在参数上只差"起止一不一样"，而"起止不小心写成一样"正是
        # 这条流水线最贵的那个 bug（写了位移没给足缩放 = 原地微缩放）长出来的样子。
        # 所以两边都要拦：声明的和参数说的对不上就报错，不去猜哪个是真的。
        m = motion_of(i)
        moving = want > 1e-6 or abs(z1 - z0) > 1e-6
        if m not in ("kenburns", "static"):
            bad.append("镜 %d 的 motion=%r 不认识，只能是 'kenburns' 或 'static'" % (i, m))
        elif m == "static" and moving:
            bad.append("镜 %d 标了 static 却写了行程 (z %.2f→%.2f, f %s→%s) —— "
                       "静帧镜的 z 和 f 起止必须完全一致；想要固定的取景就把两端写成同一个值"
                       % (i, z0, z1, s["f0"], s["f1"]))
        elif m == "kenburns" and not moving:
            bad.append("镜 %d 标了 kenburns 却起止完全一样，渲出来就是一张静帧 —— "
                       "要么给它行程，要么老实标 motion='static'" % i)

        if want > can + 1e-6:
            bad.append("镜 %d 想走 %.0f%% 行程，但 z 最大只到 %.2f，实际只能走 %.0f%% "
                       "(需要 z>=%.2f)" % (i, want * 100, zmax, can * 100,
                                           1 / max(1e-6, 1 - want)))
    return bad


def selftest_moves():
    """回归：把每一类错误各造一个，检查必须报警。

    和 selftest_safe() 是同一个理由 —— check_moves 里新加的两条是**声明与参数
    对不上**才报警的，很容易写成一条永远不报警的检查（比如把 moving 判反、
    或者把 elif 写成互斥分支之后两边都够不着）。只验"现在通过"等于没验。
    """
    if not SHOTS:
        return True
    keep = [dict(s) for s in SHOTS]
    base = len(check_moves())

    def case(name, i, patch):
        SHOTS[i - 1] = dict(keep[i - 1], **patch)
        n = len(check_moves())
        SHOTS[i - 1] = dict(keep[i - 1])
        print("回归自测: %-24s 多报 %d 条 —— %s"
              % (name, n - base, "对" if n > base else "**检查失效了**"))
        return n > base

    moving = next((i for i, s in enumerate(SHOTS, 1)
                   if abs(s["f1"][0] - s["f0"][0]) + abs(s["f1"][1] - s["f0"][1]) > 1e-6
                   or abs(s["z"][1] - s["z"][0]) > 1e-6), None)
    ok = []
    if moving:
        ok.append(case("有行程的镜标成 static", moving, dict(motion="static")))
    z, f = keep[0]["z"][0], keep[0]["f0"]
    ok.append(case("原地不动的镜标成 kenburns", 1,
                   dict(motion="kenburns", z=(z, z), f0=f, f1=f)))
    ok.append(case("motion 写错字", 1, dict(motion="ken_burns")))
    print("          当前配置 %d 条 —— %s" % (base, "对" if base == 0 else "有问题要处理"))
    return all(ok) and len(check_moves()) == base


def check_fx():
    """粒子层的窗口不能跑到片长外，也不该压到不相干的镜头上。

    **叠加层"盖住了该盖的那一句"必须显式验。** 上一支踩过一次：
    星辉层的起点定得早了一点点，星星浮在大白天的河面上 ——
    参数上完全看不出来，只有抽静帧才发现。这里至少把窗口关系拦住。
    """
    bad, total = [], total_len()
    # **关掉的层（DUR<=0）整条跳过。** 不跳的话 RAIN_OUT >= RAIN_DUR 在
    # 0 >= 0 上成立，一个没有粒子的片子会被一条不适用的检查拦住。
    layers = [(n, t0, d) for n, t0, d in
              (("残雨", RAIN_T0, RAIN_DUR), ("落叶", LEAF_T0, LEAF_DUR)) if d > 0]
    if not layers:
        print("   粒子层：这一支没有")
    for name, t0, dur in layers:
        if t0 < 0 or t0 + dur > total + 1e-6:
            bad.append("%s层 %.1f~%.1fs 超出片长 %.1fs" % (name, t0, t0 + dur, total))
        print("   %s层 %.1f~%.1fs = 镜 %d 起，到镜 %d 收"
              % (name, t0, t0 + dur, shot_of(t0 + 0.05), shot_of(t0 + dur - 0.05)))
    if RAIN_DUR > 0 and RAIN_OUT >= RAIN_DUR:
        bad.append("残雨淡出起点 %.1f 超过了它自己的长度 %.1f" % (RAIN_OUT, RAIN_DUR))
    # 残雨必须在「骤雨初歇」四个字落下来之前就已经在淡出，也必须在那一句结束前收干净 ——
    # 雨还在下着而字说"初歇"，是这一支唯一一处画面能替字幕做事的地方，做反了就白做
    xie = [(s, e) for s, e, t, y in LINES if y == "M" and "骤雨初歇" in t] if RAIN_DUR > 0 else []
    for s, e in xie:
        if RAIN_T0 + RAIN_OUT > s:
            bad.append("残雨到 %.1fs 才开始淡出，晚于『骤雨初歇』出字(%.1fs)"
                       % (RAIN_T0 + RAIN_OUT, s))
        if RAIN_T0 + RAIN_DUR > e:
            bad.append("残雨到 %.1fs 才收干净，晚于『骤雨初歇』收字(%.1fs)"
                       % (RAIN_T0 + RAIN_DUR, e))
    # 落叶必须真的盖住「更那堪，冷落清秋节」那一句
    qiu = [(s, e) for s, e, t, y in LINES if y == "M" and "冷落清秋节" in t] if LEAF_DUR > 0 else []
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


def check_credits():
    """素材来源与授权的登记。**只对"自己找来的"素材是硬约束。**

    自己生成的图没有第三方权利问题，登记与否是记账；从博物馆开放数据、图库、
    公版录音里拿来的东西不一样 —— CC-BY 要求署名，"公有领域"对**作品**成立
    不等于对**某一次录音/某一张翻拍**成立（贝多芬是公版，某乐团 2010 年的录音不是）。
    而这类错误的特点是：成片、审核、发布全都不会拦，要到被投诉才知道。
    所以放在 check 里，缺一项就不让过。
    """
    bad = []
    need = ("title", "holder", "source", "license", "url")
    if IMG_SOURCE not in ("generated", "found"):
        bad.append("IMG_SOURCE=%r 不认识，只能是 'generated' 或 'found'" % IMG_SOURCE)
    elif IMG_SOURCE == "found":
        for c in CLIPS:
            e = CREDITS.get(c["src"])
            if not e:
                bad.append("素材 %s 没登记来源（IMG_SOURCE='found' 时每张都要）" % c["src"])
            else:
                miss = [k for k in need if not str(e.get(k, "")).strip()]
                if miss:
                    bad.append("素材 %s 的来源登记缺 %s" % (c["src"], "/".join(miss)))
    if MUSIC_MODE not in ("generated", "public_domain", "library", "none", "song"):
        bad.append("MUSIC_MODE=%r 不认识，只能是 "
                   "'generated' / 'public_domain' / 'library' / 'none' / 'song'"
                   % MUSIC_MODE)
    elif MUSIC_MODE == "song" and not MUSIC_CREDIT.get("source", "").strip():
        # MV 的歌是**别人的作品**（生成的也是一次可署名的产出）。
        # 不像配乐可以含糊过去 —— 演唱是片子的主体，来源说不清就不该发
        bad.append("MV 的 MUSIC_CREDIT 至少要填 source（歌从哪儿来、谁唱的、能不能用）")
    elif MUSIC_MODE == "library" and not str(MUSIC_FROM_LIBRARY).strip():
        bad.append("MUSIC_MODE='library' 却没填 MUSIC_FROM_LIBRARY —— "
                   "不记下用了库里哪一条，做完就没法回去 `add --used`，"
                   "下一支查库时会不知道它已经用过了")
    elif MUSIC_MODE == "public_domain":
        miss = [k for k in ("work", "performer", "source", "license", "url")
                if not str(MUSIC_CREDIT.get(k, "")).strip()]
        if miss:
            bad.append("公版配乐的 MUSIC_CREDIT 缺 %s —— **录音权和作品权是两回事**，"
                       "填不出来就说明这条录音的授权还没查清楚" % "/".join(miss))
    return bad


def selftest_credits():
    """回归：把登记抽掉，检查必须报警。"""
    global IMG_SOURCE, MUSIC_MODE, CREDITS, MUSIC_CREDIT
    ki, km, kc, kmc = IMG_SOURCE, MUSIC_MODE, CREDITS, MUSIC_CREDIT
    base = len(check_credits())
    IMG_SOURCE, CREDITS = "found", {}
    a = len(check_credits()) > base
    IMG_SOURCE, CREDITS = ki, kc
    MUSIC_MODE, MUSIC_CREDIT = "public_domain", dict(work="", performer="",
                                                     source="", license="", url="")
    b = len(check_credits()) > base
    MUSIC_MODE, MUSIC_CREDIT = km, kmc
    print("回归自测: 素材标 found 但没登记来源 —— %s" % ("对" if a else "**检查失效了**"))
    print("          配乐标 public_domain 但没填授权 —— %s" % ("对" if b else "**检查失效了**"))
    return a and b


def check_music():
    """配乐相关的检查。三种来源要查的东西不一样。"""
    bad, warn = [], []
    total = total_len()
    if not music_on():
        n = sum(1 for f, *_ in SFX if os.path.exists(os.path.join(SRC, f)))
        print("配乐: 无（MUSIC_MODE='none'）—— 音频只剩 %d 条音效%s"
              % (n, " + %d 条诵读" % len(VO) if VO else ""))
        if norm_mode() == "absolute":
            print("      **不做响度归一**：整合响度会被稀疏的音效带偏，"
                  "归一等于把 SFX 表里的目标响度全部作废（见 norm_mode()）")
        if audio_sources() == 0:
            warn.append("这一支**完全没有声音** —— 成片会是一条无音轨的 mp4。"
                        "如果不是有意的，检查 MUSIC_MODE / SFX / VO")
        return bad, warn
    if not os.path.exists(MUSIC):
        warn.append("音乐还没就位")
        return bad, warn
    if song_mode():
        # MV：歌就是骨架，没有"切入点"可挑，也不该被压到背景里去
        md = music_dur()
        print("MV: 歌 %.2fs，片长 %.2fs，%d 句唱词%s"
              % (md or -1, total, len(SUNG), "" if SUNG else "  << SUNG 表还是空的"))
        if not SUNG:
            bad.append("MUSIC_MODE='song' 但 SUNG 表是空的 —— "
                       "先跑 `lyric_sync.py snap` 出唱句表，别手敲")
        if MUSIC_IN:
            bad.append("MV 里 MUSIC_IN 必须是 0（现在是 %.1f）：歌有自己的头，"
                       "从中间切进去就不是这首歌了" % MUSIC_IN)
        if MUSIC_GAIN < -3.0:
            bad.append("MV 里 MUSIC_GAIN=%.1f dB 把歌压成了背景音 —— "
                       "唱是主角，用 0，响度交给成片归一(TARGET_I)" % MUSIC_GAIN)
        if VO:
            warn.append("MV 里还挂着 %d 条诵读 —— 念白压在演唱上，确认是有意的" % len(VO))
        return bad, warn
    if MUSIC_IN is None:
        # 判据用 `is None` 而不是 `<= 0`：上一支 maximin 真的选出了 0.0，
        # 拿 0 当"还没选"的哨兵会把一个合法结果误报成占位值。
        warn.append("MUSIC_IN 还没定 —— 跑 `python make_v.py pick` 用 maximin 选切入点")
        return bad, warn
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", MUSIC],
                       capture_output=True, text=True)
    try:
        mdur = float(p.stdout.strip())
    except ValueError:
        warn.append("读不出音乐时长")
        return bad, warn
    need = MUSIC_IN + total
    if need > mdur + 1e-3:
        bad.append("音乐不够长: 从 %.1fs 切入需要到 %.1fs，全曲只有 %.1fs"
                   % (MUSIC_IN, need, mdur))
    else:
        print("配乐(%s): 全曲 %.1fs，从 %.1fs 切入，用到 %.1fs，余 %.1fs"
              % ({"generated": "生成", "library": "库里挑的"}.get(MUSIC_MODE, "公版"),
                 mdur, MUSIC_IN, need, mdur - need))
    if MUSIC_MODE == "generated":
        # 生成配乐的封顶实测 180~245s 随机、提示词管不住，所以余地是稀缺资源
        if mdur < total * 1.6:
            warn.append("音乐只比片长多 %.0fs（不到片长的 0.6 倍），切入点挑得比较紧"
                        % (mdur - total))
    else:
        # 公版录音通常远长于片长，余地不是问题；要提醒的是另外两件事
        warn.append("公版录音：`pick` 只会挑响度，**挑不出乐句边界** —— "
                    "切入点定完必须听一遍首尾，另外跑 `mquality` 看底噪和带宽")
    return bad, warn


def check_timeline():
    total, cuts, starts = total_len(), cut_points(), shot_starts()
    bad, warn = [], []
    sung = set(sung_spans())
    for st, en, txt, sty in LINES:
        if sty == "M" and (st, en) not in sung:
            # 分隔符不上屏，也就不用读 —— 不剔掉的话每句白得 0.45s 的虚假余量
            need = len(txt.replace(SUB_SEP, "")) * READ_PER_CHAR + READ_BASE
            if en - st < need - 1e-6:
                bad.append("字幕『%s』只有 %.1fs，不足可读下限 %.1fs" % (txt, en - st, need))
        # **唱句不套可读下限。** 它的挂屏时间由唱腔定，不由"读得完"定：
        # 一句唱得快的四字（「夕阳西下」实测 5.6s）本来就够读，
        # 而套下限只会逼人去改一个改不了的东西 —— 歌已经录好了。
        # 唱句该验的是另一件事，在 check_sung() 里。
        if (st, en) in sung:
            # 通用的"转场中点 ±0.3s 不许碰字幕"在 MV 里**必然误报**：
            # 句间空档实测只有 0.40s，±0.3 的余量根本放不进去。
            # 换成 check_sung() 里按转场**整段**和唱句求交 —— 那条更严不更松
            # （通用规则只看中点，漏掉 1.2s 溶解伸出去的那两截）。
            continue
        for c in cuts:
            if st - 0.3 < c < en + 0.3:
                bad.append("转场 %.1fs 压到了字幕『%s』" % (c, txt))
        if en > total:
            bad.append("字幕『%s』结束于 %.1fs，超出片长 %.1fs" % (txt, en, total))
    # 诗文页默认挂在**最后几镜**上（诗词模式一直是这么排的）。
    # MV 是唯一的例外：片长被歌锁死，片尾没有 15 秒给诗文页 ——
    # 唯一放得下的地方是**前奏**（这一支前奏 16.0s，是全片唯一一段没人唱的长镜）。
    # 所以允许逐页写 shot=（1 起）显式指定挂在哪一镜，不写就还按老规矩。
    first_poem_shot = len(SHOTS) - len(POEMS)
    for k, p in enumerate(POEMS):
        s0 = starts[p.get("shot", first_poem_shot + k + 1) - 1]
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
    mb, mw = check_music()
    bad += mb; warn += mw
    warn += check_paper()
    bad += check_xfades()
    bad += check_moves()
    bad += check_resolution()
    bad += check_vo()
    bad += check_fx()
    bad += check_safe()
    bad += check_credits()
    bad += check_sung()
    ns = sum(1 for n in range(1, len(SHOTS) + 1) if is_static(n))
    print("\n片长 %.1fs (%d:%04.1f)  镜头 %d  字幕 %d 条  诗文页 %d 列  %dx%d"
          % (total, total // 60, total % 60, len(SHOTS), len(LINES),
             len(POEMS[0]["cols"]) if POEMS else 0, W, H))
    print("运动: %s（静帧 %d 镜 / 运镜 %d 镜）  配乐: %s  素材: %s"
          % ({"kenburns": "运镜", "static": "静帧"}.get(MOTION, MOTION),
             ns, len(SHOTS) - ns,
             {"generated": "生成", "public_domain": "公版", "library": "库里挑的",
              "none": "无", "song": "MV(带演唱的成品歌)"}.get(MUSIC_MODE),
             {"generated": "按任务书生成", "found": "自己找的"}.get(IMG_SOURCE)))
    print("镜头起点: " + "  ".join("%.1f" % s for s in starts))
    print("转场落点: " + "  ".join("%.1f" % c for c in cuts))
    print("转场时长: " + "  ".join("%.1f" % xf(i) for i in range(len(SHOTS) - 1)))
    print("正文停留: " + "  ".join("%.1f" % (e - s) for s, e, _, t in LINES if t == "M"))
    print("成片中点: %.1fs (镜 %d)" % (total / 2, shot_of(total / 2)))
    selftest_safe()
    selftest_moves()
    selftest_credits()
    selftest_paper()
    if SUNG:
        selftest_sung()
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
    这一支没有诵读，怕的就是某一处塌下去。

    公版录音多一件事：**真曲子有终止式**。生成的环境乐从哪儿切进去都行，
    一段真的演奏不是 —— 所以除了 maximin 的解，这里还会单独评一个
    "让曲子的自然收束正好落在片尾"的候选，把两个都打出来给人挑。
    乐句边界本身量不出来（和音色好坏是同一类事），最终要听。"""
    if not music_on():
        sys.exit("!!! MUSIC_MODE='none' —— 这一支不要背景音乐，没有切入点可挑")
    if song_mode():
        sys.exit("!!! MUSIC_MODE='song' —— MV 从歌的第 0 秒开始，没有切入点可挑。"
                 "要看唱句和换镜余地跑 `lyric_sync.py check`")
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
    n = len(SHOTS)
    # 成片上真正要紧的窗口。**开场不放进来**：片头那几秒只有标题在走、
    # 一个字幕都没有，曲子最弱的一段落在那儿反而合适。把开场让出来，
    # 剩下的才是真正不能塌的地方。
    #
    # **这些窗口是推导出来的，不是写死的镜号。** 第一版把《雨霖铃》的
    # starts[4] / starts[11] / starts[14] 直接写在这里，换一支只有 8 镜的片子
    # 就 IndexError —— 而它在"以下一般不用改"区里，等于埋了个换支必炸的雷。
    # 现在只有"情绪核心是哪几镜"要声明（MUSIC_KEY_SHOTS），其余全推。
    keys = []
    for i in MUSIC_KEY_SHOTS:
        if 1 <= i <= n:
            keys.append(("镜%d 核心" % i, starts[i - 1], min(9.0, SHOTS[i - 1]["dur"])))
    # 长转场 = 段落翻页，是全片少数几处**只有音乐**的地方，最不能塌
    for i in range(n - 1):
        if xf(i) >= 1.8:
            keys.append(("镜%d→%d 翻片" % (i + 1, i + 2),
                         max(0.0, starts[i + 1] - xf(i)), xf(i) + 4.0))
    keys.append(("中点", max(0.0, total / 2 - 3), 6.0))
    ms = [(a, b) for a, b, t, y in LINES if y == "M"]
    if ms:
        keys.append(("末句", ms[-1][0], min(10.0, ms[-1][1] - ms[-1][0] + 2.0)))
    if POEMS:
        keys.append(("诗文页", starts[n - len(POEMS)], 8.0))
    keys.append(("淡出", max(0.0, total - FADE_OUT - 1.0), FADE_OUT + 1.0))

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
    valleys(curve, off, total)
    if MUSIC_MODE == "public_domain":
        # 让曲子自己的收尾落在片尾。对真的演奏，这一条常常比多两分贝值钱：
        # 观众听得出来"曲子结束了"和"曲子被淡出掐掉了"的区别。
        tail = room
        ts = [win_avg(tail, a, d) for _, a, d in keys]
        print("\n另一个候选：切入点 %.1fs —— 曲子的自然收束正好落在片尾"
              % tail)
        print("   全片最弱落点 %.1f LUFS（maximin 那个是 %.1f，差 %.1f dB）"
              % (min(ts), mn, min(ts) - mn))
        print("   **这两个哪个对，要听。** 差在 2 dB 以内就选这个，"
              "让曲子有结尾比多两分贝值钱")
    print("\n把 MUSIC_IN 改成 %.1f" % off)


def valleys(curve, off, total, thr=-25.0, minlen=0.4):
    """把用到的这一段里低于 thr 的谷全列出来，并说清它落在片子的哪一镜。

    SKILL.md 里"拿到曲子先翻一遍低谷再决定要不要第二条候选"原来是句手工提醒 ——
    手工翻一遍要看几百行响度采样，翻漏是必然的。上一支的候选 A 在 121~130s 藏了
    1.7 秒近乎静音，是翻出来才弃用的；这一支的最低 −70.6 在 191s，是**结尾的
    自然收尾**、根本没用到。两者的区别决定要不要重新生成，所以值得自动化。
    """
    segs, cur = [], None
    for t, m in curve:
        if not (off <= t <= off + total):
            continue
        if m < thr:
            cur = (cur[0], t) if cur else (t, t)
        elif cur:
            segs.append(cur); cur = None
    if cur:
        segs.append(cur)
    segs = [s for s in segs if s[1] - s[0] >= minlen]
    print("")
    if not segs:
        print("   用到的这一段里没有低于 %.0f LUFS 的谷 —— 干净，不用发第二条候选" % thr)
        return
    print("   用到的这一段里有 %d 处低于 %.0f LUFS 的谷：" % (len(segs), thr))
    for a, b in segs:
        ta, tb = a - off, b - off               # 换算到片上时刻
        where = "片尾淡出里" if ta > total - FADE_OUT else "镜 %d" % shot_of(ta)
        print("      曲上 %6.1f~%6.1f  ->  片上 %6.1f~%6.1f (%.1fs)  %s"
              % (a, b, ta, tb, tb - ta, where))
    print("   落在片尾淡出里的不算问题；落在正片里的**中段 breakdown** 才是"
          "该换一条曲子的理由")


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


def band_rms(path, pre=None):
    """某个频段的 RMS。**分频段一律用 RMS，不用 LUFS。**

    理由是踩出来的：一条"江风"实测 −53.5 LUFS，看着像生成失败，其实能量几乎全在
    120Hz 以下，而 LUFS 的 K 加权对低频衰减极大 —— 仪表在说实话，但说的不是
    我们要问的那件事。同一个陷阱在公版录音上换个方向出现：老转录的高频没了，
    整体 LUFS 却可能很正常。
    """
    af = (pre + ",") if pre else ""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path,
                        "-af", af + "astats=metadata=1:reset=0", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.findall(r"RMS level dB:\s*(-?\d+\.\d+|-inf)", r.stderr)
    if not m:
        return None
    return -99.0 if m[-1] == "-inf" else float(m[-1])


def mquality():
    """判一条配乐能不能用。**公版录音必跑，生成的曲子跑一下也不亏。**

    生成的曲子交回来是干净的：单一来源、现代采样率、没有底噪。找来的录音不是，
    而它坏在三处，三处都不是听一耳朵能确定、却都能量：

    一、**底噪**。历史转录带着一层持续的嘶声。片子里音乐要压到 −25 dB 左右，
        底噪跟着一起被听见 —— 而它在安静的镜头里最明显，正好是诗词片最要紧的地方。
    二、**带宽**。1930 年代的转录高频到 5kHz 就没了。它不刺耳，但和现代生成的
        音效放在一起会显得"蒙"，而且**它自己盖不住自己的嘶声**。
    三、**头尾的静音和杂音**。抓轨常带 1~3 秒引子静音和唱针噪声，
        MUSIC_IN 是按曲子内容算的，前面多一段静音就会把切入点整体推偏。

    还有一件量不出来、必须交回用户的：这条演奏好不好、贴不贴这一支的气质。
    和"音色贴不贴"是同一类事。
    """
    if not music_on():
        sys.exit("!!! MUSIC_MODE='none' —— 这一支不要背景音乐")
    if not os.path.exists(MUSIC):
        sys.exit("!!! 音乐还没就位: " + MUSIC)
    total = total_len()
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration:stream=sample_rate,channels",
                        "-of", "default=nw=1", MUSIC],
                       capture_output=True, text=True)
    print("")
    print("=== %s ===" % MUSIC)
    print("   " + "  ".join(ln.strip() for ln in p.stdout.splitlines() if ln.strip()))

    # 响度曲线：整合响度 + 最安静的一刻（= 底噪的上界估计）
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", MUSIC,
                        "-af", "ebur128=framelog=info", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    curve = []
    for ln in r.stderr.splitlines():
        if "t:" in ln and " M:" in ln:
            try:
                t = float(ln.split("t:")[1].split()[0])
                m = float(ln.split(" M:")[1].split()[0])
                curve.append((t, m))
            except (IndexError, ValueError):
                pass
    integ = integrated_lufs(MUSIC)
    print("")
    print("   整合响度 %.1f LUFS" % (integ if integ is not None else -99))
    if curve:
        mdur = curve[-1][0]
        live = [(t, m) for t, m in curve if m > -70]
        floor = min(m for _, m in live) if live else -70.0
        print("   全曲 %.1fs（片长 %.1fs，余地 %.1fs）" % (mdur, total, mdur - total))
        print("   最安静的一刻 %.1f LUFS —— 这是**底噪的上界**：" % floor)
        gap = (integ - floor) if integ is not None else 0
        print("      离整合响度 %.0f dB。" % gap
              + ("生成的曲子一般 >40 dB；<30 dB 多半是有一层持续的嘶声，"
                 "音乐压到 −25 dB 之后它会跟着上来" if gap < 30 else "够干净"))

    # 分频段。四段而不是音效那三段 —— 要看的是 >8k 那一段还在不在
    print("")
    print("   分频段 RMS（判带宽，K 加权在这里会骗人，所以用 RMS）：")
    full = band_rms(MUSIC)
    for name, f in (("<120Hz", "lowpass=f=120"),
                    ("120-2k", "highpass=f=120,lowpass=f=2000"),
                    ("2k-8k", "highpass=f=2000,lowpass=f=8000"),
                    (">8kHz", "highpass=f=8000")):
        v = band_rms(MUSIC, f)
        rel = (v - full) if (v is not None and full is not None) else 0
        note = ""
        if name == ">8kHz" and rel < -40:
            note = "  << 8k 以上基本是空的 —— 老转录，和现代音效放一起会显得蒙"
        print("      %-7s %6.1f dB  (相对全带 %+.1f)%s" % (name, v if v else -99, rel, note))

    # 单声道判定：把左右相减，差信号接近无声就是两声道完全一样
    diff = band_rms(MUSIC, "pan=mono|c0=0.5*c0-0.5*c1")
    if diff is not None and full is not None:
        print("")
        print("      左右差信号 %.1f dB（相对全带 %+.1f）—— %s"
              % (diff, diff - full,
                 "单声道（不是毛病，知道就行）" if diff - full < -40 else "立体声"))

    # 头尾静音：MUSIC_IN 是按内容算的，前面多一段静音会把切入点整体推偏
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", MUSIC,
                        "-af", "silencedetect=n=-45dB:d=0.4", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    sil = []
    st = None
    for ln in r.stderr.splitlines():
        if "silence_start:" in ln:
            try:
                st = float(ln.split("silence_start:")[1].split()[0])
            except (IndexError, ValueError):
                st = None
        elif "silence_end:" in ln and st is not None:
            try:
                sil.append((st, float(ln.split("silence_end:")[1].split()[0])))
            except (IndexError, ValueError):
                pass
            st = None
    print("")
    if sil and sil[0][0] < 0.2:
        print("   头部静音 %.2fs —— **MUSIC_IN 要把它算进去**，"
              "不然切入点会整体偏早这么多" % sil[0][1])
    else:
        print("   没有明显的头部静音")
    mid = [s for s in sil if s[0] > 1.0 and (not curve or s[1] < curve[-1][0] - 1.0)]
    if mid:
        print("   曲中有 %d 处 >=0.4s 的静默：%s"
              % (len(mid), "  ".join("%.1f~%.1fs" % s for s in mid[:5])))
        print("   跑 `pick` 看它们会不会落进正片（落在片尾淡出里不算问题）")

    print("")
    if MUSIC_MODE == "public_domain":
        miss = [k for k in ("work", "performer", "source", "license", "url")
                if not str(MUSIC_CREDIT.get(k, "")).strip()]
        print("   授权登记: " + ("**缺 %s**，check 会拦" % "/".join(miss) if miss
                                 else "齐了（%s / %s）"
                                 % (MUSIC_CREDIT["license"], MUSIC_CREDIT["source"])))
    print("   量不出来的那件事：**这条演奏好不好、贴不贴这一支**。")
    print("   和'音色贴不贴'是同一类，多留一条候选、把最终选择交回用户，比自己拍板诚实。")


def credits():
    """导出素材来源表。**用了找来的素材时，它是交付物的一部分，不是附赠。**

    CC-BY 要求署名，而署名要跟着片子走 —— 发布时贴进简介、必要时进片尾。
    写成文件而不是打印在终端里，就是为了让它跟着成片一起交出去。
    """
    lines = ["# %s · 素材来源" % TITLE, ""]
    lines.append("成片：%s" % OUT_NAME)
    lines.append("")
    if IMG_SOURCE == "found":
        lines.append("## 画面")
        lines.append("")
        lines.append("| 镜 | 文件 | 作品 | 收藏/权利人 | 来源 | 授权 | 链接 |")
        lines.append("|---|---|---|---|---|---|---|")
        for i, c in enumerate(CLIPS, 1):
            e = CREDITS.get(c["src"], {})
            lines.append("| %d | %s | %s | %s | %s | %s | %s |"
                         % (i, c["src"], e.get("title", "**缺**"),
                            e.get("holder", "**缺**"), e.get("source", "**缺**"),
                            e.get("license", "**缺**"), e.get("url", "**缺**")))
    else:
        lines.append("## 画面")
        lines.append("")
        lines.append("按出图任务书生成（IMG_SOURCE='generated'），无第三方权利。")
    lines.append("")
    lines.append("## 配乐")
    lines.append("")
    if not music_on():
        lines.append("无背景音乐（MUSIC_MODE='none'）。")
    elif MUSIC_MODE == "generated":
        lines.append("生成（ChatCut submit_music），无第三方权利。")
    elif MUSIC_MODE == "library":
        lines.append("从素材库复用：`%s`（原为自生成），无第三方权利。"
                     % (MUSIC_FROM_LIBRARY or "**没填 MUSIC_FROM_LIBRARY**"))
    else:
        lines.append("- 作品：%s" % MUSIC_CREDIT.get("work", "**缺**"))
        lines.append("- 演奏/录音：%s" % MUSIC_CREDIT.get("performer", "**缺**"))
        lines.append("- 来源：%s" % MUSIC_CREDIT.get("source", "**缺**"))
        lines.append("- 授权：%s" % MUSIC_CREDIT.get("license", "**缺**"))
        lines.append("- 链接：%s" % MUSIC_CREDIT.get("url", "**缺**"))
        lines.append("")
        lines.append("> **录音权与作品权是两回事。** 上面登记的是**这一次录音**的授权，"
                     "不是作曲家去世多少年。")
    if SFX:
        lines.append("")
        lines.append("## 音效")
        lines.append("")
        lines.append("生成（ChatCut submit_sound）%d 条，无第三方权利。" % len(SFX))
    out = os.path.join("..", "素材来源.md")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print("素材来源表 -> " + out)
    if "**缺**" in "\n".join(lines):
        print("!! 表里有**缺**的格子 —— 先把 CREDITS / MUSIC_CREDIT 填全（check 也会拦）")


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


def vo_onset(f):
    """这条诵读的**出声点** —— 头部静音有多长。

    落点要按出声点排，不是按文件起点：TTS 逐条的头部静音不一样
    （《青玉案》十一条实测 0~0.38s），按文件起点排，
    "字幕先出多久语音才进来"会一句一个样 —— 而这个不齐比整体偏晚更难听。
    """
    p = vo_path(f)
    if not os.path.exists(p):
        return 0.0
    st = os.stat(p)
    key = "onset|%s|%d|%d" % (f, int(st.st_mtime), st.st_size)
    if key not in _VO_CACHE:
        r = subprocess.run(["ffmpeg", "-v", "info", "-i", p, "-af",
                            "silencedetect=n=-45dB:d=0.08", "-f", "null", "-"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace").stderr
        on, a, b = 0.0, re.findall(r"silence_start: ([\d.]+)", r), \
            re.findall(r"silence_end: ([\d.]+)", r)
        if b and (not a or float(a[0]) < 0.05):
            on = float(b[0])
        _VO_CACHE[key] = on
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
        # **不限于正文（style "M"）**：真人朗读常常连标题和作者一起念，
        # 而那两条是 T / TS 样式。第一版只在 M 里找，于是标题的那一段没处放，
        # 只能扔掉 —— 白白丢掉朗读者已经念好的东西。
        # 挂到 T/TS 上之后，check_vo 的两条硬约束（不跨转场、字幕消失前读完）
        # 照样适用，不用额外处理。
        hit = [(s, e) for s, e, t, y in LINES if t == txt]
        if not hit:
            sys.exit("!!! 诵读 %s 对不上任何一条字幕：%s" % (f, txt))
        s, e = hit[0]
        # 按出声点排：文件带多少头部静音，起点就往前提多少
        out.append((txt, f, max(s, s + VO_LEAD - vo_onset(f)),
                    vo_dur(f), s, e))
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
    print("   语速已扣掉头部静音；打出来的语音区间是**出声**区间")
    tot = 0.0
    for txt, f, vs, d, ls, le in plan:
        if d is None:
            print("  %-12s %-12s (缺文件)" % (txt[:12], f)); miss += 1; continue
        n = sum(1 for ch in txt if ch not in "，。：；、？！|")
        tot += d
        slack = le - (vs + d)
        flag = "" if slack >= VO_TAIL_MIN else "  << 读不完，字幕先收了"
        on = vo_onset(f)
        print("  %-12s %-12s %5.2fs  %d字 %.1f字/秒  出声 +%.2f  "
              "语音 %5.1f~%5.1f  字幕 %5.1f~%5.1f  余 %5.2fs%s"
              % (txt[:12], f, d, n, n / max(0.01, d - on), on,
                 vs + on, vs + d, ls, le, slack, flag))
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
    # 没有音乐就没有要躲闪的东西 —— 侧链是"让音乐给语音让路"，不是语音的一道效果。
    # 照着有音乐那条路写下去会去引用一个不存在的 [m]，filter_complex 直接报错。
    if not music_on():
        parts.append("[vo]anull[voa]")
        mixed.append("[voa]")
        return k
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
    ins, parts, mixed, k = [], [], [], 0
    if music_on():
        ins += ["-i", MUSIC]
        # **MV 不做那 5 秒硬淡出。** 成品歌自带收尾（这一支最后 2.3s 就是它的尾奏），
        # 再叠一道 5 秒淡出等于把人家的结尾抹掉一半，听起来像被掐了。
        # 淡入同理：歌的前奏就是它的淡入。
        fi = 0.02 if song_mode() else MUSIC_FADE_IN
        fo = "" if song_mode() else ",afade=t=out:st=%.3f:d=5" % (total - 5)
        parts.append("[0:a]aresample=48000,aformat=fltp:cl=stereo,"
                     "atrim=start=%.3f:end=%.3f,asetpts=PTS-STARTPTS,volume=%.1fdB,"
                     "apad,atrim=0:%.3f,afade=t=in:st=0:d=%.2f%s[m]"
                     % (mi, mi + total, MUSIC_GAIN, total, fi, fo))
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
    if not mixed:
        # 一个音源都没有。**不静默地产出一条静音轨** —— 静音轨会让后面的
        # loudnorm 量到 −70、归一化把它乘上天文数字的增益去够 −15，
        # 于是一条"应该没有声音"的片子变成一片放大的底噪。pass_c 会直接不要音轨。
        print("   没有任何音源（无音乐、无诵读、无音效）—— 不生成 mix.wav")
        if os.path.exists("mix.wav"):
            os.remove("mix.wav")
        return False
    parts.append("%samix=inputs=%d:normalize=0:dropout_transition=0,"
                 "atrim=0:%.3f,alimiter=limit=0.95[a]"
                 % ("".join(mixed), len(mixed), total))
    run(["ffmpeg", "-y", "-v", "error", "-stats"] + ins
        + ["-filter_complex", ";".join(parts), "-map", "[a]",
           "-c:a", "pcm_s24le", "-t", "%.3f" % total, "mix.wav"],
        "混音: %s + %d 条音效"
        % ("音乐(从 %.1fs 切入%s)" % (mi, "，侧链躲闪" if VO else "")
           if music_on() else ("无音乐" + ("，%d 条诵读" % len(VO) if VO else "")),
           len(SFX)))
    return True


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
def static_vf(s):
    """静帧镜的滤镜链：按 z/f0 裁一个固定取景窗，缩到成片尺寸，不动。

    取景窗的算法**必须和 zoompan 一样**（窗宽高各 1/z、窗心在 f、被 clip 在图内），
    否则 trace 反查的位置就和成片对不上 —— trace/measure 那一套自检是全流水线
    唯一能验取景的地方，不能因为换了条渲染路径就悄悄失准。

    **量过了，不是想当然：** 同一个 z=1.35 / f=(0.42,0.58)，两条路径各渲一帧
    做位移扫描（dx,dy 各 −2~+2），最小帧差落在 **dx=0、dy 在 0 和 1 之间**，
    即横向完全对齐、纵向差约半个像素。来源是两条路在不同尺度上各自把取景窗
    取整（静帧从 PREP 2160 宽裁，zoompan 从 UP 3240 宽裁）。
    这个量级无所谓：trace 反查用的是 724x1288 的网格，一格已经比它粗五倍。
    整体帧差在 testsrc2（满屏硬边，最坏情况）上均值 0.8 级、中位 0。

    不走 zoompan 有两个实在的好处：省掉 UP 那道 3 倍上采样（静帧不需要，
    直接从 PREP 裁再缩，少一次重采样反而更锐），以及**逐帧完全相同**，
    x264 会把它压成一串 P 帧，体积和时间都可以忽略。
    """
    z, (fx_, fy_) = s["z"][0], s["f0"]
    crop = ("crop=w='iw/%.6f':h='ih/%.6f':"
            "x='clip(%.6f*iw-out_w/2,0,iw-out_w)':"
            "y='clip(%.6f*ih-out_h/2,0,ih-out_h)'" % (z, z, fx_, fy_))
    return (crop + ",scale=%d:%d:flags=lanczos," % (W, H)
            + (VIGNETTE + "," if VIGNETTE else "") + "setsar=1,format=yuv420p")


def pass_a():
    os.makedirs("shots", exist_ok=True)
    for i, s in enumerate(SHOTS, 1):
        if not os.path.exists("img%02d.png" % i):
            sys.exit("!!! 缺 img%02d.png，先跑 prep" % i)
        if is_static(i):
            vf, how = static_vf(s), "静帧"
        else:
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
            how = "运镜"
        run(["ffmpeg", "-y", "-v", "error", "-stats", "-loop", "1",
             "-framerate", str(FPS), "-t", "%.3f" % s["dur"],
             "-i", "img%02d.png" % i, "-vf", vf, "-c:v", "libx264", "-crf", "12",
             "-preset", "medium", "-pix_fmt", "yuv420p", "shots/shot%02d.mp4" % i],
            "镜头 %d/%d  %.1fs  %s" % (i, len(SHOTS), s["dur"], how))


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

    ---- 静帧镜的门槛不一样，而且低得多 ----
    1.5 倍这条线是**为运镜定的**：镜头要在图里推近，最紧的那一刻取景窗只有 1/z
    那么大，还要填满 1080 —— 余量是给行程用的。静帧镜没有行程，取景窗从头到尾
    就是那一个，够不够只看一件事：**那个窗里的源像素数不小于输出像素数**，
    也就是 eff/z >= W。低于 1 就是在放大，成片必软；1.0~1.25 之间能用但没有余量
    （缩放本身也吃一点锐度），所以在 1.25 以下给提示。

    这不是把检查放松了，是这一镜本来就只需要这么多 —— 而它有实际后果：
    博物馆开放数据里的宋画、地方档案里的老照片，很多刚好卡在 1.0~1.5 之间。
    按运镜那条线一刀切会把它们全部判死，而它们做静帧完全够用。
    """
    bad, rows = [], []
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
        # "最紧取景"要用**这一镜自己的** z，不是全片的 z 最大值（跨度大时会把
        # 低 z 的镜头算成远低于实际的源像素比，让人去换一张本来没问题的图）
        st = is_static(i) if i <= len(SHOTS) else False
        zt = (SHOTS[i - 1]["z"][0] if st else max(SHOTS[i - 1]["z"])) \
            if i <= len(SHOTS) else 1.0
        pp = eff / zt / float(OUT_SHORT)
        tgt = pp_target(i) if i <= len(SHOTS) else PP_KENBURNS
        rows.append((i, c["src"], w, h, f, eff, pp, st, tgt))
        # 判据分两级，因为这两件事性质不同：
        #   pp < 1.0  = **在放大**，成片必软，这是缺陷 -> 拦下
        #   1.0~目标  = 顶层细节从 98% 掉到 92%，是取舍不是缺陷 -> 提示
        # 旧版的 flat "eff >= 1.5 x W" 两头都不对：对缓推镜多要一倍多的像素，
        # 对大推镜反而放行（4K 配 z=2.7 时 pp 只有 1.0 也能过）。
        if pp < 1.0 - 1e-3:
            bad.append("%s 最紧取景只有 %.2f 源像素/输出像素（<1.0 = 在放大，成片会软）；"
                       "这一镜要短边 %.0f" % (c["src"], pp, required_native(i)[0]
                                              if i <= len(SHOTS) else 0))
    if rows:
        print("")
        print("=== 素材分辨率（有效值）===")
        if SRC_NATIVE:
            print("   SRC_NATIVE=%dx%d —— 文件是放大上去的，下面按原生尺寸折算"
                  % SRC_NATIVE)
        elif IMG_SOURCE == "found":
            print("   IMG_SOURCE='found' —— 找来的图按文件尺寸算通常是对的，"
                  "但**网站给的常常是缩过的派生图**，能拿到原始档就拿原始档")
        else:
            print("   SRC_NATIVE 未设 —— 按文件尺寸算。"
                  "**如果图是放大上来的，这里的数字全是假的**")
        print("   判据：pp < 1.0 = 在放大（拦）；1.0 ~ 目标 = 顶层细节 92%~98%（提示）")
        for i, s, w, h, f, eff, pp, st, tgt in rows:
            if pp < 1.0 - 1e-3:
                flag = "  << 在放大"
            elif pp < tgt - 1e-3:
                flag = "  (够用，但低于目标 %.2f，顶层细节约 %.0f%%)" % (tgt, detail_pct(pp))
            else:
                flag = ""
            print("  %-2d %-20s 文件 %dx%d  x%.2f  裁后有效短边 %5.0f  %s"
                  "最紧取景 %.2f（目标 %.2f）%s"
                  % (i, s[:20], w, h, f, eff, "静帧 " if st else "运镜 ", pp, tgt, flag))
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

    ---- 静帧镜是**反过来**判的 ----
    加了 MOTION 之后这条检查有了第二个方向：标了 static 的镜子首尾帧差必须
    <= MOTION_STATIC_MAX。"静帧镜其实在动"和"运镜镜其实不动"一样是错，
    而且更隐蔽 —— 静帧片里混进一镜缓慢的推近，看片时只会觉得"这一段怪怪的"。
    如果这里只判运镜那一边，静帧片跑 motion 就会全绿，那又是一个不会报警的检查。
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
    print("=== 运动实测（渲出来的首尾帧差）===")
    print("    运镜镜判据 均差 >= %.1f 级；静帧镜判据 均差 <= %.1f 级"
          % (MOTION_MIN, MOTION_STATIC_MAX))
    bad, drift, skipped, n_static = [], [], [], 0
    for i, s in enumerate(SHOTS, 1):
        f = "shots/shot%02d.mp4" % i
        if not os.path.exists(f):
            print("  镜%-3d (未渲染)" % i); skipped.append(i); continue
        a, b = frame(f, 0.05), frame(f, max(0.1, s["dur"] - 0.1))
        if a is None or b is None:
            print("  镜%-3d (读不出帧，可能还在渲)" % i); skipped.append(i); continue
        d = sorted(abs(a[k] - b[k]) for k in range(GW * GH))
        mean = sum(d) / len(d)
        flag, how = "", "静帧" if is_static(i) else "运镜"
        if is_static(i):
            n_static += 1
            if mean > MOTION_STATIC_MAX:
                flag = "  << 标了 static 却在动，检查 z/f 的起止和 pass_a 走了哪条路"
                drift.append(i)
        elif POEMS and i > len(SHOTS) - len(POEMS):
            flag = "  (诗文页，本来就该几乎静止 —— 不适用)"
        elif mean < MOTION_MIN:
            flag = "  << 肉眼看不出在动，加大 z 跨度或换一张有结构的图"
            bad.append(i)
        print("  镜%-3d %-18s %s 均差 %5.1f  中位 %3d  p90 %3d  最大 %3d%s"
              % (i, CLIPS[i - 1]["src"][:18], how, mean, d[len(d) // 2],
                 d[int(len(d) * 0.9)], d[-1], flag))
    if bad:
        print("")
        print("  %d 镜运镜看不出来: %s" % (len(bad), ", ".join(str(i) for i in bad)))
    if drift:
        print("")
        print("  %d 镜标了静帧却在动: %s" % (len(drift), ", ".join(str(i) for i in drift)))
    if skipped:
        print("")
        print("  !! %d 镜没量到: %s —— **不算通过**，渲完再跑一次"
              % (len(skipped), ", ".join(str(i) for i in skipped)))
    if not bad and not drift and not skipped:
        print("")
        print("  %d 镜全部对得上（运镜 %d 镜看得出动，静帧 %d 镜真的没动）。"
              % (len(SHOTS), len(SHOTS) - n_static, n_static))
    return not bad and not drift and not skipped


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
                        # 竖排片名/落款：和正文一样顶端对齐(align=8)，字距按字号给
                        _style("TV", TITLE_FS_V, TITLE_POLARITY, 10),
                        _style("TSV", TITLE_SIG_FS_V, TITLE_POLARITY, 6),
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
            if TITLE_VERTICAL:
                ev.append("Dialogue: 0,%s,%s,TV,,0,0,0,,{\\pos(%d,%d)}{\\fad(1400,1100)}%s"
                          % (ts(st), ts(en), TITLE_X_V, TITLE_TOP_V, vtext(txt)))
            else:
                ev.append("Dialogue: 0,%s,%s,T,,0,0,0,,{\\pos(540,560)}{\\fad(1400,1100)}%s"
                          % (ts(st), ts(en), txt))
        elif sty == "TS":
            if TITLE_VERTICAL:
                ev.append("Dialogue: 0,%s,%s,TSV,,0,0,0,,{\\pos(%d,%d)}{\\fad(1400,1100)}%s"
                          % (ts(st), ts(en), TITLE_SIG_X_V,
                             TITLE_TOP_V + TITLE_SIG_DROP * TITLE_FS_V, vtext(txt)))
            else:
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


def video_chain(scrim, with_fx, grain=None):
    """master -> [轻微颗粒] -> [粒子层] -> [scrim] -> 烧字幕。
    返回 (滤镜片段列表, 额外输入参数列表, 下一个可用输入序号)。

    顺序有讲究：**粒子层在 scrim 之前**。反过来的话右上那条压暗会把雨丝和叶子
    一起压掉一档，而那正是它们最该被看见的地方。"""
    fd = FONTS.replace("\\", "/")
    parts, ins, cur, idx = [], [], "[0:v]", 1
    if GRAIN if grain is None else grain:
        # 暗调实拍留一点颗粒是对的（纸本画面才不能加，见 GRAIN 处的注释）：
        # 既防大片暮色出色带，也把 AI 生成那种过分干净的质感压掉一点
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
    got_audio = build_audio()
    fc, extra, idx = video_chain(has, with_fx)
    ins = ["-i", "master.mp4"] + extra
    amap, acodec, how = [], [], ""
    if got_audio:
        if norm_mode() == "loudnorm":
            m = measure_loudness("mix.wav")
            af = ("loudnorm=I=%.1f:TP=%.1f:LRA=%s:measured_I=%s:measured_TP=%s:"
                  "measured_LRA=%s:measured_thresh=%s:offset=%s:linear=true,"
                  "aresample=48000"
                  % (TARGET_I, TARGET_TP, m["input_lra"], m["input_i"], m["input_tp"],
                     m["input_lra"], m["input_thresh"], m["target_offset"]))
            how = "归一到 %.1f LUFS" % TARGET_I
        else:
            # 只有音效时不归一，理由见 norm_mode()。仍然量一下打出来，
            # 因为"这条片子有多轻"是交付时要主动说的事，不是可以不知道的事。
            measure_loudness("mix.wav")
            af = "aresample=48000"
            how = "**不归一**（只有音效，SFX 表里的目标响度就是成片响度）"
        ins += ["-i", "mix.wav"]
        fc.append("[%d:a]%s[a]" % (idx, af))
        amap = ["-map", "[a]"]
        acodec = ["-c:a", "aac", "-b:a", "320k"]
    else:
        how = "**无音轨**"
    out = os.path.join("..", OUT_NAME)
    run(["ffmpeg", "-y", "-v", "error", "-stats"] + ins
        + ["-filter_complex", ";".join(fc), "-map", "[v]"] + amap
        + ["-c:v", "libx264", "-crf", "18", "-preset", "slow", "-pix_fmt", "yuv420p"]
        + acodec
        + ["-movflags", "+faststart", "-t", "%.3f" % total, out],
        "粒子层 + %s + 烧字幕 -> %s" % (how, out))
    print("\n完成: " + out)
    if not got_audio:
        print("这一支**没有音轨**。如果不是有意的，检查 MUSIC_MODE / SFX / VO。")


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
    # 否则只看得到"两列都在"的状态，看不出延后到底合不合适。
    # **但不是每一支都有两列句。** 《天净沙·秋思》五句全是六字、一句一列，
    # 原来这里硬取 [0]，直接 IndexError 崩在最后一步 —— 渲完了才崩，最气人的位置。
    two = [(s, e) for s, e, t, y in LINES if y == "M" and SUB_SEP in t]
    if two:
        s0, e0 = two[0]
        marks.append((s0 + (e0 - s0) * SUB_COL_DELAY * 0.5, "只有右列(延后中)"))
    # 粒子层单独看一眼：静帧上很容易看不出来。关掉的层不抽（抽了也是空帧）
    if RAIN_DUR > 0:
        marks += [(RAIN_T0 + 4.0, "残雨·最盛"), (RAIN_T0 + RAIN_OUT + 4.0, "残雨·将收")]
    if LEAF_DUR > 0:
        marks.append((LEAF_T0 + LEAF_DUR * 0.5, "落叶·最盛"))
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


def fit_title_fs(text, spacing=16, margin=70, cap=180):
    """封面标题的字号 —— 按标题长度算出来，不写死。

    写死会随词牌长度翻车：《登高》两个字、《青玉案·元夕》六个字、
    《念奴娇·赤壁怀古》八个字，同一个 fs 差出一倍宽。
    《青玉案》实测 fs=168 时墨迹 x 2~1038，**左边只剩 2px**。

    宽度模型是量出来的，不是查字体表：楷体的实际墨迹约为标称字号的 1.04 倍
    （fs=168、5.5 个字宽、5 个字距 16 -> 实测 1036px）。
    西文和间隔号按半个字宽算。
    """
    units = sum(0.5 if ord(c) < 0x2E80 else 1.0 for c in text)
    gaps = max(0, len(text) - 1) * spacing
    room = W - 2 * margin - gaps
    return max(48, min(cap, int(room / max(0.5, units * 1.04))))


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
                  "{\\pos(540,400)\\fs%d}%s\n" % (fit_title_fs(TITLE), TITLE)
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
                "pick", "pixels", "motion", "vosync", "mquality", "credits",
                "budget"):
        {"prep": prep, "probe": probe, "trace": trace, "fx": make_fx, "still": still,
         "measure": measure, "cover": cover, "pick": pick_music_in,
         "pixels": pixels, "motion": motion, "vosync": vosync,
         "mquality": mquality, "credits": credits, "budget": budget}[what]()
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
