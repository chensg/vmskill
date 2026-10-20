# -*- coding: utf-8 -*-
"""讲述片旁白：ElevenLabs 逐条生成 + scribe 转写核对（中英两条线）。

    python el_tts.py gen zh [VO_001 ...]     # 不给名字＝只补 vo/ 里缺的；给名字＝重出这几条
    python el_tts.py gen en [VO_001 ...]     # 英文：读 ../讲述稿_en.md 的「NNN. 文本」或「NNx. 文本」
    python el_tts.py asr zh|en [VO_001 ...]  # 转写，存 vo_asr.json / vo_en_asr.json，只列要人看的
    python el_tts.py credits                 # 账户剩多少额度

之后：python vo_trim.py apply（英文 apply vo_en）→ make_story_*.py sync / langfit。

**这个文件是从五支片子里抄来抄去的 vo_el.py / vo_en_gen.py / asr_diff.py 归位来的**
（风之电话 → 史可法 → 刘连仁 → 海底四十小時，每支一份，配置写死在代码里）。
项目差异放 build/tts_fix.json，不改代码：

    {"zh": {"fix":     {"VO_050": "送进 TTS 的字（字幕不变）"},
            "seed":    {"VO_106": 77},
            "no_prev": ["VO_013"]},
     "en": {"model": "eleven_v4_turbo", "seed": {"VO_081": 2077}}}

==== 定死的配置（2026-10-18 起频道用这一套，见 references/storytelling.md 第八节〇）====
  中文  eleven_v4 · Jerry Lin（台湾腔）YBS7vt5CeZiqlZYGamwR
  英文  eleven_v4 · David - Documentary ppLqTilh7rH7fbUVlXsf（额度紧时 eleven_v4_turbo，半价）
  只给 previous_text，**不给 next_text**（会把下一句的字渗进句尾）。
  一句一条：一条 mp3 = 讲述稿一行 = 一条字幕。

==== 转写核对为什么要分类 ====
scribe 出简体＋阿拉伯数字，逐字比会把同音写法全报出来：《海底四十小時》138 条报了 60 条，
「角鯊→绞杀」「納昆→那坤」「艇裡→亭里」（三声变调）这种占了九成，真读错的只有 7 条。
所以按拼音分：同音（只是写法不同）不报；只差声调且是 3-3 变调不报；其余列出来。
英文同理：数字写法（240 / two hundred forty）不报。整条转写成外文或 [背景音乐] 之类 = **乱码**，换 seed 重出。
"""
import json
import os
import re
import sys
import urllib.request
import uuid

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
VOICE = {"zh": "YBS7vt5CeZiqlZYGamwR", "en": "ppLqTilh7rH7fbUVlXsf"}
MODEL = {"zh": "eleven_v4", "en": "eleven_v4"}
DIRS = {"zh": ("vo", "vo_orig", "vo_raw"), "en": ("vo_en", "vo_en_orig", "vo_en_raw")}   # (成品, vo_trim 备份, langfit/vofit 原件)
DEFAULT_SEED = 1018


def key():
    k = os.environ.get("ElevenlabsKEY")
    if k:
        return k
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as h:
            return winreg.QueryValueEx(h, "ElevenlabsKEY")[0]
    except Exception:
        sys.exit("!!! 找不到 ElevenlabsKEY（环境变量或注册表 HKCU\\Environment）")


