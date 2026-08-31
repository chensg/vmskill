# -*- coding: utf-8 -*-
"""发布文案：出模板 + 量截断位置。

  python publish.py new  [片名]      # 打印一份 发布文案.md 的骨架（中英两份）
  python publish.py check 发布文案.md # 量每个平台的标题会被切在哪儿
  python publish.py check 发布文案.md --mono   # 只有中文的老片子用这个
  python publish.py limits           # 打印当前配置的各平台长度

**这个脚本只做一件能量的事：标题在各平台被切在第几个字。**
标题写得好不好、关键词选得对不对，量不出来，那是 references/publishing.md 的事。

为什么这一条值得量：同一句话在小红书切在第 20 字、在抖音的 feed 里切在第 22 字、
在 YouTube 能留到 100 字。一句在这里刚好的标题，换个平台会被切在最不该切的地方 ——
而这件事你在自己电脑上看文案时**完全看不出来**，要发出去才发现。

**关键词（tags）**：YouTube 后台有一栏 tags，**和描述里的 #hashtag 是两回事**。
它是检索入口，全片一份、不分语言，上限 500 字符。`check` 默认要求有 `- 标签：` 那一行。
留空不会报错、不会少发一个字，只是这支片子在搜索里少了一整个入口 —— 典型的静默损失。

**双语**：片子做了中英双音轨，发布文案就得有英文那一份 —— 观众能切英文音轨，
但标题简介还是中文，等于这条轨没人找得到。所以 `check` **默认要求**有
`## YouTube (EN)` 这一块；只有中文的老片子加 `--mono`。
英文那一块另外验两件中文块不验的：**标题里不能混中文**（写了一半忘了译，
自己读的时候完全看不出来），以及**AI 生成声明也得有英文的**。
"""
import io
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 平台长度。**这些数字会变，发之前核一次**，改这里就行。
#   hard  = 输入框的上限，超了打不进去
#   feed  = 列表页/推荐流里大约切在第几个字 —— **真正要紧的是这个**
#   body  = 简介/正文上限
#   tags  = 话题/标签个数上限
PLATFORMS = [
    # 名称           hard  feed  body   tags  备注                                    语言
    ("小红书",         20,   20,  1000,   10, "标题短得多，书名常常放不进去，就放正文第一行", "zh"),
    ("抖音",           55,   22,   55,    None, "标题和话题共用一栏，话题也吃字数", "zh"),
    ("B站",            80,   40,  2000,   10, "标签是独立字段，不占简介", "zh"),
    ("YouTube",       100,   45,  5000,  None, "描述前 2~3 行会显示在播放器下方，其余要点开", "zh"),
    # YouTube 的多语言标题/简介：中英各填一份，观众切到英文音轨时看到的是这一份。
    # hard 还是 100 个字符（平台按字符算，和语言无关），但 feed 里英文能显示得多些。
    ("YouTube (EN)", 100,   70,  5000,  None, "英文标题，配英文音轨；hard 仍是 100 字符", "en"),
]
UNVERIFIED = {"抖音", "YouTube (EN)"}   # 没在真机上比过的，报告里会标出来

# YouTube 的 tags（关键词）字段。**不是描述里的 #hashtag。**
#   - 总长按 `a, b, c` 拼起来算，上限 500 字符。**超了是整条丢掉，不是截断**
#   - 单个词太长检索不到；30 字符是个保守的上限
#   - 全片一份，不分语言 —— YouTube 的 tags 不做本地化，中英文可以混着放
YT_KEYWORDS_MAX = 500
YT_KEYWORD_MAX = 30
YT_KEYWORDS_MIN = 8        # 少于这个数只提示，不拦
CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\u3000-\u303f\uff00-\uffef]")


def limits():
    print("")
    print("=== 各平台长度（配置值，**发之前核一次**）===")
    print("  %-13s %6s %6s %7s %6s  %s"
          % ("平台", "上限", "feed切", "正文", "标签", "备注"))
    for name, hard, feed, body, tags, note, _lang in PLATFORMS:
        mark = " *" if name in UNVERIFIED else ""
        print("  %-13s %6d %6d %7d %6s  %s%s"
              % (name, hard, feed, body, tags if tags else "—", note, mark))
    print("")
    print("  * = 没在真机上比过，是按常见版式估的。核过之后把这行的星号去掉。")


