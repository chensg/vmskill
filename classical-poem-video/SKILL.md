---
name: classical-poem-video
description: 把一个真实故事、一首古诗词或一首成品歌做成短片：静帧或 AI 影片镜头 + TTS 旁白 + 字幕 + 配乐，本地 ffmpeg 合成竖版 1080x1920（Short）或横版 1920x1080（长片，可分章分段）。三种模式：讲述片（历史/真人故事，旁白驱动时间轴，带事实分级和两道人工门禁；子型有荐书片、小说第一人称连载）、诗词片（一句一镜）、MV（字幕跟唱腔）。Use when asked to make, continue, re-cut or fix such a video or any step of it：讲述稿 / 分镜 / 出图任务书 / 找公版素材与授权署名 / 旁白 TTS 与气口语速 / 字幕与平台安全区 / 运镜或静帧 / 配乐音效 / 封面 / 中英双语音轨与 SRT / 发布文案 / 交付检查；也包括排错：字幕看不清、运镜不动、片长对不上、歌词字幕和唱腔不同步、英文轨上传后丢失。
---

# 静帧短片流水线

把一个真实故事、一首古诗词或一首成品歌，做成带字幕、旁白、配乐的短片。
成片由本地 ffmpeg 合成，横竖两种版式。

这条流水线的核心不是 ffmpeg 命令，而是**几件必须量出来、不能靠眼睛判断的事**，
加上**两道必须由人点头的门禁**。凭感觉做出来的版本会在这几处翻车，而且往往到成片才看得出来。

**这份只放总纲和路由。** 细则、数字、每条规矩是在哪一支上踩出来的，都在 `references/`。
**用到哪份读哪份，别一开工全读**（文末有表）。

## 先选模式

| | **诗词模式** `make_v.py`（只做竖版） | **讲述模式** `make_story_v.py` / `make_story_h.py` |
|---|---|---|
| 做什么 | 一首诗，一句一镜，片尾竖排诗文页 | 一个真实故事 / 冷知识，有旁白 |
| 时间轴由什么定 | 字数 × 0.45 + 1.8 的可读下限 | **旁白实测时长**（`sync` 量完自动推） |
| 字幕 | 竖排、右侧、楷体 | 横排、左下、黑体；`SUB_MODE` 定烧录还是外挂 SRT |
| 每镜停留 | 10~13s | 3~8s |
| 音频 | 音乐 + 音效 | 旁白 + 音乐**侧链躲闪** + 音效 |
| 最大的风险 | 字看不清 | **把推断说成史实** |

- 讲述模式的两个子型：**荐书片**（`references/book.md`）、**小说第一人称连载**
  （`references/novel.md`；第一支没跑完，标「待实测」的都别当数）。
- **MV**（用户给一条带演唱的成品歌）：`make_v.py` + `MUSIC_MODE="song"`，见 `references/mv.md`。
- 横版长片分段做，`join.py` 拼全片。

**现行两个片型**，开片用 `python episode.py new <项目目录> --type short|long`：

- **Short 新做法七条** → `references/format-short-v2.md`（带 `segment_config` 预设，模板不用改）
- **横版长片分章节＋章节卡** → `references/format-long-chapters.md`

**接手一支做到一半的片子，先跑 `python episode.py status <项目目录>`**，二十行以内告诉你稿子、门禁、旁白、素材、交付物各到哪一步，别先去读一堆文档。

## 两道门禁（讲述片，出图之前）

两个都要**人**点头，不是检查通过：

| | 门禁 | 怎么过 | 它拦住的是 |
|---|---|---|---|
| 一 | **讲述稿人工确认** | 把稿子交给用户读一遍 | 哪句是废话、哪个转折跳了、结尾是不是在替观众下结论 |
| 二 | **只有字幕+声音的检查片** | `python make_story_*.py preview` 出片，交给用户听 | 旁白好不好听、断句与气口、字幕跟不跟得上、**片长** |

