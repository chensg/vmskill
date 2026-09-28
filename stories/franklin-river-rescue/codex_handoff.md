# 交接给 Codex：《被困激流20小时》

2026-09-28 · 从 Claude 会话交接 · 讲述模式 · 横版分段长片

**先读这三份，再动手**：`classical-poem-video/references/codex.md`（怎么跑）、
`references/storytelling.md` 第〇、一、八节（门禁、事实分级、TTS）、
`research/youtube-faceless-storytelling.md` 第四节（缺图时画面怎么处理）。
这份交接只写这一支特有的东西。

---

## 〇、现在在哪一步

| | 状态 |
|---|---|
| 讲述稿 | **第三版写完**：`stories/franklin-river-rescue/script_zh.md`，2236 汉字，四段 |
| 事实核查 | 做完一轮，结果在下面第二节。**还有一条 `待核`（C30），是门禁一的前置条件** |
| 门禁一（讲述稿人工确认） | **没签**。用户还没读第三版 |
| 三条轴 | **没定**。见第四节，要用户拍板 |
| TTS / 检查片 / 出图 / 渲染 | 都没开始 |

**下一步只有一件事：把 `script_zh.md` 交给用户读，拿到门禁一的签字。**
签字之前不要生成 TTS——改稿比重生成一批 mp3 便宜。

---

## 一、这一支的基本面

| | |
|---|---|
| 事件 | 2024-11-22，塔斯马尼亚富兰克林河。立陶宛漂流者 Valdas Bieliauskas 左腿卡进石缝，被困约 20 小时，急诊医生 Jorian "Jo" Kippax 在水下完成膝上截肢；脱困后心脏骤停，机械心肺复苏 90 分钟 + ECMO 救回 |
| 模板 | **`make_story_h.py` + `story_core.py`**（横版 1920×1080，外挂 SRT，分段）。从仓库克隆 copy，不从别的项目 copy |
| 分段 | 四段，一段一个目录：`段一` `段二` `段三` `段四`，`SEG_TOTAL = 4`，最后 `join.py` |
| 片长估算 | 默认节奏 0.346 s/汉字 → **约 12.9 分钟**；紧节奏 0.26 → **约 9.7 分钟**。外文名另算音节（见第六节）。**这只是估值**，`sync` 之后以实测为准 |
| 平台 | YouTube 长片（用户原稿未指定；如果要出竖版短切，另开一支，不在这支里做） |
| 语言 | 简体中文单轨。`LANGS = ["zh"]` |

分段和估算：

| 段 | 标题 | 汉字 | 默认 / 紧（秒） | 段尾钩子 |
|---|---|---|---|---|
| 段一 | 滑倒 | 594 | 206 / 154 | 「他们还不知道，这一等，就是一整夜。」 |
| 段二 | 一整夜 | 447 | 155 / 116 | 「Valdas点了点头。」 |
| 段三 | 两个医生 | 510 | 177 / 133 | 「整个截肢，只用了大约两分钟。」 |
| 段四 | 90分钟 | 685 | 237 / 178 | 全片结尾 |

段一有冷开场（从水下截肢那一刻切进去，停在「一下。两下。」，**不说锯断了**——
「钢丝断了」留到段三才揭晓，这是全片的主钩子，排片时别让任何字卡或画面提前泄露）。

---

## 二、CLAIMS 表

### 级别

- **史实 / 概数**：`storytelling.md` 第一节的定义，照用
- **假说**：本片**没有**。低体温保命是报道原话 + 医学常识，不是推断
- **待核**：本表新加的一级，`check_claims` 只打印不拦。含义是「来源是用户给的原稿，
  这一轮没能从可访问的报道里找到」。**门禁一签字之前，每条待核要么升成史实，要么从稿子里删掉**

稿子里每句句末的 `[Cxx]` 就是这张表的编号，**不上屏、不进 TTS**，拆 `NARR` 时去掉。

### 可直接粘进每一段 `make_story_h.py` 的表（全片一张，四段相同）

