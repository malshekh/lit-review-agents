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
