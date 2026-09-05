# -*- coding: utf-8 -*-
"""
讲述长片 · 横版**分段**构建脚本 (1920x1080，有旁白，字幕外挂)

  python make_story_h.py sync    # 量旁白实测时长 -> 时间轴。改了配音先跑它
  python make_story_h.py check   # 事实分级/语速/时间轴/运镜/分段自检。永远先跑
  python make_story_h.py budget  # **出图之前跑**：按每镜运动反推图要多大，分档抄进任务书
  python make_story_h.py prep    # 裁 16:9 + 统一调色 -> img01..N，并自动 probe
  python make_story_h.py probe   # 只打亮度网格
  python make_story_h.py trace   # 量镜头真正经过的区域（缺图会跳过）
  python make_story_h.py a       # 每张图做 Ken Burns（或按 MOTION 出静帧）-> shots/
  python make_story_h.py motion  # 量每镜首尾帧差：运镜镜要看得出动，静帧镜要真的不动
  python make_story_h.py b       # 转场串成无字无声 master.mp4
  python make_story_h.py langfit # **双语时**：把英文逐句压进中文定的槽（放在 c 之前）
  python make_story_h.py c       # 旁白+音效 -> 段用成片 + 预览 + SRT（每种语言一条轨）
  python make_story_h.py srt     # 只重出字幕文件（改了文案跑这个，不用重渲）
  python make_story_h.py still   # 抽静帧看画面（字幕不烧，所以这一趟只验画面）
  python make_story_h.py measure # 拿 trace 的落幅取样框复验运镜（**不再是量字幕底**）
  python make_story_h.py credits # 导出素材来源表（用公版/档案素材时是交付物）
  python make_story_h.py cover   # 封面。**双语片每种语言各一张**：再跑一次 `cover en`
                                 # 跑完会自己量文字底下的对比度，不够会报出来

===== 和竖版讲述模板 make_story_v.py 的五处不同 =====

  1. **横版 1920x1080**，裁 16:9，PREP 短边 2160
  2. **字幕外挂，不烧进画面** —— 出 SRT 交平台渲染。这一条删掉了四件原本的硬约束：
     字幕底 50 级、平台安全区、FLIP_SHOTS 极性、出图任务书的"留白/留暗"。
     标题与尾板**仍然烧进画面**（它们是画面设计，不是字幕）。
     **代价**：measure 原本量字幕底，是唯一能自检运镜的地方（"trace 和 measure 要对得上"）。
     所以 measure 被**重新指向 trace 的落幅取样框**，改成纯运镜校验，不能让它就这么没了。
  3. **这是长片的一段，不是一支完整的片子**。所以：
     - 段内**不做响度归一**（逐段归一 = 每段一个增益 = 接缝处台阶，而且不报警）。
       归一由 join 在拼完之后做一次。
     - FADE_IN 只给第一段、FADE_OUT 只给最后一段，中间接缝硬切。
     - 段长**向上取整到整帧**，否则 concat 会累积 A/V 漂移。
     - 出**两个文件**：`*_段用.mp4`（不归一、按 SEG_FIRST/SEG_LAST 决定淡场，给 join）
       和 `*_预览.mp4`（归一 + 头尾淡场，给人看）。**不这么分，将来拼片一定拿错文件。**
  4. **CLAIMS 是全片的，不是本段的**。假说可能在第二段抛出、第五段才自拆，
     所以"假说必须在片内自拆"只在 SEG_LAST 时才验，否则每一段都会报假警。
  5. **音效的目标响度锚在 VO_TARGET 上，不是 MUSIC_GAIN**。
     没有音乐时"音效排在音乐下面 1~9 dB"这条规则没有锚点。

三条开工前定死的轴（每条都有对应自检）：
  MOTION      运镜还是静帧，可逐镜覆盖 dict(..., motion="static")
  MUSIC_MODE  生成 / 公版 / 库里挑 / 没有
  IMG_SOURCE  按任务书生成 / 自己找（找来的必须登记来源，check 会拦）

===== 双语音轨（YouTube 多语言音轨）=====
`LANGS = ["zh", "en"]` 打开，出**一条画面 + 两条音轨 + 两份 SRT**。要点：

  - **时间轴归中文**。英文旁白塞进中文量出来的槽里，画面一帧都不动 ——
    画面只有一份，这是"多音轨"这三个字本身的要求。
  - NARR 每条加 `en="..."`，英文音频放 `vo_en/`，然后跑 `langfit`：
    逐句 atempo（不变调，上限 ×1.06），压不进去的**不压**，报出还得砍几个词。
  - `check` 每次都从**磁盘上的英文文件**重验一遍对不对得上槽 ——
    "改了翻译、重新生成、忘了跑 langfit" 只有这一条拦得住。
  - 音乐音效是同一床，侧链按各自的旁白算；两条轨各自量、各自归一到同一目标。

**竖版 make_story_v.py 不做这个**：抖音小红书没有外挂字幕，那一路必须烧字，
烧了就不能多音轨。竖版要英文版是另渲一支片子，不是加一条轨。
"""
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ================= 这一段的内容 =================
# 下面这一整块是《经度》**段一 · 海上没有东西**。
# 做别的段就整块换掉，其余逻辑一律不用碰。
# 跨段必须一致的量（GRADE / CLAIMS / 字幕样式 / 响度目标）见 ani/经度奖/全片总谱.md，
# **那份文件是唯一的真相来源，不要在这里另定一套**。
TITLE, SUBTITLE = "经度", "一个木匠的四十年"
SEG_NAME = "段一"                  # 用在输出文件名上
SEG_INDEX, SEG_TOTAL = 1, 5
SEG_FIRST = (SEG_INDEX == 1)       # 只有第一段有开场淡入
SEG_LAST = (SEG_INDEX == SEG_TOTAL)  # 只有最后一段有片尾淡出，也只有它验假说自拆
OUT_NAME = "%s_段用.mp4" % SEG_NAME       # 给 join 用：不归一
PREVIEW_NAME = "%s_预览.mp4" % SEG_NAME   # 给人看：归一 + 头尾淡场
# 字幕文件名由 srt_name(lang) 生成：中文 段一.srt，英文 段一.en.srt。
# **这里不再定义 SRT_NAME** —— 留一个没人读的常量在这儿，
# 迟早有人改它然后奇怪为什么文件名没变。
CHECK_NAME = "%s_检查片.mp4" % SEG_NAME   # 门禁二：出图前的占位检查片
PV_FS = 34                                # 占位板上标签的字号
COVER_NAME = "封面_横版.png"
COVER_FROM = 5

# ---- 事实分级 ----
# 讲历史故事唯一致命的错误是把推断说成史实。三个级别：
#   史实 —— 正常讲
#   概数 —— 稿子里就不要给精确值（「上百立方公里」比「150 立方公里」安全且一样有力）
#   假说 —— **必须在片内说出来**，不能只写在简介里。看简介的人不到十分之一
# 有"假说"却在最后三句里一个字都没提，check 会报警。
# **这张表是全片的，不是本段的**（见 全片总谱.md「四」）。假说 C12 在段二、段四
# 都会露头，到段五才自拆 —— 所以自拆检查只在 SEG_LAST 跑，否则每段都报假警。
# 本段实际用到的：C1 C2 C3 C13。其余留在表里，是为了让每一段都看得见全局。
CLAIMS = [
    ("C1",  "史实", "1707 锡利群岛海难，英国舰队损失四艘船", "1707-10-22"),
    ("C2",  "概数", "死亡上千人", "各版本 1400~2000，**片内不给精确值**"),
    ("C3",  "史实", "1714 经度法案，悬赏最高两万镑", "判据是半度以内"),
    ("C4",  "史实", "哈里森木匠出身、自学钟表，早期做木齿轮钟", "约克郡"),
    ("C5",  "史实", "H1 于 1735 完成，次年泰晤士—里斯本试航", ""),
    ("C6",  "史实", "H2、H3 他自己都不满意；H3 做了近二十年", "H2 1741 / H3 1759"),
    ("C7",  "概数", "H4 是怀表尺寸，直径十几厘米", "约 13cm，稿里说『一只大怀表』"),
    ("C8",  "概数", "1761–62 牙买加海试误差极小", "各版本不一，稿里说『几秒的量级』"),
    ("C9",  "史实", "马斯基林 1765 任皇家天文学家，同时在经度委员会", "段四的支点"),
    ("C10", "史实", "1773 议会另行拨款 8750 镑，时年 80；从未获颁经度奖本身", ""),
    ("C11", "史实", "库克第二次航行携 K1（肯德尔仿 H4）", "1772–75"),
    ("C12", "假说", "『马斯基林与委员会恶意打压哈里森』这条通行叙事",
     "来自 1995 Sobel《经度》；科学史界认为被戏剧化。**段五自拆**"),
    ("C13", "史实", "牛顿 1714 向议会陈述，认为钟表方案当时不可行",
     "列了船摇/冷热/干湿。段一→段二的钩子"),
]

# ---- 旁白 ----
# 一条 = 一句 VO = 一屏字幕。txt 里的 ｜ 是**手工断行位置**，不上屏。
#   shot  这一句落在第几镜(1 起)
#   en    这一句的英文（LANGS 里有 "en" 时每条必填）。断行符同样用 ｜。
#         **英文是塞进中文槽里的**，不是自由翻译 —— 一句太长就压不进去，
#         langfit 会报出这一句还得砍几个词。见下面「双语音轨」那一节。
#   pre/post  这一句前后的静默，不写就用 PRE_DEF/POST_DEF。只在要留戏的地方写：
#             冷开场 1.2~1.6；转折句前 0.8；金句前 0.8 后 1.2
#   est   排片用的秒数。**这一支里它已经不是估算了** —— 32 条 TTS 都生成完了，
#         下面这些数字是 ChatCut 报的实测时长（豆包 渊博小叔 / storytelling / emotionScale 3
#         / 默认语速）。mp3 落到本地之后跑 sync，它会用 ffprobe 重新量一遍并覆盖。
#         **两边应该一致**（同一个文件）—— 如果 sync 量出来和这里差得多，
#         那不是语速问题，是下载拿错了文件或者下坏了。这是个免费的完整性检查。
#
# 镜与镜之间的气口**不用手写** —— timeline() 会把每镜首句的 pre 抬到 GAP_PRE、
# 末句的 post 抬到 GAP_POST。转场落在这段静默的正中，于是永远压不到字幕。
# 手工在 13 个边界上凑这两个数，一定会漏掉一两处，而漏掉的那处要到成片才看得出来。
# 还没生成 mp3 时用来先排片的语速。**这个数是量出来的，不是通行值。**
# 《没有夏天的那一年》(无 emotion) 实测 4.6；《经度》段一
# (豆包 渊博小叔 / storytelling / emotionScale 3 / 默认语速) 实测 **4.24**。
# 换音色或换表演方向就要重新量 —— 它取决于 emotion 和 performancePrompt，不是常数。

# **口径陷阱（2026-08-26，《白衣女人》集三发现，此前咬了集一和集二）**：
# EST_RATE 在下面只被 _est() 用作 `汉字数 / EST_RATE = 这一条 mp3 的时长`，
# 量的是**剪掉边缘静音之后的纯语音**。它**不是**总谱/制作说明里那张表的「含静音语速」——
# 那个数把按条计的静音摊进了按字计的说话里，天生更小。
# 集一、集二两次都把含静音的 4.10 填了进来，于是出图前的片长估算长了两成
# （集二估 ~620s，sync 实测 520.9s）。同口径的实测是 1937 汉字 / 373.6s = **5.19 字/秒**。
# 换音色、换 emotion、换 performancePrompt 都要重新量；**填之前先问自己量的是哪一个**。
EST_RATE = 4.24

VO_DIR = "vo"
PRE_DEF, POST_DEF = 0.18, 0.28
GAP_PRE, GAP_POST = 0.45, 0.70
NARR = [
    dict(vo="VO_01a", shot=1,  pre=1.50, est=2.83, txt="你手机上那个蓝点，｜知道自己在哪。"),
    dict(vo="VO_01b", shot=1,  est=3.46, txt="三百年前，｜地球上最强的海军做不到。"),
    dict(vo="VO_01c", shot=1,  est=3.05, txt="解决它的人，｜是一个乡下木匠。"),
    dict(vo="VO_02",  shot=2,  post=0.90, est=3.05, txt="他用黄铜和木头，｜做了四十年。"),
    dict(vo="VO_03a", shot=3,  pre=0.80, est=4.03, txt="1707年10月，一支英国舰队正在返航。"),
    dict(vo="VO_03b", shot=3,  est=4.27,
         txt="连日的浓雾和坏天气，｜他们已经不知道自己在哪里了。"),
    dict(vo="VO_04a", shot=4,  est=5.64,
         txt="领航员们聚在一起推算，｜给出的答案是：前方是开阔海面。"),
    dict(vo="VO_04b", shot=4,  post=0.90, est=1.63, txt="他们错了。"),
    dict(vo="VO_05a", shot=5,  est=3.84, txt="那天夜里，舰队撞上了锡利群岛的礁石。"),
    dict(vo="VO_05b", shot=5,  est=1.63, txt="四艘船沉了。"),
    dict(vo="VO_05c", shot=5,  post=1.00, est=3.07, txt="上千人死在自己国家的海岸线上。"),
    dict(vo="VO_06",  shot=6,  est=4.66, txt="不是风暴，不是敌人。｜他们只是不知道自己在哪。"),
    dict(vo="VO_07a", shot=7,  pre=0.80, est=2.83, txt="在海上，南北方向是好办的。"),
    dict(vo="VO_07b", shot=7,  est=3.46, txt="正午量一下太阳的高度，｜纬度就出来了。"),
    dict(vo="VO_07c", shot=7,  est=3.22, txt="一把尺子，抬头看天，就够了。"),
    dict(vo="VO_08a", shot=8,  est=2.26, txt="东西方向没有这样的东西。"),
    dict(vo="VO_08b", shot=8,  post=0.80, est=4.03, txt="天上没有一条线告诉你，｜你离家有多远。"),
    dict(vo="VO_09a", shot=9,  pre=0.80, est=1.46, txt="但有一个办法。"),
    dict(vo="VO_09b", shot=9,  est=2.83, txt="地球在转，一小时转过十五度。"),
    dict(vo="VO_09c", shot=9,  est=5.62,
         txt="所以如果你知道，此刻你这里是正午，｜而伦敦已经是下午三点——"),
    dict(vo="VO_09d", shot=9,  post=1.00, est=2.45, txt="你就在伦敦以西四十五度。"),
    dict(vo="VO_10a", shot=10, est=4.82,
         txt="于是经度不再是一个地理问题，｜它变成了一个计时问题。"),
    dict(vo="VO_10b", shot=10, post=0.80, est=3.24, txt="你需要一只在海上还走得准的钟。"),
    dict(vo="VO_11a", shot=11, est=1.63, txt="那时候没有这种钟。"),
    dict(vo="VO_11b", shot=11, post=0.80, est=6.67,
         txt="摆钟在陆地上很准。｜上了船，浪一颠，冷热一变，就废了。"),
    dict(vo="VO_12a", shot=12, pre=0.80, est=2.04, txt="牛顿在议会里作过证。"),
    dict(vo="VO_12b", shot=12, post=1.00, est=5.86,
         txt="他把摆钟在海上失准的原因一条条列出来，｜然后说，这条路走不通。"),
    dict(vo="VO_13a", shot=13, pre=0.80, est=4.03, txt="1714年，英国议会做了一件事：悬赏。"),
    dict(vo="VO_13b", shot=13, est=3.62, txt="谁能在海上把经度定准，｜最高两万镑。"),
    dict(vo="VO_13c", shot=13, est=2.83, txt="那是一笔｜足够让人赌上一生的钱。"),
    dict(vo="VO_14a", shot=14, pre=0.80, est=2.83, txt="所有人都抬头去看天上的月亮。"),
    dict(vo="VO_14b", shot=14, post=1.60, est=2.83, txt="只有一个人，｜低头去看一只钟。"),
]

# ---- 尾板 ----（可选。t 是相对最后一镜起点的偏移）
# **段一没有尾板** —— 它是长片的第一段，结尾是钩子不是收束。
# 尾板只属于 SEG_LAST。开场标题字卡另说（TITLE_CARD）。
ENDCARD = None
# 逐镜角标：{镜号: 文字}。给别人的复原模型/影像打「这是模型」和 CC BY 署名用。
# **不是装饰**：展示他人复原方案时不标注，观众会以为看到的是原件；
# 而 CC BY 素材的署名是强制的，打在画面上比只写进简介稳。
SHOT_LABELS = {}

# ---- 开场标题字卡 ----（只有第一段有；烧进画面，不走 SRT）
# 段一镜 1 前六七秒只有标题在走，一个字幕都没有 —— 这一段是让出来的。
TITLE_CARD = dict(head=TITLE, sub=SUBTITLE, t0=1.0, t1=6.4, y=470) if SEG_FIRST else None

# ================= 明暗极性 =================
# 讲述片基本都是暗调实拍 -> light_on_dark（近白字 + 不透明黑描边 + 投影）。
# 拿不准先出一张图跑 probe/trace，看实测再定，不要先入为主。
POLARITY = "light_on_dark"
TITLE_POLARITY = "light_on_dark"

# scrim 原本是为烧录字幕压底的。**字幕外挂之后它没有用途了** —— 叠一条压暗带
# 只会让画面脏一档，而且 trace/measure 两边都要跟着建模它（那是三只脚的坑）。
# 一律关掉。要开就得同时补 scrim_factor() 和 measure 的抽帧叠回。
SCRIM_ALPHA = 0.0
SCRIM_Y0, SCRIM_SOFT, SCRIM_POW = 900, 260, 1.4

# ================= 全局参数 =================
W, H, FPS = 1920, 1080, 30
PREP = (3840, 2160)
UP = (5760, 3240)
XFADE = 1.0                 # 讲述片的默认转场比诗片短。任何一镜可写 xf= 覆盖
TAIL = 1.0                  # 最后一镜在旁白收完之后再留多久
# **分段片的淡场只属于两头**：中间接缝硬切，否则每三分钟黑一次，观众读作"结束了"。
FADE_IN = 1.2 if SEG_FIRST else 0.0
FADE_OUT = 3.0 if SEG_LAST else 0.0
FADE_COLOR = "black"
# 预览用的淡出（只是为了单看这一段不至于硬切收尾），不进段用文件
PREVIEW_FADE_OUT = 1.5
VIGNETTE = "vignette=PI/5"  # 暗调实拍可以加；纸质画面一律不加。trace 会自动建模它

# **这一块必须留在项目配置导入之前。** 原来它在文件末尾（check_cover_text 上面），
# 于是 segment_config 里写的 COVER_TEXT 被模板的占位符反向覆盖，
# 封面渲出来是 'English Title / Second Line' —— 而且不报错。
# ================= 封面文案：**双语片每种语言各一张** =================
# 2026-09-01 用户定的规矩：以后双语片都要单独的封面。
# 理由和"简介只写中文"是同一个：观众能切英文音轨，推荐流里看到的却是一张看不懂的图。
#
# 两张用**同一张图版**（COVER_FROM 那一镜），只换文字 —— 换图就成了两支片子的封面。
#
# `lines` 是**逐行**写的，不靠自动换行：英文标题一行常常排不开，断在哪儿是设计决定，
# 交给自动换行会断在最难看的地方。每行写 (文字, 字号, y)；`sub` 同样。
COVER_TEXT = {
    "zh": dict(lines=[(TITLE, 120, int(H * 0.44))], sub=(SUBTITLE, 54, int(H * 0.56))),
    # 英文这一行是占位，按自己的标题改。**字号和位置要量，不要靠眼睛挪** ——
    # cover 跑完会自己量（见 check_cover_text），不够会报出来。
    "en": dict(lines=[("English Title", 96, int(H * 0.40)),
                      ("Second Line", 96, int(H * 0.52))],
               sub=("Subtitle · Year", 46, int(H * 0.64))),
}



SRC = os.path.join("..", "素材")
FONTS = os.path.join("..", "fonts")
SUB_FONT = "Microsoft YaHei"        # 讲述是现代口吻，用黑体不用楷体

# ================= 运动：运镜还是静帧 =================
# 全片默认，任何一镜可写 motion="static" / "kenburns" 覆盖。
#   "kenburns"  每张图缓推缓摇（这一支，以及此前交付的每一支）
#   "static"    一镜一张静止的画
#
# **静帧要显式声明，不能靠"z 起止写成一样"隐式表示。** 这条流水线最贵的错误
# 就是"写了位移却没给足缩放 = 原地微缩放"，参数表上看不出来；如果允许隐式，
# 那个 bug 就变成一个合法配置，check 再也拦不住。所以两边都拦：
# 标了 static 却有行程、标了 kenburns 却起止全同，check_moves 都报错；
# 渲完 motion 命令反过来验（运镜镜要动，静帧镜要真的不动）。
#
# **讲述模式选静帧要想清楚一件事**：诗片没有旁白，画面停住时全靠音乐撑；
# 讲述片有旁白连着说，画面停住并不空 —— 所以静帧在讲述片里比在诗片里好用。
# 代价是转场变成唯一的视觉节拍，别再让它是个常数。
MOTION = "kenburns"
MOTION_STATIC_MAX = 0.6     # 静帧镜的上限（MOTION_MIN 在下面，是运镜镜的下限）

# ================= 配乐：生成 / 公版 / 没有 =================
#   "generated"      ChatCut submit_music 生成的。封顶实测 180~245s 随机、
#                    提示词管不住，所以片长要倒着排。
#   "public_domain"  自己找来的公版或开放授权录音。**录音权和作品权是两回事**
#                    （贝多芬是公版，某乐团 2010 年的录音不是），另外历史转录有
#                    底噪和带宽损失。走这一路 MUSIC_CREDIT 必填，跑 mquality 量。
#                    详见 references/music.md。
#   "none"           不要背景音乐。**讲述片这一条比诗片实际得多** —— 旁白本来
#                    就是连续的音床，去掉音乐剩下的是"人在跟你说话 + 环境声"，
#                    是一种成立的风格，不是缺了一块。
MUSIC_MODE = "none"
MUSIC = os.path.join(SRC, "00_music_main.mp3")      # MUSIC_MODE="none" 时忽略
MUSIC_CREDIT = dict(work="", performer="", source="", license="", url="")
# MUSIC_MODE="library" 时填库里的文件名。**记它是为了两件事**：
# 交付时说清这条曲子是复用的；以及做完之后回去 `music_index.py add --used`，
# 否则下一支查库时不知道它已经用过了 —— **同一个系列里重复用同一条，观众记得住**。
MUSIC_FROM_LIBRARY = ""

# 有旁白，音乐要低 3~4dB，而且必须**侧链躲闪** —— 只调低音量是不够的：
# 压到听不见音乐就没意义，压不够旁白就发浑。
MUSIC_GAIN = -12.5
MUSIC_IN = 0.0              # 跑 pick 得到
MUSIC_FADE_IN = 0.8
DUCK = dict(threshold=0.06, ratio=6, attack=25, release=350)   # release 短了音乐会喘

VO_TARGET = -16.0           # 每条旁白**单独**归一到这个响度，顺带抹平 TTS 的忽大忽小
TARGET_I, TARGET_TP = -15.0, -1.5

# ================= 音效 =================
# **没有背景音乐时，音效是承重结构，不是加分项。** 句间的静默是真的静。
#
# 两处和竖版模板不同：
#
# 一、**目标响度锚在 VO_TARGET 上，不是 MUSIC_GAIN。**
#     原规则是"音效排在音乐下面 1~9 dB"，锚点是"音乐实测 + MUSIC_GAIN"。
#     MUSIC_MODE='none' 时那个锚**不存在**，照抄会把所有音效排到一个没有意义的绝对值上。
#     现在一律写成 VO_TARGET - N：动作声最近(N≈8)，环境底最远(N≈20)。
#
# 二、**起点按镜号 + 镜内偏移写，不写绝对秒数。**
#     时间轴是旁白实测推出来的，改一条旁白，后面所有绝对秒数全错，而
#     "在镜 3 开头进来"这个**意图**没有变。写镜号，让脚本去算秒数。
#     （竖版模板写绝对秒是因为它的 SFX 表是空的，这个坑还没人踩到。）
SFX_ANCHOR = VO_TARGET
# 三、**先查库再生成。** 段一 11 条里有 3 条直接用自己素材库里的（雨 / 秋风 / 晓风），
#     库里的文件名原样保留 —— 那是复用的凭证，改名就看不出来了。
#     其余 8 条（远海浪/船体缆绳/触礁/海岸与鸟/钟走时/船舱摆钟/议会室内）库里没有，
#     生成的。ChatCut 内置库有 light-clock-tick 等三条机械音，**没用** ——
#     钟走时是贯穿五段的声音动机，要十八世纪黄铜机芯在木壳里的走时，通用 UI 滴答指定不出来。
SFX = [
    # v1 废弃：整体 −40.0，但 <120 −27.7 / 120-2k −56.2 / >2k −84.3 —— 能量几乎全在
    # 120Hz 以下，手机喇叭上等于不存在（江风那个坑）。v2 把中频抬了 31.7 dB。
    # 教训：否定式提示词（"not a subsonic rumble"）管不住频谱，要**正面指定频段**。
    dict(f="s01_远海浪_v2.mp3", shot=3, off=-0.5, tgt=SFX_ANCHOR - 20, fi=2.0, fo=3.0, dur=34.0),
    dict(f="声声慢·宋人淡设色版_04_雨.mp3",
                               shot=3,  off=0.0,  tgt=SFX_ANCHOR - 18, fi=1.5, fo=2.5, dur=18.0),
    dict(f="声声慢·宋人淡设色版_01_秋风.mp3",
                               shot=3,  off=0.0,  tgt=SFX_ANCHOR - 19, fi=1.5, fo=2.5, dur=18.0),
    dict(f="s03_船体缆绳.mp3", shot=3,  off=2.0,  tgt=SFX_ANCHOR - 16, fi=1.2, fo=2.0, dur=15.0),
    dict(f="s04_触礁碎裂.mp3", shot=5,  off=0.8,  tgt=SFX_ANCHOR - 8,  fi=0.1, fo=2.5, dur=6.0),
    dict(f="s05_海岸与鸟.mp3", shot=6,  off=-0.3, tgt=SFX_ANCHOR - 16, fi=1.0, fo=1.5, dur=6.5),
    dict(f="s06_钟走时.mp3",   shot=2,  off=0.0,  tgt=SFX_ANCHOR - 12, fi=0.3, fo=1.0, dur=4.5),
    dict(f="s06_钟走时.mp3",   shot=10, off=0.5,  tgt=SFX_ANCHOR - 14, fi=1.0, fo=2.0, dur=17.0),
    # **两版叠起来用，不是选一版。** 分频段量出来它们正好互补：
    #   v1  <120 −26.1 / 120-2k −31.3 / >2k −64.1  有船舱的身体，但**没有 tick**
    #   v2  <120 −47.9 / 120-2k −52.9 / >2k −41.8  tick 出来了，但身体没了、整体轻 10dB
    # 这一镜的全部任务是让人听见钟摆走得不匀，所以 v2 当前景、v1 垫在下面 4dB。
    # 重生成一版换掉另一版是本能反应，但**量完发现两版各有一半**，叠加不花额度。
    dict(f="s07_船舱摆钟_v2.mp3", shot=11, off=0.0, tgt=SFX_ANCHOR - 14, fi=1.0, fo=1.5, dur=8.5),
    dict(f="s07_船舱摆钟.mp3",   shot=11, off=0.0, tgt=SFX_ANCHOR - 18, fi=1.0, fo=1.5, dur=8.5),
    # 生成上限 22s，所以这一条压到 21.8 让它**不循环** —— 房间残响的接缝很难藏
    dict(f="s08_议会室内.mp3", shot=12, off=-0.3, tgt=SFX_ANCHOR - 18, fi=1.5, fo=2.5, dur=21.8),
    dict(f="雨霖铃·电影写实版_05_晓风.mp3",
                               shot=14, off=-0.5, tgt=SFX_ANCHOR - 20, fi=1.5, fo=3.0, dur=9.0),
]
# **s01 是唯一一条会循环的**：要盖镜 3~6 共 34s，而 ElevenLabs 生成上限 22s。
# 连续的涌浪循环一次几乎听不出接缝，接受了；换成别的声音就不能这么办。
SFX_GAIN_WARN = 12.0

