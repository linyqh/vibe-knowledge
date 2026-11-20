#!/usr/bin/env python3
"""长卷：把几段 16:9 生图从右往左羽化拼成一整条横卷（generate_image 最宽只有 16:9）。
用法：python3 stitch_scroll.py <输出.jpg> <最右段.png> <中段.png> [<最左段.png> …] [--overlap 160] [--h 1080]
- 参数顺序 = 卷轴读的顺序（中国长卷从右往左读）：第 1 张放最右，后面每张接在上一张左边。
- 每张先按高度缩放到 --h；相邻两张重叠 --overlap 像素，重叠区按横向线性透明度渐变混合。
- 生图时第 2、3 段把上一段作为 generate_image 的 input 续画（「continue the scene to the left」），拼缝才接得上；拼完先看拼缝。
- 打印输出宽度，film.js 里卷宽 W 用这个数。"""
import sys

import numpy as np
from PIL import Image


def arg(n, d):
    if n in sys.argv:
        i = sys.argv.index(n)
        v = sys.argv[i + 1]
        del sys.argv[i:i + 2]
        return v
    return d


ov, H = int(arg("--overlap", "160")), int(arg("--h", "1080"))
if len(sys.argv) < 4:
    sys.exit(__doc__)
out, srcs = sys.argv[1], sys.argv[2:]
panels = []
for p in srcs:
    im = Image.open(p).convert("RGB")
    panels.append(np.asarray(im.resize((round(im.width * H / im.height), H), Image.LANCZOS), np.float32))
if any(p.shape[1] <= 2 * ov for p in panels):
    sys.exit(f"--overlap {ov} 太大：每段缩放后宽度要大于 {2 * ov}")

# 从最左段开始往右接：canvas 的右边缘重叠区跟下一段（更靠右）的左边缘混合
canvas = panels[-1]
ramp = np.linspace(0, 1, ov, dtype=np.float32)[None, :, None]  # 0 = 全是左边那张，1 = 全是右边那张
for right in reversed(panels[:-1]):
    blend = canvas[:, -ov:] * (1 - ramp) + right[:, :ov] * ramp
    canvas = np.concatenate([canvas[:, :-ov], blend, right[:, ov:]], axis=1)

Image.fromarray(canvas.clip(0, 255).astype(np.uint8)).save(out, quality=92)
print(canvas.shape[1])
