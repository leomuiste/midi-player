#!/usr/bin/env python3
"""Headless UI smoke test for dist/index.html (needs: pip install playwright && playwright install chromium).

Checks: no JS errors, count-in, lane rows inside the piano roll (1, 4 and 8 lanes; 390 and 320 px wide),
note buttons (current/next note, tap plays), solo/mute (gains + dimming), end of song stops playback.
Screenshots go to tests/out_*.png. Exits non-zero if any check fails.
Set CHROME=/path/to/chrome (or msedge.exe) to use a system browser instead of Playwright's Chromium.
"""
import asyncio, os, pathlib, sys
from playwright.async_api import async_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = (ROOT / "dist/index.html").as_uri()
OUT = ROOT / "tests"
fails = []

def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not ok: fails.append(name)

# Builds a type-0 MIDI file in the page with nch channels, 8 notes each (synthetic lane-count tests).
MK_MIDI = """nch=>{const vlq=v=>{const o=[v&127];while(v>>=7)o.unshift((v&127)|128);return o};
  const ev=[];for(let c=0;c<nch;c++)for(let k=0;k<8;k++){const st=k*480,n=48+c*4+(k%3);ev.push([st,0x90|c,n,90],[st+400,0x80|c,n,0])}
  ev.sort((a,b)=>a[0]-b[0]||a[3]-b[3]);const t=[];let last=0;for(const e of ev){t.push(...vlq(e[0]-last),e[1],e[2],e[3]);last=e[0]}
  t.push(0,0xFF,0x2F,0);const L=t.length;
  return new Uint8Array([0x4D,0x54,0x68,0x64,0,0,0,6,0,0,0,1,1,0xE0,0x4D,0x54,0x72,0x6B,L>>>24&255,L>>16&255,L>>8&255,L&255,...t]).buffer}"""

# Layout facts about the lane panel inside the roll.
GEOM = """()=>{const roll=document.querySelector('.roll').getBoundingClientRect(),pan=document.getElementById('lanes').getBoundingClientRect();
  const rows=[...document.querySelectorAll('#lanes .lane')],inR=r=>r.left>=roll.left-.5&&r.right<=roll.right+.5&&r.top>=roll.top-.5&&r.bottom<=roll.bottom+.5;
  const btns=[...document.querySelectorAll('#lanes .lane button')].map(b=>b.getBoundingClientRect());
  const sq=btns.every(b=>Math.abs(b.width-b.height)<.6&&Math.abs(b.width-btns[0].width)<.6);
  const corner=[...document.querySelectorAll('#lanes .lnc button')].map(b=>b.getBoundingClientRect());
  const rowsNoOverlap=rows.every((r,i)=>i===0||rows[i-1].getBoundingClientRect().bottom<=r.getBoundingClientRect().top+.5);
  const cornerBelowRows=!rows.length||corner.every(c=>c.top>=rows[rows.length-1].getBoundingClientRect().bottom-.5);
  const textFits=[...document.querySelectorAll('#lanes button')].every(b=>b.scrollWidth<=b.clientWidth+1);
  return{rows:rows.length,lanes:laneChans().length,rowsInRoll:rows.every(r=>inR(r.getBoundingClientRect())),
    cornerInRoll:corner.length===2&&corner.every(inR),cornerBelowRows,rowsNoOverlap,square:sq,btn:Math.round(btns[0].width),textFits,
    playheadAtPanelEdge:Math.abs((pan.right-roll.left)-laneW)<1,ahead:Math.round(roll.right-pan.right),rollW:Math.round(roll.width),rollH:Math.round(roll.height),
    pageOverflowX:document.documentElement.scrollWidth>innerWidth}}"""

def check_geom(tag, g, lanes):
    check(f"[{tag}] {lanes} lane rows render in the roll", g["rows"] == lanes == g["lanes"] and g["rowsInRoll"], str(g))
    check(f"[{tag}] ♪ All / Reset inside roll, below the rows", g["cornerInRoll"] and g["cornerBelowRows"])
    check(f"[{tag}] S, M and note buttons square and equal size", g["square"], f"{g['btn']} px")
    check(f"[{tag}] rows don't overlap, button text fits", g["rowsNoOverlap"] and g["textFits"])
    check(f"[{tag}] playhead at panel edge, music ahead visible", g["playheadAtPanelEdge"] and g["ahead"] >= g["rollW"] * 0.5,
          f"ahead {g['ahead']} of {g['rollW']} px, roll height {g['rollH']}")
    check(f"[{tag}] no horizontal page overflow", not g["pageOverflowX"])