def parse(path):
    """从 发布文案.md 里读出 {平台: {"titles":[...], "tags":[...], "body":n}}。

    认的是这三种行（其余当正文）：
        ## <平台名>
        - 标题：xxx        （可以有多条）
        - 话题：#a #b #c

    **平台名按整行认，不是按第一个空白之前那一段。** 原来用 `(\\S+)` 取到的是
    "YouTube (EN)" 的 "YouTube" —— 于是英文那一块被并进中文块，两块的标题混在一起量，
    而报告看上去一切正常。这类错的形状是"少量到一块"，不是"报错"。
    """
    out, cur = {}, None
    body_chars = 0
    names = [p[0] for p in PLATFORMS]
    for raw in io.open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if cur:
                out[cur]["body"] = body_chars
            name = m.group(1)
            cur = name if name in names else None
            body_chars = 0
            if cur:
                out[cur] = {"titles": [], "tags": [], "body": 0}
            continue
        if not cur:
            continue
        mt = re.match(r"^[-*]\s*标题[：:]\s*(.+?)\s*$", line)
        if mt:
            out[cur]["titles"].append(mt.group(1))
            continue
        mg = re.match(r"^[-*]\s*话题[：:]\s*(.+?)\s*$", line)
        if mg:
            out[cur]["tags"] = re.findall(r"#\S+", mg.group(1))
            continue
        # **列表项一律是注释，不是正文。** 第一版把「- 推荐用第 1 条，因为…」
        # 算进了正文字数，抖音（正文上限 55）当场被这一行顶爆 —— 假警。
        # 正文是散文行，注释是列表项，按这个分就干净了。
        if re.match(r"^[-*]\s", line):
            continue
        body_chars += len(line)
    if cur:
        out[cur]["body"] = body_chars
    return out


def _split_tags(s):
    return [x.strip().lstrip("#") for x in re.split(r"[,，、]", s) if x.strip()]


def parse_keywords(path):
    """读 `- 标签：a, b, c`，**带续行**。

    和 `- 话题：` 分开认：话题是写进描述里的 #hashtag，标签是后台那一栏，
    两者的上限和作用都不同，混在一起量就两边都量不准。

    **续行必须认。** 上限 500 字符的一行在任何编辑器里都会折。只认第一行的话，
    你写 22 个、它数 6 个、然后**报「自检通过」** —— 不报错、不崩，
    只是发出去少了十六个词。这一条在《四十二年》上真发生过。

    续行的判据：有缩进、非空、且不是新的列表项 / 标题 / 括注。
    """
    out, in_block = [], False
    for raw in io.open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        m = re.match(r"^[-*]\s*标签[：:]\s*(.*?)\s*$", line)
        if m:
            in_block = True
            out += _split_tags(m.group(1))
            continue
        if in_block:
            if (not line.strip()) or (not line[:1].isspace()) \
                    or re.match(r"^\s*[-*#（(]", line):
                in_block = False
                continue
            out += _split_tags(line)
    return out


