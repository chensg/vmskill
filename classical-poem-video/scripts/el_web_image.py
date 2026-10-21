# -*- coding: utf-8 -*-
"""ElevenLabs 网页版出图：出图任务书 → 提示词 → 贴进页面的 JS → 下载落盘。

    python el_web_image.py list                    # 任务书里所有档名（★样图在前），已出的打 ✓
    python el_web_image.py show 06_綠燈            # 打印一张的完整提示词（字数）
    python el_web_image.py js [档名...]            # 不给＝还没出的全部；输出 window.__C/__ROWS（压缩）+ 展开成 __P/__MID
    python el_web_image.py fetch <导出文件>         # __export() 的工具结果文件 → ../素材/生成/<档名>.png（旧的改名 _v1）

页面那一侧的函数在同目录 el_web_image.js（设定核对、逐张提交、收图、导出），用法写在它开头。

==== 任务书格式（《十三個冬天》《海底四十小時》那套，固定开头＋一句画面＋固定结尾）====
    ## 固定開頭
    > 寫實電影劇照……16:9 橫構圖。
    **夜裡的鏡另加一句**（表裡標「夜」）：「夜裡，但畫面不能暗：……」
    ## 固定結尾 A（有人）
    > ……
    ## 固定結尾 E（沒有人）
    > ……
    - **（艇內）**：一九三九年美國海軍潛艇的內部……        ← 画面句里写（艇內）就整句换进去
    | 檔 | 鏡 | 結尾 | 畫面句 |
    | ★17_躺著的人 | 38 39 | 暗 A | （艇內）。這是……|
    | 04a_北狩 | 4 | A | ……|                      ← 拆镜补图：两位数字后可带一个小写字母

**为什么提示词要压缩着贴**：43 张完整提示词 2 万多字，原样贴进一次 javascript_tool 要花一万多 token；
固定开头/结尾只贴一次、每张只带中间那句，五千字就够，页面里再拼回全文（和这里拼的逐字一致，收图按它对档名）。

==== 设定（memory elevenlabs-web-image-gen）====
GPT Image 2.5 Flare / 16:9（竖版 9:16）/ 2K / Medium / 每次 1 张 / 自动改写关。2K Medium 85 credits，落盘 2048×1152。
**任何 navigate（包括刷新）之后设定都会被重置成 Sunburst/1K/High/4** —— 提交前 __checkSettings()。
"""
import json
import os
import re
import subprocess
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
BRIEF = os.path.join(PROJ, "出图任务书.md")
DST = os.path.join(PROJ, "素材", "生成")


def _brief():
    if not os.path.exists(BRIEF):
        sys.exit("!!! 找不到 %s" % BRIEF)
    md = open(BRIEF, encoding="utf-8").read()

    def block(title):
        m = re.search(r"## " + re.escape(title) + r"[^\n]*\n\n> (.+?)\n", md)
        if not m:
            sys.exit("!!! 任务书缺「## %s」那一节（下面空一行接 > 一段）" % title)
        return m.group(1).replace("**", "").strip()

    head = block("固定開頭")
    ends = {"A": block("固定結尾 A"), "E": block("固定結尾 E")}
    extra = dict(re.findall(r"表裡標「(.+?)」）：「(.+?)」\n", md))
    desc = dict(re.findall(r"- \*\*（(.+?)）\*\*：(.+)", md))
    rows = {}
    for line in md.split("\n"):
        m = re.match(r"\| (★?)(\d{2,3}[a-z]?_[^ |]+) \| [^|]+ \| ([^|]+) \| (.+) \|$", line)  # 04a_：拆镜补的图；102a_：长片三位数镜号
        if m:
            rows[m.group(2)] = (m.group(3).strip(), m.group(4).strip(), bool(m.group(1)))
    if not rows:
        sys.exit("!!! 任务书里没读到逐张画面句（| 檔 | 鏡 | 結尾 | 畫面句 | 表）")
    return head, ends, extra, desc, rows


def _expand(text, desc):
    """画面句里的（名字）换成固定描述。描述以「一個」开头而前面已有「一個」时不叠字。"""
    for k, v in desc.items():
        tok = "（%s）" % k
        while tok in text:
            i = text.index(tok)
            nxt = text[i + len(tok):i + len(tok) + 1]
            v2 = v.strip().rstrip("。")
            if text[max(0, i - 2):i] == "一個" and v2.startswith("一個"):
                v2 = v2[2:]
            text = text[:i] + v2 + ("" if nxt in "，。、；（）：" else "，") + text[i + len(tok):]
    return text