```python
CLAIMS = [
    ("C01", "史实", "2024-11-22 塔斯马尼亚西南部富兰克林河", "ABC / Paddling Magazine"),
    ("C02", "史实", "1983 塔斯马尼亚水坝案，高院 4:3，大坝停建", "Commonwealth v Tasmania 1983-07-01；稿里说『四十多年前』"),
    ("C03", "概数", "六十多岁；一行十一人", "年龄报道 66（多数）/ 69（The Examiner），**片内不给精确值**；11 人见 Paddling"),
    ("C04", "概数", "带立陶宛国旗漂各大洲山地河流，澳洲是最后一站", "『五大洲』(Paddling) vs『所有大洲』(15min/LRT)；稿里说『各个大洲』"),
    ("C05", "史实", "河上第五天；急流不安全，改为上岸抬船绕行", "Paddling：five days in / portage"),
    ("C06", "史实", "左腿卡进两块巨石间的窄缝，水没到胸口", ""),
    ("C07", "概数", "被困『将近20个小时』", "报道 ~20h / 近 24h 都有；稿里统一『将近20个小时』"),
    ("C08", "史实", "大峡谷段（Great Ravine，Coruscades 急流）", "急流名不进旁白"),
    ("C09", "概数", "水温 8~10℃；每秒约 13 吨", "报道原话 8-10 degrees / 13 tonnes per second"),
    ("C10", "史实", "厚潜水服 + 救生衣；没救生衣可能被吸到石下；朋友每 30 分钟送热食", "Paddling，救援人员的判断，稿里带『救援人员后来说』"),
    ("C11", "史实", "液压扩张器、气囊、钻孔架三脚架滑轮", "spreaders/hydraulics/airbags/drilled tripod pulley"),
    ("C12", "史实", "Rohan Kilham（Ambulance Tasmania 重症飞行急救员）三段引语", "ABC Australian Story；中文是意译，**原文附在第二节下面**"),
    ("C13", "史实", "凌晨 4 点决定截肢", ""),
    ("C14", "史实", "膝上截肢", "above-the-knee"),
    ("C15", "史实", "队友 Arvydas Rudokas 用立陶宛语翻译；『你会死在这个坑里』", "他是不是医生来源不一，**稿里不说**"),
    ("C16", "史实", "Nick Scott 是现场唯一医生，滑倒摔断手腕", "retrieval consultant"),
    ("C17", "史实", "Jo Kippax 急诊专科，本人是有经验的白水皮划艇手", "Ambulance Tasmania 转运顾问 / 皇家霍巴特医院"),
    ("C18", "史实", "不戴手套；魔术贴止血带水下失效，改用棘轮绑带；氯胺酮", ""),
    ("C19", "史实", "Gigli 线锯锯到一半断了，徒手折断股骨", ""),
    ("C20", "史实", "没有大出血；全程约两分钟", ""),
    ("C21", "史实", "脱困后心脏骤停；机械 CPR；到霍巴特皇家医院时已 90 分钟", ""),
    ("C22", "史实", "低体温是活下来的原因之一", "报道原话 survived thanks to hypothermia and advanced CPR"),
    ("C23", "史实", "急救员提前通知医院备 ECMO；ECMO 上昏迷四天", ""),
    ("C24", "史实", "ICU 里开口说英语；译员 Jurgita 说『他就是一个幸存者』", "**原稿写成 Valdas 自己说的，改了**，见下"),
    ("C25", "史实", "2025 年 1 月回立陶宛；拐杖 → 假肢", "15min.lt / Amputee Store"),
    ("C26", "史实", "2025-07-06 立陶宛国家日，总统在维尔纽斯授 Kippax 救生十字勋章", "Pulse Tasmania / ABC 2025-07-07"),
    ("C27", "史实", "2026 年塔斯马尼亚州年度澳大利亚人", "2025-11-18 公布"),
    ("C28", "史实", "他说想装着假肢回来把最后一站漂完", "**2025 年的说法，有时效**，见下"),
    ("C29", "概数", "『一天一夜』= 救援全程", "15min.lt 23 小时 / ABC『24-hour rescue』"),
    ("C30", "待核", "原稿细节五处（见下）", "**门禁一前必须清掉**"),
]
```

### 三条要特别交代的

**C24 —— 原稿有一处归属错误，已改。**
原稿写「Valdas 醒来第二天用英语说：我是幸存者」。能查到的报道里，
"He is a survivor" 是医院里帮忙翻译的霍巴特立陶宛社区志愿者
**Jurgita Rakauskaite-Stanwix** 说的：

> "I was in tears. Nurses were in tears. It's just such a beautiful moment. And he is. He is a survivor."

她那句 "And he is." 暗示 Valdas 先说了类似的话，但 ABC 原文这一轮读不到（见第八节），
**不能写成他的原话**。如果用户手里有原文、证实他说过，可以改回去，改完把 C24 的备注一起改。
另外「醒来第二天」也没核实到，稿里只说「在ICU里」。

