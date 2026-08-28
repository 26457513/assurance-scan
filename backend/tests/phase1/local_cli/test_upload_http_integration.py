"""Real stdlib HTTP integration checks for response-loss recovery."""

from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.modules.atomic.local_cli.upload_client import (
    StdlibUploadClient,
    UploadBundle,
    UploadClientConfig,
    UploadDisposition,
)


class _RecoveryHandler(BaseHTTPRequestHandler):
    posts = 0
    status_checks = 0
    request_id = ""

    def do_POST(self) -> None:  # noqa: N802
        type(self).posts += 1
        length = int(self.headers["Content-Length"])
        self.rfile.read(length)
        assert self.headers["Authorization"].startswith("Bearer ")
        type(self).request_id = self.headers["Idempotency-Key"]
        self.close_connection = True

    def do_GET(self) -> None:  # noqa: N802
        type(self).status_checks += 1
        body = json.dumps({
            "request_id": type(self).request_id,
            "status": "completed",
            "run_id": "local-recovered",
            "project_id": 42,
            "run_url": "https://scan.example.test/scans/local-recovered",
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *args: object) -> None:
        return


def test_server_commit_response_loss_recovers_without_second_post(tmp_path: Path) -> None:
    request_id = str(uuid.uuid4())
    metadata = tmp_path / "metadata.json"
    findings = tmp_path / "findings.json"
    metadata.write_text("{}")
    findings.write_text("{}")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RecoveryHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = StdlibUploadClient().upload(
            UploadBundle(request_id, metadata, findings),
            UploadClientConfig(
                base_url=f"http://127.0.0.1:{server.server_port}",
                token="asu_v1_test-token-not-logged",
                allow_loopback_http=True,
                max_attempts=2,
            ),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result.disposition is UploadDisposition.REPLAYED
    assert result.run_id == "local-recovered"
    assert _RecoveryHandler.posts == 1
    assert _RecoveryHandler.status_checks == 1
