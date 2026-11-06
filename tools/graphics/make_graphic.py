#!/usr/bin/env python3
"""Render a month infographic (or a before/after bar chart) from a JSON file.

Usage (from the repo root):
  python3 tools/graphics/make_graphic.py tools/graphics/data/m3.json
      -> docs/img/m3_graphic.png
  python3 tools/graphics/make_graphic.py tools/graphics/data/m4_before_after.json
      -> docs/img/m4_before_after.png
  python3 tools/graphics/make_graphic.py tools/graphics/data/improve_loop.json
      -> docs/img/improve-loop.png
  python3 tools/graphics/make_graphic.py --out /tmp/out tools/graphics/data/m3.json

Needs google-chrome (headless). Renders at 2x.
"""
import json, sys, subprocess, tempfile, os, html

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_IMG = os.path.join(REPO_ROOT, "docs", "img")

ARC = [("M1","Python, APIs, Git"),("M2","LLM basics + first tool call"),("M3","Agent loop + RAG"),
       ("M4","Graphs, evals, tracing"),("M5","Human-approved agents"),("M6","Ship 2 live demos")]
COLORS = {"blue":("#e8f3fd","#3b8fd9"),"green":("#eaf7ec","#3aa856"),"red":("#fdeeee","#d9534f"),
          "orange":("#fff8e6","#f0a020"),"purple":("#f1eefd","#7d5ce0"),"yellow":("#fffbe6","#e0b400"),
          "white":("#ffffff","#c9cfdc")}
NAVY="#1b2340"; BLUE="#3555d8"
e = html.escape

CSS = f"""
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:Inter,sans-serif;background:#fff;color:{NAVY};width:1024px;padding:14px 20px 12px 24px}}
h1{{font-size:27px;font-weight:800;letter-spacing:-.3px}}
.sub{{color:#555c6e;font-size:12.5px;margin:3px 0 10px}}
.lbl{{font-size:9.5px;font-weight:700;letter-spacing:1.1px;color:#3b4258;margin:6px 0 4px}}
.arc{{display:flex;gap:16px;position:relative;margin-top:16px}}
.mc{{flex:1;height:64px;border:1.5px solid #c9cfdc;border-radius:8px;padding:8px 10px;position:relative}}
.mc b{{display:block;font-size:17px;color:{BLUE};font-weight:700}}
.mc span{{font-size:9.5px;color:#333}}
.mc.cur{{background:#fff4dc;border:2.5px solid #f0a020}} .mc.cur b{{color:#d8500a}}
.tab{{position:absolute;top:-17px;left:-6px;background:#f0a020;color:#fff;font-size:8.5px;font-weight:800;padding:3px 8px;border-radius:5px 5px 0 0;white-space:nowrap}}
.mc:not(:last-child)::after{{content:"";position:absolute;right:-14px;top:30px;width:11px;border-top:1.5px solid #555}}
.rowt{{font-size:9.5px;font-weight:700;color:#2b3fc0;margin:7px 0 4px}}
.flow{{display:flex;align-items:stretch;gap:0}}
.fc{{flex:1;border-radius:8px;border:1.5px solid;padding:9px 11px;min-height:66px}}
.fc h3{{font-size:11.5px;font-weight:700;margin-bottom:3px;color:{NAVY}}}
.fc p{{font-size:9.3px;line-height:1.42;color:#3a4050}}
.ar{{width:34px;display:flex;align-items:center;justify-content:center;color:#444;font-size:14px}}
.keys{{display:flex;gap:16px}}
.kc{{flex:1;border:1.5px solid #c9cfdc;border-radius:8px;padding:8px 10px;min-height:104px}}
.kc h3{{font-size:13px;color:{BLUE};font-weight:700;line-height:1.2;margin-bottom:4px}}
.kc p{{font-size:9.3px;line-height:1.42;color:#3a4050}}
.bars{{margin-top:5px}} .bar{{display:flex;align-items:center;gap:5px;font-size:8.6px;margin:2px 0}}
.bar i{{display:block;height:9px;border-radius:3px}} .bar em{{font-style:normal;font-weight:700}}
"""