def check(path, bilingual=True):
    """bilingual=False 时跳过英文那些块（只有中文的老片子）。

    **默认要求双语**：从"每支片子都出中英双音轨"那天起，只有中文标题的
    发布文案就是漏了一半 —— 而漏掉的那一半恰恰是给听英文轨的人看的。
    """
    if not os.path.exists(path):
        sys.exit("!!! 找不到 %s" % path)
    data = parse(path)
    limit = {p[0]: p for p in PLATFORMS}
    bad, warn, counted = [], [], 0
    plats = [p for p in PLATFORMS if bilingual or p[6] == "zh"]

    print("")
    print("=== 标题会被切在哪儿%s ===" % ("" if bilingual else "（--mono：只看中文块）"))
    for name, _, _, _, _, _, lang in plats:
        d = data.get(name)
        if not d:
            (bad if lang == "en" else warn).append(
                "%s：文档里没有这一块 —— 没量到，不算通过%s"
                % (name, "。片子有英文音轨就必须有英文标题简介，"
                         "否则听英文的人根本找不到这支片子" if lang == "en" else ""))
            continue
        if not d["titles"]:
            (bad if lang == "en" else warn).append(
                "%s：这一块里一条『- 标题：』都没有 —— 没量到，不算通过" % name)
            continue
        hard, feed, body, tags, _ = limit[name][1:6]
        print("\n  【%s】上限 %d / feed 约切在 %d%s"
              % (name, hard, feed, "  （长度未核实）" if name in UNVERIFIED else ""))
        for tt in d["titles"]:
            counted += 1
            n = len(tt)
            if n > hard:
                bad.append("%s 的标题 %d 字，超过输入框上限 %d：『%s』" % (name, n, hard, tt))
                flag = "  << 打不进去"
            elif n > feed:
                flag = "  << feed 里会切成『%s…』" % tt[:feed]
                warn.append("%s 的标题 %d 字，feed 里只看得到前 %d 字：『%s…』"
                            % (name, n, feed, tt[:feed]))
            else:
                flag = "  ✓"
            # 英文块里混着中文 = 有一句忘了译。自己读的时候完全看不出来，
            # 因为两种语言你都读得懂 —— 只有量一遍才发现。
            if lang == "en" and CJK.search(tt):
                bad.append("%s 的标题里还有中文：『%s』—— 这一块是给英文观众看的"
                           % (name, tt))
                flag = "  << 还没译"
            print("    %2d 字  %s%s" % (n, tt, flag))
        if tags and len(d["tags"]) > tags:
            bad.append("%s 的话题 %d 个，超过上限 %d" % (name, len(d["tags"]), tags))
        if d["body"] > body:
            bad.append("%s 的正文约 %d 字，超过上限 %d" % (name, d["body"], body))
        print("    话题 %d 个%s，正文约 %d 字（上限 %d）"
              % (len(d["tags"]), "" if not tags else "/%d" % tags, d["body"], body))

    # ---- YouTube 关键词（独立字段）----
    kw = parse_keywords(path)
    print("")
    print("=== YouTube 关键词（后台独立字段，不是描述里的 #hashtag）===")
    if not kw:
        bad.append("文档里没有『- 标签：』那一行 —— YouTube 的 tags 是独立于描述的一栏，"
                   "留空不报错也不少发字，只是白丢一个检索入口")
        print("  没有。**不算通过。**")
    else:
        joined = ", ".join(kw)
        print("  %d 个，拼起来 %d 字符（上限 %d）"
              % (len(kw), len(joined), YT_KEYWORDS_MAX))
        print("  " + joined[:200] + ("…" if len(joined) > 200 else ""))
        if len(joined) > YT_KEYWORDS_MAX:
            bad.append("关键词拼起来 %d 字符，超过上限 %d —— **超出的部分是整条丢掉，不是截断**"
                       % (len(joined), YT_KEYWORDS_MAX))
        for k in kw:
            if len(k) > YT_KEYWORD_MAX:
                bad.append("关键词『%s』%d 字符，单个超过 %d —— 太长的词没人会搜"
                           % (k, len(k), YT_KEYWORD_MAX))
        if len(kw) < YT_KEYWORDS_MIN:
            warn.append("关键词只有 %d 个，建议 %d 个以上（这一栏不占描述字数，写满没有代价）"
                        % (len(kw), YT_KEYWORDS_MIN))

    # 全文必须出现的几项（荐书片/生成画面的片子）
    text = io.open(path, encoding="utf-8").read()
    if not re.search(r"AI\s*生成|人工智能生成|AIGC", text):
        bad.append("全文没有一句『画面为 AI 生成』—— 画面是 AI 生成的，多个平台要求标注")
    # 声明也要有英文的：YouTube 的英文简介里没有，等于对英文观众没声明过。
    if bilingual and not re.search(r"AI[- ]?generated|generated (?:by|with) AI|AIGC",
                                   text, re.I):
        bad.append("全文没有一句英文的 AI 生成声明（AI-generated …）—— "
                   "英文简介里没有，就等于对英文观众没有声明过")

    print("")
    if counted == 0:
        # **没量到 = 不算通过。** 一个在空文档上打印"全部通过"的检查等于没有检查。
        print("!! 一条标题都没量到 —— 不算通过。检查 `- 标题：` 这一行的写法")
        return False
    for w in warn:
        print("提示: " + w)
    if bad:
        print("\n!! 问题 %d 条:" % len(bad))
        for b in bad:
            print("   - " + b)
        return False
    print("自检通过（量了 %d 条标题）。" % counted)
    return True