# 找来的音效的来源。**自己生成的不用登记，从站点下的必须登记** ——
# `credits` 会把它写进交付的《素材来源》，没有它那份文件会断言
# "音效均无第三方权利"，而那是**一句会被交出去的假话**。
# 键是 SFX 表里的文件名，值至少要有 title / author / source / license / url。
# `sort_downloads.py` 也读它：按 url 末尾的数字 id 把下载来的原始文件名改成这里的键。
SFX_CREDITS = {}
# 全片的声音动机：航海钟的走时声（s06）。没有音乐，它替代音乐当那条听得出来的线 ——
# 段一镜 2 第一次出现，镜 10~11 回来。此后每一段的关键处各回来一次，段五收尾再响。

# ================= 调色：全片唯一一条，各段不许各自重定 =================
# **判据是量出来的直方图，不是画种。** 这条是拿两张样图实测定下来的：
#
#   样图A 工作台(室内暗)  mean 45.3  p1/p25/p50 = 4/18/31   p90/p99/max = 101/169/253
#   样图B 加勒比甲板(亮)  mean 156.5 p1/p25/p50 = 28/86/178 p90/p99/max = 235/246/255
#
# 三条结论：
#
# 一、**这个画种不欠曝。** A 的 max 是 253，白点没塌，`colorlevels` 无事可做；
#     median 31 / p75 64 已经比《没有夏天的那一年》调完之后还好。
#     前几支"AI 生成的暗调实拍一定技术性欠曝"是**那个画种和那个生成器**的性质，
#     不是普遍规律 —— 油画的天光本来就是画出来的光源。
#
# 二、**一条全局曲线扛得住 mean 45 和 mean 157 两头，条件是只在 0.75 以下起作用。**
#     实测：A 的 p25 18→26、p50 31→41、亮度<16 的面积 19.3%→9.1%（暗部的锉刀救回来了）；
#     B 的 p50 178→179（只动 1 级）、p90 235→235、高光截顶 0.2%→0.2%（完全没动）。
#     所以"段一最暗 / 段四最亮"那个明暗差是**叙事设计**，这条曲线正好不去碰它。
#
# 三、不要加 contrast。在暗调片上加反差是负的（这一条在两支片子上都验过）。
GRADE = "curves=all='0/0 0.06/0.09 0.25/0.28 0.75/0.75 1/1'"

# 素材与裁切。**不必一镜一图**：同一场景出一张大图、用两次不同取景窗更省。
# 这一段 14 镜 / **13 张图** —— 镜 12 和镜 13 共用 `12_议会.png`：
# 那张图要构图成「作证的人在画面左上、桌面文书在右下」，镜 12 推向人、镜 13 下摇到文书。
# 两镜的 zoompan 取景窗就足以把它们分开，所以 CLIPS 的 zoom 保持 1.00，不额外买像素。
CLIPS = [
    dict(src="01_手机蓝点.png",     zoom=1.00, cx=0.50, cy=0.50, tweak=""),
    dict(src="02_黄铜机芯.png",     zoom=1.00, cx=0.50, cy=0.50, tweak=""),
    dict(src="03_夜海舰队.png",     zoom=1.00, cx=0.50, cy=0.50, tweak=""),
    dict(src="04_舱内推算.png",     zoom=1.00, cx=0.50, cy=0.50, tweak=""),
    dict(src="05_触礁.png",         zoom=1.00, cx=0.50, cy=0.50, tweak=""),
    dict(src="06_白日残骸.png",     zoom=1.00, cx=0.50, cy=0.50, tweak=""),
    dict(src="07_甲板量日.png",     zoom=1.00, cx=0.50, cy=0.50, tweak=""),
    dict(src="08_十八世纪海图.png", zoom=1.00, cx=0.50, cy=0.50, tweak=""),
    dict(src="09_正午与黄昏.png",   zoom=1.00, cx=0.50, cy=0.50, tweak=""),
    dict(src="10_钟与海图.png",     zoom=1.00, cx=0.50, cy=0.50, tweak=""),
    dict(src="11_船舱摆钟.png",     zoom=1.00, cx=0.50, cy=0.50, tweak=""),
    dict(src="12_议会.png",         zoom=1.00, cx=0.50, cy=0.50, tweak=""),   # 镜12 推向人
    dict(src="12_议会.png",         zoom=1.00, cx=0.50, cy=0.50, tweak=""),   # 镜13 下摇到文书
    dict(src="13_月亮与窗.png",     zoom=1.00, cx=0.50, cy=0.50, tweak=""),
]

# 分镜。**没有 dur** —— 时长由旁白算出来。
# 缩放 z 时焦点只能落在 [1/(2z), 1-1/(2z)]，想走 d 比例行程必须 z >= 1/(1-d)：
#   10%->1.12  20%->1.25  30%->1.43  40%->1.67
# 写了位移不给足缩放 = 原地微缩放，check_moves() 会报警。
# xf 是"这一镜转到下一镜"用多久，转场是叙事标点，不该是常数。
SHOTS = [
    # 镜1 现代：手机蓝点。慢推近，从确定的现在推进去
    dict(z=(1.10, 1.30), f0=(0.500, 0.520), f1=(0.500, 0.460), xf=0.5),  # 钩子后硬切
    # 镜2 黄铜机芯特写。**静帧** —— 4.0s，运镜走不完；短镜硬切当重音
    dict(z=(1.00, 1.00), f0=(0.500, 0.500), f1=(0.500, 0.500), motion="static", xf=1.2),
    # 镜3 夜海舰队。下摇：从天压到海面
    dict(z=(1.24, 1.42), f0=(0.500, 0.420), f1=(0.500, 0.580)),
    # 镜4 舱内推算海图。推近到图上，斜着走
    dict(z=(1.18, 1.44), f0=(0.480, 0.460), f1=(0.520, 0.540), xf=0.4),  # 「他们错了」后短切
    # 镜5 触礁。急推，全段唯一的力度
    dict(z=(1.20, 1.55), f0=(0.500, 0.500), f1=(0.540, 0.440), xf=1.8),  # 长溶解=跳到白日
    # 镜6 白日残骸。**静帧** —— 5.3s 的余波拍子，静比动狠
    dict(z=(1.00, 1.00), f0=(0.500, 0.500), f1=(0.500, 0.500), motion="static", xf=1.6),
    # 镜7 甲板量太阳。上摇，跟着仪器抬起来
    dict(z=(1.22, 1.40), f0=(0.500, 0.580), f1=(0.500, 0.420)),
    # 镜8 十八世纪海图。**静帧** —— 图本身是内容，值得停着看
    dict(z=(1.00, 1.00), f0=(0.500, 0.500), f1=(0.500, 0.500), motion="static"),
    # 镜9 正午与黄昏。**横移** —— 全段的知识核心，让镜头把"两地"走一遍
    dict(z=(1.34, 1.34), f0=(0.380, 0.500), f1=(0.620, 0.500)),
    # 镜10 钟与海图。慢推：需要一只走得准的钟
    dict(z=(1.14, 1.34), f0=(0.500, 0.500), f1=(0.500, 0.480)),
    # 镜11 船舱摆钟。斜推 + 微晃，"失准"要看得出来
    dict(z=(1.26, 1.44), f0=(0.460, 0.480), f1=(0.550, 0.530)),
    # 镜12 议会作证。推向画面左上的那个人（和镜13 共用同一张图）
    dict(z=(1.16, 1.42), f0=(0.440, 0.480), f1=(0.420, 0.450), xf=0.8),  # 短一点才像答上了
    # 镜13 同一张议会图，下摇到右下的桌面文书
    dict(z=(1.24, 1.40), f0=(0.560, 0.480), f1=(0.580, 0.640)),
    # 镜14 月亮与远处亮着的窗。慢拉远收尾，钩住段二
    dict(z=(1.36, 1.14), f0=(0.520, 0.460), f1=(0.500, 0.500)),
]

# 细节就是内容的那几镜。**静帧镜不用列** —— pp_target 对静帧一律给 1.00
# （恒等重采样，不过滤波器），所以镜 2 / 8 虽然是特写也不进这个集合。
DETAIL_SHOTS = {12}     # 镜12 是脸的推近

# ================= 字幕版式（横排、左下）=================
# 竖版右侧 x 929~1080 / y 864~1632 是抖音小红书的操作栏（真机验过）。
# 诗片的竖排字幕靠**上移**避开；横排字幕是宽的，靠**收窄 + 靠左**避开。
SUB_CX = W // 2             # 外挂字幕由播放器居中渲染，这里只用于**标题字卡**定位
SUB_FS = 46                 # 只影响烧进画面的标题/尾板
SUB_BOT = 980               # 同上
SUB_LH = 64
# **一屏字数上限**，取代竖版的像素宽度判据。
# 烧录字幕时"一行放得下多少"是像素问题；外挂字幕由播放器排版，字号我们管不着，
# 所以判据要换成**字数** —— 通行做法是一行不超过 ~18 个全角字符、一屏不超过两行。
SUB_MAX_CHARS = 20
SUB_SEP = "｜"              # 手工断行符，不上屏。不要交给自动换行
# 行宽按**字形宽度**算，不按字数：ASCII 只有汉字的一半多一点，
# 「1815 年 4 月，印尼松巴哇岛，」按字数是 18 个超标，按宽度只有 14.4 个字，够得下。
ASCII_W = 0.55

# ================= 双语音轨（YouTube 多音轨）=================
# YouTube 的多语言音轨是**一条视频 + N 条音轨**，画面只有一份。这一句推出下面全部设计：
#
#   1. **时间轴归中文所有。** 英文旁白必须塞进中文量出来的槽里。反过来让画面
#      迁就英文，两条轨就是两支片子，多音轨本身就没有意义了。
#   2. **正文字幕一律外挂**（横版本来就是），中英各一份 SRT。烧进画面的中文字幕
#      会跟着英文轨一起播 —— 这是这个功能最容易犯、而且自己看中文版时永远发现不了的错。
#   3. 音乐和音效是**同一床**，只有旁白换语言。侧链躲闪按各自的旁白算：
#      英文的停顿位置和中文不一样，拿中文的包络去躲英文，会在错的地方让路。
#
# **竖版（make_story_v.py）不做这个。** 抖音小红书没有外挂字幕这回事，那一路必须
# 烧字，烧了就不能多音轨。竖版要英文版是另渲一支片子，不是加一条轨。
LANGS = ["zh"]              # 只写 ["zh"] 就是单语，整条流水线和以前一模一样
DEFAULT_LANG = "zh"         # 定时间轴的那一条，也是播放器默认选中的那一条
LANG_INFO = {
    # code 是 ISO 639-2，YouTube 按它认音轨语言；name 写进音轨标题给人看
    "zh": dict(code="zho", name="中文", srt_suffix=""),
    "en": dict(code="eng", name="English", srt_suffix=".en"),
}
VO_DIR_OF = {"zh": VO_DIR, "en": "vo_en"}
# 逐句压的原件备份。**倍率永远从原件算**，不从上一次压完的文件算 —— 否则第二次
# 调整会走反方向，而且一声不吭（竖版 vofit 上踩过，见那边的注释）。
VO_RAW_OF = {"en": "vo_en_raw"}

# 英文语速，词/秒。**必须自己量，不要填通行值** —— 它和中文的 EST_RATE 是同一类数，
# 取决于音色、emotion 和 performancePrompt。留 None 时 langfit 用**本批实测**的语速
# 去换算"还得砍几个词"，并把量到的数打出来让你回填。第一支英文片做完就填上。
EN_RATE = None

# 逐句压的倍率上限。atempo 不变调，1.06 以内听不出来，1.08 开始有"赶"的感觉。
# 超过上限**不压**，报出这一句还得砍几个词 —— 把 1.2 倍的活交给 atempo，
# 等于用一个听得出来的毛病换一个看不出来的错位，那不是修好，是藏起来。
LANG_TEMPO_MAX = 1.06
# 一句英文最多能从**它后面那段静默**里借多少秒。
# **镜末那一句不许借**：镜末的静默正中骑着转场，借了就是把话说到转场底下去，
# 而这件事在参数表和波形上都看不出来，要放出来听才发现。
LANG_BORROW = 0.30
# 填了理由，压不进槽的那几句就降级成提示（空着照旧拦下）。
# **不给静默绕过的开关** —— 那样下一支照抄配置时就再也不知道这里做过妥协。
LANG_ACCEPT_REASON = ""
# 英文一行的字数上限。中文是 20 个全角字，英文按半角算大约是它的两倍。
SUB_MAX_CHARS_EN = 42

# ================= 平台安全区：**这一支不适用** =================
# 竖版那套 (929,864,1080,1632) / 顶部 173 是抖音小红书真机比出来的，用来防
# **烧录**字幕撞操作栏。这一支字幕外挂，由播放器渲染，播放器自己会避开它的控件 ——
# 所以 check_safe 和 selftest_safe 一起删掉了，不是忘了搬。
#
# 唯一还需要留意的是**烧进画面的标题字卡**：横版底部约 y>1000 会被进度条压住，
# 所以 TITLE_CARD 的 y 放在 470（画心偏上），不放底部。

# ---- 语速 ----
# 第一版写的是"VO 字/秒落在 3.8~5.5"。那是个坏判据，而且坏在一个值得记住的地方：
# 它量的不是任何真正要紧的东西，于是只能靠不断调常数去迁就数据。
#   「马，也吃粮食。」5 字 1 逗号 = 2.3 字/秒 —— 短句里停顿占大头，指标本身不成立
#   扣掉逗号停顿之后，另外两句又变成"太快" —— 按下葫芦浮起瓢
#
# 真正要防的其实是两件独立的事，分开量就都不用调常数了：
#   一、**字幕读不读得完** —— 字数 / 在屏时间。这是硬判据，直接对应观众体验。
#       中文字幕的舒适上限通行值 7 字/秒（区间 5~9），取下沿。
#   二、**这一批里有没有离群的一条** —— 同一个音色、同一套参数，某条比中位数慢
#       三成，多半是 TTS 卡在专名上了（人名、地名、年份是重灾区）。
#       拿这一批自己的中位数当基准，不需要任何绝对常数，换音色也不用改。
READ_MAX = 7.0                       # 字幕可读上限，字/秒。硬判据
PACE_OUTLIER_LO, PACE_OUTLIER_HI = 0.70, 1.35   # 相对本批中位数。只提示，不拦
PACE_MIN_CHARS = 10                  # 少于这么多字不参与离群判断

# 运镜实测下限：渲出来的首尾帧平均绝对差。亮度可觉察差约 2~3 级，取 4。
MOTION_MIN = 4.0

# ================= 运镜自检的取样框 =================
# 烧录字幕时，"trace 预测的字幕底亮度"和"measure 在成片上量到的字幕底亮度"
# 必须对得上 —— 那是**唯一一处能自检运镜**的地方：对不上说明镜头没走在你以为的位置上，
# 而这比字幕糊了严重得多，且没有别的办法能发现它。
#
# 字幕外挂之后字幕框没有了，但那个自检不能跟着丢。**改成一组固定的取样框**：
# 三块（左 / 心 / 右），对平移和缩放都敏感（只取画心的话平移量不出来）。
# trace 在**源图**上按 zoompan 公式预测这三块的亮度，measure 在**渲出来的帧**上
# 量同样三块，逐条对。差 5 级以内才算运镜走对了。
PROBE_BOXES = [
    ("左", 0.06, 0.28, 0.30, 0.70),
    ("心", 0.39, 0.61, 0.39, 0.61),
    ("右", 0.72, 0.94, 0.30, 0.70),
]
# trace 与 measure 允许的差。**8 而不是 5，理由要记住**：
# 实测残差有明确形状 —— 心框 −1~−2、左右框 −3~−6，离画心越远越暗，全片同向。
# 那是 vig_factor() 对边缘暗角建模精度不足的签名，不是运镜错误。
# 运镜真错的时候长的是另一个样子：**单镜跳变、幅度 ±20~72**（转场混合帧那次就是），
# 分得很开。所以下面还会单独打每一框的平均偏差，让"全片同向"和"某镜跳变"不混在一起。
PROBE_TOL = 8.0
PROBE_EDGE = 0.05           # 离干净区两端再让开一点，躲开转场的第一/最后一帧

VO_CACHE = "vo_times.json"
_VO = {}                    # 按语言缓存：{lang: (durs_map, missing)}
_VIG_CACHE = {}
_SCRIM_CACHE = {}


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
#
# **这一支实测：生成器封顶在 1672x941。** 项目里的图文件写着 1956x1100 ~ 3733x2100，
# 那些是放大上去的。941 的短边**比成片的 1080 还小** —— 也就是说连"整幅铺满画面"
# 都要 1.15 倍放大，做不到 pp=1.0 的镜头一个也没有。
SRC_NATIVE = (1672, 941)

# ================= pp < 1.0 的显式承认 =================
# `check_resolution` 在 pp < 1.0 时拦下，因为那是"在放大"。这一支**全部 14 镜都低于
# 1.0**（0.56~0.87），而且降不下来 —— 源图短边 941 比成片短边 1080 还小。
#
# 判决性对比做过了（最差的镜 5，pp 0.56）：把文件还原到原生 1672x941，裁镜 5 最紧的
# 取景窗，分别放到 1920x1080（1.78x）和 1280x720（1.19x）。
#   同一显示尺寸下的高频方差：720p 315.1 / 1080p 284.5 —— 1080p 确实软 11%
#   但 1:1 目视：索具细线、船体笔触、浪花碎白都还是"画"的质感，没有糊
#
# **为什么 pp 判据在这里偏严**：那条曲线（pp 0.70 -> 68% 顶层细节）是拿图库**实拍
# 照片**量出来的。照片的顶层频率能量本来就多，放大丢的是真东西；油画的最高频信息
# 本来就少，"丢掉的"很多本来不存在。所以同一个 pp 值，油画看起来比照片好得多。
#
# 决定：保持 1920x1080。**但不让检查悄悄放行** —— 填了理由才降级成提示，
# 空着照旧拦下。理由会打印在 check 里，交付时也要照抄进制作说明。
# ================= 出图前的两道门禁 =================
# **出图是整条流水线上最贵、最不可逆的一步；改稿是最便宜的一步。**
# 所以这两件事必须在出图之前由**人**确认过，不是由检查通过。
# 两个都是字符串：留空 = 没确认，`budget` 会拦住；填了就是签字，内容会打印出来。
#
# 不给一个布尔开关，理由和 PP_ACCEPT_REASON 一样：True 是无痕的，
# 半年后回看没人知道当时确认了什么、改了什么。**要写人话。**
GATE_SCRIPT_OK = ""
# ↑ 讲述稿人工确认。写清楚：谁看的、什么时候、改了哪几处、还是原样通过。
#   例：'2026-08-21 用户看过，第三幕两处改写（"社会议题"删掉，换成书自己在问什么），确认可用'
#
#   为什么这一道必须是人：稿子的毛病全是**检查判不出来的那一类** ——
#   哪句话是废话、哪个转折跳了、第三幕是不是在替读者下结论。
#   `check_claims` 只管"有没有把推断说成史实"，管不了"好不好听"。

GATE_PREVIEW_OK = ""
# ↑ 只有字幕 + 声音的检查片人工确认。跑 `python 本脚本 preview` 出片，
#   交给用户听完再填。写清楚听下来改了什么。
#   例：'2026-08-21 用户听过检查片，VO_08a 重生成（原版带贬义），其余通过；片长 138.0s 认可'
#
#   这一版**能定死四件事，全在出图之前**：
#     旁白好不好听 · 断句与气口 · 字幕跟不跟得上 · **片长**（有硬线时尤其要紧）
#   真图到了直接替换同名文件，CLIPS / SHOTS / NARR 一个字都不用动。


def check_gates():
    """出图前的两道门禁。`budget` 末尾调用 —— 尺寸表照印，但不签字就不许拿去出图。

    **为什么拦在 budget 上**：budget 是"出图之前跑、把尺寸抄进任务书"的那一步，
    是流水线上最后一个还来得及改稿的位置。再往后就是花钱花时间的出图。

    **为什么是拦而不是提示**：这两件事被跳过的时候不会有任何症状 ——
    图出完了、片子渲出来了、一切检查全绿，只是稿子不好听、或者片长超了硬线。
    那时候再回头，前面所有的钱都白花。**一个只提示不拦的门禁等于没有门禁。**
    """
    me = os.path.basename(sys.argv[0])
    rows = [("讲述稿人工确认", GATE_SCRIPT_OK,
             "把%s讲述稿交给用户读一遍。稿子的毛病是检查判不出来的那一类。"
             % ("本段" if SEG_TOTAL > 1 else "")),
            ("检查片人工确认", GATE_PREVIEW_OK,
             "跑 `python %s preview` 出一支只有字幕+声音的片子，交给用户听。" % me)]
    print("")
    print("=== 出图前的两道门禁 ===")
    bad = []
    for name, val, how in rows:
        if val.strip():
            print("  [已签字] %s" % name)
            print("           %s" % val.strip())
        else:
            print("  [ 未过 ] %s" % name)
            print("           %s" % how)
            bad.append(name)
    if bad:
        print("")
        # 单独跑 `gates` 时上面没有尺寸表，别说一句不存在的东西
        from_budget = len(sys.argv) > 1 and sys.argv[1] == "budget"
        print("  %s**先不要出图**。还差 %d 道：%s"
              % ("上面的尺寸表" if from_budget else "", len(bad), "、".join(bad)))
        print("  确认完把结论写进脚本顶部的 GATE_SCRIPT_OK / GATE_PREVIEW_OK，")
        print("  **写人话，不要写 True** —— 半年后回看要知道当时确认了什么。")
        sys.exit(1)
    print("")
    print("  两道都过了，可以出图。")
    return True


PP_ACCEPT_REASON = (
    "生成器封顶 1672x941，源图短边比成片短边还小，pp 无法达到 1.0。"
    "已在最差镜（镜5 pp 0.56）做 1080p/720p 判决性对比："
    "高频方差 284.5 vs 315.1（软 11%），但 1:1 目视笔触未糊。"
    "pp 曲线是拿实拍照片量的，对油画偏严。接受软化，保持 1080p。"
)


# ================= 素材来源：任务书生成 / 自己找 =================
#   "generated"  写一份自包含的出图任务书交给用户生成（做法见 references/sourcing.md）
#   "found"      从公版开放数据、图库里找现成的。**流水线方向反过来**：
#                不是分镜提要求、图去满足，而是先看有什么图、分镜跟着图走。
#                每张必须登记来源与授权（check 会拦，credits 命令导出）。
#                讲述片比诗片更常走这一路 —— 历史题材的老照片、版画、地图
#                往往本来就有档案版本，比生成的更有说服力。
IMG_SOURCE = "generated"
CREDITS = {}        # {"01_xxx.png": dict(title=, holder=, source=, license=, url=)}

# ---- 出图尺寸按运动反推，不要写死一个"越大越好"的数 ----
#
# **实测拐点（真原生图库照片，一密一疏，两条曲线几乎重合）：**
#   pp（源像素/输出像素）  0.70   0.85   1.00   1.20   1.30   1.45
#   成片顶层细节            67%    83%    92%    98%    99%   100%
# 拐点在 1.2~1.3，**和画面类型无关**。所以尺寸只由运动决定。
# 静帧不要余量：pp=1.0 时是恒等重采样，根本不过滤波器。
#
# **上限是 PREP 不是钱包**：prep 第一步就 scale 到 PREP，源图短边超出的部分
# 在流水线第一步就被丢掉。跑 budget 看每一镜到底要多大。
PP_STATIC, PP_KENBURNS, PP_DETAIL = 1.00, 1.20, 1.30
# DETAIL_SHOTS 在上面的内容块里定义（跟着 SHOTS 一起看才有意义）。这里不要再赋值，
# 否则会把上面那份覆盖成空集 —— 所有细节镜的尺寸要求会静默降档，而 budget 照样打印得很好看。


# 项目内容由同目录 segment_config.py 覆盖；上面的模板块只是缺省值。
# **必须放在模板块之后、流水线之前** —— 放前面会被模板反过来覆盖，
# 而且不报错：素材列表、音效列表会静默变回模板的，旁白却是项目的。
import os as _os
if _os.path.exists(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                 "segment_config.py")):
    from segment_config import *          # noqa: F401,F403


# ================= 以下一般不用改 =================
def run(args, desc):
    print("\n>>> " + desc)
    if subprocess.run(args).returncode != 0:
        sys.exit("!!! 失败: " + desc)


VIDEO_FIT = "pillarbox"      # 视频镜怎么填满画框："pillarbox" 加黑边（默认）/ "crop" 裁掉
# 加黑边是默认，因为**裁掉画面会和"还剩多少"这类题材自相矛盾**，而且档案影像
# 本来就该看着像档案。要裁的片子逐镜写 fit="crop"。


PLATE_COLOR = "black"       # 贴纸版式的台纸颜色。深色片子用 black，纸本画种要改浅


def is_plate(n):
    """镜 n 是不是贴纸版式（图不裁、整张贴在台纸上）。

    **它不是"省事"的那条，是"这张图本来就不该裁"的那条。** 竖构图的海报、
    小尺寸的目录版画、档案剧照 —— 裁成 16:9 要么把主体裁没，要么把 pp 拉到
    1.0 以下靠放大硬撑。贴纸把这两件事一起解决：整张都在，而且是 1:1 不放大。

    代价是运镜全取消（台纸不动），所以只在 static 镜上用 —— check 会拦。"""
    return (CLIPS[n - 1].get("fit") == "plate") if 0 < n <= len(CLIPS) else False


def plate_box(w, h):
    """一张 w x h 的图贴在成片画框上时的 (缩放后宽, 高, 缩放系数)。

    **系数取 min(1, ...) —— 永远不放大。** 这是贴纸版式存在的全部理由：
    放大就等于回到了它要解决的那个问题。比画框大的图照常缩到画框内。"""
    f = min(1.0, W / float(w), H / float(h))
    return (max(2, int(round(w * f)) // 2 * 2), max(2, int(round(h * f)) // 2 * 2), f)


def clip_key(c):
    """CLIPS 一条用的素材文件名。视频镜写 video=，静帧/运镜镜写 src=。

    登记来源、查重、报错都要用它 —— 直接写 c["src"] 的地方一旦遇到视频镜就 KeyError，
    而且是在跑到一半才炸。"""
    return c.get("video") or c.get("src") or ""


def is_video(n):
    """镜 n(1 起) 是不是视频镜。**判据放在 CLIPS 上，不放在 SHOTS 上** ——
    素材是什么由素材那一侧说了算，SHOTS 只管时间和运动。"""
    return bool(CLIPS[n - 1].get("video")) if 0 < n <= len(CLIPS) else False


def tc(v):
    """时间码 -> 秒。接受 12.5 / "20:10" / "20:10.5" / "1:02:03"。

    分镜表上写的是 20:10 这种给人读的形式，直接当浮点数用会得到 20.0 ——
    **不报错，只是取错了地方**，所以入口统一从这里过。"""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return 0.0
    parts = s.split(":")
    if len(parts) > 3:
        sys.exit("!!! 时间码 %r 认不出来" % v)
    sec = 0.0
    for x in parts:
        sec = sec * 60 + float(x)
    return sec


def probe_video(path):
    """(宽, 高, 时长秒, fps)。拿不到就返回 None —— 让调用处自己决定是拦还是跳过。"""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height,r_frame_rate",
                        "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", path],
                       capture_output=True, text=True)
    vals = [x.strip() for x in r.stdout.split() if x.strip()]
    if len(vals) < 4:
        return None
    try:
        w, h = int(vals[0]), int(vals[1])
        num, den = (vals[2].split("/") + ["1"])[:2]
        fps = float(num) / float(den or 1)
        dur = float(vals[3])
    except (ValueError, ZeroDivisionError):
        return None
    return (w, h, dur, fps)


def video_seg(n):
    """视频镜 n 声明的 (入点秒, 出点秒, 段长秒)。"""
    c = CLIPS[n - 1]
    a = tc(c.get("ss", 0))
    b = tc(c.get("to", 0))
    return a, b, max(0.0, b - a)


def video_fit_vf():
    """把源画幅装进成片画框的滤镜段。

    **黑边是加在 prep 这一层的，不是渲染时才补。** 放在这里的好处是
    `vidNN.mp4` 出来就已经是成片尺寸，pass_a 只管切时长，转场、字幕、调色
    全都和静帧镜走同一条路 —— 视频镜因此是"第三种镜"，不是一个图层。"""
    if VIDEO_FIT == "crop":
        return ("scale=%d:%d:force_original_aspect_ratio=increase:flags=lanczos,"
                "crop=%d:%d" % (W, H, W, H))
    return ("scale=%d:%d:force_original_aspect_ratio=decrease:flags=lanczos,"
            "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black" % (W, H, W, H))


def motion_of(n):
    """镜 n(1 起) 是运镜、静帧还是视频。逐镜的 motion= 覆盖全局 MOTION。

    **视频镜由 CLIPS 决定，不看 SHOTS 的 motion=** —— 素材是一段影片这件事
    不该靠两处配置对上口径才成立。"""
    if is_video(n):
        return "video"
    return SHOTS[n - 1].get("motion", MOTION)


