"""Codec portrait asset pipeline:
crop (x,y,w,h) -> Swin2SR 4x -> resize to target height -> BiRefNet matte -> MediaPipe landmarks
-> kaia_codec.webp + kaia_rig.json (+ face-only debug overlay)."""
import json
import subprocess
import sys

import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision
from PIL import Image, ImageDraw
from rembg import new_session, remove

src, box, outdir, model, sr_script, label = sys.argv[1:7]
x, y, w, h = [int(v) for v in box.split(",")]
TARGET_H = 840

sr_path = f"{outdir}/sr.png"
subprocess.run([sys.executable, "-I", sr_script, src, f"{x},{y},{x + w},{y + h}", sr_path], check=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
img = Image.open(sr_path).convert("RGB")
img = img.resize((round(img.width * TARGET_H / img.height), TARGET_H), Image.LANCZOS)
W, H = img.size

mask = remove(img, session=new_session("birefnet-portrait"), only_mask=True)
rgba = img.copy()
rgba.putalpha(mask)
rgba.save(f"{outdir}/kaia_codec.webp", quality=92, method=6)

det = vision.FaceLandmarker.create_from_options(
    vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=model), num_faces=1))
lm = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(img))).face_landmarks[0]
idx = {
  "eyeR_outer": 33, "eyeR_inner": 133, "eyeR_top": 159, "eyeR_bot": 145,
  "eyeL_outer": 263, "eyeL_inner": 362, "eyeL_top": 386, "eyeL_bot": 374,
  "irisR": 468, "irisR_edge": 469, "irisL": 473, "irisL_edge": 474,
  "browR_inner": 55, "browR_mid": 105, "browR_outer": 70,
  "browL_inner": 285, "browL_mid": 334, "browL_outer": 300,
  "mouth_R": 61, "mouth_L": 291, "lip_top": 0, "lip_upper_in": 13, "lip_lower_in": 14, "lip_bot": 17,
  "nose_tip": 1, "chin": 152, "forehead": 10, "cheekR": 234, "cheekL": 454,
}
rig = {k: [round(lm[i].x, 5), round(lm[i].y, 5)] for k, i in idx.items()}
rig["_size"] = [W, H]
rig["_source"] = f"{label} crop x={x} y={y} w={w} h={h}; Swin2SR x4 -> {W}x{H}; landmarks via MediaPipe FaceLandmarker"
json.dump(rig, open(f"{outdir}/kaia_rig.json", "w"), indent=1)

dbg = img.copy()
d = ImageDraw.Draw(dbg)
for _k, (px, py) in ((key, value) for key, value in rig.items() if not key.startswith("_")):
    d.ellipse((px * W - 4, py * H - 4, px * W + 4, py * H + 4), outline=(255, 0, 255), width=2)
fx0, fx1 = int(rig["cheekR"][0] * W) - 30, int(rig["cheekL"][0] * W) + 30
fy0, fy1 = int(rig["forehead"][1] * H) - 50, int(rig["chin"][1] * H) + 25
dbg.crop((fx0, fy0, fx1, fy1)).save(f"{outdir}/rig_debug.jpg")
print(label, W, H, "forehead", rig["forehead"], "chin", rig["chin"], "nose", rig["nose_tip"])
