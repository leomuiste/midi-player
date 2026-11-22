# MIDI Player for choir practice

A single web page for practising choir parts on a phone. Open a `.mid` file and it shows a scrolling piano roll and plays each MIDI channel as its own lane, which you can solo or mute. Other features: A–B bar loop, metronome, count-in, speed control, starting-pitch buttons, and synth, piano, organ and choir sounds.

Everything runs in the browser. Nothing is uploaded, and the page makes no network requests.

## Build

```
python build.py --no-song            # -> dist/index.html
```

Pushing to `main` builds the page and deploys it to GitHub Pages (`.github/workflows/pages.yml`).

## Credits

Piano samples: Salamander Grand Piano by Alexander Holm, licensed [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/). The samples have been resampled to mono 32 kHz, trimmed to 6 s and faded out.