def selftest():
    """回归：造一个超长标题，检查必须报警；空文档必须报『没量到』。"""
    import tempfile
    ok = True
    d = tempfile.mkdtemp()
    # 每个用例只该验它自己那一件事。少了这一行，新加的关键词检查会把下面几条
    # **为别的理由**弄错的用例一起带响 —— 看着还是「报警了」，验的却已不是原来那件事。
    KW = "- 标签：a1, b2, c3, d4, e5, f6, g7, h8\n"

    p1 = os.path.join(d, "over.md")
    io.open(p1, "w", encoding="utf-8").write(
        KW + "## 小红书\n- 标题：" + "字" * 40 + "\n- 话题：#a\n正文\nAI 生成\n")
    r1 = check(p1, bilingual=False)   # 只验字数，用 --mono 把双语那几条隔开
    print("回归自测: 40 字标题塞进小红书(上限20) → %s" % ("报警了，对" if not r1 else "**检查失效了**"))
    ok = ok and (not r1)

    p2 = os.path.join(d, "empty.md")
    io.open(p2, "w", encoding="utf-8").write("# 空文档\n随便写点什么\nAI 生成\n")
    r2 = check(p2, bilingual=False)
    print("回归自测: 空文档 → %s" % ("报『没量到』，对" if not r2 else "**静默放行了**"))
    ok = ok and (not r2)

    FULL = (KW
            + "## 小红书\n- 标题：十八个字刚好放得下的标题\n- 话题：#a #b\n正文\n"
            "## 抖音\n- 标题：二十二字以内\n- 话题：#a\n"
            "## B站\n- 标题：正常长度的标题\n- 话题：#a\n"
            "## YouTube\n- 标题：一个正常长度的中文标题\n- 话题：#a\n"
            "## YouTube (EN)\n- 标题：A normal English title\n- 话题：#a\n"
            "片中画面为 AI 生成。Visuals are AI-generated.\n")

    p3 = os.path.join(d, "ok.md")
    io.open(p3, "w", encoding="utf-8").write(FULL)
    r3 = check(p3)
    print("回归自测: 五个块都在限内 → %s" % ("通过，对" if r3 else "**误报了**"))
    ok = ok and r3

    p4 = os.path.join(d, "noai.md")
    io.open(p4, "w", encoding="utf-8").write(
        KW + "## 小红书\n- 标题：短标题\n- 话题：#a\n正文\n")
    r4 = check(p4, bilingual=False)   # 验的是中文那句声明
    print("回归自测: 没写 AI 生成声明 → %s" % ("报警了，对" if not r4 else "**漏了**"))
    ok = ok and (not r4)

    p5 = os.path.join(d, "note.md")
    io.open(p5, "w", encoding="utf-8").write(
        KW + "## 抖音\n- 标题：短标题 #a\n- 话题：#a\n"
        "- 推荐用第 1 条，因为：" + "理" * 80 + "\n"
        "片中画面为 AI 生成。\n")
    r5 = check(p5, bilingual=False)   # 验的是"列表项不算正文"
    print("回归自测: 80 字的『推荐』注释（抖音正文上限 55）→ %s"
          % ("不算进正文，对" if r5 else "**又把注释当正文了**"))
    ok = ok and r5

    # ---- 双语那几条 ----
    p6 = os.path.join(d, "noen.md")
    io.open(p6, "w", encoding="utf-8").write(
        FULL.replace("## YouTube (EN)\n- 标题：A normal English title\n- 话题：#a\n", ""))
    r6 = check(p6)
    print("回归自测: 缺 YouTube (EN) 整块 → %s" % ("报警了，对" if not r6 else "**放行了**"))
    ok = ok and (not r6)
    r6b = check(p6, bilingual=False)
    print("回归自测: 同一份文档加 --mono → %s" % ("通过，对" if r6b else "**--mono 没生效**"))
    ok = ok and r6b

    p7 = os.path.join(d, "notrans.md")
    io.open(p7, "w", encoding="utf-8").write(
        FULL.replace("- 标题：A normal English title", "- 标题：忘了译的中文标题"))
    r7 = check(p7)
    print("回归自测: 英文块里留着中文标题 → %s" % ("报警了，对" if not r7 else "**看不出来**"))
    ok = ok and (not r7)

    p8 = os.path.join(d, "noenai.md")
    io.open(p8, "w", encoding="utf-8").write(
        FULL.replace("Visuals are AI-generated.", ""))
    r8 = check(p8)
    print("回归自测: 只有中文的 AI 声明 → %s" % ("报警了，对" if not r8 else "**漏了**"))
    ok = ok and (not r8)

    p9 = os.path.join(d, "merged.md")
    io.open(p9, "w", encoding="utf-8").write(
        FULL.replace("- 标题：A normal English title", "- 标题：" + "A" * 130))
    r9 = check(p9)
    print("回归自测: 英文块 130 字符标题（上限 100）→ %s"
          % ("报警了，对 —— 说明两个 YouTube 块没被并成一块"
             if not r9 else "**被并进中文块了**"))
    ok = ok and (not r9)

    # ---- 关键词那几条 ----
    p10 = os.path.join(d, "nokw.md")
    io.open(p10, "w", encoding="utf-8").write(FULL.replace(KW, ""))
    r10 = check(p10)
    print("回归自测: 没有『- 标签：』那一行 → %s" % ("报警了，对" if not r10 else "**放行了**"))
    ok = ok and (not r10)

    p11 = os.path.join(d, "kwlong.md")
    io.open(p11, "w", encoding="utf-8").write(
        FULL.replace(KW, "- 标签：" + ", ".join("kw%02d" % i for i in range(120)) + "\n"))
    r11 = check(p11)
    print("回归自测: 关键词拼起来超 %d 字符 → %s"
          % (YT_KEYWORDS_MAX, "报警了，对" if not r11 else "**没量总长**"))
    ok = ok and (not r11)

    p13 = os.path.join(d, "kwwrap.md")
    io.open(p13, "w", encoding="utf-8").write(FULL.replace(
        KW, "- 标签：a1, b2, c3, d4,\n  e5, f6, g7, h8, i9\n\n（括注不该被吃进去）\n"))
    got = len(parse_keywords(p13))
    print("回归自测: 标签行折成两行 → 数到 %d 个 —— %s"
          % (got, "对，续行认了" if got == 9 else "**只认第一行，静默漏掉后面的**"))
    ok = ok and got == 9

    p12 = os.path.join(d, "kwwide.md")
    io.open(p12, "w", encoding="utf-8").write(
        FULL.replace(KW, "- 标签：ok1, " + "x" * (YT_KEYWORD_MAX + 5) + ", ok2\n"))
    r12 = check(p12)
    print("回归自测: 单个关键词超 %d 字符 → %s"
          % (YT_KEYWORD_MAX, "报警了，对" if not r12 else "**只量了总长没量单个**"))
    ok = ok and (not r12)

    print("\n回归自测总体: %s" % ("通过" if ok else "**有失效的检查**"))
    return ok