def call(path, body=None, raw=False):
    req = urllib.request.Request("https://api.elevenlabs.io" + path, method="POST" if body is not None else "GET",
                                 headers={"xi-api-key": key(), "Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    return data if raw else json.loads(data)


def fixes():
    p = os.path.join(HERE, "tts_fix.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def lines(lang):
    """[(vo, 送进 TTS 的文字)]。中文读 narr.json；英文按编号对上 ../讲述稿_en.md。"""
    narr = json.load(open(os.path.join(HERE, "narr.json"), encoding="utf-8"))
    cfg = fixes().get(lang, {})
    if lang == "zh":
        # 年份「二〇一一」送 TTS 一律写成「二零一一」（字幕不变）：2026-10-20 豆包把「二〇一一年」读成「二千一一年」，
        # 而转写会把两种读法都写成「2011年」，核对拦不住。ElevenLabs 读「零」也对，所以默认就换。
        out = [(n["vo"], cfg.get("fix", {}).get(n["vo"], n["txt"].replace("〇", "零"))) for n in narr]
    else:
        en = dict(re.findall(r"^(\d{2,3}[a-g]?)\. (.+)$",
                             open(os.path.join(HERE, "..", "讲述稿_en.md"), encoding="utf-8").read(), re.M))
        miss = [n["vo"] for n in narr if n["vo"][3:] not in en]
        if miss:
            sys.exit("!!! 讲述稿_en.md 缺这几条：%s" % " ".join(miss[:10]))
        out = [(n["vo"], cfg.get("fix", {}).get(n["vo"], en[n["vo"][3:]])) for n in narr]
    return [(v, t.replace("｜", "" if lang == "zh" else " ")) for v, t in out]


def gen(lang, names):
    cfg = fixes().get(lang, {})
    model = cfg.get("model", MODEL[lang])
    vo_dir, orig_dir, raw_dir = DIRS[lang]
    os.makedirs(os.path.join(HERE, vo_dir), exist_ok=True)
    rows = lines(lang)
    n_chars = 0
    for i, (vo, txt) in enumerate(rows):
        out = os.path.join(HERE, vo_dir, vo + ".mp3")
        if names and vo not in names:
            continue
        if not names and os.path.exists(out):
            continue
        # 重出：同名旧件一起删 —— vo_trim 会从 _orig 剪、langfit/vofit 会从 _raw 推导，
        # 旧件留着就会把旧录音写回来（2026-10-18 记忆 elevenlabs-v4-tts、《海底四十小時》vo_trim）。
        if names:
            for d in (orig_dir, raw_dir):
                old = os.path.join(HERE, d, vo + ".mp3")
                if os.path.exists(old):
                    os.remove(old)
        prev = rows[i - 1][1] if i and vo not in cfg.get("no_prev", []) else None
        body = dict(text=txt, model_id=model, language_code=lang, seed=cfg.get("seed", {}).get(vo, DEFAULT_SEED))
        if prev:
            body["previous_text"] = prev
        a = call("/v1/text-to-speech/%s?output_format=mp3_44100_128" % VOICE[lang], body, raw=True)
        open(out, "wb").write(a)
        n_chars += len(txt)
        print(vo, len(a), flush=True)
    print("生成 %d 字（%s，约 %.0f credits）" % (n_chars, model, n_chars * (0.5 if "turbo" in model or "flash" in model else 1.0)))


def scribe(path, lang):
    b = uuid.uuid4().hex
    body = (("--%s\r\nContent-Disposition: form-data; name=\"model_id\"\r\n\r\nscribe_v1\r\n"
             "--%s\r\nContent-Disposition: form-data; name=\"language_code\"\r\n\r\n%s\r\n"
             "--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.mp3\"\r\n"
             "Content-Type: audio/mpeg\r\n\r\n") % (b, b, "zho" if lang == "zh" else "eng", b)).encode() \
        + open(path, "rb").read() + ("\r\n--%s--\r\n" % b).encode()
    req = urllib.request.Request("https://api.elevenlabs.io/v1/speech-to-text", data=body, method="POST",
                                 headers={"xi-api-key": key(), "Content-Type": "multipart/form-data; boundary=%s" % b})
    return json.load(urllib.request.urlopen(req, timeout=120))["text"]


# ---------------------------------------------------------------- 分类
def _garbled(lang, asr):
    """整条转写不像这门语言：乱码（TTS 偶发，换 seed 就好）。"""
    t = asr.strip()
    if not t or re.fullmatch(r"[\[\(（【].*[\]\)）】]", t):
        return True
    if lang == "zh":
        cjk = len(re.findall(r"[一-鿿]", t))
        return cjk < max(2, 0.4 * len(re.sub(r"[\s\W\d_]", "", t)))
    letters = re.sub(r"[^A-Za-z]", "", t)
    return len(letters) < 0.6 * len(re.sub(r"[\s\W\d_]", "", t))


_SAME = str.maketrans({"著": "着", "〇": "零", "裡": "里", "裏": "里", "臺": "台"})   # 台湾用字的「著」就是「着」


def _readings(ch, tone):
    """一个字所有可能的读音（多音字全取）。没装 pypinyin 时返回 None。"""
    try:
        from pypinyin import pinyin, Style
    except ImportError:
        return None
    r = pinyin(ch, style=Style.TONE3 if tone else Style.NORMAL, heteronym=True, neutral_tone_with_five=True)[0]
    out = set(r)
    if tone:   # 轻声和本调互通：「得 de2 / 的 de5」不算错
        out |= {x[:-1] + "5" for x in r if x[-1:].isdigit()}
    return out


def classify_zh(src, asr):
    """返回 (类别, 说明)。类别：same / homophone / sandhi / number / year / tone / suspect / garbled。

    逐字比读音：两边的字只要有一个共同读音（多音字全取、轻声和本调互通）就是同音写法；
    只差声调的看是不是 3-3 变调；读音完全不同、多读、漏读才算可疑。
    """
    import difflib
    circle = "〇" in src            # 归一化会把「〇」换成「零」，要在这之前记下来（见下面 year 那条）
    try:
        import opencc
        src = opencc.OpenCC("t2s").convert(src)
    except ImportError:
        pass
    norm = lambda t: re.sub(r"[^一-鿿0-9]", "", t.translate(_SAME))
    a, b = norm(src), norm(asr)
    if a == b:
        return "same", ""
    if _garbled("zh", asr):
        return "garbled", "转写不像中文 → 换 seed 重出"
    if _readings("测", False) is None:
        return "suspect", "（没装 pypinyin，无法判同音）"
    from pypinyin import lazy_pinyin, Style
    tone3 = lambda t: [x if x[-1:].isdigit() else x + "5" for x in
                       lazy_pinyin(t, style=Style.TONE3, neutral_tone_with_five=True, errors=lambda c: ["?"] * len(c))]
    PA, PB = tone3(a), tone3(b)
    if len(PA) != len(a) or len(PB) != len(b):      # 对不齐（不该发生）就退回逐字
        PA = [tone3(c)[0] for c in a]
        PB = [tone3(c)[0] for c in b]
    rank = ["homophone", "sandhi", "number", "year", "tone", "suspect"]
    worst, notes = "homophone", []
    nums = set("零〇一二三四五六七八九十百千万两")
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if op == "equal":
            continue
        x, y = a[i1:i2], b[j1:j2]
        if re.search(r"[0-9]", x + y) or (x and set(x) <= nums and (not y or set(y) <= nums)):
            # 送进 TTS 的字里还有「〇」：豆包会把「二〇一一」读成「二千一一」，而转写两种读法都写成「2011」，
            # 这一类转写**证明不了读音**，要人听（2026-10-20《我想回家》漏过一次）。lines() 现在默认换成「零」，
            # 这条只在 tts_fix.json 手写了「〇」、或核对别处生成的旁白时才会响。只认「〇」：一九四三这类年份没出过事，
            # 全报会让每支片子多十几条要人听的噪音。
            cat = "year" if circle and "零" in x and re.search(r"\d", y) else "number"
        elif len(x) != len(y) or not x:
            cat = "suspect"                    # 多读 / 漏读 / 读串了
        else:
            # **按上下文读音比，不按多音字的读音集合比**：集合一取交集，「壓載→鴨仔」「杜父→杜甫」就被放行了，
            # 而多音字选错读音恰恰是中文 TTS 最常见的错。原文用 pypinyin 的词组读音（壓載 zài），
            # 转写那边也按它自己的词组读（鴨仔 zǎi）；只差声调 → tone（要人听），三声连读的前一个变二声 → sandhi。
            cats = []
            for k in range(len(x)):
                ra, rb = PA[i1 + k], PB[j1 + k]
                if ra == rb or (ra[:-1] == rb[:-1] and "5" in (ra[-1:], rb[-1:])):
                    cats.append("homophone")
                elif ra[:-1] == rb[:-1]:
                    nxt = PA[i1 + k + 1] if i1 + k + 1 < len(PA) else ""
                    cats.append("sandhi" if ra.endswith("3") and rb.endswith("2") and nxt.endswith("3") else "tone")
                else:
                    cats.append("suspect")
            cat = max(cats, key=rank.index)
        notes.append("%s→%s(%s)" % (x or "∅", y or "∅", cat))
        if rank.index(cat) > rank.index(worst):
            worst = cat
    return worst, "；".join(notes)


_NUMW = set("""zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen
seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand million and a
first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth twentieth thirtieth
am pm st nd rd th oclock""".split())


def classify_en(src, asr):
    """英文：逐词比。差异两边都只是数字 / 数字词（240 ↔ two hundred forty、19th ↔ nineteenth）→ number；
    其余（Her → Our、漏词、多词）→ suspect。整条不像英文 → garbled。"""
    import difflib
    norm = lambda t: re.sub(r"[^a-z0-9 ]", " ", t.lower().replace("-", " ").replace(".", "")).split()
    a, b = norm(src), norm(asr)
    if a == b:
        return "same", ""
    if _garbled("en", asr):
        return "garbled", "转写不像英文 → 换 seed 重出"
    isnum = lambda ws: all(w.isdigit() or re.fullmatch(r"\d+(st|nd|rd|th|s)?", w) or w in _NUMW for w in ws)
    worst, notes = "number", []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if op == "equal":
            continue
        x, y = a[i1:i2], b[j1:j2]
        cat = "number" if (x or y) and isnum(x) and isnum(y) and any(re.search(r"\d", w) for w in x + y) else "suspect"
        notes.append("%s→%s(%s)" % (" ".join(x) or "∅", " ".join(y) or "∅", cat))
        if cat == "suspect":
            worst = "suspect"
    return worst, "；".join(notes)


def asr(lang, names):
    vo_dir = DIRS[lang][0]
    src = dict(lines(lang))
    narr_txt = {n["vo"]: n["txt"].replace("｜", "") for n in json.load(open(os.path.join(HERE, "narr.json"), encoding="utf-8"))}
    p = os.path.join(HERE, "vo_asr.json" if lang == "zh" else "vo_en_asr.json")
    res = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    for vo in src:
        f = os.path.join(HERE, vo_dir, vo + ".mp3")
        if (names and vo not in names) or not os.path.exists(f):
            continue
        res[vo] = dict(src=narr_txt[vo] if lang == "zh" else src[vo], tts=src[vo], asr=scribe(f, lang))
    json.dump(res, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    shown, counts = 0, {}
    if lang == "zh" and _readings("测", False) is None:
        print("** 没装 pypinyin：同音字没法自动放行，全部列出（pip install pypinyin）")
    for vo, r in sorted(res.items()):
        if names and vo not in names:
            continue
        cat, why = (classify_zh(r["tts"], r["asr"]) if lang == "zh" else classify_en(r["tts"], r["asr"]))
        counts[cat] = counts.get(cat, 0) + 1
        if cat in ("suspect", "tone", "garbled", "year"):
            shown += 1
            print("%s %-8s %s ｜ASR: %s" % (vo, cat, why, r["asr"]))
    print("分类：%s；要人看的 %d 条" % ("，".join("%s %d" % kv for kv in sorted(counts.items())), shown))


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("gen", "asr", "credits"):
        print(__doc__); sys.exit(1)
    if sys.argv[1] == "credits":
        s = call("/v1/user/subscription")
        print("%s：已用 %d / %d，剩 %d" % (s["tier"], s["character_count"], s["character_limit"], s["character_limit"] - s["character_count"]))
        sys.exit(0)
    lang = sys.argv[2] if len(sys.argv) > 2 else "zh"
    if lang not in ("zh", "en"):
        sys.exit("!!! 语言只有 zh / en")
    (gen if sys.argv[1] == "gen" else asr)(lang, sys.argv[3:])
