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

# Builds a type-0 MIDI file in the page with nch channels, 8 notes each, one every 0.5 s (synthetic lane-count tests).
# uni=true: every channel plays the same pitches at the same times (unison).
MK_MIDI = """(nch,uni)=>{const vlq=v=>{const o=[v&127];while(v>>=7)o.unshift((v&127)|128);return o};
  const ev=[];for(let c=0;c<nch;c++)for(let k=0;k<8;k++){const st=k*480,n=uni?60+(k%3):48+c*4+(k%3);ev.push([st,0x90|c,n,90],[st+400,0x80|c,n,0])}
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

# Simulates dragging a file over the roll and dropping it. Args: [file name, MIME type, lanes (0 = not a MIDI file)].
DROP = """async ([name,type,lanes])=>{const roll=document.querySelector('.roll'),mk=(MK);
  const dt=new DataTransfer();dt.items.add(new File([lanes?mk(lanes):'not midi'],name,{type}));
  roll.dispatchEvent(new DragEvent('dragenter',{dataTransfer:dt,bubbles:true,cancelable:true}));const highlighted=roll.classList.contains('drop');
  roll.dispatchEvent(new DragEvent('drop',{dataTransfer:dt,bubbles:true,cancelable:true}));
  await new Promise(r=>setTimeout(r,300));
  return{highlighted,cleared:!roll.classList.contains('drop'),title:document.getElementById('title').textContent,
    info:document.getElementById('info').textContent,rows:document.querySelectorAll('#lanes .lane').length,
    disabled:document.querySelectorAll(':disabled').length,nosong:document.body.classList.contains('nosong')}}""".replace("(MK)", "(" + MK_MIDI + ")")

def mk_midi(nch):
    """Same synthetic type-0 MIDI as MK_MIDI, as bytes (for the real file chooser)."""
    def vlq(v):
        o = [v & 127]; v >>= 7
        while v: o.insert(0, (v & 127) | 128); v >>= 7
        return o
    ev = [e for c in range(nch) for k in range(8)
          for e in ((k * 480, 0x90 | c, 48 + c * 4 + k % 3, 90), (k * 480 + 400, 0x80 | c, 48 + c * 4 + k % 3, 0))]
    ev.sort(key=lambda e: (e[0], e[3]))
    t, last = [], 0
    for e in ev: t += vlq(e[0] - last) + list(e[1:]); last = e[0]
    t += [0, 0xFF, 0x2F, 0]
    return b"MThd" + bytes([0, 0, 0, 6, 0, 0, 0, 1, 1, 0xE0]) + b"MTrk" + len(t).to_bytes(4, "big") + bytes(t)

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
            check("no-song: header Open .mid hidden", not await pg.locator("label.open").is_visible())
            check("no-song: info button visible and usable, tempo buttons disabled",
                  await pg.locator("#infob").is_enabled() and await pg.locator("#infob").is_visible()
                  and await pg.evaluate('["tdn","tup","bpm"].every(id=>document.getElementById(id).disabled)'))
            async with pg.expect_file_chooser(timeout=3000) as fc:
                await pg.click(".roll")
            await (await fc.value).set_files({"name": "picked-2-lanes.mid", "mimeType": "audio/midi", "buffer": mk_midi(2)})
            await pg.wait_for_timeout(300)
            st = await pg.evaluate('[document.getElementById("title").textContent,document.querySelectorAll("#lanes .lane").length]')
            check("no-song: tapping the empty roll opens the file chooser and loads the file", st == ["picked-2-lanes.mid", 2], str(st))
            check("after loading: header Open .mid visible, roll tap layer gone",
                  await pg.locator("label.open").is_visible() and not await pg.locator("label.pick").is_visible())
            await pg.reload()
            d = await pg.evaluate(DROP, ["dropped-4-lanes.mid", "audio/midi", 4])
            check("no-song: dropping a .mid on the roll opens it and enables controls",
                  d["highlighted"] and d["cleared"] and d["title"] == "dropped-4-lanes.mid" and d["rows"] == 4 and d["disabled"] == 0 and not d["nosong"], str(d))
            check("no JS errors", not errs, str(errs)); await b.close(); return

        # --- layout with the built-in song ---
        check("song loaded: header Open .mid visible, roll tap layer gone",
              await pg.locator("label.open").is_visible() and not await pg.locator("label.pick").is_visible())
        check_geom("390px song", await pg.evaluate(GEOM), await pg.evaluate("laneChans().length"))

        # --- count-in ---
        await pg.select_option("#inst", "piano")
        await pg.click("#met"); await pg.click("#cin"); await pg.click("#play")
        await pg.wait_for_timeout(1200)
        ci = await pg.evaluate("[countMarks.length, seg.c0-ctx.currentTime]")
        check("count-in clicks scheduled, music starts later", ci[0] >= 2 and ci[1] > 0, f"marks {ci[0]}, music in {ci[1]:.2f}s")
        cn = await pg.evaluate("""()=>{const e=document.getElementById('cnt'),r=e.getBoundingClientRect(),l=document.getElementById('lanes').getBoundingClientRect();
          return{txt:e.textContent,dx:(r.left+r.right)/2-document.documentElement.clientWidth/2,abovePanel:+getComputedStyle(e).zIndex>+getComputedStyle(document.getElementById('lanes')).zIndex}}""")
        check("count-in number shows, centred on the page, above the lane panel", cn["txt"].isdigit() and abs(cn["dx"]) < 1 and cn["abovePanel"], str(cn))
        await pg.screenshot(path=str(OUT / "out_countin.png"), clip={"x": 0, "y": 0, "width": 390, "height": 400})
        await pg.wait_for_timeout(int(ci[1] * 1000) + 300)
        check("count-in number disappears when the music starts", await pg.evaluate("document.getElementById('cnt').textContent") == "")
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
        # lanes: per-lane UI state; voices: every live voice's gain must be 1 iff any of its lanes is audible
        state = """()=>{const now=ctx.currentTime,lv=live.filter(v=>v.end>now);
          return{lanes:laneChans().map(c=>({c,aud:audible(c),off:document.querySelector(`.lane[data-ch="${c}"]`).classList.contains('off'),
            s:document.querySelector(`.lane[data-ch="${c}"] .s`).classList.contains('on'),m:document.querySelector(`.lane[data-ch="${c}"] .m`).classList.contains('on')})),
          nLive:lv.length,wrong:lv.filter(v=>Math.abs(v.g.gain.value-(v.members.some(m=>audible(m.ch))?1:0))>0.05).length}}"""
        await pg.click(".lane:nth-child(1) .s"); await pg.wait_for_timeout(300)
        st = await pg.evaluate(state); L = st["lanes"]
        check("solo lane 1: only lane 1 audible, others dimmed, voice gains follow", L[0]["aud"] and L[0]["s"] and not L[0]["off"]
              and all(not x["aud"] and x["off"] for x in L[1:]) and st["nLive"] > 0 and st["wrong"] == 0,
              f"{[(x['aud'], x['off']) for x in L]}, {st['nLive']} live voices, {st['wrong']} wrong gains")
        await pg.screenshot(path=str(OUT / "out_solo.png"), clip={"x": 0, "y": 0, "width": 390, "height": 420})
        await pg.click(".lane:nth-child(1) .s"); await pg.click(".lane:nth-child(2) .m"); await pg.wait_for_timeout(300)
        st = await pg.evaluate(state); L = st["lanes"]
        check("mute lane 2: lane 2 silent and dimmed, others audible, voice gains follow", not L[1]["aud"] and L[1]["m"] and L[1]["off"]
              and all(x["aud"] and not x["off"] for i, x in enumerate(L) if i != 1) and st["nLive"] > 0 and st["wrong"] == 0,
              f"{[(x['aud'], x['off']) for x in L]}, {st['nLive']} live voices, {st['wrong']} wrong gains")
        await pg.click("#play")
        await pg.screenshot(path=str(OUT / "out_390.png"), full_page=True)
        await pg.click("#reset")
        st = await pg.evaluate(state)
        check("Reset clears solo/mute", not any(x["off"] or x["s"] or x["m"] for x in st["lanes"]))

        # --- end of song stops playback ---
        await pg.evaluate("(()=>{offset=song.duration-1})()"); await pg.click("#play"); await pg.wait_for_timeout(2500)
        check("stops at end", await pg.evaluate("!playing && offset===0"))

        # --- drag the roll to move through the song ---
        box = await pg.locator("#roll").bounding_box()
        y = box["y"] + box["height"] / 2
        lw, pxs = await pg.evaluate("[laneW,(cv.clientWidth-laneW)/AHEAD]")  # px per second
        async def drag_roll(x0, dx, mid=None):
            await pg.mouse.move(x0, y); await pg.mouse.down()
            for i in range(1, 11): await pg.mouse.move(x0 + dx * i / 10, y)
            r = await pg.evaluate(mid) if mid else None
            await pg.mouse.up(); return r
        await pg.evaluate("offset=2;draw()")
        await drag_roll(box["x"] + box["width"] - 20, -100)
        o = await pg.evaluate("offset")
        check("drag left moves forward by the dragged distance", abs(o - (2 + 100 / pxs)) < 0.05, f"offset {o:.2f}, expected {2 + 100 / pxs:.2f}")
        await drag_roll(box["x"] + box["width"] - 120, 60)
        o2 = await pg.evaluate("offset")
        check("drag right moves back", abs(o2 - (o - 60 / pxs)) < 0.05, f"offset {o2:.2f}")
        await pg.evaluate("offset=0.5;draw()")
        await drag_roll(box["x"] + lw + 10, 200)
        check("dragging back stops at the start", await pg.evaluate("offset") == 0)
        await pg.evaluate("offset=2;draw()"); await pg.click("#play"); await pg.wait_for_timeout(400)
        await pg.mouse.click(box["x"] + box["width"] - 60, y); await pg.wait_for_timeout(100)
        check("a tap on the roll doesn't pause playback", await pg.evaluate("playing"))
        before = await pg.evaluate("pos()")
        during = await drag_roll(box["x"] + box["width"] - 20, -100, "playing")
        await pg.wait_for_timeout(300)
        after = await pg.evaluate("[playing,pos()]")
        check("drag while playing pauses, then resumes from the new spot",
              during is False and after[0] and after[1] > before + 100 / pxs * 0.8, f"before {before:.2f}, after {after[1]:.2f}")
        await pg.click("#play")

        # --- header: Open .mid left of the always-visible info button; info window holds help + piano credit ---
        hb = await pg.evaluate("""()=>{const o=document.querySelector('label.open').getBoundingClientRect(),i=document.getElementById('infob').getBoundingClientRect(),
          m=document.querySelector('main').getBoundingClientRect();return[o.right<=i.left,Math.round(m.right-i.right),Math.round(i.width),Math.round(i.height)]}""")
        check("header: Open .mid sits left of the round info button at the top right", hb[0] and hb[1] == 16 and hb[2] == hb[3], str(hb))
        check("credit and help text are gone from the page itself",
              not await pg.evaluate("[...document.querySelectorAll('main *')].some(e=>e.textContent.includes('Salamander'))"))
        await pg.click("#infob")
        dl = await pg.evaluate("[about.open,about.textContent.includes('Salamander Grand Piano by Alexander Holm'),about.textContent.includes('CC BY 3.0')]")
        check("info button opens the info window with the piano credit", all(dl), str(dl))
        hs = await pg.evaluate("[[...about.querySelectorAll('h3')].map(h=>h.textContent),about.textContent.includes('iPhone')]")
        check("info window: no Play/Stop, Metronome or Sound titles, not iPhone-specific",
              not any(h in hs[0] for h in ("Play and Stop", "Metronome and Count-in", "Sound")) and not hs[1], str(hs))
        await pg.screenshot(path=str(OUT / "out_info.png"))
        await pg.click("#about .dh button"); await pg.wait_for_timeout(100)
        check("✕ closes the info window", not await pg.evaluate("about.open"))
        await pg.click("#infob"); await pg.mouse.click(5, 5); await pg.wait_for_timeout(100)
        check("tapping outside closes the info window", not await pg.evaluate("about.open"))

        # --- tempo: original shown top left; − [BPM] + ; tap = ±1, hold repeats ~3-4/s, applied on release ---
        orig = await pg.evaluate("Math.round(song.bpm)")
        info = await pg.evaluate("document.getElementById('info').textContent")
        check("info line starts with the file's original tempo as 'N BPM'", info.startswith(f"{orig} BPM · "), info)
        gaps = await pg.evaluate("""()=>{const r=id=>document.getElementById(id).getBoundingClientRect(),d=r('tdn'),b=r('bpm'),u=r('tup'),mid=document.documentElement.clientWidth/2;
          return[b.left-d.right,u.left-b.right,(b.left+b.right)/2-mid,(mid-d.left)-(u.right-mid)]}""")
        check("− and + sit right next to the tempo number", gaps[0] <= 8 and gaps[1] <= 8, f"gaps {gaps[0]:.1f}/{gaps[1]:.1f} px")
        check("tempo number sits on the page's centre line, − and + symmetric", abs(gaps[2]) < 1 and abs(gaps[3]) < 1,
              f"number centre {gaps[2]:+.1f} px, asymmetry {gaps[3]:+.1f} px")
        lbl = await pg.evaluate("[...document.querySelectorAll('.row')].map(r=>[...r.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent.trim()).join(''))")
        check("no 'Tempo' / 'Sound' text labels next to the fields", not any(lbl), str(lbl))
        check("tempo starts at the original", await pg.evaluate("[bpm,speed]") == [orig, 1])
        await pg.click("#tup")
        st = await pg.evaluate("[bpm,speed,song.bpm,document.getElementById('bpm').textContent]")
        check("tap + adds 1 BPM and changes speed", st[0] == orig + 1 and abs(st[1] - (orig + 1) / st[2]) < 1e-9 and st[3] == f"{orig + 1}BPM", str(st))
        await pg.click("#tdn")
        check("tap − takes it back to exactly the original speed", await pg.evaluate("[bpm,speed]") == [orig, 1])
        tb = await pg.locator("#tup").bounding_box()
        await pg.mouse.move(tb["x"] + tb["width"] / 2, tb["y"] + tb["height"] / 2); await pg.mouse.down()
        await pg.wait_for_timeout(2000)
        mid = await pg.evaluate("[bpm,speed]")
        await pg.mouse.up()
        steps = mid[0] - orig  # expected: 1 at press + 1 at 450 ms + every 125 ms after = 14 in 2 s
        check("hold + repeats at 8 per second", 12 <= steps <= 15, f"{steps} steps in 2.0 s")
        check("while held, only the number changes; speed applies on release",
              mid[1] == 1 and abs(await pg.evaluate("speed") - mid[0] / await pg.evaluate("song.bpm")) < 1e-9)
        await pg.click("#bpm")
        check("tapping the number resets to the original tempo", await pg.evaluate("[bpm,speed]") == [orig, 1])
        await pg.evaluate("bpm=Math.floor(song.bpm*1.5);tempoLabel()"); await pg.click("#tup")
        await pg.evaluate("bpm=Math.ceil(song.bpm*0.5);tempoLabel()"); await pg.click("#tdn")
        check("tempo stops at half and 1.5 times the original", await pg.evaluate("bpm===Math.ceil(song.bpm*0.5)"))
        await pg.click("#bpm")

        # --- unison: the same pitch starting together in several lanes plays as ONE voice ---
        await pg.evaluate(f"""()=>{{load(({MK_MIDI})(4,true),'unison-4.mid');window.calls=[];window.origVoice=voice;
          voice=(n,t0,t1,out)=>{{calls.push([n.n,+t0.toFixed(3),out]);origVoice(n,t0,t1,out)}}}}""")
        await pg.click("#play"); await pg.wait_for_timeout(1300)
        u = await pg.evaluate("""()=>{const keys=calls.map(c=>c[0]+'@'+c[1]);
          return{calls:calls.length,unique:new Set(keys).size,groups:song.groups.length,notes:song.notes.length,
            members:song.groups.map(g=>g.members.length)}}""")
        check("unison: 4 lanes on the same note are grouped into one voice each", u["groups"] * 4 == u["notes"] and set(u["members"]) == {4}, str(u))
        check("unison: each onset is played once, not 4 times", u["calls"] >= 2 and u["calls"] == u["unique"], f"{u['calls']} voices started for {u['calls']} onsets")
        await pg.click(".lane:nth-child(1) .m"); await pg.wait_for_timeout(250)
        st = await pg.evaluate(state)
        check("unison: muting one of the lanes keeps the shared note sounding",
              st["nLive"] > 0 and st["wrong"] == 0 and await pg.evaluate("live.filter(v=>v.end>ctx.currentTime).some(v=>v.g.gain.value>0.95)"))
        await pg.click("#play"); await pg.click("#reset")
        await pg.evaluate("calls.length=0"); await pg.click("#pall"); await pg.wait_for_timeout(100)
        check("unison: ♪ All plays a shared pitch once", await pg.evaluate("calls.length") == 1, str(await pg.evaluate("calls.length")))
        await pg.evaluate("()=>{voice=origVoice}")

        # --- drop a file on the roll ---
        d = await pg.evaluate(DROP, ["dropped-3-lanes.mid", "audio/midi", 3])
        check("dropping a .mid on the roll opens it", d["highlighted"] and d["cleared"] and d["title"] == "dropped-3-lanes.mid" and d["rows"] == 3, str(d))
        d = await pg.evaluate(DROP, ["notes.txt", "text/plain", 0])
        check("dropping a non-MIDI file is refused", d["info"].startswith("Not a MIDI file") and d["title"] == "dropped-3-lanes.mid" and d["cleared"], d["info"])

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

if __name__ == "__main__":
    asyncio.run(main())
    if fails:
        print(f"\n{len(fails)} check(s) failed"); sys.exit(1)
    print("\nall checks passed")
