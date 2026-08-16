# 找图与生成图

十几张图是这条流水线里最花时间、也最容易返工的一环。
脚本里的 `IMG_SOURCE` 有两个值：

- **`generated`（默认）** —— 写一份自包含的出图任务书交给用户去生成。
  这一篇的前半（共用的硬要求、五个画种的风格前缀）说的就是这条路。
- **`found`** —— 自己去找现成的：公版开放数据、图库实拍。见下面
  「自己去找图」那一节。**它不是省事的那一条，是方向相反的那一条。**

## 通用的硬要求

不管走哪条路，每张图都要满足：

1. **分辨率：跑 `budget` 算，不要写死一个数。**
   以前这里写的是"一律 `2896 x 5152`"，那是**两头都错**的：
   对缓推镜多买一倍多的像素，对大推镜又不够（而当时的 flat 判据还会放行）。

   尺寸是算得出来的：`需要的源图短边 = pp目标 × 这一镜最紧的 z × 1080`。

   | | pp 目标 | 依据 |
   |---|---|---|
   | 静帧镜 | **1.00** | pp=1.0 时裁出来正好等于输出尺寸，是恒等重采样，不过滤波器 |
   | 运镜镜 | **1.20** | 实测保住 98% 的顶层细节，性价比最高的一档 |
   | 细节就是内容的镜 | **1.30** | 实测 99%。人脸特写、工笔织物、市井细节、封面 |

   **实测曲线**（两张真原生图库照片，一密一疏，同一镜头走完整流水线，
   量落幅帧的最高倍频程）：

   | pp | 0.70 | 0.85 | 1.00 | 1.20 | 1.30 | 1.45 |
   |---|---|---|---|---|---|---|
   | 保住的顶层细节 | 67% | 83% | 92% | 98% | 99% | 100% |

   两条曲线几乎重合——**拐点和画面类型无关**。画面类型改的不是尺寸，
   是"最后那几个百分点值不值得买"。

   **上限是 PREP，不是钱包。** `prep` 第一步就 `scale` 到 PREP（竖横版短边都是 2160），
   源图短边超过 2160 的部分**在流水线第一步就被丢掉**。要 2896 等于交给流水线 2160，
   白付 26% 的线性分辨率、45% 的像素。跑一次 `budget` 就都算好了：

   ```bash
   python make_v.py budget
   ```

   它按镜打出需要的尺寸，并分档汇总——**出图任务书直接抄那张分档表**。
   实测在两支已交付的片子上，按镜要比统一 2896 省 60%~63% 的像素。

   还要注意两件事：生成器出不了 9:16 时要再除裁切损失（出 2:3 裁 9:16 只剩 84%）；
   `CLIPS` 的 `zoom` 是事后再裁一刀，`budget` 已经帮你折回去了。
2. **字幕区要干净**：竖版是右侧约四分之一，横版是底部约五分之一。
   **"干净"是留白还是留暗，取决于画种**——见下面那一节，弄反了整批要重出。
3. **要整条从画顶浅（暗）到画底，不只是某一段。** 镜头是动的，摇镜会把字幕拖过
   明暗分界。有一张右侧在地平线以上是干净的浅色天、以下是画满细密浪纹的海，
   起幅时字幕干净，下摇到末尾就糊进浪里了（实测框内最暗从 132 掉到 36）。
4. **上下（横版是左右）都要有内容**：运镜的落幅不能停在一片没有明暗变化的区域。
5. **主体不顶满画框**：四边各留约 10% 给推拉平移。
6. **不要自带文字、印章、签名、水印**、匾额、招幌、旗子上的字、船身编号。
   诗句由脚本用楷体排上去；印章生成出来一律是乱码。

## 风格统一的唯一保证：共用风格前缀

**每张提示词都由「共用风格前缀 + 这一镜的画面描述」组成，前缀一字不改。**
分开生成最容易失守的就是这里——纸纹、墨色浓淡、色调会慢慢漂。

前缀里要把上面那几条硬要求都写进去。这是有意的：写在前缀里，每一张都会遵守。

**下面四段前缀里的 `{W} x {H}` 是占位符，按 `budget` 分档表逐镜填**，
不要再填一个统一的 4K 数字——原因见上面第 1 条。同一档的几镜共用同一个数，
所以实际上只有三四个不同的值要填。

**后续每一张都要把第一张样图当参考图传进去**——文字描述锁不住笔性和长相，
参考图能。有反复出现的角色时（写实版的男女主）这一条是硬性的。

---

