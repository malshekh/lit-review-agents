from dataclasses import dataclass


def as_parts(user) -> list[dict]:
    """A user message as [{"text", "cache"}] blocks (agents pass blocks; a plain string is one block)."""
    return [{"text": user, "cache": False}] if isinstance(user, str) else list(user)


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    input_tokens: int                      # uncached input only (cache reads and writes are counted below)
    output_tokens: int
    stop_reason: str | None = None         # "refusal" when a provider declined for policy reasons
    refusal_category: str | None = None
    cached_input_tokens: int = 0           # read from the prompt cache
    cache_write_tokens: int = 0            # written to the prompt cache