脚本里是 `GATE_SCRIPT_OK` / `GATE_PREVIEW_OK` 两个字符串，**留空就拦住 `budget`**（出图前那一步）。
写人话，不写 `True`。第二道经常直接改数字：《经度》段五估 138.0s，旁白实测 130.5s。
有平台硬线时这个差额是致命的，而它只在这个窗口里看得见。见 `references/storytelling.md` 第〇节。

## 三条轴：开工前定死

它们各有默认值，**但每一条都会往回改前面的决定**（片长、素材门槛、分镜方式），做到一半再改要重来。

| 轴 | 值 | 默认 | 改了会连带什么 |
|---|---|---|---|
| `MOTION` | `kenburns` / `static`，**可逐镜覆盖** | `kenburns` | 素材分辨率门槛、每镜停留、粒子层的价值 |
| `MUSIC_MODE` | `library` / `generated` / `public_domain` / `none` / **`song`** | `generated` | 片长怎么排、`pick` 挑什么、归一化策略、要不要附授权 |
| `IMG_SOURCE` | `generated` / `found` | `generated` | **分镜跟着图走还是图跟着分镜走**、要不要登记来源 |

**这三条不要替用户默认**，问一句就够，不用摆候选。三条都有自检，`check` 会跑。

- 运动 → `references/visuals.md`「静帧模式」
- 配乐 → `references/music.md`（先要长度再倒推片长、maximin 切入点）；
  公版 `references/music-public-domain.md`，不要配乐 `references/music-none.md`
- 素材来源 → `found` 读 `references/found-images.md`。它不是省事的那条：省掉等出图，换来检索和核对，
  而且**每张都要登记来源与授权**（`check` 会拦，`credits` 导出）

## 旁白 TTS

**中文 ChatCut 豆包、英文 Fish**（2026-10-19 用户定）。一句一条，逐句 `performancePrompt`，
下载完先 `vo_trim.py` 剪静音再 `sync`。**照 `references/tts.md` 开头的速查做**，出了问题再往下翻。
`el_tts.py`（ElevenLabs v4）不是默认，只在用户点名时用；它的 `asr` 能核对任何一批中文旁白的读音。

## 渲染分四趟，改什么跑哪趟

| 趟 | 做什么 | 什么时候要重跑 |
|---|---|---|
| `prep` | 裁切 + 统一调色 → img01..N，并自动 `probe` | 换图、改调色、改裁切位 |
| `a` | 每张图做 Ken Burns（+ vignette）**或按 `MOTION` 出静帧** → shots/ | 改运镜、改 `MOTION` 或改了 prep |
| `b` | xfade 溶解转场串成无字无声的 master.mp4 | 改镜头时长、转场或改了 a |
| `c` | 粒子 + 混音 + 归一 + 烧字幕 → 成片 | 改字幕、scrim、音乐、音效、粒子颜色 |

- **`check` 永远先跑。** 讲述模式多一趟 `sync`（量旁白时长、推时间轴），排在 `check` 前面。
- **改了字幕只跑 `c`**；改粒子只跑 `fx` + `c`。a/b 两趟不含文字和声音，重渲是纯浪费。
- 讲述模式的 `a` **只补过期的镜**（默认并行），改完直接跑 `a`，它自己知道补哪几镜；
  中间件对不上账时 `a` / `b` 会拒绝开工。不带参数只打印用法，`all` 要明说。
- 出图前 `budget`（按运动反推每镜要多大的图）；出图后三道缺一不可：
  `check`（**先填 `SRC_NATIVE`**）→ `trace` → `pixels`。
- **长任务（渲染、等下载、重渲全片）一律用 `runlog.py run` 跑**，停用 `runlog.py stop`。
- 脚本住在 `<项目>/build/`，交付物写到 `..`。放错位置会写进片库根，脚本会拦。

全部命令和对账规则见 `references/pipeline.md`。

## 必须量、不能看的事

