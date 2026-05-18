"""Service layer for the jaarinsigne_2026 meta-badge.

Progress is derived from signed-off eisen of regular badges (gewoon / buitengewoon).
Scouts select which signed-off eisen to "include"; the system then programmatically
sets the jaarinsigne_2026 eis statuses based on drempel thresholds.

Leaders may still manually edit jaarinsigne_2026 eis status the normal way.
Programmatic recalculation never touches entries with status ``signed_off``.
"""
from pathlib import Path

from sqlalchemy.orm import Session

from insigne.badges import BadgeCatalogue
from insigne.models import Jaarinsigne2026Inclusion, ProgressEntry, SpeltakMembership

_CATALOGUE = BadgeCatalogue(Path(__file__).parent.parent.parent / "api" / "data")
_JAARINSIGNE_SLUG = "jaarinsigne_2026"
_ELIGIBLE_CATEGORIES = {"gewoon", "buitengewoon"}


def _build_slug_order() -> dict[str, int]:
    """Map slug → ordinal as listed in badges.yml (for stable card sort)."""
    order: dict[str, int] = {}
    for items in _CATALOGUE.list().values():
        for badge in items:
            order[badge["slug"]] = len(order)
    return order


_SLUG_ORDER = _build_slug_order()


def _card_sort_key(item: dict) -> tuple[int, int, int]:
    """Sort key: badges.yml order → niveau (step_index) → eis (level_index)."""
    return (_SLUG_ORDER.get(item["badge_slug"], 1_000_000),
            item["step_index"],
            item["level_index"])


# ── Eligible badges ────────────────────────────────────────────────────────────

def get_eligible_badges() -> list[dict]:
    """Return badge summary dicts for categories in _ELIGIBLE_CATEGORIES."""
    result = []
    for category, badges in _CATALOGUE.list().items():
        if category in _ELIGIBLE_CATEGORIES:
            result.extend(badges)
    return result


# ── Inclusions ────────────────────────────────────────────────────────────────

def get_inclusions(db: Session, user_id: str) -> list[Jaarinsigne2026Inclusion]:
    """Return all Jaarinsigne2026Inclusion rows for this user."""
    return db.query(Jaarinsigne2026Inclusion).filter_by(user_id=user_id).all()


