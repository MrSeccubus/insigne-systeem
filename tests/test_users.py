from datetime import datetime, timedelta, timezone

import jwt
import pytest

from insigne import users as user_svc
from insigne.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from insigne.models import ConfirmationToken, User


# ── helpers ─────────────────────────────────────────────────────────────────

def _register_and_activate(db, email="jan@example.com", password="validpass1", name=""):
    """Full registration flow. Returns the activated User."""
    user_svc.start_registration(db, email)
    user = db.query(User).filter_by(email=email).first()
    raw_token = db.query(ConfirmationToken).filter_by(user_id=user.id, type="email_confirmation").first()
    setup = user_svc.confirm_email(db, raw_token.token)
    user_svc.activate_account(db, setup, password, name)
    db.refresh(user)
    return user


# ── password hashing ─────────────────────────────────────────────────────────

class TestPasswordHashing:
    def test_correct_password_verifies(self):
        h = hash_password("mypassword")
        assert verify_password("mypassword", h)

    def test_wrong_password_does_not_verify(self):
        h = hash_password("mypassword")
        assert not verify_password("wrongpassword", h)

    def test_hashes_are_unique_due_to_salt(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2


# ── JWT ───────────────────────────────────────────────────────────────────────

class TestJWT:
    def test_decode_returns_correct_user_id(self):
        token, _ = create_access_token("user-123")
        assert decode_access_token(token) == "user-123"

    def test_expires_at_is_in_future(self):
        _, expires_at = create_access_token("user-123")
        assert expires_at > datetime.now(timezone.utc)

    def test_invalid_token_raises(self):
        with pytest.raises(jwt.PyJWTError):
            decode_access_token("not.a.jwt")

    def test_tampered_token_raises(self):
        token, _ = create_access_token("user-123")
        tampered = token[:-4] + "xxxx"
        with pytest.raises(jwt.PyJWTError):
            decode_access_token(tampered)


# ── start_registration ────────────────────────────────────────────────────────

class TestStartRegistration:
    def test_creates_pending_user(self, db):
        user_svc.start_registration(db, "jan@example.com")
        user = db.query(User).filter_by(email="jan@example.com").first()
        assert user is not None
        assert user.status == "pending"

    def test_returns_confirmation_code(self, db):
        code, _, _ = user_svc.start_registration(db, "jan@example.com")
        assert code is not None

    def test_normalises_email(self, db):
        user_svc.start_registration(db, "  JAN@EXAMPLE.COM  ")
        assert db.query(User).filter_by(email="jan@example.com").first() is not None

    def test_returns_new_code_for_already_pending_user(self, db):
        code1, _, _ = user_svc.start_registration(db, "jan@example.com")
        code2, _, _ = user_svc.start_registration(db, "jan@example.com")
        assert code1 != code2

    def test_invalidates_old_token_on_re_registration(self, db):
        user_svc.start_registration(db, "jan@example.com")
        user = db.query(User).filter_by(email="jan@example.com").first()
        old = db.query(ConfirmationToken).filter_by(user_id=user.id).first()

        user_svc.start_registration(db, "jan@example.com")
        db.refresh(old)
        assert old.used_at is not None

    def test_returns_password_reset_code_for_active_user(self, db):
        _register_and_activate(db)
        code, _, _ = user_svc.start_registration(db, "jan@example.com")
        assert code is not None
        ct = db.query(ConfirmationToken).filter_by(token=code).first()
        assert ct.type == "password_reset"

    def test_password_reset_code_works_in_confirm_flow(self, db):
        _register_and_activate(db)
        code, _, _ = user_svc.start_registration(db, "jan@example.com")
        assert user_svc.confirm_email(db, code) is not None


# ── confirm_email ─────────────────────────────────────────────────────────────

class TestConfirmEmail:
    def _pending_with_token(self, db, token_type="email_confirmation", expired=False, used=False):
        user = User(email="jan@example.com", status="pending")
        db.add(user)
        db.flush()
        expires = (
            datetime.now(timezone.utc) - timedelta(hours=1)
            if expired
            else datetime.now(timezone.utc) + timedelta(hours=1)
        )
        ct = ConfirmationToken(
            user_id=user.id,
            token="testcode123",
            type=token_type,
            expires_at=expires,
            used_at=datetime.now(timezone.utc) if used else None,
        )
        db.add(ct)
        db.commit()
        return user, ct

    def test_valid_code_returns_setup_token(self, db):
        self._pending_with_token(db)
        assert user_svc.confirm_email(db, "testcode123") is not None

    def test_password_reset_code_also_works(self, db):
        self._pending_with_token(db, token_type="password_reset")
        assert user_svc.confirm_email(db, "testcode123") is not None

    def test_marks_confirmation_token_as_used(self, db):
        _, ct = self._pending_with_token(db)
        user_svc.confirm_email(db, "testcode123")
        db.refresh(ct)
        assert ct.used_at is not None

    def test_creates_setup_token_record(self, db):
        user, _ = self._pending_with_token(db)
        user_svc.confirm_email(db, "testcode123")
        setup = db.query(ConfirmationToken).filter_by(user_id=user.id, type="setup").first()
        assert setup is not None

    def test_invalid_code_returns_none(self, db):
        self._pending_with_token(db)
        assert user_svc.confirm_email(db, "wrongcode") is None

    def test_expired_code_returns_none(self, db):
        self._pending_with_token(db, expired=True)
        assert user_svc.confirm_email(db, "testcode123") is None

    def test_already_used_code_returns_none(self, db):
        self._pending_with_token(db, used=True)
        assert user_svc.confirm_email(db, "testcode123") is None

    def test_strips_whitespace_from_code(self, db):
        self._pending_with_token(db)
        assert user_svc.confirm_email(db, "  testcode123  ") is not None


# ── activate_account ──────────────────────────────────────────────────────────

class TestActivateAccount:
    def _setup_token(self, db, email="jan@example.com"):
        user_svc.start_registration(db, email)
        user = db.query(User).filter_by(email=email).first()
        ct = db.query(ConfirmationToken).filter_by(user_id=user.id, type="email_confirmation").first()
        setup = user_svc.confirm_email(db, ct.token)
        return user, setup

    def test_sets_status_to_active(self, db):
        user, setup = self._setup_token(db)
        user_svc.activate_account(db, setup, "validpass1")
        db.refresh(user)
        assert user.status == "active"

    def test_password_is_stored_as_hash(self, db):
        user, setup = self._setup_token(db)
        user_svc.activate_account(db, setup, "validpass1")
        db.refresh(user)
        assert verify_password("validpass1", user.password_hash)

    def test_name_set_when_provided(self, db):
        user, setup = self._setup_token(db)
        user_svc.activate_account(db, setup, "validpass1", name="Jan")
        db.refresh(user)
        assert user.name == "Jan"

    def test_name_defaults_to_email_local_part(self, db):
        user, setup = self._setup_token(db)
        user_svc.activate_account(db, setup, "validpass1")
        db.refresh(user)
        assert user.name == "jan"

    def test_setup_token_marked_as_used(self, db):
        user, setup = self._setup_token(db)
        user_svc.activate_account(db, setup, "validpass1")
        ct = db.query(ConfirmationToken).filter_by(token=setup).first()
        assert ct.used_at is not None

    def test_invalid_token_raises_expired(self, db):
        with pytest.raises(user_svc.ActivationError) as exc:
            user_svc.activate_account(db, "badtoken", "validpass1")
        assert str(exc.value) == "expired"

    def test_expired_token_raises_expired(self, db):
        user_svc.start_registration(db, "jan@example.com")
        user = db.query(User).filter_by(email="jan@example.com").first()
        ct = ConfirmationToken(
            user_id=user.id,
            token="expiredsetup",
            type="setup",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        db.add(ct)
        db.commit()
        with pytest.raises(user_svc.ActivationError) as exc:
            user_svc.activate_account(db, "expiredsetup", "validpass1")
        assert str(exc.value) == "expired"

    def test_short_password_raises(self, db):
        _, setup = self._setup_token(db)
        with pytest.raises(user_svc.ActivationError) as exc:
            user_svc.activate_account(db, setup, "short")
        assert str(exc.value) == "password_too_short"

    def test_setup_token_cannot_be_reused(self, db):
        _, setup = self._setup_token(db)
        user_svc.activate_account(db, setup, "validpass1")
        with pytest.raises(user_svc.ActivationError):
            user_svc.activate_account(db, setup, "anotherpass")


# ── authenticate ──────────────────────────────────────────────────────────────

class TestAuthenticate:
    def test_correct_credentials_return_user(self, db):
        _register_and_activate(db)
        user = user_svc.authenticate(db, "jan@example.com", "validpass1")
        assert user is not None
        assert user.email == "jan@example.com"

    def test_wrong_password_returns_none(self, db):
        _register_and_activate(db)
        assert user_svc.authenticate(db, "jan@example.com", "wrongpassword") is None

    def test_unknown_email_returns_none(self, db):
        assert user_svc.authenticate(db, "nobody@example.com", "anypass") is None

    def test_pending_user_returns_none(self, db):
        user_svc.start_registration(db, "jan@example.com")
        assert user_svc.authenticate(db, "jan@example.com", "anypass") is None

    def test_email_normalised_before_lookup(self, db):
        _register_and_activate(db)
        user = user_svc.authenticate(db, "  JAN@EXAMPLE.COM  ", "validpass1")
        assert user is not None


# ── forgot_password ───────────────────────────────────────────────────────────

class TestForgotPassword:
    def test_returns_code_for_active_user(self, db):
        _register_and_activate(db)
        assert user_svc.forgot_password(db, "jan@example.com") is not None

    def test_returns_none_for_unknown_email(self, db):
        assert user_svc.forgot_password(db, "nobody@example.com") is None

    def test_returns_none_for_pending_user(self, db):
        user_svc.start_registration(db, "jan@example.com")
        assert user_svc.forgot_password(db, "jan@example.com") is None

    def test_invalidates_existing_reset_token(self, db):
        _register_and_activate(db)
        code1 = user_svc.forgot_password(db, "jan@example.com")
        old = db.query(ConfirmationToken).filter_by(token=code1).first()
        user_svc.forgot_password(db, "jan@example.com")
        db.refresh(old)
        assert old.used_at is not None

    def test_reset_code_accepted_by_confirm_email(self, db):
        _register_and_activate(db)
        code = user_svc.forgot_password(db, "jan@example.com")
        assert user_svc.confirm_email(db, code) is not None

    def test_full_password_reset_flow(self, db):
        user = _register_and_activate(db, password="oldpassword")
        code = user_svc.forgot_password(db, "jan@example.com")
        setup = user_svc.confirm_email(db, code)
        user_svc.activate_account(db, setup, "newpassword!")
        db.refresh(user)
        assert verify_password("newpassword!", user.password_hash)
        assert not verify_password("oldpassword", user.password_hash)

    def test_old_password_no_longer_works_after_reset(self, db):
        _register_and_activate(db, password="oldpassword")
        code = user_svc.forgot_password(db, "jan@example.com")
        setup = user_svc.confirm_email(db, code)
        user_svc.activate_account(db, setup, "newpassword!")
        assert user_svc.authenticate(db, "jan@example.com", "oldpassword") is None
        assert user_svc.authenticate(db, "jan@example.com", "newpassword!") is not None


# ── update_user ───────────────────────────────────────────────────────────────

class TestUpdateUser:
    def test_updates_name(self, db):
        user = _register_and_activate(db, name="Oud Naam")
        user_svc.update_user(db, user, name="Nieuw Naam")
        db.refresh(user)
        assert user.name == "Nieuw Naam"

    def test_updates_email(self, db):
        user = _register_and_activate(db)
        user_svc.update_user(db, user, email="nieuw@example.com")
        db.refresh(user)
        assert user.email == "nieuw@example.com"

    def test_updates_password(self, db):
        user = _register_and_activate(db, password="oldpassword1")
        user_svc.update_user(db, user, password="newpassword1")
        db.refresh(user)
        assert verify_password("newpassword1", user.password_hash)

    def test_short_password_raises(self, db):
        user = _register_and_activate(db)
        with pytest.raises(ValueError, match="password_too_short"):
            user_svc.update_user(db, user, password="short")

    def test_none_fields_are_not_updated(self, db):
        user = _register_and_activate(db, name="Jan")
        original_name = user.name
        user_svc.update_user(db, user, email="other@example.com")
        db.refresh(user)
        assert user.name == original_name
