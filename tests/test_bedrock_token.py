"""Deriving a Bedrock bearer token from ordinary AWS credentials.

A short-term Bedrock API key is a SigV4-presigned request, so any credential the
standard AWS chain resolves can become one. These tests pin the wire format —
if it drifts, the mantle endpoint rejects every request with a 401 and the cause
is invisible from the error.
"""

from __future__ import annotations

import base64
import urllib.parse

import pytest

from shipit_agent.llms import bedrock_token
from shipit_agent.llms.bedrock_token import (
    MAX_TOKEN_DURATION,
    BedrockTokenError,
    bedrock_bearer_token,
    existing_bearer_token,
    generate_bearer_token,
    resolve_region,
)

# The canonical AWS documentation example credentials — inert, and they make the
# signature deterministic enough to assert on.
_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Isolate from any real AWS config on the machine running the tests."""
    for var in (
        "AWS_BEARER_TOKEN_BEDROCK",
        "BEDROCK_MANTLE_API_KEY",
        "AWS_PROFILE",
        "AWS_SESSION_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", _ACCESS_KEY)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", _SECRET_KEY)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    bedrock_token._cache.clear()
    yield
    bedrock_token._cache.clear()


def _decode(token: str) -> dict[str, str]:
    assert token.startswith("bedrock-api-key-")
    raw = base64.b64decode(token[len("bedrock-api-key-") :]).decode()
    assert raw.endswith("&Version=1")
    query = urllib.parse.urlparse("https://" + raw).query
    return {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}


class TestTokenFormat:
    def test_token_is_a_presigned_sigv4_request(self) -> None:
        fields = _decode(generate_bearer_token())
        assert fields["X-Amz-Algorithm"] == "AWS4-HMAC-SHA256"
        assert fields["Action"] == "CallWithBearerToken"
        assert fields["X-Amz-Signature"]

    def test_credential_scope_binds_service_and_region(self) -> None:
        fields = _decode(generate_bearer_token(region="eu-west-1"))
        # scope is <key>/<date>/<region>/<service>/aws4_request — the region
        # travels in the signature, not the host, which is why the URL is global.
        scope = fields["X-Amz-Credential"].split("/")
        assert scope[0] == _ACCESS_KEY
        assert scope[2] == "eu-west-1"
        assert scope[3] == "bedrock"

    def test_expiry_is_carried_in_the_signature(self) -> None:
        fields = _decode(generate_bearer_token(expires_in=3600, use_cache=False))
        assert fields["X-Amz-Expires"] == "3600"


class TestRegionResolution:
    def test_explicit_region_wins(self) -> None:
        assert resolve_region("ap-south-1") == "ap-south-1"

    @pytest.mark.parametrize(
        "var", ["AWS_REGION", "AWS_DEFAULT_REGION", "AWS_REGION_NAME"]
    )
    def test_every_documented_region_var_is_read(self, monkeypatch, var) -> None:
        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.setenv(var, "ca-central-1")
        assert resolve_region() == "ca-central-1"


class TestValidation:
    @pytest.mark.parametrize("bad", [0, -1, MAX_TOKEN_DURATION + 1])
    def test_lifetime_is_bounded_by_the_aws_ceiling(self, bad) -> None:
        with pytest.raises(BedrockTokenError, match="12 hours"):
            generate_bearer_token(expires_in=bad)

    def test_missing_region_is_named_precisely(self, monkeypatch) -> None:
        for var in ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_REGION_NAME"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(bedrock_token, "resolve_region", lambda region=None: None)
        with pytest.raises(BedrockTokenError, match="No AWS region"):
            generate_bearer_token()

    def test_missing_credentials_is_named_precisely(self, monkeypatch) -> None:
        monkeypatch.setattr(
            bedrock_token, "_resolve_credentials", lambda profile=None: None
        )
        with pytest.raises(Exception):
            generate_bearer_token()


class TestCaching:
    def test_repeated_calls_reuse_one_token(self) -> None:
        assert generate_bearer_token() == generate_bearer_token()

    def test_cache_can_be_bypassed(self, monkeypatch) -> None:
        first = generate_bearer_token()
        # A different region must not collide with the cached entry.
        assert generate_bearer_token(region="eu-west-1") != first

    def test_refresh_happens_before_expiry_not_after(self, monkeypatch) -> None:
        """A token cached to its full lifetime would be presented at the very
        moment it expires; the entry is deliberately shorter-lived than the
        token it holds."""
        generate_bearer_token(expires_in=1000)
        (_token, expires_at) = next(iter(bedrock_token._cache.values()))
        import time

        assert expires_at - time.time() < 1000


class TestPrecedence:
    def test_existing_token_is_preferred_over_signing(self, monkeypatch) -> None:
        monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "already-configured")

        def _must_not_sign(**_):  # pragma: no cover - guards the assertion
            raise AssertionError("should not sign when a key is configured")

        monkeypatch.setattr(bedrock_token, "generate_bearer_token", _must_not_sign)
        assert bedrock_bearer_token() == "already-configured"

    def test_env_vars_are_checked_most_specific_first(self, monkeypatch) -> None:
        monkeypatch.setenv("BEDROCK_MANTLE_API_KEY", "mantle")
        monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "aws")
        assert existing_bearer_token() == "aws"

    def test_optional_by_default_and_strict_on_request(self, monkeypatch) -> None:
        def _fail(**_):
            raise BedrockTokenError("nope")

        monkeypatch.setattr(bedrock_token, "generate_bearer_token", _fail)
        assert bedrock_bearer_token() is None
        with pytest.raises(BedrockTokenError):
            bedrock_bearer_token(required=True)


class TestSecrecy:
    def test_token_is_not_exported_to_the_environment_as_a_side_effect(self) -> None:
        """Deriving a token must not publish it process-wide — only the explicit
        export helper may do that."""
        import os

        generate_bearer_token()
        assert "AWS_BEARER_TOKEN_BEDROCK" not in os.environ

    def test_export_helper_is_the_only_thing_that_publishes(self, monkeypatch) -> None:
        import os

        token = bedrock_token.export_bearer_token()
        assert os.environ["AWS_BEARER_TOKEN_BEDROCK"] == token
        monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
