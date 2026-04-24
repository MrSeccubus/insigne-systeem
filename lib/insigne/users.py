import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .auth import hash_password, verify_password
from .models import ConfirmationToken, EmailChangeRequest, GroupMembership, SpeltakMembership, User

_TOKEN_EXPIRE_HOURS = 1
_EMAIL_CHANGE_CONFIRM_HOURS = 24
_EMAIL_CHANGE_REVERT_DAYS = 7


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
    if name.strip():
        user.name = name.strip()
    elif is_new:
        user.name = _local_part(user.email)
    user.password_hash = hash_password(password)
    user.status = "active"
    token.used_at = now
    # Approve pending (non-withdrawn) memberships created as invitations
    db.query(GroupMembership).filter_by(user_id=user.id, approved=False, withdrawn=False).update({"approved": True})
    db.query(SpeltakMembership).filter_by(user_id=user.id, approved=False, withdrawn=False).update({"approved": True})
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


class EmailChangeError(Exception):
    pass


def request_email_change(db: Session, user: User, new_email: str) -> "EmailChangeRequest":
    """Start an email change flow. Sends confirm link to new address, revert link to old.

    Cancels any existing pending change for this user.
    Raises EmailChangeError('email_taken') if new_email already belongs to another account.
    Raises EmailChangeError('same_email') if new_email == current email.
    """
    new_email = new_email.strip().lower()
    if new_email == (user.email or "").lower():
        raise EmailChangeError("same_email")

    existing = db.query(User).filter(User.email == new_email, User.id != user.id).first()
    if existing is not None:
        raise EmailChangeError("email_taken")

    now = datetime.now(timezone.utc)
    db.query(EmailChangeRequest).filter(
        EmailChangeRequest.user_id == user.id,
        EmailChangeRequest.confirmed_at.is_(None),
        EmailChangeRequest.reverted_at.is_(None),
    ).update({"reverted_at": now})

    req = EmailChangeRequest(
        user_id=user.id,
        old_email=user.email or "",
        new_email=new_email,
        confirm_token=secrets.token_urlsafe(32),
        revert_token=secrets.token_urlsafe(32),
        expires_at=now + timedelta(hours=_EMAIL_CHANGE_CONFIRM_HOURS),
        revert_expires_at=now + timedelta(days=_EMAIL_CHANGE_REVERT_DAYS),
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


def confirm_email_change(db: Session, token: str) -> "EmailChangeRequest | None":
    """Apply the email change. Returns the request or None if token invalid/expired."""
    now = datetime.now(timezone.utc)
    req = db.query(EmailChangeRequest).filter(
        EmailChangeRequest.confirm_token == token,
        EmailChangeRequest.confirmed_at.is_(None),
        EmailChangeRequest.reverted_at.is_(None),
        EmailChangeRequest.expires_at > now,
    ).first()
    if req is None:
        return None

    existing = db.query(User).filter(User.email == req.new_email, User.id != req.user_id).first()
    if existing is not None:
        return None

    user = db.get(User, req.user_id)
    user.email = req.new_email
    req.confirmed_at = now
    db.commit()
    db.refresh(req)
    return req


def revert_email_change(db: Session, token: str) -> "EmailChangeRequest | None":
    """Revert the email change back to the old address. Returns the request or None."""
    now = datetime.now(timezone.utc)
    req = db.query(EmailChangeRequest).filter(
        EmailChangeRequest.revert_token == token,
        EmailChangeRequest.reverted_at.is_(None),
        EmailChangeRequest.revert_expires_at > now,
    ).first()
    if req is None:
        return None

    user = db.get(User, req.user_id)
    user.email = req.old_email
    req.reverted_at = now
    db.commit()
    db.refresh(req)
    return req


def get_revert_request(db: Session, token: str) -> "EmailChangeRequest | None":
    """Return the EmailChangeRequest for a valid (unexpired, unreverted) revert token."""
    now = datetime.now(timezone.utc)
    return db.query(EmailChangeRequest).filter(
        EmailChangeRequest.revert_token == token,
        EmailChangeRequest.reverted_at.is_(None),
        EmailChangeRequest.revert_expires_at > now,
    ).first()


def pending_email_change(db: Session, user_id: str) -> "EmailChangeRequest | None":
    """Return the active (unconfirmed, unreverted, unexpired) email change request, if any."""
    now = datetime.now(timezone.utc)
    return db.query(EmailChangeRequest).filter(
        EmailChangeRequest.user_id == user_id,
        EmailChangeRequest.confirmed_at.is_(None),
        EmailChangeRequest.reverted_at.is_(None),
        EmailChangeRequest.expires_at > now,
    ).first()
