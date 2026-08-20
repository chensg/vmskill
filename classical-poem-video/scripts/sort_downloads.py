# -*- coding: utf-8 -*-
"""把浏览器下载来的一堆文件归到脚本要找的位置。

  python sort_downloads.py <段目录>            # 看会怎么动，不真动
  python sort_downloads.py <段目录> --apply    # 真动

===== 为什么要这个 =====

《经度》做到第四段，同一套手工动作重复了四次，每次都一样：

1. **旁白 mp3 落在 `素材/` 而不是 `build/vo/`** —— 用户从编辑器批量下载，
   浏览器不知道该分到哪里，全堆在一处。
2. **一大半带着 ` (1)` ` (2)` 后缀** —— 重复下载时浏览器自动加的。
   脚本按精确文件名找，`VO_01a (2).mp3` 等于没下。段四 38 条里有 35 条带后缀。
3. **找来的音效还是站点的原始文件名**（`freesound_community-shroud-wind-wistles-27053.mp3`），
   要改成 SFX 表里写的名字。
4. 试听/废弃的变体混在里面，会被当成正式素材。

这些都不是判断题，是机械动作 —— 而机械动作重复四次就该是脚本。
手工做的问题不在慢，在**每次都要重新想一遍规则，而想漏一条就静默出错**
（带后缀的文件不会报错，它只是"缺素材"）。

===== 它做什么 =====

- `VO_*.mp3` → `build/vo/`，去掉 ` (N)` 后缀
- 试听/试读/废弃 开头的 mp3 → `_废弃试听/`
- 其余 mp3 留在 `素材/`（音效），**但按 SFX_CREDITS 把找来的那些改名**
- `*.png` 留在 `素材/`；如果散落在段目录下则移进 `素材/`
- **撞名一律中止**，不覆盖任何东西

默认只打印计划。加 `--apply` 才真动。
"""
import io
import os
import re
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DISCARD_PREFIXES = ("试听", "试读", "废弃")


def sfx_rename_map(seg_dir):
    """从 build/make_story_h.py 的 SFX_CREDITS 里读出 {站点原始名片段: 目标名}。

    找来的音效下载下来是站点的文件名，而 SFX 表里写的是我们自己的名字。
    两者的桥就在 SFX_CREDITS 的 url 里 —— 那串 slug 通常就在文件名中。
    """
    p = os.path.join(seg_dir, "build", "make_story_h.py")
    if not os.path.exists(p):
        return {}
    src = io.open(p, encoding="utf-8").read()
    m = re.search(r"SFX_CREDITS\s*=\s*\{(.*?)\n\}", src, re.S)
    if not m:
        return {}
    out = {}
    # 结尾那个 `|$` **不是可有可无的**：上面外层正则非贪婪匹配到换行加右花括号，
    # 那个换行被它吃掉了，所以 group(1) 的末尾是 4 个空格加右圆括号加逗号，
    # **后面没有换行**。内层只认换行结尾的话，最后一条永远匹配不上 ——
    # 而 SFX_CREDITS 通常就只有一两条，于是整张映射表恒为空，
    # 脚本一声不吭地什么都不改名：它不报错，只是说「没有要改名的」。
    # 这个坑活了三段没被发现，因为那三次找来的音效都是我手工改的名。
    for blk in re.finditer(r'"([^"]+\.mp3)"\s*:\s*dict\((.*?)\),\s*(?:\n|$)', m.group(1), re.S):
        target, body = blk.group(1), blk.group(2)
        u = re.search(r'url\s*=\s*"([^"]+)"', body)
        if not u:
            continue
        slug = u.group(1).rstrip("/").rsplit("/", 1)[-1]
        # 去掉尾部的数字 id，留下可辨认的词干
        stem = re.sub(r"-\d+$", "", slug)
        stem = re.sub(r"^[a-z]+-[a-z]+-effects-", "", stem)
        if len(stem) >= 6:
            out[stem] = target
    return out