LOOP_CSS = f"""
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{height:100%}}
body{{font-family:Inter,sans-serif;background:#f6f7fb;color:{NAVY};padding:32px 36px 28px}}
h1{{font-size:32px;font-weight:800;letter-spacing:-.4px}}
.sub{{color:#555c6e;font-size:15px;margin:6px 0 16px;line-height:1.4}}
.lbl{{font-size:11px;font-weight:700;letter-spacing:1.2px;color:#3b4258;margin:0 0 10px}}
.grid{{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));column-gap:10px;row-gap:0;align-items:stretch}}
.lc{{border-radius:12px;border:1.5px solid;padding:12px 12px 11px;min-height:118px}}
.lc h3{{font-size:14px;font-weight:700;margin-bottom:6px;line-height:1.25;color:{NAVY}}}
.lc p{{font-size:12px;line-height:1.4;color:#3a4050}}
.arr{{display:flex;align-items:center;justify-content:center;color:#444;font-size:16px;padding-bottom:28px}}
.ret{{position:relative;height:36px;margin-top:8px}}
.ret i{{position:absolute;left:0;right:0;top:16px;border-top:2.5px dotted #3555d8}}
.ret i::before{{content:"";position:absolute;left:-1px;top:-6px;border:6px solid transparent;border-right:8px solid #3555d8}}
.ret span{{position:absolute;left:50%;top:6px;transform:translateX(-50%);background:#f6f7fb;color:#d8500a;font-size:12px;font-weight:700;padding:0 8px}}
.panel{{margin-top:16px;background:#fff;border:1.5px solid #d5dbe8;border-radius:14px;padding:14px 18px 12px}}
.panel h2{{font-size:15px;font-weight:700;margin-bottom:8px}}
.panel li{{font-size:13px;line-height:1.45;color:#3a4050;margin:4px 0 4px 18px}}
"""

def reveal(n):
    if n is None: return ""
    return f"<script>document.querySelectorAll('.an').forEach((el,i)=>{{if(i>={n})el.style.visibility='hidden'}})</script>"

def card(c):
    bg, bd = COLORS[c.get("color","white")]
    extra = ""
    if "bars" in c:
        extra = '<div class="bars">' + "".join(
            f'<div class="bar"><span style="width:34px">{e(b["label"])}</span><i style="width:{b["value"]/b["total"]*70:.0f}px;background:{COLORS[b["color"]][1]}"></i><em>{b["value"]}/{b["total"]}</em></div>'
            for b in c["bars"]) + "</div>"
    return f'<div class="fc an" style="background:{bg};border-color:{bd}"><h3>{e(c["title"])}</h3><p>{e(c["body"])}</p>{extra}</div>'

def month_html(d, n=None):
    arc = ""
    for m, t in ARC:
        cur = m == d["month"]
        tab = f'<div class="tab">{e(d["tab"])}</div>' if cur else ""
        arc += f'<div class="an mc{" cur" if cur else ""}">{tab}<b>{m}</b><span>{e(t)}</span></div>'
    rows = ""
    for r in d["rows"]:
        cards = '<div class="ar an">&#10230;</div>'.join(card(c) for c in r["cards"])
        rows += f'<div class="rowt">{e(r["title"])}</div><div class="flow">{cards}</div>'
    keys = "".join(f'<div class="kc an"><h3>{e(k["title"])}</h3><p>{e(k["body"])}</p></div>' for k in d["keys"])
    return f"""<html><head><style>{CSS}</style></head><body>
<h1>{e(d["month"])}: {e(dict(ARC)[d["month"]])}</h1><div class="sub">{e(d["subtitle"])}</div>
<div class="lbl">THE 6-MONTH AI ENGINEER ARC</div><div class="arc">{arc}</div>
<div class="lbl" style="margin-top:14px">WHAT YOU BUILT AND HOW IT FLOWS</div>{rows}
<div class="lbl" style="margin-top:10px">KEY IDEAS TO UNDERSTAND</div><div class="keys">{keys}</div>
{reveal(n)}</body></html>"""

def loop_html(d):
    """Horizontal improvement loop. A dotted return sits under cards[return.from : return.to]."""
    cards = d["cards"]
    ret = d.get("return") or {}
    start = int(ret.get("from", 0))
    end = int(ret.get("to", len(cards) - 1))
    if not (0 <= start < end < len(cards)):
        sys.exit("loop return.from must be a card index left of return.to")
    cells = []
    for i, c in enumerate(cards):
        bg, bd = COLORS[c.get("color", "white")]
        cells.append(
            f'<div class="lc" style="background:{bg};border-color:{bd};grid-column:{i+1};grid-row:1">'
            f'<h3>{e(c["title"])}</h3><p>{e(c["body"])}</p></div>'
        )
        if i < len(cards) - 1:
            cells.append(
                f'<div class="arr" style="grid-column:{i+1};grid-row:1;justify-self:end;width:0;overflow:visible;position:relative;left:12px">&#10230;</div>'
            )
    # The return track shares the card grid so it starts and ends on the named cards.
    span = end - start + 1
    ret_html = ""
    if ret.get("label"):
        ret_html = (
            f'<div class="ret" style="grid-column:{start+1} / span {span};grid-row:2">'
            f'<i></i><span>{e(ret["label"])}</span></div>'
        )
    notes = "".join(f"<li>{e(n)}</li>" for n in d.get("notes", []))
    panel = ""
    if notes:
        panel = f'<div class="panel"><h2>{e(d.get("note_title",""))}</h2><ul>{notes}</ul></div>'
    return f"""<html><head><style>{LOOP_CSS}</style></head><body>
<h1>{e(d["title"])}</h1><div class="sub">{e(d["subtitle"])}</div>
<div class="lbl">{e(d.get("section","THE LOOP"))}</div>
<div class="grid" style="grid-template-columns:repeat({len(cards)},minmax(0,1fr))">{''.join(cells)}{ret_html}</div>
{panel}</body></html>"""