## 一、水墨淡彩（宣纸）

题材苍茫、写景写志的（《登高》《观沧海》这类）。

```
Traditional Chinese ink-wash landscape painting (水墨淡彩, light-colour shuimo) on
textured xuan paper. Autumn daylight under a pale overcast sky — this is NOT a night
scene: no moon, no stars, no deep blue. Restricted palette: ink black and grey washes,
ochre-brown for dry autumn foliage, muted indigo-grey for water and distant hills, and
large areas of bare unpainted paper for sky and mist. Loose expressive brushwork,
wet-into-wet washes, generous negative space, visible paper grain. Vertical 9:16,
full-bleed, {W} x {H}. Keep the right quarter of the picture pale and quiet — mist or
bare paper, no heavy ink there. Both the top and the bottom of the frame must carry
content; no empty band at either edge. No calligraphy, no seal, no signature, no text,
no border or frame, no scroll edges.
```

## 二、唐风工笔重彩（绢本设色）

题材富丽、写人写花的（《清平调》《丽人行》这类），水墨托不住。
下面这段是《清平调三首》十五张实际用的，**十五张字幕列实测 197~226、零告警**，
可以原样复用，只替换后面的画面描述：

```
Tang-dynasty Chinese court painting in the gongbi heavy-colour manner (工笔重彩),
painted on aged silk: a warm ivory-ochre silk ground with a faintly visible woven
texture showing through everywhere. Fine, confident ink outlines (铁线描) enclosing
every form, then filled with layered graded mineral washes built up in many thin
passes (层层分染) — never flat poster-like fills. Restricted mineral palette:
azurite blue (石青), malachite green (石绿), cinnabar and rouge red (朱砂/胭脂),
ochre earth (赭石), lead white, and thin gold outlining (泥金) used sparingly on
edges and highlights. Opulent, courtly, jewel-like, but held together by the ink
line — decorative rather than photographic, with no cast shadows and no perspective
vanishing point.

The composition is organised so that the colour weight sits in the left two thirds
and the right side breathes. Every large area — sky, cloud, wall, water, silk ground
— must carry visible internal variation from the layered dyeing: gradations, cloud
volume, brick joints, texture. Nothing may be a flat uniform field of one colour.

Vertical 9:16, full-bleed, {W} x {H}. The right quarter of the picture, from the very
top edge to the very bottom edge, must stay pale and quiet — bare silk ground, thin
luminous cloud, mist or very pale distance — with no strong colour, no dark mass, no
dense detail and no subject anywhere in that vertical strip. Both the top and the bottom
of the frame must carry content; no empty band at either edge. Keep the main subject
about one tenth of the frame clear of every edge. Any human figure is seen from
behind or in profile, never a frontal portrait, and facial features are not drawn.
No calligraphy, no seal, no signature, no text, no border or frame, no scroll edges,
no mounting silk.
```

这段里有三处是踩出来的，别删：

- **「右侧留一条素绢」要说成这个画种本来的样子**，不是外加的构图要求。
  唐代绢本设色（《簪花仕女图》《捣练图》）背景本来就是大片空绢、只有主体着色，
  说清楚这一点生成器就照做了，浓艳和留白并不冲突。
- **「每一大片都要有分染的内部变化，不许平涂」**。重彩最容易出大块平色，
  那样落幅就没法走。
- **「凡有人处一律背影或侧影，不画五官」**。一是含蓄合于唐画，
  二是这类诗里的人本来就是被比喻着写的。**注意：写实版要把这一条反过来。**

**夜景要专门交代"淡"**：写成 `a pale, luminous night on silk, never a black one`，
月画成一个描金的素绢圆盘。《清平调》的「瑶台月下」这么写，
字幕底实测 206~210，比白天的镜还亮。

## 三、英式水彩（《再别康桥》用过）

近现代题材、西方场景，水墨那套"苍茫写志"套不上。

```
English watercolour and light wash on cold-pressed rag paper, in the tradition of
Turner and the 1920s Cambridge topographical watercolourists. Wet-in-wet washes with
soft bleeding edges, visible paper grain, generous areas of unpainted paper.
Muted restrained palette: pale ochre, willow green, dove grey, faded rose, soft indigo,
warm sepia. No ink outlines, no heavy impasto, no photographic detail, no digital
sharpness. Soft diffuse English light. Quiet, unhurried, slightly melancholy.
No text, no signature, no seal, no watermark, no lettering of any kind.
The right-hand third of the picture, from the very top edge down to the very bottom
edge, is kept as near-empty pale paper: an unbroken vertical band of the lightest wash,
with no subject, no dark foliage, no strong reflection and no dark shape in it. The
upper half of that band in particular must be the palest, emptiest part of the whole
picture. Any horizon, bank or bridge line that crosses this band must cross it as a
pale, low-contrast edge only.
Vertical 9:16 composition, {W} x {H}.
```

