# 在 Codex 里跑这条流水线

这份是**操作说明**，不讲为什么——判据和踩过的坑在 `SKILL.md` 和其余 reference 里。
下面每一条都是在 Windows + Codex CLI 上实跑过的。

---

## 〇、技能装在哪，怎么触发

| | 路径 |
|---|---|
| 仓库（唯一真相） | `github.com/chensg/vmskill`，技能在 `classical-poem-video/` |
| 本地克隆 | `~/Documents/vmskill` ——**改代码只改这里** |
| Codex 安装 | `~/.codex/skills/classical-poem-video` ——从克隆同步过去，**不在这里改** |
| Claude 安装 | `~/.claude/skills/classical-poem-video` ——同上 |

**动手前先拉、改完必提交、然后同步两处安装。** 同步命令（PowerShell）：

```powershell
robocopy "$HOME\Documents\vmskill\classical-poem-video" "$HOME\.codex\skills\classical-poem-video" /MIR /XD __pycache__ .git
```

触发：`agents/openai.yaml` 里 `allow_implicit_invocation: true`，所以说
"把《登高》做成竖版短片"就会自动挂上。要显式点名就写 `$classical-poem-video`。

---

## 一、开工前确认三样（缺一样后面全白做）

```bash
ffmpeg -version | head -1      # 主力。成片是本地 ffmpeg 合成的，不是云端渲的
python -V                       # 3.9+ 即可，脚本只用标准库
ls ../../build/fonts/simkai.ttf # 楷体。没有它字幕会退到系统默认字体，全片走样
```

**字体查找顺序**（`make_v.py` 顶部的 `FONTS`，按顺序取第一个存在的目录）：

```
项目/fonts/  →  项目上一级/fonts/  →  项目上一级/build/fonts/
```

放一份 `simkai.ttf` 进去就行。**这台机器上的 python 没有 numpy/scipy/librosa/PIL**，
所有测量都是 `ffmpeg` 出数、纯 python 算——不要试图 `pip install`，
脚本本来就是按这个前提写的。

---

## 二、目录长什么样

```
Documents/ani/《片名》/
├── scripts/
│   ├── make_v.py          ← 从克隆 copy 过来，改配置区
│   └── lyric_sync.py      ← 只有 MV 模式要
├── 素材/
│   ├── img01.png ...      ← 一镜一张，脚本按这个名字找
│   ├── 00_music_main.mp3  ← 或 MV 的 song.mp3
│   └── vo/VO_01.mp3 ...   ← 有诵读时
├── 图片生成任务.md         ← 交给出图的人/模型
└── 《片名》_竖版.mp4        ← 成片输出在项目根，不在 scripts/
```

**新开一支时从克隆 copy `scripts/*.py`，不要从任何一处安装、也不要从上一支 copy。**
上一支的脚本里带着它自己的配置和临时补丁。

---

## 三、三种模式的最短路径

三种都**先跑 `check`，通过了再碰素材**。`check` 不过就出图 = 白出。

### 诗词模式（一首诗，一句一镜）

```bash
cd 项目/scripts
python make_v.py check     # 时间轴自检。永远第一步
python make_v.py budget    # 出图之前跑：按每镜运动反推要多大的图
# ——出图，放进 素材/——
python make_v.py prep      # 裁 9:16 + 调色 → img01..N，自动 probe
python make_v.py trace     # 量镜头真正扫过的区域 + 落幅平坦度
python make_v.py a         # Ken Burns → shots/          ← 慢，后台跑
python make_v.py b         # xfade 转场 → master.mp4     ← 慢，后台跑
python make_v.py c         # 混音 + 归一 + 烧字幕 → 成片
python make_v.py still     # 抽静帧，用眼睛看
python make_v.py measure   # 量字幕底和字色的亮度差（判据 ≥50）
python make_v.py motion    # 量每镜首尾帧差（运镜 ≥4.0，静帧 ≤0.6）
python make_v.py cover     # 封面
```

横版换 `make_h.py`。**但它是旧模板**，缺 `check_safe`/`vig_factor`/`FLIP_SHOTS`/
目标响度音效/粒子层/`pick`/`GRAIN`/`check_paper`/MV 模式——做横版前要么先移植，要么心里有数。
（另：`make_h.py` 不带参数直接跑的是 `check`，不是打印帮助，和 `make_v.py` 不一样。）

### 讲述模式（历史小故事 / 冷知识）

```bash
python make_story_v.py sync    # **多这一步**：量旁白实测时长，时间轴由它推
python make_story_v.py check
# 其余同上；SHOTS 不写 dur
```

先读 `references/storytelling.md`——事实分级表（`CLAIMS`）是这个模式的核心，
不是可选项。

### MV 模式（带演唱的成品歌 + 歌词）