TEMPLATE = """# 《%s》发布文案

> 交付物之一。**每一块都是复制粘贴就能用的成品**，不是"建议围绕 XX 展开"。
> 写完跑一次：`python publish.py check 发布文案.md`

## 通用（每个平台都要出现，放正文里）

- 书名 / 作者 / 出版年：
- **片中画面为 AI 生成。**
- **Visuals in this video are AI-generated.**（英文简介里也要有，不能只有中文）
- 配乐来源（`MUSIC_MODE` 是 public_domain 时必填）：
- 素材来源与授权（`IMG_SOURCE` 是 found 时贴 `credits` 导出的表）：
- 音轨：中文 / English（`LANGS` 有两条时，简介里说一句怎么切音轨 ——
  多数观众不知道 YouTube 有这个菜单）

## 小红书

- 标题：
- 标题：
- 推荐用第 1 条，因为：
- 话题：#
（正文，前两行是钩子）

## 抖音

- 标题：
- 标题：
- 推荐用第 1 条，因为：
- 话题：#

## B站

- 标题：
- 标题：
- 推荐用第 1 条，因为：
- 话题：#
（简介）

## YouTube

- 标题：
- 标题：
- 推荐用第 1 条，因为：
- 话题：#
（描述，前 2~3 行会显示在播放器下方）

## YouTube (EN)

- 标题：
- 标题：
- 推荐用第 1 条，因为：
- 话题：#
（English description. 这一块整块都用英文，包括 AI-generated 声明。
 **不是把中文标题直译** —— 中文标题的钩子常常靠成语和语序，直译过去是平的。
 同一个悬念用英文重写一遍。）

## 标签（YouTube 关键词，全片一份，不分语言）

- 标签：

（这一栏在 YouTube 后台是**独立字段**，不是描述里的 #hashtag。
 上限 500 字符，按 `a, b, c` 拼起来算；单个词别超过 30 字符。
 中英文可以混着放——它服务的是检索，不是阅读。
 写满没有代价：它不占描述的字数。）

## 不要做的

- 标题剧透第三幕的反转
- 把片里明确标为「假说」的东西写成结论
- 堆不相关的热词（推荐系统会把片子投给不看这类内容的人，完播率更差）
- 英文那一块留着中文没译（`check` 会拦，但它只看得见标题行）
"""


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "limits"
    if what == "limits":
        limits()
    elif what == "new":
        print(TEMPLATE % (sys.argv[2] if len(sys.argv) > 2 else "片名"))
    elif what == "check":
        if len(sys.argv) < 3:
            sys.exit("用法: python publish.py check 发布文案.md [--mono]")
        sys.exit(0 if check(sys.argv[2], "--mono" not in sys.argv) else 1)
    elif what == "selftest":
        sys.exit(0 if selftest() else 1)
    else:
        sys.exit("不认识的命令 %r，只有 new / check / limits / selftest" % what)
