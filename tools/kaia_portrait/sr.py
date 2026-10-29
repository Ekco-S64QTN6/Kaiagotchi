"""4x real-world super-resolution of an image crop with Swin2SR (GPU), tiled to bound VRAM."""
import sys

import numpy as np
import torch
from PIL import Image
from transformers import AutoImageProcessor, Swin2SRForImageSuperResolution

src, box, out = sys.argv[1], [int(v) for v in sys.argv[2].split(",")], sys.argv[3]
name = "caidas/swin2SR-realworld-sr-x4-64-bsrgan-psnr"
proc = AutoImageProcessor.from_pretrained(name)
model = Swin2SRForImageSuperResolution.from_pretrained(name).to("cuda").half().eval()

img = Image.open(src).convert("RGB").crop(tuple(box))
W, H = img.size
T, PAD = 192, 16
res = np.zeros((H * 4, W * 4, 3), np.float32)
for y in range(0, H, T):
    for x in range(0, W, T):
        x0, y0 = max(0, x - PAD), max(0, y - PAD)
        x1, y1 = min(W, x + T + PAD), min(H, y + T + PAD)
        tile = img.crop((x0, y0, x1, y1))
        inp = proc(tile, return_tensors="pt").pixel_values.to("cuda").half()
        with torch.no_grad():
            o = model(pixel_values=inp).reconstruction[0].float().clamp(0, 1).cpu().numpy()
        o = np.transpose(o, (1, 2, 0))[: (y1 - y0) * 4, : (x1 - x0) * 4]
        ix, iy = (x - x0) * 4, (y - y0) * 4
        w, h = min(T, W - x) * 4, min(T, H - y) * 4
        res[y * 4 : y * 4 + h, x * 4 : x * 4 + w] = o[iy : iy + h, ix : ix + w]
Image.fromarray((res * 255).round().astype(np.uint8)).save(out)
print("saved", out, res.shape)
