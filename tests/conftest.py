import pytest


class FakeResp:
    def __init__(self, payload=None, status=200, text=""):
        self._payload, self.status_code, self.text = payload, status, text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")


@pytest.fixture
def fake_get(monkeypatch):
    """Route requests.get/post by URL substring to canned payloads: fake_get({"substring": payload})."""
    import requests

    def install(routes: dict, method: str = "get"):
        calls = []

        def _fake(url, *a, **kw):
            calls.append((url, kw.get("params"), kw.get("json")))
            for key, payload in routes.items():
                if key in url:
                    return payload if isinstance(payload, FakeResp) else FakeResp(payload)
            return FakeResp(None, 404)
        monkeypatch.setattr(requests, method, _fake)
        return calls
    return install


@pytest.fixture(autouse=True)
def _projection_guard(request, monkeypatch):
    """Tests drive runs past CP2 with fake models: the spend guards (Run._require_projection, the worst-case line
    check, the batch gate, and the downstream re-projection, gate, line and long-context checks) are off unless a
    test is marked `projection_guard`, which tests the guards."""
    if request.node.get_closest_marker("projection_guard"):
        return
    from litreview import orchestrator
    monkeypatch.setattr(orchestrator.Run, "_require_projection", lambda self: None)
    monkeypatch.setattr(orchestrator.Run, "_check_worst_case_line", lambda self, agent_id: None)
    monkeypatch.setattr(orchestrator.Run, "_batch_gate", lambda self, *a, **k: None)
    monkeypatch.setattr(orchestrator.Run, "_reproject", lambda self, stage: None)
    monkeypatch.setattr(orchestrator.Run, "_downstream_gate", lambda self, *a, **k: None)
    monkeypatch.setattr(orchestrator.Run, "_check_request_line", lambda self, agent_id: None)
    monkeypatch.setattr(orchestrator.Run, "_check_long_context", lambda self, agent_id, a: None)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No test reaches the network: any socket connection or name lookup fails the test. Paid and free provider
    endpoints alike are only ever called from the audit scripts, never from tests."""
    import socket

    def refuse(*a, **k):
        raise AssertionError(f"a test tried to reach the network: {a[:2]}")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    # the free provider token count (context_watch) is a network call too: never from a test
    from litreview import context_watch
    monkeypatch.setattr(context_watch, "anthropic_counter", lambda *a, **k: None)


def pytest_configure(config):
    config.addinivalue_line("markers", "projection_guard: run with the CP2 cost-projection spend guard on")
