# -*- coding: utf-8 -*-
"""讲述稿.md → narr.json（一句一条 VO）。两种稿子格式都认，自动判断：

  A. 表格版（《海底四十小時》）：  | 句号 | 旁白 | 画面 |      → VO_001、VO_002 …（句号三位）
  B. 镜头段落版（《十三個冬天》）：**鏡12** 下面一行 > 甲｜乙   → VO_12a、VO_12b …（｜切句）

    python narr_build.py          # 生成 / 更新 narr.json，报出文字变了的条目

改稿后重跑。**文字变了的条目要重出旁白**：python el_tts.py gen zh VO_xxx（会顺手清掉旧件）。
表格版只认第一列是纯数字的行；说明性表格（第一列不是数字）不受影响。
"""
import io
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))


def parse(md):
    rows = [(int(m.group(1)), m.group(2).strip()) for m in re.finditer(r"^\| (\d+) \| (.+?) \| .*\|$", md, re.M)]
    if rows:
        nums = [n for n, _ in rows]
        if nums != list(range(1, len(rows) + 1)):
            sys.exit("!!! 表格版的句号不连续（应 1..%d）：%s" % (len(rows), [n for i, n in enumerate(nums, 1) if n != i][:5]))
        return [dict(vo="VO_%03d" % n, txt=t) for n, t in rows]
    parts = md.split("\n---\n")
    body = parts[1] if len(parts) > 1 else md
    out, shot, k = [], None, 0
    for ln in body.splitlines():
        m = re.match(r"\*\*鏡(\d+)\*\*", ln)
        if m:
            shot, k = int(m.group(1)), 0
            continue
        if ln.startswith("> ") and shot is not None:
            for p in [x.strip() for x in ln[2:].split("｜") if x.strip()]:
                out.append(dict(vo="VO_%02d%s" % (shot, "abcdefghij"[k]), txt=p))
                k += 1
    if not out:
        sys.exit("!!! 讲述稿里两种格式都没读到旁白（表格「| 1 | 旁白 | 画面 |」或「**鏡1**」＋「> 句｜句」）")
    return out


def main():
    md = io.open(os.path.join(HERE, "..", "讲述稿.md"), encoding="utf-8").read()
    out = parse(md)
    p = os.path.join(HERE, "narr.json")
    old = {n["vo"]: n["txt"] for n in json.load(open(p, encoding="utf-8"))} if os.path.exists(p) else {}
    changed = [n["vo"] for n in out if n["vo"] in old and old[n["vo"]] != n["txt"]]
    gone = [v for v in old if v not in {n["vo"] for n in out}]
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("%d 条；汉字 %d；文字变了：%s%s" % (len(out), sum(len(re.findall(r"[一-鿿]", n["txt"])) for n in out),
                                     changed or "无", "；没了的编号：%s" % gone if gone else ""))
    if changed:
        print("→ 重出：python el_tts.py gen zh %s" % " ".join(changed))


if __name__ == "__main__":
    main()
