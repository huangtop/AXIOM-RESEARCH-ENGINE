#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
from axiom_engine.automation import build_metrics, build_trends, load_history

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output-dir', default='data/generated/automation')
    p.add_argument('--trend-window', type=int, default=30)
    a=p.parse_args(); out=Path(a.output_dir)
    if not out.is_absolute(): out=ROOT/out
    history=load_history(out/'history')
    metrics=build_metrics(history); trends=build_trends(history,a.trend_window)
    write(out/'automation_metrics.json',metrics); write(out/'automation_trends.json',trends)
    print(json.dumps({'history_runs':len(history),'metrics_path':str(out/'automation_metrics.json'),'trends_path':str(out/'automation_trends.json')},indent=2))
    return 0
if __name__=='__main__': raise SystemExit(main())
