"""回归：runlog.py（长任务按步骤跑、写日志、能停干净）和 chatcut_dl.py（出下载页、等齐归位）。

    python tests/test_runlog_dl.py

每条都配一个「改坏的版本」，看测试抓不抓得到（记忆 checks-that-never-fire）：
- runlog 的 stop 只杀外层、不带 /T（＝2026-11-02 TaskStop 的行为）→ 子进程活着，要红；
- runlog 去掉锁 → 第二个能起来，要红；
- chatcut_dl 不看 t0 → 把「下载」里别的片子的旧同名文件当成新的收进来，要红。

要 bash（Git for Windows）和 ffmpeg / ffprobe 在 PATH 上。
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.environ.get("VMSKILL_SCRIPTS") or os.path.join(ROOT, "classical-poem-video", "scripts")
FAILS = []
PY = sys.executable


def ok(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        FAILS.append(what)


def run(script, *args, **kw):
    return subprocess.run([PY, script] + list(args), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", **kw)


def alive(pid):
    sys.path.insert(0, SCRIPTS)
    import runlog
    return runlog.alive(pid)


def write(p, s):
    io.open(p, "w", encoding="utf-8", newline="\n").write(s)


# ---------------- runlog ----------------

def runlog_basic(rl, tmp):
    steps = os.path.join(tmp, "s1.txt")
    write(steps, "# 测试\n== 一\necho 第一步\n== ? 二（容忍）\nfalse\n== 三\necho done > three.txt\n")
    r = run(rl, "run", steps)
    log = io.open(steps + ".log", encoding="utf-8").read()
    ok(r.returncode == 0 and "RUNLOG DONE" in log, "全部成功（带 ? 的失败被容忍）→ DONE、退出码 0")
    ok(os.path.exists(os.path.join(tmp, "three.txt")), "每步从步骤文件所在目录起跑")
    ok("容忍的失败：二（容忍）" in log, "容忍的失败写进末行")
    ok(not os.path.exists(steps + ".log.pid"), "跑完删掉 .pid")

    steps2 = os.path.join(tmp, "s2.txt")
    write(steps2, "== 一\necho a\n== 二\necho 这步会失败\nexit 3\n== 三\necho no > never.txt\n")
    r = run(rl, "run", steps2)
    log = io.open(steps2 + ".log", encoding="utf-8").read()
    ok(r.returncode == 1 and "RUNLOG FAILED" in log, "一步失败 → FAILED、退出码 1")
    ok(not os.path.exists(os.path.join(tmp, "never.txt")), "失败之后的步骤不跑（不拿半成品往下做）")
    ok("这步会失败" in log, "失败那步的最后几行抄进主日志")


def runlog_stop(rl, tmp, expect_clean=True):
    """起一个会跑很久的 runlog，等子进程起来，stop，看子进程死没死。"""
    steps = os.path.join(tmp, "long.txt")
    child = os.path.join(tmp, "child.pid")
    if os.path.exists(child):
        os.remove(child)
    write(steps, "== 长\n\"%s\" -c \"import os,time; open(r'%s','w').write(str(os.getpid())); time.sleep(60)\"\n"
          % (PY.replace("\\", "/"), child))
    p = subprocess.Popen([PY, rl, "run", steps], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(80):
        if os.path.exists(child) and io.open(child).read().strip():
            break
        time.sleep(0.25)
    cpid = int(io.open(child).read())
    # 锁：同一个日志再起一个
    r2 = run(rl, "run", steps)
    lock_ok = r2.returncode == 2
    r = run(rl, "stop", steps)
    time.sleep(1.0)
    child_dead = not alive(cpid)
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
    if not child_dead:  # 收拾残局
        subprocess.run(["taskkill", "/PID", str(cpid), "/F"] if os.name == "nt" else ["kill", str(cpid)], capture_output=True)
    log = io.open(steps + ".log", encoding="utf-8").read()
    return lock_ok, child_dead, "RUNLOG STOPPED" in log


def test_runlog():
    print("runlog.py")
    rl = os.path.join(SCRIPTS, "runlog.py")
    tmp = tempfile.mkdtemp(prefix="runlog_")
    try:
        runlog_basic(rl, tmp)
        lock_ok, child_dead, stopped = runlog_stop(rl, tmp)
        ok(lock_ok, "同一个日志已经有人在跑 → 第二个拒绝（退出码 2）")
        ok(child_dead, "stop 连子进程一起停掉")
        ok(stopped, "stop 在日志末行写 RUNLOG STOPPED")

        # 步骤文件写错的报错走 stderr：没设 PYTHONIOENCODING 时原来打成 \\uXXXX（2026-11-12）
        bad_steps = os.path.join(tmp, "错的步骤.steps")
        write(bad_steps, "echo 第一行没写步骤名\n== 收旁白\necho hi\n")
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
        r = subprocess.run([PY, rl, "run", bad_steps], capture_output=True, env=env)
        err = r.stderr.decode("utf-8", "replace")
        ok(r.returncode != 0 and "步骤名" in err and "\\u" not in err,
           "没设 PYTHONIOENCODING：步骤文件写错的报错是中文，不是 \\uXXXX（%s）" % err.strip()[:60])

        print("  -- 改坏的版本（应该被抓到）")
        src = io.open(rl, encoding="utf-8").read()
        bad = src.replace('"/T", "/F"', '"/F"').replace("os.killpg(os.getpgid(pid), signal.SIGTERM)", "os.kill(pid, signal.SIGTERM)")
        bad = bad.replace("if old and old != os.getpid() and alive(old):", "if False:")
        assert bad != src
        brl = os.path.join(tmp, "runlog_bad.py")
        write(brl, bad)
        lock_ok, child_dead, _ = runlog_stop(brl, tmp)
        ok(not child_dead, "只杀外层（TaskStop 那样）时子进程还活着 —— 测试能分辨")
        ok(not lock_ok, "去掉锁时第二个起得来 —— 测试能分辨")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------- chatcut_dl ----------------

def tone(path, sec=1.0):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=%.2f" % sec,
                    "-c:a", "libmp3lame", "-q:a", "4", path], check=True)


def dl_case(dl, tmp, tag):
    """返回 (齐了没, dest 里的文件, 补下载页在不在)。VO_03 只有一个比 t0 早的旧件。"""
    src, dest = os.path.join(tmp, tag + "_src"), os.path.join(tmp, tag + "_dest")
    os.makedirs(src)
    tone(os.path.join(src, "VO_03.mp3"))
    old = time.time() - 3600
    os.utime(os.path.join(src, "VO_03.mp3"), (old, old))
    lst = os.path.join(tmp, tag + ".txt")
    write(lst, "# 名字 资产id\nVO_01 aaaaaaaaaa\nVO_02 bbbbbbbbbb\nVO_03 cccccccccc\n")
    page = os.path.join(tmp, tag + ".html")
    r = run(dl, "page", lst, "--project", "11111111-2222-3333-4444-555555555555", "--out", page)
    assert r.returncode == 0, r.stdout + r.stderr
    tone(os.path.join(src, "VO_01 (1).mp3"))
    tone(os.path.join(src, "VO_02.mp3.mp3"))
    r = run(dl, "wait", page[:-5] + ".json", "--dest", dest, "--src", src, "--every", "0.3", "--nag", "0", "--timeout", "0.05")
    files = sorted(os.listdir(dest)) if os.path.isdir(dest) else []
    return r.returncode == 0, files, os.path.exists(page[:-5] + "_补.html"), page, r


def test_dl():
    print("chatcut_dl.py")
    dl = os.path.join(SCRIPTS, "chatcut_dl.py")
    tmp = tempfile.mkdtemp(prefix="ccdl_")
    try:
        done, files, sup, page, r = dl_case(dl, tmp, "a")
        html = io.open(page, encoding="utf-8").read()
        man = json.load(io.open(page[:-5] + ".json", encoding="utf-8"))
        ok("iframe" not in html and "createElement('a')" in html, "下载页用 <a> 点击，不用 iframe（Chrome 会拦）")
        ok("/api/assets/aaaaaaaaaa/download?projectId=11111111" in html, "下载地址是资产前缀＋项目 id")
        ok(man["t0"] > time.time() - 120 and len(man["items"]) == 3, "清单 .json 记了 t0 和三条")
        ok(not done, "VO_03 只有出页之前的旧件 → 不算齐、超时退出码 1")
        ok(sup and "VO_03" in io.open(page[:-5] + "_补.html", encoding="utf-8").read()
           and "VO_01" not in io.open(page[:-5] + "_补.html", encoding="utf-8").read(), "补下载页只含缺件")
        # 补上 VO_03 的新件
        src = os.path.join(tmp, "a_src")
        tone(os.path.join(src, "VO_03 (2).mp3"))
        r = run(dl, "wait", page[:-5] + ".json", "--dest", os.path.join(tmp, "a_dest"), "--src", src, "--every", "0.3")
        files = sorted(os.listdir(os.path.join(tmp, "a_dest")))
        ok(r.returncode == 0 and files == ["VO_01.mp3", "VO_02.mp3", "VO_03.mp3"],
           "认 ` (N)` 和 `.mp3.mp3`，齐了按清单名字复制进 dest（%s）" % files)

        print("  -- 改坏的版本（应该被抓到）")
        src_code = io.open(dl, encoding="utf-8").read()
        bad = src_code.replace("if st.st_mtime < t0 - 1:", "if False:")
        assert bad != src_code
        bdl = os.path.join(tmp, "chatcut_dl_bad.py")
        write(bdl, bad)
        done, files, _, _, _ = dl_case(bdl, tmp, "b")
        ok(done, "不看 t0 时把旧同名文件当新的收了 —— 测试能分辨")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    test_runlog()
    test_dl()
    print()
    if FAILS:
        print("FAIL %d 条" % len(FAILS))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
