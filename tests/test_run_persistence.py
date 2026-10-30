"""JSON persistence must not materialize whole documents or destroy accepted artifacts."""
import json
import pytest
from litreview import orchestrator as orch


def test_run_save_streams_unicode_without_whole_document_dumps(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, 'RUNS_DIR', tmp_path)
    run = orch.Run('stream')
    payload = {'evidence': ['µM ⟦P1⟧\n' * 1000] * 256, 'nullable': None}
    expected = json.dumps(payload, ensure_ascii=False, indent=2)
    monkeypatch.setattr(json, 'dumps', lambda *a, **k: pytest.fail('whole document dumps'))
    sizes = []
    original = orch.os.fdopen
    class Writer:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): return self
        def __exit__(self, *args): self.stream.close()
        def write(self, value):
            sizes.append(len(value))
            return self.stream.write(value)
    monkeypatch.setattr(orch.os, 'fdopen', lambda *a, **k: Writer(original(*a, **k)))
    run.save('nested/evidence.json', payload)
    assert run.data('nested/evidence.json').read_text(encoding='utf-8') == expected
    assert run.load('nested/evidence.json') == payload
    assert max(sizes) < len(expected) // 100
    assert not list(run.data('nested/evidence.json').parent.glob('.*.tmp'))


@pytest.mark.parametrize('failure', ['encode', 'interrupt', 'replace'])
def test_run_save_failure_preserves_previous_accepted_artifact(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(orch, 'RUNS_DIR', tmp_path)
    run = orch.Run('atomic')
    run.save('accepted.json', {'accepted': 'original'})
    before = run.data('accepted.json').read_bytes()
    if failure == 'encode':
        payload = {'partial': [1, object()]}
        error = TypeError
    elif failure == 'interrupt':
        def interrupted(obj, stream, **kw):
            stream.write('{"partial":')
            raise KeyboardInterrupt('simulated interruption')
        monkeypatch.setattr(json, 'dump', interrupted)
        payload, error = {'partial': 1}, KeyboardInterrupt
    else:
        def refused(*args): raise OSError('simulated replace failure')
        monkeypatch.setattr(orch.os, 'replace', refused)
        payload, error = {'replacement': 1}, OSError
    with pytest.raises(error): run.save('accepted.json', payload)
    assert run.data('accepted.json').read_bytes() == before
    assert not list(run.data('accepted.json').parent.glob('.*.tmp'))


@pytest.mark.parametrize('payload', [None, {'\u00b5M': ['\u27e6P1\u27e7', '\n', True, 0.125], 'z': {'b': 1, 'a': 2}},
                                     {'shared': ['qualification' * 1000] * 256}])
def test_streaming_fingerprint_keeps_existing_canonical_identity(payload, monkeypatch):
    import hashlib
    from litreview import synthesis_registry as registry
    expected = hashlib.sha256(registry.canonical(payload).encode('utf-8')).hexdigest()
    monkeypatch.setattr(registry, 'canonical', lambda *a: pytest.fail('whole document canonical'))
    assert registry.fingerprint(payload) == expected


def test_load_preserves_crlf_strings_and_accepts_crlf_json(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, 'RUNS_DIR', tmp_path)
    run = orch.Run('load')
    run.data('crlf.json').write_bytes(b'{\r\n"text": "line1\\r\\nline2"\r\n}')
    assert run.load('crlf.json') == {'text': 'line1\r\nline2'}
    assert run.load('missing.json', {'default': 1}) == {'default': 1}
