"""Sealed A06-only operational entry point; invoked through bootstrap.py."""
from pathlib import Path
import argparse,json
from litreview.pilot7_semantics_continue import main
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['audit','a06-strict','a06-only','remaining-strict','scope']);p.add_argument('run_id');a=p.parse_args()
    result=main(Path(__file__).resolve().parents[1],a.action,a.run_id)
    print(json.dumps(result,indent=2))
    if result.get('accepted') is False:raise SystemExit(2)
