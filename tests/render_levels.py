#!/usr/bin/env python3
"""Render the built-in song offline with each instrument; print peak/RMS and write tests/out_<inst>.wav.

Used to loudness-match instruments (LEVEL table in src/template.html; synth RMS ~0.27 is the reference)
and to sanity-check pitch/decay without listening. Same requirements as ui_smoke.py.
"""
import asyncio, base64, os, pathlib, sys, wave
from playwright.async_api import async_playwright

PAGE = (pathlib.Path(__file__).resolve().parent.parent / "dist/index.html").as_uri()
JS = '''async(name)=>{inst=name;
 const sr=44100,dur=song.duration+1;const off=new OfflineAudioContext(1,Math.ceil(sr*dur),sr);
 ctx=off;pianoBufs=null;pianoLoading=null;if(name==="piano")await loadPiano();
 const out=off.createGain();out.connect(off.destination);
 for(const n of song.notes)voice(n,n.start,n.end,out);
 const b=await off.startRendering();const d=b.getChannelData(0);let pk=0,ss=0;for(const x of d){pk=Math.max(pk,Math.abs(x));ss+=x*x}
 const i16=new Int16Array(d.length);for(let i=0;i<d.length;i++)i16[i]=Math.max(-1,Math.min(1,d[i]))*32767;
 let bin="";const u=new Uint8Array(i16.buffer);for(let i=0;i<u.length;i+=8192)bin+=String.fromCharCode(...u.subarray(i,i+8192));
 return [pk,Math.sqrt(ss/d.length),btoa(bin)];}'''

async def main(names):
    async with async_playwright() as p:
        kw = {"executable_path": os.environ["CHROME"]} if os.environ.get("CHROME") else {}
        b = await p.chromium.launch(**kw); pg = await b.new_page()
        await pg.goto(PAGE)
        for n in names:
            pk, rms, data = await pg.evaluate(JS, n)
            with wave.open(f"tests/out_{n}.wav", "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100); w.writeframes(base64.b64decode(data))
            print(f"{n:6s} peak {pk:.2f}  rms {rms:.3f}")
        await b.close()

asyncio.run(main(sys.argv[1:] or ["synth", "piano", "organ", "choir"]))
