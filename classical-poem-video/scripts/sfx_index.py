# -*- coding: utf-8 -*-
"""音效库的登记与查询工具。

    python sfx_index.py            # 列出库里所有音效（带实测数据）
    python sfx_index.py rebuild    # 重新量 assets/sfx/ 下所有 mp3，重写 INDEX.md
    python sfx_index.py add <mp3> --name "雨夜·中雨与远雷" --prompt "..." --used "《XXX》镜12"

**为什么这个库要存实测数据，而不是只存 mp3：**

生成出来的音效响度实测能差 45dB，所以片子里**不能写死增益**，要写目标响度让脚本
按实测反算。更麻烦的是 **LUFS 会骗人**：一条 −53.5 LUFS 的"江风"不是失败，
是能量全在 120Hz 以下（K 加权把低频衰掉了），但手机喇叭根本放不出来。
所以判一条音效能不能用、该配多大增益，必须**分频段量**：<120 / 120–2k / >2k。

把这三个数连同提示词一起存下来，下一支就不用重新生成、也不用重新量 ——
这才是"可复用"的实际含义。只存 mp3 等于每次都要重走一遍。
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SFX_DIR = os.path.normpath(os.path.join(HERE, "..", "assets", "sfx"))
INDEX = os.path.join(SFX_DIR, "INDEX.md")
META = os.path.join(SFX_DIR, "_meta.json")
BANDS = [("<120", "lowpass=f=120"),
         ("120-2k", "highpass=f=120,lowpass=f=2000"),
         (">2k", "highpass=f=2000")]

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _run(args):
    return subprocess.run(args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def duration(path):
    r = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "csv=p=0", path])
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def integrated(path, pre=None):
    af = (pre + ",") if pre else ""
    r = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", path,
              "-af", af + "ebur128=framelog=quiet", "-f", "null", "-"])
    mm = re.findall(r"I:\s*(-?\d+\.\d+) LUFS", r.stderr)
    return float(mm[-1]) if mm else None


def rms_db(path, pre=None):
    """分频段用 RMS 而不是 LUFS —— K 加权会把低频衰掉，正是要避开的那个骗局。"""
    af = (pre + ",") if pre else ""
    r = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", path,
              "-af", af + "astats=metadata=1:reset=0", "-f", "null", "-"])
    mm = re.findall(r"RMS level dB:\s*(-?\d+\.\d+|-inf)", r.stderr)
    if not mm:
        return None
    v = mm[-1]
    return -99.0 if v == "-inf" else float(v)


def measure(path):
    d = duration(path)
    return {
        "duration": round(d, 2) if d else None,
        "lufs": integrated(path),
        "bands": {n: rms_db(path, f) for n, f in BANDS},
    }


def load_meta():
    if os.path.exists(META):
        with open(META, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_meta(m):
    with open(META, "w", encoding="utf-8", newline="\n") as f:
        json.dump(m, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def write_index(meta):
    rows = []
    rows.append("# 音效库\n")
    rows.append("生成一条音效要花额度，而且**同一个提示词两次的结果并不一样**；")
    rows.append("更要紧的是每条都得分频段量过才知道能不能用。所以这里存的是")
    rows.append("**mp3 + 提示词 + 实测数据**，下一支直接取，不要重新生成。\n")
    rows.append("加新条目：`python scripts/sfx_index.py add <mp3> --name ... --prompt ...`\n")
    rows.append("## 怎么用这张表\n")
    rows.append("- **`>2k` 那一列低于约 −45 dB 的，手机喇叭上基本听不见**——")
    rows.append("  这类素材（低频风、远雷）只能当垫底，不要指望它在小喇叭上有存在感。")
    rows.append("- 片子里**不要写死 dB**，写目标响度让脚本按实测反算：")
    rows.append("  生成音效之间的响度差能到 45dB。")
    rows.append("- 整合响度（LUFS）只作参考，**判断依据是分频段的 RMS**。\n")
    rows.append("| 文件 | 名称 | 时长 | LUFS | <120Hz | 120–2k | >2k | 标签 |")
    rows.append("|---|---|---|---|---|---|---|---|")
    for fn in sorted(meta):
        e = meta[fn]
        b = e.get("bands", {})
        def f(x):
            return "—" if x is None else ("%.1f" % x)
        rows.append("| `%s` | %s | %.1fs | %s | %s | %s | %s | %s |" % (
            fn, e.get("name", ""), e.get("duration") or 0, f(e.get("lufs")),
            f(b.get("<120")), f(b.get("120-2k")), f(b.get(">2k")),
            " ".join(e.get("tags", []))))
    rows.append("")
    for fn in sorted(meta):
        e = meta[fn]
        rows.append("### `%s` — %s\n" % (fn, e.get("name", "")))
        if e.get("prompt"):
            rows.append("提示词（ElevenLabs `submit_sound`）：\n")
            rows.append("```\n%s\n```\n" % e["prompt"])
        if e.get("used"):
            rows.append("用过：%s\n" % "；".join(e["used"]))
        if e.get("note"):
            rows.append("> %s\n" % e["note"])
    with open(INDEX, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(rows))


def cmd_rebuild():
    meta = load_meta()
    seen = set()
    for fn in sorted(os.listdir(SFX_DIR)):
        if not fn.lower().endswith(".mp3"):
            continue
        seen.add(fn)
        e = meta.setdefault(fn, {})
        e.update(measure(os.path.join(SFX_DIR, fn)))
        print("量过 %-28s %5.1fs  LUFS %6.1f  <120 %6.1f  120-2k %6.1f  >2k %6.1f"
              % (fn, e["duration"], e["lufs"] or -99,
                 e["bands"]["<120"] or -99, e["bands"]["120-2k"] or -99,
                 e["bands"][">2k"] or -99))
    for fn in [k for k in meta if k not in seen]:
        print("!! %s 在 _meta.json 里但文件不在了" % fn)
    save_meta(meta)
    write_index(meta)
    print("\nINDEX.md 已重写，共 %d 条" % len(seen))


def cmd_add(a):
    fn = os.path.basename(a.mp3)
    dst = os.path.join(SFX_DIR, fn)
    if os.path.abspath(a.mp3) != os.path.abspath(dst):
        with open(a.mp3, "rb") as s, open(dst, "wb") as d:
            d.write(s.read())
    meta = load_meta()
    e = meta.setdefault(fn, {})
    e.update(measure(dst))
    if a.name:
        e["name"] = a.name
    if a.prompt:
        e["prompt"] = a.prompt
    if a.note:
        e["note"] = a.note
    if a.tags:
        e["tags"] = a.tags.split(",")
    if a.used:
        e.setdefault("used", [])
        if a.used not in e["used"]:
            e["used"].append(a.used)
    save_meta(meta)
    write_index(meta)
    print("已登记 %s" % fn)


def cmd_list():
    meta = load_meta()
    if not meta:
        print("库是空的。先跑 rebuild 或 add")
        return
    print("%-28s %-20s %6s %7s %8s %8s %8s"
          % ("文件", "名称", "时长", "LUFS", "<120", "120-2k", ">2k"))
    for fn in sorted(meta):
        e = meta[fn]
        b = e.get("bands", {})
        print("%-28s %-20s %5.1fs %7.1f %8.1f %8.1f %8.1f"
              % (fn, e.get("name", ""), e.get("duration") or 0,
                 e.get("lufs") or -99, b.get("<120") or -99,
                 b.get("120-2k") or -99, b.get(">2k") or -99))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("rebuild")
    pa = sub.add_parser("add")
    pa.add_argument("mp3")
    pa.add_argument("--name")
    pa.add_argument("--prompt")
    pa.add_argument("--note")
    pa.add_argument("--tags")
    pa.add_argument("--used")
    a = p.parse_args()
    if a.cmd == "rebuild":
        cmd_rebuild()
    elif a.cmd == "add":
        cmd_add(a)
    else:
        cmd_list()
