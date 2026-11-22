#!/usr/bin/env python3
"""Build dist/index.html: a single self-contained page.

Embeds the piano samples (assets/piano/*.mp3) and, optionally, one built-in song.

  python build.py                              # built-in song: assets/songs/moto-B2.mid
  python build.py --song assets/songs/x.mid    # different built-in song
  python build.py --no-song                    # no built-in song; users open their own .mid
"""
import argparse, base64, glob, json, os

ROOT = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("--song", default=os.path.join(ROOT, "assets/songs/moto-B2.mid"))
ap.add_argument("--no-song", action="store_true")
ap.add_argument("--out", default=os.path.join(ROOT, "dist/index.html"))
a = ap.parse_args()

t = open(os.path.join(ROOT, "src/template.html"), encoding="utf-8").read()
piano = {os.path.basename(f)[:-4]: base64.b64encode(open(f, "rb").read()).decode()
         for f in sorted(glob.glob(os.path.join(ROOT, "assets/piano/*.mp3")))}
assert len(piano) == 30, f"expected 30 piano samples, found {len(piano)}"
song_b64, song_name = "", ""
if not a.no_song:
    song_b64 = base64.b64encode(open(a.song, "rb").read()).decode()
    song_name = os.path.basename(a.song)
for k, v in {"__PIANO__": json.dumps(piano, separators=(",", ":")),
             "__SONG_B64__": song_b64, "__SONG_NAME__": song_name}.items():
    assert t.count(k) == 1, k
    t = t.replace(k, v)
os.makedirs(os.path.dirname(a.out), exist_ok=True)
open(a.out, "w", encoding="utf-8").write(t)
print(f"wrote {a.out} ({len(t)/1e6:.2f} MB, song: {song_name or 'none'})")
