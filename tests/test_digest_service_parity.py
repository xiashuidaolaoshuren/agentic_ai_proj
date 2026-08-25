"""Parity tests: warm digest service vs CLI fake digest output."""

from __future__ import annotations

import io
import json
import re
import threading
import time
from http.client import HTTPConnection
from pathlib import Path

from ai_news_agent.cli import main as cli_main


def _start_fake_service(tmp_path: Path) -> tuple[int, object]:
    from ai_news_agent.app.digest_service import DigestServiceServer

    server = DigestServiceServer(
        host="127.0.0.1",
        port=0,
        db_path=tmp_path / "parity.db",
        fake=True,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5.0
    while server.port is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.port is not None
    return server.port, server


_GENERATED_LINE = re.compile(r"^.*Generated:.*$")


def _strip_generated_timestamp(text: str) -> str:
    lines = [line for line in text.splitlines() if not _GENERATED_LINE.match(line)]
    return "\n".join(lines).strip()


def test_service_fake_digest_matches_cli_fake_digest(tmp_path: Path) -> None:
    port, server = _start_fake_service(tmp_path)

    cli_buf = io.StringIO()
    cli_code = cli_main(
        [
            "digest",
            "--fake",
            "--db-path",
            str(tmp_path / "cli.db"),
            "--sources",
            "github",
            "--topics",
            "RAG",
        ],
        stdout=cli_buf,
    )
    assert cli_code == 0
    cli_text = cli_buf.getvalue()

    conn = HTTPConnection("127.0.0.1", port, timeout=30)
    body = json.dumps(
        {
            "sources": "github",
            "topics": ["RAG"],
            "fake": True,
        }
    )
    conn.request(
        "POST",
        "/digest",
        body=body,
        headers={"Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    assert resp.status == 200
    service_text = json.loads(resp.read().decode())["text"]

    server.shutdown()

    assert "AI News Digest" in cli_text
    assert "Fake GitHub repo" in cli_text
    assert "Fake GitHub repo" in service_text
    assert _strip_generated_timestamp(cli_text) == _strip_generated_timestamp(service_text)
