# Kaia codec portrait builder

Turns any Kaia image into a rigged codec portrait for the web UI
(`kaiagotchi/ui/web/static/assets/kaia/<id>/kaia_codec.webp` + `kaia_rig.json`).

Pipeline: crop -> Swin2SR 4x super-resolution (GPU) -> resize to 840 px tall ->
BiRefNet alpha matte -> MediaPipe face landmarks -> rig JSON (+ `rig_debug.jpg` overlay).

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
curl -LO https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task

# crop is x,y,w,h in the source image; keep w/h ~ 1.09, forehead ~1/3 down, chin ~4/5 down
.venv/bin/python build_portrait.py "/path/kaia_60.png" 633,125,420,385 out/ face_landmarker.task sr.py kaia_60.png
```

Copy `out/kaia_codec.webp` and `out/kaia_rig.json` into a new folder under
`assets/kaia/`, add its name to `KaiaCodec.PORTRAITS` in `js/kaia/kaia-codec.js`,
and select it with `?face=<id>`. Check `out/rig_debug.jpg`: every magenta point
should sit on its feature (eye corners, lids, irises, brows, mouth corners, nose, chin).
Brightness is normalised automatically at runtime, so differently lit sources match.
