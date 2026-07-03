from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import config

_ALGORITHM = config.jwt_algorithm
_EXPIRE_DAYS = config.jwt_expire_days


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# A valid bcrypt hash of an arbitrary password, computed once at import. Its
# cost factor matches hash_password (both use the library-default gensalt()),
# so verifying against it takes the same ~time as verifying a real user's hash.
_DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"insigne-timing-equalizer", bcrypt.gensalt())


def verify_password_dummy(plain: str) -> None:
    """Spend a bcrypt comparison against a fixed dummy hash and discard the
    result. Call this on the account-not-found login path so its latency
    matches the account-found path — otherwise the fast early return leaks
    whether an e-mail is registered (account-enumeration timing oracle)."""
    bcrypt.checkpw(plain.encode(), _DUMMY_PASSWORD_HASH)


def create_access_token(user_id: str) -> tuple[str, datetime]:
    expires_at = datetime.now(timezone.utc) + timedelta(days=_EXPIRE_DAYS)
    token = jwt.encode({"sub": user_id, "exp": expires_at}, config.jwt_secret_key, algorithm=_ALGORITHM)
    return token, expires_at


def decode_access_token(token: str) -> str:
    payload = jwt.decode(token, config.jwt_secret_key, algorithms=[_ALGORITHM])
    return payload["sub"]