def parts(name):
    head, ends, extra, desc, rows = _brief()
    end, text, _ = rows[name]
    flags = [k for k in extra if k in end]
    tail = ends["E"] if end.rstrip().endswith("E") else ends["A"]
    return head, [extra[k] for k in flags], _expand(text, desc), tail


def prompt(name):
    head, extras, mid, tail = parts(name)
    return " ".join([head] + extras + [mid, tail])


def check(name):
    """拼出来的句子有没有明显的病：描述换进去之后「，的」「一個一個」这种。"""
    p = prompt(name)
    bad = [x for x in ("一個一個", "，的", "，裡面", "，背上") if x in p]
    return bad


def cmd_list():
    _, _, _, _, rows = _brief()
    for n, (_, _, star) in sorted(rows.items(), key=lambda kv: (not kv[1][2], kv[0])):
        print(("★" if star else " "), ("✓" if os.path.exists(os.path.join(DST, n + ".png")) else "·"), n)
    print(len(rows), "张")


def cmd_js(names):
    head, ends, extra, desc, rows = _brief()
    names = names or [n for n in rows if not os.path.exists(os.path.join(DST, n + ".png"))]
    out = []
    for n in names:
        h, ex, mid, tail = parts(n)
        flags = "".join(k for k in extra if extra[k] in ex) + ("E" if tail == ends["E"] else "A")
        bad = check(n)
        if bad:
            print("!! %s 拼出来有病句：%s —— 改任务书的画面句" % (n, bad), file=sys.stderr)
        out.append([n, flags, mid])
    keys = list(extra.keys())
    js = ("window.__C=" + json.dumps({"S": head, "X": extra, "A": ends["A"], "E": ends["E"]}, ensure_ascii=False) + ";"
          "window.__ROWS=" + json.dumps(out, ensure_ascii=False) + ";"
          "window.__P=window.__P||{};window.__MID=window.__MID||{};"
          "for(const [n,f,m] of window.__ROWS){const p=[__C.S];for(const k of " + json.dumps(keys, ensure_ascii=False) +
          ") if(f.includes(k)) p.push(__C.X[k]);p.push(m);p.push(f.endsWith('E')?__C.E:__C.A);"
          "window.__P[n]=p.join(' ');window.__MID[n]=m;}"
          "[window.__ROWS.length,Object.keys(window.__P).length]")
    # 自检：页面里拼回的全文必须和这里逐字一致（收图靠它对档名）
    for n, f, m in out:
        p = [head] + [extra[k] for k in keys if k in f] + [m, ends["E"] if f.endswith("E") else ends["A"]]
        assert " ".join(p) == prompt(n), n
    print(js)


def cmd_fetch(path, dst=DST):
    raw = open(path, encoding="utf-8").read()
    data = json.loads(raw)
    if isinstance(data, list):          # 工具结果文件：[{type,text}]，text 是页面返回值（可能还套一层 JSON 字符串）
        data = data[0]["text"]
    while isinstance(data, str):
        s = data.strip()
        data = json.JSONDecoder().raw_decode(s[s.find(next(c for c in s if c in '{"')):])[0]
    os.makedirs(os.path.join(dst, "_预览"), exist_ok=True)
    for name, url in data.items():
        out = os.path.join(dst, name + ".png")
        if os.path.exists(out):
            k = 1
            while os.path.exists(os.path.join(dst, "%s_v%d.png" % (name, k))):
                k += 1
            os.rename(out, os.path.join(dst, "%s_v%d.png" % (name, k)))
        open(out, "wb").write(urllib.request.urlopen(url, timeout=300).read())
        wh = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", out],
                            capture_output=True, text=True).stdout.strip()
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", out, "-vf", "scale=576:-1",
                        os.path.join(dst, "_预览", name + ".jpg")])
        print("存", name, wh, flush=True)
    print("**下载完逐张看一眼**（联络表）：按提示词对上了名字，图仍可能是查看器里上一张的残影。")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    c, args = sys.argv[1], sys.argv[2:]
    if c == "list":
        cmd_list()
    elif c == "show":
        for n in args:
            p = prompt(n)
            print("== %s %d 字%s\n%s" % (n, len(p), ("  !! " + str(check(n))) if check(n) else "", p))
    elif c == "js":
        cmd_js(args)
    elif c == "fetch":
        cmd_fetch(args[0])
    else:
        print(__doc__); sys.exit(1)
