# -*- coding: utf-8 -*-
"""发布文案：出模板 + 量截断位置。

  python publish.py new  [片名]      # 打印一份 发布文案.md 的骨架
  python publish.py check 发布文案.md # 量每个平台的标题会被切在哪儿
  python publish.py limits           # 打印当前配置的各平台长度

**这个脚本只做一件能量的事：标题在各平台被切在第几个字。**
标题写得好不好、关键词选得对不对，量不出来，那是 references/publishing.md 的事。

为什么这一条值得量：同一句话在小红书切在第 20 字、在抖音的 feed 里切在第 22 字、
在 YouTube 能留到 100 字。一句在这里刚好的标题，换个平台会被切在最不该切的地方 ——
而这件事你在自己电脑上看文案时**完全看不出来**，要发出去才发现。
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
    # 名称        hard  feed  body   tags  备注
    ("小红书",      20,   20,  1000,   10, "标题短得多，书名常常放不进去，就放正文第一行"),
    ("抖音",        55,   22,   55,    None, "标题和话题共用一栏，话题也吃字数"),
    ("B站",         80,   40,  2000,   10, "标签是独立字段，不占简介"),
    ("YouTube",    100,   45,  5000,  None, "描述前 2~3 行会显示在播放器下方，其余要点开"),
]
UNVERIFIED = {"抖音"}          # 没在真机上比过的，报告里会标出来


def limits():
    print("")
    print("=== 各平台长度（配置值，**发之前核一次**）===")
    print("  %-8s %6s %6s %7s %6s  %s" % ("平台", "上限", "feed切", "正文", "标签", "备注"))
    for name, hard, feed, body, tags, note in PLATFORMS:
        mark = " *" if name in UNVERIFIED else ""
        print("  %-8s %6d %6d %7d %6s  %s%s"
              % (name, hard, feed, body, tags if tags else "—", note, mark))
    print("")
    print("  * = 没在真机上比过，是按常见版式估的。核过之后把这行的星号去掉。")


def parse(path):
    """从 发布文案.md 里读出 {平台: {"titles":[...], "tags":[...], "body":n}}。

    认的是这三种行（其余当正文）：
        ## <平台名>
        - 标题：xxx        （可以有多条）
        - 话题：#a #b #c
    """
    out, cur = {}, None
    body_chars = 0
    for raw in io.open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        m = re.match(r"^##\s+(\S+)", line)
        if m:
            if cur:
                out[cur]["body"] = body_chars
            name = m.group(1)
            cur = name if any(name == p[0] for p in PLATFORMS) else None
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


def check(path):
    if not os.path.exists(path):
        sys.exit("!!! 找不到 %s" % path)
    data = parse(path)
    limit = {p[0]: p for p in PLATFORMS}
    bad, warn, counted = [], [], 0

    print("")
    print("=== 标题会被切在哪儿 ===")
    for name, _, _, _, _, _ in PLATFORMS:
        d = data.get(name)
        if not d:
            warn.append("%s：文档里没有这一块 —— 没量到，不算通过" % name)
            continue
        if not d["titles"]:
            warn.append("%s：这一块里一条『- 标题：』都没有 —— 没量到，不算通过" % name)
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
            print("    %2d 字  %s%s" % (n, tt, flag))
        if tags and len(d["tags"]) > tags:
            bad.append("%s 的话题 %d 个，超过上限 %d" % (name, len(d["tags"]), tags))
        if d["body"] > body:
            bad.append("%s 的正文约 %d 字，超过上限 %d" % (name, d["body"], body))
        print("    话题 %d 个%s，正文约 %d 字（上限 %d）"
              % (len(d["tags"]), "" if not tags else "/%d" % tags, d["body"], body))

    # 全文必须出现的几项（荐书片/生成画面的片子）
    text = io.open(path, encoding="utf-8").read()
    for key, why in (("AI", "画面是 AI 生成的，多个平台要求标注"),):
        if not re.search(r"AI\s*生成|人工智能生成|AIGC", text):
            bad.append("全文没有一句『画面为 AI 生成』—— %s" % why)

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

    p1 = os.path.join(d, "over.md")
    io.open(p1, "w", encoding="utf-8").write(
        "## 小红书\n- 标题：" + "字" * 40 + "\n- 话题：#a\n正文\nAI 生成\n")
    r1 = check(p1)
    print("回归自测: 40 字标题塞进小红书(上限20) → %s" % ("报警了，对" if not r1 else "**检查失效了**"))
    ok = ok and (not r1)

    p2 = os.path.join(d, "empty.md")
    io.open(p2, "w", encoding="utf-8").write("# 空文档\n随便写点什么\nAI 生成\n")
    r2 = check(p2)
    print("回归自测: 空文档 → %s" % ("报『没量到』，对" if not r2 else "**静默放行了**"))
    ok = ok and (not r2)

    p3 = os.path.join(d, "ok.md")
    io.open(p3, "w", encoding="utf-8").write(
        "## 小红书\n- 标题：十八个字刚好放得下的标题\n- 话题：#a #b\n正文\n"
        "## 抖音\n- 标题：二十二字以内\n- 话题：#a\n"
        "## B站\n- 标题：正常长度的标题\n- 话题：#a\n"
        "## YouTube\n- 标题：A normal title\n- 话题：#a\n"
        "片中画面为 AI 生成。\n")
    r3 = check(p3)
    print("回归自测: 四个平台都在限内 → %s" % ("通过，对" if r3 else "**误报了**"))
    ok = ok and r3

    p4 = os.path.join(d, "noai.md")
    io.open(p4, "w", encoding="utf-8").write(
        "## 小红书\n- 标题：短标题\n- 话题：#a\n正文\n")
    r4 = check(p4)
    print("回归自测: 没写 AI 生成声明 → %s" % ("报警了，对" if not r4 else "**漏了**"))
    ok = ok and (not r4)

    p5 = os.path.join(d, "note.md")
    io.open(p5, "w", encoding="utf-8").write(
        "## 抖音\n- 标题：短标题 #a\n- 话题：#a\n"
        "- 推荐用第 1 条，因为：" + "理" * 80 + "\n"
        "片中画面为 AI 生成。\n")
    r5 = check(p5)
    print("回归自测: 80 字的『推荐』注释（抖音正文上限 55）→ %s"
          % ("不算进正文，对" if r5 else "**又把注释当正文了**"))
    ok = ok and r5

    print("\n回归自测总体: %s" % ("通过" if ok else "**有失效的检查**"))
    return ok


TEMPLATE = """# 《%s》发布文案

> 交付物之一。**每一块都是复制粘贴就能用的成品**，不是"建议围绕 XX 展开"。
> 写完跑一次：`python publish.py check 发布文案.md`

## 通用（每个平台都要出现，放正文里）

- 书名 / 作者 / 出版年：
- **片中画面为 AI 生成。**
- 配乐来源（`MUSIC_MODE` 是 public_domain 时必填）：
- 素材来源与授权（`IMG_SOURCE` 是 found 时贴 `credits` 导出的表）：

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

## 不要做的

- 标题剧透第三幕的反转
- 把片里明确标为「假说」的东西写成结论
- 堆不相关的热词（推荐系统会把片子投给不看这类内容的人，完播率更差）
"""


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "limits"
    if what == "limits":
        limits()
    elif what == "new":
        print(TEMPLATE % (sys.argv[2] if len(sys.argv) > 2 else "片名"))
    elif what == "check":
        if len(sys.argv) < 3:
            sys.exit("用法: python publish.py check 发布文案.md")
        sys.exit(0 if check(sys.argv[2]) else 1)
    elif what == "selftest":
        sys.exit(0 if selftest() else 1)
    else:
        sys.exit("不认识的命令 %r，只有 new / check / limits / selftest" % what)
