"""Security, retry, recovery, and multipart tests for the local upload client."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.atomic.local_cli.upload_client import (
    HttpResponse,
    StdlibUploadTransport,
    UploadBundle,
    UploadClientConfig,
    UploadClientError,
    UploadDisposition,
    UploadNetworkError,
    UploadRejectedError,
    upload_bundle,
)


class Clock:
    def __init__(self) -> None:
        self.delays: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.delays.append(seconds)


class Transport:
    def __init__(
        self,
        posts: list[HttpResponse | Exception],
        statuses: list[HttpResponse | Exception] | None = None,
    ) -> None:
        self.posts = posts
        self.statuses = statuses or []
        self.post_urls: list[str] = []
        self.status_urls: list[str] = []

    def post_multipart(self, url: str, config: UploadClientConfig, bundle: UploadBundle):
        self.post_urls.append(url)
        value = self.posts.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def get_status(self, url: str, config: UploadClientConfig):
        self.status_urls.append(url)
        if not self.statuses:
            return HttpResponse(404, {}, b"{}")
        value = self.statuses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def _bundle(tmp_path: Path) -> UploadBundle:
    metadata = tmp_path / "metadata.json"
    findings = tmp_path / "findings.json"
    metadata.write_text("{}")
    findings.write_text("{}")
    return UploadBundle("018f47a2-4c72-4c9e-9f60-780cb70b8fe4", metadata, findings)


def _config(**changes) -> UploadClientConfig:
    values = {"base_url": "https://scan.example", "token": "asu_v1_hidden.secret"}
    values.update(changes)
    return UploadClientConfig(**values)


def test_https_required_except_explicit_loopback(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    with pytest.raises(UploadClientError, match="HTTPS"):
        upload_bundle(
            bundle,
            _config(base_url="http://scan.example"),
            transport=Transport([]),
            clock=Clock(),
        )
    response = HttpResponse(201, {}, b'{"run_id":"local-1","project_id":1}')
    result = upload_bundle(
        bundle,
        _config(base_url="http://127.0.0.1:8000", allow_loopback_http=True),
        transport=Transport([response]),
        clock=Clock(),
    )
    assert result.disposition is UploadDisposition.UPLOADED


def test_cross_origin_redirect_is_blocked_before_bearer_forward(tmp_path: Path) -> None:
    transport = Transport([HttpResponse(307, {"location": "https://evil.example/x"}, b"")])
    with pytest.raises(UploadClientError) as exc:
        upload_bundle(_bundle(tmp_path), _config(), transport=transport, clock=Clock())
    assert exc.value.code == "cross_origin_redirect_blocked"
    assert transport.post_urls == ["https://scan.example/api/v1/ingest/local-scans"]


def test_response_loss_recovers_completed_request_without_reposting(tmp_path: Path) -> None:
    network = UploadNetworkError("network_error", "network request failed")
    recovered = HttpResponse(
        200,
        {},
        b'{"status":"completed","run_id":"local-7","project_id":4,"run_url":"/scans/7"}',
    )
    transport = Transport([network], [recovered])
    result = upload_bundle(_bundle(tmp_path), _config(), transport=transport, clock=Clock())
    assert result.disposition is UploadDisposition.REPLAYED
    assert result.run_id == "local-7"
    assert len(transport.post_urls) == 1
    assert transport.status_urls[0].endswith(_bundle(tmp_path).request_id)


def test_only_retryable_statuses_retry_and_respect_retry_after(tmp_path: Path) -> None:
    clock = Clock()
    transport = Transport([
        HttpResponse(429, {"retry-after": "7"}, b'{"code":"upload_quota_exceeded"}'),
        HttpResponse(201, {}, b'{"run_id":"local-1","project_id":1}'),
    ])
    upload_bundle(_bundle(tmp_path), _config(), transport=transport, clock=clock)
    assert clock.delays == [7]

    permanent = Transport([HttpResponse(422, {}, b'{"code":"invalid_scan_schema"}')])
    with pytest.raises(UploadRejectedError) as exc:
        upload_bundle(_bundle(tmp_path), _config(), transport=permanent, clock=Clock())
    assert exc.value.code == "invalid_scan_schema"
    assert len(permanent.post_urls) == 1


def test_stdlib_transport_streams_fixed_multipart_parts(monkeypatch, tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    sent: list[bytes] = []
    headers: dict[str, str] = {}

    class Response:
        status = 201

        def read(self, size: int) -> bytes:
            return b'{"run_id":"local-1"}'

        def getheaders(self):
            return []

    class Connection:
        sock = None

        def putrequest(self, method, target):
            assert method == "POST"

        def putheader(self, name, value):
            headers[name.casefold()] = value

        def endheaders(self):
            pass

        def send(self, content):
            sent.append(content)

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(
        "app.modules.atomic.local_cli.upload_client._adapters.http.client.HTTPConnection",
        lambda *args, **kwargs: Connection(),
    )
    response = StdlibUploadTransport().post_multipart(
        "http://127.0.0.1/api/v1/ingest/local-scans",
        _config(base_url="http://127.0.0.1", allow_loopback_http=True),
        bundle,
    )
    body = b"".join(sent)
    assert response.status == 201
    assert b'name="metadata"' in body and b'name="findings"' in body
    assert headers["authorization"].startswith("Bearer asu_v1_")
    assert int(headers["content-length"]) == len(body)


def test_errors_never_embed_token_or_outbox_path(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    bundle.metadata_path.unlink()
    with pytest.raises(UploadClientError) as exc:
        StdlibUploadTransport().post_multipart(
            "http://127.0.0.1/upload",
            _config(base_url="http://127.0.0.1", allow_loopback_http=True),
            bundle,
        )
    rendered = str(exc.value)
    assert str(tmp_path) not in rendered
    assert "asu_v1_" not in rendered
