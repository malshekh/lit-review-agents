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
    """Tests drive runs past CP2 with fake models: the spend guard (Run._require_projection) is off unless a
    test is marked `projection_guard`, which tests the guard itself."""
    if request.node.get_closest_marker("projection_guard"):
        return
    from litreview import orchestrator
    monkeypatch.setattr(orchestrator.Run, "_require_projection", lambda self: None)


def pytest_configure(config):
    config.addinivalue_line("markers", "projection_guard: run with the CP2 cost-projection spend guard on")
