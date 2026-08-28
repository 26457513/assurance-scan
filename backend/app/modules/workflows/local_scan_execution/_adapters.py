"""Default bridge from execution workflow config to the stdlib upload client."""

from app.modules.atomic.local_cli.upload_client import (
    StdlibUploadClient,
    UploadBundle,
    UploadClientConfig,
    UploadClientError,
    UploadResult,
)

from .models import LocalCLIConfig


class DefaultLocalUploadPort:
    def __init__(self) -> None:
        self._client = StdlibUploadClient()

    def upload(self, bundle: UploadBundle, config: LocalCLIConfig) -> UploadResult:
        if config.token is None:
            raise UploadClientError("not_enrolled", "scan upload token is not configured")
        return self._client.upload(
            bundle,
            UploadClientConfig(
                base_url=config.api_base_url,
                token=config.token,
                custom_ca_file=config.custom_ca_file,
                allow_loopback_http=config.allow_loopback_http,
            ),
        )


__all__ = ["DefaultLocalUploadPort"]
