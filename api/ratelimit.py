"""Rate limiting for the e-mail-sending endpoints.

`/register`, `/forgot-password` and `/contact` each fire an e-mail per request
with no login required. Without a throttle they can be abused to bomb a
victim's inbox (or the admins') and hammer the SMTP relay. This module wires up
a single slowapi ``Limiter`` and exposes ready-made decorators for those
routes; limits and the on/off switch come from ``config.rate_limit``.

The by-email sign-off request endpoints are authenticated but let a scout
mail an *arbitrary* address from our domain (and mint a placeholder ``User``
row per unknown address). Those get ``signoff_rate_limit``, keyed per user
(JWT ``sub`` from the ``access_token`` cookie) rather than per IP, so a
household/venue NAT never shares one bucket and an abuser can't reset theirs
by hopping IPs. Unauthenticated hits fall back to IP keying; the handler
rejects them anyway.

Keying is by client IP via ``get_remote_address`` (reads
``request.client.host``). That is only the *real* client IP when uvicorn runs
behind a trusted proxy with ``server.forwarded_allow_ips`` set — uvicorn then
rewrites ``request.client.host`` from ``X-Forwarded-For`` before the app sees
it. We deliberately do NOT parse ``X-Forwarded-For`` ourselves: that would let
any client spoof the header and evade the limit when not behind a trusted
proxy. Same trust model as the fail2ban login log.

The limit strings and ``enabled`` flag are read at *request* time (via the
callable limit-provider and ``exempt_when``), so tests can flip
``config.rate_limit`` without rebuilding the app.

The limiter uses slowapi's default in-memory (``memory://``) storage, so the
counters live in *this process*. This is correct only under ``--workers 1``
(see run_prod.sh); with more workers each limit is multiplied by the worker
count. Move to a shared ``storage_uri`` (e.g. Redis) before scaling out.
"""
import jwt
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from insigne.auth import decode_access_token
from insigne.config import config

limiter = Limiter(key_func=get_remote_address)


def _disabled(*args) -> bool:
    return not config.rate_limit.enabled


def _user_or_ip(request: Request) -> str:
    """Key on the authenticated user id, falling back to the client IP.

    Decodes the JWT directly (no DB hit — the limiter runs before the
    handler); an invalid/absent token keys on IP, and the handler's own auth
    check then rejects the request.
    """
    token = request.cookies.get("access_token")
    if token:
        try:
            return f"user:{decode_access_token(token)}"
        except jwt.PyJWTError:
            pass
    return get_remote_address(request)


# Ready-made decorators. The limit-provider is a zero-arg callable so slowapi
# re-reads config on every request (dynamic limit); exempt_when short-circuits
# the whole check when rate limiting is switched off.
register_rate_limit = limiter.limit(lambda: config.rate_limit.register, exempt_when=_disabled)
forgot_password_rate_limit = limiter.limit(lambda: config.rate_limit.forgot_password, exempt_when=_disabled)
contact_rate_limit = limiter.limit(lambda: config.rate_limit.contact, exempt_when=_disabled)
signoff_rate_limit = limiter.limit(
    lambda: config.rate_limit.signoff, key_func=_user_or_ip, exempt_when=_disabled
)
