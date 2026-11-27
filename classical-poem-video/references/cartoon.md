# 卡通画风（粗线漫画）出图管线

2026-11-21 第二频道英文长片《Why It's Hell to Be a Chaste Widow》（98 镜、10 个角色）和关联 Short
《Bury Me With My Finger》踩出来的。全在本机 3090 上跑，三个模型都是 Apache-2.0，可商用。

画风「A 粗线漫画」＝ Théo / Bernard 那类英文「Why it sucks to be…」历史动画频道的样子：
粗而均匀的黑描边、平涂亮色、没有渐变、大眼睛。用户在三种画风样张里挑的这一种。

## 一张表：谁出哪种镜头

| 镜头 | 模型 | 为什么 |
|---|---|---|
| 角色定妆（每人一张竖版全身） | Qwen-Image-2512 文生图 50 步 | 定妆图就是之后所有镜头的「长相合同」 |
| **有人物的镜头** | **Qwen-Image-Edit-2511** int8 ＋ Lightning 4 步，拿定妆图当参考 | 只靠文字描述，同一个人每张长得都不一样；参考图法 10 个角色全片认得出来 |
| **空镜**（景、物、建筑、人群远景） | Qwen-Image-2512 **纯文生图** 50 步，不给参考图 | 编辑模型拿参考图出空镜会翻车，见下面「两轮翻车」 |
| 放大到 4K 静帧 | SeedVR2 静帧（`comfy_gen.py upscale --image`） | 平涂画风放大后线条更利，没有偏色问题 |

编辑模型 **4 步比 40 步好**：颜色更亮、更像目标画风，而且 15 秒一张（40 步要两分多钟）。

## 命令

```
cp <克隆>/scripts/{cartoon_jobs.py,qwen_edit.py,comfy_gen.py} <项目>/build/   # comfy/ 也要
cp <克隆>/scripts/presets/cartoon_config.py <项目>/build/                        # 填 REFS / SHOTS / T2I_SHOTS
python -X utf8 cartoon_jobs.py refs            # 定妆 → 素材/生成/角色/
python -X utf8 cartoon_jobs.py sheet refs      # 定妆表，给用户认角色
python -X utf8 cartoon_jobs.py shots           # 全部分镜 → 素材/生成/原图/S<n>.png（1920x1088 / 空镜 1664x928）
python -X utf8 cartoon_jobs.py sheet           # 镜头联络表，逐张看
python -X utf8 cartoon_jobs.py up              # 放大 → 素材/生成/S<n>.png，film.py 的 STILL_PAT 指这里
```

已有的跳过。重出哪张：把它挪进 `原图_废/`，必要时在 `SHOT_SEED` / `T2I_SEED` 换种子，再跑 `shots <镜号>`。
单张修补（去掉血迹、改一个道具）用 `python qwen_edit.py fix <out> "<修改指令>" <原图> --fast`，
尺寸跟原图走（11-21 修过：模板会把图缩到 1MP 再编码，1088x1920 改完变 752x1392）。

## 两轮翻车（98 镜重出了两轮）

1. **画风句里写了照明**。「只用蜡烛和陶土油灯照明」写在统一画风句里 → 几乎每张都在桌上摆一排灯。
   画风句只写线条、颜色、造型；要灯写进那一镜的画面句。
2. **「只借画风」的参考图会被抄内容**：
   - 拿**带人**的定妆图当画风参考出空镜 → 那个寡妇被贴进空镜，有两张里她站上了殉节台，和旁白冲突。
   - 换成**没有人**的场景图当画风参考 → 那张图里的运河和石桥被抄进了 13 个空镜。
   - 结论：**空镜不给参考图，走纯文生图**（`T2I_SHOTS`）。`STYLE_SCENE` 只留给「人物不认识、但要画风一致」的人群镜。
3. **外国味**：纯文生图会冒出西方面孔、罗马拱门、皮鞋、火漆印。中国的东西要点名写成中国的：
   「Chinese stone memorial archway (pailou) with small tiled roofs and three openings」，不要只写「memorial arch」。
   第三轮把六张空镜这样改写、换种子，全过。
4. **否定句会把东西招来**（2026-11-26 卖妻）：写「no Forbidden City, no palaces, no yellow glazed roofs」，
   县衙那几镜反而出了紫禁城和黄琉璃瓦。Qwen 两个模型都不懂否定，只认名词。只写要什么
   （「a plain grey-tiled gatehouse with whitewashed walls」），要的东西写具体就挤掉了不要的。
5. **全局写「男人剃发留辫」，编辑模型会把女人也剃了**：同一句在 `EDIT_SET` 里，只有女人的镜两轮都出光头女人。
   剃发只写进有男人的那几镜；只有女人的镜号放进 `WOMEN_ONLY`，`cartoon_jobs.py` 对它们改用 `EDIT_STYLE_W`
   （配置里 `EDIT_STYLE_W = EDIT_STYLE.replace(EDIT_SET, "...The woman has a full head of thick black hair. ")`）。
   女人那镜的画面句再写一次「her thick black hair in a bun」。
6. **「oil lamp」出玻璃罩煤油灯**：清代穷人家点灯改写「a short white candle in a plain brass candlestick」。
7. **「a man sits on a rock」会出两个**（11-27 余氏 Short 镜 10）：远景里的配角要写「one single ... alone」，
   再加一句「Exactly two people in the whole picture: ...」（肯定句，不是 no third person）。

## AI 画不出来的东西：换个拍法

