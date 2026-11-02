# -*- coding: utf-8 -*-
"""ChatCut 生成物落地：出下载页 → 用户点 → 后台等齐、归位。

    python chatcut_dl.py page <清单> --project <项目UUID> --out ../下载VO.html [--ext mp3]
    python chatcut_dl.py wait ../下载VO.json --dest ../素材 [--src ~/Downloads] [--every 60] [--timeout 0]
    python chatcut_dl.py missing ../下载VO.json [--src ~/Downloads]

清单：一行一条「名字 资产id」，名字就是 ChatCut 里的资产名（不带扩展名，如 `VO_034_v4`），
资产 id 用 `track_progress` / `browse_assets` 给的 10 位前缀就行。`#` 开头是注释。

===== 为什么要这个 =====

ChatCut 的下载接口要用户的登录会话，Agent 直接取是 401，所以只能出下载页让用户点
（记忆 chatcut-download-page；用户 2026-10-02 定：不许 Agent 自己在面板里下）。
点完以后那一段以前每次手写一个 `until ls ~/Downloads/...; do sleep 60; done` 的 shell，
写了四五遍，每次都要重想同样几条规则，而漏一条就静默出错：

1. **只认下载页出了之后落地的文件。** 「下载」目录里常有别的片子同名的 `VO_034.mp3`。
   `page` 把出页时刻写进 `.json`（`t0`），`wait` 只收 mtime 晚于它的。
2. **浏览器会加 ` (1)` 后缀、偶尔叠成 `.mp3.mp3`。** 都认，同名取最新。
3. **还在写的文件不能收。** 两次轮询大小一样、且大于 0 才算落地。
4. **前一两条常被吞**（Chrome「允许多个下载」的提示答完之前发出的会丢）。
   等太久还缺的，自动出一张**只含缺件的补下载页**（`<页名>_补.html`），日志里打出路径。
5. 2026-11-02 那一页用了隐藏 iframe 下载，Chrome 全拦了。下载页一律用 `<a>` 点击，
   第一条之后停 4 秒让用户答授权提示。

`wait` 收齐后把文件**复制**到 `--dest/<名字>.<ext>`（原件留在「下载」里），退出码 0；
`--timeout` 分钟到了还不齐，退出码 1。适合当 `runlog.py` 的第一步。
"""
import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

API = "https://api.chatcut.io/api/assets/%s/download?projectId=%s"

PAGE = """<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8"><title>%(title)s</title>
<style>body{background:#14110e;color:#f0e9df;font:16px sans-serif;padding:40px}a{color:#c8a86a;display:inline-block;min-width:180px;margin:4px 0}button{font-size:18px;padding:10px 24px;margin:16px 0}</style></head><body>
<p>在已登入 ChatCut 的瀏覽器開，按「全部下載」（瀏覽器問「允許多個下載」選允許）；檔案留在「下載」資料夾就行，後台齊了自己收。</p>
<button onclick="dl()">全部下載（%(n)d 個）</button> <span id=s></span><div id=L>
%(links)s
</div>
<script>async function dl(){const a=[...document.querySelectorAll('#L a')];document.querySelector('button').disabled=true;
for(let i=0;i<a.length;i++){const x=document.createElement('a');x.href=a[i].href;x.style.display='none';document.body.appendChild(x);x.click();
setTimeout(()=>x.remove(),2000);document.getElementById('s').textContent='已送出 '+(i+1)+' / '+a.length+'（送出不等於落地，後台逐個核對）';
await new Promise(r=>setTimeout(r,i==0?4000:1200));}}</script>
</body></html>
"""


def read_list(path):
    items = []
    for ln in io.open(path, encoding="utf-8-sig"):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split()
        if len(parts) < 2:
            sys.exit("!! 清单这行不是「名字 资产id」：%r" % ln)
        items.append({"name": parts[0], "id": parts[1]})
    names = [x["name"] for x in items]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        sys.exit("!! 清单里重名：%s" % "、".join(dup))
    if not items:
        sys.exit("!! 清单是空的")
    return items


def write_page(out, items, project, title):
    links = "\n".join('<a href="%s">%s</a>' % (API % (x["id"], project), x["name"]) for x in items)
    io.open(out, "w", encoding="utf-8").write(PAGE % {"title": title, "n": len(items), "links": links})


def cmd_page(a):
    items = read_list(a.list)
    out = os.path.abspath(a.out)
    write_page(out, items, a.project, a.title or os.path.splitext(os.path.basename(out))[0])
    man = {"project": a.project, "ext": a.ext.lstrip("."), "t0": time.time(), "page": out, "items": items}
    mpath = os.path.splitext(out)[0] + ".json"
    io.open(mpath, "w", encoding="utf-8").write(json.dumps(man, ensure_ascii=False, indent=1))
    print("下载页 %s（%d 个）" % (out, len(items)))
    print("清单   %s  ← 交给 `chatcut_dl.py wait`" % mpath)