**C28 —— 有时效，发布前必须重查。**
「2026 年回富兰克林河把最后一站漂完」是 2025 年报道里他的计划。截至 2026-09-28
**没查到他有没有成行**。发布前搜一次：
- 已经成行 → 这是比现在强得多的结尾，改段四最后四句，并告诉用户
- 还没成行 / 查不到 → 保持「他说……他想……」的说法，**不要改成将来时的肯定句**

**C30 —— 五处待核（全部来自原稿，这一轮没找到出处）：**

| 位置 | 内容 |
|---|---|
| 段一 | 朋友们拉了 40 分钟；有人把手伸到水下去摸 |
| 段二 | 一开始他还挺镇定，会说话、开玩笑 |
| 段三 | Jo 问「真的没有别的办法了吗」 |
| 段四 | 先停了呼吸、马上通气，然后心脏才停 |

对照 ABC 2025-06-29 那篇长文和 Australian Story 两集（The River Part 1 / Part 2）。
对得上就把 C30 拆成对应的史实条；对不上就删句子，删完重数片长。

### C12 引语原文（中文是意译，TTS 读中文）

- "How does someone's leg go into a crack and not come out, like surely there is a way, there is always a way and there wasn't."
- "There's a little part of you that thinks that we killed him as his rescuers."
- （被问 Valdas 当时是否已经死了）"I couldn't say yes, but I definitely couldn't say no."

C15 原文："Valdas asked, 'So I will become handicapped?' Maybe, Valdas. But if not, you will die here in this hole."

### 已经从原稿里删掉的（别加回去）

| 原稿 | 为什么删 |
|---|---|
| 65 岁 | 报道是 66 / 69，改成 C03 的概数 |
| 标题「24小时」、正文「近24小时」 | 被困约 20 小时，24 是救援全程。改成 C07 / C29 |
| 两架直升机、500 公斤装备、几十次吊运 | 查不到；立陶宛媒体说是 **7 架**直升机，冲突 |
| ICU 18 天 | 查不到 |
| Jo 后来再见 Valdas、对截肢「怀有复杂的感情」 | 查不到，而且是替当事人说心情 |
| 事发在「前一天中午」 | 查不到具体时刻 |
| 「Valdas 说：我是幸存者」 | 见 C24 |

---

## 三、稿子的几条写法，拆 NARR 时别弄丢

- **一个自然段 ≈ 一到两条 `NARR`**。「一下。」「两下。」「钢丝断了。」「没有。」这种单句**各自一条**，它们是节奏，不能并句
- **冷开场**：段一第一条 `pre` 用 1.2~1.6（`check_coldopen` 会拦默认值）
- **钩子之后硬切**：段一「……唯一能切断骨头的东西。」→「事情要从前一天说起。」这里 0.4~0.5s 硬切，不溶解
- **「钢丝断了。」**：前一句「锯到一半——」`post` 留足（≥0.8），这一句前面不要转场。转场只放在它**之后**，0.4s 短切
- **金句**：全片最后一句「然后，一群人用了一天一夜，把他一点一点从死亡那边拉了回来。」前 0.8、后 1.2，2.0s 长叠化进尾板
- **引语**（Rohan、Arvydas、Jurgita）：旁白读，不配角色音。字幕保留中文引号
- **加粗只是给人读稿看的**，拆 `NARR` 时去掉 `**`

---

## 四、开工前要用户拍板的三条轴（**没定，别替用户定**）

下面是建议，交给用户选：

| 轴 | 建议 | 理由 |
|---|---|---|
| `MOTION` | `kenburns`，地图/示意图/字卡逐镜 `motion="static"` | 十分钟横版全静帧会闷；示意图动起来反而难读 |
| `MUSIC_MODE` | `library` 或 `generate`，低存在感的暗调铺底，全程侧链躲闪 | 研究报告第四节纪律五：缺图时声音要多扛情绪。**截肢和心脏骤停两处建议抽掉音乐只留河水声** |
| `IMG_SOURCE` | **`generated` + `CREDITS` 登记找来的那几份**（`story_core` 支持混用） | 见第五节 |

---

## 五、画面：这一支的硬约束

**这是真人真事，当事人都在世。** 按 `research/youtube-faceless-storytelling.md` 第四节：

