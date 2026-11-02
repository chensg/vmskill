# -*- coding: utf-8 -*-
"""长任务按步骤跑、写日志、能停干净。

    python runlog.py run <步骤文件> [--log 路径]   # 前台跑到完；Agent 用 run_in_background 起它
    python runlog.py status <步骤文件或日志>        # 在不在跑、跑到哪一步、最后几行
    python runlog.py stop <步骤文件或日志>          # 连子进程整棵树一起停

日志默认是步骤文件旁边的 `<步骤文件名>.log`；每步的完整输出在 `<日志>.d/NN_步骤名.log`，
主日志只记时间、步骤名、成败和每步最后几行，`tail` 一眼看得懂。

===== 步骤文件 =====

    # 注释
    == 收旁白
    cd .. && python 收旁白.py --src 素材
    python vo_trim.py apply
    == 段2
    cd ../build_s2
    for p in prep check a b c; do python make_story_h.py $p; done
    == ? 联络表            ← 「?」开头＝失败了也接着往下跑
    ffmpeg -y -i ../全片.mp4 ...

- `== 名字` 开一步，下面到下一个 `==` 为止是这一步的 bash 脚本（`set -e`：任一命令失败这步就失败）。
- 每步都从**步骤文件所在目录**起跑，`cd` 只在这一步内有效。
- 一步失败（不带 `?` 的），后面的都不跑，日志末行 `RUNLOG FAILED`；全部成功末行 `RUNLOG DONE`；
  被 `stop` 停掉末行 `RUNLOG STOPPED`。等它结束只看末行。
- 环境里预设 `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`（记忆 python-console-encoding）。

===== 为什么要这个 =====

2026-11-02《季子平安否》读音修正那一轮，手写的 `_v4.sh` 被 TaskStop 停掉，**停的只是外层 shell，
里面那个 bash 还活着**，自己一路跑完、拿新旧混着的章节拼了全片、覆盖了 `全片.mp4`；
同时我起的新脚本往**同一个日志**里写，日志里出现两个「合全片」，差点没看出来。还有：
旧脚本某章失败照样往下拼全片；每次都手写 `say()`、`: > $LOG`、`|| echo "!! 失败"` 那一套。

所以这里定死三件事：

1. **锁**：日志旁边有 `.pid`，那个进程还活着就拒绝再起一个（退出码 2）。
2. **停要停整棵树**：`stop` 在 Windows 上 `taskkill /T /F`，在别处杀进程组。
3. **一步失败就停**，不让下游拿半成品继续做（要容忍的步骤显式写 `?`）。
"""
import argparse
import io
import os
import re
import shutil
import signal
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

TAIL = 4


def find_bash():
    """Git Bash 优先。System32 / WindowsApps 下的 bash.exe 是 WSL，路径和 Python 对不上，不用。"""
    env = os.environ.get("RUNLOG_BASH")
    if env and os.path.exists(env):
        return env
    cands = []
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramW6432", "")):
            if base:
                cands += [os.path.join(base, "Git", "bin", "bash.exe"), os.path.join(base, "Git", "usr", "bin", "bash.exe")]
    w = shutil.which("bash")
    if w:
        cands.append(w)
    for c in cands:
        low = c.lower()
        if os.path.exists(c) and "system32" not in low and "windowsapps" not in low:
            return c
    sys.exit("!! 找不到 bash（Windows 上要装 Git for Windows，或设 RUNLOG_BASH）")


def parse(path):
    steps, cur = [], None
    for ln in io.open(path, encoding="utf-8-sig"):
        m = re.match(r"^==\s*(\?)?\s*(.+?)\s*$", ln)
        if m:
            cur = {"name": m.group(2), "optional": bool(m.group(1)), "body": []}
            steps.append(cur)
        elif cur is not None:
            cur["body"].append(ln.rstrip("\r\n"))
        elif ln.strip() and not ln.lstrip().startswith("#"):
            sys.exit("!! 第一个 `== 步骤名` 之前有命令：%r" % ln.strip())
    steps = [s for s in steps if any(b.strip() and not b.strip().startswith("#") for b in s["body"])] or steps
    if not steps:
        sys.exit("!! %s 里没有步骤（用 `== 名字` 开一步）" % path)
    return steps


def log_of(target):
    """命令行给的是步骤文件还是日志，都换成日志路径。"""
    target = os.path.abspath(target)
    return target if target.endswith(".log") else target + ".log"


def alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_pid(log):
    try:
        return int(io.open(log + ".pid", encoding="utf-8").read().split()[0])
    except (OSError, ValueError, IndexError):
        return 0


def kill_tree(pid):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except OSError:
            pass


def safe(name):
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name)[:40]