def is_static(n):
    return motion_of(n) == "static"


OUT_SHORT = min(W, H)
PREP_SHORT = min(PREP)
# 实测曲线：pp -> 成片保住的顶层细节（两张真原生图库照片的平均，同一镜头走完整流水线）
_PP_CURVE = [(0.70, 68), (0.85, 83), (1.00, 92), (1.20, 98), (1.30, 99), (1.45, 100)]


def detail_pct(pp):
    if pp <= _PP_CURVE[0][0]:
        return _PP_CURVE[0][1]
    for (a, va), (b, vb) in zip(_PP_CURVE, _PP_CURVE[1:]):
        if pp <= b:
            return va + (vb - va) * (pp - a) / (b - a)
    return 100.0


def pp_target(n):
    if is_static(n):
        return PP_STATIC
    return PP_DETAIL if n in DETAIL_SHOTS else PP_KENBURNS


def required_native(n):
    """镜 n 要的源图短边（裁成成片比例之后）。返回 (需要多少, 有没有被 PREP 卡住)。
    不在这里 clamp —— 卡住是要被看见的事实：再买大图也没用，得改运镜或抬 PREP。"""
    s = SHOTS[n - 1]
    z = s["z"][0] if is_static(n) else max(s["z"])
    need = pp_target(n) * z * OUT_SHORT
    return need, need > PREP_SHORT + 1


def wh(short):
    """把「短边」按成片方向印成 宽x高。横版长边在前，竖版短边在前。
    印反了任务书上就是一串方向错的尺寸，而数字本身是对的 —— 看不出来。"""
    long_ = short * max(W, H) / float(min(W, H))
    return ("%.0f x %.0f" % (long_, short)) if W >= H else ("%.0f x %.0f" % (short, long_))