1. **不生成任何当事人的脸**：Valdas、Jo、Nick、Rohan、Arvydas、Jurgita 一律用剪影、背影、手，或者名字字卡（L6 / L3）
2. **不用新闻照片和 Australian Story 的截图**：ABC、Ambulance Tasmania、Tasmania Police 的图都有版权。用户如果拿到了授权，登记进 `CREDITS` 再用
3. **截肢不画**：「切开皮肤，切开肌肉」到「整个截肢，只用了大约两分钟」这一整段，画面走**示意图 + 物件 + 黑场**，不出现伤口、血、断肢。平台审核是一半原因，另一半是：这一段的力量在声音上
4. **写实生成图只放 L5**（河、石头、雨林、水面、夜色），不带人、不带可以核对的细节
5. **示意图角标「示意」**，全片统一位置

建议的锚点（研究报告纪律四：复用本身就是风格）：

| 锚点 | 等级 | 用在哪 |
|---|---|---|
| 塔斯马尼亚 → 西南荒野 → 富兰克林河 → 大峡谷段 的一张地图 | L2 | 段一交代地点；段二「车开不进来」；段四飞往霍巴特。每次换取景 |
| **被困时长计数器**（「约 0 小时」→「约 5 小时」→「凌晨 4:00」→「约 20 小时」） | L6 字卡 | 每段开头一次。数字前一律带「约」，对应 C07 |
| 石缝剖面示意：两块巨石、一条腿、水流方向 | L2 | 段一「插进窄缝」；段二「腿是怎么进去的」；段三截肢 |
| 线锯、棘轮绑带、ECMO 回路三张物件/原理图 | L3 | 段三、段四 |

找来的素材（登记 `CREDITS`，跑 `credits` 出来源表）：Wikimedia Commons 上的富兰克林河
实景（注意逐张看许可证，CC BY-SA 要署名）、OpenStreetMap 底图（ODbL，要署名）。
**上面每一张都要在 `still` 里用眼睛看过**，别只看许可证。

---

## 六、TTS 与片长的两个坑

**外文名算不进汉字数**（`storytelling.md` 第七节附注）。本稿外文词约 40 个
（Valdas、Kippax、Rohan、ECMO……），`EST_RATE` 估算会**偏短**。按音节补，或者直接生成完跑 `sync`。

**外文名先试听。** 豆包渊博小叔读 Valdas / Bieliauskas / Kippax / Arvydas / Jurgita 可能别扭。
先单独生成含这几个名字的四五句试听，读得不自然就换中文音译，**旁白和字幕一起换**：

| 原文 | 音译备选 |
|---|---|
| Valdas Bieliauskas | 瓦尔达斯·别利奥斯卡斯 |
| Jorian "Jo" Kippax | 乔里安·基帕克斯（乔） |
| Nick Scott | 尼克·斯科特 |
| Rohan Kilham | 罗汉·基勒姆 |
| Arvydas | 阿尔维达斯 |
| Jurgita | 尤尔吉塔 |
| ECMO | 保留字母，或「叶克膜」（读前先问用户） |

TTS 配置照抄 `codex.md` 第五节，**不设 `speedRatio`**。本片要逐句加写的：

| 句子 | 加写 |
|---|---|
| 「锯到一半——」 | 句尾吊住，等下一句落下来 |
| 「钢丝断了。」 | 短、平，不要惊呼 |
| 「手腕断了。」「接着，心脏也停了。」 | 同上，陈述，不渲染 |
| 三段引语 | 略放慢当引语；不要模仿哭腔 |
| 「可Valdas有一个特殊的条件：他太冷了。」 | 冒号处停住 |
| 「那他就当第一个。」 | 句尾略收，不要上扬成玩笑 |

---

## 七、命令序列（每段各跑一遍，全在 PowerShell 里）

