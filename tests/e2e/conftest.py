"""A live review server over a seeded temporary database."""

import socket
import threading
import time

import pytest
import uvicorn
from playwright.sync_api import Page

from notam_gold.review.app import create_app
from tests.e2e.site import ReviewPage, seed


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def server(gold_db):
    """The review app over a freshly seeded database, served on a free local port."""
    seed(gold_db)
    port = _free_port()
    config = uvicorn.Config(create_app(gold_db.path, "Tester"), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join()


@pytest.fixture
def review(page: Page, server) -> ReviewPage:
    return ReviewPage(page, server).open()
