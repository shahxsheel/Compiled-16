import os
import socket
import threading
import time

import pytest
import uvicorn


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server_url(tmp_path_factory):
    home = tmp_path_factory.mktemp("hotpath_home")
    os.environ["HOTPATH_HOME"] = str(home)
    os.environ["HOTPATH_LLM"] = "fake"
    port = _free_port()
    os.environ["HOTPATH_BASE_URL"] = f"http://127.0.0.1:{port}"
    from hotpath.server import app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(timeout=5)


@pytest.fixture(scope="session")
def rt(server_url):
    from hotpath.fake_llm import FakeLLM
    from hotpath.runtime import Runtime

    r = Runtime(llm_factory=FakeLLM)
    yield r
    r.close()


@pytest.fixture
def fresh(server_url):
    """Clean state and the original (non-redesigned) site."""
    import httpx

    from hotpath import store
    from hotpath.server import SITE

    store.reset()
    SITE["redesign"] = False
    yield
    SITE["redesign"] = False