## 四、电影写实（《雨霖铃》用过）——**要求整个反过来**

叙事性强、核心是人脸的（《雨霖铃》这种"帐饮→执手→凝噎→舟行→酒醒"的），
水墨托不住特写，工笔又太富丽压不住秋和雨。用这一套。

代价是**字幕改白字，所以要的不是留白，是留暗**。这条最容易想反，也最贵：
留白事后还能压，**留暗不行**。

```
Photorealistic cinematic film still, 35mm anamorphic, shallow depth of field.
Northern Song dynasty China, eleventh century, late autumn. Naturalistic low-key
lighting — overcast dusk, rain-washed air, only practical light sources such as a
lantern, a candle or the moon. No studio key light, no HDR, no glow filter, no
orange-and-teal look. Muted desaturated palette: ink blue, slate grey, wet dark
stone, weathered bronze, faded celadon, dark willow green, with at most one small
warm accent. Fine natural film grain, gentle halation on the few highlights, real
skin texture, no plastic retouching, no beauty filter. Historically plausible Song
costume — crossed-collar robes, beizi, thin silk gauze, jade and silver ornaments;
not Ming, not Qing, not Japanese, not Korean. The people are young and beautiful in
an unforced, believable way; they are fictional and must not resemble any real or
famous person.

Vertical 9:16 composition, {W} x {H}, full-bleed. The image is dark overall.
A rectangle covering from 55% to 95% of the width and from 10% to 55% of the height
— the upper right of the frame — must be kept DARK, quiet and free of detail: deep
dusk sky, a backlit eave, shadowed water, mist, out-of-focus dark foliage or an
unlit wall. Absolutely no face, no lantern, no candle, no moon, no bright sky, no
water sparkle, no pale fabric and no specular highlight anywhere inside that
rectangle. Place every figure, every face and every pale or bright element in the
left and lower part of the frame. Both the top edge and the bottom edge of the
frame must carry content; no empty band at either edge. Keep the main subject about
one tenth of the frame clear of every edge.
No text, no calligraphy, no signature, no seal, no watermark, no shop sign, no
banner with writing, no lettering of any kind.
```

这段里四处是踩出来的：

- **暗区给的是精确矩形（55%~95% 宽 × 10%~55% 高）**，不是"右上留暗"。
  这个矩形是把十几镜的 zoompan 取景窗反查回原图取并集算出来的，不是拍脑袋。
  做新的一支要重算（`trace` 会打出每一镜实际扫过的范围）。
- **列清楚"不能有什么"**：脸、灯笼、烛火、月亮、亮天、水面反光、浅色衣料、
  密集枝叶、任何镜面高光。只说"要暗"生成器会给你一片有月亮的暗天。
- **还要说清楚"暗成什么样"**。这一条是《青玉案》的诗文页底图踩出来的：
  写「这块保持暗、无细节」，生成器**直接在画面正中涂了一块硬边的纯黑矩形**，
  字落上去就成了个黑框。它没理解错，是照字面执行的。
  正确写法：**「这一块要暗，但必须是画面本身的暗（雾、远墙、水面、屋檐的背光面），
  不能是纯色块，四条边不能有可见的硬边界」**。
  收图时顺手量一下那块的极差——接近 0 就是被涂黑了，不是拍出来的暗。
- **"人物放画面左侧和下部"**要单独说。这在电影构图里本来就常见（人偏左、
  右上留负空间），说了就照做。
- **"虚构人物，不要像任何真人或明星"**。

### 写实版另外三条单独交代

1. **唯一横移的那一镜**，字幕扫过的横向范围宽一倍（《雨霖铃》img04 是原图 x 0.60~0.89），
   暗区要**从画面中线一直铺到右缘**。
2. **有月亮的那一镜，月必须放画面左侧。** 放右上正好落进字幕带，
   而「晓风残月」这种名句重出的代价最大。
3. **诗文页底那一张要求和其余不同**：整张都要暗、都要平，不只是右上——
   八列词文会铺满画心（x 8%~85%、y 22%~82%）。
4. **封面那一张也不同**：标题横跨画心上方，所以**画面上方三分之一整条都要空**，
   人的头顶不要越过画高的 40%。（曾有一支的落款正压在人的头顶上。）

