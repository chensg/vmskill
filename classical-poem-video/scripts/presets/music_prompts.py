# -*- coding: utf-8 -*-
"""__TITLE__ 的配乐描述（本机 MiniMax Music3）。由 `episode.py new --type long` 生成，放在 build/，mm_music.py 读它。

一个部分一条：部分 1＝冷开场＋第一章，部分 N＝第 N 章（和 film.py 的分段一致）。出来的文件叫
素材/配乐/MM_段N_k.mp3，film.py 每段把候选接起来、不够长就循环。

    python mm_music.py 1 2 3 4 5 [--k 1] [--seed 101]
"""
# 各段共用的一段：乐器、结构、用途。只留一件乐器、写明没有人声，出来才干净。
TAIL = ("Instrumentation: 純器樂，只有古琴一件樂器，沒有人聲，沒有哼唱，沒有合唱，沒有吟唱，沒有吹管樂器，沒有鼓和打擊樂。\n"
        "Structure: 全曲約四分鐘，一直維持同樣的安靜情緒，沒有高潮。\n"
        "Role: 紀錄片旁白底下的配樂，音量起伏小，不搶旁白，段落之間沒有突然的爆發。")

# 填：每段一句情绪 + 一句编排
CAP = {
    1: "Global Metadata: 中國古風純器樂，古琴獨奏，慢板約 60 BPM，填：這一段的情緒。\nArrangement: 填：怎麼彈。",
    # 2: "…",
}

# 每段要多少秒：比那一段的片长略长即可（`python film.py check` 第一行有各段秒数）
SECS = {1: 240}
