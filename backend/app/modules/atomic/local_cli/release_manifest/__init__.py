"""Public API for signed local-CLI release metadata."""

from .models import CLIReleaseManifest, ReleaseManifestError
from .service import CLI_IMAGE, SIGNATURE_ISSUER, validate_release_manifest

__all__ = [
    "CLIReleaseManifest",
    "CLI_IMAGE",
    "ReleaseManifestError",
    "SIGNATURE_ISSUER",
    "validate_release_manifest",
]
