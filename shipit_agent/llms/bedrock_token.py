"""Derive a Bedrock **bearer token** from ordinary AWS credentials.

Some Bedrock surfaces — notably the OpenAI-compatible ``bedrock-mantle``
endpoint that serves Gemma 4 — authenticate with a *Bedrock API key* sent as an
HTTP bearer token, not with SigV4 request signing. Everything else on Bedrock
(Anthropic, Nova, Llama, Mistral, Titan via the Converse API) uses SigV4. So an
environment holding perfectly good ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY``
— or a profile, an SSO login, an EC2 instance role, an ECS task role, an EKS web
identity — could reach every Bedrock model *except* the mantle ones, and failed
at the first call with an opaque 401.

It does not have to. A short-term Bedrock API key **is** a SigV4 presigned
request: sign ``POST https://bedrock.amazonaws.com/?Action=CallWithBearerToken``
with the ``bedrock`` service name, drop the scheme, append a version marker,
base64 it, and prefix ``bedrock-api-key-``. That is exactly what AWS's own
``aws-bedrock-token-generator`` package does, and it needs nothing this package
does not already have: ``botocore`` ships inside ``boto3``, which is already the
``[bedrock]`` extra.

So: any credential the standard AWS chain can resolve becomes a mantle bearer
token, automatically. Nothing is hardcoded — region, credentials and lifetime
all resolve through botocore's own machinery, and an explicitly supplied token
always wins over a derived one.

Tokens are cached per (region, access-key) and refreshed at 80% of their
lifetime, because signing is pure local crypto but not free, and a 12-hour token
re-derived on every request would be waste with a clock-skew failure mode.

If the official ``aws-bedrock-token-generator`` is installed it is used
verbatim, so AWS remains the source of truth for the format; the botocore
implementation below is the fallback that keeps this working without adding a
dependency.
"""

from __future__ import annotations

import base64
import os
import threading
import time
from typing import Any

#: AWS's documented ceiling for a short-term Bedrock API key.
MAX_TOKEN_DURATION = 43_200  # 12 hours

#: Refresh once this fraction of the lifetime has elapsed, so a long-running
#: agent never presents a token that expires mid-request.
_REFRESH_AT = 0.8

# Signing constants, per AWS's aws-bedrock-token-generator. The host is global
# (not per-region) even though the *signature* is regional — the region binds
# through SigV4's credential scope, not the URL.
_HOST = "bedrock.amazonaws.com"
_URL = f"https://{_HOST}/"
_SERVICE = "bedrock"
_PREFIX = "bedrock-api-key-"
_VERSION = "&Version=1"

#: Env vars that may already hold a ready-made key, most specific first.
BEARER_ENV_VARS = ("AWS_BEARER_TOKEN_BEDROCK", "BEDROCK_MANTLE_API_KEY")

#: Region env vars, in botocore's own order of preference.
REGION_ENV_VARS = ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_REGION_NAME")

_cache: dict[tuple[str, str], tuple[str, float]] = {}
_lock = threading.Lock()


class BedrockTokenError(RuntimeError):
    """No credential could be resolved into a Bedrock bearer token."""


def existing_bearer_token() -> str | None:
    """Return a bearer token already present in the environment, if any."""
    for var in BEARER_ENV_VARS:
        value = os.getenv(var)
        if value:
            return value
    return None


def resolve_region(region: str | None = None) -> str | None:
    """Resolve an AWS region from the argument, the environment, or botocore.

    Falls through to botocore's session so a region set only in
    ``~/.aws/config`` (or by a profile) is honoured just as the CLI honours it.
    """
    if region:
        return region
    for var in REGION_ENV_VARS:
        value = os.getenv(var)
        if value:
            return value
    try:
        from botocore.session import Session

        return Session().get_config_variable("region")
    except Exception:  # noqa: BLE001 — absence of botocore is not an error here
        return None


def _resolve_credentials(profile: str | None = None) -> Any:
    """Resolve credentials through the full standard AWS chain.

    Env vars, shared config/credentials files, SSO, assumed roles, EC2 instance
    metadata, ECS task roles and EKS web identity all arrive through this one
    call — which is the point: this module adds a token format, not a
    credential source.
    """
    try:
        from botocore.session import Session
    except ImportError as exc:  # pragma: no cover - exercised only without boto3
        raise BedrockTokenError(
            "Deriving a Bedrock bearer token needs botocore. "
            "Install it with:  pip install 'shipit-agent[bedrock]'"
        ) from exc

    session = Session(profile=profile) if profile else Session()
    credentials = session.get_credentials()
    if credentials is None:
        raise BedrockTokenError(
            "No AWS credentials found. Configure any one of: "
            "AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY, AWS_PROFILE, an SSO "
            "login, or an attached instance/task role."
        )
    return credentials


