"""Sealed CP1 approval and CP2-limited discovery launcher."""
import argparse,json
from pathlib import Path
from litreview.pilot7_discovery_continue import main
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['approve-cp1','discover-to-cp2','report-cp2']);p.add_argument('run_id');a=p.parse_args()
    result=main(Path(__file__).resolve().parents[1],a.run_id,a.action)
    print(json.dumps({k:v for k,v in result.items() if k not in ('proposed_papers','query_yield_by_theme','projection')},indent=2))
