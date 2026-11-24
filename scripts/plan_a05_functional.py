"""Offline planning only. Does not load keys or dispatch; writes only the requested report path."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from litreview.a05_functional import plan
from litreview.budget import BudgetTracker
from litreview import structured
p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
a=p.parse_args()
structured.RECORD=a.run_dir/'structured_output.json'
result=plan(BudgetTracker(a.run_dir))
a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2))