def _sign(credentials: Any, region: str, expires: int) -> str:
    """Presign the bearer-token request and encode it as a Bedrock API key."""
    from botocore.auth import SigV4QueryAuth
    from botocore.awsrequest import AWSRequest

    request = AWSRequest(
        method="POST",
        url=_URL,
        headers={"host": _HOST},
        params={"Action": "CallWithBearerToken"},
    )
    SigV4QueryAuth(credentials, _SERVICE, region, expires=expires).add_auth(request)

    presigned = request.url.replace("https://", "") + _VERSION
    return _PREFIX + base64.b64encode(presigned.encode("utf-8")).decode("utf-8")


def generate_bearer_token(
    *,
    region: str | None = None,
    profile: str | None = None,
    expires_in: int = MAX_TOKEN_DURATION,
    use_cache: bool = True,
) -> str:
    """Derive a short-term Bedrock bearer token from AWS credentials.

    Args:
        region: AWS region. Resolved from the environment or botocore config
            when omitted.
        profile: Named AWS profile to resolve credentials from.
        expires_in: Token lifetime in seconds; AWS caps this at 12 hours.
        use_cache: Reuse a cached token until 80% of its lifetime has elapsed.

    Returns:
        A ``bedrock-api-key-…`` string suitable for ``AWS_BEARER_TOKEN_BEDROCK``.

    Raises:
        BedrockTokenError: no region, no credentials, or botocore missing.
    """
    if expires_in <= 0 or expires_in > MAX_TOKEN_DURATION:
        raise BedrockTokenError(
            f"expires_in must be between 1 and {MAX_TOKEN_DURATION} seconds "
            f"(12 hours), got {expires_in}."
        )

    resolved_region = resolve_region(region)
    if not resolved_region:
        raise BedrockTokenError(
            "No AWS region. Set AWS_REGION (or AWS_DEFAULT_REGION), pass "
            "region=..., or configure one in ~/.aws/config."
        )

    credentials = _resolve_credentials(profile)
    # Frozen so the cache key and the signature see the same credential, even
    # if the underlying provider refreshes between the two.
    frozen = credentials.get_frozen_credentials()
    cache_key = (resolved_region, frozen.access_key)

    if use_cache:
        with _lock:
            cached = _cache.get(cache_key)
            if cached and time.time() < cached[1]:
                return cached[0]

    # Prefer AWS's own generator when it is installed, so the token format stays
    # theirs to define. Any failure falls through to the local implementation.
    token: str | None = None
    try:
        from aws_bedrock_token_generator import provide_token  # type: ignore
        from datetime import timedelta

        token = provide_token(
            region=resolved_region, expiry=timedelta(seconds=expires_in)
        )
    except Exception:  # noqa: BLE001 — optional dependency, optional success
        token = None

    if not token:
        token = _sign(frozen, resolved_region, expires_in)

    if use_cache:
        with _lock:
            _cache[cache_key] = (token, time.time() + expires_in * _REFRESH_AT)
    return token


def bedrock_bearer_token(
    *,
    region: str | None = None,
    profile: str | None = None,
    required: bool = False,
) -> str | None:
    """Return an existing bearer token, or derive one from AWS credentials.

    This is the entry point adapters should call: an explicitly configured key
    always wins, and only when none is present do we sign one.

    Args:
        region: AWS region for signing.
        profile: Named AWS profile.
        required: Raise instead of returning ``None`` when nothing can be
            resolved.

    Returns:
        A bearer token, or ``None`` when none is available and ``required`` is
        ``False``.
    """
    existing = existing_bearer_token()
    if existing:
        return existing
    try:
        return generate_bearer_token(region=region, profile=profile)
    except BedrockTokenError:
        if required:
            raise
        return None


def export_bearer_token(
    *, region: str | None = None, profile: str | None = None
) -> str:
    """Derive a token and publish it as ``AWS_BEARER_TOKEN_BEDROCK``.

    Useful when a downstream library reads the environment variable directly
    rather than accepting an explicit key.
    """
    token = bedrock_bearer_token(region=region, profile=profile, required=True)
    assert token is not None  # `required=True` guarantees it
    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = token
    return token