```bash
cd 项目/scripts
python lyric_sync.py probe 素材/song.mp3 --spec        # 出起音表、空档、谱图切片
# ——听一遍，报出每句的起和止——
python lyric_sync.py spans 素材/song.mp3 \
    --lines "枯藤老树昏鸦|小桥流水人家|..." \
    --at "16.478-20.038,20.120-23.360,..."             # 出 SUNG 表 + sync.json
python lyric_sync.py check 素材/song.mp3               # 结构 + 换镜余地
python lyric_sync.py proof 素材/song.mp3 --video       # **必须听一遍**
# ——把打印出来的 SUNG 表整块粘进 make_v.py，MUSIC_MODE="song"——
python make_v.py check                                  # 之后同诗词模式
```

只有起点没有终点就用 `snap --at "16.2,20.3,..."`（会自动校人手打点的滞后）；
有 LRC 就用 `lrc --lrc 歌.lrc`。

**MV 的三条硬规矩**（`check` 会拦）：片长必须等于歌长、`MUSIC_IN` 必须是 0、
`MUSIC_GAIN` 不许压过 −3dB。

---

## 四、Codex 特有的坑（都是实际撞过的）

### 1. 两个 shell 不通用，选错会段错误

Codex 在 Windows 上同时给了 PowerShell 和 Git bash。**带 `drawtext` 的 ffmpeg
在 Git bash 下会 `Fontconfig error` + Segmentation fault**，同一条命令在
PowerShell 下正常。

```
带 drawtext / subtitles / 中文路径的 ffmpeg  → PowerShell
纯管道、grep、逐帧读字节                      → bash 更顺手
```

其余对照：`/dev/null` ↔ `$null`；ffmpeg 丢弃输出一律 `-f null -`（不要写 `nul`）；
PowerShell 里 `&&` 不可用，用 `; if ($?) { }`。

### 2. 长渲染必须后台跑，而且**不能在半路跑下一趟**

`a`（Ken Burns，3× 上采样）和 `b`（xfade）在七镜 50 秒的片子上要 10 分钟以上。
实撞过一次：`b` 还在写 `master.mp4` 时就跑了 `c`，ffmpeg 报
`moov atom not found`——**半截的 mp4 没有 moov**。

正确做法：`a` 和 `b` 串起来后台跑，等它真的结束再跑 `c`：

```bash
(python make_v.py a && python make_v.py b)   # run_in_background
ffprobe -v error -show_entries format=duration -of csv=p=0 master.mp4   # 先确认时长对
python make_v.py c
```

### 3. 中文输出

脚本自己在开头 `sys.stdout.reconfigure(encoding="utf-8")`，所以**直接跑脚本不会有事**。
但你临时写的 `python -c "print('中文')"` 在 bash 下会 `UnicodeEncodeError: cp1252`，
加 `PYTHONIOENCODING=utf-8` 就行。

### 4. 改图之前先备份，而且探测要读原件

任何"修图"脚本都遵守两条：原件先复制进 `素材/_orig/`；**探测一律读 `_orig/`**。
不这么做的话，改一次判据重跑一次，第二次探到的是上一次改完的结果
（实撞过：边界从 936 漂到 1300，有一张直接探不到）。

### 5. `maskedmerge` 会悄悄把整幅拉成灰度

三路输入必须同像素格式，喂一张灰度遮罩进去，ffmpeg 把彩色输入一起转灰。
要保色用 `alphamerge` + `overlay`：

```
[a]<处理>,format=yuva444p[s];[s][mask]alphamerge[sa];[b][sa]overlay=0:0
```

### 6. 审批

`prep`/`a`/`b`/`c` 会写大量文件、跑几百条 ffmpeg。在需要逐条批准的模式下会很痛，
建议把项目目录设成可写、或者用 workspace-write。**不要为了省审批去跳 `check`**。

---

## 五、报错对照

| 现象 | 真正的原因 |
|---|---|
| `moov atom not found` | 上一趟渲染还没结束（见上面第 2 条） |
| `Fontconfig error` + Segmentation fault | 在 bash 里跑了带 drawtext 的 ffmpeg，换 PowerShell |
| `UnicodeEncodeError: cp1252` | 临时 `python -c` 缺 `PYTHONIOENCODING=utf-8` |
| 字幕字体不对 | `FONTS` 三个候选目录都没有 `simkai.ttf` |
| `!! 缺素材: imgNN.png` | 文件名要正好是 `img01.png` 这种；`make_v` 报提示、`make_h` 报错误 |
| `MUSIC_MODE='song' 不认识` | 只有 `make_v.py` 支持 MV；另外三个模板没有 |
| `pick` 拒跑 | MV 模式没有切入点可挑，正常 |
| 检查全绿但成片难看 | 见下 |

---

## 六、最后一条，也是最要紧的一条

**数值判据拦不住的东西，这一支上一口气撞了三样：**

- 生成器把"右侧留素纸"画成一块**实心白板**——`probe` 量出来 220~232，
  比真画面还干净，全绿
- 46px 的落款被 3px 浅描边冲成灰——`measure` 判的是"字底"离字色多远，
  143 级，全绿
- 唱段结束的位置——起音检测在尾奏里照样找得到一堆峰，结构自检全绿

三样都只有**眼睛**和**耳朵**发现得了。所以：

```bash
python make_v.py still     # 逐张打开看
python lyric_sync.py proof # 听一遍
```

**这两步不能跳，跳了前面所有的量都白量。**
