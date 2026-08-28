# vmskill

用静帧 + 可选 Ken Burns 运镜 + 字幕 + 可选配乐音效，本地 ffmpeg 合成竖版 1080×1920 /
横版 1920×1080 短片的 Agent Skill。

一条流水线跑四种片子：

| | 做什么 | 时间轴由什么定 | 字幕 | 脚本 |
|---|---|---|---|---|
| **诗词模式** | 一首古诗词，一句一镜，片尾竖排诗文页 | 字数 × 0.45 + 1.8 的可读下限 | 竖排、右侧、楷体 | `make_v.py` / `make_h.py` |
| **讲述模式** | 历史小故事 / 冷知识 / 科普 / **荐书** | 旁白实测时长（`sync` 量完自动推） | 横排、左下、黑体 | `make_story_v.py`（竖）/ `make_story_h.py`（横，分段） |
| **MV 模式** | 一条带演唱的成品歌 + 一份歌词 | **锁死等于歌长**，换镜只能落在句间空档 | 跟着唱腔走 | `lyric_sync.py` → `make_v.py` |
| **小说第一人称** | 公版小说连载，书里一个角色自述 | 一集 600s ± 60，一集一个完整故事 | 外挂 SRT | `make_story_h.py` + `join.py` |

**三条轴开工前必须定死**，四种模式都适用：

- `MOTION` — 运镜，还是**一镜一张静态图**（可逐镜覆盖）
- `MUSIC_MODE` — `library` 查库 / `generate` 生成 / `public_domain` 公版 / `none` 不要 / `song` 用成品歌
- `IMG_SOURCE` — 按任务书生成，还是**自己去找公版或图库**（找来的必须登记来源与授权）

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
- **TTS 每条 mp3 头尾自带静音**。不剪的话每句被"文件自带静音 + `GAP_*`"两层包着，
  片长凭空涨一成多（《潘多拉的瓮》44 条 180.9s → 164.4s）。所以 `sync` 之前必跑 `vo_trim.py`
- **竖版字幕会撞平台操作栏**。右侧 x 929~1080 / y 864~1632 是禁区（真机验过）
- **讲历史最大的风险不是字看不清，是把推断说成史实**。所以讲述模式多一张
  `CLAIMS` 事实分级表（史实 / 概数 / 假说），假说必须在片内自我拆解
- **分段长片的坑全在接缝上，且大半不报警**。所以拼接不用裸 `concat`，走 `join.py`：
  一次全局响度归一 + 按实际段起点合并 SRT + 接缝校验

每一条数字都是踩出来的，不是理论。文档里标了是在哪一支上踩的。

## 两道门禁：不是检查通过，是**人**点头

故事片 / 荐书片 / 小说片在出图之前有两道，脚本里是 `GATE_SCRIPT_OK` /
`GATE_PREVIEW_OK` 两个字符串，**留空就拦住 `budget`**（出图前那一步）：

1. **讲述稿人工确认** — 稿子交给用户读一遍。拦的是：哪句是废话、哪个转折跳了、
   第三幕是不是在替读者下结论
2. **只有字幕 + 声音的检查片**（`preview`）— 交给用户听。拦的是：旁白好不好听、
   断句与气口、字幕跟不跟得上、**片长**。第二道经常直接改数字：《经度》段五按 `est`
   排 138.0s，旁白实测回来 130.5s，差 7.5s——有平台硬线时这个差额是致命的

## 一条贯穿始终的纪律

**永远不要根据文件名、alt 文本或接口返回的元数据判断一张图是什么。**
靠缩略图编号选图，九张里错过三张；两张样图的文件名互相反了，也是打开看才发现的。

同理，**写检查的时候要问一句：这一条在最坏情况下会不会静默放行。**
一个永远不报警的检查比没有检查更糟。所以几处关键检查都带回归自测
（`--selftest`：去掉被检查的东西，它还报不报警）。

## 用法

装到 agent 的 skills 目录：

```bash
git clone https://github.com/chensg/vmskill.git
cp -r vmskill/classical-poem-video ~/.codex/skills/
```

Claude Code 换成 `~/.claude/skills/`。**改动请回到克隆里改、提交，再同步过去**，
不要在安装目录里直接改。

跑一支（讲述模式）：

