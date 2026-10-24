import os

import pytest

from hotpath import store, tasks
from hotpath.runtime import Runtime


@pytest.fixture(scope="module")
def rt(server_url):
    from hotpath.fake_llm import FakeLLM

    r = Runtime(llm_factory=FakeLLM)
    yield r
    r.close()


@pytest.mark.parametrize("template_id", list(tasks.TEMPLATES))
def test_interpreter_completes_each_task(rt, template_id):
    store.reset()
    run = rt.run(template_id)
    assert run["ok"] and run["correct"], run
    assert run["tier"] == "interpreted"
    assert [s["action"] for s in run["trace"]] == ["fill", "click", "extract_table"]
    assert run["llm_calls"] == 4 and run["cost"] > 0 and run["ms"] > 0
    assert set(run["trace"][0]) == {"step", "action", "selector", "args"}
    assert store.load("runs.json", [])[-1]["id"] == run["id"]


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="no ANTHROPIC_API_KEY")
def test_live_smoke_price_of(rt):
    """One real-model run of task 1."""
    from hotpath.fake_llm import FakeLLM
    from hotpath.llm import AnthropicLLM

    store.reset()
    rt.llm_factory = AnthropicLLM
    try:
        run = rt.run("price_of", {"product": "Pruning Shears"})
    finally:
        rt.llm_factory = FakeLLM
    assert run["ok"], run
    assert run["result"] == {"price": "$19.99"}
    assert run["llm_calls"] <= 15 and run["cost"] > 0
