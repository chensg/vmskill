# vmskill

用静帧 + Ken Burns 运镜 + 烧录字幕 + 生成配乐，本地 ffmpeg 合成竖版/横版短片的 Agent Skill。

同一条流水线跑两种片子：

| | **诗词模式** | **讲述模式** |
|---|---|---|
| 做什么 | 一首古诗词，一句一镜，片尾竖排诗文页 | 一个历史小故事 / 冷知识，有旁白 |
| 时间轴由什么定 | 字数 × 0.45 + 1.8 的可读下限 | 旁白实测时长（`sync` 量完自动推） |
| 字幕 | 竖排、右侧、楷体 | 横排、左下、黑体 |
| 每镜停留 | 10~13s | 3~8s，12~16 镜 |
| 音频 | 音乐 + 音效 | 旁白 + 音乐侧链躲闪 + 音效 |
| 最大的风险 | 字看不清 | 把推断说成史实 |

## 这个 skill 到底在解决什么

不是 ffmpeg 命令——那部分网上都有。是**几件必须量出来、不能靠眼睛判断的事**：
凭感觉做出来的版本一定会在这几处翻车，而且往往要到成片才看得出来。

- **运镜行程受缩放限制**。`zoompan` 的取景窗被 clip 在画面内，想走 `d` 比例的行程
  必须 `z ≥ 1/(1-d)`。写了位移却不给足缩放，成片就是原地微缩放——
  看起来镜头没动，而且这个错误在参数表上完全看不出来
- **三级实测，量的是三个不同区域**：`probe` 量整张图（报警常是误报）、
  `trace` 量镜头真正经过的那一段、`measure` 量渲出来的无字成片。
  跳过中间那级，会去换掉本来完全没问题的图
- **`trace` 和 `measure` 必须建模同一条流水线**。`pass_a`/`pass_c` 每加一道
  影响亮度的滤镜（vignette、scrim），两边都得跟着补——否则那条判据
  长期挂着系统性偏差，而它是全流水线唯一一处能自检运镜的地方
- **调色的判据是量出来的直方图，不是画种**。生成器交回来的暗调图常常是
  技术性欠曝的，照抄"几乎不调"是负的
- **配乐要的是时长**。生成的曲子几乎一定自带弱前奏，提示词管不住（试过三轮）；
  真正解决问题的是留出足够的切入余地，然后用 maximin 选点
- **竖版字幕会撞平台操作栏**。右侧 x 929~1080 / y 864~1632 是禁区（真机验过）
- **讲历史最大的风险不是字看不清，是把推断说成史实**。所以讲述模式多一张
  `CLAIMS` 事实分级表（史实 / 概数 / 假说），假说必须在片内自我拆解

每一条数字都是踩出来的，不是理论。文档里标了是在哪一支上踩的。

## 一条贯穿始终的纪律

**永远不要根据文件名、alt 文本或接口返回的元数据判断一张图是什么。**
靠缩略图编号选图，九张里错过三张；两张样图的文件名互相反了，也是打开看才发现的。

同理，**写检查的时候要问一句：这一条在最坏情况下会不会静默放行。**
一个永远不报警的检查比没有检查更糟。所以几处关键检查都带回归自测。

## 用法

装到 agent 的 skills 目录：

```bash
git clone https://github.com/chensg/vmskill.git
cp -r vmskill/classical-poem-video ~/.codex/skills/
```

Claude Code 换成 `~/.claude/skills/`。

跑一支（讲述模式）：

```bash
python make_story_v.py sync     # 量旁白 -> 推整条时间轴
python make_story_v.py check    # 永远先跑它
python make_story_v.py prep     # 裁切 + 调色，自动 probe
python make_story_v.py trace    # 量镜头真正经过的区域，开渲前最后一道
python make_story_v.py a        # Ken Burns
python make_story_v.py motion   # 量渲出来的首尾帧差，验运镜看不看得出来
python make_story_v.py b        # 转场 -> master.mp4（无字无声）
python make_story_v.py pick     # maximin 选音乐切入点
python make_story_v.py c        # 旁白 + 音乐 + 烧字幕 -> 成片
python make_story_v.py still    # 抽静帧用眼睛看
python make_story_v.py measure  # 量字幕底，和 trace 逐条对
python make_story_v.py cover    # 封面
```

诗词模式把 `make_story_v.py` 换成 `make_v.py`（竖版）或 `make_h.py`（横版），
去掉 `sync`。

依赖：Python 3、ffmpeg / ffprobe（要带 `libass`、`zoompan`、`xfade`、
`sidechaincompress`）。字幕用系统字体：诗词模式 KaiTi，讲述模式 Microsoft YaHei。

## 已经跑通并交付过的

诗词模式：水调歌头 / 望月怀远 / 十五夜望月 / 登高（水墨 + 现代两版）/ 观沧海 /
清平调三首 / 声声慢 / 再别康桥 / 雨霖铃。
讲述模式：没有夏天的那一年（1816 无夏之年 → 自行车，13 镜 / 25 条旁白 / 113.97s）。

`make_v.py` 内含《雨霖铃》那一支的完整真实配置，`make_story_v.py` 内含
《没有夏天的那一年》的——都是跑通交付过的，copy 过去改内容块就能用。

## 文件

- `SKILL.md` — 主文档。所有判据和它们的来历
- `references/storytelling.md` — 讲述模式独有的：事实分级、旁白气口与语速、
  横排字幕避操作栏、转场当叙事标点、侧链躲闪
- `references/sourcing.md` — 找图与生成图：五个画种的共用风格前缀、
  暗调写实的"留暗"要求怎么写、验证纪律
- `references/checklist.md` — 开工到交付的逐项检查表，含所有硬性数值
- `scripts/make_v.py` / `make_h.py` / `make_story_v.py` — 构建脚本
- `agents/openai.yaml` — Codex 的技能界面配置