def plan(seg_dir):
    src = os.path.join(seg_dir, "素材")
    vo = os.path.join(seg_dir, "build", "vo")
    junk = os.path.join(seg_dir, "_废弃试听")
    if not os.path.isdir(src):
        sys.exit("!!! 没有 %s" % src)
    ren = sfx_rename_map(seg_dir)
    moves, warns = [], []

    # 段目录下散落的图先收进素材
    for f in sorted(os.listdir(seg_dir)):
        if f.lower().endswith((".png", ".jpg", ".jpeg")):
            moves.append((os.path.join(seg_dir, f), os.path.join(src, f), "图归位"))

    for f in sorted(os.listdir(src)):
        p = os.path.join(src, f)
        if not os.path.isfile(p) or not f.lower().endswith(".mp3"):
            continue
        if f.startswith(DISCARD_PREFIXES):
            moves.append((p, os.path.join(junk, f), "废弃"))
            continue
        if f.startswith("VO_"):
            clean = re.sub(r"\s*\(\d+\)(?=\.mp3$)", "", f)
            tag = "旁白" + ("（去后缀）" if clean != f else "")
            moves.append((p, os.path.join(vo, clean), tag))
            continue
        hit = [t for stem, t in ren.items() if stem in f]
        if hit:
            moves.append((p, os.path.join(src, hit[0]), "找来的音效改名"))
        # 其余 mp3（复用的音效）不动

    seen = {}
    for _, dstp, _ in moves:
        seen[dstp] = seen.get(dstp, 0) + 1
        if seen[dstp] > 1 or os.path.exists(dstp):
            warns.append("撞名: " + dstp)
    return moves, warns


def selftest():
    """回归自测：把 SFX_CREDITS 的解析拿假数据跑一遍。

    为什么专门给这个函数写自测：它的失效形式是**恒返回空字典** ——
    不抛异常、不打印任何东西，只是"没有要改名的文件"，
    而那和"确实没有要改名的文件"长得一模一样。
    这种检查失效活了三段才被发现。**一个永远不报警的检查比没有检查更糟。**
    """
    import tempfile
    ok = True
    cases = [
        ("一条", 1, '''SFX_CREDITS = {
    "s16_炉火.mp3": dict(
        author="somebody (via Freesound)",
        url="https://pixabay.com/sound-effects/household-fireplace-17909/",
    ),
}
'''),
        ("两条", 2, '''SFX_CREDITS = {
    "sA_甲.mp3": dict(
        url="https://pixabay.com/sound-effects/nature-shroud-wind-wistles-27053/",
    ),
    "sB_乙.mp3": dict(
        url="https://pixabay.com/sound-effects/household-tools-metal-kit-13197/",
    ),
}
'''),
        ("没有这一块", 0, "SFX = []"),
    ]
    for name, want, src in cases:
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "build"))
        io.open(os.path.join(d, "build", "make_story_h.py"), "w",
                encoding="utf-8").write(src)
        got = sfx_rename_map(d)
        good = len(got) == want
        ok = ok and good
        print("  %-12s 期望 %d 条，实得 %d 条  %s%s"
              % (name, want, len(got), "ok" if good else "**不对**",
                 "  " + repr(got) if got else ""))
    # 作者名里的 "(via Freesound)" 带一个右括号+引号+逗号 —— 内层正则如果写成
    # `\),\s*` 而不管引号，就会在这里提前收尾，把 url 甩在匹配之外。
    print("  自测%s" % ("通过" if ok else "**失败**"))
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if len(sys.argv) < 2:
        sys.exit("用法: python sort_downloads.py <段目录> [--apply]" + chr(10)
                 + "      python sort_downloads.py --selftest")
    seg = sys.argv[1].rstrip("/\\")
    apply_ = "--apply" in sys.argv
    moves, warns = plan(seg)
    if not moves:
        print("没有要动的文件。")
        return
    for a, b, why in moves:
        print("  %-10s %s\n             -> %s" % (why, os.path.basename(a), b))
    print("\n共 %d 个动作" % len(moves))
    if warns:
        print("\n!! %d 处撞名，**一个都不动**（不覆盖任何东西）:" % len(warns))
        for w in warns:
            print("   - " + w)
        sys.exit(1)
    if not apply_:
        print("\n（这是计划。加 --apply 才真动。）")
        return
    for a, b, _ in moves:
        os.makedirs(os.path.dirname(b), exist_ok=True)
        shutil.move(a, b)
    print("\n做完了。")


if __name__ == "__main__":
    main()