def budget():
    """出图之前跑：反推每一镜要多大的图，直接抄进出图任务书。

    以前是给所有镜头一个统一的 2896x5152，那是两头错的：对缓推镜多买一倍多的
    像素，对大推镜又不够（而 flat 判据还会放行）。尺寸算得出来，就不该拍脑袋。

    ---- 但这张表有个前提：**生成器肯照着尺寸出图** ----
    《经度》段二按这里的分档写了五档（3022x1700 ~ 3733x2100，"省 32%"），
    拿回来的 13 张**全部是 1672x941**，一档都没给。段一同一个生成器也是封顶
    1672x941，只不过那次它把文件放大到 4K 存盘、这次没放大 —— 有效信息量一样。

    **封顶的生成器上，分档表只是自我安慰。** 出图之前先拿一张试出生成器的实际上限，
    再决定：换生成器，还是按那个上限直接排运镜（降 z），而不是写一张漂亮的表。

    顺带一条：源图短边小于成片短边时（941 < 1080），**连"整幅铺满画面"都要放大**，
    pp 在这个输出尺寸上永远到不了 1.0，z 只决定软到什么程度。
    真要 pp>=1.0 只能降输出（720p：静帧 1.31、运镜 z<=1.30 时 1.0）。
    """
    print("")
    print("=== 出图尺寸（按每镜的运动反推）===")
    print("   判据 pp = 源像素/输出像素。实测 pp 1.0→92%，1.2→98%，1.3→99% 的顶层细节")
    print("   静帧 %.2f（恒等重采样）/ 运镜 %.2f / 细节镜 %.2f"
          % (PP_STATIC, PP_KENBURNS, PP_DETAIL))
    print("   **流水线天花板 PREP 短边 = %d**，要得再大也会在 prep 第一步被丢掉"
          % PREP_SHORT)
    print("")
    rows, capped, tiers = [], [], {}
    for n, s in enumerate(SHOTS, 1):
        if is_video(n) or is_plate(n):   # 视频镜和贴纸镜都不按 pp 反推尺寸
            continue
        need, over = required_native(n)
        z = s["z"][0] if is_static(n) else max(s["z"])
        zoom = CLIPS[n - 1]["zoom"] if n <= len(CLIPS) else 1.0
        gen = min(need, PREP_SHORT) * zoom
        rows.append((n, need, gen, z))
        if over:
            capped.append(n)
        # **向上取整，不能四舍五入** —— 舍小了整批图都不够用
        tiers.setdefault(int(-(-gen // 100) * 100), []).append(n)
        note = ("  << 被 PREP(%d) 卡住：买再大也没用，降 z 或抬 PREP" % PREP_SHORT
                if over else ("  (细节镜)" if n in DETAIL_SHOTS else ""))
        # **尺寸要按成片的方向印**：横版是「长 x 短」，竖版是「短 x 长」。
        # 印反了任务书上就是一串竖图尺寸，而数字本身是对的，看不出来。
        print("  镜%-3d %s  z最紧 %.2f  pp %.2f  需要短边 %4.0f  出图 %s%s"
              % (n, "静帧" if is_static(n) else "运镜", z, pp_target(n), need,
                 wh(gen), note))
    print("")
    print("=== 分档（出图任务书按这个写）===")
    for k in sorted(tiers, reverse=True):
        print("  %-12s %2d 镜：%s"
              % (wh(k), len(tiers[k]), ", ".join(str(i) for i in tiers[k])))
    tot = sum(r[2] ** 2 for r in rows)
    print("")
    print("  合计像素相对「一律 4K（短边 2160）」： %.0f%%（省 %.0f%%）"
          % (100.0 * tot / (len(rows) * 2160.0 ** 2),
             100 * (1 - tot / float(len(rows) * 2160.0 ** 2))))
    if capped:
        print("")
        print("  !! 镜 %s 的 z 超出 PREP 的能力。这不是素材问题，是流水线天花板："
              % ", ".join(str(i) for i in capped))
        print("     prep 把源图压到 %d，再大的源图也补不回来。" % PREP_SHORT)
    print("")
    print("  上面是**裁成成片比例之后**的尺寸要求，已按 CLIPS 的 zoom 折回。")
    print("  生成器出不了 16:9 的话还要再除裁切损失（出 3:2 裁 16:9 只剩 89%）。")
    print("  **务必显式指定尺寸** —— 很多工具默认出 1K，那样只剩六成细节，这一条被坑过两次。")
    # **拦在这里，不拦在别处。** budget 是"出图之前跑、把尺寸抄进任务书"的那一步，
    # 也是流水线上最后一个还来得及改稿的位置。再往后就是花钱花时间的出图。
    check_gates()


def music_on():
    return MUSIC_MODE != "none"


def norm_mode():
    """成片的响度归一策略。

    loudnorm 的整合响度是**带门限**的（−70 绝对门 + 相对门），静音段会被剔掉，
    量到的是"出声段落的平均"。有连续音床时这正是要的；只剩几条稀疏音效时，
    门限会把整合响度变成那几条音效自己的响度，归一等于把 SFX 表里逐条写的
    目标响度全部作废，一层本该若有若无的环境声会被硬抬到 −15 LUFS。

    讲述片几乎总有旁白，所以基本走 loudnorm；这个分支是为"只剩音效"的
    极端配置留的，别让它悄悄走错。
    """
    return "loudnorm" if (music_on() or NARR) else "absolute"


def est_of(n):
    """这一条还没生成时的估算时长。

    **NARR 里的 est 是可选的，能不写就不写。** 手写 est 要人去数字数，而数字数
    要扣标点 —— 段二 37 条里手写错了 20 条，差值全是 ±1 个字（1/EST_RATE≈0.24s），
    积起来把段长算少了 2.1s。这是个不该存在的错误类别：**这个数是算得出来的。**
    写了就用写的（比如某条明知会读得特别慢），没写就按 EST_RATE 从文本推。
    """
    if n.get("est") is not None:
        return n["est"]
    return n_chars(n["txt"]) / EST_RATE


def n_words(txt):
    """英文按**词**数算，不按字符数 —— 换算「还得砍几个词」时要的是词。"""
    return len([w for w in re.split(r"\s+", " ".join(sub_lines(txt or ""))) if w])


def lang_text(n, lang):
    return n["txt"] if lang == DEFAULT_LANG else (n.get(lang) or "")


def srt_name(lang):
    return "%s%s.srt" % (SEG_NAME, LANG_INFO[lang]["srt_suffix"])


def vo_path(n, lang=None):
    lang = lang or DEFAULT_LANG
    f = n["vo"] if n["vo"].lower().endswith((".mp3", ".wav", ".m4a")) else n["vo"] + ".mp3"
    return os.path.join(VO_DIR_OF.get(lang, VO_DIR), f)


def vo_cache_of(lang):
    return VO_CACHE if lang == DEFAULT_LANG else "vo_times_%s.json" % lang


def est_of_lang(n, lang):
    """这一条还没生成时的估算时长。

    非默认语言只有量过语速（EN_RATE）之后才估得准；没量过就退回中文那一条的估算。
    **这个回退值不是给人拿去排片的** —— 缺文件这件事本身由 check_langs 报出来，
    这里只是让流水线在缺文件时还能跑完把表打出来。
    """
    if lang == DEFAULT_LANG:
        return est_of(n)
    if EN_RATE:
        return n_words(lang_text(n, lang)) / EN_RATE
    return est_of(n)


def vo_durs(lang=None):
    """量每条旁白的实测时长，按 (文件, mtime, 大小) 缓存。

    时间轴是**量出来的，不是排出来的** —— 换了配音重新生成，时间轴自动跟着变。
    手工回填一定会漏一条，而漏掉的那一条要到成片才听得出来。
    mp3 还没生成时回退到 est，并让 check 大字提醒时间轴是估算的。"""
    lang = lang or DEFAULT_LANG
    if lang in _VO:
        return _VO[lang]
    cache_path = vo_cache_of(lang)
    cache = {}
    if os.path.exists(cache_path):
        try:
            cache = json.load(open(cache_path, encoding="utf-8"))
        except (ValueError, OSError):
            cache = {}
    out, missing, dirty = {}, [], False
    for n in NARR:
        p = vo_path(n, lang)
        if not os.path.exists(p):
            missing.append(n["vo"]); out[n["vo"]] = (est_of_lang(n, lang), False); continue
        st = os.stat(p)
        key = "%s|%d|%d" % (n["vo"], int(st.st_mtime), st.st_size)
        if key not in cache:
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                "format=duration", "-of", "csv=p=0", p],
                               capture_output=True, text=True)
            try:
                cache[key] = float(r.stdout.strip())
            except ValueError:
                cache[key] = est_of_lang(n, lang)
            dirty = True
        out[n["vo"]] = (cache[key], True)
    if dirty:
        try:
            json.dump(cache, open(cache_path, "w", encoding="utf-8"))
        except OSError:
            pass
    _VO[lang] = (out, missing)
    return _VO[lang]


def per_shot():
    """每一镜下面挂着哪几条旁白（NARR 的下标）。timeline 和双语两边都要用它，
    抄成两份迟早会分叉。"""
    per = [[] for _ in range(len(SHOTS))]
    for k, n in enumerate(NARR):
        if not 1 <= n["shot"] <= len(SHOTS):
            sys.exit("!!! 旁白 %s 的 shot=%d 超出 %d 镜" % (n["vo"], n["shot"], len(SHOTS)))
        per[n["shot"] - 1].append(k)
    return per


def pads(k, per):
    """第 k 条旁白前后的静默。镜与镜之间的气口自动抬到 GAP_PRE / GAP_POST ——
    转场就落在这段静默的正中，于是永远压不到字幕。"""
    n = NARR[k]
    pre = n.get("pre", PRE_DEF)
    post = n.get("post", POST_DEF)
    if k == per[n["shot"] - 1][0]:
        pre = max(pre, GAP_PRE)
    if k == per[n["shot"] - 1][-1]:
        post = max(post, GAP_POST)
    return pre, post


def timeline():
    """由旁白实测时长推出整条时间轴。

    内容时间是连续的：镜 i 占 [S_i, S_i + D_i)，D_i = Σ(pre + 实测 + post)。
    **xfade 骑在边界正中**（起点 S_{i+1} − xf/2），所以每镜要渲的长度是

        dur_i = D_i + xf(i)/2 + xf(i−1)/2

    这样 total = Σdur − Σxf = ΣD，而转场中点恰好落在 S_{i+1} ——
    也就是两句旁白之间那段静默的正中。转场只挂在边界上、不去骑字幕，
    是讲述片和诗片最容易搞错的一处：诗片一句一镜，气口天然在句间；
    讲述片旁白是连着的，不把边界对准静默，十三个转场会条条压字。

    返回 (lines, durs, total, starts)：
      lines = [(字幕起, 字幕止, 文本, 镜号, 旁白起, 旁白时长), ...]
      starts = 每镜的**内容**起点 S_i（不是渲出来那段片子的起点，见 clip_starts）
    """
    durs_map, _ = vo_durs()
    n_shots = len(SHOTS)
    per = per_shot()
    D = []
    for i in range(n_shots):
        if per[i]:
            d = sum(sum(pads(k, per)) + durs_map[NARR[k]["vo"]][0] for k in per[i])
        else:
            d = SHOTS[i].get("dur", 3.0)        # 没有旁白的镜必须自己写 dur
        D.append(d + (TAIL if i == n_shots - 1 else 0.0))
    # ---- 段长吸到整帧 ----
    # 分段片 concat 时，每段差半帧就会累积成 A/V 漂移。
    # **但不要让人手工调 TAIL 去凑** —— 段长是旁白实测推出来的，换一次配音就得再凑一次，
    # 那是"靠不断调常数去迁就检查"，这条流水线明确反对。
    # TAIL 是软值（旁白收完之后多留一会儿），**向上**取整最多拉长不到一帧，听不出来，
    # 而且只加不减，不会把留白吃掉。check_seg 仍然验一遍，但那是复核不是要人动手。
    raw = sum(D)
    D[-1] += -(-raw * FPS // 1) / FPS - raw
    starts, t = [], 0.0
    for d in D:
        starts.append(t); t += d
    lines = []
    for i in range(n_shots):
        c = starts[i]
        for k in per[i]:
            n = NARR[k]
            pre, post = pads(k, per)
            vd = durs_map[n["vo"]][0]
            vs = c + pre
            # 字幕比声音早 0.10s 起、晚一点收 —— 早一点跟上，晚一点让人读完
            lines.append((max(0.0, vs - 0.10), vs + vd + min(post, 0.35),
                          n["txt"], i + 1, vs, vd))
            c = vs + vd + post
    durs = [D[i] + (xf(i) / 2 if i < n_shots - 1 else 0.0)
            + (xf(i - 1) / 2 if i > 0 else 0.0) for i in range(n_shots)]
    return lines, durs, sum(D), starts


def xf(i):
    """镜 i(0 起) 转到下一镜的溶解时长。转场是叙事标点，不该是常数：
    钩子后 0.4~0.5 硬切；段落翻页 1.8~2.2 长溶解；转折后 0.4 短切；金句 2.0 叠化。"""
    return SHOTS[i].get("xf", XFADE)


def total_len():
    return timeline()[2]


def shot_starts():
    return timeline()[3]


def clip_starts():
    """每镜渲出来那段片子在成片上的起点 = S_i − xf(i−1)/2（转场骑在边界正中）。
    trace 反查取景窗时要用它算镜内局部时刻，用 S_i 会偏半个转场。"""
    st = shot_starts()
    return [st[i] - (xf(i - 1) / 2 if i > 0 else 0.0) for i in range(len(SHOTS))]


def cut_points():
    """转场中点 = 内容边界 S_{i+1}，也就是两句旁白之间那段静默的正中。"""
    return shot_starts()[1:]


def lang_slots():
    """每一句留给别的语言的空间：(中文实测时长, 可借的静默)。

    **镜末那一句借不到东西。** 镜末的静默正中骑着转场（理由见 timeline 的注释），
    借了就是把话说到转场底下去 —— 而这件事在参数表和波形上都看不出来，
    要放出来听才发现。镜内的句子可以从后面那段气口里借一点，但最多借一半：
    剩下的一半是气口本身，把气口借光了英文那条轨会变成连珠炮。
    """
    zh, _ = vo_durs(DEFAULT_LANG)
    per = per_shot()
    out = []
    for k, n in enumerate(NARR):
        _, post = pads(k, per)
        grp = per[n["shot"] - 1]
        pos = grp.index(k)
        if pos == len(grp) - 1:
            # **镜末可以借到「转场开始之前」为止，不是一点都不能借。**
            # 原来写死 0.0，理由是"镜末的静默正中骑着转场"。那个理由只对了一半：
            # 转场骑在镜界正中、宽 xf，所以它是从 post 段里 (post - xf/2) 处才开始的，
            # 在那之前的静默是干净的。而且音频是一条**连续混音**，并不在镜界切开 ——
            # 说到转场底下去是编辑上的忌讳，不是技术上的错。
            # 借到转场起点为止，等于"话说完，画面才开始溶解"，这正是想要的。
            #
            # 这一条按**实际转场宽度**算，不是给一个固定的宽限：
            # 转场长的镜（比如时间跳跃用的 1.4s 长溶解）算出来仍然是 0，
            # 2026-08-31《四十二年》镜59→60 就是这种情况，实测 borrow=0.00。
            i = n["shot"] - 1
            half = (xf(i) / 2.0) if i < len(SHOTS) - 1 else 0.0
            borrow = max(0.0, min(LANG_BORROW, post - half - 0.02))
        else:
            gap = post + pads(grp[pos + 1], per)[0]
            borrow = min(LANG_BORROW, gap / 2.0)
        out.append((zh[n["vo"]][0], borrow))
    return out


def lang_lines(lang=None):
    """某条语言的字幕行，字段和 timeline() 的 lines 完全一样。

    **起点一律沿用中文定出来的槽** —— 画面只有一份，起点动了就不是多音轨了。
    只有收尾跟着这条语言自己的音频走：英文那句短一点，字幕就早一点收。
    """
    lang = lang or DEFAULT_LANG
    zh_lines = timeline()[0]
    if lang == DEFAULT_LANG:
        return zh_lines
    durs_map, _ = vo_durs(lang)
    per = per_shot()
    out = []
    for k, n in enumerate(NARR):
        _, post = pads(k, per)
        vs = zh_lines[k][4]
        vd = durs_map[n["vo"]][0]
        out.append((max(0.0, vs - 0.10), vs + vd + min(post, 0.35),
                    lang_text(n, lang), n["shot"], vs, vd))
    return out


def sfx_dur(e):
    """音效该放多长。**优先写 span（盖几镜），不要写死 dur。**

    写死秒数的毛病和当初手写 est 一模一样：旁白一改，镜长就变，
    而秒数不会跟着变 —— 它不报错，只是悄悄错位。段五头一版就踩了：
    照着 budget 打印的**渲染长**填 dur（每镜含两侧各半个 xfade，比内容长约 1s），
    于是镜 7~9 那条房间底噪多压了 3 秒进镜 10，盖在该由钟声独占的地方。
    参数表上完全看不出来，要把起止秒数打出来对才发现。

    span=n 表示从这一镜起盖 n 镜的**内容**，尾巴伸到最后那个转场的正中 ——
    也就是画面正好 50/50 的那一帧。声音在那里断，是断在切点上而不是切点后。
    """
    if e.get("dur") is not None:
        return e["dur"]
    st, total = shot_starts(), total_len()
    i = e["shot"] - 1
    j = min(i + e.get("span", 1), len(SHOTS))          # 末镜下标 +1
    # **不要再加 xf/2。** 转场骑在内容边界正中（见 cut_points），
    # 所以画面 50/50 的那一帧就是 st[j] 本身，加半个转场是往后多伸了。
    end = st[j] if j < len(SHOTS) else total
    # **起点要和混音处用同一个夹过的值。** 混音里是 max(0, st+off)，
    # 这里如果直接用 st+off，负的 off（镜 1 那种"提前进来"）就会把长度多算 |off|，
    # 尾巴越过切点 —— 半秒的事，听不出来，但它是错的。
    return max(0.1, end - max(0.0, st[i] + e.get("off", 0.0)))


def shot_of(t):
    n = 1
    for i, s in enumerate(shot_starts(), 1):
        if t >= s - 1e-6:
            n = i
    return n


def sub_lines(txt):
    return [p for p in txt.split(SUB_SEP) if p]


def text_w(s):
    """一行字的像素宽。按字形宽度算，不按字数 —— 数字和西文只有汉字的一半多一点，
    按字数判会把「1815 年 4 月，印尼松巴哇岛，」这种排得下的行误判成超标。"""
    return sum(ASCII_W if ord(c) < 0x2E80 else 1.0 for c in s) * SUB_FS


def sub_box(txt, pad=8):
    """字幕在画面上的外接矩形（x0, x1, y0, y1），用来量它压着的底、判安全区。"""
    parts = sub_lines(txt)
    w = max(text_w(p) for p in parts)
    top = SUB_BOT - len(parts) * SUB_LH
    return (max(0, int(SUB_CX - w / 2 - pad)), min(W, int(SUB_CX + w / 2 + pad)),
            max(0, int(top - pad)), min(H, int(SUB_BOT + pad)))


# ================= 渲染前的自检 =================
def check_claims():
    """讲历史唯一致命的错误是把推断说成史实。

    **分段片和单支片在这里不一样。** CLAIMS 是**全片**的表：假说可能在段二抛出、
    段五才自拆。所以"必须在片内自拆"这条只在 SEG_LAST 上验 ——
    否则前四段每一段都会报一条它根本无法满足的警，
    而一个长期报假警的检查等于没有检查（这条教训在 trace/vignette 上付过学费）。
    """
    bad = []
    print("\n=== 事实分级（全片表，本段 %d/%d）===" % (SEG_INDEX, SEG_TOTAL))
    for cid, lvl, what, note in CLAIMS:
        print("  %-4s %-4s %-34s %s" % (cid, lvl, what, note))
    hyp = [c for c in CLAIMS if c[1] == "假说"]
    if hyp and not SEG_LAST:
        print("  -> %d 条假说（%s）：本段不是最后一段，自拆检查留给段 %d"
              % (len(hyp), "/".join(c[0] for c in hyp), SEG_TOTAL))
    elif hyp:
        # 窗口是**尾板那一段**，不是"最后三句"。后者是按 13 镜的排法定的；
        # 镜数一多（21 镜时尾板会跨最后两镜），自拆句就掉出窗口，报假警。
        # 语义上要查的单位是尾板，不是一个固定的句数。
        last = NARR[-1]["shot"]
        tail = "".join(n["txt"] for n in NARR if n["shot"] >= last - 1)
        # "证明不了/说明不了" 和 "是主流推断" 一样是标准的自拆句式，原表里漏了。
        hit = any(w in tail for w in ("推断", "假说", "存疑", "并没有", "没有这么", "不是",
                                      "证明不了", "说明不了"))
        # 第二条路：**画面角标**。这个检查的理由是"看简介的人不到十分之一"，
        # 而烧在画面上、跟着那几镜一直在的角标，比一句旁白更满足这个理由
        # （旁白只说一次，角标在整段展示期间都在）。
        # 但只认带披露词的角标，纯署名（"NASA/GSFC"）不算自拆。
        vis = [(sn, tx) for sn, tx in sorted(SHOT_LABELS.items())
               if any(w in tx for w in ("Reconstruction", "reconstruction",
                                        "Model", "model", "复原", "模型"))]
        if not hit and vis:
            hit = True
            print("  -> %d 条假说，靠画面角标披露：镜 %s"
                  % (len(hyp), "/".join(str(sn) for sn, _ in vis)))
        elif hit:
            print("  -> %d 条假说，结尾已自我拆解" % len(hyp))
        if not hit:
            bad.append("CLAIMS 里有 %d 条『假说』(%s)，尾板旁白里没有自我拆解，"
                       "画面上也没有带披露词的角标（SHOT_LABELS）。"
                       "假说必须**在片内**说出来或标出来 —— 看简介的人不到十分之一"
                       % (len(hyp), "/".join(c[0] for c in hyp)))
    return bad


def n_chars(txt):
    return sum(1 for ch in "".join(sub_lines(txt)) if ch not in "，。：；、？！—…「」《》 ")


def check_pace():
    """两件独立的事，分开量（为什么不用「VO 字/秒落在某个区间」见常数处的注释）：

    一、**字幕读不读得完** —— 字数 / 在屏时间，硬判据。
    二、**这一批里有没有离群的一条** —— 拿本批中位数当基准，不用绝对常数。
        同一个音色同一套参数，某条明显偏慢，多半是 TTS 卡在专名上了。
    """
    durs_map, _ = vo_durs()
    lines = timeline()[0]
    bad = []
    rows = []
    for n, ln in zip(NARR, lines):
        d, real = durs_map[n["vo"]]
        c = n_chars(n["txt"])
        rows.append((n["vo"], d, real, c, c / d if d else 0, ln[1] - ln[0]))
    pool = sorted(p for _, _, real, c, p, _ in rows if real and c >= PACE_MIN_CHARS)
    med = pool[len(pool) // 2] if pool else 0

    print("\n=== 旁白与字幕（本批中位语速 %.1f 字/秒）===" % med)
    print("   在屏 = 字幕停留时间；读速上限 %.1f 字/秒" % READ_MAX)
    for vo, d, real, c, p, on in rows:
        flag = ""
        if on > 0 and c / on > READ_MAX:
            flag = "  << 字幕读不完"
            bad.append("字幕『%s』%d 字只停 %.1fs（%.1f 字/秒），超过可读上限 %.1f"
                       % (vo, c, on, c / on, READ_MAX))
        elif real and c >= PACE_MIN_CHARS and med:
            r = p / med
            if not (PACE_OUTLIER_LO <= r <= PACE_OUTLIER_HI):
                flag = "  << 比本批中位%s %.0f%%，检查专名是否读不顺" % (
                    "慢" if r < 1 else "快", abs(1 - r) * 100)
        print("  %-11s %5.2fs %2d字  语速 %.1f  在屏 %4.1fs  读速 %.1f%s%s"
              % (vo, d, c, p, on, c / on if on else 0,
                 "" if real else "  (估算)", flag))
    return bad


def check_subs():
    bad = []
    for st, en, txt, _, _, vd in timeline()[0]:
        parts = sub_lines(txt)
        if len(parts) > 2:
            bad.append("字幕『%s』断成了 %d 行，一屏最多两行" % (txt, len(parts)))
        for p in parts:
            # 外挂字幕按**字数**判，不按像素宽 —— 播放器的字号我们管不着
            if len(p) > SUB_MAX_CHARS:
                bad.append("字幕行『%s』%d 字，超过一行上限 %d —— "
                           "在稿子里用 %s 手工断行" % (p, len(p), SUB_MAX_CHARS, SUB_SEP))
        if en - st < vd:
            bad.append("字幕『%s』在屏 %.1fs，短于它自己的旁白 %.1fs" % (txt, en - st, vd))
    return bad


def check_langs(quiet=False):
    """多音轨的自检。四件事，都是「单看中文那条轨完全正常」的那一类：

      一、每一条旁白有没有写英文
      二、英文音频齐不齐
      三、**逐句对不对得上槽** —— 量的是**磁盘上的文件**，不是 langfit 当时的结论
      四、英文字幕一行有没有超长

    第三条是这里唯一会**静默出错**的：英文音频长出槽去，不报错、不崩、
    波形上也看不出来，只会让那句话说到转场底下去 —— 而你手上放的是中文版，
    一切正常。所以它必须在每次 check 时从文件重新量，
    "改了翻译、重新生成、忘了跑 langfit" 就是靠这一条拦住的。
    """
    bad = []
    lang_warn = []
    if len(LANGS) <= 1:
        return bad
    slots = lang_slots()
    for lang in LANGS:
        if lang == DEFAULT_LANG:
            continue
        info = LANG_INFO.get(lang)
        if not info:
            bad.append("LANGS 里的 %r 在 LANG_INFO 里没有登记" % lang)
            continue
        no_txt = [x["vo"] for x in NARR if not x.get(lang)]
        if no_txt:
            bad.append("%d 条旁白没写 %s 文本（%s%s）"
                       % (len(no_txt), lang, ", ".join(no_txt[:3]),
                          "..." if len(no_txt) > 3 else ""))
        durs_map, missing = vo_durs(lang)
        if missing:
            bad.append("%s 轨还缺 %d 条音频（%s%s），要放在 %s/ 下"
                       % (info["name"], len(missing), ", ".join(missing[:3]),
                          "..." if len(missing) > 3 else "",
                          VO_DIR_OF.get(lang, lang)))
        over = []
        if not quiet:
            print("\n=== %s 轨逐句对槽（槽是中文定的，%s 塞进去）==="
                  % (info["name"], info["name"]))
        for k, x in enumerate(NARR):
            base, borrow = slots[k]
            room = base + borrow
            d, real = durs_map[x["vo"]][0], durs_map[x["vo"]][1]
            if not real:
                continue
            flag = ""
            if d > room + 0.02:
                flag = "  << 超 %.2fs" % (d - room)
                grp = per_shot()[x["shot"] - 1]
                at_end = grp.index(k) == len(grp) - 1
                over.append((x["vo"], d - room, at_end))
            if not quiet:
                print("  %-11s 槽 %5.2f(+%.2f 可借)  实测 %5.2f%s"
                      % (x["vo"], base, borrow, d, flag))
        # **镜末句和镜内句要分开判，不能一起放行。**
        # 镜内句超出的两三百毫秒吃的是后面那段气口；镜末句的静默正骑在转场上，
        # 超了就是把话说到溶解底下去 —— 那件事在参数表和波形上都看不出来。
        # 第一版的 LANG_ACCEPT_REASON 把两种一起降级，回归自测当场报
        # 「镜末那条英文超槽 → 多报 0 条 —— 检查失效了」：**开的口子太大**。
        ends = [z for z in over if z[2]]
        mids = [z for z in over if not z[2]]
        for grpz, tail, always_block in ((ends, "**镜末**", True), (mids, "镜内", False)):
            if not grpz:
                continue
            worst = max(grpz, key=lambda z: z[1])
            msg = ("%s 轨有 %d 条%s句塞不进中文的槽（最长的 %s 超 %.2fs）—— "
                   "跑 `python make_story_h.py langfit %s`；"
                   "压不进去的那几句它会报出还得砍几个词"
                   % (info["name"], len(grpz), tail, worst[0], worst[1], lang))
            if always_block:
                bad.append(msg + " —— **镜末不接受妥协**：那段静默骑在转场上，"
                                 "超出去就是把话说到溶解底下")
                continue
            # **有时候砍不动。** "All true." 两个词已经是地板，砍掉 "All" 就丢了
            # 「那三个数**都**对」这个全部内容；核心数字那一句两个单位都不能省。
            # 强行砍是拿内容换一个判据过关，那不是修好。
            #
            # 所以和 REUSE_ACCEPT_REASON / PP_ACCEPT_REASON 一个形状：
            # **填了理由就降级成提示，空着照旧拦下，不给静默绕过的开关。**
            # 理由每次 check 都打印，交付时要照抄进制作说明的「哪几处是妥协的」。
            #
            # 判断该不该填，看**超的那几条在不在镜末**：镜内句超出的两三百毫秒
            # 吃的是气口；镜末句的静默正骑在转场上，超了就是把话说到溶解底下去。
            if str(LANG_ACCEPT_REASON).strip():
                lang_warn.append(msg)
            else:
                bad.append(msg)
        for x in NARR:
            parts = sub_lines(x.get(lang) or "")
            # **行数也要验。** 原来只验行长，于是「一条断成三行」整个溜过去 ——
            # 中文那一路 check_subs 一直验着这一条，非默认语言这边漏了。
            # 2026-08-31《四十二年》：英文 VO_08 写了两个 ｜＝三行字幕，check 照样通过。
            # 一屏两行是硬约束（`SUB_MAX_CHARS_EN` 是按两行算的），三行会被播放器截掉或压扁。
            if len(parts) > 2:
                bad.append("%s 字幕『%s』断成了 %d 行，一屏最多两行 —— 一条里只能有一个 %s"
                           % (info["name"], (x.get(lang) or "")[:30], len(parts), SUB_SEP))
            for p in parts:
                if len(p) > SUB_MAX_CHARS_EN:
                    bad.append("%s 字幕行『%s』%d 字，超过一行上限 %d —— 用 %s 手工断行"
                               % (info["name"], p[:34], len(p), SUB_MAX_CHARS_EN, SUB_SEP))
    if lang_warn:
        print("")
        print("=== 多音轨对槽（%d 处超出，**已显式承认**）===" % len(lang_warn))
        for w in lang_warn:
            print("  " + w)
        print("  理由：" + LANG_ACCEPT_REASON.strip())
        print("  交付时这一条要照抄进制作说明的「哪几处是妥协的」。")
    return bad


def selftest_langs():
    """回归：把双语的三种错法逐个造出来，检查必须报警。

    造错的办法是**换掉 NARR 和 vo_durs**，不去碰磁盘 —— 自测不该依赖
    这台机器上有没有英文配音文件，否则它会在没有文件的机器上"通过"。
    """
    global LANGS, NARR, vo_durs, _VO
    keep = (LANGS, NARR, vo_durs, _VO)
    base = [
        dict(vo="T1", shot=1, txt="第一句。", en="First line."),
        dict(vo="T2", shot=1, txt="第二句。", en="Second line."),
        dict(vo="T3", shot=2, txt="第三句。", en="Third line."),
    ]
    zh = {"T1": 3.0, "T2": 3.0, "T3": 3.0}

    def fake(en_map):
        def f(lang=None):
            m = zh if (lang or DEFAULT_LANG) == DEFAULT_LANG else en_map
            return ({x["vo"]: (m[x["vo"]], True) for x in NARR}, [])
        return f

    def count(narr, en_map):
        global NARR, vo_durs, _VO
        NARR, vo_durs, _VO = narr, fake(en_map), {}
        return len(check_langs(quiet=True))

    LANGS = ["zh", "en"]
    fit = {"T1": 3.0, "T2": 3.0, "T3": 3.0}
    # T3 是镜 2 里唯一一条 = 镜末，借不到静默，槽就是 3.0
    cases = [
        ("有一条没写英文", [base[0], base[1], dict(base[2], en="")], fit),
        ("镜末那条英文超槽", base, dict(fit, T3=4.2)),
        ("英文字幕一行超长", [dict(base[0], en="x" * (SUB_MAX_CHARS_EN + 5))] + base[1:], fit),
        # 断成三行：每行都不超长，只有**行数**不对 —— 原来这一条整个溜过去
        ("英文字幕断成三行",
         [dict(base[0], en="aa%sbb%scc" % (SUB_SEP, SUB_SEP))] + base[1:], fit),
    ]
    ok = True
    results = [(name, count(narr, em)) for name, narr, em in cases]
    now = count(base, fit)
    LANGS, NARR, vo_durs, _VO = keep
    for name, c in results:
        print("回归自测: %s → 报警 %d 条 —— %s"
              % (name, c, "对" if c else "**检查失效了**"))
        ok = ok and c > 0
    print("          %d 条都合规 报警 %d 条 —— %s"
          % (len(cases), now, "对" if now == 0 else "**误报**"))
    return ok and now == 0


def check_seg(quiet=False):
    """分段片独有的自检。三条，都是「单看这一段完全正常、拼起来才坏」的那类。

    `quiet` 给回归自测用 —— 自测要连跑三遍，每遍都打一屏会把真正的输出淹掉。
    """
    bad = []
    total = total_len()
    say = (lambda *a: None) if quiet else (lambda s: print(s))
    say("\n=== 分段 %d/%d ===" % (SEG_INDEX, SEG_TOTAL))

    # 一、段长必须落在整帧上。差半帧看不出来，五段累加就是 A/V 漂移。
    # timeline() 已经自动吸过了，所以这里是**复核**：报警说明吸的逻辑坏了，
    # 不是要人去调 TAIL（手工凑常数，换一次配音就得再凑一次）。
    frames = total * FPS
    off = abs(frames - round(frames))
    if off > 1e-6:
        bad.append("段长 %.4fs = %.3f 帧，不是整帧（差 %.3f 帧）—— "
                   "timeline() 的整帧吸附失效了，查那一段，别手工调 TAIL"
                   % (total, frames, off))
    else:
        say("  段长 %.4fs = %d 帧，整帧对齐 ✓（TAIL 自动吸的，不用管）"
            % (total, round(frames)))

    # 二、淡场归属。中间段两头都不能有黑场，否则每三分钟黑一次。
    if SEG_FIRST and FADE_IN <= 0:
        bad.append("这是第一段，但 FADE_IN=0 —— 全片没有开场淡入")
    if not SEG_FIRST and FADE_IN > 0:
        bad.append("这不是第一段，但 FADE_IN=%.1f —— 接缝处会黑一次" % FADE_IN)
    if SEG_LAST and FADE_OUT <= 0:
        bad.append("这是最后一段，但 FADE_OUT=0 —— 全片没有收尾")
    if not SEG_LAST and FADE_OUT > 0:
        bad.append("这不是最后一段，但 FADE_OUT=%.1f —— 接缝处会黑一次" % FADE_OUT)
    say("  淡场: 入 %.1fs / 出 %.1fs（预览另加 %.1fs 淡出，不进段用文件）"
        % (FADE_IN, FADE_OUT, PREVIEW_FADE_OUT))

    # 三、尾板只属于最后一段
    if ENDCARD and not SEG_LAST:
        bad.append("非最后一段却有 ENDCARD —— 尾板会在片子中间出现")
    return bad


def selftest_seg():
    """回归：把三条分段规矩逐条弄错，检查必须报警。
    一个永远不报警的检查比没有检查更糟 —— 这条教训在 check_safe 的解包顺序上付过。"""
    global TAIL, FADE_OUT, SEG_LAST
    ok = True
    kt, kf, kl = TAIL, FADE_OUT, SEG_LAST

    # 整帧那一条现在由 timeline() 自动吸，所以造错要绕过吸附本身 —— 直接篡改
    # total_len 的返回值，检查必须发现"段长不是整帧"。这才是它真正要防的东西：
    # 吸附逻辑坏掉而没人知道。
    global total_len
    keep = total_len
    total_len = lambda: keep() + 0.0137
    n1 = len(check_seg(quiet=True))
    total_len = keep
    FADE_OUT = 3.0; SEG_LAST = False        # 非末段却有片尾淡出
    n2 = len(check_seg(quiet=True)); FADE_OUT, SEG_LAST = kf, kl
    now = len(check_seg(quiet=True))

    for name, n in (("段长错开半帧", n1), ("非末段加了片尾淡出", n2)):
        print("回归自测: %s → 报警 %d 条 —— %s"
              % (name, n, "对" if n else "**检查失效了**"))
        ok = ok and n > 0
    print("          当前配置 报警 %d 条 —— %s" % (now, "对" if now == 0 else "有问题"))
    return ok and now == 0


def _win(sh, p, clip=None):
    """镜 sh 在进度 p(0~1) 时的取景窗：(左, 右, 上, 下, 占画面比例)。

    **给了 clip 就换算到「源图」坐标系。** CLIPS 的 zoom/cx/cy 是 prep 阶段的裁切，
    prep 为每一镜产出它自己的 imgNN —— 所以相邻两镜共用同一张源图时，
    只比 SHOTS 的 z/f 会**漏掉这一层**：明明已经用 cx/cy 切到画面另一块去了，
    check_reuse 仍然报「取景没分开」，而且报的是 100.0% / 窗心移动 0.000
    （z 恒为 1 的静帧镜必然如此），看起来完全像配置写错了。

    这和 trace 少算 vignette / scrim 是同一个形状的坑：**筛子少建模了流水线里的
    一道，于是长期报假警。** 技能文档说的省图手段本来就是「CLIPS 里 cx/cy/zoom
    不同」，判据却只看 SHOTS —— 两边对不上，要补的是判据。
    （2026-08-25《潘多拉的瓮》：33 镜里 9 处假警，全部是已经切开了的。）
    """
    z = sh["z"][0] + (sh["z"][1] - sh["z"][0]) * p
    half = 1 / (2 * z)
    fx = min(max(sh["f0"][0] + (sh["f1"][0] - sh["f0"][0]) * p, half), 1 - half)
    fy = min(max(sh["f0"][1] + (sh["f1"][1] - sh["f0"][1]) * p, half), 1 - half)
    if clip is None:
        return (fx - half, fx + half, fy - half, fy + half, 1.0 / z)
    cz = clip.get("zoom", 1.0) or 1.0
    cx, cy = clip.get("cx", 0.5), clip.get("cy", 0.5)
    # prep 窗在源图上：中心 (cx,cy)、边长 1/cz；SHOTS 窗再在它里面取 1/z。
    h = half / cz
    return (cx + (fx - 0.5) / cz - h, cx + (fx - 0.5) / cz + h,
            cy + (fy - 0.5) / cz - h, cy + (fy - 0.5) / cz + h,
            1.0 / (z * cz))


REUSE_TIGHTEN = 0.80        # 后一镜的取景至少要收到前一镜的这个比例
REUSE_SHIFT = 0.12          # 或者窗心至少移动这么多（占画幅）
# 填了理由就降级成提示，空着照旧拦下。**不给静默绕过的开关** ——
# 那样下一支照抄配置时就再也不知道这里做过妥协了。理由会打印在每次 check 里。
REUSE_ACCEPT_REASON = ""


def check_reuse():
    """**相邻两镜用同一张图时，第二镜必须真的换了取景。**

    「一图两镜」是这条流水线省图的主要手段，但它有个前提：两个取景窗要分得开。
    分不开就不是两镜，是**同一镜中间被硬切了一刀** —— 观众读作跳接，
    而那一镜的时长全部浪费掉。

    《经度》段二镜 6/7 就是这么坏的：镜 6 是木钟机芯全貌、镜 7 本该切进齿轮咬合，
    结果**镜 7 的起幅取景 76.9% 反而比镜 6 的落幅 74.6% 更宽** ——
    想切近，实际切远了。渲完看静帧才发现两镜几乎一模一样，12.8s 白花。

    参数表上完全看不出来：两镜的 z 都写着 1.3~1.5，看着"差不多"，
    而"差不多"正是问题本身。所以要算窗、不能看 z。

    判据（满足其一即可）：
      - 后一镜起幅的取景比例 <= 前一镜落幅的 REUSE_TIGHTEN 倍（真的切近了），或
      - 窗心移动 >= REUSE_SHIFT（切到画面另一块去了）

    **只查相邻的**。段二镜 12/15 也共用一张图，但中间隔着镜 13、14 二十多秒，
    那是"回到同一个地方"的设计，不是跳接。
    """
    bad, warn_reuse = [], []
    for i in range(len(SHOTS) - 1):
        if i + 1 >= len(CLIPS) or clip_key(CLIPS[i]) != clip_key(CLIPS[i + 1]):
            continue
        # 相邻两镜取同一段影片的**不同时间段**，本来就是两镜，不是一图两镜。
        # 分不分得开由 ss/to 决定，check_video 去管。
        if is_video(i + 1) or is_video(i + 2):
            continue
        a, b = _win(SHOTS[i], 1.0, CLIPS[i]), _win(SHOTS[i + 1], 0.0, CLIPS[i + 1])
        tighten = b[4] / a[4]
        shift = (((b[0] + b[1]) / 2 - (a[0] + a[1]) / 2) ** 2
                 + ((b[2] + b[3]) / 2 - (a[2] + a[3]) / 2) ** 2) ** 0.5
        if tighten > REUSE_TIGHTEN and shift < REUSE_SHIFT:
            (warn_reuse if REUSE_ACCEPT_REASON.strip() else bad).append(
                       "镜 %d/%d 共用 %s，但取景没分开："
                       "镜%d 落幅占画面 %.1f%%、镜%d 起幅 %.1f%%（%s），窗心只移了 %.3f。"
                       "读作跳接，不是两镜 —— 收紧镜%d 的 z，或让它切到画面另一块去"
                       % (i + 1, i + 2, clip_key(CLIPS[i]), i + 1, a[4] * 100,
                          i + 2, b[4] * 100,
                          "反而更宽" if tighten > 1 else "只收到 %.0f%%" % (tighten * 100),
                          shift, i + 2))
    if warn_reuse:
        print("")
        print("=== 一图两镜取景（%d 处低于判据，**已显式承认**）===" % len(warn_reuse))
        for w in warn_reuse:
            print("  " + w)
        print("  理由：" + REUSE_ACCEPT_REASON.strip())
        print("  交付时这一条要照抄进制作说明的「哪几处是妥协的」。")
    return bad


def selftest_reuse():
    """回归：造一个"两镜共用一张图但取景几乎相同"的配置，检查必须报警。"""
    if not any(clip_key(CLIPS[i]) == clip_key(CLIPS[i + 1])
               and not (is_video(i + 1) or is_video(i + 2))
               for i in range(len(CLIPS) - 1)):
        print("回归自测: 本段没有相邻共用图，check_reuse 不适用")
        return True
    # **自测必须绕过 REUSE_ACCEPT_REASON。** 填了理由之后 check_reuse 走降级路径、
    # 返回空 bad，自测就永远测不到拦截 —— 一个承认机制把自测一起关掉了。
    # 这一条是自测自己报"检查失效了"才发现的，它诚实地报了，而不是默默通过。
    global REUSE_ACCEPT_REASON
    reason_keep = REUSE_ACCEPT_REASON
    REUSE_ACCEPT_REASON = ""
    keep = dict(SHOTS[1])
    SHOTS[1].update(z=SHOTS[0]["z"], f0=SHOTS[0]["f1"], f1=SHOTS[0]["f1"])
    src_keep = CLIPS[1]["src"]; CLIPS[1]["src"] = CLIPS[0]["src"]
    n = len(check_reuse())
    SHOTS[1].clear(); SHOTS[1].update(keep); CLIPS[1]["src"] = src_keep
    REUSE_ACCEPT_REASON = reason_keep
    now = len(check_reuse())
    print("回归自测: 相邻两镜共用图且取景相同 → 报警 %d 条 —— %s"
          % (n, "对" if n else "**检查失效了**"))
    print("          当前配置 报警 %d 条 —— %s" % (now, "对" if now == 0 else "有问题"))
    return n > 0 and now == 0


def check_xfades():
    starts = shot_starts()
    total = total_len()
    D = [(starts[i + 1] if i + 1 < len(starts) else total) - starts[i]
         for i in range(len(SHOTS))]
    bad = []
    for i in range(len(SHOTS) - 1):
        x = xf(i)
        if x <= 0:
            bad.append("镜 %d 的转场 %.2fs 必须大于 0" % (i + 1, x))
        elif x > min(D[i], D[i + 1]) - 1e-6:
            bad.append("镜 %d 的转场 %.2fs 不短于相邻镜的内容时长(%.1fs/%.1fs)"
                       % (i + 1, x, D[i], D[i + 1]))
    return bad


VIDEO_HEADROOM = 0.5        # 素材段至少要比旁白算出来的镜长再多这么多秒
VIDEO_BLACK_MIN = 0.4       # 连续黑帧超过这么久就算「卡」，不是转场自带的暗场


BLACK_CACHE = "black_spans.json"


def black_spans(path):
    """`blackdetect` 扫出来的黑段 [(起, 止), ...]，**按 (大小, mtime) 缓存**。

    不缓存的话每跑一次 check 就要把十一个视频中间件整个解码一遍 ——
    判据是对的，代价放错了地方：check 应该是随时能跑的，慢到要等就没人跑，
    而不跑的判据等于没有。这和 vo_durs() 用 vo_times.json 缓 ffprobe 是同一件事。

    键里带 mtime 和大小，所以 prep 重出之后自动失效，不会拿旧结果糊弄。
    """
    try:
        st = os.stat(path)
    except OSError:
        return []
    key = "%s|%d|%d" % (os.path.basename(path), st.st_size, int(st.st_mtime))
    cache = {}
    if os.path.exists(BLACK_CACHE):
        try:
            cache = json.load(open(BLACK_CACHE, encoding="utf-8"))
        except Exception:
            cache = {}
    if key in cache:
        return [tuple(x) for x in cache[key]]
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", path, "-an",
                        "-vf", "blackdetect=d=%.2f:pic_th=0.98:pix_th=0.12"
                               % VIDEO_BLACK_MIN,
                        "-f", "null", "-"], capture_output=True, text=True)
    spans = [(float(m.group(1)), float(m.group(2)))
             for m in re.finditer(r"black_start:([\d.]+) black_end:([\d.]+)",
                                  r.stderr or "")]
    cache[key] = spans
    with open(BLACK_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    return spans


def check_video():
    """视频镜自己的判据。**静图那套判据一条都套不上它，所以要单独一张。**

    查五件事，前三件都是"不查就会在成片上静默出错"的那一类：

    1. **段够不够长。** 镜长由旁白算出来，素材段由 ss/to 声明，两者没有任何
       约束关系。段短了 pass_a 会冻结末帧补足 —— 画面会僵在那里好几秒，
       而 ffmpeg 退出码是 0、check 全绿、只有真的看片子才发现。
    2. **入点出点在源片里。** ss 写超过源片时长，ffmpeg 输出一段空的，也不报错。
    3. **同一份素材的相邻两镜段不能重叠。** 重叠就是同一段放了两遍，
       观众读作卡带。这是视频版的 check_reuse。
    4. 声明了 to 没有 —— 不声明出点，prep 会一路读到片尾，出一个几百兆的中间件。
    5. 时间码写成 20.10 这种（想写 20:10）—— 值合法、位置错，量不出来。
    """
    bad = []
    vids = [i for i in range(1, len(CLIPS) + 1) if is_video(i)]
    if not vids:
        return bad
    durs = timeline()[1]
    info_cache = {}
    for i in vids:
        c = CLIPS[i - 1]
        name = c["video"]
        if not c.get("to"):
            bad.append("镜 %d 是视频镜但没写 to= —— 出点不声明，prep 会一路读到片尾" % i)
            continue
        a, b, seg = video_seg(i)
        if seg <= 0:
            bad.append("镜 %d 的 ss=%r / to=%r 反了或相等" % (i, c.get("ss"), c.get("to")))
            continue
        path = os.path.join(SRC, name)
        if name not in info_cache:
            info_cache[name] = probe_video(path) if os.path.exists(path) else None
        info = info_cache[name]
        if info is None:
            continue                      # 缺素材由 check_timeline 的「缺素材」那条管
        src_dur = info[2]
        if b > src_dur + 1e-3:
            bad.append("镜 %d 的 to=%s（%.1fs）超出 %s 的时长 %.1fs —— "
                       "ffmpeg 会安静地少给你几秒" % (i, c.get("to"), b, name, src_dur))
        need = durs[i - 1] if i - 1 < len(durs) else 0.0
        if seg + 1e-3 < need:
            bad.append("镜 %d 的素材段只有 %.2fs，旁白要 %.2fs —— "
                       "pass_a 会冻结末帧补足，画面会僵住。把 to 往后放，"
                       "或者把这一镜的旁白挪一句走" % (i, seg, need))
        elif seg < need + VIDEO_HEADROOM:
            bad.append("镜 %d 的素材段 %.2fs 只比旁白 %.2fs 多 %.2fs —— "
                       "余量不足 %.1fs。旁白重新生成后镜长会变，现在刚好等于以后不够"
                       % (i, seg, need, seg - need, VIDEO_HEADROOM))
    # ---- 段**内部**有没有不能用的黑帧 ----
    # 这一条是踩出来的：档案影像里常夹着现代标题卡、机构水印黑卡、黑场。
    # 段够长、入出点合法、不重叠 —— 前三条全过，而金句那一镜开口三秒是一块
    # 写着 "NFSA 2006" 的黑屏。渲得出来、退出码 0、check 全绿，
    # 只有真看画面才发现，而看的时候还得刚好采到那一帧
    # （15 秒一帧的联络表就漏掉了它）。
    #
    # 用 blackdetect 一次解码扫完 vidNN.mp4，不逐帧 seek —— 逐帧 seek 在
    # 十分钟以上的源片上要几分钟，慢到没人会跑。
    for i in vids:
        vf = "vid%02d.mp4" % i
        if not os.path.exists(vf):
            continue          # 还没 prep，跳过；prep 之后再跑一次 check
        need = durs[i - 1] if i - 1 < len(durs) else 0.0
        for a, b in black_spans(vf):
            if a >= need:
                continue      # 落在这一镜用不到的那一段里，不管
            bad.append("镜 %d 的素材段内 %.1f~%.1fs 是黑帧（这一镜只用前 %.1fs，"
                       "所以它会**出现在成片上**）—— 多半是现代标题卡或机构水印卡，"
                       "换一段或把 ss 往后挪" % (i, a, min(b, need), need))

    # 相邻同源镜的段重叠
    for i in range(1, len(CLIPS)):
        if not (is_video(i) and is_video(i + 1)):
            continue
        if clip_key(CLIPS[i - 1]) != clip_key(CLIPS[i]):
            continue
        a1, b1, _ = video_seg(i)
        a2, b2, _ = video_seg(i + 1)
        if a2 < b1 - 1e-3 and a1 < b2 - 1e-3:
            bad.append("镜 %d/%d 共用 %s，但取的段重叠（%.1f~%.1f 和 %.1f~%.1f）—— "
                       "同一段放两遍，观众读作卡带"
                       % (i, i + 1, clip_key(CLIPS[i - 1]), a1, b1, a2, b2))
    return bad


def selftest_video():
    """回归：造三种错各一个，检查必须报警。没有视频镜时直接算过。"""
    if not any(is_video(i) for i in range(1, len(CLIPS) + 1)):
        return True
    print("回归自测: 视频镜 —— 段长为 0 / 没写 to / 出点超出源片，三种各造一个")
    i = next(i for i in range(1, len(CLIPS) + 1) if is_video(i))
    keep = dict(CLIPS[i - 1])
    base = len(check_video())
    ok = []
    CLIPS[i - 1]["to"] = keep["ss"]                     # 段长为 0
    ok.append(len(check_video()) > base)
    CLIPS[i - 1].update(keep); CLIPS[i - 1].pop("to")   # 没写 to
    ok.append(len(check_video()) > base)
    CLIPS[i - 1].update(keep); CLIPS[i - 1]["to"] = 99999
    ok.append(len(check_video()) > base)                # 出点超出源片
    CLIPS[i - 1].clear(); CLIPS[i - 1].update(keep)
    for nm, r in zip(("段长为 0", "没写 to", "出点超出源片"), ok):
        print("          %-14s %s" % (nm, "对" if r else "**检查失效了**"))
    print("          当前配置 %d 条 —— %s" % (base, "对" if base == 0 else "有问题要处理"))
    return all(ok) and len(check_video()) == base


def check_moves():
    bad = []
    for i, s in enumerate(SHOTS, 1):
        # 视频镜没有取景窗，z/f 对它没有意义。不跳过的话它会被当成"标了 kenburns
        # 却起止一样"而长期报警 —— 判据少建模了一种镜，就会稳定地冤枉它。
        if is_video(i):
            continue
        z0, z1 = s["z"]
        for (fx, fy), z, w in ((s["f0"], z0, "起"), (s["f1"], z1, "止")):
            lo, hi = 1 / (2 * z), 1 - 1 / (2 * z)
            for v, ax in ((fx, "x"), (fy, "y")):
                if not (lo - 1e-6 <= v <= hi + 1e-6):
                    bad.append("镜 %d %s幅 f%s=%.3f 超出 z=%.2f 的可达范围 [%.3f,%.3f]"
                               % (i, w, ax, v, z, lo, hi))
        want = abs(s["f1"][1] - s["f0"][1]) + abs(s["f1"][0] - s["f0"][0])
        zmax = max(z0, z1); can = max(0.0, 1 - 1 / zmax)

        # 运动方式和参数必须互相印证。"起止不小心写成一样"正是那个最贵的 bug
        # 长出来的样子，所以两边都拦，不去猜哪个是真的。
        m = motion_of(i)
        moving = want > 1e-6 or abs(z1 - z0) > 1e-6
        if m not in ("kenburns", "static"):
            bad.append("镜 %d 的 motion=%r 不认识，只能是 'kenburns' / 'static'"
                       "（视频镜不用写 motion，CLIPS 里给了 video= 就是）" % (i, m))
        elif m == "static" and moving:
            bad.append("镜 %d 标了 static 却写了行程 (z %.2f→%.2f, f %s→%s) —— "
                       "静帧镜的 z 和 f 起止必须完全一致"
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
    """回归：每一类错误各造一个，检查必须报警。理由同 selftest_safe()。"""
    if not SHOTS:
        return True
    keep = [dict(s) for s in SHOTS]
    base = len(check_moves())
    # **造错误的那一镜不能是视频镜。** check_moves 对视频镜整镜跳过（它没有取景窗），
    # 挑中视频镜时三个 case 全部"多报 0 条"，回归自测于是报「检查失效了」——
    # 而失效的其实是自测本身。视频镜自己的回归在 selftest_video()。
    plain = next((i for i in range(1, len(SHOTS) + 1) if not is_video(i)), None)
    if plain is None:
        print("回归自测: 全部是视频镜，check_moves 不适用")
        return True

    def case(name, i, patch):
        SHOTS[i - 1] = dict(keep[i - 1], **patch)
        n = len(check_moves())
        SHOTS[i - 1] = dict(keep[i - 1])
        print("回归自测: %-24s 多报 %d 条 —— %s"
              % (name, n - base, "对" if n > base else "**检查失效了**"))
        return n > base

    moving = next((i for i, s in enumerate(SHOTS, 1)
                   if not is_video(i)
                   and (abs(s["f1"][0] - s["f0"][0]) + abs(s["f1"][1] - s["f0"][1]) > 1e-6
                        or abs(s["z"][1] - s["z"][0]) > 1e-6)), None)
    ok = []
    if moving:
        ok.append(case("有行程的镜标成 static", moving, dict(motion="static")))
    z, f = keep[plain - 1]["z"][0], keep[plain - 1]["f0"]
    ok.append(case("原地不动的镜标成 kenburns", plain,
                   dict(motion="kenburns", z=(z, z), f0=f, f1=f)))
    ok.append(case("motion 写错字", plain, dict(motion="ken_burns")))
    print("          当前配置 %d 条 —— %s" % (base, "对" if base == 0 else "有问题要处理"))
    return all(ok) and len(check_moves()) == base


def check_credits():
    """素材来源与授权的登记。**只对"自己找来的"素材是硬约束。**

    自己生成的图没有第三方权利问题；从开放数据、图库、公版录音里拿来的不一样 ——
    CC-BY 要求署名，而"公有领域"对**作品**成立不等于对**某一次录音或翻拍**成立。
    这类错误成片、审核、发布全都不会拦，要到被投诉才知道，所以放进 check。
    """
    bad = []
    need = ("title", "holder", "source", "license", "url")
    if IMG_SOURCE not in ("generated", "found"):
        bad.append("IMG_SOURCE=%r 不认识，只能是 'generated' 或 'found'" % IMG_SOURCE)
    elif IMG_SOURCE == "found":
        seen = set()
        for c in CLIPS:
            k = clip_key(c)
            if k in seen:          # 一份素材用在多镜，登记一次就够
                continue
            seen.add(k)
            e = CREDITS.get(k)
            if not e:
                bad.append("素材 %s 没登记来源（IMG_SOURCE='found' 时每一份都要，"
                           "视频也算）" % k)
            else:
                miss = [k2 for k2 in need if not str(e.get(k2, "")).strip()]
                if miss:
                    bad.append("素材 %s 的来源登记缺 %s" % (k, "/".join(miss)))
    if MUSIC_MODE not in ("generated", "public_domain", "library", "none"):
        bad.append("MUSIC_MODE=%r 不认识，只能是 'generated' / 'public_domain' / 'library' / 'none'"
                   % MUSIC_MODE)
    elif MUSIC_MODE == "library" and not str(MUSIC_FROM_LIBRARY).strip():
        bad.append("MUSIC_MODE='library' 却没填 MUSIC_FROM_LIBRARY —— "
                   "不记下用了库里哪一条，做完就没法回去 `add --used`，"
                   "下一支查库时会不知道它已经用过了")
    elif MUSIC_MODE == "public_domain":
        miss = [k for k in ("work", "performer", "source", "license", "url")
                if not str(MUSIC_CREDIT.get(k, "")).strip()]
        if miss:
            bad.append("公版配乐的 MUSIC_CREDIT 缺 %s —— **录音权和作品权是两回事**，"
                       "填不出来说明这条录音的授权还没查清楚" % "/".join(miss))
    return bad


def selftest_credits():
    """回归：把登记抽掉，检查必须报警。

    **两路各要一条自己的干净基线，不能共用"当前配置"的 base。**
    原来两路都拿 `base = len(check_credits())` 比，而 base 里可能已经有一条
    **别的**告警（实际撞上的是 `MUSIC_MODE='library'` 还没填 `MUSIC_FROM_LIBRARY`）：
    注入故障后条数不增，自测就报"**检查失效了**" —— 假警，而且偏偏是在
    检查本身好好的时候报。一个乱叫的自测和一个不叫的自测一样会被无视。

    修法：基线和注入只差**被测的那一维**，别的维度保持不动。
    """
    global IMG_SOURCE, MUSIC_MODE, CREDITS, MUSIC_CREDIT
    ki, km, kc, kmc = IMG_SOURCE, MUSIC_MODE, CREDITS, MUSIC_CREDIT
    empty = dict(work="", performer="", source="", license="", url="")

    IMG_SOURCE, CREDITS = "generated", {}                    # 素材那一路的干净基线
    base_i = len(check_credits())
    IMG_SOURCE, CREDITS = "found", {}
    a = len(check_credits()) > base_i
    IMG_SOURCE, CREDITS = ki, kc

    MUSIC_MODE, MUSIC_CREDIT = "none", kmc                   # 配乐那一路的干净基线
    base_m = len(check_credits())
    MUSIC_MODE, MUSIC_CREDIT = "public_domain", empty
    b = len(check_credits()) > base_m
    MUSIC_MODE, MUSIC_CREDIT = km, kmc

    print("回归自测: 素材标 found 但没登记来源 —— %s" % ("对" if a else "**检查失效了**"))
    print("          配乐标 public_domain 但没填授权 —— %s" % ("对" if b else "**检查失效了**"))
    return a and b


def check_endcard():
    """**下集预告板不能指向本集自己。**

    换集时从上一支复制脚本，`ENDCARD` 会原样继承过来。《白衣女人》集二就这样
    带着集一的板子渲完了整片 —— 成片里写着「下一集 · 黑水园」，而黑水园就是这一集。
    `check_seg` 只验 ENDCARD 该不该存在，不验里面写了什么，所以一路全绿，
    **是用户看片的时候发现的**。

    判据很笨但够用：预告板的 head 里不许出现本集的 TITLE。
    """
    if not ENDCARD:
        return []
    if TITLE and TITLE in ENDCARD.get("head", ""):
        return ["下集预告板写的是本集自己（TITLE=%r 出现在 ENDCARD.head=%r）—— "
                "换集时忘了重填？" % (TITLE, ENDCARD["head"])]
    return []


def check_coldopen(lines):
    """**冷开场那句不能压在开场淡入里。**

    第二节写着「冷开场第一句的 pre 给 1.2~1.6s」，但不写也能跑、别的检查也不报，
    所以**连着两支都漏了**（《白衣女人》集一集二，第二支是在集一刚把这条写进技能之后）。
    光写进文档不管用，这里拦。

    判据：第一条旁白的**出声点**必须落在 FADE_IN 之后，且留 0.2s 余量。
    出声点 = 第一条字幕起点 + 0.10（字幕比声音早 0.10s 起，见 timeline()）。
    """
    if not SEG_FIRST or FADE_IN <= 0 or not lines:
        return []
    vs = lines[0][4]                      # 第一条旁白的落点
    if vs < FADE_IN + 0.2:
        return ["冷开场压在淡入里：旁白 %.2fs 出声，而 FADE_IN 要到 %.2fs 才走完 —— "
                "给第一条 NARR 写 pre=1.2~1.6（现在是 %.2f）"
                % (vs, FADE_IN, vs)]
    return []


def check_timeline():
    lines, durs, total, _ = timeline()
    _, missing = vo_durs()
    cuts = cut_points()
    bad, warn = [], []
    bad += check_claims()
    bad += check_pace()
    bad += check_subs()
    bad += check_seg()
    bad += check_reuse()
    bad += check_xfades()
    bad += check_moves()
    bad += check_video()
    bad += check_resolution()
    bad += check_coldopen(lines)
    bad += check_endcard()
    bad += check_langs()

    for st, en, txt, _, _, _ in lines:
        for c in cuts:
            if st - 0.25 < c < en + 0.25:
                bad.append("转场 %.1fs 压到了字幕『%s』" % (c, txt))
        if en > total + 1e-6:
            bad.append("字幕『%s』结束于 %.1fs，超出片长 %.1fs" % (txt, en, total))
    for c in CLIPS:
        if not os.path.exists(os.path.join(SRC, clip_key(c))):
            warn.append("缺素材: " + clip_key(c))
    if len(CLIPS) != len(SHOTS):
        bad.append("CLIPS %d 张对不上 SHOTS %d 镜" % (len(CLIPS), len(SHOTS)))

    if missing:
        warn.append("**时间轴是估算的** —— 还缺 %d 条旁白 (%s...)。"
                    "配音生成之后跑 sync 会自动重算" % (len(missing), missing[0]))
    bad += check_credits()
    if not music_on():
        # SFX 是 dict 列表，不是 tuple —— 写成 `for f, *_ in SFX` 会去解包字典的**键**，
        # 于是永远数出 0 条而不报错。没有音乐时音效是承重的，这个数不能骗人。
        miss = [s["f"] for s in SFX if not os.path.exists(os.path.join(SRC, s["f"]))]
        n = len(SFX) - len(miss)
        print("\n配乐: 无（MUSIC_MODE='none'）—— 音频是 %d 条旁白 + %d/%d 条音效"
              % (len(NARR), n, len(SFX)))
        for f in miss:
            warn.append("缺音效: " + f)
        print("      旁白本来就是连续的音床，所以归一化照常（norm_mode=%s）"
              % norm_mode())
    elif not os.path.exists(MUSIC):
        warn.append("音乐还没就位")
    else:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "csv=p=0", MUSIC],
                           capture_output=True, text=True)
        try:
            mdur = float(p.stdout.strip())
            if MUSIC_IN + total > mdur + 1e-3:
                bad.append("音乐不够长: 从 %.1fs 切入需要到 %.1fs，全曲只有 %.1fs"
                           % (MUSIC_IN, MUSIC_IN + total, mdur))
            else:
                print("\n配乐(%s): 全曲 %.1fs，从 %.1fs 切入，余地 %.1fs"
                      % ({"generated": "生成", "library": "库里挑的"}.get(MUSIC_MODE, "公版"),
                         mdur, MUSIC_IN, mdur - total))
            # 诗片的判据是 1.6 倍（音乐是唯一音源，某处塌下去就毁了）。
            # 讲述片全程有旁白盖着，音乐只在句间的缝里露出来，要挑的落点少得多，
            # 所以放宽到 1.4 倍。照抄诗片那条会一直报一个不需要处理的警。
            if MUSIC_MODE in ("generated", "library") and mdur < total * 1.4:
                warn.append("音乐只比片长多 %.0fs（不到片长的 0.4 倍），切入点几乎没得挑"
                            % (mdur - total))
            if MUSIC_MODE == "public_domain":
                warn.append("公版录音：`pick` 只挑响度、**挑不出乐句边界** —— "
                            "切入点定完要听首尾，另外跑 `mquality` 看底噪和带宽")
        except ValueError:
            warn.append("读不出音乐时长")

    ns = sum(1 for n in range(1, len(SHOTS) + 1) if is_static(n))
    nv = sum(1 for n in range(1, len(SHOTS) + 1) if is_video(n))
    print("\n片长 %.1fs (%d:%04.1f)  镜头 %d  旁白 %d 条  %dx%d"
          % (total, total // 60, total % 60, len(SHOTS), len(NARR), W, H))
    # **视频镜要单独数。** 不数的话它会被并进"运镜"，于是汇总上写着运镜 11 镜、
    # 实际一镜运镜都没有 —— 汇总是最常被照抄进制作说明的一行，错在这里传得最远。
    print("运动: %s（静帧 %d 镜 / 运镜 %d 镜 / 视频 %d 镜）  配乐: %s  素材: %s"
          % ({"kenburns": "运镜", "static": "静帧"}.get(MOTION, MOTION),
             ns, len(SHOTS) - ns - nv, nv,
             {"generated": "生成", "public_domain": "公版",
              "library": "库里挑的", "none": "无"}.get(MUSIC_MODE),
             {"generated": "按任务书生成", "found": "自己找的"}.get(IMG_SOURCE)))
    print("字幕: **外挂 SRT**（%s），不烧进画面；标题字卡烧进画面"
          % " / ".join(srt_name(l) for l in LANGS))
    if len(LANGS) > 1:
        print("音轨: %d 条（%s），默认 %s —— YouTube 多语言音轨，画面只有一份"
              % (len(LANGS), " / ".join(LANG_INFO[l]["name"] for l in LANGS),
                 LANG_INFO[DEFAULT_LANG]["name"]))
    print("每镜时长: " + "  ".join("%.1f" % d for d in durs))
    print("转场落点: " + "  ".join("%.1f" % c for c in cuts))
    selftest_seg()
    selftest_reuse()
    selftest_moves()
    selftest_video()
    selftest_credits()
    selftest_langs()
    for w in warn:
        print("提示: " + w)
    if bad:
        print("\n!! 问题 %d 条:" % len(bad))
        for b in bad:
            print("   - " + b)
    else:
        print("\n自检通过。")
    return not bad


def sync():
    """量旁白 -> 打出时间轴。改了配音先跑它（缓存会自动失效，不用手工清）。"""
    for lang in LANGS:
        p = vo_cache_of(lang)
        if os.path.exists(p):
            os.remove(p)
    global _VO
    _VO = {}
    lines, durs, total, _ = timeline()
    durs_map, missing = vo_durs()
    print("=== 旁白实测 ===")
    for n in NARR:
        d, real = durs_map[n["vo"]]
        print("  镜%-3d %-11s %6.2fs %s  %s"
              % (n["shot"], n["vo"], d, "" if real else "(估算)",
                 "".join(sub_lines(n["txt"]))[:24]))
    print("\n旁白净时长 %.1fs，加气口后片长 %.1fs" % (sum(durs_map[n["vo"]][0] for n in NARR), total))
    st = shot_starts()
    print("\n=== 每镜 ===")
    for i, d in enumerate(durs):
        print("  镜%-3d 起 %6.2f  dur %5.2f  xf %.2f"
              % (i + 1, st[i], d, xf(i) if i < len(SHOTS) - 1 else 0.0))
    if missing:
        print("\n还缺 %d 条旁白，上面带 (估算) 的是按 est 排的。" % len(missing))


def langfit(lang="en"):
    """把某条语言的旁白**逐句**压进中文定出来的槽里。

    ---- 为什么是逐句，不是整条一个倍率（竖版 vofit 那样）----
    vofit 解决的是"整片超硬线"，全片同一个倍率听不出来。这里解决的是
    "这一句和画面对不上"：各句超出的比例天差地别，拿全片平均倍率去压，
    短句被无谓地拉快、长句照样压不进去，**而且两头都听得出来**。

    ---- 倍率永远从原件算 ----
    原件在 VO_RAW_OF[lang]，第一次跑时自动备份。拿"已经压过一次"的文件算倍率
    再作用到原件上，第二次调整会走反方向，而且一声不吭（竖版 vofit 踩过）。

    ---- 压不进去的句子不压 ----
    报出这一句还得砍几个词，并且把文件**放回原速**（不是留着上一次压的结果 ——
    那会让磁盘上的状态取决于跑过几次，无法复现）。这时脚本 exit 1，
    但塞得下的那些句子已经压好了：逐句是彼此独立的，全盘拒绝只会让你多跑几趟。
    真正的安全网是 check_langs()，它每次 check 都从磁盘重验一遍。
    """
    if lang == DEFAULT_LANG:
        sys.exit("!!! langfit 是把别的语言压进 %s 的槽，不能对 %s 自己跑"
                 % (DEFAULT_LANG, DEFAULT_LANG))
    if lang not in LANGS:
        sys.exit("!!! LANGS 里没有 %r —— 先在「双语音轨」那一节把它打开" % lang)
    vdir = VO_DIR_OF.get(lang, lang)
    if not os.path.isdir(vdir):
        sys.exit("!!! 没有 %s/ —— %s 旁白还没就位" % (vdir, lang))
    raw_dir = VO_RAW_OF.get(lang, "vo_%s_raw" % lang)
    if not os.path.isdir(raw_dir):
        os.makedirs(raw_dir)
        for x in NARR:
            src = vo_path(x, lang)
            if os.path.exists(src):
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-c", "copy",
                                os.path.join(raw_dir, os.path.basename(src))], check=True)
        print("原件已备份到 %s/（以后每次都从这里重新推导，压不会叠加）" % raw_dir)

    slots = lang_slots()
    rows, missing = [], []
    for k, x in enumerate(NARR):
        dst = vo_path(x, lang)
        raw = os.path.join(raw_dir, os.path.basename(dst))
        if not os.path.exists(raw):
            missing.append(x["vo"]); continue
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "csv=p=0", raw],
                           capture_output=True, text=True)
        try:
            d = float(r.stdout.strip())
        except ValueError:
            missing.append(x["vo"]); continue
        base, borrow = slots[k]
        rows.append((x, dst, raw, d, base + borrow))
    if not rows:
        sys.exit("!!! %s/ 下一条原件都没量到" % raw_dir)

    # 换算"还得砍几个词"用的语速：EN_RATE 填了就用它，没填就用**本批实测**。
    # 用本批实测比填一个通行值靠谱 —— 语速取决于音色和表演方向，不是常数。
    words = sum(n_words(lang_text(x, lang)) for x, _, _, _, _ in rows)
    speech = sum(d for _, _, _, d, _ in rows)
    rate = EN_RATE or (words / speech if speech else 0.0)

    print("")
    print("=== langfit %s：中文定槽，逐句压（倍率上限 ×%.2f，可借静默 %.2fs）==="
          % (lang, LANG_TEMPO_MAX, LANG_BORROW))
    over, moved = [], 0
    for x, dst, raw, d, room in rows:
        if d <= room + 1e-3:
            act = "原速"
            cmd = ["ffmpeg", "-y", "-v", "error", "-i", raw, "-c", "copy", dst]
        else:
            tempo = d / room
            if tempo > LANG_TEMPO_MAX:
                over.append((x["vo"], d, room, tempo,
                             (d - room * LANG_TEMPO_MAX) * rate))
                act = "**压不进，已放回原速**"
                cmd = ["ffmpeg", "-y", "-v", "error", "-i", raw, "-c", "copy", dst]
            else:
                act = "×%.3f" % tempo
                moved += 1
                cmd = ["ffmpeg", "-y", "-v", "error", "-i", raw,
                       "-filter:a", "atempo=%.6f" % tempo, "-q:a", "2", dst]
        if subprocess.run(cmd).returncode != 0:
            sys.exit("!!! 处理 %s 失败" % x["vo"])
        print("  %-11s 槽 %5.2f  原件 %5.2f  %s" % (x["vo"], room, d, act))

    _VO.pop(lang, None)
    c = vo_cache_of(lang)
    if os.path.exists(c):
        os.remove(c)

    if missing:
        print("\n提示: %d 条没有原件（%s%s）—— 先把音频放进 %s/ 再跑一次"
              % (len(missing), ", ".join(missing[:3]),
                 "..." if len(missing) > 3 else "", vdir))
    print("\n本批 %s 实测语速 **%.2f 词/秒**（%d 词 / %.1fs）%s"
          % (lang, words / speech if speech else 0, words, speech,
             "" if EN_RATE else "  << EN_RATE 还是 None，把这个数填上去"))
    print("压了 %d 条，原速 %d 条。" % (moved, len(rows) - moved - len(over)))
    if over:
        print("\n!! %d 条压不进去（超过 ×%.2f 就不压了）：" % (len(over), LANG_TEMPO_MAX))
        for vo, d, room, tempo, cut in over:
            print("   %-11s 槽 %.2fs，现在 %.2fs，要 ×%.3f 才塞得下 —— "
                  "**还得砍约 %d 个词**" % (vo, room, d, tempo, int(-(-cut // 1))))
        print("\n   别把这活交给 atempo：听得出来的毛病换看不出来的错位，不是修好。")
        print("   要改的是英文稿，中文那条轨和画面一个字都不用动。")
        return False
    print("全部塞得进。**接着跑 check** —— 它会从磁盘上的文件再验一遍。")
    return True


# ================= 素材 =================
def prep():
    for i, c in enumerate(CLIPS, 1):
        if c.get("video"):
            prep_video(i, c); continue
        src = os.path.join(SRC, c["src"])
        if not os.path.exists(src):
            print("   跳过(缺图): " + c["src"]); continue
        if c.get("fit") == "plate":
            prep_plate(i, c, src); continue
        z, cx, cy = c["zoom"], c["cx"], c["cy"]
        # 横版裁 16:9（竖版模板这里是 9:16，两个分数都要跟着翻，翻漏一个会裁出细长条）
        crop = ("crop=w='min(iw,ih/%.6f*16/9)':h='min(ih/%.6f,iw*9/16)':"
                "x='clip(%.6f*iw-out_w/2,0,iw-out_w)':"
                "y='clip(%.6f*ih-out_h/2,0,ih-out_h)'" % (z, z, cx, cy))
        # **空段要跳过**。GRADE="" 是合法状态（还没量直方图定调色，或这一支不需要），
        # 直接字符串拼接会拼出 "crop,,scale=" —— ffmpeg 报 `No such filter: ''`，
        # 而报错信息里完全看不出是哪个常数为空。
        _parts = [crop]
        if str(GRADE).strip():
            _parts.append(GRADE)
        if c["tweak"]:
            _parts.append(c["tweak"])
        _parts.append("scale=%d:%d:flags=lanczos" % PREP)
        _parts.append("setsar=1")
        vf = ",".join(_parts)
        run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", vf,
             "-frames:v", "1", "img%02d.png" % i],
            "prep %d/%d  %s" % (i, len(CLIPS), c["src"]))
    probe()


def prep_plate(i, c, src):
    """贴纸版式的 prep：整张图按 1:1（或缩小）贴在成片画框中央，四周补台纸。

    **不走 crop。** 走 crop 就等于承认要裁，而这条路的前提正是"这张不能裁"。

    出的是**成片尺寸**的 imgNN.png，不是 PREP 尺寸 —— 所以用贴纸版式的片子
    要把 PREP 设成成片尺寸，让 pass_a 的 static_vf 变成恒等重采样。
    PREP 还留在 3840x2160 的话，pass_a 会把整张台纸再缩一半，图就只有半幅大。
    check_resolution 会拦这个组合。
    """
    d = img_dims(src)
    if not d:
        print("   跳过(读不出尺寸): " + c["src"]); return
    w, h = d
    tw, th, f = plate_box(w, h)
    _parts = ["scale=%d:%d:flags=lanczos" % (tw, th)]
    if str(GRADE).strip():
        _parts.append(GRADE)
    if c.get("tweak"):
        _parts.append(c["tweak"])
    _parts.append("pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=%s" % (W, H, PLATE_COLOR))
    _parts.append("setsar=1")
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", ",".join(_parts),
         "-frames:v", "1", "img%02d.png" % i],
        "prep %d/%d  %s  贴纸 %dx%d -> %dx%d (x%.2f)"
        % (i, len(CLIPS), c["src"], w, h, tw, th, f))