1. **运镜行程受缩放限制**：走过 `d` 比例的行程要 `z ≥ 1/(1-d)`，`check_moves()` 会拦。
2. **三级实测量的是三个区域**：`probe` 整张图（常误报）→ `trace` 镜头真正经过的那一段 → `measure` 无字 master。
3. **`trace` 和 `measure` 要建模同一条流水线**；改了 `GRADE` / `VIGNETTE` / `SUB_MODE` / 裁切，`measure` 之前重跑 `trace`。
4. **字幕在真实成片上验**：量无字的 `master.mp4`，离字色 ≥ 50 级。

**看和量都要做**：`still` 漏掉「勉强能认但很脏」，`measure` 漏掉「数值够但压在人脸上」。
细则 `references/measuring.md`。

## 竖版平台安全区（真机验过）

右侧头像/赞/评论/分享压在 **x 0.86~1.00、y 0.45~0.85**，顶部导航压在 y 0~0.09。
字幕要躲开，**往上移，不要往左移**。`check_safe()` 会验。

## 图、影片、配乐从哪儿来

先看这个会话里有什么，按这个顺序用：

1. **本机 ComfyUI（有 3090 时的默认）**：`comfy_gen.py`，同一份任务书出图、图生影片、放大，
   也能出配乐（`music`）和音效（`sfx`）。硬件红线、「图/影片/放大不同时跑」、
   H3 和 Stable Audio 的署名要求都由脚本拦，别绕。见 `references/local-gen.md`、`references/music.md`「一·五」。
2. **ChatCut**：`submit_image` / `submit_video` / `submit_music` / `submit_voice`。
   下载要用户的登录会话，走 `chatcut_dl.py` 出下载页。
3. **ElevenLabs 网页版**（有浏览器面板时）：`el_web_image.py`，见 `references/sourcing.md`。
4. 都没有：**写一份自包含的出图任务书交给用户**。这不是退路，是这条流水线的正常形态。

任务书里的尺寸一律来自 `budget`；样图先出两张把风格夹住。
档案照片（600~740px 的线上图）先 `upscale.py` 再用贴纸版式 `fit="plate"`。

## 双语音轨（细则 `references/bilingual.md`）

`LANGS = ["zh", "en"]`：一条画面 + 中英两条音轨 + 两份 SRT，横竖版都做。

- **时间轴归中文**。英文用 `langfit` 逐句压进中文的槽，压不进去的不压，报出还得砍几个词。
  英文稿是配音改写，不是翻译
- **竖版要先 `SUB_MODE = "srt"`**（烧录字幕和多语言不能共存，`check_mode()` 会拦）
- **上传件单音轨**（视频 + 中文），附加语言是独立 m4a，在 Studio 里加。
  多音轨文件直接传上去，英文轨会被静默丢掉

## 交付

- 成片：H.264 + AAC 48k 立体声，响度 **−15 LUFS**。
- 双语片：单音轨上传件 + 每种附加语言一个 `*_音轨_eng.m4a` + 两条轨都在的留档件；中英各一份外挂 SRT。
- **`发布文案.md` 是交付物**：`python publish.py new 片名` 出骨架，`python publish.py check` 量各平台标题截断。
  **标题不能剧透结尾的反转。** 见 `references/publishing.md`。
- 封面：`cover` / `cover en`，跑完自己量文字底下的对比度。横版字号用户定过，见 `references/storytelling.md`「封面」。
  封面帧要手动 remux 嵌进 mp4（`-disposition:v:1 attached_pic`，`-c copy`）。
- **用了找来的素材（图或音乐），`credits` 导出的素材来源表是交付物的一部分**，署名要跟着片子走。
- 交付前先跑 **`python episode.py deliver <项目目录>`**：封装、响度、片长、字幕、英文轨、封面、发布文案、
  章节时间码、门禁，只打印没过的。它过了，再对 `references/checklist.md` 里要人判的那些。

交付时要**主动说**：哪几处是妥协的；哪几处和原计划不同、为什么；还留了什么可以改的口子
（换某张图只需重跑哪几趟）；三条轴各取了什么值。
**「没有背景音乐」和「完全没有音轨」尤其要说**，它们看起来像做漏了。

## 一条贯穿始终的纪律：看过再说

