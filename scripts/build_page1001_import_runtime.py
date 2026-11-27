import sys, shutil, json
from pathlib import Path
from build_pilot7_cp_syn_runtime import RUN, seal
from build_pilot7_page1001_runtime import DEST as OLD
from build_pilot7_readiness_runtime import REPO, git
DEST=OLD.with_name('execution-20261126-v41-pilot7-cp3-50usd')
PIN='437bcca20bb0f942ef84d0763591fcec9458a768229a566abf37c1531060bf34'
if __name__=='__main__':
    assert sys.dont_write_bytecode and not git('status','--porcelain').strip() and not DEST.exists()
    sys.path[:0]=[str(REPO/'src'),str(OLD/'vendor')]
    from litreview.runtime_integrity import sha,verify
    source=Path(sys.argv[1])
    assert sha(source/'page1001.recovery-v2.json')=='665b268d30c2a02f3584832b09d89b87af7fd88f9fd5578ef9e60806907d7195'
    assert sha(source/'evidence.json')=='c9db5535fcf2e4c24696e0d77d4ee3ea6c8e3138ec1e6bd0c379c16cf7be4464'
    manifest=OLD/'frozen_runtime_manifest.json'
    assert sha(manifest)==PIN
    m=json.loads(manifest.read_bytes())
    verify(OLD,m)
    run=OLD/'runs'/RUN
    before={p.relative_to(run).as_posix():sha(p) for p in run.rglob('*') if p.is_file()}
    seal(OLD,DEST,m,before,PIN,'v40','v41',Path(__file__),'CP3')
    dest=DEST/'runs'/RUN/'data/recovery/page1001_import_v2'
    dest.mkdir()
    for name in ['page1001.recovery-v2.json','evidence.json','changes.diff','validation.json']:
        shutil.copy2(source/name,dest/name)