def prep_video(i, c):
    """视频镜的 prep：把声明的那一段**归一成成片尺寸的 vidNN.mp4**，
    顺带出一张 imgNN.png 供缺图检查和封面用。

    和静帧镜的 prep 是同一件事 —— 都是"把素材整理成流水线能直接用的形状"。
    区别只在产物：静帧镜出一张 PREP 尺寸的大图留给 zoompan 取景，
    视频镜没有取景可言，直接出成片尺寸。

    ---- 三条实现上的取舍 ----
    1. **-ss 放在 -i 前面**（输入定位）。放后面是逐帧解到入点，20 分钟的片子
       每一镜都要重解一遍，十一镜就是十一次全解。放前面靠关键帧跳，
       代价是入点可能差几帧 —— 对档案影像完全可以接受。
    2. **fps 在这里就落到 FPS**。29.97 和 30 不统一，pass_c 的 concat
       会得到一段时间戳乱掉的片子，而且它**不报错**。
       这里用的是 fps 滤镜的丢/复帧，不是插值 —— 不要改成 minterpolate，
       默片本来就抖，插出来的中间帧会把抖动抹成糊的。
    3. **调色和 tweak 走和静帧镜同一套**，否则视频镜和静帧镜在成片里
       是两个色调，一眼看得出来。
    """
    src = os.path.join(SRC, c["video"])
    if not os.path.exists(src):
        print("   跳过(缺视频): " + c["video"]); return
    a, b, seg = video_seg(i)
    if seg <= 0:
        print("   跳过(镜%d 的 ss/to 没写或写反了): %s" % (i, c["video"])); return
    parts = [video_fit_vf()]
    if str(GRADE).strip():
        parts.append(GRADE)
    if c.get("tweak"):
        parts.append(c["tweak"])
    parts += ["fps=%d" % FPS, "setsar=1", "format=yuv420p"]
    vf = ",".join(parts)
    out = "vid%02d.mp4" % i
    run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % a, "-t", "%.3f" % seg,
         "-i", src, "-vf", vf, "-an", "-c:v", "libx264", "-crf", "12",
         "-preset", "medium", "-pix_fmt", "yuv420p", out],
        "prep %d/%d  %s  %s~%s (%.1fs)  %s"
        % (i, len(CLIPS), c["video"], c.get("ss"), c.get("to"), seg,
           "黑边" if VIDEO_FIT == "pillarbox" else "裁切"))
    # 出一张静帧：probe/trace/封面 都还按 imgNN.png 找素材，缺了会一路 KeyError。
    run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % a, "-i", src,
         "-vf", vf, "-frames:v", "1", "img%02d.png" % i],
        "     └ 代表帧 img%02d.png" % i)


def probe():
    """16x9 亮度网格（横版；竖版模板是 9x16）。能发现落幅摇进无特征区域这类问题。
    **但它量的是整张图，而镜头只经过其中一段，所以报警经常是误报** —— 跑完一定要跑 trace。"""
    print("\n=== 亮度网格 (0-255, 16 列 x 9 行) ===")
    for i in range(1, len(CLIPS) + 1):
        f = "img%02d.png" % i
        if not os.path.exists(f):
            print("%s  (未生成)" % f); continue
        p = subprocess.run(["ffmpeg", "-v", "error", "-i", f, "-vf",
                            "scale=16:9:flags=area,format=gray", "-f", "rawvideo", "-"],
                           capture_output=True)
        raw = p.stdout
        if len(raw) != 144:
            print("%s  (读不出)" % f); continue
        print("\n%s  %s" % (f, clip_key(CLIPS[i - 1])))
        for r in range(9):
            print("   " + " ".join("%3d" % raw[r * 16 + c] for c in range(16)))


def vig_factor(x0, x1, y0, y1):
    """pass_a 里的 vignette 对画面上某矩形的平均衰减系数(1.0 = 不衰减)。

    **少了这个，trace 和 measure 会系统性对不上**，而"对不上 = 运镜没走在你以为的
    位置上"是全流水线唯一一处能自检运镜的判据 —— 一个长期报假警的检查等于没有检查。
    做法：拿一张纯灰跑一遍 VIGNETTE，用画心的值归一，改参数自动跟着变。"""
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
    step = 8
    v = [raw[y * W + x] for y in range(y0, y1, step) for x in range(x0, x1, step)]
    return (sum(v) / len(v)) / ctr


def scrim_factor(x0, x1, y0, y1):
    """pass_c 里那层 scrim 对画面上某矩形的平均透过率（1.0 = 没压）。

    和 vig_factor 是同一个道理，而且是同一个坑的第二只脚：**trace 必须和
    pass_a/pass_c 建模同一条流水线**。只补了 vignette 不补 scrim，
    trace 会系统性地比 measure 亮 —— 而"两者对不上 = 运镜没走对"
    是全流水线唯一一处能自检运镜的判据，一旦有系统性偏差就等于废了。

    做法同样是拿一张纯灰跑一遍真正的合成，按画心归一，改参数自动跟着变。
    """
    if SCRIM_ALPHA <= 0:
        return 1.0
    if "map" not in _SCRIM_CACHE:
        if not os.path.exists("scrim.png"):
            make_scrim()
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi",
             "-i", "color=c=0xC8C8C8:s=%dx%d" % (W, H), "-i", "scrim.png",
             "-filter_complex", "[0:v][1:v]overlay=0:0:shortest=1,format=gray",
             "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True).stdout
        _SCRIM_CACHE["map"] = raw if len(raw) == W * H else None
    raw = _SCRIM_CACHE["map"]
    if not raw:
        return 1.0
    step = 8
    v = [raw[y * W + x] for y in range(y0, y1, step) for x in range(x0, x1, step)]
    return (sum(v) / len(v)) / 200.0          # 0xC8 = 200


