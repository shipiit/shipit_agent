"""Everything specific to the ``bedrock-mantle`` endpoint.

Mantle is the OpenAI-compatible surface for Bedrock's next-generation inference
engine, and it is how Gemma 4 is served. Three of its properties are easy to get
wrong in ways that produce unhelpful errors:

**It is regional, with a short list.** Calling from an unsupported region fails
at connect time with a DNS or 404 error that says nothing about regions. This
module checks first and names the supported ones.

**It authenticates with a bearer token, not SigV4.** A short-term Bedrock API
key *is* a presigned SigV4 request, so ordinary AWS credentials are sufficient
to derive one — but the derived key expires after at most 12 hours. An agent
process that outlives that (a scheduler daemon, a long research run) starts
401ing halfway through. :class:`RefreshingBearerToken` re-derives before expiry
and on demand after an auth failure.

**Its permissions are their own action namespace.** A 403 mentions
``bedrock-mantle:CreateInference``, which does not appear in any Bedrock policy
a user is likely to already have attached. The diagnostic here names the managed
policy that fixes it.

The token generator is injected, so this module has no hard dependency on any
particular AWS SDK and is fully testable without credentials.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)

__all__ = [
    "MANTLE_REGIONS",
    "MANTLE_URL_TEMPLATE",
    "MantleRegionError",
    "MantleAuthError",
    "RefreshingBearerToken",
    "mantle_base_url",
    "check_region",
    "iam_hint",
]

#: Regions where Gemma 4 is served at launch. Overridable from config — a new
#: region must not require a release.
MANTLE_REGIONS: frozenset[str] = frozenset(
    {"us-east-1", "us-east-2", "us-west-2", "eu-central-1"}
)

MANTLE_URL_TEMPLATE = "https://bedrock-mantle.{region}.api.aws/openai/v1"

#: Maximum lifetime of a short-term Bedrock API key.
MAX_TOKEN_TTL_SECONDS = 12 * 60 * 60

#: Refresh at this fraction of the lifetime, so a call in flight when the
#: threshold is crossed still holds a valid token.
DEFAULT_REFRESH_AT = 0.8

_MANAGED_POLICY = "AmazonBedrockMantleInferenceAccess"
_REQUIRED_ACTIONS = (
    "bedrock-mantle:CreateInference",
    "bedrock-mantle:CallWithBearerToken",
)


class MantleRegionError(RuntimeError):
    """The configured region does not serve the Mantle endpoint."""


class MantleAuthError(RuntimeError):
    """No bearer token could be obtained or derived."""


def _nearest(region: str, allowed: frozenset[str]) -> str:
    """Best-guess alternative: same continent prefix, else the first allowed."""
    prefix = region.split("-", 1)[0] if "-" in region else region
    same = sorted(r for r in allowed if r.startswith(prefix))
    return same[0] if same else sorted(allowed)[0]


def check_region(region: str | None, *, allowed: frozenset[str] | None = None) -> str:
    """Validate *region* against the Mantle region list.

    Raises before the first network call rather than letting an unsupported
    region surface as an opaque connection failure.
    """
    allowed = allowed or MANTLE_REGIONS
    normalized = (region or "").strip().lower()
    if not normalized:
        raise MantleRegionError(
            "No AWS region configured for the bedrock-mantle endpoint. "
            f"Set one of: {', '.join(sorted(allowed))}."
        )
    if normalized not in allowed:
        raise MantleRegionError(
            f"Region {normalized!r} does not serve the bedrock-mantle endpoint. "
            f"Supported: {', '.join(sorted(allowed))}. "
            f"Nearest alternative: {_nearest(normalized, allowed)}."
        )
    return normalized


def mantle_base_url(
    region: str | None,
    *,
    allowed: frozenset[str] | None = None,
    template: str = MANTLE_URL_TEMPLATE,
) -> str:
    """The OpenAI-compatible base URL for *region*, region-checked first."""
    return template.format(region=check_region(region, allowed=allowed))


def iam_hint(status: int | None = None) -> str:
    """A 403 that actually says what to attach."""
    actions = "\n".join(f"    - {action}" for action in _REQUIRED_ACTIONS)
    return (
        f"The bedrock-mantle endpoint returned {status or 403}. It uses its own "
        f"IAM action namespace, so a Bedrock policy is not enough.\n"
        f"  Attach the managed policy {_MANAGED_POLICY} to the calling "
        f"principal, or grant:\n{actions}\n"
        f"  Bearer-token calls additionally require "
        f"bedrock-mantle:CallWithBearerToken."
    )


@dataclass(slots=True)
class _TokenState:
    value: str | None = None
    expires_at: float = 0.0


class RefreshingBearerToken:
    """A Bedrock API key that re-derives itself before it expires.

    Constructed with a *generator* — anything that returns a token string for a
    region — so this class needs no AWS SDK and tests need no credentials.

    Thread-safe: several tool threads may call :meth:`get` concurrently and
    exactly one derivation happens. :meth:`force_refresh` exists for the 401
    path, where the token may have been revoked before its nominal expiry.
    """

    __slots__ = ("_generate", "_region", "_ttl", "_refresh_at", "_lock", "_state", "_clock")

    def __init__(
        self,
        generate: Callable[..., str],
        *,
        region: str | None = None,
        ttl_seconds: int = MAX_TOKEN_TTL_SECONDS,
        refresh_at: float = DEFAULT_REFRESH_AT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0.0 < refresh_at <= 1.0:
            raise ValueError("refresh_at must be in (0, 1]")
        self._generate = generate
        self._region = region
        self._ttl = min(int(ttl_seconds), MAX_TOKEN_TTL_SECONDS)
        self._refresh_at = refresh_at
        self._lock = threading.Lock()
        self._state = _TokenState()
        self._clock = clock

    # -- internals ---------------------------------------------------------

    def _derive(self) -> str:
        try:
            token = self._generate(region=self._region) if self._region else self._generate()
        except TypeError:
            token = self._generate()
        except Exception as exc:  # noqa: BLE001
            raise MantleAuthError(
                "Could not derive a short-term Bedrock API key. Either export "
                "AWS_BEARER_TOKEN_BEDROCK, or configure ordinary AWS "
                f"credentials plus a supported region. Underlying cause: {exc}"
            ) from exc
        if not token:
            raise MantleAuthError("Token generator returned an empty token.")
        self._state = _TokenState(
            value=str(token),
            expires_at=self._clock() + self._ttl * self._refresh_at,
        )
        logger.debug(
            "Derived bedrock-mantle bearer token; refreshing in %.0fs",
            self._ttl * self._refresh_at,
        )
        return self._state.value  # type: ignore[return-value]

    # -- public ------------------------------------------------------------

    def get(self) -> str:
        """A currently-valid token, deriving or refreshing if needed."""
        with self._lock:
            if self._state.value is None or self._clock() >= self._state.expires_at:
                return self._derive()
            return self._state.value

    def force_refresh(self) -> str:
        """Derive a new token unconditionally — the 401/403 recovery path."""
        with self._lock:
            return self._derive()

    def invalidate(self) -> None:
        """Forget the current token without deriving a replacement."""
        with self._lock:
            self._state = _TokenState()

    @property
    def seconds_remaining(self) -> float:
        """Time until the next scheduled refresh; 0 when none is held."""
        if self._state.value is None:
            return 0.0
        return max(0.0, self._state.expires_at - self._clock())

    def __call__(self) -> str:
        """Usable directly wherever a ``Callable[[], str]`` is expected."""
        return self.get()
