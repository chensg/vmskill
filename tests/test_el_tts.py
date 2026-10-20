"""回归：el_tts.py 转写核对的分类（离线，不调接口）。

    python tests/test_el_tts.py

样本全是《海底四十小時》（2026-10-18）的真实转写：同音写法、三声变调要放行；
多音字选错读音、读成别的字、乱码要报出来。要 pypinyin（没装就跳过并说明）。
"""
import importlib.util
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.environ.get("VMSKILL_SCRIPTS") or os.path.join(ROOT, "classical-poem-video", "scripts")
FAILS = []


def ok(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        FAILS.append(what)


def main():
    try:
        import pypinyin  # noqa: F401
    except ImportError:
        print("没装 pypinyin，跳过（pip install pypinyin）")
        return 0
    spec = importlib.util.spec_from_file_location("el_tts", os.path.join(SCRIPTS, "el_tts.py"))
    el = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(el)
    print("== 中文：要放行的")
    for src, asr, want in [("角鯊號是美國海軍最新的潛艇", "绞杀号是美国海军最新的潜艇", "homophone"),
                           ("納昆下令", "那坤下令", "homophone"),
                           ("海水滲進電池會冒出氯氣", "海水渗进电池会冒出绿气", "homophone"),
                           ("艇裡又黑、又冷、又濕。", "亭里又黑又冷又湿", "sandhi"),
                           ("一九四三年十一月十九日", "1943年11月19日", "number"),
                           ("一九四〇年五月", "一九四零年五月", "same"),
                           ("隔著艇殼", "隔着艇壳", "same")]:
        cat, why = el.classify_zh(src, asr)
        ok(cat == want, "%s → %s：%s（应 %s）%s" % (src[:10], asr[:10], cat, want, why))
    print("== 中文：要报的")
    for src, asr, want in [("到了七月十三日，浮筒充氣。", "到了前月十三日，浮筒充气。", "suspect"),
                           ("要是瞭望哨那一眼沒看到", "那是瞭望哨那一眼没看到", "suspect"),
                           ("先往鐘的壓載艙裡吹一點氣", "先往钟的鸭仔舱里吹一点气", "tone"),
                           ("杜父魚號撈起了那個浮標", "杜甫于浩捞起了那个浮标", "tone"),
                           # 《我想回家》：豆包读成「二千一一年」，转写照样是「2011年」—— 这种只能人听
                           ("二〇一一年三月十一日，", "2011年3月11日", "year"),
                           ("今天，那座指揮塔還立在造船廠的草坪上", "вшая. personalize of R", "garbled")]:
        cat, why = el.classify_zh(src, asr)
        ok(cat == want, "%s → %s：%s（应 %s）%s" % (src[:10], asr[:10], cat, want, why))
    print("== 英文")
    for src, asr, want in [("She lies 240 feet down.", "She lies two hundred forty feet down.", "number"),
                           ("Its cable motor turns once, then jams.", "[outro jingle]", "garbled"),
                           ("Her captain is killed.", "Our captain is killed.", "suspect"),
                           ("Then the phone rings.", "Then the phone rings", "same")]:
        cat, why = el.classify_en(src, asr)
        ok(cat == want, "%s：%s（应 %s）%s" % (src[:24], cat, want, why))
    print("\n%s" % ("全部通过" if not FAILS else "失败 %d 条" % len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
