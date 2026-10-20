# -*- coding: utf-8 -*-
"""Windows 上跑官方 YuE2 运行时的补丁（可重复执行）。

问题：Windows 版 PyTorch 2.10 没编译 FlashAttention；yue2/cuda_graph.py 的 attention_backend="auto"
只看 torch.ops.aten._flash_attention_forward 这个算子在不在（Windows 上注册了但没编进去）就选 flash，
一生成就报「USE_FLASH_ATTENTION was not enabled for build」。
改法：flash 的判定再加 torch.backends.cuda.is_flash_attention_available()；不可用时 auto 自然落到 cuDNN
（10-21 实测 cuDNN 注意力在这台 3090 上可用）。Linux 上这个函数返回 True，行为不变。

用法：D:\\yue2_runtime\\.venv\\Scripts\\python.exe D:\\yue2_runtime\\patch_windows.py
"""
import io
import os
import sys

import yue2

p = os.path.join(os.path.dirname(yue2.__file__), "cuda_graph.py")
s = io.open(p, encoding="utf-8").read()
old = 'flash = fused and config.head_dim <= 256 and hasattr(torch.ops.aten, "_flash_attention_forward") and ('
new = ('flash = fused and config.head_dim <= 256 and torch.backends.cuda.is_flash_attention_available() '
       'and hasattr(torch.ops.aten, "_flash_attention_forward") and (')
if new in s:
    print("已经打过补丁：%s" % p)
    sys.exit(0)
if old not in s:
    sys.exit("!!! cuda_graph.py 里找不到要改的那一行（yue2-infer 版本变了？）：%s" % p)
io.open(p, "w", encoding="utf-8", newline="").write(s.replace(old, new, 1))
print("补丁已打：%s" % p)