def tail(path, n):
    try:
        lines = io.open(path, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return []
    return [l for l in lines if l.strip()][-n:]


def dur(s):
    s = int(s)
    return "%ds" % s if s < 60 else "%dm%02ds" % (s // 60, s % 60) if s < 3600 else "%dh%02dm" % (s // 3600, s % 3600 // 60)


def cmd_run(a):
    steps_path = os.path.abspath(a.steps)
    steps = parse(steps_path)
    log = os.path.abspath(a.log) if a.log else log_of(steps_path)
    old = read_pid(log)
    if old and old != os.getpid() and alive(old):
        print("!! 另一个 runlog 正在用这个日志跑（pid %d）。要换掉它先 `runlog.py stop %s`" % (old, log))
        sys.exit(2)
    bash = find_bash()
    cwd = os.path.dirname(steps_path)
    d = log + ".d"
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    io.open(log + ".pid", "w", encoding="utf-8").write("%d\n" % os.getpid())
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    L = io.open(log, "w", encoding="utf-8")

    def say(s):
        L.write(s + "\n")
        L.flush()
        print(s, flush=True)

    say("=== %s 开始 %s（%d 步，pid %d）" % (time.strftime("%m-%d %H:%M"), os.path.basename(steps_path), len(steps), os.getpid()))
    t_all, failed, soft = time.time(), None, []
    try:
        for i, s in enumerate(steps, 1):
            tag = "[%d/%d] %s" % (i, len(steps), s["name"])
            sh = os.path.join(d, "%02d_%s.sh" % (i, safe(s["name"])))
            out = sh[:-3] + ".log"
            io.open(sh, "w", encoding="utf-8", newline="\n").write("set -e\n" + "\n".join(s["body"]) + "\n")
            say("=== %s %s" % (time.strftime("%H:%M"), tag))
            t0 = time.time()
            with open(out, "wb") as fo:
                kw = {} if os.name == "nt" else {"start_new_session": True}
                rc = subprocess.call([bash, sh], cwd=cwd, env=env, stdout=fo, stderr=subprocess.STDOUT, **kw)
            for l in tail(out, TAIL):
                say("    " + l[:300])
            if rc == 0:
                say("    ✓ %s" % dur(time.time() - t0))
                continue
            if s["optional"]:
                say("    ! 失败（退出码 %d），这步标了 ?，接着跑 —— 全文 %s" % (rc, out))
                soft.append(s["name"])
                continue
            say("!!! %s %s 失败（退出码 %d）—— 全文 %s" % (time.strftime("%H:%M"), tag, rc, out))
            failed = s["name"]
            break
        if failed:
            say("RUNLOG FAILED  %s（总 %s）" % (failed, dur(time.time() - t_all)))
            rc_all = 1
        else:
            extra = "；容忍的失败：%s" % "、".join(soft) if soft else ""
            say("RUNLOG DONE  总 %s%s" % (dur(time.time() - t_all), extra))
            rc_all = 0
    finally:
        L.close()
        if read_pid(log) == os.getpid():
            os.remove(log + ".pid")
    sys.exit(rc_all)


def cmd_status(a):
    log = log_of(a.target)
    pid = read_pid(log)
    run = pid and alive(pid)
    lines = tail(log, 400)
    cur = [l for l in lines if l.startswith("=== ")]
    end = [l for l in lines if l.startswith("RUNLOG ")]
    if run:
        print("在跑（pid %d），当前：%s" % (pid, cur[-1][4:] if cur else "?"))
    elif end:
        print("已结束：%s" % end[-1])
    elif lines:
        print("没在跑，也没有结束标记 —— 被外力杀掉了（不是 runlog stop），产物别信")
    else:
        print("没有日志：%s" % log)
        sys.exit(1)
    for l in lines[-a.n:]:
        print("  " + l)


def cmd_stop(a):
    log = log_of(a.target)
    pid = read_pid(log)
    if not (pid and alive(pid)):
        print("没在跑（%s）" % log)
        return
    kill_tree(pid)
    for _ in range(20):
        if not alive(pid):
            break
        time.sleep(0.25)
    with io.open(log, "a", encoding="utf-8") as f:
        f.write("RUNLOG STOPPED  %s 被 runlog stop 停掉（连子进程）\n" % time.strftime("%H:%M"))
    try:
        os.remove(log + ".pid")
    except OSError:
        pass
    print("已停 pid %d 及其子进程" % pid if not alive(pid) else "!! pid %d 还活着" % pid)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("steps")
    r.add_argument("--log", default="")
    s = sub.add_parser("status")
    s.add_argument("target")
    s.add_argument("-n", type=int, default=12)
    t = sub.add_parser("stop")
    t.add_argument("target")
    a = ap.parse_args(argv)
    {"run": cmd_run, "status": cmd_status, "stop": cmd_stop}[a.cmd](a)


if __name__ == "__main__":
    main()
