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


def create_access_token(user_id: str) -> tuple[str, datetime]:
    expires_at = datetime.now(timezone.utc) + timedelta(days=_EXPIRE_DAYS)
    token = jwt.encode({"sub": user_id, "exp": expires_at}, config.jwt_secret_key, algorithm=_ALGORITHM)
    return token, expires_at


def decode_access_token(token: str) -> str:
    payload = jwt.decode(token, config.jwt_secret_key, algorithms=[_ALGORITHM])
    return payload["sub"]
