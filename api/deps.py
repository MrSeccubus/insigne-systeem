from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

import jwt
from insigne.auth import decode_access_token
from insigne.models import User

from insigne.database import get_db

bearer_scheme = HTTPBearer()
bearer_scheme_optional = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    try:
        user_id = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user = db.get(User, user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


def get_current_user_or_none(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme_optional),
    db: Session = Depends(get_db),
) -> User | None:
    if credentials is None:
        return None
    try:
        user_id = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        return None
    user = db.get(User, user_id)
    if user is None or user.status != "active":
        return None
    return user