def bars_html(d):
    W,H=1200,675; maxh=380
    cols=""
    for b in d["bars"]:
        h=b["value"]/b["total"]*maxh; col=COLORS[b["color"]][1]
        vis="hidden" if b.get("hide") else "visible"
        cols+=f'''<div style="visibility:{vis};display:flex;flex-direction:column;align-items:center;justify-content:flex-end;width:230px;height:{maxh+70}px">
<div style="font-size:44px;font-weight:800;color:{col}">{round(100*b["value"]/b["total"])}%</div>
<div style="font-size:18px;color:#555c6e;margin-bottom:10px">{b["value"]} of {b["total"]} pass</div>
<div style="width:200px;height:{h:.0f}px;background:{col};border-radius:12px 12px 0 0"></div></div>'''
    labels="".join(f'<div style="width:230px;text-align:center;font-size:20px;font-weight:700">{e(b["label"])}</div>' for b in d["bars"])
    return f"""<html><head><style>*{{margin:0;box-sizing:border-box}}body{{font-family:Inter,sans-serif;color:{NAVY};width:{W}px;height:{H}px;background:#fff;padding:40px 60px}}</style></head><body>
<div style="font-size:38px;font-weight:800">{e(d["title"])}</div><div style="font-size:19px;color:#555c6e;margin-top:6px">{e(d["subtitle"])}</div>
<div style="display:flex;justify-content:center;gap:120px;margin-top:20px;border-bottom:2px solid #c9cfdc">{cols}</div>
<div style="display:flex;justify-content:center;gap:120px;margin-top:10px">{labels}</div>
<div style="text-align:center;font-size:15px;color:#555c6e;margin-top:14px">{e(d.get("note",""))}</div></body></html>"""

def chrome_bin():
    """A Chrome that exits after --screenshot.

    Prefer google-chrome-stable. Skip a google-chrome wrapper that turns on
    remote debugging: that one writes the picture and then stays running.
    """
    import shutil
    for name in ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if not path:
            continue
        try:
            with open(path, "r", errors="ignore") as f:
                head = f.read(400)
        except OSError:
            return path
        if head.startswith("#!") and "remote-debugging-port" in head:
            continue
        return path
    sys.exit("needs google-chrome")

def render(htmltext, out, w, h):
    import shutil
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(htmltext); p=f.name
    profile = tempfile.mkdtemp(prefix="chrome-gfx-")
    try:
        subprocess.run([chrome_bin(),"--headless=new","--no-sandbox","--disable-gpu","--disable-dev-shm-usage",
            "--hide-scrollbars","--force-device-scale-factor=2",f"--window-size={w},{h}",
            f"--user-data-dir={profile}",f"--screenshot={os.path.abspath(out)}","file://"+p],
            check=True,capture_output=True,timeout=90)
    finally:
        os.unlink(p)
        shutil.rmtree(profile, ignore_errors=True)

def output_dir(out_flag):
    """Png files go to docs/img. --out DIR writes them there instead."""
    if out_flag:
        return os.path.abspath(out_flag)
    return DEFAULT_IMG

def parse_args(argv):
    out_flag = None
    paths = []
    i = 0
    while i < len(argv):
        if argv[i] == "--out":
            if i + 1 >= len(argv):
                sys.exit("usage: make_graphic.py [--out DIR] data.json ...")
            out_flag = argv[i + 1]
            i += 2
            continue
        paths.append(argv[i])
        i += 1
    if not paths:
        sys.exit("usage: make_graphic.py [--out DIR] data.json ...")
    return out_flag, paths

if __name__=="__main__":
    out_flag, paths = parse_args(sys.argv[1:])
    img_dir = output_dir(out_flag)
    os.makedirs(img_dir, exist_ok=True)
    for path in paths:
        d=json.load(open(path))
        if d.get("type")=="bars":
            name=d["out"]; w,h=1200,675
            htmltext=bars_html(d)
        elif d.get("type")=="loop":
            name=d["out"]; w,h=d.get("width",1280),d.get("height",640)
            htmltext=loop_html(d)
        else:
            name=d.get("out", d["month"].lower()+"_graphic.png"); w,h=1024,d.get("height",806)
            htmltext=month_html(d)
        out=os.path.join(img_dir, os.path.basename(name))
        render(htmltext, out, w, h)
        print("wrote", out)
