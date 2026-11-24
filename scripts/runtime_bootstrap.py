"""Launch inventoried runtime code under a non-administrator current Windows account."""
import json
from pathlib import Path
import runpy
import sys

ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'vendor')]


def main():
    from litreview.runtime_identity import require_execution_context, load_current_account_keys
    from litreview.runtime_integrity import verify
    require_execution_context()
    args=sys.argv[1:]
    env_file=None
    if args[:1]==['--env-file']:
        if len(args)<3:raise SystemExit('Use --env-file CURRENT_ACCOUNT_FILE SCRIPT [ARGS]')
        env_file=Path(args[1]); args=args[2:]
    if not args:raise SystemExit('Use python -I -S -B bootstrap.py [--env-file PATH] SCRIPT [ARGS]')
    manifest=json.loads((ROOT/'frozen_runtime_manifest.json').read_text(encoding='utf-8'))
    verify(ROOT,manifest)
    script=(ROOT/args[0]).resolve()
    if not script.is_relative_to(ROOT) or script.relative_to(ROOT).as_posix() not in manifest['files']:
        raise SystemExit('Execution target must be an inventoried immutable runtime file')
    load_current_account_keys(env_file)
    sys.argv=[str(script),*args[1:]]
    runpy.run_path(str(script),run_name='__main__')


if __name__=='__main__':main()
