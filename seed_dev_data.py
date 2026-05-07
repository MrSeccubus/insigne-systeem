#!/usr/bin/env python3
"""
Seed the development database with ~3 months of realistic test data.
Run from the project root:  venv/bin/python seed_dev_data.py

Safe to run multiple times — existing rows (matched by email/slug) are skipped.
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("INSIGNE_CONFIG", str(Path(__file__).parent / "config.yml"))
sys.path.insert(0, str(Path(__file__).parent / "api"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from insigne.auth import hash_password
from insigne.config import config
from insigne.models import (
    Group,
    GroupMembership,
    ProgressEntry,
    SignoffRequest,
    Speltak,
    SpeltakMembership,
    User,
)

engine = create_engine(config.database_url, connect_args={"check_same_thread": False})
db = sessionmaker(bind=engine)()

PW = hash_password("Welkom123")


def ts(y, m, d, h=9, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


# ── helpers ──────────────────────────────────────────────────────────────────

def get_or_create_user(email, name, created_at, *, email_none=False):
    if email_none:
        u = db.query(User).filter_by(name=name, email=None).first()
        if u:
            return u, False
        u = User(email=None, name=name, status="active", password_hash=None)
    else:
        u = db.query(User).filter_by(email=email).first()
        if u:
            return u, False
        u = User(email=email, name=name, status="active", password_hash=PW)
    db.add(u)
    db.flush()
    u.created_at = created_at
    return u, True


def get_or_create_group(name, slug, created_by, created_at):
    g = db.query(Group).filter_by(slug=slug).first()
    if g:
        g.created_at = created_at
        return g, False
    g = Group(name=name, slug=slug, created_by_id=created_by.id)
    db.add(g)
    db.flush()
    g.created_at = created_at
    return g, True


def get_or_create_speltak(group, name, slug, created_at, peer_signoff=False):
    s = db.query(Speltak).filter_by(group_id=group.id, slug=slug).first()
    if s:
        s.created_at = created_at
        return s, False
    s = Speltak(group_id=group.id, name=name, slug=slug, peer_signoff=peer_signoff)
    db.add(s)
    db.flush()
    s.created_at = created_at
    return s, True


def add_group_member(user, group, role, approved, invited_by, created_at):
    existing = db.query(GroupMembership).filter_by(user_id=user.id, group_id=group.id).first()
    if existing:
        return existing
    m = GroupMembership(
        user_id=user.id, group_id=group.id, role=role,
        approved=approved, withdrawn=False, invited_by_id=invited_by.id,
    )
    db.add(m)
    db.flush()
    m.created_at = created_at
    return m


def add_speltak_member(user, speltak, role, approved, invited_by, created_at):
    existing = db.query(SpeltakMembership).filter_by(user_id=user.id, speltak_id=speltak.id).first()
    if existing:
        return existing
    m = SpeltakMembership(
        user_id=user.id, speltak_id=speltak.id, role=role,
        approved=approved, withdrawn=False, invited_by_id=invited_by.id,
    )
    db.add(m)
    db.flush()
    m.created_at = created_at
    return m


def add_progress(user, badge_slug, level_index, step_index, status, created_at,
                 signed_off_by=None, signed_off_at=None, notes=None):
    existing = db.query(ProgressEntry).filter_by(
        user_id=user.id, badge_slug=badge_slug,
        level_index=level_index, step_index=step_index,
    ).first()
    if existing:
        return existing
    e = ProgressEntry(
        user_id=user.id, badge_slug=badge_slug,
        level_index=level_index, step_index=step_index,
        status=status, notes=notes,
        signed_off_by_id=signed_off_by.id if signed_off_by else None,
        signed_off_at=signed_off_at,
    )
    db.add(e)
    db.flush()
    e.created_at = created_at
    return e


def add_signoff_request(entry, mentor, created_at):
    existing = db.query(SignoffRequest).filter_by(
        progress_entry_id=entry.id, mentor_id=mentor.id,
    ).first()
    if existing:
        return existing
    r = SignoffRequest(progress_entry_id=entry.id, mentor_id=mentor.id)
    db.add(r)
    db.flush()
    r.created_at = created_at
    return r


# ── Groups & speltakken ───────────────────────────────────────────────────────

admin = db.query(User).filter_by(email="frank@breedijk.net").first()
if not admin:
    print("Admin user frank@breedijk.net not found — create it first via the app.")
    sys.exit(1)

tbm, _ = get_or_create_group("Scouting TBM", "tbm", admin, ts(2026, 2, 1))

bevers,     _ = get_or_create_speltak(tbm, "Bevers",     "bevers",     ts(2026, 2, 1))
welpen,     _ = get_or_create_speltak(tbm, "Welpen",     "welpen",     ts(2026, 2, 1))
verkenners, _ = get_or_create_speltak(tbm, "Verkenners", "verkenners", ts(2026, 2, 1))
stam,       _ = get_or_create_speltak(tbm, "Stam",       "stam",       ts(2026, 2, 3), peer_signoff=True)

# ── Leaders ───────────────────────────────────────────────────────────────────

leiders = [
    ("bram.vandijk@tbm.nl",    "Bram van Dijk",    ts(2026, 2, 2),  bevers),
    ("lisa.smit@tbm.nl",       "Lisa Smit",        ts(2026, 2, 2),  welpen),
    ("mark.jansen@tbm.nl",     "Mark Jansen",      ts(2026, 2, 3),  verkenners),
    ("femke.bosman@tbm.nl",    "Femke Bosman",     ts(2026, 2, 4),  stam),
]

leider_objs = {}
for email, name, created, speltak in leiders:
    u, _ = get_or_create_user(email, name, created)
    add_group_member(u, tbm, "groepsleider", True, admin, created)
    add_speltak_member(u, speltak, "speltakleider", True, admin, created)
    leider_objs[speltak.slug] = u

# ── Scouts — Bevers ───────────────────────────────────────────────────────────

bevers_scouts_data = [
    ("emma.devries@tbm.nl",  "Emma de Vries",  ts(2026, 2, 10)),
    ("noah.bakker@tbm.nl",   "Noah Bakker",    ts(2026, 2, 12)),
    ("lotte.visser@tbm.nl",  "Lotte Visser",   ts(2026, 2, 15)),
    ("daan.meijer@tbm.nl",   "Daan Meijer",    ts(2026, 2, 20)),
    (None,                   "Pieter Zondag",  ts(2026, 2, 22)),  # emailless scout
]

bevers_scouts = []
for email, name, created in bevers_scouts_data:
    u, _ = get_or_create_user(email, name, created, email_none=(email is None))
    add_group_member(u, tbm, "member", True, leider_objs["bevers"], created)
    add_speltak_member(u, bevers, "scout", True, leider_objs["bevers"], created)
    bevers_scouts.append(u)

# ── Scouts — Welpen ───────────────────────────────────────────────────────────

welpen_scouts_data = [
    ("sophie.janssen@tbm.nl",    "Sophie Janssen",    ts(2026, 2, 14)),
    ("luuk.peters@tbm.nl",       "Luuk Peters",       ts(2026, 2, 18)),
    ("julia.vandenberg@tbm.nl",  "Julia van den Berg",ts(2026, 2, 22)),
    ("tim.mulder@tbm.nl",        "Tim Mulder",        ts(2026, 3, 1)),
    ("eva.bos@tbm.nl",           "Eva Bos",           ts(2026, 3, 5)),
    (None,                       "Bas Timmerman",     ts(2026, 3, 7)),   # emailless scout
]

welpen_scouts = []
for email, name, created in welpen_scouts_data:
    u, _ = get_or_create_user(email, name, created, email_none=(email is None))
    add_group_member(u, tbm, "member", True, leider_objs["welpen"], created)
    add_speltak_member(u, welpen, "scout", True, leider_objs["welpen"], created)
    welpen_scouts.append(u)

# ── Scouts — Verkenners ───────────────────────────────────────────────────────

verkenners_scouts_data = [
    ("lars.boer@tbm.nl",       "Lars Boer",       ts(2026, 2, 20)),
    ("anna.dejong@tbm.nl",     "Anna de Jong",    ts(2026, 2, 25)),
    ("finn.vermeer@tbm.nl",    "Finn Vermeer",    ts(2026, 3, 3)),
    ("noor.hendriks@tbm.nl",   "Noor Hendriks",   ts(2026, 3, 10)),
    ("sam.dekker@tbm.nl",      "Sam Dekker",      ts(2026, 3, 15)),
]

verkenners_scouts = []
for email, name, created in verkenners_scouts_data:
    u, _ = get_or_create_user(email, name, created)
    add_group_member(u, tbm, "member", True, leider_objs["verkenners"], created)
    add_speltak_member(u, verkenners, "scout", True, leider_objs["verkenners"], created)
    verkenners_scouts.append(u)

# ── Scouts — Stam (peer sign-off) ─────────────────────────────────────────────

stam_scouts_data = [
    ("robin.devos@tbm.nl",   "Robin de Vos",   ts(2026, 2, 5)),
    ("iris.kok@tbm.nl",      "Iris Kok",       ts(2026, 2, 5)),
    ("joris.wolf@tbm.nl",    "Joris Wolf",     ts(2026, 2, 8)),
    ("maya.brand@tbm.nl",    "Maya Brand",     ts(2026, 2, 10)),
]

stam_scouts = []
for email, name, created in stam_scouts_data:
    u, _ = get_or_create_user(email, name, created)
    add_group_member(u, tbm, "member", True, leider_objs["stam"], created)
    add_speltak_member(u, stam, "scout", True, leider_objs["stam"], created)
    stam_scouts.append(u)

# ── Invited but not yet activated ─────────────────────────────────────────────

for email, name, created in [
    ("max.pending@tbm.nl",   "Max (uitgenodigd)",   ts(2026, 4, 20)),
    ("floor.pending@tbm.nl", "Floor (uitgenodigd)", ts(2026, 4, 28)),
]:
    existing = db.query(User).filter_by(email=email).first()
    if not existing:
        u = User(email=email, name=name, status="pending", password_hash=None)
        db.add(u)
        db.flush()
        u.created_at = created

# ── Progress — Bevers (sport_spel + koken) ────────────────────────────────────

bl = leider_objs["bevers"]

# Emma — completed sport_spel niveau 1 in March, niveau 2 in progress
e = bevers_scouts[0]
for li in range(5):
    p = add_progress(e, "sport_spel", li, 0, "signed_off", ts(2026, 2, 15),
                     signed_off_by=bl, signed_off_at=ts(2026, 3, 10))
for li in range(3):
    add_progress(e, "sport_spel", li, 1, "work_done", ts(2026, 3, 12))
for li in range(2):
    add_progress(e, "sport_spel", li, 2, "in_progress", ts(2026, 4, 1))
for li in range(5):
    p = add_progress(e, "koken", li, 0, "signed_off", ts(2026, 3, 5),
                     signed_off_by=bl, signed_off_at=ts(2026, 3, 28))

# Noah — sport_spel niveau 1 in progress
n = bevers_scouts[1]
for li in range(4):
    add_progress(n, "sport_spel", li, 0, "in_progress", ts(2026, 2, 20))
for li in range(2):
    add_progress(n, "koken", li, 0, "work_done", ts(2026, 3, 1))

# Lotte — pending signoff
lo = bevers_scouts[2]
for li in range(5):
    p = add_progress(lo, "sport_spel", li, 0, "pending_signoff", ts(2026, 3, 15))
    add_signoff_request(p, bl, ts(2026, 4, 10))
for li in range(5):
    add_progress(lo, "koken", li, 0, "signed_off", ts(2026, 2, 25),
                 signed_off_by=bl, signed_off_at=ts(2026, 3, 20))

# Daan — just started
d = bevers_scouts[3]
for li in range(2):
    add_progress(d, "sport_spel", li, 0, "in_progress", ts(2026, 3, 1))

# ── Progress — Welpen (kamperen + pionieren + vuur_stoken) ───────────────────

wl = leider_objs["welpen"]

# Sophie — kamperen niveau 1 + 2 signed off
s = welpen_scouts[0]
for li in range(5):
    add_progress(s, "kamperen", li, 0, "signed_off", ts(2026, 2, 20),
                 signed_off_by=wl, signed_off_at=ts(2026, 3, 15))
for li in range(5):
    add_progress(s, "kamperen", li, 1, "signed_off", ts(2026, 3, 18),
                 signed_off_by=wl, signed_off_at=ts(2026, 4, 12))
for li in range(3):
    add_progress(s, "kamperen", li, 2, "work_done", ts(2026, 4, 15))

# Luuk — pionieren niveau 1 done, signoff requested
lu = welpen_scouts[1]
for li in range(5):
    p = add_progress(lu, "pionieren", li, 0, "pending_signoff", ts(2026, 3, 10))
    add_signoff_request(p, wl, ts(2026, 4, 20))

# Julia — vuur_stoken in various stages
ju = welpen_scouts[2]
for li in range(5):
    add_progress(ju, "vuur_stoken", li, 0, "signed_off", ts(2026, 3, 5),
                 signed_off_by=wl, signed_off_at=ts(2026, 3, 25))
for li in range(2):
    add_progress(ju, "vuur_stoken", li, 1, "in_progress", ts(2026, 4, 1))

# Tim — just joined, a few entries
ti = welpen_scouts[3]
add_progress(ti, "kamperen", 0, 0, "in_progress", ts(2026, 3, 5))
add_progress(ti, "kamperen", 1, 0, "in_progress", ts(2026, 3, 8))

# Eva — mixed progress
ev = welpen_scouts[4]
for li in range(5):
    add_progress(ev, "vuur_stoken", li, 0, "signed_off", ts(2026, 3, 15),
                 signed_off_by=wl, signed_off_at=ts(2026, 4, 5))
for li in range(4):
    add_progress(ev, "kamperen", li, 0, "work_done", ts(2026, 4, 10))

# ── Progress — Verkenners (navigeren + vredeslicht + sport_spel) ──────────────

vl = leider_objs["verkenners"]

# Lars — navigeren volledig niveau 1 afgetekend
la = verkenners_scouts[0]
for li in range(5):
    add_progress(la, "navigeren", li, 0, "signed_off", ts(2026, 2, 25),
                 signed_off_by=vl, signed_off_at=ts(2026, 3, 20))
for li in range(5):
    add_progress(la, "vredeslicht", li, 0, "signed_off", ts(2026, 3, 22),
                 signed_off_by=vl, signed_off_at=ts(2026, 4, 18))
for li in range(3):
    add_progress(la, "navigeren", li, 1, "work_done", ts(2026, 4, 20))

# Anna — navigeren niveau 1 pending
an = verkenners_scouts[1]
for li in range(5):
    p = add_progress(an, "navigeren", li, 0, "pending_signoff", ts(2026, 3, 15))
    add_signoff_request(p, vl, ts(2026, 4, 28))
for li in range(3):
    add_progress(an, "sport_spel", li, 0, "in_progress", ts(2026, 3, 20))

# Finn — scattered entries
fi = verkenners_scouts[2]
for li in range(3):
    add_progress(fi, "vredeslicht", li, 0, "in_progress", ts(2026, 3, 8))
for li in range(5):
    add_progress(fi, "navigeren", li, 0, "signed_off", ts(2026, 3, 10),
                 signed_off_by=vl, signed_off_at=ts(2026, 4, 2))

# Noor — recent entries only
no = verkenners_scouts[3]
for li in range(2):
    add_progress(no, "sport_spel", li, 0, "in_progress", ts(2026, 3, 20))

# Sam — just started
sa = verkenners_scouts[4]
add_progress(sa, "vredeslicht", 0, 0, "in_progress", ts(2026, 3, 20))
add_progress(sa, "vredeslicht", 1, 0, "in_progress", ts(2026, 3, 22))

# ── Progress — Stam (peer, identiteit + internationaal) ──────────────────────

sl = leider_objs["stam"]

ro, ik, jo, ma = stam_scouts

for li in range(5):
    add_progress(ro, "identiteit", li, 0, "signed_off", ts(2026, 2, 15),
                 signed_off_by=ik, signed_off_at=ts(2026, 3, 5))
for li in range(5):
    add_progress(ik, "identiteit", li, 0, "signed_off", ts(2026, 2, 15),
                 signed_off_by=ro, signed_off_at=ts(2026, 3, 5))
for li in range(5):
    add_progress(jo, "internationaal", li, 0, "signed_off", ts(2026, 3, 1),
                 signed_off_by=ma, signed_off_at=ts(2026, 4, 1))
for li in range(3):
    p = add_progress(ma, "internationaal", li, 0, "pending_signoff", ts(2026, 4, 15))
    add_signoff_request(p, jo, ts(2026, 4, 28))

# ── Commit ────────────────────────────────────────────────────────────────────

db.commit()
print("Seed complete.")

counts = {
    "users": db.query(User).count(),
    "groups": db.query(Group).count(),
    "speltakken": db.query(Speltak).count(),
    "progress_entries": db.query(ProgressEntry).count(),
    "signoff_requests": db.query(SignoffRequest).count(),
}
for k, v in counts.items():
    print(f"  {k}: {v}")