def probe_times(n, durs):
    """镜 n 里可以取样的三个**镜内局部时刻**（起/中/止）。trace 和 measure 必须
    共用这一个函数 —— 各写一份就一定会漂。

    **必须躲开转场。** 每一镜渲出来那段片子的头尾各骑着半个转场（xfade 骑在内容
    边界正中），在 master.mp4 上那几帧是**两镜的混合帧**，而 trace 建模的是单镜的
    zoompan。第一版 measure 直接在 0.05s 和 dur−0.05s 上取样，于是 68 处超差，
    而**中间那一列严丝合缝** —— 静帧镜（画面本来不动）也照样报 ±72，
    那就只能是转场混合，不可能是运镜。

    干净区 = [进来的转场, dur − 出去的转场]，两端再各让开 PROBE_EDGE。
    """
    i = n - 1
    lo = xf(i - 1) if i > 0 else 0.0
    hi = durs[i] - (xf(i) if i < len(SHOTS) - 1 else 0.0)
    # **片头/片尾的黑场淡入淡出也要躲开**，理由和转场完全一样：它们加在 pass_b 上，
    # 而 trace 不建模。第一版只躲了转场，于是镜 1 的起幅量到 0/2/0（还在淡入的黑里），
    # 报 −45 级看着像运镜错了。淡场只压在第一镜的头和最后一镜的尾上。
    if i == 0:
        lo = max(lo, FADE_IN)
    if i == len(SHOTS) - 1 and FADE_OUT > 0:
        hi = min(hi, durs[i] - FADE_OUT)
    lo, hi = lo + PROBE_EDGE, hi - PROBE_EDGE
    if hi <= lo:                      # 极短的镜头：退回镜心
        lo = hi = durs[i] / 2.0
    return (lo, (lo + hi) / 2.0, hi)


