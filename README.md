# MIDI Player for choir practice

A single web page for practising choir parts on a phone. Open a `.mid` file and it shows a scrolling piano roll. Each MIDI channel plays as its own lane.

**Live:** https://leomuiste.github.io/midi-player/

Everything runs in the browser. Nothing is uploaded, and the page makes no network requests.

## Use

- **Open a song:** tap the empty piano roll, or drag a `.mid` file onto it. Once a song is open, **Open .mid** (top right) loads another one, and dropping a file on the roll still works.
- **Move through the song:** drag the piano roll left or right with a finger or the mouse, or tap the timeline. Dragging during playback pauses it, and playback continues from where you let go.
- **Lanes:** the controls are on the left of the roll. **S** solos a lane, **M** mutes it, and the note button shows and plays the note the lane is singing now (or its next note). **♪ All** plays every audible lane's note; **Reset** clears solo and mute. When several lanes sing the same note at the same time, it's played once, so unisons sound clean.
- **Tempo:** the file's original tempo is shown at the top (e.g. "96 BPM"). **−** and **+** change the tempo by 1 BPM; hold them to keep changing it (8 steps a second). Tap the number to go back to the original. The range is half to 1.5 times the original.
- **Also:** metronome, one-bar count-in, and synth, piano, organ and choir sounds.
- **Help:** the **ⓘ** button (top right) explains the controls and holds the piano credit.

## Build and test

```
python build.py --no-song            # -> dist/index.html (no built-in song)
python tests/ui_smoke.py             # headless browser checks; needs: pip install playwright && playwright install chromium
```

Pushing to `main` builds the page and deploys it to GitHub Pages (`.github/workflows/pages.yml`).

## Credits

Piano samples: Salamander Grand Piano by Alexander Holm, licensed [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/). The samples have been resampled to mono 32 kHz, trimmed to 6 s and faded out.
