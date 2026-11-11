# 脚本一览

> 2026-11-11 从 SKILL.md 原样挪来（总纲只留摘要）。

脚本（`scripts/`，开新一支时从仓库克隆里复制，放进 `<项目>/build/`）：

**讲述模式是「一个模板 + 一个引擎」，两个文件都要复制。** 模板只放配置，
所有函数在 `story_core.py`，横竖两版共用这一份（2026-09-25 拆出来的：
两份手抄脚本时代，112 个同名函数里 50 个已经分叉，好几处是一边修了 bug 另一边没跟上）。
**改流水线行为去改 `story_core.py`，不要往模板里加函数** —— 回归测试会拦。
横竖的差别全部是配置：W/H（推出 `LAYOUT`）、`SUB_MODE`、`SEG_*`、`HARD_LIMIT`、`SAFE_*`。

| 脚本 | 做什么 |
|---|---|
| `story_core.py` | **讲述模式引擎**，横竖共用。不直接跑，由模板在配置之后 `exec` 进来 |
| `make_story_v.py` | 讲述模式竖版 1080×1920 的配置模板，内含《没有夏天的那一年》。`SUB_MODE` 定烧录还是外挂 |
| `make_story_h.py` | 讲述模式横版 1920×1080 的配置模板（长片的「一段」，不分段也行），内含《经度》段一。长片和小说连载都走它 + `join.py` |
| `join.py` | 分段拼全片：一次全局响度归一、按实际段起点合并 SRT、接缝校验、多音轨 `-map 0` |
| `make_v.py` | 诗词模式竖版 / MV，内含《雨霖铃》的完整配置 |
| `lyric_sync.py` | MV 对轴：`probe` → `spans` / `snap` / `lrc` → `check` → `proof`（必须听一遍） |
| `narr_build.py` | 讲述稿.md → narr.json（一句一条 VO）。表格版（`\| 句号 \| 旁白 \| 画面 \|`）和镜头段落版（`**鏡N**` + `> 甲｜乙`）都认 |
| `el_tts.py` | ElevenLabs 旁白：`gen zh/en` 逐条生成（重出时自动清 _orig/_raw 旧件）、`asr zh/en` 转写分类核对、`credits` 查额度 |
| `vo_trim.py` | 剪 TTS 每条头尾自带的静音。**讲述片下载完旁白、`sync` 之前必跑**。账本 `_trimmed.json` 认得出重出过的新录音（不再拿旧原件盖掉） |
| `el_web_image.py` / `.js` | ElevenLabs 网页版出图：任务书 → 压缩提示词 → 页面里提交与收 2K 原图 → 下载 |
| `comfy_gen.py` + `comfy/*.api.json` | 本机 ComfyUI：`start`／`check`；`image`（`--fast`/`--variants` 进候选，`promote` 转正，`sheet` 联络表）；`video`（缺首帧自动补 4 步、硬切当场报，`strip` 帧条）；`upscale`（SeedVR2 / lanczos）；`notes` 生成记录。每次生成记进 `素材/生成/comfy_log.jsonl`。影片秒数用引擎的 `vidplan write` 算 |
| `upscale.py` | 档案照片 EDSR ×2 超分（OpenCV，CPU）。中文路径安全；单进程（OpenCV 自己吃满线程，多进程反而慢 3 倍） |
| `vo_split.py` | 把一整条真人朗读切成一句一个文件 |
| `music_index.py` / `sfx_index.py` | 素材库（`ani/_素材库/`）。`music_index.py find --dur <片长>` 是查库入口 |
| `publish.py` | 发布文案骨架 + 量各平台标题截断位置 |
| `sort_downloads.py` | 把浏览器下载来的一堆文件归到脚本要找的位置 |
| `chatcut_dl.py` | ChatCut 生成物落地：`page` 出下载页（`<a>` 点击，首条后停 4 秒等授权）＋清单 `.json`（记出页时刻）；`wait` 只收出页之后落地、大小已稳定的文件（认 ` (N)`、`.mp3.mp3`），齐了复制进项目，久等不齐自动出**只含缺件**的补下载页 |
| `runlog.py` | **长任务一律用它跑**（渲染、等下载、重渲全片）：步骤文件 `== 步骤名` 分段，一步失败即停；主日志记时间/成败/每步末几行，末行 `RUNLOG DONE/FAILED/STOPPED`；`.pid` 锁防同一件事起两份；`stop` 连子进程整棵树停（TaskStop 只停外层 shell，2026-11-02 旧脚本因此自己跑完、覆盖了全片）；`status` 看进度 |

横版诗词模板 `make_h.py` 2026-09-25 退役。回归测试在仓库根 `tests/`。

## `episode.py`（2026-11-11）

只看文件，不 import、不 exec 引擎和配置，所以不走引擎的片子也能用。

| 命令 | 做什么 |
|---|---|
| `new <项目目录> --type short\|long [--title 片名]` | 建 `build/`、`素材/`，复制模板、引擎和常用工具；Short 放 `presets/segment_config_short_v2.py`；生成讲述稿 / 查证记录 / 素材处理说明骨架；记引擎提交号（`build/ENGINE_COMMIT.txt`）。**已有文件不覆盖**，片库根拒绝 |
| `status <项目目录>` | 稿子、门禁、旁白到了几条（缺的点名）、素材、中间件、成片与字幕音轨、封面、发布文案；末行是按缺什么推的下一步 |
| `deliver <项目目录> [--video 成片] [--type short\|long] [--mono] [-v]` | 封装（H.264、单音轨、AAC 48k 立体声、画面尺寸）、响度 −15±1、Short ≤180s、中英 SRT 不超片长、英文轨与画面等长、封面 ≤2MB（长片要英文那张）、`publish.py check`、长片章节时间码、门禁签字。只打印没过的，全过退出码 0 |

回归 `tests/test_episode.py`（约一分钟）：造齐全的假片子不该报，逐条弄坏必须报那一项。

## `film.py` 和 `longfilm/`（2026-11-11）

横版长片的合成和生成工具，细则 `long-film.md`。`episode.py new --type long` 会把它们铺进 `build/`。

| 脚本 | 做什么 |
|---|---|
| `film.py` | `check`（逐镜画面从哪来、缺什么）、`tsv`、`srt`、`gate2`（门禁二片）、`shots <镜号…>`、`part N`、`final`、`en [check]`。画面按帧网格对齐；整片归一 −15 LUFS；缺画面时 `final` 拒绝；成品比配置和源文件都新才沿用 |
| `presets/film_config_long.py` | `film.py` 的配置模板：常数、`SPEC`（kb / page / route / labels / clips / seq）、`CARD_BG`、英文卡字 |
| `presets/vid_prompts.py` / `music_prompts.py` | 影片镜动作提示词、各段配乐描述的模板 |
| `longfilm/run_pika.py` + `pika_seedvr2.py` | 本机 Pika 8 步 HD → SeedVR2 1080p，按 `vid_prompts.py` 逐条跑，已有成品跳过。工作流在 `comfy/video_pika_h3_*.json`。**收进来后没联机跑过** |
| `longfilm/mm_music.py` | 本机 MiniMax Music3 出纯音乐，读 `music_prompts.py`。**收进来后没联机跑过** |
| `longfilm/frame_strips.py` | 影片每条抽 6 帧拼成一行，再叠成总表 |
| `longfilm/sep_vocals.py` | HDemucs 报配乐里的人声占比，出去人声版（用 ComfyUI 的 python 跑） |
| `longfilm/fish_en.py` | 英文旁白：Fish s2-pro，过提亮 EQ |

回归 `tests/test_film.py`（两三分钟）。