def trace():
    """量镜头**真正经过的区域** —— 出图阶段就能判一张图能不能用，缺图会跳过。

    zoompan 的取景窗宽高各 1/z、窗心在 (fx,fy) 且被 clip 在图内，于是
        src = (f - 1/(2z)) + (out/边长) * (1/z)
    打扫过范围要取**并集**，不能打"起帧框顶→止帧框底"：上摇时落幅的框底在起幅框底
    之上，那样打出来会把行程严重低估。"""
    lines, durs, _, _ = timeline()
    starts = clip_starts()          # 镜内局部时刻要按**渲出来那段片子**的起点算
    dark = POLARITY == "dark_on_light"
    GW, GH = 1288, 724              # 横版：宽 > 高（竖版模板这里是 724x1288）
    cache = {}

    def gray(i):
        if i in cache:
            return cache[i]
        f = "img%02d.png" % i
        if not os.path.exists(f):
            f = os.path.join(SRC, clip_key(CLIPS[i - 1]))
            if not os.path.exists(f):
                cache[i] = None; return None
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", f, "-vf",
                              "scale=%d:%d:flags=area,format=gray" % (GW, GH),
                              "-f", "rawvideo", "-"], capture_output=True).stdout
        cache[i] = raw if len(raw) == GW * GH else None
        return cache[i]

    def box(n, tl, x0o, x1o, y0o, y1o):
        s = SHOTS[n - 1]
        p = min(1.0, max(0.0, tl / durs[n - 1]))
        z = s["z"][0] + (s["z"][1] - s["z"][0]) * p
        half = 1 / (2 * z)
        fx = min(max(s["f0"][0] + (s["f1"][0] - s["f0"][0]) * p, half), 1 - half)
        fy = min(max(s["f0"][1] + (s["f1"][1] - s["f0"][1]) * p, half), 1 - half)
        span = 1.0 / z
        return (fx - half + x0o / W * span, fx - half + x1o / W * span,
                fy - half + y0o / H * span, fy - half + y1o / H * span)

    def stat(raw, b, vig):
        x0, x1 = int(b[0] * GW), max(int(b[0] * GW) + 1, int(b[1] * GW))
        y0, y1 = int(b[2] * GH), max(int(b[2] * GH) + 1, int(b[3] * GH))
        x0, x1, y0, y1 = max(0, x0), min(GW, x1), max(0, y0), min(GH, y1)
        v = [raw[y * GW + x] * vig for y in range(y0, y1) for x in range(x0, x1)]
        return sum(v) / len(v)

    # ---- 取样框预测：给 measure 对账用（不再是量字幕底）----------------------
    print("\n=== 取样框预测亮度（三框 × 起/中/止）===")
    print("    这一节的用途**只有一个**：给 measure 对账，自检运镜有没有走在预期位置。")
    print("    字幕外挂之后不再有「字幕底」要判，但那个自检不能跟着丢。")
    print("    已建模 vignette。跑完 a+b 之后跑 measure，逐条差 %.0f 级以内才算对。" % PROBE_TOL)
    pred = {}
    for n in range(1, len(SHOTS) + 1):
        raw = gray(n)
        if raw is None:
            print("  镜%-3d (缺图)" % n); continue
        cells = []
        for name, rx0, rx1, ry0, ry1 in PROBE_BOXES:
            x0, x1 = int(rx0 * W), int(rx1 * W)
            y0, y1 = int(ry0 * H), int(ry1 * H)
            vig = vig_factor(x0, x1, y0, y1) * scrim_factor(x0, x1, y0, y1)
            vals = []
            for tl in probe_times(n, durs):
                b = box(n, tl, x0, x1, y0, y1)
                vals.append(stat(raw, b, vig))
            pred[(n, name)] = vals
            cells.append("%s %3.0f/%3.0f/%3.0f" % (name, vals[0], vals[1], vals[2]))
        print("  镜%-3d %-14s %s" % (n, clip_key(CLIPS[n - 1])[:13], "   ".join(cells)))
    try:
        json.dump({"%d|%s" % k: v for k, v in pred.items()},
                  open("trace_pred.json", "w", encoding="utf-8"))
        print("\n  预测值存进 trace_pred.json —— measure 会读它对账。")
    except OSError:
        pass

    print("\n=== 落幅平坦度（只量镜头真正停住的那一帧）===")
    for n in range(1, len(SHOTS) + 1):
        raw = gray(n)
        if raw is None:
            print("  镜%-3d (缺图)" % n); continue
        b = box(n, durs[n - 1], 0, W, 0, H)
        gx0, gx1 = int(b[0] * GW), int(b[1] * GW)
        gy0, gy1 = int(b[2] * GH), int(b[3] * GH)
        # 横版是 9 行 × 16 列（竖版模板反过来）。数的是**每一行内部的横向变化**，
        # 所以行列搞反了判据就变成另一回事了，而它照样会打印得很正常。
        cells, flat = [], 0
        for r in range(9):
            row = []
            for c in range(16):
                sx0 = gx0 + (gx1 - gx0) * c // 16
                sx1 = max(sx0 + 1, gx0 + (gx1 - gx0) * (c + 1) // 16)
                sy0 = gy0 + (gy1 - gy0) * r // 9
                sy1 = max(sy0 + 1, gy0 + (gy1 - gy0) * (r + 1) // 9)
                v = [raw[y * GW + x] for y in range(sy0, min(GH, sy1))
                     for x in range(sx0, min(GW, sx1))]
                row.append(sum(v) / len(v))
            cells.append(row)
            if max(row) - min(row) < 12:
                flat += 1
        allv = [v for row in cells for v in row]
        rng = max(allv) - min(allv)
        note = ""
        if is_static(n):
            # 静帧镜的这两个数换了含义：平坦行本来是在问"落幅停在这里会不会像静止"，
            # 而静帧镜本来就静止，那个问题不成立。剩下有意义的只有"这张停这么久
            # 够不够看"，所以只在整帧极差很低时提示，且只是提示。
            note = ("  << 静帧，整帧极差只有 %.0f，要停 %.1fs，会很空"
                    % (rng, durs[n - 1])) if rng < 25 else "  (静帧，平坦行不适用)"
        elif flat >= 3:
            note = "  << %d 行几乎无明暗变化，这一镜会像静止" % flat
        elif rng < 25:
            note = "  << 整帧极差只有 %.0f，运镜会看不出来" % rng
        print("  镜%-3d %-16s 整帧极差 %3.0f  平坦行 %2d/9%s"
              % (n, clip_key(CLIPS[n - 1])[:16], rng, flat, note))
    print("\n  平坦行对暗调图**结构性地误报**（大片夜空、暗海面本来就是平的）。")
    print("  真正要紧的是「这一镜从头走到尾画面变了多少」—— 渲完跑 motion 复核，")
    print("  判据均差 >= %.1f 级。别拿 trace 的平坦行去换图。" % MOTION_MIN)


# ================= 渲染 =================
def static_vf(s):
    """静帧镜的滤镜链：按 z/f0 裁一个固定取景窗，缩到成片尺寸，不动。

    取景算法和 zoompan 一致（窗宽高各 1/z、窗心在 f、clip 在图内），否则 trace
    反查的位置会和成片对不上 —— 那是全流水线唯一能自检取景的地方。
    实测过：同一个 z/f 两条路径渲出来做位移扫描，最小帧差落在 dx=0、dy 在 0~1 之间，
    即横向完全对齐、纵向差约半个像素（两条路在 PREP 和 UP 两种尺度上各自取整）。
    trace 用的是 724x1288 网格，一格比这粗五倍，不影响判断。

    不走 zoompan 还省掉 UP 那道 3 倍上采样（静帧不需要），且逐帧完全相同，
    x264 会压成一串 P 帧。
    """
    z, (fx_, fy_) = s["z"][0], s["f0"]
    crop = ("crop=w='iw/%.6f':h='ih/%.6f':"
            "x='clip(%.6f*iw-out_w/2,0,iw-out_w)':"
            "y='clip(%.6f*ih-out_h/2,0,ih-out_h)'" % (z, z, fx_, fy_))
    return (crop + ",scale=%d:%d:flags=lanczos," % (W, H)
            + (VIGNETTE + "," if VIGNETTE else "") + "setsar=1,format=yuv420p")


def pass_a():
    durs = timeline()[1]
    os.makedirs("shots", exist_ok=True)
    for i, s in enumerate(SHOTS, 1):
        dur = durs[i - 1]
        if is_video(i):
            pass_a_video(i, dur); continue
        if is_static(i):
            vf, how = static_vf(s), "静帧"
        else:
            d = max(1, int(round(dur * FPS)) - 1)
            z0, z1 = s["z"]; (x0, y0), (x1, y1) = s["f0"], s["f1"]
            ze = "%.6f+(%.6f)*on/%d" % (z0, z1 - z0, d)
            xe = ("max(0,min(iw-iw/zoom,(%.6f+(%.6f)*on/%d)*iw-(iw/zoom)/2))"
                  % (x0, x1 - x0, d))
            ye = ("max(0,min(ih-ih/zoom,(%.6f+(%.6f)*on/%d)*ih-(ih/zoom)/2))"
                  % (y0, y1 - y0, d))
            vf = ("scale=%d:%d:flags=lanczos," % UP
                  + "zoompan=z='%s':x='%s':y='%s':d=1:s=%dx%d:fps=%d,"
                    % (ze, xe, ye, W, H, FPS)
                  + (VIGNETTE + "," if VIGNETTE else "") + "setsar=1,format=yuv420p")
            how = "运镜"
        run(["ffmpeg", "-y", "-v", "error", "-stats", "-loop", "1",
             "-framerate", str(FPS), "-t", "%.3f" % dur,
             "-i", "img%02d.png" % i, "-vf", vf, "-c:v", "libx264", "-crf", "12",
             "-preset", "medium", "-pix_fmt", "yuv420p", "shots/shot%02d.mp4" % i],
            "镜头 %d/%d  %.1fs  %s" % (i, len(SHOTS), dur, how))


def pass_a_video(i, dur):
    """视频镜的 pass_a：从 vidNN.mp4 的头上取 dur 秒。

    `dur` 是旁白算出来的，和素材段本来就不一样长 —— 这条流水线里
    **时间永远由旁白说了算**，素材去迁就它，不是反过来。

    段比 dur 短时**冻结最后一帧补足**，并且报出来。不补的话 concat 会
    得到一段比时间轴短的片子，后面所有镜头整体前移，而且没有任何报错 ——
    这正是"不会报警的错"，所以宁可补上再喊一声。
    """
    src = "vid%02d.mp4" % i
    if not os.path.exists(src):
        print("   跳过(缺 %s，先跑 prep): 镜%d" % (src, i)); return
    info = probe_video(src)
    have = info[2] if info else 0.0
    vf = "setsar=1,format=yuv420p"
    note = "视频"
    if have + 1e-3 < dur:
        vf = ("tpad=stop_mode=clone:stop_duration=%.3f," % (dur - have + 0.5)) + vf
        note = "视频(素材短 %.2fs，冻结末帧补足)" % (dur - have)
        print("   !! 镜%d 的素材段只有 %.2fs，旁白要 %.2fs —— 已冻结末帧补足。"
              "要么把 to 往后放，要么把这一镜的旁白挪一句走" % (i, have, dur))
    run(["ffmpeg", "-y", "-v", "error", "-stats", "-i", src,
         "-t", "%.3f" % dur, "-vf", vf, "-an",
         "-c:v", "libx264", "-crf", "12", "-preset", "medium",
         "-pix_fmt", "yuv420p", "-r", str(FPS), "shots/shot%02d.mp4" % i],
        "镜头 %d/%d  %.1fs  %s" % (i, len(SHOTS), dur, note))


def motion():
    """量每一镜**渲出来**的首尾帧差 —— 运镜到底看不看得出来。

    `trace` 的落幅平坦度是出图阶段的筛子，它数的是"有几行几乎没有明暗变化"。
    对暗调实拍它**天生爱误报**：大片夜空、暗地面本来就是平的，
    整帧极差 147 的一张好图照样能报 8/16 行平坦。

    真正要紧的不是落幅那一帧长什么样，而是**这一镜从头走到尾画面变了多少**。
    那个只能在 shots/ 上量 —— 和 measure 之于 probe 是同一个关系：
    筛子在源头上估，判据在流水线的真实输出上量。

    判据：首尾帧的平均绝对差 < MOTION_MIN 就是"肉眼看不出在动"
    （亮度的可觉察差约 2~3 级，取 4 作下限）。

    ---- 静帧镜是**反过来**判的 ----
    标了 static 的镜子首尾帧差必须 <= MOTION_STATIC_MAX。"静帧镜其实在动"
    和"运镜镜其实不动"一样是错。只判运镜那一边的话，静帧片跑 motion 会全绿，
    那又是一个不会报警的检查。
    """
    if not os.path.isdir("shots"):
        sys.exit("!!! 还没有 shots/，先跑 a")
    durs = timeline()[1]
    GW, GH = 96, 171
    # 视频镜两个方向都不判：它"动不动"由素材决定，不是配置错误。
    # 末段那种几乎全是化学斑的档案影像首尾帧差可能很小 —— 那是内容，不是缺陷。

    def frame(f, t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "%.3f" % t, "-i", f,
                              "-frames:v", "1", "-vf",
                              "scale=%d:%d:flags=area,format=gray" % (GW, GH),
                              "-f", "rawvideo", "-"], capture_output=True).stdout
        return raw if len(raw) == GW * GH else None

    print("\n=== 运动实测（渲出来的首尾帧差）===")
    print("    运镜镜判据 均差 >= %.1f 级；静帧镜判据 均差 <= %.1f 级"
          % (MOTION_MIN, MOTION_STATIC_MAX))
    bad, drift, skipped, n_static, n_video = [], [], [], 0, 0
    for i in range(1, len(SHOTS) + 1):
        f = "shots/shot%02d.mp4" % i
        if not os.path.exists(f):
            print("  镜%-3d (未渲染)" % i); skipped.append(i); continue
        a, b = frame(f, 0.05), frame(f, max(0.1, durs[i - 1] - 0.1))
        if a is None or b is None:
            # 读不出多半是这一镜还在写（ffmpeg 还没收尾，moov atom 没落盘）。
            # **不能当成通过。** 第一版跳过之后照样打印"全部都看得出来"，
            # 又造出一个不会报警的检查 —— 这一条是被自己坑了一次之后加的。
            print("  镜%-3d %-16s (读不出帧，可能还在渲)" % (i, clip_key(CLIPS[i - 1])[:16]))
            skipped.append(i); continue
        d = sorted(abs(a[k] - b[k]) for k in range(GW * GH))
        mean = sum(d) / len(d)
        flag, how = "", ("视频" if is_video(i) else "静帧" if is_static(i) else "运镜")
        if is_video(i):
            # 视频镜两个方向都不判：它动不动由素材决定，不是配置错误。
            # 末段那种几乎全是化学斑的档案影像首尾帧差可能极小 —— 那是内容，不是缺陷。
            n_video += 1
        elif is_static(i):
            n_static += 1
            if mean > MOTION_STATIC_MAX:
                flag = "  << 标了 static 却在动，检查 z/f 的起止和 pass_a 走了哪条路"
                drift.append(i)
        elif ENDCARD and i == len(SHOTS):
            flag = "  (尾板，本来就该几乎静止 —— 不适用)"
        elif mean < MOTION_MIN:
            flag = "  << 肉眼看不出在动，加大 z 跨度或换一张有结构的图"
            bad.append(i)
        print("  镜%-3d %-16s %s 均差 %5.1f  中位 %3d  p90 %3d  最大 %3d%s"
              % (i, clip_key(CLIPS[i - 1])[:16], how, mean, d[len(d) // 2],
                 d[int(len(d) * 0.9)], d[-1], flag))
    if bad:
        print("\n  %d 镜运镜看不出来: %s" % (len(bad), ", ".join(str(i) for i in bad)))
    if drift:
        print("\n  %d 镜标了静帧却在动: %s" % (len(drift), ", ".join(str(i) for i in drift)))
    if skipped:
        print("\n  !! %d 镜没量到: %s —— **不算通过**，渲完再跑一次"
              % (len(skipped), ", ".join(str(i) for i in skipped)))
    if not bad and not drift and not skipped:
        print("\n  %d 镜全部对得上（运镜 %d 镜看得出动，静帧 %d 镜真的没动，"
              "视频 %d 镜不判 —— 动不动由素材决定）。"
              % (len(SHOTS), len(SHOTS) - n_static - n_video, n_static, n_video))


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
    1.5 倍是**为运镜定的**：余量是给行程用的。静帧镜没有行程，取景窗从头到尾
    就那一个，只需要 eff/z >= W（窗里的源像素不少于输出像素）。低于 1 是在放大，
    1.0~1.25 之间能用但没余量。

    这不是放松检查，是这一镜本来只需要这么多 —— 而它有实际后果：档案馆的老照片、
    博物馆开放数据里的画作很多卡在 1.0~1.5 之间，按运镜那条线一刀切会全判死，
    而它们做静帧完全够用。讲述片尤其吃这个：历史题材的真实图像常常只有这个分辨率。
    """
    bad, rows, warn_pp, vrows, prows = [], [], [], [], []
    # **贴纸版式和 PREP 的组合会静默出错。** prep_plate 出的是成片尺寸的图，
    # 而 pass_a 的 static_vf 会把 PREP 尺寸缩到成片尺寸 —— PREP 还是 3840x2160
    # 时，那张已经是 1920x1080 的台纸会被再缩一半，成片上图只有半幅大而四周全是台纸。
    # 渲得出来、不报错、退出码 0，只有真看画面才发现。
    if any(c.get("fit") == "plate" for c in CLIPS) and tuple(PREP) != (W, H):
        bad.append("有贴纸版式的镜，但 PREP=%s 不等于成片尺寸 %dx%d —— "
                   "pass_a 会把台纸再缩一次，成片上图只有 %.0f%% 大小。"
                   "用贴纸版式就要把 PREP 设成 (%d, %d)"
                   % (tuple(PREP), W, H, W / float(PREP[0]) * 100, W, H))
    for i, c in enumerate(CLIPS, 1):
        if c.get("video"):
            # **视频镜不走 pp 判据。** 档案影像天生就低分辨率 —— 640x480 铺到
            # 1080 高是 2.25 倍放大，按 pp<1.0 那条线一刀切会把整支片子判死，
            # 而"糊"恰恰是这类素材的内容本身。所以只报事实，不拦。
            vp = os.path.join(SRC, c["video"])
            info = probe_video(vp) if os.path.exists(vp) else None
            if info:
                vw, vh, vdur, vfps = info
                if VIDEO_FIT == "crop":
                    up = max(W / float(vw), H / float(vh))
                    keep = min(1.0, (vw / float(vh)) / (W / float(H)))
                else:
                    up = min(W / float(vw), H / float(vh))
                    keep = 1.0
                vrows.append((i, c["video"], vw, vh, vfps, vdur, up, keep))
            continue
        # "最紧取景"要用**这一镜自己的** z，不是全片的 z 最大值。用全局值时，
        # 各镜 z 差不多还看不出来；一旦跨度大（比如 1.02~2.15），低 z 的镜头会被
        # 算成远低于实际的源像素比，让人去换一张本来完全没问题的图。
        st = is_static(i) if i - 1 < len(SHOTS) else False
        zmax = ((SHOTS[i - 1]["z"][0] if st else max(SHOTS[i - 1]["z"]))
                if i - 1 < len(SHOTS) else 1.0)
        p = os.path.join(SRC, c["src"])
        if not os.path.exists(p):
            continue
        d = img_dims(p)
        if not d:
            continue
        w, h = d
        if c.get("fit") == "plate":
            # 贴纸镜不裁、不放大，pp 按定义就是 1.00。要看的是**另一件事**：
            # 这张图在画框里占多大 —— 占得太小就成了一张邮票贴在大黑板上。
            tw, th, sf = plate_box(w, h)
            # **判据用 max(占宽, 占高)，不用面积比。** 面积比对竖构图是稳定的误报：
            # 一张 480x1180 的海报贴上去正好把画框的高占满（该有的样子），
            # 面积却只有 23% —— 按面积判会说它"像一张邮票贴在黑板上"，
            # 而真正的邮票（两个方向都小）反而混在同一档里看不出来。
            prows.append((i, c["src"], w, h, tw, th, sf,
                          max(tw / float(W), th / float(H))))
            if not (i - 1 < len(SHOTS) and is_static(i)):
                bad.append("镜 %d 用了贴纸版式却不是静帧镜 —— 台纸不动，"
                           "运镜在它上面没有意义（写 motion=\"static\"）" % i)
            continue
        f = native_factor(w, h)
        # 裁成成片比例之后的**短边**。竖版模板这里直接用了裁后宽度，因为竖版的宽就是短边；
        # 横版反过来（宽是长边），照抄会拿长边去比 OUT_SHORT，pp 被虚报 W/H = 1.78 倍 ——
        # 于是一张刚够用的 1920x1080 被算成 pp 1.78，检查全部放行而一声不吭。
        crop_w = min(w, h * W / float(H))
        crop_h = crop_w * H / float(W)
        cw = min(crop_w, crop_h) / c["zoom"]
        eff = cw * f
        pp = eff / zmax / float(OUT_SHORT)
        tgt = pp_target(i) if i - 1 < len(SHOTS) else PP_KENBURNS
        rows.append((i, c["src"], w, h, f, eff, pp, st, tgt))
        # 判据分两级：pp < 1.0 = **在放大**，是缺陷，拦；1.0~目标 = 顶层细节
        # 从 98% 掉到 92%，是取舍不是缺陷，提示。
        # 旧的 flat "eff >= 1.5 x W" 两头都不对：对缓推镜多要一倍多的像素，
        # 对大推镜反而放行。
        if pp < 1.0 - 1e-3:
            msg = ("%s 最紧取景只有 %.2f 源像素/输出像素（<1.0 = 在放大，成片会软）"
                   % (c["src"], pp))
            # 填了 PP_ACCEPT_REASON 就降级成提示 —— 但**必须写理由**，而且理由会打印出来。
            # 不给一个"静默放行"的开关：那样下一支照抄配置时就再也不知道这里做过妥协了。
            (warn_pp if PP_ACCEPT_REASON.strip() else bad).append(msg)
    if prows:
        print("")
        print("=== 贴纸版式（%d 镜；不裁不放大，pp 恒为 1.00）===" % len(prows))
        print("   台纸 %s，看的是「图占画框多大」不是 pp" % PLATE_COLOR)
        for i, f_, w, h, tw, th, sf, frac in prows:
            flag = ""
            if frac < 0.60:
                flag = "  <- 两个方向都不满 60%，成片上会像一张邮票贴在黑板上"
            elif frac < 0.95:
                flag = "  <- 长边只到 %.0f%%" % (frac * 100)
            print("   镜%-3d %-22s %dx%d -> %dx%d  长边占画框 %.0f%%%s"
                  % (i, f_, w, h, tw, th, frac * 100, flag))
    if vrows:
        print("")
        print("=== 视频素材（%d 镜；**不参与 pp 判据**）===" % len(vrows))
        print("   填充方式：%s" % ("加黑边（保画幅完整）" if VIDEO_FIT == "pillarbox"
                                   else "裁切（填满画框）"))
        for i, f, vw, vh, vfps, vdur, up, keep in vrows:
            flag = ""
            if up > 3.0:
                flag = "  <- 放大超过 3 倍，成片上会很糊"
            elif keep < 0.999:
                flag = "  <- 裁掉了 %.0f%% 的画面" % ((1 - keep) * 100)
            print("   镜%-3d %-22s %dx%d  %.2ffps  源长 %.1fs  放大 %.2fx%s"
                  % (i, f, vw, vh, vfps, vdur, up, flag))
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
        if warn_pp:
            print("")
            print("   !! %d 镜低于 1.0，**已显式承认**（PP_ACCEPT_REASON 已填）：" % len(warn_pp))
            for ln in ("   " + PP_ACCEPT_REASON).split("。"):
                if ln.strip():
                    print("      " + ln.strip() + "。")
            print("      交付时这一条要照抄进制作说明的「哪几处是妥协的」。")
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
        if c.get("video"):        # 视频镜没有源图可以取原生像素样，不参与
            continue
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


def pass_b():
    _, durs, total, _ = timeline()
    ins = []
    for i in range(1, len(SHOTS) + 1):
        ins += ["-i", "shots/shot%02d.mp4" % i]
    parts, cur, off = [], "[0:v]", 0.0
    for i in range(1, len(SHOTS)):
        off += durs[i - 1] - xf(i - 1)
        parts.append("%s[%d:v]xfade=transition=fade:duration=%.3f:offset=%.3f[x%d]"
                     % (cur, i, xf(i - 1), off, i)); cur = "[x%d]" % i
    # **d=0 的 fade 不是"不淡入"。** ffmpeg 的 fade 在 duration 为 0 时会退回
    # nb_frames 的默认值 **25 帧** —— 30fps 下就是 0.83s 的黑场。
    # 中间段 FADE_IN/FADE_OUT 都是 0，照写就等于给每一段的头尾各塞一段黑场，
    # 而这正是接缝规矩要防的东西。check_seg 也拦不住：它验的是**配置**里 FADE 为 0，
    # 不是输出里真的没有黑场。这一处是 measure 的运镜对账抓出来的
    # （镜 1 起幅量到 2/3/2 几乎全黑，而预测 31/51/31）。
    fades = []
    if FADE_IN > 0:
        fades.append("fade=t=in:st=0:d=%.2f:c=%s" % (FADE_IN, FADE_COLOR))
    if FADE_OUT > 0:
        fades.append("fade=t=out:st=%.3f:d=%.2f:c=%s" % (total - FADE_OUT, FADE_OUT, FADE_COLOR))
    parts.append("%s%s[v]" % (cur, ("" if not fades else ",".join(fades) + ",") + "null"))
    run(["ffmpeg", "-y", "-v", "error", "-stats"] + ins
        + ["-filter_complex", ";".join(parts), "-map", "[v]", "-c:v", "libx264",
           "-crf", "14", "-preset", "medium", "-pix_fmt", "yuv420p",
           "-r", str(FPS), "master.mp4"],
        "拼接 %d 镜  总长 %.1fs" % (len(SHOTS), total))


# ================= 音频 =================
def integrated_lufs(path):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af",
                        "loudnorm=print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        m = json.loads(p.stderr[p.stderr.rfind("{"):p.stderr.rfind("}") + 1])
        return float(m["input_i"])
    except (ValueError, KeyError):
        return None


def band_rms(path, pre=None):
    """某个频段的 RMS。**分频段一律用 RMS，不用 LUFS** —— K 加权会把低频衰掉，
    正是要避开的那个骗局；同一个陷阱在老录音上换个方向出现（高频没了，
    整体 LUFS 却可能正常）。"""
    af = (pre + ",") if pre else ""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path,
                        "-af", af + "astats=metadata=1:reset=0", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.findall(r"RMS level dB:\s*(-?\d+\.\d+|-inf)", r.stderr)
    if not m:
        return None
    return -99.0 if m[-1] == "-inf" else float(m[-1])


def mquality():
    """判一条配乐能不能用。**公版录音必跑。**

    生成的曲子交回来是干净的；找来的录音坏在三处，都能量：
    一、**底噪** —— 历史转录带一层持续嘶声，音乐压到 −25 dB 后它跟着被听见；
    二、**带宽** —— 老转录高频到 5kHz 就没了，和现代音效放一起显得蒙，
        而且它自己盖不住自己的嘶声；
    三、**头尾静音与杂音** —— 抓轨常带引子静音，MUSIC_IN 会被整体推偏。
    量不出来的那件事（这条演奏好不好、贴不贴）必须交回用户。
    """
    if not music_on():
        sys.exit("!!! MUSIC_MODE='none' —— 这一支不要背景音乐")
    if not os.path.exists(MUSIC):
        sys.exit("!!! 音乐还没就位: " + MUSIC)
    total = timeline()[2]
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration:stream=sample_rate,channels",
                        "-of", "default=nw=1", MUSIC], capture_output=True, text=True)
    print("\n=== %s ===" % MUSIC)
    print("   " + "  ".join(ln.strip() for ln in p.stdout.splitlines() if ln.strip()))
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", MUSIC,
                        "-af", "ebur128=framelog=info", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    curve = []
    for ln in r.stderr.splitlines():
        if "t:" in ln and " M:" in ln:
            try:
                curve.append((float(ln.split("t:")[1].split()[0]),
                              float(ln.split(" M:")[1].split()[0])))
            except (IndexError, ValueError):
                pass
    integ = integrated_lufs(MUSIC)
    print("\n   整合响度 %.1f LUFS" % (integ if integ is not None else -99))
    if curve:
        live = [m for _, m in curve if m > -70]
        floor = min(live) if live else -70.0
        gap = (integ - floor) if integ is not None else 0
        print("   全曲 %.1fs（片长 %.1fs，余地 %.1fs）" % (curve[-1][0], total,
                                                          curve[-1][0] - total))
        print("   最安静的一刻 %.1f LUFS，离整合响度 %.0f dB —— %s"
              % (floor, gap,
                 "生成的曲子一般 >40 dB；<30 dB 多半有一层持续嘶声" if gap < 30 else "够干净"))
    print("\n   分频段 RMS（判带宽）：")
    full = band_rms(MUSIC)
    for name, f in (("<120Hz", "lowpass=f=120"),
                    ("120-2k", "highpass=f=120,lowpass=f=2000"),
                    ("2k-8k", "highpass=f=2000,lowpass=f=8000"),
                    (">8kHz", "highpass=f=8000")):
        v = band_rms(MUSIC, f)
        rel = (v - full) if (v is not None and full is not None) else 0
        note = ("  << 8k 以上基本是空的 —— 老转录"
                if name == ">8kHz" and rel < -40 else "")
        print("      %-7s %6.1f dB  (相对全带 %+.1f)%s" % (name, v if v else -99, rel, note))
    diff = band_rms(MUSIC, "pan=mono|c0=0.5*c0-0.5*c1")
    if diff is not None and full is not None:
        print("      左右差信号 %.1f dB —— %s"
              % (diff, "单声道（不是毛病，知道就行）" if diff - full < -40 else "立体声"))
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", MUSIC,
                        "-af", "silencedetect=n=-45dB:d=0.4", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    head = [ln for ln in r.stderr.splitlines() if "silence_end:" in ln]
    if head and "silence_start: 0" in r.stderr.split("silence_end:")[0]:
        try:
            print("\n   头部静音 %.2fs —— **MUSIC_IN 要把它算进去**"
                  % float(head[0].split("silence_end:")[1].split()[0]))
        except (IndexError, ValueError):
            pass
    if MUSIC_MODE == "public_domain":
        miss = [k for k in ("work", "performer", "source", "license", "url")
                if not str(MUSIC_CREDIT.get(k, "")).strip()]
        print("\n   授权登记: " + ("**缺 %s**，check 会拦" % "/".join(miss) if miss
                                   else "齐了（%s）" % MUSIC_CREDIT["license"]))
    print("\n   量不出来的那件事：**这条演奏好不好、贴不贴这一支**。")
    print("   多留一条候选、把最终选择交回用户，比自己拍板诚实。")


def credits():
    """导出素材来源表。用了找来的素材时，它是交付物的一部分。"""
    lines = ["# %s · 素材来源" % TITLE, "", "成片：%s" % OUT_NAME, "", "## 画面", ""]
    if IMG_SOURCE == "found":
        lines.append("| 镜 | 文件 | 类型 | 用到的段 | 作品 | 收藏/权利人 | 来源 | 授权 | 链接 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for i, c in enumerate(CLIPS, 1):
            k = clip_key(c)
            e = CREDITS.get(k, {})
            seg = ("%s–%s" % (c.get("ss"), c.get("to"))) if c.get("video") else "—"
            lines.append("| %d | %s | %s | %s | %s | %s | %s | %s | %s |"
                         % (i, k, "视频" if c.get("video") else "静图", seg,
                            e.get("title", "**缺**"), e.get("holder", "**缺**"),
                            e.get("source", "**缺**"), e.get("license", "**缺**"),
                            e.get("url", "**缺**")))
    else:
        lines.append("按出图任务书生成（IMG_SOURCE='generated'），无第三方权利。")
    lines += ["", "## 配乐", ""]
    if not music_on():
        lines.append("无背景音乐（MUSIC_MODE='none'）。")
    elif MUSIC_MODE == "generated":
        lines.append("生成（ChatCut submit_music），无第三方权利。")
    elif MUSIC_MODE == "library":
        lines.append("从素材库复用：`%s`（原为自生成），无第三方权利。"
                     % (MUSIC_FROM_LIBRARY or "**没填 MUSIC_FROM_LIBRARY**"))
    else:
        for k, label in (("work", "作品"), ("performer", "演奏/录音"),
                         ("source", "来源"), ("license", "授权"), ("url", "链接")):
            lines.append("- %s：%s" % (label, MUSIC_CREDIT.get(k, "**缺**")))
        lines += ["", "> **录音权与作品权是两回事。** 上面登记的是**这一次录音**的授权，"
                      "不是作曲家去世多少年。"]
    lines += ["", "## 旁白与音效", "", "旁白 %d 条为 TTS 生成，无第三方权利。" % len(NARR)]
    # **音效不能一句"均为生成"带过。** 找来的音效有第三方权利，来源就写在同一个
    # 脚本的 SFX_CREDITS 里 —— 第一版的 credits 根本不读它，于是在交付物里
    # **断言了一件不成立的事**（"音效 N 条为生成，均无第三方权利"）。
    # 它不报错，只是把一句假话写进了要交出去的文件。四支片子都这么写过。
    used = []
    for e in SFX:
        if e["f"] not in used:
            used.append(e["f"])
    found = [f for f in used if f in SFX_CREDITS]
    if not found:
        lines.append("音效 %d 条（%d 个文件）全部为生成或自有素材库，无第三方权利。"
                     % (len(SFX), len(used)))
    else:
        lines.append("音效 %d 条，用到 %d 个文件，其中 **%d 个来自第三方**，逐条登记如下。"
                     % (len(SFX), len(used), len(found)))
        lines += ["", "| 文件 | 作品 | 作者 | 来源 | 授权 | 链接 |",
                  "|---|---|---|---|---|---|"]
        for f in found:
            e = SFX_CREDITS[f]
            lines.append("| %s | %s | %s | %s | %s | %s |"
                         % (f, e.get("title", "**缺**"), e.get("author", "**缺**"),
                            e.get("source", "**缺**"), e.get("license", "**缺**"),
                            e.get("url", "**缺**")))
        lines += ["", "其余 %d 个文件为生成或自有素材库，无第三方权利。" % (len(used) - len(found)),
                  "",
                  "> **署名一律给。** Pixabay 的 License Summary 说署名非强制，"
                  "但同一页也写着「certain Content may be subject to additional "
                  "intellectual property rights，**It is your responsibility to check**」——"
                  "而从 Freesound 转载的条目，原始授权可能是 CC-BY（要求署名）。"
                  "署名成本为零，不署名的风险不为零。"]
    out = os.path.join("..", "素材来源.md")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print("素材来源表 -> " + out)
    if "**缺**" in "\n".join(lines):
        print("!! 表里有**缺**的格子 —— 先把 CREDITS / MUSIC_CREDIT 填全（check 也会拦）")


def pick_music_in():
    """maximin 选音乐切入点。

    **讲述片的关键窗口和诗片不一样。** 诗片全程只有音乐，窗口取每句字幕的落点；
    讲述片全程有旁白盖着，音乐在那些地方本来就该退到后面 ——
    真正听得见音乐的是**旁白之间的缝**：冷开场、长转场、金句留白、尾板。
    照搬诗片那套窗口会选错点。

    公版录音多一件事：**真曲子有终止式**。除了 maximin 的解，这里还会单独评一个
    "让曲子的自然收束正好落在片尾"的候选。乐句边界本身量不出来，最终要听。"""
    if not music_on():
        sys.exit("!!! MUSIC_MODE='none' —— 这一支不要背景音乐，没有切入点可挑")
    if not os.path.exists(MUSIC):
        sys.exit("!!! 音乐还没就位: " + MUSIC)
    lines, durs, total, starts = timeline()
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
        sys.exit("!!! 读不出响度曲线（ffmpeg 8.x 要 framelog=info，不是 verbose）")
    mdur = curve[-1][0]
    print("全曲 %.1fs，采样 %d 点，最低 %.1f / 最高 %.1f LUFS"
          % (mdur, len(curve), min(m for _, m in curve), max(m for _, m in curve)))

    keys = [("冷开场", 0.0, max(1.5, NARR[0]["pre"]))]
    for i in range(len(SHOTS) - 1):          # 每个长转场都是一处听得见音乐的缝
        if xf(i) >= 1.5:
            keys.append(("镜%d→%d 长转场" % (i + 1, i + 2),
                         max(0.0, starts[i + 1] - xf(i)), xf(i) + 1.5))
    gaps = []                                # 旁白之间 >=0.9s 的静默
    for a, b in zip(lines, lines[1:]):
        g = b[4] - (a[4] + a[5])
        if g >= 0.9:
            gaps.append((a[4] + a[5], g))
    gaps.sort(key=lambda x: -x[1])
    for t, g in gaps[:3]:
        keys.append(("留白 %.0fs" % t, t, g))
    keys.append(("尾板", starts[-1], min(6.0, durs[-1])))
    keys.append(("淡出", total - FADE_OUT, FADE_OUT))

    def win_avg(off, a, d):
        v = [m for t, m in curve if off + a <= t <= off + a + d]
        return sum(v) / len(v) if v else -70.0

    room = mdur - total
    if room <= 0:
        sys.exit("!!! 音乐比片子还短")
    best, off = None, 0.0
    while off <= room + 1e-6:
        scores = [win_avg(off, a, d) for _, a, d in keys]
        mn = min(scores)
        if best is None or mn > best[0]:
            best = (mn, off, scores)
        off += 0.5
    mn, off, scores = best
    print("\nmaximin 选出切入点 %.1fs（余地 %.1fs，用到 %.1fs）" % (off, room, off + total))
    for (name, _, _), s in zip(keys, scores):
        print("   %-16s %.1f LUFS" % (name, s))
    print("   全片最弱落点 %.1f LUFS" % mn)
    print("   这一段的最深谷 %.1f LUFS"
          % min(m for t, m in curve if off <= t <= off + total))
    valleys(curve, off, total, starts)
    if MUSIC_MODE == "public_domain":
        ts = [win_avg(room, a, d) for _, a, d in keys]
        print("\n另一个候选：切入点 %.1fs —— 曲子的自然收束正好落在片尾" % room)
        print("   全片最弱落点 %.1f LUFS（maximin 那个是 %.1f，差 %.1f dB）"
              % (min(ts), mn, min(ts) - mn))
        print("   **这两个哪个对要听。** 差在 2 dB 以内就选这个，"
              "让曲子有结尾比多两分贝值钱")
    print("\n把 MUSIC_IN 改成 %.1f" % off)


def valleys(curve, off, total, starts, thr=-25.0, minlen=0.4):
    """把用到的这一段里低于 thr 的谷全列出来，并说清它落在片子的哪一镜。

    "拿到曲子先翻一遍低谷再决定要不要第二条候选"原来是句手工提醒 —— 手工翻要看
    几百行响度采样，翻漏是必然的。上一支的候选 A 在 121~130s 藏了 1.7 秒近乎静音，
    是翻出来才弃用的；另一支的最低 −70.6 在 191s，那只是**结尾的自然收尾**、
    根本没用到。两者的区别决定要不要重新生成，所以值得自动化。
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
        ta, tb = a - off, b - off
        n = sum(1 for s in starts if ta >= s - 1e-6)
        where = "片尾淡出里" if ta > total - FADE_OUT else "镜 %d" % max(1, n)
        print("      曲上 %6.1f~%6.1f  ->  片上 %6.1f~%6.1f (%.1fs)  %s"
              % (a, b, ta, tb, tb - ta, where))
    print("   落在片尾淡出里的不算问题；落在正片里的**中段 breakdown** 才是"
          "该换一条曲子的理由")


def mix_name(lang):
    return "mix_%s.wav" % lang


def build_audio(lang=None):
    """旁白 + 音乐(侧链躲闪) + 音效，混出**一条语言**的音床。

    音乐**必须侧链躲闪**，只调低音量是不够的：压到听不见音乐就没意义，
    压不够旁白就发浑。每条旁白**单独**归一到 VO_TARGET，顺带抹平 TTS 的忽大忽小。

    **多音轨时这个函数每种语言各跑一遍。** 音乐和音效是同一床、同样的切入点和增益，
    只有旁白换语言 —— 但侧链要按**各自的**旁白重算：英文的停顿位置和中文不一样，
    拿中文的包络去躲英文，音乐会在英文正在说话的地方抬起来。
    旁白的落点一律取中文定出来的 vs（画面只有一份），所以这里不重排时间轴。
    """
    lang = lang or DEFAULT_LANG
    lines, _, total, _ = timeline()
    durs_map, missing = vo_durs(lang)
    if missing:
        sys.exit("!!! %s 轨还缺 %d 条旁白，不能混音: %s"
                 % (LANG_INFO[lang]["name"], len(missing), ", ".join(missing[:3])))
    ins, parts, vbus, k = [], [], [], 0
    if music_on():
        ins += ["-i", MUSIC]
        parts.append("[0:a]aresample=48000,aformat=fltp:cl=stereo,"
                     "atrim=start=%.3f:end=%.3f,asetpts=PTS-STARTPTS,volume=%.1fdB,"
                     "apad,atrim=0:%.3f,afade=t=in:st=0:d=%.2f,afade=t=out:st=%.3f:d=3[m]"
                     % (MUSIC_IN, MUSIC_IN + total, MUSIC_GAIN, total,
                        MUSIC_FADE_IN, max(0.0, total - 3)))
        k = 1
    print("\n=== %s 旁白增益（每条按实测反算到 %.1f LUFS）==="
          % (LANG_INFO[lang]["name"], VO_TARGET))
    # lines 与 NARR 严格同序（timeline 按镜号分组、组内保序，而 NARR 本来就按镜号排），
    # 所以按下标取起点，不要按文本去匹配 —— 两句话一字不差是很常见的
    for j, n in enumerate(NARR):
        path = vo_path(n, lang)
        meas = integrated_lufs(path)
        g = VO_TARGET - meas if meas is not None else 0.0
        print("   %-11s 实测 %6.1f → %+6.1f dB" % (n["vo"], meas if meas else 0, g))
        vs = lines[j][4]
        ins += ["-i", path]
        parts.append("[%d:a]aresample=48000,aformat=fltp:cl=stereo,volume=%.1fdB,"
                     "adelay=%d|%d,apad[v%d]" % (k, g, int(vs * 1000), int(vs * 1000), k))
        vbus.append("[v%d]" % k)
        k += 1
    parts.append("%samix=inputs=%d:normalize=0:dropout_transition=0,atrim=0:%.3f[vo]"
                 % ("".join(vbus), len(vbus), total))
    if music_on():
        parts.append("[vo]asplit=2[voa][vosc]")
        parts.append("[m][vosc]sidechaincompress=threshold=%.3f:ratio=%d:attack=%d:"
                     "release=%d[md]"
                     % (DUCK["threshold"], DUCK["ratio"], DUCK["attack"], DUCK["release"]))
        mixed = ["[md]", "[voa]"]
    else:
        # 没有音乐就没有要躲闪的东西 —— 侧链是"让音乐给旁白让路"，不是旁白的效果。
        # 照着有音乐那条路写下去会引用一个不存在的 [m]，filter_complex 直接报错。
        parts.append("[vo]anull[voa]")
        mixed = ["[voa]"]
    # 音效起点按**镜号 + 镜内偏移**解析成秒数。旁白一改，绝对秒数全错，
    # 而"在镜 3 开头进来"这个意图不变 —— 所以让脚本来算，不手写秒数。
    st_shots = shot_starts()
    print("\n=== 音效（目标响度锚在 VO_TARGET=%.1f 上，不是音乐）===" % SFX_ANCHOR)
    for s in SFX:
        f, tgt, fi, fo = s["f"], s["tgt"], s["fi"], s["fo"]
        dur = sfx_dur(s)
        if not 1 <= s["shot"] <= len(SHOTS):
            sys.exit("!!! 音效 %s 的 shot=%d 超出 %d 镜" % (f, s["shot"], len(SHOTS)))
        t = max(0.0, st_shots[s["shot"] - 1] + s["off"])
        if t + dur > total + 1e-6:
            print("   ** %s 从 %.1fs 放 %.1fs 会超出段长 %.1fs，已裁短" % (f, t, dur, total))
            dur = max(0.1, total - t)
        path = os.path.join(SRC, f)
        if not os.path.exists(path):
            print("   跳过音效(缺文件): " + f); continue
        meas = integrated_lufs(path)
        g = tgt - meas if meas is not None else -20.0
        flag = "  << 提得太多，底噪会一起上来，建议重生成" if g > SFX_GAIN_WARN else ""
        print("   %-14s 镜%-3d 起 %6.2fs 长 %5.1fs  实测 %6.1f → 目标 %6.1f（VO%+.0f），增益 %+6.1f dB%s"
              % (f, s["shot"], t, dur, meas or 0, tgt, tgt - SFX_ANCHOR, g, flag))
        ins += ["-stream_loop", "-1", "-i", path]
        parts.append("[%d:a]aresample=48000,aformat=fltp:cl=stereo,atrim=0:%.3f,"
                     "asetpts=PTS-STARTPTS,volume=%.1fdB,afade=t=in:st=0:d=%.2f,"
                     "afade=t=out:st=%.3f:d=%.2f,adelay=%d|%d,apad[s%d]"
                     % (k, dur, g, fi, max(0.0, dur - fo), fo, int(t * 1000), int(t * 1000), k))
        mixed.append("[s%d]" % k)
        k += 1
    # **`level=disabled` 比 `limit` 本身更要紧。**
    # alimiter 的 `level` 选项默认是开的，它会把输出**重新归一回 0 dBFS** ——
    # 于是 `limit=0.85` 限完又被抬回去，一点余量都不剩。实测同一条 mix：
    #     alimiter=limit=0.85                  样本峰值 -0.0 dB / 真峰值 +0.10 dBTP
    #     alimiter=limit=0.85:level=disabled   样本峰值 -1.4 dB / 真峰值 -1.32 dBTP
    # 之前把 0.95 改成 0.85 是白改的，从来没产生过余量 —— 参数写了但没生效，
    # 和运镜那个"写了位移却没给足缩放"是同一个形状：**参数表上完全看不出来。**
    #
    # 为什么要留余量：**段用文件是要交给 join 再编码一次的中间件**，顶在 0 dBTP 上
    # AAC 解码会漏一层失真。1.4 dB 是**所有段共用的常数**，不会变成逐段增益差。
    # 预览那一路照旧归一到 −15，看不出区别。
    parts.append("%samix=inputs=%d:normalize=0:dropout_transition=0,"
                 "atrim=0:%.3f,alimiter=limit=0.85:level=disabled[a]" % ("".join(mixed), len(mixed), total))
    out = mix_name(lang)
    run(["ffmpeg", "-y", "-v", "error", "-stats"] + ins
        + ["-filter_complex", ";".join(parts), "-map", "[a]",
           "-c:a", "pcm_s24le", "-t", "%.3f" % total, out],
        "混音(%s): 旁白 %d 条 + %s + 音效 %d 条 -> %s"
        % (LANG_INFO[lang]["name"], len(NARR),
           "音乐(从 %.1fs 切入，侧链躲闪)" % MUSIC_IN if music_on() else "无音乐",
           len(mixed) - (2 if music_on() else 1), out))
    return out


def measure_loudness(path):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af",
                        "loudnorm=I=%.1f:TP=%.1f:print_format=json" % (TARGET_I, TARGET_TP),
                        "-f", "null", "-"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    m = json.loads(p.stderr[p.stderr.rfind("{"):p.stderr.rfind("}") + 1])
    print("   实测 I=%s LUFS  TP=%s dBTP" % (m["input_i"], m["input_tp"]))
    return m


# ================= 字幕 =================
def _style(name, size, pol, spacing=0, align=5):
    # **第 4 个位置参数是字距，第 5 个才是对齐。**
    # 传 _style(..., 3) 想要右下对齐，实际设的是字距 3、对齐仍是默认的 5（居中），
    # 于是 \pos 变成以该点为中心，一半文字跑出画面 —— 而且渲得出来，不报错。
    if pol == "dark_on_light":
        pri, out, ol, sh = "&H00262A2D", "&H00EAF3F6", 3, 0
    else:
        pri, out, ol, sh = "&H00F2F2EC", "&H00000000", 3, 3
    return ("Style: %s,%s,%d,%s,%s,%s,%s,0,0,0,0,100,100,%d,0,1,%d,%d,%d,20,20,0,1"
            % (name, SUB_FONT, size, pri, pri, out, out, spacing, ol, sh, align))


def styles_block():
    return "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour," \
           "SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline," \
           "StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow," \
           "Alignment,MarginL,MarginR,MarginV,Encoding\n" \
           + "\n".join([_style("T", 88, TITLE_POLARITY, 6),
                        _style("TS", 44, TITLE_POLARITY, 8),
                        _style("M", SUB_FS, POLARITY, 2),
                        _style("L", 26, POLARITY, 0, 3)]) + "\n"


def ts(t):
    return "%d:%02d:%05.2f" % (t // 3600, t % 3600 // 60, t % 60)


def srt_ts(t):
    """SRT 的时间码是 HH:MM:SS,mmm —— 毫秒用**逗号**，不是 ASS 的点。
    写成点号大多数播放器会整条丢掉而**不报错**，字幕就是"莫名其妙没有"。"""
    ms = int(round(t * 1000))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60,
                                    ms // 1000 % 60, ms % 1000)


def preview(lang=None):
    """出图之前的检查片：**占位画面 + 真旁白 + 真字幕**。门禁二靠它。

    多音轨时可以 `preview en` 单听英文那条 —— 英文塞得进槽是 langfit 算出来的，
    **听起来赶不赶只有放出来才知道**，而这时候图还没出，改稿最便宜。

    交给用户的是一支能听完的片子，不是一堆数字。它定死四件事，全在出图之前：
    旁白好不好听 · 断句与气口 · 字幕跟不跟得上 · **片长**。
    真图到了直接替换同名文件，CLIPS / SHOTS / NARR 一个字都不用动。

    ---- 三条实现上的讲究 ----

    1. **所有文字都走 ASS，一个 drawtext 都不用。** 带 drawtext 的 ffmpeg 在
       Git bash 下会 Fontconfig error + 段错误（见 references/codex.md），
       而 `subtitles=`（libass）这条路整条流水线天天在跑，是验过的。
       占位板上的镜号、文件名、画面描述因此全部当字幕烧，不画进图里。

    2. **背景只出一张，不是一镜一张。** 镜与镜的分界靠镜号标签变化看出来，
       够用；一镜一张要多跑 N 条 ffmpeg 换不来任何信息。

    3. **只有旁白，没有音效没有音乐。** 这一版要验的是"话说得对不对"，
       多铺一层会让人分神去听氛围。而且这时候音效多半还没找。

    ---- 这一版验不了什么（必须说清楚，别让它冒充通过）----

      motion            **结构性失效** —— 占位板是均匀灰，中位帧差恒为 0
      trace / measure   不适用 —— 量的是真实画面的明暗
      字幕排版          **有效** —— 断行/宽度只跟字号坐标有关，跟画面无关
    """
    lang = lang or DEFAULT_LANG
    _, durs, total, starts = timeline()
    lines = lang_lines(lang)
    durs_map, missing = vo_durs(lang)
    if missing:
        sys.exit("!!! %s 轨还缺 %d 条旁白，出不了检查片: %s"
                 % (LANG_INFO[lang]["name"], len(missing), ", ".join(missing[:5])))

    # ---- 背景：深灰 + 一条压暗的横带标出字幕位置 ----
    y0 = max(0, SUB_BOT - 2 * SUB_LH - 14)
    bh = min(H - y0, 2 * SUB_LH + 28)
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "color=c=0x2b2b2b:s=%dx%d" % (W, H),
         "-vf", "drawbox=x=0:y=%d:w=%d:h=%d:color=0x171717@1:t=fill" % (y0, W, bh),
         "-frames:v", "1", "_pv_bg.png"], "占位背景")

    # ---- 一份 ASS 装下全部文字：镜号 / 图名 / 描述 / 正文字幕 ----
    ev = []
    for i, c in enumerate(CLIPS):
        t0 = starts[i]
        t1 = starts[i + 1] if i + 1 < len(starts) else total
        desc = SHOTS[i].get("desc", "")
        head = "镜 %d / %d" % (i + 1, len(CLIPS))
        reuse = [j + 1 for j, d in enumerate(CLIPS) if clip_key(d) == clip_key(c)]
        if len(reuse) > 1:
            head += "   （%s 共用一张图）" % " / ".join("镜%d" % r for r in reuse)
        z0, z1 = SHOTS[i]["z"]
        move = ("静帧" if z0 == z1 and SHOTS[i]["f0"] == SHOTS[i]["f1"]
                else "推近" if z1 > z0 else "拉远" if z1 < z0 else "横移")
        head += "   %s z %.2f→%.2f   %.1fs" % (move, z0, z1, t1 - t0)
        for k, txt in enumerate([head, clip_key(c), desc]):
            if not txt:
                continue
            ev.append("Dialogue: 0,%s,%s,PV,,0,0,0,,{\\pos(%d,%d)}%s"
                      % (ts(t0), ts(t1), W // 2,
                         int(H * 0.16) + k * int(PV_FS * 1.7), txt))
    # **逐行堆叠，不要挤成一条。** 排版要和成片一模一样，
    # 否则「字幕跟不跟得上」这一项验的就不是真东西了。
    for st, en, txt, _, _, _ in lines:
        parts = sub_lines(txt)
        for j, q in enumerate(parts):
            y = SUB_BOT - (len(parts) - 1 - j) * SUB_LH - SUB_FS // 2
            ev.append("Dialogue: 1,%s,%s,M,,0,0,0,,{\\pos(%d,%d)}%s"
                      % (ts(st), ts(en), SUB_CX, y, q))
    with open("_pv.ass", "w", encoding="utf-8-sig") as f:
        f.write("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\n"
                "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n" % (W, H)
                + styles_block()[:-1] + "\n"
                + _style("PV", PV_FS, "light_on_dark", 2) + "\n"
                + "\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,"
                  "MarginV,Effect,Text\n" + "\n".join(ev) + "\n")

    # ---- 音频：只有旁白，每条按实测反算到 VO_TARGET ----
    ins, parts, bus = ["-loop", "1", "-i", "_pv_bg.png"], [], []
    for j, n in enumerate(NARR):
        path = vo_path(n, lang)
        meas = integrated_lufs(path)
        g = VO_TARGET - meas if meas is not None else 0.0
        vs = lines[j][4]
        ins += ["-i", path]
        parts.append("[%d:a]aresample=48000,aformat=fltp:cl=stereo,volume=%.1fdB,"
                     "adelay=%d|%d,apad[v%d]"
                     % (j + 1, g, int(vs * 1000), int(vs * 1000), j + 1))
        bus.append("[v%d]" % (j + 1))
    parts.append("%samix=inputs=%d:normalize=0:dropout_transition=0,"
                 "atrim=0:%.3f,alimiter=limit=0.85:level=disabled[a]"
                 % ("".join(bus), len(bus), total))
    parts.append("[0:v]fps=%d,format=yuv420p,subtitles=_pv.ass:fontsdir=%s[v]"
                 % (FPS, FONTS.replace("\\", "/")))

    out = os.path.join("..", CHECK_NAME if lang == DEFAULT_LANG
                       else CHECK_NAME.replace(".mp4", ".%s.mp4" % lang))
    run(["ffmpeg", "-y", "-v", "error", "-stats"] + ins
        + ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]",
           "-t", "%.3f" % total, "-c:v", "libx264", "-crf", "23",
           "-preset", "veryfast", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", out],
        "检查片(%s) %d 镜 / %d 条旁白 / %.1fs -> %s"
        % (LANG_INFO[lang]["name"], len(CLIPS), len(NARR), total, out))
    for f in ("_pv_bg.png", "_pv.ass"):
        if os.path.exists(f):
            os.remove(f)
    print("")
    print("  **这一版没有音效、没有音乐**，要验的是话说得对不对。")
    print("  片长 %.3fs = %.1f 分。%s"
          % (total, total / 60.0,
             "硬线 %ds，%s" % (HARD_LIMIT,
                              "还差 %.1fs" % (HARD_LIMIT - total) if total <= HARD_LIMIT
                              else "**已超 %.1fs**" % (total - HARD_LIMIT))
             if globals().get("HARD_LIMIT") else "没有硬线"))
    print("  交给用户听完，把结论写进 GATE_PREVIEW_OK，才允许出图。")
    print("  motion / trace / measure 对占位板**不适用**，这时候别跑。")
    return out


