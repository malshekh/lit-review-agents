from dataclasses import dataclass


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str | None = None
