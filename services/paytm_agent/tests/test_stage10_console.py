"""Stage 10 — the employee console is served and wired to the real endpoints."""
from __future__ import annotations

import re


def test_the_console_is_served_as_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")


def test_it_has_the_three_sections_the_contract_asks_for(client):
    html = client.get("/").text
    for anchor in ('id="strip"', 'id="queue"', 'id="feed"'):
        assert anchor in html, anchor


def test_it_reads_the_endpoints_this_service_actually_exposes(client):
    html = client.get("/").text
    for path in ("/metrics", "/tickets", "/summaries", "/claim"):
        assert path in html, path

    # Same-origin relative paths only: a hard-coded host would break the deployed link.
    assert "http://localhost" not in html
    assert "127.0.0.1" not in html


def test_it_shows_the_sub_agent_trace(client):
    """The mesh is the differentiator; if the console does not surface it, nobody sees it."""
    assert "agent_trace" in client.get("/").text


def test_empty_states_render_a_dash_not_nan(client):
    """A cold-start console must not show NaN or undefined to a judge."""
    html = client.get("/").text
    assert "—" in html
    assert "Number.isNaN" in html