def toggle_inclusion(
    db: Session,
    user_id: str,
    badge_slug: str,
    level_index: int,
    step_index: int,
) -> bool:
    """Add the inclusion if absent, delete if present.

    Returns True if the row was added (included), False if it was removed.
    """
    existing = db.query(Jaarinsigne2026Inclusion).filter_by(
        user_id=user_id,
        badge_slug=badge_slug,
        level_index=level_index,
        step_index=step_index,
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
        return False
    db.add(Jaarinsigne2026Inclusion(
        user_id=user_id,
        badge_slug=badge_slug,
        level_index=level_index,
        step_index=step_index,
    ))
    db.commit()
    return True


# ── Score computation ──────────────────────────────────────────────────────────

def compute_score(db: Session, user_id: str, signed_off_only: bool = True) -> dict:
    """Compute the aggregate score from included eisen.

    Only counts inclusions where the corresponding ProgressEntry has status
    ``signed_off`` (when signed_off_only=True).

    Returns::

        {
            "total_punten": int,
            "total_groen": int,
            "total_niveau2": int,   # step_index >= 1
            "total_niveau3": int,   # step_index >= 2
            "distinct_insignes": int,
            "inclusions": [
                {"badge_slug": ..., "level_index": ..., "step_index": ...,
                 "punten": ..., "groen": bool},
                ...
            ]
        }
    """
    inclusions = get_inclusions(db, user_id)

    total_punten = 0
    total_groen = 0
    total_niveau2 = 0
    total_niveau3 = 0
    distinct_badges: set[str] = set()
    counted_inclusions = []

    for inc in inclusions:
        if signed_off_only:
            entry = db.query(ProgressEntry).filter_by(
                user_id=user_id,
                badge_slug=inc.badge_slug,
                level_index=inc.level_index,
                step_index=inc.step_index,
            ).first()
            if entry is None or entry.status != "signed_off":
                continue

        # Points = step_index + 1 (niveau 1 = 1pt, niveau 2 = 2pt, niveau 3 = 3pt)
        punten = inc.step_index + 1

        # Groen: look up the badge step
        badge = _CATALOGUE.get(inc.badge_slug)
        groen = False
        if badge and badge.get("type") not in ("jaarinsigne",):
            levels = badge.get("levels", [])
            if inc.level_index < len(levels):
                steps = levels[inc.level_index].get("steps", [])
                if inc.step_index < len(steps):
                    groen = bool(steps[inc.step_index].get("green", False))

        total_punten += punten
        if groen:
            total_groen += 1
        if inc.step_index >= 1:
            total_niveau2 += 1
        if inc.step_index >= 2:
            total_niveau3 += 1
        distinct_badges.add(inc.badge_slug)

        counted_inclusions.append({
            "badge_slug": inc.badge_slug,
            "level_index": inc.level_index,
            "step_index": inc.step_index,
            "punten": punten,
            "groen": groen,
        })

    return {
        "total_punten": total_punten,
        "total_groen": total_groen,
        "total_niveau2": total_niveau2,
        "total_niveau3": total_niveau3,
        "distinct_insignes": len(distinct_badges),
        "inclusions": counted_inclusions,
    }


# ── Eis status from drempel ────────────────────────────────────────────────────

def compute_eis_status(
    score: dict,
    drempel: dict | None,
    speltak_min_punten: int = 3,
) -> str | None:
    """Return the programmatic status for a single eis based on the score and drempel.

    Returns None when drempel is None (no programmatic control).
    Otherwise returns one of: ``"none"``, ``"in_progress"``, ``"work_done"``.
    """
    if drempel is None:
        return None

    drempel_type = drempel.get("type")

    if drempel_type == "leiding_bepaald":
        metric = score["total_punten"]
        minimum = speltak_min_punten
    elif drempel_type == "punten":
        metric = score["total_punten"]
        minimum = drempel["minimum"]
    elif drempel_type == "groen":
        metric = score["total_groen"]
        minimum = drempel["minimum"]
    elif drempel_type == "niveau2":
        metric = score["total_niveau2"]
        minimum = drempel["minimum"]
    elif drempel_type == "niveau3":
        metric = score["total_niveau3"]
        minimum = drempel["minimum"]
    elif drempel_type == "insignes":
        metric = score["distinct_insignes"]
        minimum = drempel["minimum"]
    else:
        return None

    if metric == 0:
        return "none"
    if metric < minimum:
        return "in_progress"
    return "work_done"


# ── Update progress entries ────────────────────────────────────────────────────

def update_progress_entries(
    db: Session,
    user_id: str,
    speltak_slug: str,
    speltak_min_punten: int = 3,
) -> None:
    """Programmatically update jaarinsigne_2026 eis statuses for the given speltak.

    Never touches entries with status ``signed_off``.
    When the computed status is ``"none"``, the ProgressEntry is deleted (if it exists).
    """
    badge = _CATALOGUE.get(_JAARINSIGNE_SLUG)
    if badge is None:
        return

    # Find the level matching this speltak_slug
    level = next((lv for lv in badge["levels"] if lv["slug"] == speltak_slug), None)
    if level is None:
        return

    score = compute_score(db, user_id)
    level_index = level["level_index"]

    for step in level["steps"]:
        eis_status = compute_eis_status(score, step.get("drempel"), speltak_min_punten)
        if eis_status is None:
            continue

        step_index = step["index"]
        entry = db.query(ProgressEntry).filter_by(
            user_id=user_id,
            badge_slug=_JAARINSIGNE_SLUG,
            level_index=level_index,
            step_index=step_index,
        ).first()

        # Never touch signed_off entries
        if entry is not None and entry.status == "signed_off":
            continue

        if eis_status == "none":
            if entry is not None:
                db.delete(entry)
        else:
            if entry is None:
                entry = ProgressEntry(
                    user_id=user_id,
                    badge_slug=_JAARINSIGNE_SLUG,
                    level_index=level_index,
                    step_index=step_index,
                    status=eis_status,
                )
                db.add(entry)
            elif entry.status != eis_status:
                entry.status = eis_status

    db.commit()


# ── Included eisen with display details ──────────────────────────────────────

def get_included_details(db: Session, user_id: str) -> list[dict]:
    """Return currently included eisen with full display details."""
    result = []
    for inc in get_inclusions(db, user_id):
        badge = _CATALOGUE.get(inc.badge_slug)
        if badge is None:
            continue
        levels = badge.get("levels", [])
        if inc.level_index >= len(levels):
            continue
        steps = levels[inc.level_index].get("steps", [])
        if inc.step_index >= len(steps):
            continue
        step = steps[inc.step_index]
        result.append({
            "badge_slug": inc.badge_slug,
            "badge_title": badge["title"],
            "level_index": inc.level_index,
            "step_index": inc.step_index,
            "punten": inc.step_index + 1,
            "groen": bool(step.get("green", False)),
            "step_text": step.get("text", ""),
        })
    result.sort(key=_card_sort_key)
    return result


# ── Available to include ──────────────────────────────────────────────────────

def get_available_to_include(db: Session, user_id: str) -> list[dict]:
    """Return signed-off eisen from eligible badges NOT yet included by the user.

    Returns a list of dicts with badge info + step info.
    """
    eligible_slugs = {b["slug"] for b in get_eligible_badges()}

    # Collect existing inclusions as a set for fast lookup
    existing_inclusions = {
        (inc.badge_slug, inc.level_index, inc.step_index)
        for inc in get_inclusions(db, user_id)
    }

    # Signed-off progress entries for eligible badges
    signed_off = db.query(ProgressEntry).filter(
        ProgressEntry.user_id == user_id,
        ProgressEntry.badge_slug.in_(eligible_slugs),
        ProgressEntry.status == "signed_off",
    ).all()

    result = []
    for entry in signed_off:
        key = (entry.badge_slug, entry.level_index, entry.step_index)
        if key in existing_inclusions:
            continue
        badge = _CATALOGUE.get(entry.badge_slug)
        if badge is None:
            continue
        levels = badge.get("levels", [])
        if entry.level_index >= len(levels):
            continue
        steps = levels[entry.level_index].get("steps", [])
        if entry.step_index >= len(steps):
            continue
        step = steps[entry.step_index]
        result.append({
            "badge_slug": entry.badge_slug,
            "badge_title": badge["title"],
            "level_index": entry.level_index,
            "step_index": entry.step_index,
            "punten": entry.step_index + 1,
            "groen": bool(step.get("green", False)),
            "step_text": step.get("text", ""),
        })
    result.sort(key=_card_sort_key)
    return result


# ── Item aggregates (for the include/exclude editor columns) ──────────────────

def summarize_items(items: list[dict]) -> dict:
    """Aggregate counts over a list of inclusion-style dicts.

    Each item must have ``step_index``, ``punten``, ``groen``, ``badge_slug``.
    """
    niveau_counts = [0, 0, 0]
    for item in items:
        idx = item["step_index"]
        if 0 <= idx < 3:
            niveau_counts[idx] += 1
    return {
        "total_punten": sum(item["punten"] for item in items),
        "total_groen": sum(1 for item in items if item["groen"]),
        "total_niveau1": niveau_counts[0],
        "total_niveau2": niveau_counts[1],
        "total_niveau3": niveau_counts[2],
        "distinct_insignes": len({item["badge_slug"] for item in items}),
    }


def summarize_additional(available: list[dict], included: list[dict]) -> dict:
    """Like summarize_items, but distinct_insignes counts only badges not already included."""
    summary = summarize_items(available)
    included_badges = {item["badge_slug"] for item in included}
    available_badges = {item["badge_slug"] for item in available}
    summary["distinct_insignes"] = len(available_badges - included_badges)
    return summary


# ── Score summary ─────────────────────────────────────────────────────────────

def get_score_summary(
    db: Session,
    user_id: str,
    speltak_slug: str,
    speltak_min_punten: int = 3,
) -> dict:
    """Return a complete score summary for the jaarinsigne_2026 progress display."""
    badge = _CATALOGUE.get(_JAARINSIGNE_SLUG)
    score = compute_score(db, user_id)

    level = None
    eis_statuses: dict[int, str | None] = {}
    if badge:
        level = next((lv for lv in badge["levels"] if lv["slug"] == speltak_slug), None)
        if level:
            eis_statuses = {
                step["index"]: compute_eis_status(score, step.get("drempel"), speltak_min_punten)
                for step in level["steps"]
            }

    # Available punten: signed-off eisen not yet included
    eligible_slugs = {b["slug"] for b in get_eligible_badges()}
    existing_inclusions = {
        (inc.badge_slug, inc.level_index, inc.step_index)
        for inc in get_inclusions(db, user_id)
    }
    signed_off_not_included = db.query(ProgressEntry).filter(
        ProgressEntry.user_id == user_id,
        ProgressEntry.badge_slug.in_(eligible_slugs),
        ProgressEntry.status == "signed_off",
    ).all()
    available_punten = sum(
        e.step_index + 1
        for e in signed_off_not_included
        if (e.badge_slug, e.level_index, e.step_index) not in existing_inclusions
    )

    return {
        "score": score,
        "speltak_slug": speltak_slug,
        "speltak_min_punten": speltak_min_punten,
        "eis_statuses": eis_statuses,
        "available_punten": available_punten,
    }


# ── Resolve user's speltak level + bevers min_punten ──────────────────────────

def resolve_user_level(db: Session, user_id: str) -> tuple[str | None, int]:
    """Return ``(speltak_slug, speltak_min_punten)`` for this user's jaarinsigne_2026 level.

    Looks at the user's stored :class:`JaarinsigneLevel` first (manual override
    or leider-set), falling back to ``get_user_primary_speltak_type`` derived
    from speltak memberships.

    ``speltak_min_punten`` is the bevers-specific "leiding_bepaald" threshold
    pulled from the user's :class:`Speltak` row (defaults to 3 if absent or the
    user isn't a member of a matching speltak).
    """
    from insigne import groups as groups_svc
    from insigne import progress as progress_svc

    jl = progress_svc.get_jaarinsigne_level(db, user_id, _JAARINSIGNE_SLUG)
    if jl:
        speltak_slug = jl.speltak_slug
    else:
        speltak_slug = groups_svc.get_user_primary_speltak_type(db, user_id)

    speltak_min_punten = 3
    if speltak_slug:
        for m in db.query(SpeltakMembership).filter_by(
            user_id=user_id, approved=True, withdrawn=False
        ).all():
            if m.speltak and m.speltak.speltak_type == speltak_slug:
                if m.speltak.jaarinsigne_2026_min_punten is not None:
                    speltak_min_punten = m.speltak.jaarinsigne_2026_min_punten
                break
    return speltak_slug, speltak_min_punten
