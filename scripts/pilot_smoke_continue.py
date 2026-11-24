"""Offline, explicit smoke-pilot migration through the sealed current-account bootstrap."""
from pathlib import Path
import argparse,json
from litreview.smoke_migration import migrate
from litreview import structured

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source',required=True);p.add_argument('--run-id',required=True)
    p.add_argument('--source-manifest-sha256',required=True);p.add_argument('--destination-manifest-sha256',required=True)
    args=p.parse_args()
    destination=Path(__file__).resolve().parents[1]
    report=migrate(Path(args.source),destination,args.run_id,args.source_manifest_sha256,args.destination_manifest_sha256)
    print(json.dumps({k:report[k] for k in ('run_id','destination_commit','destination_manifest_sha256','eligible_reuse_count','recorded_spend_usd','outstanding_reservations','status')},indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())
