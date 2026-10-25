"""LLM clients: the real Anthropic model and the selector for the scripted fake."""
import os

MODEL = "claude-sonnet-5-5"
# $ per million tokens (input, output), Anthropic list prices.
PRICES = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
}


def default_model() -> str:
    return os.environ.get("HOTPATH_MODEL", MODEL)


def cost(tokens_in: int, tokens_out: int, model: str = MODEL) -> float:
    p_in, p_out = PRICES.get(model, PRICES[MODEL])
    return (tokens_in * p_in + tokens_out * p_out) / 1e6


class AnthropicLLM:
    def __init__(self, model: str | None = None):
        import anthropic

        self.client = anthropic.Anthropic()
        self.name = model or default_model()

    def bind(self, template_id: str, params: dict) -> None:
        pass

    def create(self, system: str, messages: list, tools: list):
        kwargs = {}
        if self.name == "claude-sonnet-5-5":
            # Sonnet 5.5 rejects disabled thinking; between_tools is its thinking-off mode.
            kwargs["thinking"] = {"type": "between_tools"}
        # Older models (e.g. Sonnet 4.6) run without thinking when the parameter is omitted.
        return self.client.messages.create(
            model=self.name,
            max_tokens=2048,
            system=system,
            messages=messages,
            tools=tools,
            tool_choice={"type": "auto", "disable_parallel_tool_use": True},
            output_config={"effort": "low"},
            **kwargs,
        )


def get_llm():
    if os.environ.get("HOTPATH_LLM", "anthropic") == "fake":
        from hotpath.fake_llm import FakeLLM

        return FakeLLM()
    return AnthropicLLM()
