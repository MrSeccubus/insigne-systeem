import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .auth import hash_password, verify_password
from .models import ConfirmationToken, User

_TOKEN_EXPIRE_HOURS = 1


def _local_part(email: str) -> str:
    return email.split("@")[0]


def _make_token(db: Session, user_id: str, token_type: str) -> str:
    value = secrets.token_urlsafe(32)
    db.add(ConfirmationToken(
        user_id=user_id,
        token=value,
        type=token_type,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=_TOKEN_EXPIRE_HOURS),
    ))
    return value


def start_registration(db: Session, email: str) -> tuple[str, str, User]:
    """Create or find a user and issue a confirmation token.

    - New / pending user: issues an email_confirmation token.
    - Already active user: issues a password_reset token so they can regain
      access without revealing whether the address is registered.
    Returns (code, token_type, user).
    """
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(email=email)
        db.add(user)
        db.flush()

    if user.status == "active":
        db.query(ConfirmationToken).filter(
            ConfirmationToken.user_id == user.id,
            ConfirmationToken.type == "password_reset",
            ConfirmationToken.used_at.is_(None),
        ).update({"used_at": datetime.now(timezone.utc)})
        code = _make_token(db, user.id, "password_reset")
        db.commit()
        return code, "password_reset", user

    db.query(ConfirmationToken).filter(
        ConfirmationToken.user_id == user.id,
        ConfirmationToken.type == "email_confirmation",
        ConfirmationToken.used_at.is_(None),
    ).update({"used_at": datetime.now(timezone.utc)})
    code = _make_token(db, user.id, "email_confirmation")
    db.commit()
    return code, "email_confirmation", user


def confirm_email(db: Session, code: str) -> str | None:
    """Validate a confirmation or password-reset code and return a setup token, or None."""
    now = datetime.now(timezone.utc)
    token = (
        db.query(ConfirmationToken)
        .filter(
            ConfirmationToken.token == code.strip(),
            ConfirmationToken.type.in_(["email_confirmation", "password_reset"]),
            ConfirmationToken.used_at.is_(None),
            ConfirmationToken.expires_at > now,
        )
        .first()
    )
    if token is None:
        return None

    token.used_at = now
    setup_token = _make_token(db, token.user_id, "setup")
    db.commit()
    return setup_token


class ActivationError(Exception):
    pass


def activate_account(db: Session, setup_token: str, password: str, name: str = "") -> tuple[User, bool]:
    """Complete account setup. Returns (user, is_new_account).

    is_new_account is True when this is the first activation (registration),
    False when it is a password reset for an existing active account.
    Raises ActivationError("expired") or ActivationError("password_too_short").
    """
    now = datetime.now(timezone.utc)
    token = (
        db.query(ConfirmationToken)
        .filter(
            ConfirmationToken.token == setup_token,
            ConfirmationToken.type == "setup",
            ConfirmationToken.used_at.is_(None),
            ConfirmationToken.expires_at > now,
        )
        .first()
    )
    if token is None:
        raise ActivationError("expired")

    if len(password) < 8:
        raise ActivationError("password_too_short")

    user = db.get(User, token.user_id)
    is_new = user.status == "pending"
    user.name = name.strip() or _local_part(user.email)
    user.password_hash = hash_password(password)
    user.status = "active"
    token.used_at = now
    db.commit()
    return user, is_new


def authenticate(db: Session, email: str, password: str) -> User | None:
    """Return the active User if credentials are valid, else None."""
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email, User.status == "active").first()
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user


def forgot_password(db: Session, email: str) -> str | None:
    """Issue a password_reset token for an active account.

    Returns the token value to send by email, or None if no active account
    exists. Callers should always respond 202 regardless.
    """
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email, User.status == "active").first()
    if user is None:
        return None

    db.query(ConfirmationToken).filter(
        ConfirmationToken.user_id == user.id,
        ConfirmationToken.type == "password_reset",
        ConfirmationToken.used_at.is_(None),
    ).update({"used_at": datetime.now(timezone.utc)})

    code = _make_token(db, user.id, "password_reset")
    db.commit()
    return code


def update_user(
    db: Session,
    user: User,
    *,
    name: str | None = None,
    email: str | None = None,
    password: str | None = None,
) -> User:
    """Update mutable profile fields. Raises ValueError('password_too_short') if needed."""
    if name is not None:
        user.name = name.strip()
    if email is not None:
        user.email = email.strip().lower()
    if password is not None:
        if len(password) < 8:
            raise ValueError("password_too_short")
        user.password_hash = hash_password(password)
    db.commit()
    return user


def delete_user(db: Session, user: User) -> None:
    db.delete(user)
    db.commit()
