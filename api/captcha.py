"""ALTCHA proof-of-work captcha for the unauthenticated form endpoints.

Self-hosted and privacy-friendly: no cookies, no fingerprinting, no third-party
calls. The browser widget (frontend/static/vendor/altcha.min.js) fetches a
challenge from ``GET /altcha/challenge``, solves a proof-of-work, and submits
the solution in a hidden ``altcha`` form field; the server re-verifies it with
the same HMAC key.

We use the ALTCHA **v1** protocol to match the vendored widget (altcha@1.5.1).
The signing key is derived from ``jwt_secret_key`` (independent from JWT signing
via a distinct HMAC label), so no extra secret to configure.

Replay: a valid solution is accepted once. ALTCHA payloads embed the unique
challenge salt; we remember spent salts until they expire (short window) so a
captured payload can't be reused within its validity — otherwise a single solve
could be replayed to send many messages. In-memory store, which is correct for
the single-worker production model (see run_prod.sh ``--workers 1``).
"""
import base64
import binascii
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

from altcha import create_challenge_v1, verify_solution_v1
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from insigne.config import config

router = APIRouter()

_CHALLENGE_TTL_SECONDS = 600  # 10-minute validity window
_HMAC_LABEL = b"altcha-captcha-secret"

# challenge-salt -> expiry epoch seconds, for single-use enforcement.
_spent_salts: dict[str, float] = {}


def is_enabled() -> bool:
    return config.captcha.enabled


def _hmac_key() -> bytes:
    """Captcha-signing key derived from the JWT secret via a distinct label, so
    the two keys are independent (a leak of one does not expose the other)."""
    return hmac.new(config.jwt_secret_key.encode(), _HMAC_LABEL, hashlib.sha256).digest()


def _prune(now: float) -> None:
    for salt, exp in list(_spent_salts.items()):
        if exp <= now:
            del _spent_salts[salt]


def reset() -> None:
    """Clear the single-use store. For tests."""
    _spent_salts.clear()


def create_challenge_dict() -> dict:
    """Build a fresh ALTCHA v1 challenge for the widget to solve."""
    challenge = create_challenge_v1(
        algorithm="SHA-256",
        max_number=config.captcha.complexity,
        hmac_key=_hmac_key(),
        expires=datetime.now(timezone.utc) + timedelta(seconds=_CHALLENGE_TTL_SECONDS),
    )
    d = challenge.to_dict()
    # altcha@1.5.1 reads ``maxnumber``; the Python lib emits ``maxNumber``.
    # Provide both so the widget works regardless of which key it looks for.
    d.setdefault("maxnumber", d.get("maxNumber"))
    return d


def _payload_salt(payload: str) -> str | None:
    """Extract the challenge salt from a base64 ALTCHA payload (for replay
    tracking). Returns None if the payload isn't decodable."""
    try:
        data = json.loads(base64.b64decode(payload).decode())
        salt = data.get("salt")
        return salt if isinstance(salt, str) else None
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None


def verify(payload: str) -> bool:
    """Return True if ``payload`` is a valid, unexpired, not-yet-spent ALTCHA
    solution. Consumes the solution (single-use) on success."""
    if not payload:
        return False
    ok, _ = verify_solution_v1(payload, _hmac_key(), check_expires=True)
    if not ok:
        return False

    now = time.time()
    _prune(now)
    salt = _payload_salt(payload)
    if salt is None:
        # Verified but unparseable salt: accept once but we can't dedupe it.
        return True
    if salt in _spent_salts:
        return False  # replay
    _spent_salts[salt] = now + _CHALLENGE_TTL_SECONDS
    return True


@router.get("/altcha/challenge")
async def altcha_challenge():
    """Issue a signed PoW challenge for the ALTCHA widget. Public GET, no auth;
    the signature (not secrecy) is what makes a forged solution unacceptable."""
    return JSONResponse(create_challenge_dict())