- **缺一根手指的手**：四个种子都画成五指（或六指）。改拍装手指的木盒，旁白讲。
- **血、伤口、绳结**：别画。菜刀上的血用 `qwen_edit.py fix` 去掉；殉节只拍台和人群背影。
  这也是 YouTube 广告友好的底线。
- **文字**：画面里的字基本是乱码（偶尔对）。引文、诏书走 film.py 的 `quote` 引文板，别指望出图模型写字。
  每条提示词末尾都加了 `No text, no letters, no writing anywhere.`。

## 角色一致性怎么做

- 定妆描述写死能区分人的特征：脸型、眉眼、**一个记号**（痣、雀斑）、发型＋发饰、衣服颜色。
  同一支片里的女性角色衣服颜色要分开（白、灰、浅蓝、粉、浅绿、棕），观众靠颜色认人。
- 画面句里用「the young widow from the reference」指参考图里的人；两人同框时另一个人用文字描述就行（配角不定妆）。
- 关联 Short 里已经定好的人物，用 `REF_FILE` 直接指那张图，长片和 Short 是同一张脸。
- 同一人换年龄（16 岁新娘 → 78 岁临终）：各给一张参考图，不要指望模型自己变老。

## 让画面真的动起来：本机 MiniMax H3 图生视频（2026-11-22 实测）

静帧做完以后，挑一部分镜头用 Pika H3 8 步 HD 做图生视频，流程跟写实长片一样（`references/long-film.md`），
只改三处：

1. `vid_prompts.py` 里 `CARTOON = True`：每条前面自动加画风句（粗线不变宽、平涂、不加 3D 和光影、不切镜），
   「realistic human motion」换成卡通表演的说法。
2. `PREFIX = "S"`，首帧直接用 `素材/生成/S<n>.png`；`film_config.py` 的 `VID_PREFIX` 也改 `"S"`。
3. 影片自带的声音不要：H3 会给人物配喊叫声（镜 37 实测有声），卡通片由英文旁白讲，`film_config.py` 写 `MUTE_GEN = True`。
   （11-22 前这里写的是 `MUTE_EXT`——那个只管 SPEC / CARD_BG 里的外部影片，[生] 镜的原声照样进混音。）

**四镜实测**（《Why It's Hell to Be a Chaste Widow》镜 02 / 37 / 53 / 08，1280x704、5.2 秒、种子 42，
对照片 `第二频道_贞节寡妇/动画试验/动画试验_四镜对照.mp4`）：

| 镜 | 内容 | 结果 |
|---|---|---|
| 02 特写 | 寡妇对镜举针、流泪 | 眨眼、眼泪往下流、手和针在动；脸颊多了一点柔和阴影，线条不变 |
| 37 双人 | 婆婆指着骂、寡妇低头 | 嘴一张一合在骂，寡妇垂下眼；两人长相全程不变 |
| 53 夜景 | 姐妹灯下读书 | 缓推、火苗跳、两人眨眼微笑；左边那位的眼形帧间略有变化 |
| 08 空镜 | 运河小镇 | 水波、船漂、柳枝摆、镜头平移；画风最稳 |

- **粗线和平涂守得住**，没有变成 3D 或写实，这是最担心的一点。
- 耗时：首条冷启动 793 秒，之后每条 490~541 秒（5.2 秒片）。
- 放大走 FlashVSR+（视频放大的默认）：`python run_pika.py --up none` 只出 1280x704 原片到 `素材/影片_720/`，再 `python fvsr_batch.py`（前缀不限，S 开头的卡通镜也认）出 1920x1080 到 `素材/影片/`。不加 `--up none` 是老路子 SeedVR2。
- 动作要小：卡通人物做大动作（走远、转身、甩袖）还没试过；写实片的经验是大动作会糊、会变脸，先当成同样的限制。
- 不是所有镜都要动。一支 14 分钟、98 镜的片子全做要约 14 小时；先给开头一分钟、每章第一镜和情绪最重的镜。

### 整片实测（2026-11-22《Why It's Hell to Be a Song Princess》，17 镜）

- 帧数照旁白长度（上限 362 帧＝15 秒）：**出片约 5.6 秒/帧**——124 帧 9 分钟、192 帧 13 分钟、277 帧 21 分钟、362 帧 34 分钟。
  17 条共 4,488 帧，H3 6 小时 19 分；FlashVSR+ 放大 17 条 1 小时 50 分。镜长超过 15 秒的，film.py 放慢 15% 后定格补齐。
- 16 条能用，1 条不用：**空镜写了「No person appears」也会走出人来**（镜 47 月夜池塘，2.6 秒起屋边走出一个小人，
  而那一镜讲的是皇后投水，等于替旁白演了出来）。空镜动画出完要逐格看人，不只看画风。
- 「转头看镜头」被演成转身走开（镜 05），这次反而更好；大动作（拍桌站起、从马上滑下来）粗线照样守得住，没有糊。
- 卡通片 film_config 要写 `MUTE_GEN = True`（见上面第 3 条），`VID_PREFIX = "S"`；只给要动的镜标 `[生]`，其余留 `[推]`——
  `[生]` 镜缺影片时 film.py 不会退回静帧，会报缺画面。

## 交给 film.py

`film_config.py` 里 `STILL_PAT = "素材/生成/S{n}.png"`；引文板、章节卡底图都直接指这批图。
英文主轨的片子：film.py 的字幕按字符数分时长（没有汉字时），2026-11-22 起是默认行为。
