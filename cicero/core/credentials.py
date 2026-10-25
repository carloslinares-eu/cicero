"""Loading Google Cloud credentials: a service account key file, or Application Default Credentials."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import google.auth
import google.auth.exceptions
from google.auth.credentials import Credentials
from google.oauth2 import service_account

from cicero.core.errors import CredentialsError

SCOPES = ["https://www.googleapis.com/auth/cloud-translation"]


@dataclass(frozen=True, slots=True)
class CloudAccount:
    """Credentials plus the Google Cloud project that Translation requests are billed to."""

    credentials: Credentials
    project_id: str
    source: str  # what the credentials came from, for display: a file path or "Application Default Credentials"


def load_key_file(path: str | Path, project_id: str | None = None) -> CloudAccount:
    """Read a service account key (the JSON file downloaded from the Google Cloud console)."""
    path = Path(path)
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CredentialsError(f"Key file not found:\n{path}") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise CredentialsError(f"Can't read the key file:\n{path}\n\n{exc}") from None
    except json.JSONDecodeError:
        raise CredentialsError("This isn't a Google Cloud key file (it isn't valid JSON).") from None

    if not isinstance(info, dict) or info.get("type") != "service_account":
        kind = info.get("type") if isinstance(info, dict) else None
        hint = " It looks like an OAuth client ID file." if isinstance(info, dict) and "installed" in info else ""
        raise CredentialsError(
            f"This isn't a service account key (type: {kind or 'unknown'}).{hint}\n\n"
            "Create one under IAM & Admin → Service Accounts → Keys → Add key → JSON."
        )
    try:
        credentials = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    except (ValueError, KeyError) as exc:
        raise CredentialsError(f"The key file is incomplete or damaged:\n{exc}") from None

    project = project_id or info.get("project_id")
    if not project:
        raise CredentialsError("The key file doesn't say which Google Cloud project it belongs to.")
    return CloudAccount(credentials, project, str(path))


def load_default(project_id: str | None = None) -> CloudAccount:
    """Use Application Default Credentials (``GOOGLE_APPLICATION_CREDENTIALS`` or ``gcloud auth``)."""
    try:
        credentials, project = google.auth.default(scopes=SCOPES, quota_project_id=project_id)
    except google.auth.exceptions.DefaultCredentialsError as exc:
        raise CredentialsError(f"No Application Default Credentials found.\n\n{exc}") from None
    project = project_id or project
    if not project:
        raise CredentialsError(
            "Application Default Credentials were found, but no Google Cloud project.\n"
            "Run `gcloud config set project <PROJECT_ID>` or choose a key file instead."
        )
    return CloudAccount(credentials, project, "Application Default Credentials")