### 写实版一定要量直方图再定调色

生成器交回来的往往是**技术上欠曝**的：《雨霖铃》两张样图实测平均亮度 15/19、
中位数 8/7、最亮只有 133。**不要照抄纸本画种"几乎不调"那条**，
那句 `eq=contrast=1.06:saturation=0.92` 实测把中位数压成了 0。
先量 `mean / p50 / p90 / p99 / max` 再定，做法见 SKILL.md「调色」那一节。

---

## 五、图库实拍

用 `search_stock_media` 检索 Pexels / Unsplash / Pixabay，
它直接返回下载地址、原图尺寸和授权，比开浏览器翻页快得多。

检索词按**画面**写，不要按诗句写。「渚清沙白鸟飞回」搜不到东西，
`river sandbank birds shore autumn overcast` 才搜得到。

**统一调色是必需的，不是锦上添花。** 多个摄影师的照片，白平衡、反差、季节甚至
黑白与彩色都不一样，不重手统一串起来就是 PPT 换页。

### 图库的能力边界（省得白费时间）

- **中年人的疲惫感**。搜"天台独立"出来的大半是屋顶跑酷和蓝天极限运动；
  搜"白发老人"出来的全是西方老年人的正脸棚拍肖像。
- **朴素的静物**。搜酒杯出来的全是烈酒广告——琥珀打光、水晶酒樽。
  绕道搜"药""水杯""窗边"反而能找到朴素的。
- **不艳的秋景**。图库的秋天九成是暴力饱和的金黄红叶。加 overcast、muted、grey，
  并且做好在调色里再压一道的准备。

---

# 自己去找图（`IMG_SOURCE = "found"`）

## 方向是反的，这是最要紧的一句

生成那条路是**图跟着分镜走**：分镜提要求（"右侧留白，从画顶到画底"），
生成器去满足。找图这条路反过来——**分镜跟着图走**。

一张宋画的留白在哪儿是不可能改的；一张老照片的构图、光线、纵横比都定死了。
所以流程要倒过来：

1. 先按题材把候选图捞一批回来，**看过**（不是看描述，看图本身）
2. 看它们各自能承担哪一句，再排分镜——有时候一句诗要迁就一张图，那是对的
3. 定裁切（`zoom` / `cx` / `cy`）。**这一步是找图路线的主要工作量**，
   相当于生成路线里写提示词
4. 跑 `trace` 逐张验字幕底，**`FLIP_SHOTS` 这时会真的用上**——
   十几张来源不同的图不可能有统一的极性

**别指望"统一风格"。** 生成路线靠共用风格前缀锁住笔性；找图路线锁不住，
只能靠两件事补：选图时把画种/年代/媒介限死在一个窄范围里，
以及 `GRADE` 重手统一（和图库实拍那条一样，不做就是 PPT 换页）。

## 分辨率：找图路线最常卡的地方，而静帧模式正是解法

开放数据里的画作和档案照片，裁成 9:16 之后的有效短边很多落在
**1080~1620** 之间——按运镜的 1.5 倍门槛（竖版 1440）会被判死一大半，
而它们做**静帧**完全够用（只需要 `eff/z ≥ 1080`）。

所以找图和静帧是一对：**先看素材实际有多少像素，再决定这一镜运不运镜。**
`check_resolution` 会按每一镜自己的 `MOTION` 分开判，报表里标出是哪一种。

两个连带的坑：

- **网站给的常常是缩过的派生图。** 详情页的大图、API 返回的 `primaryImage`
  可能已经是 1000px 级的派生件，而原始档（IIIF 全尺寸、TIFF 下载）大得多。
  能拿到原始档就拿原始档，别拿网页图凑合。
- **`zoom` 会吃掉有效分辨率。** 从一张横构图里裁 9:16 已经损失一大截，
  再 `zoom=1.3` 收紧就更少。`check_resolution` 算的是裁后、按 `zoom` 收紧后的值，
  以它为准。

## 去哪儿找

**逐件看条款，而且条款会变。** 下面只是常去的地方，不是"这里的都能用"：

