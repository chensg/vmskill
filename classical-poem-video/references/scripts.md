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
