"""回归：vo_trim apply 认得出「重新生成过的句子」。

    python tests/test_vo_trim.py

2026-10-18《海底四十小時》踩到：重出过的 VO 只要忘了删 vo_orig/ 里的同名旧原件，
apply 就拿旧录音剪一刀、把新录音盖掉 —— 不报错，时长还跟改稿前一样。
这里逐条造场景，看它是不是真的用了新文件（判据是剪完的时长），
并且验：把 is_fresh 改成永远 False（旧行为），这套测试会红。

要 ffmpeg / ffprobe 在 PATH 上。
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.environ.get("VMSKILL_SCRIPTS") or os.path.join(ROOT, "classical-poem-video", "scripts")
FAILS = []


def ok(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        FAILS.append(what)


def tone(path, speak, pad=0.5):
    """pad 秒数字静音 + speak 秒 440Hz + pad 秒静音。"""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=%.2f,adelay=%d|%d,apad=pad_dur=%.2f" % (speak, pad * 1000, pad * 1000, pad),
                    "-ac", "1", "-ar", "44100", "-c:a", "libmp3lame", "-q:a", "2", path], check=True)


def dur(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                 "-of", "csv=p=0", path], capture_output=True, text=True).stdout)


def apply(script, d):
    r = subprocess.run([sys.executable, script, "apply", d], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.stdout


def run(script):
    tmp = tempfile.mkdtemp(prefix="vo_trim_")
    try:
        vo = os.path.join(tmp, "vo")
        os.makedirs(vo)
        tone(os.path.join(vo, "VO_001.mp3"), 1.0)
        tone(os.path.join(vo, "VO_002.mp3"), 1.5)
        apply(script, vo)
        d1 = dur(os.path.join(vo, "VO_001.mp3"))
        ok(1.05 < d1 < 1.35, "首次 apply：头尾静音剪掉（%.2fs）" % d1)
        apply(script, vo)
        ok(abs(dur(os.path.join(vo, "VO_001.mp3")) - d1) < 0.03, "再跑一次 apply：幂等，不多削")

        # 重出 VO_001：说话 2.0s
        tone(os.path.join(vo, "VO_001.mp3"), 2.0)
        out = apply(script, vo)
        d2 = dur(os.path.join(vo, "VO_001.mp3"))
        ok(2.05 < d2 < 2.35, "重出后 apply：用的是新录音（%.2fs，旧录音剪完约 %.2fs）" % (d2, d1))
        ok(abs(dur(os.path.join(tmp, "vo_orig", "VO_001.mp3")) - 3.0) < 0.1, "vo_orig 里的原件换成了新录音")
        ok("重新生成" in out, "apply 报出认出了几条新文件")

        # 有下游在改写（vo_raw/ 存在 = vofit 跑过）：sha1 对不上时不能断定是新录音 → 不动、报出来
        os.makedirs(os.path.join(tmp, "vo_raw"))
        tone(os.path.join(vo, "VO_002.mp3"), 0.8, pad=0.0)          # 模拟 vofit 的产物
        before = dur(os.path.join(vo, "VO_002.mp3"))
        out = apply(script, vo)
        ok(abs(dur(os.path.join(vo, "VO_002.mp3")) - before) < 0.03, "有 vo_raw/：对不上的文件跳过不动（不拿旧原件盖掉）")
        ok(abs(dur(os.path.join(tmp, "vo_orig", "VO_002.mp3")) - 2.5) < 0.1, "有 vo_raw/：原件备份没被换成下游产物")
        ok("没动" in out, "有 vo_raw/：报出拿不准的那几条")
        shutil.rmtree(os.path.join(tmp, "vo_raw"))

        # 没有账本的老项目：维持老行为（从原件剪），不猜
        os.remove(os.path.join(tmp, "vo_orig", "_trimmed.json"))
        tone(os.path.join(vo, "VO_002.mp3"), 0.8)
        apply(script, vo)
        d3 = dur(os.path.join(vo, "VO_002.mp3"))
        ok(1.55 < d3 < 1.85, "无账本：维持老行为，从原件剪（%.2fs）" % d3)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    script = os.path.join(SCRIPTS, "vo_trim.py")
    print("== vo_trim：真脚本")
    run(script)
    real_fails = list(FAILS)

    # 自检：把 is_fresh 改成永远 False（2026-10-18 之前的行为），测试必须红
    print("== vo_trim：故意改坏（is_fresh 恒 False），这一段应当出 FAIL")
    broken_dir = tempfile.mkdtemp(prefix="vo_trim_broken_")
    try:
        src = open(script, encoding="utf-8").read()
        src, n = re.subn(r"def is_fresh\(src, orig, ledger, f, derived\):",
                         "def is_fresh(src, orig, ledger, f, derived):\n    return False\n\ndef _unused(src, orig, ledger, f, derived):", src)
        ok(n == 1, "改坏的副本确实改到了 is_fresh（替换 %d 处）" % n)
        bp = os.path.join(broken_dir, "vo_trim.py")
        open(bp, "w", encoding="utf-8").write(src)
        before = len(FAILS)
        run(bp)
        caught = len(FAILS) - before
        del FAILS[before:]
        ok(caught > 0, "改坏的脚本被测试抓到（%d 条 FAIL）" % caught)
    finally:
        shutil.rmtree(broken_dir, ignore_errors=True)

    print()
    if FAILS or real_fails:
        print("FAIL %d 条" % len(FAILS))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
