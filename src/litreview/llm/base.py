from dataclasses import dataclass


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str                      # the model that produced `text` (a fallback model if one served it)
    input_tokens: int
    output_tokens: int
    stop_reason: str | None = None
    refusal_category: str | None = None   # set when stop_reason == "refusal"
    usage_parts: list[tuple[str, int, int]] | None = None   # (model, input, output) per billed model
