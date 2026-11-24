"""Execution requirements for a sealed runtime; no fixed account name or SID."""
from __future__ import annotations

import os
from pathlib import Path
import sys


class ExecutionRefused(RuntimeError):
    pass


def validate_context(*, platform: str, elevated: bool, administrator: bool,
                     isolated: bool, no_site: bool, no_bytecode: bool) -> None:
    if platform != "win32":
        raise ExecutionRefused("This runtime requires Windows token verification")
    if elevated or administrator:
        raise ExecutionRefused("Use a non-administrator process; no model or network operation started")
    if not (isolated and no_site and no_bytecode):
        raise ExecutionRefused("Launch with python -I -S -B; user-site and editable import hooks must be disabled")


def windows_token() -> dict:
    import ctypes as c
    import ctypes.wintypes as w
    if sys.platform != "win32":
        raise ExecutionRefused("This runtime requires Windows token verification")
    a=c.WinDLL("advapi32",use_last_error=True)
    k=c.WinDLL("kernel32",use_last_error=True)
    shell=c.WinDLL("shell32",use_last_error=True)
    k.GetCurrentProcess.restype=w.HANDLE
    a.OpenProcessToken.argtypes=[w.HANDLE,w.DWORD,c.POINTER(w.HANDLE)]
    a.GetTokenInformation.argtypes=[w.HANDLE,w.DWORD,w.LPVOID,w.DWORD,c.POINTER(w.DWORD)]
    a.ConvertSidToStringSidW.argtypes=[w.LPVOID,c.POINTER(w.LPWSTR)]
    k.CloseHandle.argtypes=[w.HANDLE]
    k.LocalFree.argtypes=[w.LPVOID]
    token=w.HANDLE()
    if not a.OpenProcessToken(k.GetCurrentProcess(),8,c.byref(token)):
        raise ExecutionRefused("Cannot verify process token")
    try:
        size=w.DWORD()
        a.GetTokenInformation(token,1,None,0,c.byref(size))
        info=c.create_string_buffer(size.value)
        if not a.GetTokenInformation(token,1,info,size,c.byref(size)):
            raise ExecutionRefused("Cannot verify token identity")
        sid=w.LPWSTR()
        if not a.ConvertSidToStringSidW(c.cast(info,c.POINTER(w.LPVOID))[0],c.byref(sid)):
            raise ExecutionRefused("Cannot read token identity")
        try: actual=sid.value
        finally:k.LocalFree(c.cast(sid,w.LPVOID))
        elevation=w.DWORD()
        if not a.GetTokenInformation(token,20,c.byref(elevation),4,c.byref(size)):
            raise ExecutionRefused("Cannot verify token elevation")
        return {"sid":actual,"elevated":bool(elevation.value),"administrator":bool(shell.IsUserAnAdmin())}
    finally:k.CloseHandle(token)


def require_execution_context() -> dict:
    token=windows_token()
    validate_context(platform=sys.platform,elevated=token["elevated"],administrator=token["administrator"],
                     isolated=bool(sys.flags.isolated),no_site=bool(sys.flags.no_site),no_bytecode=sys.dont_write_bytecode)
    return {**token,"isolation":"same-account filesystem access; no separate-account ACL isolation claimed"}


def load_current_account_keys(env_file: Path | None, env=None) -> dict:
    """Load allowlisted API keys into this process only; return presence/source metadata, never values."""
    from .preflight import require_clean_endpoints, REDIRECTING_ENV
    env=os.environ if env is None else env
    require_clean_endpoints(env)
    names=("ANTHROPIC_API_KEY","OPENAI_API_KEY","MOONSHOT_API_KEY")
    sources={name:"process" if env.get(name) else None for name in names}
    if env_file is not None:
        path=Path(env_file)
        resolved=path.resolve(strict=True)
        if path.is_symlink() or not resolved.is_relative_to(Path.home().resolve()):
            raise ExecutionRefused("Credential file must be inside the current account profile")
        from dotenv import dotenv_values
        values=dotenv_values(resolved,interpolate=False)
        if any(values.get(name) for name in REDIRECTING_ENV):
            raise ExecutionRefused("Credential file contains provider endpoint redirection; nothing loaded")
        for name in names:
            if not env.get(name) and values.get(name):
                env[name]=values[name]
                sources[name]="current-account explicit env file"
    require_clean_endpoints(env)
    return {name:{"present":bool(env.get(name)),"source":sources[name]} for name in names}
