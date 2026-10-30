"""Record each downstream model's context window from its provider's model-metadata endpoint. No generation.

    python -B tests/model_window_probe.py

Free metadata requests only: Anthropic GET /v1/models/{id} (max_input_tokens), Moonshot GET /v1/models
(context_length), OpenAI GET /v1/models/{id} (reports no window). Writes docs/integration_validation/
model_windows.json and compares it with pipeline.yaml -> admission.context_windows.
"""
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from litreview import config  # noqa: E402

load_dotenv(ROOT.parent / "lit-review-agents" / ".env")
load_dotenv(ROOT / ".env")


def main():
    out, cfg = {}, config.load("pipeline")["admission"]["context_windows"]
    for m in ("claude-opus-5", "claude-sonnet-5-5"):
        r = requests.get(f"https://api.anthropic.com/v1/models/{m}", timeout=30,
                         headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"})
        d = r.json()
        out[m] = {"source": f"GET https://api.anthropic.com/v1/models/{m}", "status": r.status_code,
                  "max_input_tokens": d.get("max_input_tokens"), "max_tokens": d.get("max_tokens")}
    r = requests.get("https://api.moonshot.ai/v1/models", timeout=30,
                     headers={"Authorization": "Bearer " + os.environ["MOONSHOT_API_KEY"]})
    for d in r.json().get("data", []):
        if d["id"] in ("kimi-k3.1-pro", "kimi-k3", "kimi-k2.6"):
            out[d["id"]] = {"source": "GET https://api.moonshot.ai/v1/models", "status": r.status_code,
                            "context_length": d.get("context_length"), "reasoning": d.get("reasoning")}
    r = requests.get("https://api.openai.com/v1/models/gpt-6.1-sol", timeout=30,
                     headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]})
    out["gpt-6.1-sol"] = {"source": "GET https://api.openai.com/v1/models/gpt-6.1-sol", "status": r.status_code,
                          "reported_window": None, "note": "the endpoint reports no context window"}
    for m, v in out.items():
        provider = v.get("max_input_tokens") or v.get("context_length")
        v["configured_window"] = cfg.get(m)
        v["configured_within_provider"] = None if provider is None or cfg.get(m) is None else cfg[m] <= provider
    result = {"retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "models": out}
    path = ROOT / "docs" / "integration_validation" / "model_windows.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
