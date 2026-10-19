#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Contact sheet of eye captures: contact_sheet.py OUT.png DIR name [name...] (uses <name>-left.ppm)."""
import sys
from pathlib import Path
from PIL import Image

out, d, names = sys.argv[1], Path(sys.argv[2]), sys.argv[3:]
ims = [Image.open(d / f'{n}-left.ppm').convert('RGB') for n in names if (d / f'{n}-left.ppm').is_file()]
w, h = ims[0].size
W = 420; H = int(h * W / w)
cols = min(3, len(ims))
sheet = Image.new('RGB', (W * cols, H * ((len(ims) + cols - 1) // cols)))
for k, im in enumerate(ims):
    sheet.paste(im.resize((W, H)), ((k % cols) * W, (k // cols) * H))
sheet.save(out)
