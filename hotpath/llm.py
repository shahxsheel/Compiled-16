"""LLM clients: the real Anthropic model and the selector for the scripted fake."""
import os

MODEL = "claude-sonnet-5-5"
PRICE_IN, PRICE_OUT = 2.00 / 1e6, 10.00 / 1e6  # $/token for claude-sonnet-5-5


def cost(tokens_in: int, tokens_out: int) -> float:
    return tokens_in * PRICE_IN + tokens_out * PRICE_OUT


class AnthropicLLM:
    name = MODEL

    def __init__(self):
        import anthropic

        self.client = anthropic.Anthropic()

    def bind(self, template_id: str, params: dict) -> None:
        pass

    def create(self, system: str, messages: list, tools: list):
        return self.client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=system,
            messages=messages,
            tools=tools,
            tool_choice={"type": "auto", "disable_parallel_tool_use": True},
            thinking={"type": "between_tools"},
            output_config={"effort": "low"},
        )


def get_llm():
    if os.environ.get("HOTPATH_LLM", "anthropic") == "fake":
        from hotpath.fake_llm import FakeLLM

        return FakeLLM()
    return AnthropicLLM()
