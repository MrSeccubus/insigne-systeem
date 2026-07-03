"""Per-IP rate limiting for the unauthenticated, e-mail-sending endpoints.

`/register`, `/forgot-password` and `/contact` each fire an e-mail per request
with no login required. Without a throttle they can be abused to bomb a
victim's inbox (or the admins') and hammer the SMTP relay. This module wires up
a single slowapi ``Limiter`` and exposes ready-made decorators for those
routes; limits and the on/off switch come from ``config.rate_limit``.

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
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from insigne.config import config

limiter = Limiter(key_func=get_remote_address)


def _disabled(*args) -> bool:
    return not config.rate_limit.enabled


# Ready-made decorators. The limit-provider is a zero-arg callable so slowapi
# re-reads config on every request (dynamic limit); exempt_when short-circuits
# the whole check when rate limiting is switched off.
register_rate_limit = limiter.limit(lambda: config.rate_limit.register, exempt_when=_disabled)
forgot_password_rate_limit = limiter.limit(lambda: config.rate_limit.forgot_password, exempt_when=_disabled)
contact_rate_limit = limiter.limit(lambda: config.rate_limit.contact, exempt_when=_disabled)
