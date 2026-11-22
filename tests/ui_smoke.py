#!/usr/bin/env python3
"""Headless UI smoke test for dist/index.html (needs: pip install playwright && playwright install chromium).

Checks: no JS errors, count-in, A-B loop wraps, starting-pitch labels, song end stops playback.
Set CHROME=/path/to/chrome to use a system Chrome instead of Playwright's Chromium.
"""
import asyncio, os, pathlib
from playwright.async_api import async_playwright

PAGE = (pathlib.Path(__file__).resolve().parent.parent / "dist/index.html").as_uri()

async def main():
    async with async_playwright() as p:
        kw = {"args": ["--autoplay-policy=no-user-gesture-required"]}
        if os.environ.get("CHROME"): kw["executable_path"] = os.environ["CHROME"]
        b = await p.chromium.launch(**kw)
        pg = await b.new_page(viewport={"width": 390, "height": 1150}, device_scale_factor=2)
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        await pg.goto(PAGE)
        if not await pg.evaluate("!!song"):
            print("no built-in song; only checking for load errors"); print("errors", errs); await b.close(); return
        await pg.select_option("#inst", "piano")
        await pg.click("#met"); await pg.click("#cin"); await pg.click("#play")
        await pg.wait_for_timeout(1200)
        print("count-in:", await pg.evaluate('"marks "+countMarks.length+", music starts in "+(segs[0].c0-ctx.currentTime).toFixed(2)+"s"'))
        await pg.screenshot(path="tests/out_countin.png", clip={"x": 0, "y": 0, "width": 390, "height": 340})
        await pg.evaluate("(()=>{halt();offset=song.bars[1].s+0.1;draw()})()")
        await pg.click("#seta"); await pg.evaluate("(()=>{offset=song.bars[2].s+0.1})()"); await pg.click("#setb")
        print("loop:", await pg.evaluate('document.getElementById("loopl").textContent+" LA "+LA()+" LB "+LB()'))
        await pg.evaluate("(()=>{offset=LA()})()"); await pg.click("#cin"); await pg.click("#play")
        ts = []
        for _ in range(16):
            await pg.wait_for_timeout(500); ts.append(float(await pg.evaluate("pos()")))
        wrapped = any(b < a for a, b in zip(ts, ts[1:]))
        print("loop positions:", [round(t, 2) for t in ts], "-> wrapped" if wrapped else "-> DID NOT WRAP")
        await pg.screenshot(path="tests/out_full.png")
        await pg.click("#play")
        print("pitch labels:", await pg.evaluate('[...document.querySelectorAll(".pt")].map(b=>b.textContent).join(" | ")'))
        await pg.click("#loopt")
        await pg.evaluate("(()=>{offset=song.duration-1})()"); await pg.click("#play"); await pg.wait_for_timeout(2500)
        print("stops at end:", await pg.evaluate("!playing && offset===0"))
        print("errors", errs); await b.close()

asyncio.run(main())