```bash
python vo_trim.py apply         # 先剪掉 TTS 每条头尾的边缘静音
python make_story_v.py sync     # 量旁白 -> 推整条时间轴
python make_story_v.py check    # 永远先跑它
python make_story_v.py preview  # 门禁二：只有字幕+声音的检查片，交给用户听
python make_story_v.py budget   # 两道门禁签字后才跑：按运镜反推图要多大
python make_story_v.py prep     # 裁切 + 调色，自动 probe
python make_story_v.py trace    # 量镜头真正经过的区域，开渲前最后一道
python make_story_v.py a        # Ken Burns
python make_story_v.py motion   # 量渲出来的首尾帧差，验运镜看不看得出来
python make_story_v.py b        # 转场 -> master.mp4（无字无声）
python make_story_v.py pick     # maximin 选音乐切入点
python make_story_v.py c        # 旁白 + 音乐 + 烧字幕 -> 成片
python make_story_v.py measure  # 量字幕底，和 trace 逐条对
python make_story_v.py cover    # 封面
python publish.py new 片名      # 交付物之一：发布文案
```

诗词模式把 `make_story_v.py` 换成 `make_v.py`（竖版）或 `make_h.py`（横版），
去掉 `sync` / `vo_trim` / 两道门禁。分段长片和小说连载走 `make_story_h.py`
一幕一个段目录，最后 `python join.py 段一 段二 ...` 拼全片。

依赖：Python 3、ffmpeg / ffprobe（要带 `libass`、`zoompan`、`xfade`、
`sidechaincompress`）。字幕用系统字体：诗词模式 KaiTi，讲述模式 Microsoft YaHei。

## 已经跑通并交付的

- **诗词模式**：水调歌头 / 望月怀远 / 十五夜望月 / 登高（水墨 + 现代两版）/ 观沧海 /
  清平调三首 / 声声慢 / 再别康桥 / 雨霖铃（电影写实版）
- **讲述模式**：没有夏天的那一年（1816 无夏之年 → 自行车，13 镜 / 25 条旁白 /
  113.97s / −15.1 LUFS）；经度（横版分段长片，706s）；廷巴克图
- **荐书子型**：吞下宇宙的男孩（第一支，21 镜 / 180.1s）；潘多拉的瓮（44 条 / 164.4s）
- **MV 模式**：天净沙·秋思
- **小说第一人称**：白衣女人（连载，已出三集）

`make_v.py` 内含《雨霖铃》那一支的完整真实配置，`make_story_v.py` 内含
《没有夏天的那一年》的，`make_story_h.py` 内含《经度》段一的——都是跑通交付过的，
copy 过去改内容块就能用。

## 文件

**主文档**

- `SKILL.md` — 所有判据和它们的来历

**参考（按需读，不用全读）**

- `references/storytelling.md` — 讲述模式独有的：出图前两道门禁（〇）、事实分级（一）、
  旁白气口与语速（二）、横排字幕避操作栏（三）、镜数与节奏（四）、侧链躲闪（五）、
  **荐书子型**（七）、**旁白 TTS 完整配置与去 AI 味**（八）、**小说第一人称模式**（九）
- `references/sourcing.md` — 找图与生成图：五个画种的共用风格前缀、暗调写实的"留暗"
  怎么写、`IMG_SOURCE='found'` 那一路怎么走、验证纪律
- `references/music.md` — 配乐四种来源：查库 / 生成 / 公版 / 不要。录音权与作品权的区别、
  公版录音怎么量、没有音乐时归一化为什么要换策略
- `references/publishing.md` — 发布文案：标题在各平台被切在第几个字；标题不能剧透第三幕
- `references/checklist.md` — 开工到交付的逐项检查表，含所有硬性数值
- `references/codex.md` — 在 Codex 里怎么跑：环境前提、命令序列、PowerShell 与 bash 的分工、
  长渲染的后台纪律、报错对照表。**第一次在 Codex 上开工先读它**

**构建脚本**

- `scripts/make_v.py` / `make_h.py` — 诗词模式 竖版 / 横版。横版**还是旧模板**，缺几样检查
- `scripts/make_story_v.py` — 讲述模式 竖版，多 `sync`（量旁白）、`vofit`（压进平台硬线）、
  `motion`（验运镜）
- `scripts/make_story_h.py` — 讲述模式 横版**分段**，字幕外挂不烧录。长片与小说连载走它
- `scripts/join.py` — 拼全片：concat + **一次**全局响度归一 + 合并 SRT + 接缝校验

**工具**

- `scripts/vo_trim.py` — 剪 TTS 每条 mp3 的边缘静音（`measure` 干量 / `apply` 真剪）
- `scripts/vo_split.py` — 把一整条真人朗读切成一句一个文件，供诗词模式的 `VO` 链路
- `scripts/lyric_sync.py` — MV 对轴：`probe` → `spans` / `snap` / `lrc` → `check` → `proof`
- `scripts/publish.py` — 发布文案骨架 + 量各平台标题截断位置
- `scripts/music_index.py` / `sfx_index.py` — 素材库登记与检索（库本身不在仓库里）
- `scripts/sort_downloads.py` — 把浏览器下载的一堆文件归到脚本要找的位置
- `agents/openai.yaml` — Codex 的技能界面配置