async def main():
    async with async_playwright() as p:
        kw = {"args": ["--autoplay-policy=no-user-gesture-required"]}
        if os.environ.get("CHROME"): kw["executable_path"] = os.environ["CHROME"]
        b = await p.chromium.launch(**kw)
        pg = await b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        await pg.goto(PAGE)
        if not await pg.evaluate("!!song"):
            n = await pg.evaluate('document.querySelectorAll(":disabled").length')
            check("no-song: controls disabled", n > 0 and await pg.evaluate('document.body.classList.contains("nosong")'), f"{n} disabled")
            await pg.screenshot(path=str(OUT / "out_nosong.png"), full_page=True)
            check("no JS errors", not errs, str(errs)); await b.close(); return

        # --- layout with the built-in song ---
        check_geom("390px song", await pg.evaluate(GEOM), await pg.evaluate("laneChans().length"))

        # --- count-in ---
        await pg.select_option("#inst", "piano")
        await pg.click("#met"); await pg.click("#cin"); await pg.click("#play")
        await pg.wait_for_timeout(1200)
        ci = await pg.evaluate("[countMarks.length, seg.c0-ctx.currentTime]")
        check("count-in clicks scheduled, music starts later", ci[0] >= 2 and ci[1] > 0, f"marks {ci[0]}, music in {ci[1]:.2f}s")
        await pg.screenshot(path=str(OUT / "out_countin.png"), clip={"x": 0, "y": 0, "width": 390, "height": 400})
        await pg.click("#play")  # pause
        await pg.click("#cin"); await pg.click("#met")

        # --- note buttons: current note while sounding, next note when the lane is silent ---
        nb = await pg.evaluate("""()=>{const c=laneChans()[0],ns=laneNotes[c],btn=()=>document.querySelector(`.lane[data-ch="${c}"] .pt`).textContent;
          const r={};const n=ns.find(n=>n.end-n.start>0.2);offset=(n.start+n.end)/2;draw();
          r.sounding=btn();r.soundingOk=ns.filter(m=>m.start<=offset&&m.end>offset).map(m=>noteName(m.n)).includes(r.sounding);
          let gap=null;if(ns[0].start>0.1)gap=[0,ns[0]];else for(let i=1;i<ns.length;i++)if(ns[i].start>ns[i-1].end+0.1&&ns.slice(0,i).every(m=>m.end<ns[i].start-0.05)){gap=[ns[i-1].end,ns[i]];break}
          if(gap){offset=(gap[0]+gap[1].start)/2;draw();r.silent=btn();r.silentOk=r.silent===noteName(gap[1].n)}
          r.allLabels=[...document.querySelectorAll('.lane .pt')].map(b=>b.textContent);return r}""")
        check("note button shows the sounding note", nb["soundingOk"], nb["sounding"])
        if "silentOk" in nb: check("note button shows the next note when lane is silent", nb["silentOk"], nb["silent"])
        else: print("SKIP next-note check: lane 1 has no silent gap")
        check("note button labels are bare note names", all(l == "–" or (2 <= len(l) <= 4 and l[-1].isdigit()) for l in nb["allLabels"]), " | ".join(nb["allLabels"]))
        await pg.evaluate("prevOut=null")
        await pg.click(".lane .pt")
        await pg.wait_for_timeout(300)
        check("tapping a note button plays it", await pg.evaluate("prevOut!==null"))
        await pg.click("#pall"); await pg.wait_for_timeout(200)
        check("♪ All plays", await pg.evaluate("prevOut!==null"))

        # --- solo / mute while playing ---
        await pg.select_option("#inst", "synth")
        await pg.evaluate("offset=0"); await pg.click("#play"); await pg.wait_for_timeout(300)
        state = """()=>laneChans().map(c=>({c,g:chanG[c].gain.value,off:document.querySelector(`.lane[data-ch="${c}"]`).classList.contains('off'),
          s:document.querySelector(`.lane[data-ch="${c}"] .s`).classList.contains('on'),m:document.querySelector(`.lane[data-ch="${c}"] .m`).classList.contains('on')}))"""
        await pg.click(".lane:nth-child(1) .s"); await pg.wait_for_timeout(300)
        st = await pg.evaluate(state)
        check("solo lane 1: only lane 1 audible, others dimmed", st[0]["g"] > .95 and st[0]["s"] and not st[0]["off"]
              and all(x["g"] < .05 and x["off"] for x in st[1:]), str([(round(x["g"], 2), x["off"]) for x in st]))
        await pg.screenshot(path=str(OUT / "out_solo.png"), clip={"x": 0, "y": 0, "width": 390, "height": 420})
        await pg.click(".lane:nth-child(1) .s"); await pg.click(".lane:nth-child(2) .m"); await pg.wait_for_timeout(300)
        st = await pg.evaluate(state)
        check("mute lane 2: lane 2 silent and dimmed, others audible", st[1]["g"] < .05 and st[1]["m"] and st[1]["off"]
              and all(x["g"] > .95 and not x["off"] for i, x in enumerate(st) if i != 1), str([(round(x["g"], 2), x["off"]) for x in st]))
        await pg.click("#play")
        await pg.screenshot(path=str(OUT / "out_390.png"), full_page=True)
        await pg.click("#reset")
        st = await pg.evaluate(state)
        check("Reset clears solo/mute", not any(x["off"] or x["s"] or x["m"] for x in st))

        # --- end of song stops playback ---
        await pg.evaluate("(()=>{offset=song.duration-1})()"); await pg.click("#play"); await pg.wait_for_timeout(2500)
        check("stops at end", await pg.evaluate("!playing && offset===0"))

        # --- 1 and 8 lanes, 390 and 320 px wide ---
        for w in (390, 320):
            await pg.set_viewport_size({"width": w, "height": 844})
            for n in (1, 8):
                await pg.evaluate(f"load(({MK_MIDI})({n}),'synthetic-{n}-lanes.mid')")
                await pg.wait_for_timeout(100)
                check_geom(f"{w}px {n} lanes", await pg.evaluate(GEOM), n)
                await pg.screenshot(path=str(OUT / f"out_{w}_{n}lanes.png"), clip={"x": 0, "y": 0, "width": w, "height": 480})

        check("no JS errors", not errs, str(errs))
        await b.close()

asyncio.run(main())
if fails:
    print(f"\n{len(fails)} check(s) failed"); sys.exit(1)
print("\nall checks passed")