**永远不要根据文件名、alt 文本、搜索结果的描述或接口返回的元数据判断一张图是什么。**
靠读缩略图上的编号选图，九张里错过三张，而且尺寸校验全部通过。

图多的时候先拼一张**联络表**核对序号和画面，再单独打开有风险的那几张。
渲染完成后**抽静帧真正看一眼**，ffmpeg 退出码是 0 不等于画面是对的。
目视也有盲区：粒子方向、运镜幅度、音效互相盖，这三类只能量。

## 按需读

| 什么时候 | 读哪份 |
|---|---|
| 做 Short（新做法七条、`TOP_BAR` / `TIGHT_PACING` / `MUSIC_HP`） | `references/format-short-v2.md` |
| 做横版长片（分章、章节卡、简介时间码） | `references/format-long-chapters.md` |
| 做讲述片：门禁、事实分级、时间轴与气口、字幕、转场、侧链、封面 | `references/storytelling.md` |
| 生成旁白、剪静音、排片长、核读音 | `references/tts.md`（先看速查） |
| 四趟的全部命令、中间件对账 | `references/pipeline.md` |
| 跑 `trace` / `measure` / `motion`，或两者对不上 | `references/measuring.md` |
| 静帧模式、视频镜、素材分辨率与 `budget` | `references/visuals.md` |
| 选画种、字幕极性（`FLIP_SHOTS`）、调色（`GRADE`） | `references/style.md` |
| 配乐（查库 / 生成 / 本机生成）、片长倒推、切入点、音效 | `references/music.md` |
| 公版 / 开放授权的配乐：录音权、去哪儿找、`mquality`、合成音乐床 | `references/music-public-domain.md` |
| 不要背景音乐 | `references/music-none.md` |
| 出图的共用硬要求、写出图任务书 | `references/sourcing.md` |
| 定了画种，写风格前缀和各画种的出图要求 | `references/style-prompts.md` |
| 自己找公版图 / 图库图，登记授权（`IMG_SOURCE = "found"`） | `references/found-images.md` |
| 本机 `comfy_gen.py`：出图、图生影片、放大、提示词的坑 | `references/local-gen.md` |
| 中英双语音轨 | `references/bilingual.md`，出了问题再看 `bilingual-detail.md` |
| 写发布文案 | `references/publishing.md` |
| 交付前逐项对一遍 | `references/checklist.md` |
| 荐书片 | `references/book.md` |
| 小说第一人称连载 | `references/novel.md` |
| 诗词模式 | `references/poem.md` |
| MV（带演唱的成品歌） | `references/mv.md` |
| 冷开场七句式、封面题眼变色（外部参考） | `references/external-modules.md` |
| 在 Codex 里跑 | `references/codex.md` |
| 某个脚本具体做什么 | `references/scripts.md` |

## 脚本

开新一支时从**仓库克隆**复制进 `<项目>/build/`。讲述模式是「模板 + 引擎」，**两个文件都要复制**：
模板只放配置，函数全在 `story_core.py`。改流水线行为去改 `story_core.py`，不要往模板里加函数（回归测试会拦）。

- 讲述：`make_story_v.py`（竖）、`make_story_h.py`（横）、`story_core.py`（引擎）、`join.py`（分段拼全片）
- 诗词 / MV：`make_v.py`、`lyric_sync.py`
- 旁白：`narr_build.py`（稿子拆成一句一条）、`vo_trim.py`（剪静音）、`vo_split.py`（切真人朗读）、`el_tts.py`
- 出图与生成：`comfy_gen.py` + `comfy/`、`el_web_image.py` / `.js`、`upscale.py`
- 素材与下载：`chatcut_dl.py`、`sort_downloads.py`、`music_index.py`、`sfx_index.py`
- 开片 / 看状态 / 交付检查：`episode.py`（预设在 `presets/`）
- 发布与长任务：`publish.py`、`runlog.py`

每个脚本的命令和注意事项见 `references/scripts.md`。回归测试在仓库根 `tests/`。