| | 有什么 | 注意 |
|---|---|---|
| **The Met Open Access** | 大量藏品图，含中国书画；有 API | 标 CC0 的才是 CC0，馆藏里也有受限件 |
| **Rijksmuseum** | 高清藏品图，有 API | 逐件看权利声明 |
| **Smithsonian Open Access** | CC0 为主，量大 | 同上 |
| **Art Institute of Chicago** | 公版藏品图 + API | 同上 |
| **National Gallery of Art (US)** | 开放获取图像 | 同上 |
| **Getty / NYPL / Library of Congress** | 档案照片、版画、地图 | **权利声明逐件不同**，尤其照片 |
| **Wikimedia Commons** | 极杂，逐文件授权 | 常见 CC-BY-SA（要署名且传染） |
| **台北故宫 Open Data** | 中国书画的开放数据 | 用前读它当下的使用条款 |
| Pexels / Unsplash / Pixabay | 现代实拍，`search_stock_media` 可直接检索 | **免版税不等于公版**，各站条款不同 |

北京故宫的数字文物库等项目**多数只授权在线浏览、不授权二次使用**——
这是判断不是实测，真要用逐件读条款。

## 授权：填不出来就是还没查清楚

`IMG_SOURCE='found'` 时每张图都要在 `CREDITS` 里登记五项，
少一项 `check` 就不让过：

```python
CREDITS = {"img01.png": dict(
    title="谿山行旅图（局部）", holder="国立故宫博物院",
    source="Open Data 專區", license="公有领域",
    url="https://...")}
```

**"公有领域"是对**作品**说的，不一定对**这一张翻拍**成立。**
和配乐那边"录音权与作品权是两回事"完全同构（见 `references/music.md`）。
拿不到明确声明的，换一张有明确 CC0 标注的，比研究保护期便宜得多。

跑 `credits` 导出 `素材来源.md`，**它是交付物的一部分**——
CC-BY 要求署名，署名要跟着片子走。

## 检索词怎么写

和图库那条一样：**按画面写，不要按诗句写。**「渚清沙白鸟飞回」搜不到东西，
`river sandbank birds shore autumn overcast` 才搜得到。
找古画多加媒介和年代：`hanging scroll ink landscape Song dynasty`。

## 验证纪律在这条路上加倍重要

生成路线里图是按你的描述做出来的，"这张是不是我要的"基本不成问题；
找图路线里**每一张都是别人的东西，靠元数据认它必错**。
下面「验证纪律」那一节里九张错三张的教训就是在找图时踩的。

## 古典题材改写现代场景时

分镜表要整个重写，不能拿水墨版那套改。例如《登高》：

| 诗句 | 古典读法 | 现代读法 |
|---|---|---|
| 万里悲秋常作客 | 江边客舟 | 出租屋的窗 / 黄昏的站台 |
| 百年多病独登台 | 独立高台 | 高层落地窗前 / 空旷广场 |
| 艰难苦恨繁霜鬓 | 老者背影 | 鬓角白发的极近景 |
| 潦倒新停浊酒杯 | 案上停杯 | 一杯清水配几粒药 |

最后一行值得单说：「新停浊酒杯」的意思是**戒了**，
所以拍一杯清水加药比拍一杯没动的酒更准——替换本身就是那句诗的意思。

## 图文不强相关时

选图标准从"这句诗画的是什么"变成"这一秒观众该感到什么"：

- 「不尽长江滚滚来」→ 雾霾里排到看不见的高层住宅
- 「艰难苦恨繁霜鬓」→ 地铁站里所有人都糊成一片，只有站着不动的那个是实的
- 「潦倒新停浊酒杯」→ 夜里几百扇亮着的窗，每一扇后面都有一个人

这种做法要有整体的视觉弧线兜住，比如"越走越暗"：高调的白 → 灰 → 落进夜。
没有弧线就会散。

## 验证纪律

**永远不要根据文件名、alt 文本、搜索结果描述或接口返回的元数据判断一张图是什么。**

真实教训：靠读缩略图上叠的编号选图，九张里错了三张——下载回来一张是城堡、
一张是红山茶花、一张是森林。而且尺寸校验全部通过，因为下到的确实是那个 ID 的图，
只是那个 ID 不是看中的那张。

正确做法：

1. 图多的时候先拼一张**联络表**（`hstack` + `vstack` 排成网格）核对序号和画面，
   再单独打开有具体风险的那几张看细节。
   联络表要**带上调色**，否则暗调写实的片子在联络表上全是黑的、什么也看不出来。
2. 图给齐之后**先跑 `trace` 再开渲**——它在出图阶段就能判每张图能不能用，
   比渲完再发现问题便宜得多。缺图会跳过，所以出一张就能验一张。
3. 渲染完成后**抽静帧真正看一眼**——ffmpeg 退出码是 0 不等于画面是对的。