def find(src, name, ext, t0):
    """src 里 t0 之后落地、名字对得上的最新文件；认 ` (N)` 后缀和叠起来的扩展名。"""
    pat = re.compile(r"^%s(?:\.%s)?(?: \(\d+\))?\.%s$" % (re.escape(name), re.escape(ext), re.escape(ext)), re.I)
    best = None
    for fn in os.listdir(src):
        if not pat.match(fn):
            continue
        p = os.path.join(src, fn)
        try:
            st = os.stat(p)
        except OSError:
            continue
        if st.st_mtime < t0 - 1:
            continue
        if best is None or st.st_mtime > best[0]:
            best = (st.st_mtime, p, st.st_size)
    return best


def playable(p):
    """音视频过一遍 ffprobe：解不出时长当坏件。没有 ffprobe 就只看大小。"""
    if not shutil.which("ffprobe"):
        return True
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return float(r.stdout.strip()) > 0.1
    except ValueError:
        return False


def scan(man, src, sizes):
    """一轮：返回 {名字: 路径}（已稳定）和缺的名字。sizes 记上一轮大小，用来判断还在不在写。"""
    ext, t0 = man["ext"], man["t0"]
    got, miss = {}, []
    for x in man["items"]:
        f = find(src, x["name"], ext, t0)
        if f and f[2] > 0 and sizes.get(x["name"]) == (f[1], f[2]):
            got[x["name"]] = f[1]
        else:
            miss.append(x["name"])
        if f:
            sizes[x["name"]] = (f[1], f[2])
    return got, miss


def default_src():
    return os.path.join(os.path.expanduser("~"), "Downloads")


def load(path):
    return json.load(io.open(path, encoding="utf-8"))


def cmd_wait(a):
    man = load(a.manifest)
    src, dest = os.path.abspath(a.src), os.path.abspath(a.dest)
    os.makedirs(dest, exist_ok=True)
    n = len(man["items"])
    print("等下载：%d 个，从 %s 收到 %s（只认 %s 之后落地的）"
          % (n, src, dest, time.strftime("%m-%d %H:%M", time.localtime(man["t0"]))))
    sizes, start, last_n, last_change, nagged = {}, time.time(), -1, time.time(), False
    audio = man["ext"].lower() in ("mp3", "wav", "m4a", "mp4", "aac", "flac", "ogg")
    while True:
        got, miss = scan(man, src, sizes)
        if len(got) != last_n:
            print("  %s  %d / %d" % (time.strftime("%H:%M"), len(got), n), flush=True)
            last_n, last_change = len(got), time.time()
        if not miss:
            break
        stuck = (time.time() - last_change) / 60
        if not nagged and got and stuck >= a.nag:
            sup = os.path.splitext(man["page"])[0] + "_补.html"
            write_page(sup, [x for x in man["items"] if x["name"] in miss], man["project"], "補下載 %d 個" % len(miss))
            print("  !! %.0f 分钟没新进展，缺 %d 个：%s" % (stuck, len(miss), "、".join(miss)))
            print("  !! 补下载页 %s（只含缺件）" % sup, flush=True)
            nagged = True
        if a.timeout and (time.time() - start) / 60 >= a.timeout:
            print("!! 等了 %d 分钟还缺 %d 个：%s" % (a.timeout, len(miss), "、".join(miss)))
            sys.exit(1)
        time.sleep(a.every)
    bad = []
    for x in man["items"]:
        p = got[x["name"]]
        if audio and not playable(p):
            bad.append(x["name"])
            continue
        shutil.copy2(p, os.path.join(dest, "%s.%s" % (x["name"], man["ext"])))
    if bad:
        print("!! 坏件（解不出时长）%d 个：%s —— 删掉它们重下" % (len(bad), "、".join(bad)))
        sys.exit(1)
    print("✓ %d 个齐了，已复制到 %s" % (n, dest))


def cmd_missing(a):
    man = load(a.manifest)
    src = os.path.abspath(a.src)
    miss = [x["name"] for x in man["items"] if not find(src, x["name"], man["ext"], man["t0"])]
    print("%d / %d 已落地" % (len(man["items"]) - len(miss), len(man["items"])))
    if miss:
        print("缺：%s" % "、".join(miss))
        sys.exit(1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("page", help="出下载页和清单 .json")
    p.add_argument("list")
    p.add_argument("--project", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--ext", default="mp3")
    p.add_argument("--title", default="")
    w = sub.add_parser("wait", help="等齐、复制进 --dest")
    w.add_argument("manifest")
    w.add_argument("--dest", required=True)
    w.add_argument("--src", default=default_src())
    w.add_argument("--every", type=float, default=60, help="轮询间隔秒（默认 60）")
    w.add_argument("--nag", type=float, default=15, help="几分钟没新进展就出补下载页（默认 15）")
    w.add_argument("--timeout", type=float, default=0, help="分钟；0＝一直等")
    m = sub.add_parser("missing", help="看一眼还缺哪些")
    m.add_argument("manifest")
    m.add_argument("--src", default=default_src())
    a = ap.parse_args(argv)
    {"page": cmd_page, "wait": cmd_wait, "missing": cmd_missing}[a.cmd](a)


if __name__ == "__main__":
    main()
