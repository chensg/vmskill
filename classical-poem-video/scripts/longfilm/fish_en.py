# -*- coding: utf-8 -*-
"""英文旁白：讲述稿_en.md（`ID. text` 一行一句）→ Fish s2-pro → 原件 <out>/raw/，提亮 EQ 后 <out>/<ID>.mp3。
参数照《寒席》但 speed 0.95（0.80 塞不进中文槽，11-02 实测 2.35 词/秒）（s2-pro / temp 0.65 / top_p 0.7 / rep 1.2）；音色 FishTTSVoiceIdEn，缺了回退 FishTTSVoiceId。
EQ 照记忆 fish-english-voice-needs-clarity-eq。已有的跳过。
python fish_en.py <讲述稿_en.md> <输出目录> [--prefix VO_]"""
import io, json, os, re, subprocess, sys, time, urllib.error, urllib.request
sys.stdout.reconfigure(encoding="utf-8")
API = "https://api.fish.audio/v1/tts"
EQ = "highpass=f=90,equalizer=f=220:t=q:w=1:g=-2,equalizer=f=1100:t=q:w=0.9:g=3.5,equalizer=f=3000:t=q:w=1.2:g=3.5"
TTS_FIX = [("Hanke", "Hahn-kuh"), ("Han Rizuan", "Hahn Rr-dzwahn"), ("Han Zonglai", "Hahn Zong-lie"), ("Han ", "Hahn "), ("Han,", "Hahn,"),
           ("Luyong", "Loo-yong"), ("Daoguang", "Dow-gwahng"), ("Boluo", "Bwo-lwo"), ("Guangdong", "Gwahng-dong"),
           ("Shengjing", "Shung-jing"), ("Shenyang", "Shun-yahng"), ("Shengren", "Shung-ren"),
           ("Hong Chengchou", "Hong Chung-joe"), ("Daodu", "Dow-doo"), ("Zhaozhou", "Jao-joe"), ("Zhencheng", "Jen-chung"),
           ("Chen Zhilin", "Chun Jir-lin"), ("Wu Zhaoqian", "Woo Jao-chyen"), ("Ningguta", "Ning-goo-tah"),
           ("Qianshan", "Chyen-shahn"), ("Guzhu", "Goo-joo"), ("Shouyang", "Show-yahng"), ("Bo Yi", "Bwo Yee"), ("Shu Qi", "Shoo Chee"),
           ("Yongping", "Yong-ping"), ("Liaodong", "Lyao-dong"), ("Luofu", "Lwo-foo"), ("Puji", "Poo-jee"), ("Caodong", "Tsao-dong"),
           ("Axiang", "Ah-shyahng"), ("Bashan", "Bah-shahn"), ("Zhang Dayou", "Jahng Dah-yo"), ("Dongguan", "Dong-gwahn"),
           ("Shanhai", "Shahn-hy"), ("Mount Lu,", "Mount Loo,"), ("Mount Lu.", "Mount Loo."), ("Suzhou", "Soo-joe"),
           ("Qing", "Ching")]


def env_ci(name):
    for k, v in os.environ.items():
        if k.casefold() == name.casefold() and v.strip():
            return v.strip()
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        i = 0
        while True:
            try:
                n, v, _ = winreg.EnumValue(key, i)
            except OSError:
                return ""
            if n.casefold() == name.casefold() and str(v).strip():
                return str(v).strip()
            i += 1


def tts_text(s):
    for a, b in TTS_FIX:
        s = s.replace(a, b)
    return s


def main():
    script, out = sys.argv[1], sys.argv[2]
    prefix = sys.argv[sys.argv.index("--prefix") + 1] if "--prefix" in sys.argv else ""
    key = env_ci("FIshTTSKey"); voice = env_ci("FishTTSVoiceIdEn") or env_ci("FishTTSVoiceId")
    assert key and voice, "缺 FIshTTSKey / FishTTSVoiceId"
    body = io.open(script, encoding="utf-8").read().split("---", 1)[1]
    lines = re.findall(r"^(\w+)\.\s+(.+\S)\s*$", body, re.M)
    raw = os.path.join(out, "raw"); os.makedirs(raw, exist_ok=True)
    for sid, text in lines:
        name = prefix + sid
        rp, fp = os.path.join(raw, name + ".mp3"), os.path.join(out, name + ".mp3")
        if not os.path.exists(rp):
            payload = {"text": tts_text(text), "format": "mp3", "mp3_bitrate": 128, "normalize": True, "latency": "normal",
                       "reference_id": voice, "sample_rate": 44100, "temperature": 0.65, "top_p": 0.7,
                       "repetition_penalty": 1.2, "prosody": {"speed": 0.95, "volume": 0, "normalize_loudness": True}}
            req = urllib.request.Request(API, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
                                         headers={"Authorization": "Bearer " + key, "Content-Type": "application/json", "model": "s2-pro"})
            for k in range(3):
                try:
                    a = urllib.request.urlopen(req, timeout=180).read()
                    assert len(a) > 512
                    open(rp, "wb").write(a); break
                except Exception as e:
                    print("  重试", name, e); time.sleep(3 * (k + 1))
            else:
                print("!! 失败", name); continue
        if not os.path.exists(fp):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", rp, "-af", EQ, "-b:a", "192k", fp], check=True)
        print("ok", name, flush=True)
    print("FISHDONE", len(lines))


main()