```powershell
# 0. 建目录，每段 copy 一份模板和引擎（从仓库克隆，不从别的项目）
#    段一/scripts/make_story_h.py + story_core.py + vo_trim.py，段二……同理
#    改 SEG_INDEX / SEG_TOTAL=4 / SEG_NAME / TITLE / CLAIMS（四段同一张）/ NARR

# 1. 门禁一：用户读 script_zh.md，签字写进 GATE_SCRIPT_OK（写人话，不写 True）
# 2. TTS：一句一条 mp3，VO_<镜号><序号>；提交完用 codex.md 第五节那句 assert 核对
python vo_trim.py measure            # sync 之前必跑：先量
python vo_trim.py apply              # 再剪，原件备份到 vo_orig/
python make_story_h.py sync
python make_story_h.py check          # CLAIMS 会打出来；C30 还在就停下
# 3. 门禁二：检查片给用户听，签字写进 GATE_PREVIEW_OK
python make_story_h.py preview
python make_story_h.py gates
# 4. 两道都签了才跑
python make_story_h.py budget         # 尺寸分档抄进出图任务书
# 5. 图到了：prep → trace → a → motion → b → c → still → measure → cover
#    a 和 b 串起来后台跑，确认结束再跑 c（codex.md 第四节第 2 条）
# 6. 四段都出了段用文件
python join.py 段一 段二 段三 段四
python publish.py new 被困激流20小时
```

---

## 八、这一轮核查的局限（交给下一个人知道）

- **ABC、RNZ、Paddling Magazine、塔斯马尼亚大学的原网页这一轮都抓不到**（出口网络拦截），
  上面的事实来自搜索摘要，**没有逐篇核对原文**。C12、C15、C24 的英文原话也来自摘要
- 能抓到原文的环境里，优先对这两个：ABC 2025-06-29 长文、Australian Story 两集
- 发布文案的简介里列出下面的来源（`storytelling.md` 第一节：核查要留痕）

## 来源

- ABC News：[How one slip on the Franklin River triggered a race to save a rafter's life](https://www.abc.net.au/news/2025-06-29/franklin-river-rescue-man-stuck-lithuanian-valdas-leg-amputated/105420916)（2025-06-29）
- ABC News：[The River, Part 1](https://www.abc.net.au/news/2025-06-30/the-river,-part-1-franklin-river-rescue/105478962) / [Part 2](https://www.abc.net.au/news/2025-07-07/the-river,-part-2-franklin-river-rescue/105504920)（Australian Story）
- ABC News：[Franklin River rescue doctor receives Lithuanian award](https://www.abc.net.au/news/2025-07-07/franklin-river-rescue-doctor-awarded-lithuanian-medal/105485760)
- ABC News：[Doctor from Franklin River rescue named 2026 Tasmanian of the Year](https://www.abc.net.au/news/2025-11-18/australian-of-the-year-for-tasmania-2026/106021912)
- Paddling Magazine：[Inside The Whitewater Accident That Led To An Underwater Amputation](https://paddlingmag.com/stories/news-events/underwater-amputation-rescue/)
- Yahoo News Australia：[Chilling new details on 20-hour rescue](https://au.news.yahoo.com/chilling-details-20-hour-rescue-102137423.html)
- University of Tasmania：[Teamwork down to the wire](https://www.utas.edu.au/about/news-and-stories/articles/2025/teamwork-down-to-the-wire)
- Australasian College of Paramedicine：[Patient-centred team-based critical care in austere environments](https://paramedics.org/news/patient-centred-team-based-critical-care-in-austere-environments)
- Pulse Tasmania：[Tasmanian doctor receives prestigious Lithuanian award](https://pulsetasmania.com.au/news/tasmanian-doctor-receives-prestigious-lithuanian-award-for-dramatic-river-leg-amputation/)
- Amputee Store：[Rafter Trapped in Rapids Saved by Underwater Amputation](https://amputeestore.com/blogs/amputee-life/franklin-river-raft-rescue-valdas-bieliauskas)
- 15min.lt：[Gelbėjimo operacija – 23 valandos, 7 sraigtasparniai](https://www.15min.lt/gyvenimas/naujiena/keliones/gelbejimo-operacija-23-valandos-7-sraigtasparniai-tragiska-nelaime-australijoje-patyres-ir-kojos-netekes-lietuvis-grizo-namo-1630-2385332)
- LRT：[Tasmanijoje kojos netekęs keliautojas](https://www.lrt.lt/lituanica/aktualijos/751/2471538/tasmanijoje-kojos-netekes-keliautojas-gelbetojai-pasake-arba-koja-arba-cia-ir-liksi)
- Australian of the Year：[2026 Australians of the Year for Tasmania announced](https://australianoftheyear.org.au/news-and-media/news/article/2026-australians-year-tasmania-announced)
- Parliamentary Education Office：[High Court rules on the Franklin Dam Case](https://peo.gov.au/understand-our-parliament/history-of-parliament/history-milestones/australian-parliament-history-timeline/events/high-court-rules-on-the-franklin-dam-case)
