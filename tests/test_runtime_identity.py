"""Offline tests for privilege, endpoint and credential-source execution requirements."""
from pathlib import Path
import pytest
from litreview import runtime_identity as identity
from litreview.preflight import PreflightRefused


def context(**over):
    return dict(platform='win32',elevated=False,administrator=False,isolated=True,no_site=True,no_bytecode=True)|over


def test_any_non_admin_windows_account_is_accepted():
    identity.validate_context(**context())


@pytest.mark.parametrize('over',[{'elevated':True},{'administrator':True},{'platform':'linux'},
                                {'isolated':False},{'no_site':False},{'no_bytecode':False}])
def test_unsafe_contexts_fail_closed(over):
    with pytest.raises(identity.ExecutionRefused):identity.validate_context(**context(**over))


def test_keys_are_presence_only_and_process_keys_win(tmp_path,monkeypatch):
    monkeypatch.setattr(Path,'home',lambda:tmp_path)
    p=tmp_path/'.env'; p.write_text('OPENAI_API_KEY=file-secret\nMOONSHOT_API_KEY=kimi-secret\nUNRELATED=ignored\n')
    env={'OPENAI_API_KEY':'process-secret'}
    meta=identity.load_current_account_keys(p,env)
    assert env=={'OPENAI_API_KEY':'process-secret','MOONSHOT_API_KEY':'kimi-secret'}
    assert meta['OPENAI_API_KEY']=={'present':True,'source':'process'}
    assert 'secret' not in str(meta) and not meta['ANTHROPIC_API_KEY']['present']


def test_redirecting_process_or_env_file_is_refused_before_loading_keys(tmp_path,monkeypatch):
    monkeypatch.setattr(Path,'home',lambda:tmp_path)
    with pytest.raises(PreflightRefused):identity.load_current_account_keys(None,{'OPENAI_BASE_URL':'https://other.invalid'})
    p=tmp_path/'.env'; p.write_text('OPENAI_API_KEY=secret\nANTHROPIC_AUTH_TOKEN=redirect\n')
    env={}
    with pytest.raises(identity.ExecutionRefused):identity.load_current_account_keys(p,env)
    assert not env


def test_other_account_credential_file_is_refused(tmp_path,monkeypatch):
    own=tmp_path/'own'; own.mkdir()
    p=tmp_path/'other.env'; p.write_text('OPENAI_API_KEY=secret\n')
    monkeypatch.setattr(Path,'home',lambda:own)
    with pytest.raises(identity.ExecutionRefused):identity.load_current_account_keys(p,{})
