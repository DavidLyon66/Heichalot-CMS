#!/usr/bin/env python3
import argparse, json, sys
from datetime import date
from pathlib import Path

BASE=Path(__file__).resolve().parent
DATA=BASE/"data"
QUOTE="USDT"

def load(path):
    with path.open(encoding="utf-8") as f: return json.load(f)

def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8") as f:
        json.dump(obj,f,indent=2,ensure_ascii=False); f.write("\n")

def history_path(asset): return DATA/f"{asset}_{QUOTE}.json"
def shapes_path(asset): return DATA/f"{asset}_{QUOTE}_shapes.json"

def history(asset):
    rows=load(history_path(asset)).get("data",[])
    out=[]
    for r in rows:
        try:
            out.append({
                "date":str(r["date"]),
                "close":float(r["close"]),
                "volume":float(r.get("volume",0.0)),
            })
        except Exception:
            pass
    out.sort(key=lambda r:r["date"])
    if not out: raise ValueError("No usable history")
    return out

def select(rows,start,end):
    if date.fromisoformat(end)<date.fromisoformat(start):
        raise ValueError("end date is before start date")
    out=[r for r in rows if start<=r["date"]<=end]
    if len(out)<2: raise ValueError("Need at least two points")
    return out

def normalize(rows):
    d0=date.fromisoformat(rows[0]["date"])
    d1=date.fromisoformat(rows[-1]["date"])
    days=max(1,(d1-d0).days)
    closes=[r["close"] for r in rows]
    lo,hi=min(closes),max(closes)
    span=hi-lo
    pts=[]
    for r in rows:
        x=(date.fromisoformat(r["date"])-d0).days/days
        y=(r["close"]-lo)/span if span else 0.5
        pts.append({"x":round(x,8),"y":round(y,8)})
    return pts,lo,hi

def svg_path(points,w=1000,h=400):
    coords=[f"{pt['x']*w:.2f},{(1-pt['y'])*h:.2f}" for pt in points]
    return "M "+" L ".join(coords)

def load_shapes(asset):
    path=shapes_path(asset)
    if not path.exists():
        return {"asset":asset,"reference_currency":QUOTE,"shapes":[]}
    doc=load(path)
    doc.setdefault("shapes",[])
    return doc

def add_shape(asset,start,end,label,description=""):
    rows=select(history(asset),start,end)
    pts,lo,hi=normalize(rows)
    shape={
        "label":label,
        "description":description,
        "source_start":rows[0]["date"],
        "source_end":rows[-1]["date"],
        "source_days":(date.fromisoformat(rows[-1]["date"])-date.fromisoformat(rows[0]["date"])).days+1,
        "source_points":len(rows),
        "source_low":lo,
        "source_high":hi,
        "normalization":{"x":"0..1 elapsed time","y":"0..1 close-price range"},
        "points":pts,
        "source_data":[{"date":r["date"],"close":r["close"],"volume":r["volume"]} for r in rows],
        "svg":{"width":1000,"height":400,"path":svg_path(pts)},
    }
    doc=load_shapes(asset)
    replaced=False
    for i,s in enumerate(doc["shapes"]):
        if str(s.get("label","")).casefold()==label.casefold():
            doc["shapes"][i]=shape; replaced=True; break
    if not replaced: doc["shapes"].append(shape)
    save(shapes_path(asset),doc)
    return shape,replaced

def find_shape(asset,label):
    for s in load_shapes(asset)["shapes"]:
        if str(s.get("label","")).casefold()==label.casefold(): return s
    raise ValueError(f'No shape labelled "{label}"')

def list_shapes(asset):
    ss=load_shapes(asset)["shapes"]
    if not ss:
        print(f"No saved shapes for {asset}/{QUOTE}."); return
    print(f"{asset}/{QUOTE} SHAPES\n")
    for s in ss:
        print(f"{s.get('label','(unlabelled)'):<24} {s.get('source_start','?')} -> {s.get('source_end','?')}  {s.get('source_points','?')} points")
        if s.get("description"): print("  "+s["description"])

def show_shape(asset,label):
    s=find_shape(asset,label)
    print(f"{asset}/{QUOTE}")
    print(f"Shape:       {s['label']}")
    print(f"Period:      {s['source_start']} -> {s['source_end']}")
    print(f"Points:      {s['source_points']}")
    print(f"Source low:  {s['source_low']}")
    print(f"Source high: {s['source_high']}")
    if s.get("description"): print(f"Description: {s['description']}")
    print("\nNORMALIZED POINTS\n-----------------")
    for pt in s["points"]: print(f"x={pt['x']:.4f}  y={pt['y']:.4f}")
    print("\nSVG PATH\n--------")
    print(s["svg"]["path"])

def main():
    ap=argparse.ArgumentParser(description="Capture normalized historical price shapes.")
    ap.add_argument("asset")
    ap.add_argument("start_date",nargs="?")
    ap.add_argument("end_date",nargs="?")
    ap.add_argument("--label")
    ap.add_argument("--description",default="")
    ap.add_argument("--list",action="store_true")
    ap.add_argument("--show",metavar="LABEL")
    a=ap.parse_args()
    asset=a.asset.upper()
    try:
        if a.list: return list_shapes(asset)
        if a.show: return show_shape(asset,a.show)
        if not (a.start_date and a.end_date and a.label):
            ap.error("capture mode requires start_date, end_date and --label")
        s,replaced=add_shape(asset,a.start_date,a.end_date,a.label,a.description)
        print(f"{'Updated' if replaced else 'Added'} shape: {s['label']}")
        print(f"Asset:       {asset}/{QUOTE}")
        print(f"Period:      {s['source_start']} -> {s['source_end']}")
        print(f"Points:      {s['source_points']}")
        print(f"Stored in:   {shapes_path(asset)}")
        print("\nSVG path generated for later manual smoothing/editing.")
    except (OSError,ValueError,KeyError,json.JSONDecodeError) as e:
        print(f"Error: {e}",file=sys.stderr); sys.exit(1)

if __name__=="__main__":
    main()