def make_srt(lang=None):
    """正文字幕 → 外挂 SRT。多音轨时每种语言各一份，文件名由 srt_name() 定。

    两处和烧录不一样：
      - 手工断行符 SUB_SEP 在 SRT 里就是真正的换行（烧录时是分行定位）
      - **相邻两条不能重叠**：烧录时重叠只是两行字同时在屏上，SRT 里
        重叠会让播放器行为不一致（有的堆叠、有的闪、有的丢）。所以硬性收尾。

    英文那份的**起点和中文完全一样**（槽是中文定的），只有收尾跟着英文音频走。
    """
    lang = lang or DEFAULT_LANG
    lines = lang_lines(lang)
    ev, fixed = [], 0
    for i, (st, en, txt, _, _, _) in enumerate(lines):
        if i + 1 < len(lines) and en > lines[i + 1][0] - 0.04:
            en = max(st + 0.4, lines[i + 1][0] - 0.04)
            fixed += 1
        ev.append("%d\n%s --> %s\n%s\n" % (len(ev) + 1, srt_ts(st), srt_ts(en),
                                           "\n".join(sub_lines(txt))))
    out = os.path.join("..", srt_name(lang))
    with open(out, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(ev))
    print("已生成 %s（%s，%d 条%s）"
          % (out, LANG_INFO[lang]["name"], len(ev),
             "，收掉 %d 处重叠" % fixed if fixed else ""))
    return out


def make_ass():
    """**只有烧进画面的东西**：开场标题字卡、尾板。正文字幕走 make_srt。"""
    starts = timeline()[3]
    ev = []
    if TITLE_CARD:
        ev.append("Dialogue: 0,%s,%s,T,,0,0,0,,{\\pos(%d,%d)}{\\fad(900,900)}%s"
                  % (ts(TITLE_CARD["t0"]), ts(TITLE_CARD["t1"]),
                     W // 2, TITLE_CARD["y"], TITLE_CARD["head"]))
        ev.append("Dialogue: 0,%s,%s,TS,,0,0,0,,{\\pos(%d,%d)}{\\fad(900,900)}%s"
                  % (ts(TITLE_CARD["t0"] + 0.6), ts(TITLE_CARD["t1"]),
                     W // 2, TITLE_CARD["y"] + 92, TITLE_CARD["sub"]))
    for _sn, _tx in sorted(SHOT_LABELS.items()):
        _i = _sn - 1
        if not (0 <= _i < len(starts)):
            sys.exit("!!! SHOT_LABELS 里的镜 %d 不存在" % _sn)
        _a = starts[_i] + 0.5
        _b = (starts[_i + 1] if _i + 1 < len(starts) else total_len()) - 0.3
        if _b - _a < 0.8:
            print("   角标跳过镜 %d：在屏不足 0.8s" % _sn)
            continue
        ev.append("Dialogue: 0,%s,%s,L,,0,0,0,,{\\an3\\pos(%d,%d)}{\\fad(400,400)}%s"
                  % (ts(_a), ts(_b), W - 40, H - 44, _tx))
    if ENDCARD:
        t0 = starts[-1] + ENDCARD["t0"]
        t1 = min(starts[-1] + ENDCARD["t1"], total_len())
        ev.append("Dialogue: 0,%s,%s,T,,0,0,0,,{\\pos(%d,%d)}{\\fad(900,800)}%s"
                  % (ts(t0), ts(t1), W // 2, ENDCARD["y"], ENDCARD["head"]))
        ev.append("Dialogue: 0,%s,%s,TS,,0,0,0,,{\\pos(%d,%d)}{\\fad(900,800)}%s"
                  % (ts(t0 + 0.5), ts(t1), W // 2, ENDCARD["y"] + 96, ENDCARD["sub"]))
    with open("sub.ass", "w", encoding="utf-8-sig") as f:
        f.write("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\n"
                "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n" % (W, H)
                + styles_block()
                + "\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,"
                  "MarginV,Effect,Text\n" + "\n".join(ev) + "\n")
    print("已生成 sub.ass（%d 条，只有标题/尾板）" % len(ev))
    return bool(ev)


def make_scrim():
    """字幕在**左下**，所以 scrim 压的是底部，不是诗片的右侧。"""
    if SCRIM_ALPHA <= 0:
        return False
    c = "white" if POLARITY == "dark_on_light" else "black"
    v = "255" if c == "white" else "0"
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         "color=c=%s:s=%dx%d,format=rgba," % (c, W, H)
         + r"geq=r='%s':g='%s':b='%s':a='clip(255*%.3f*pow(max(0\,(Y-%d))/%d\,%.2f),0,255)'"
         % (v, v, v, SCRIM_ALPHA, SCRIM_Y0, SCRIM_SOFT, SCRIM_POW),
         "-frames:v", "1", "scrim.png"], "生成底部 scrim")
    return True


def video_chain(tag="[0:v]", scrim=False, grain=True, text=True):
    """画面链。`text` 只管**烧进画面的标题/尾板** —— 正文字幕是外挂的，不在这里。
    没有标题也没有尾板时（中间段）整条 subtitles 滤镜要省掉，不要挂一个空的。"""
    fd = FONTS.replace("\\", "/")
    pre = "%snoise=alls=2:allf=t[g];" % tag if grain else ""
    base = "[g]" if grain else tag
    if scrim:
        pre += "%s[1:v]overlay=0:0:shortest=1[s];" % base
        base = "[s]"
    if text:
        return pre + "%ssubtitles=sub.ass:fontsdir=%s[v]" % (base, fd)
    return pre + "%snull[v]" % base


def audio_meta():
    """音轨的语言元数据。**不写就全是 und（未定）**，上传 YouTube 之后
    要在网页上一条条手点，而且看不出是缺了元数据还是平台没认出来。"""
    meta = []
    for j, lang in enumerate(LANGS):
        info = LANG_INFO[lang]
        meta += ["-metadata:s:a:%d" % j, "language=%s" % info["code"],
                 "-metadata:s:a:%d" % j, "title=%s" % info["name"],
                 "-disposition:a:%d" % j,
                 "default" if lang == DEFAULT_LANG else "0"]
    return meta


def verify_tracks(path):
    """渲完立刻验**输出**里的音轨，不是复述配置。

    和 join 里那条黑场检查同一个道理：**配置对不等于输出对**。
    filter_complex 或 -map 写错一个下标，ffmpeg 不一定报错 ——
    它会安安静静地少写一条轨，而文件能播、时长对、中文轨也对。
    这一条几乎不花时间，却是唯一能在段这一级发现丢轨的地方
    （到了 join 那里，每段都少一条就成了"各段一致"，看不出来）。
    """
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                        "-show_entries", "stream_tags=language",
                        "-of", "default=nw=1:nk=1", path],
                       capture_output=True, text=True)
    got = [x.strip() or "und" for x in r.stdout.splitlines()]
    want = [LANG_INFO[l]["code"] for l in LANGS]
    if got != want:
        sys.exit("!!! %s 的音轨是 %s，应该是 %s —— 渲染时把轨弄丢或弄乱了，"
                 "不要拿它去 join" % (path, "/".join(got) or "无", "/".join(want)))
    return got


def pass_c():
    has_text = make_ass(); has = make_scrim(); total = total_len()
    mixes, norms = {}, {}
    for lang in LANGS:
        mixes[lang] = build_audio(lang)
    for lang in LANGS:
        if len(LANGS) > 1:
            print("\n--- %s 轨 ---" % LANG_INFO[lang]["name"])
        m = measure_loudness(mixes[lang])
        if norm_mode() == "loudnorm":
            # **每条轨各自量、各自归一到同一个目标。** 拿中文那条的测量值去归英文，
            # 两条轨会差出一个台阶，而观众切换音轨时那个台阶特别明显。
            norms[lang] = ("loudnorm=I=%.1f:TP=%.1f:LRA=%s:measured_I=%s:measured_TP=%s:"
                           "measured_LRA=%s:measured_thresh=%s:offset=%s:linear=true,"
                           "aresample=48000"
                           % (TARGET_I, TARGET_TP, m["input_lra"], m["input_i"],
                              m["input_tp"], m["input_lra"], m["input_thresh"],
                              m["target_offset"]))
        else:
            # 既没有音乐也没有旁白，只剩稀疏音效 —— 归一会把 SFX 表里的目标响度
            # 全部作废（理由见 norm_mode()）。只过一道重采样。
            print("   **不归一**（只有音效，SFX 表里的目标响度就是成片响度）")
            norms[lang] = "aresample=48000"
    for lang in LANGS:
        make_srt(lang)
    ins = ["-i", "master.mp4"] + (["-loop", "1", "-i", "scrim.png"] if has else [])
    base = 2 if has else 1
    for lang in LANGS:
        ins += ["-i", mixes[lang]]
    amaps = []
    for lang in LANGS:
        amaps += ["-map", "[a_%s]" % lang]
    ameta = audio_meta()
    enc = ["-c:v", "libx264", "-crf", "18", "-preset", "slow", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart",
           "-r", str(FPS), "-t", "%.3f" % total]

    # ---- 两个输出，别搞混 ----------------------------------------------------
    # 段用：**不归一**。逐段归一 = 每段一个增益 = 接缝处一个响度台阶，而且不报警
    #       （loudnorm 的整合响度带门限，各段静默比例不同就会算出不同的增益）。
    #       归一由 join 在拼完之后做一次。淡场按 SEG_FIRST/SEG_LAST 决定，已在 pass_b 里做完。
    # 预览：归一 + 尾部淡出，只为单看这一段。**不要拿它去拼片。**
    seg = os.path.join("..", OUT_NAME)
    fc = [video_chain("[0:v]", has, text=has_text)]
    fc += ["[%d:a]aresample=48000[a_%s]" % (base + j, l) for j, l in enumerate(LANGS)]
    run(["ffmpeg", "-y", "-v", "error", "-stats"] + ins
        + ["-filter_complex", ";".join(fc), "-map", "[v]"] + amaps + enc + ameta + [seg],
        "段用（**不归一**，%d 条音轨，给 join 拼片）-> %s" % (len(LANGS), seg))

    prev = os.path.join("..", PREVIEW_NAME)
    vf = video_chain("[0:v]", has, text=has_text)
    if PREVIEW_FADE_OUT > 0 and not SEG_LAST:
        vf = vf.replace("[v]", "[vp]") + \
            ";[vp]fade=t=out:st=%.3f:d=%.2f:c=%s[v]" \
            % (total - PREVIEW_FADE_OUT, PREVIEW_FADE_OUT, FADE_COLOR)
    fcp = [vf]
    fcp += ["[%d:a]%s[a_%s]" % (base + j, norms[l], l) for j, l in enumerate(LANGS)]
    run(["ffmpeg", "-y", "-v", "error", "-stats"] + ins
        + ["-filter_complex", ";".join(fcp), "-map", "[v]"] + amaps + enc + ameta + [prev],
        "预览（归一到 %.1f LUFS + 尾部淡出，给人看）-> %s" % (TARGET_I, prev))

    verify_tracks(seg)
    verify_tracks(prev)

    # ---- 多音轨要拆成可上传的形态 ----
    # **单段片子不走 join.py，于是原来永远拿不到这一步。** 多段的由 join 拆
    # （见 join.py 的 split_tracks），单段的走完 c 就交付了 —— 交出去的是一个
    # "能播、时长对、中文轨也对，只有英文轨没了" 的上传件，而文件本身完全正常。
    # 又一个不报错的失败，2026-09-04《剩下的二九六公尺》踩到。
    up = multi = None
    auds = []
    if len(LANGS) > 1:
        base = PREVIEW_NAME.replace("_预览.mp4", "")
        multi = os.path.join("..", "%s_多音轨.mp4" % base)
        shutil.copyfile(prev, multi)
        up = os.path.join("..", "%s.mp4" % base)
        run(["ffmpeg", "-y", "-v", "error", "-i", multi,
             "-map", "0:v:0", "-map", "0:a:0", "-c", "copy",
             "-movflags", "+faststart", up],
            "上传件：视频 + %s 一条轨（流拷贝）" % LANG_INFO[LANGS[0]]["code"])
        for jj, lg in enumerate(LANGS[1:], start=1):
            code = LANG_INFO[lg]["code"]
            a = os.path.join("..", "%s_音轨_%s.m4a" % (base, code))
            run(["ffmpeg", "-y", "-v", "error", "-i", multi,
                 "-map", "0:a:%d" % jj, "-c:a", "copy", a],
                "独立音频（%s）" % code)
            auds.append((code, a))
        # **拆完要验两件，两种失败都不报错。**
        na = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                             "-show_entries", "stream=index", "-of", "csv=p=0", up],
                            capture_output=True, text=True).stdout.split()
        if len(na) != 1:
            print("  !! 上传件里有 %d 条音轨，应该只有 1 条" % len(na))
        def _dur(f):
            return float(subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", f], capture_output=True, text=True).stdout)
        vd = _dur(up)
        for code, a in auds:
            if abs(_dur(a) - vd) > 0.05:
                print("  !! %s 音频和画面差 %.3fs —— 独立音频差一点点就是整条错位"
                      % (code, abs(_dur(a) - vd)))

    print("\n完成三件：")
    print("  段用   %s   **不归一**，给 join" % seg)
    print("  预览   %s   归一 + 淡出，单看这一段用这个" % prev)
    print("  字幕   %s   外挂，播放器渲染"
          % " / ".join(os.path.join("..", srt_name(l)) for l in LANGS))
    if len(LANGS) > 1:
        print("  上传件 %s   **只有 %s 一条轨，传这个**"
              % (up, LANG_INFO[LANGS[0]]["code"]))
        for code, a in auds:
            print("  附加音频 %s   在 Studio 里作为独立音频添加" % a)
        print("  留档   %s   两条轨都在，**不要拿它当上传件**" % multi)


def still():
    """抽静帧用眼睛看。

    **和竖版模板抽的东西不一样。** 那边一条字幕抽一张，因为要验字幕压在什么底上；
    这一支字幕外挂，没有那个问题了，要验的变成**画种在运镜下立不立得住** ——
    所以改成**每镜抽首/中/尾三帧**：一张看构图，三张连起来看镜头走了多远、
    落幅停在哪儿。这两件都是量不出来、只能看的。

    仍然先烧一版低码率预览再抽帧，不直接对 master 用 "-ss T -i"：
    标题字卡是烧进画面的，而 -ss 放在 -i 前会把 PTS 重置为 0，
    subtitles 滤镜按 PTS 找事件，字卡那几帧会一个字都渲不出来 —— 画面却是正常的，
    很容易误判成字卡样式有问题。
    """
    if not os.path.exists("master.mp4"):
        sys.exit("!!! 还没有 master.mp4，先跑 a + b")
    has_text = make_ass(); has = make_scrim(); os.makedirs("stills", exist_ok=True)
    ins = ["-i", "master.mp4"] + (["-loop", "1", "-i", "scrim.png"] if has else [])
    run(["ffmpeg", "-y", "-v", "error", "-stats"] + ins
        + ["-filter_complex", video_chain("[0:v]", has, grain=False, text=has_text),
           "-map", "[v]", "-c:v", "libx264", "-crf", "30", "-preset", "ultrafast",
           "-pix_fmt", "yuv420p", "-t", "%.3f" % total_len(), "preview.mp4"],
        "烧预览（含标题字卡）")
    durs, cst = timeline()[1], clip_starts()
    k = 0
    for n in range(1, len(SHOTS) + 1):
        # 用 probe_times 而不是 6%/50%/94% —— 后者会把起/尾帧取在转场里，
        # 于是一半静帧是**两镜的混合**（镜 2 的尾帧上能看见下一镜的船）。
        # 混合帧看不出这一镜自己走了多远，而"起→尾连起来看行程"正是这一趟的主要用途。
        for tag, tl in zip(("起", "中", "尾"), probe_times(n, durs)):
            t = cst[n - 1] + tl
            run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % t, "-i", "preview.mp4",
                 "-frames:v", "1", "stills/%02d%s_%.0fs.png" % (n, tag, t)],
                "静帧 镜%-3d %s  %.1fs  %s" % (n, tag, t, clip_key(CLIPS[n - 1])[:14]))
            k += 1
    print("\n%d 张静帧在 stills/（每镜 起/中/尾）" % k)
    print("要看三件事，都是量不出来的：")
    print("  1. 构图和内容对不对 —— 别信文件名，看画面")
    print("  2. 起→尾连起来，镜头是不是真的走了那么远")
    print("  3. 落幅那一帧停在哪儿 —— 停在人脸、发丝、窗框上都不行")


def measure():
    """**运镜对账** —— 拿 trace 的取样框预测和成片上实测的同一批框逐条对。

    ==== 为什么这个命令还在 ====

    竖版模板里 measure 量的是"每条字幕压着的底"，而它真正的价值不在字幕：
    它和 trace 一个在源图上算、一个在成片上量，**两者对得上是全流水线唯一一处
    能自检运镜的地方**。对不上说明镜头没走在你以为的位置上 —— 那比字幕糊了严重得多，
    而且没有别的办法能发现它（`motion` 只能证明画面变了，证明不了它变到了哪儿）。

    这一支字幕外挂，字幕框没有了。**但那个自检不能跟着丢**，所以把量的对象换成
    PROBE_BOXES 那三块固定取样框，其余机制一字不动。

    ==== 对不上的时候，先怀疑建模不一致，再怀疑运镜 ====

    历史上这个坑有三只脚，都是"pass_a / pass_c 加了一道影响亮度的滤镜，
    而 trace 那边没跟着补"：
      - vignette 加在 pass_a，trace 不补 → measure 一律低 5~31 级，越亮差得越多
      - scrim 加在 pass_c，trace 不补 → trace 一律偏亮
      - scrim 加在 pass_c，measure 抽帧后不叠回 → measure 一律偏亮（差 26 级）
    所以每加一道滤镜，**trace 和 measure 两边都得跟着补**。
    这一支 SCRIM_ALPHA=0，第二三只脚不存在；vignette 由 vig_factor() 建模。
    """
    if not os.path.exists("master.mp4"):
        sys.exit("!!! 还没有 master.mp4，先跑 a + b")
    if not os.path.exists("trace_pred.json"):
        sys.exit("!!! 没有 trace_pred.json —— 先跑 trace，它会把预测值存下来")
    raw_pred = json.load(open("trace_pred.json", encoding="utf-8"))
    pred = {}
    for k, v in raw_pred.items():
        a, b = k.split("|")
        pred[(int(a), b)] = v
    has_scrim = make_scrim()
    durs = timeline()[1]
    cst = clip_starts()

    print("\n=== 运镜对账（trace 预测 vs 成片实测，三框 × 起/中/止）===")
    print("    判据：逐条差 <= %.0f 级。差得多而且**越亮差得越多**，" % PROBE_TOL)
    print("    先查 pass_a/pass_c 有没有 trace 没建模的滤镜，再怀疑运镜。")
    worst, nbad, bias = 0.0, 0, {}
    for n in range(1, len(SHOTS) + 1):
        if (n, PROBE_BOXES[0][0]) not in pred:
            print("  镜%-3d (trace 当时缺图，跳过)" % n); continue
        cells = []
        # 取样时刻和 trace 共用 probe_times() —— 各写一份必漂，而且会漂在转场上
        for pi, tl in enumerate(probe_times(n, durs)):
            t = cst[n - 1] + tl
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % t,
                            "-i", "master.mp4", "-frames:v", "1", "_m.png"],
                           capture_output=True)
            args = ["ffmpeg", "-v", "error", "-i", "_m.png"]
            if has_scrim:
                args += ["-i", "scrim.png", "-filter_complex",
                         "[0:v][1:v]overlay=0:0:shortest=1,format=gray"]
            else:
                args += ["-vf", "format=gray"]
            b = subprocess.run(args + ["-f", "rawvideo", "-"], capture_output=True).stdout
            if len(b) < W * H:
                cells.append("  (读不出帧)"); continue
            for name, rx0, rx1, ry0, ry1 in PROBE_BOXES:
                x0, x1 = int(rx0 * W), int(rx1 * W)
                y0, y1 = int(ry0 * H), int(ry1 * H)
                v = [b[y * W + x] for y in range(y0, y1, 4) for x in range(x0, x1, 4)]
                got = sum(v) / len(v)
                exp = pred[(n, name)][pi]
                d = abs(got - exp)
                worst = max(worst, d)
                bias.setdefault(name, []).append(got - exp)
                if d > PROBE_TOL:
                    nbad += 1
                cells.append("%s%s %3.0f/%3.0f(%+.0f)%s"
                             % (name, "起中止"[pi], exp, got, got - exp,
                                "!" if d > PROBE_TOL else ""))
        print("  镜%-3d %s" % (n, "  ".join(cells)))
    if os.path.exists("_m.png"):
        os.remove("_m.png")
    if bias:
        print("")
        print("  每框平均偏差（成片 − 预测）：" + "   ".join(
            "%s %+.1f" % (k, sum(v) / len(v)) for k, v in bias.items()))
        print("  全框同向的小偏差 = 建模精度（多半是暗角），**某一镜跳变才是运镜出错**。")
    print("\n  最大偏差 %.1f 级，超出 %.0f 级的有 %d 处 —— %s"
          % (worst, PROBE_TOL, nbad,
             "运镜走在预期位置上" if nbad == 0 else "**对不上，先查滤镜建模再查运镜**"))
    print("  这只是数字，还要跑 still 用眼睛看：数值对但落幅停在人脸上是量不出来的。")


def check_cover_text(shot_png, bare_png):
    """量封面文字**笔画底下**的底够不够暗/够不够亮。

    ==== 为什么要有这一条 ====
    封面是全片唯一一处"文字压在没有为它留白的画面上"的地方：正文字幕有 measure 兜着，
    封面没有。而它恰恰是观众第一眼看到的东西。

    ==== 量法：文字掩膜，不是框一个矩形 ====
    拿**有字**和**无字**两张图逐像素比，差得多的就是文字覆盖的像素，再回到无字那张
    量这些位置的底。框矩形去量会被大片浅色稀释 —— 实测同一处矩形量出 94、掩膜量出 84，
    而真正决定看不看得清的是笔画底下那些像素。（《给蛾子盖的礼堂》英文封面上踩的）

    判据和正文字幕同一条：**离字色至少 50 级**，用 1%/99% 分位不用绝对极值。
    """
    def gray(p):
        return subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-vf", "format=gray",
                               "-frames:v", "1", "-f", "rawvideo", "-"],
                              capture_output=True).stdout
    a, b = gray(bare_png), gray(shot_png)
    if len(a) < W * H or len(b) < W * H:
        print("   (读不出帧，跳过封面对比度检查)"); return True
    dark_ink = TITLE_POLARITY == "dark_on_light"
    ink = 40 if dark_ink else 242
    under = sorted(a[i] for i in range(W * H) if abs(a[i] - b[i]) > 30)
    if len(under) < 200:
        print("   (几乎没量到文字像素，跳过)"); return True
    v = under[max(0, int(len(under) * 0.01))] if dark_ink \
        else under[min(len(under) - 1, int(len(under) * 0.99))]
    gap = abs(v - ink)
    print("   文字覆盖 %d 像素，底的%s分位 %d，离字色 %d 级 —— %s"
          % (len(under), "1%" if dark_ink else "99%", v, gap,
             "够用" if gap >= 50 else "**不够，换位置或收字号**"))
    if gap < 50:
        print("   注意：**先扫一遍再挪**。不够常常不是高度不对而是宽度太宽 ——")
        print("   一行字横出去两端压在暗处，中间那段其实是干净的。收字号比挪位置对。")
    return gap >= 50


def cover(lang=None):
    """封面。`cover en` 出英文那张（文件名后缀 _en）。

    双语片**每种语言各一张**，见 COVER_TEXT 上面那段。
    """
    lang = lang or DEFAULT_LANG
    if lang not in COVER_TEXT:
        sys.exit("!!! COVER_TEXT 里没有 %r —— 双语片每种语言都要写一份封面文案" % lang)
    t = COVER_TEXT[lang]
    ev = []
    for txt, fs, y in t["lines"]:
        ev.append("Dialogue: 0,0:00:00.00,0:00:10.00,T,,0,0,0,,"
                  "{\\pos(%d,%d)\\fs%d}%s" % (W // 2, y, fs, txt))
    stxt, sfs, sy = t["sub"]
    ev.append("Dialogue: 0,0:00:00.00,0:00:10.00,TS,,0,0,0,,"
              "{\\pos(%d,%d)\\fs%d}%s" % (W // 2, sy, sfs, stxt))
    with open("cover.ass", "w", encoding="utf-8-sig") as f:
        f.write("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\n"
                "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n" % (W, H)
                + styles_block() + "\n[Events]\nFormat: Layer,Start,End,Style,Name,"
                "MarginL,MarginR,MarginV,Effect,Text\n" + "\n".join(ev) + "\n")
    src = "img%02d.png" % COVER_FROM
    if not os.path.exists(src):
        sys.exit("!!! 缺 " + src + "，先跑 prep")
    out = os.path.join("..", COVER_NAME if lang == DEFAULT_LANG
                       else COVER_NAME.replace(".png", "_%s.png" % lang))
    base = "scale=%d:%d:flags=lanczos%s" % (W, H, "," + VIGNETTE if VIGNETTE else "")
    run(["ffmpeg", "-y", "-v", "error", "-i", src,
         "-vf", base + ",subtitles=cover.ass:fontsdir=%s" % FONTS.replace("\\", "/"),
         "-frames:v", "1", out], "封面(%s) -> %s" % (LANG_INFO[lang]["name"], out))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", base,
                    "-frames:v", "1", "_cover_bare.png"], capture_output=True)
    check_cover_text(out, "_cover_bare.png")
    if os.path.exists("_cover_bare.png"):
        os.remove("_cover_bare.png")
    print("   数值够了还要打开看一眼：标题很容易压在人脸或主体上，那是量不出来的。")
    if len(LANGS) > 1 and lang == DEFAULT_LANG:
        print("   **双语片记得再跑一次** `cover %s`。"
              % [l for l in LANGS if l != DEFAULT_LANG][0])
        print("   注意 YouTube 的多语言**不覆盖缩略图**（只有标题/简介/音轨/字幕），")
        print("   一个视频只有一张封面 —— 另一张是给别处用的（分享图、社媒）。")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    # `preview` 和 `budget` 都必须在**没有图**的时候跑得起来 —— 那正是它们的位置。
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    if what in ("sync", "prep", "probe", "trace", "still", "measure", "cover",
                "pick", "motion", "pixels", "mquality", "credits", "budget",
                "srt", "preview", "gates", "langfit"):
        if what == "langfit":
            # 逐句把别的语言压进中文的槽。压不进去的会报出还得砍几个词。
            sys.exit(0 if langfit(arg or "en") else 1)
        if what == "cover":
            cover(arg)                         # `cover en` 出英文封面（双语片两张都要）
        elif what == "preview":
            preview(arg)                       # `preview en` 单听英文那条
        elif what == "srt":
            for l in LANGS:
                make_srt(l)                    # 每种语言各一份
        else:
            {"sync": sync, "prep": prep, "probe": probe, "trace": trace, "still": still,
             "measure": measure, "pick": pick_music_in,
             "motion": motion, "pixels": pixels,
             "mquality": mquality, "credits": credits, "budget": budget,
             "gates": check_gates}[what]()
        sys.exit(0)
    ok = check_timeline()
    if what == "check":
        sys.exit(0 if ok else 1)
    if not ok:
        sys.exit("!!! 自检没过，先修上面的问题")
    if what in ("a", "all"):
        if what == "all":
            prep()
        pass_a()
    if what in ("b", "all"):
        pass_b()
    if what in ("c", "all"):
        pass_c()
