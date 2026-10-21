"""回归：el_web_image.py 读出图任务书。

    python tests/test_el_web_image.py

2026-10-19《冷山》：sync 量出三镜一张静帧停 16~21 秒，补三张图拆镜，档名写 04a_北狩 ——
任务书的行正则只认「两位数字 + _」，这三行被**静默跳过**（list 少三张、show 报 KeyError）。
这里造一份最小任务书，验带字母后缀的档名读得到、描述替换和结尾选择没坏；
并且验：把正则改回老样子，这套测试会红。
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

BRIEF = """# 出圖任務書 · 測試

## 固定開頭

> 寫實電影劇照，豎構圖 9:16。

**夜裡的鏡另加一句**（表裡標「夜」）：「夜裡，但畫面不能暗。」

## 固定結尾 A（有人）

> 人物不露正臉。

## 固定結尾 E（沒有人）

> 畫面裡沒有任何人物。

- **（主角）**：一個清瘦的宋朝男子

| 檔 | 鏡 | 結尾 | 畫面句 |
|---|---|---|---|
| ★01_火 | 1 | 夜 A | 雪夜，（主角）蹲在火前。 |
| 04a_北狩 | 4 | A | 雪原上一列隊伍往北走。 |
| 06b_鼎鑊 | 6 | E | 一口大鍋架在火上。 |
| 102a_晚飯 | 102 | E | 長桌上點著一串堅果燈。 |
"""


def ok(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        FAILS.append(what)


def run(script_src):
    tmp = tempfile.mkdtemp(prefix="el_web_image_")
    try:
        os.makedirs(os.path.join(tmp, "build"))
        os.makedirs(os.path.join(tmp, "素材", "生成"))
        open(os.path.join(tmp, "出图任务书.md"), "w", encoding="utf-8").write(BRIEF)
        dst = os.path.join(tmp, "build", "el_web_image.py")
        open(dst, "w", encoding="utf-8").write(script_src)

        def call(*a):
            r = subprocess.run([sys.executable, dst] + list(a), capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            return r.returncode, r.stdout + r.stderr

        rc, out = call("list")
        names = re.findall(r"(\d{2,3}[a-z]?_\S+)", out)
        ok(rc == 0 and "01_火" in names, "list 读到普通档名 01_火")
        ok("04a_北狩" in names and "06b_鼎鑊" in names, "list 读到带字母后缀的档名（04a_北狩、06b_鼎鑊）")
        # 2026-10-21《海圖上找不到的島》112 镜：镜号过百，102a_ 也被静默跳过（list 少 18 张）
        ok("102a_晚飯" in names, "list 读到三位数镜号的档名（102a_晚飯）")
        rc, out = call("show", "04a_北狩")
        ok(rc == 0 and "雪原上一列隊伍往北走" in out and "人物不露正臉" in out, "show 04a_北狩：画面句 + 结尾 A")
        rc, out = call("show", "06b_鼎鑊")
        ok(rc == 0 and "畫面裡沒有任何人物" in out, "show 06b_鼎鑊：结尾 E")
        rc, out = call("show", "01_火")
        ok(rc == 0 and "夜裡，但畫面不能暗" in out and "一個清瘦的宋朝男子" in out, "show 01_火：夜句 + 描述替换")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    src = open(os.path.join(SCRIPTS, "el_web_image.py"), encoding="utf-8").read()
    print("== el_web_image：真脚本")
    run(src)
    real = list(FAILS)

    print("== el_web_image：故意改坏（档名正则改回只认两位数字），这一段应当出 FAIL")
    broken, n = re.subn(r"\\d\{2,3\}\[a-z\]\?_", r"\\d\\d_", src)
    ok(n >= 1, "改坏的副本确实改到了档名正则（替换 %d 处）" % n)
    before = len(FAILS)
    run(broken)
    caught = len(FAILS) - before
    del FAILS[before:]
    ok(caught > 0, "改坏的脚本被测试抓到（%d 条 FAIL）" % caught)

    print()
    if FAILS or real:
        print("FAIL %d 条" % len(FAILS))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
