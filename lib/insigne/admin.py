from collections import defaultdict

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from .models import (
    Group,
    GroupMembership,
    MembershipRequest,
    ProgressEntry,
    SignoffRequest,
    SpeltakMembership,
    User,
)


def get_dashboard_stats(db: Session) -> dict:
    """Aggregated stats for the admin dashboard."""
    # Pie: users per group (a user in N groups counts N times) + ungrouped
    all_groups = {g.id: g.name for g in db.query(Group).all()}
    active_memberships = (
        db.query(GroupMembership.user_id, GroupMembership.group_id)
        .filter_by(approved=True, withdrawn=False)
        .all()
    )
    user_to_groups: dict[str, set[str]] = defaultdict(set)
    group_user_count: dict[str, int] = defaultdict(int)
    for user_id, group_id in active_memberships:
        if group_id not in user_to_groups[user_id]:
            user_to_groups[user_id].add(group_id)
            group_user_count[group_id] += 1

    users_by_group = [
        {"label": all_groups[gid], "count": cnt}
        for gid, cnt in sorted(group_user_count.items(), key=lambda x: all_groups[x[0]])
    ]
    total_users: int = db.query(func.count(User.id)).scalar() or 0
    ungrouped = total_users - len(user_to_groups)
    if ungrouped > 0:
        users_by_group.append({"label": "Zonder groep", "count": ungrouped})

    # Pie: active vs pending (invited but not yet activated)
    status_rows = (
        db.query(User.status, func.count(User.id))
        .group_by(User.status)
        .all()
    )
    status_labels = {"active": "Actief", "pending": "Uitgenodigd / in afwachting"}
    users_by_status = [
        {"label": status_labels.get(s, s), "count": c}
        for s, c in sorted(status_rows, key=lambda x: x[0])
    ]

    # Line: cumulative users over time (by month)
    monthly_users = (
        db.query(func.strftime("%Y-%m", User.created_at), func.count(User.id))
        .group_by(func.strftime("%Y-%m", User.created_at))
        .order_by(func.strftime("%Y-%m", User.created_at))
        .all()
    )
    cumulative = 0
    users_over_time = []
    for month, count in monthly_users:
        cumulative += count
        users_over_time.append({"month": month or "?", "count": cumulative})

    # Line: sign-off requests per month
    signoff_rows = (
        db.query(
            func.strftime("%Y-%m", SignoffRequest.created_at),
            func.count(SignoffRequest.id),
        )
        .group_by(func.strftime("%Y-%m", SignoffRequest.created_at))
        .order_by(func.strftime("%Y-%m", SignoffRequest.created_at))
        .all()
    )
    signoff_over_time = [{"month": m or "?", "count": c} for m, c in signoff_rows]

    # Line: badges earned (signed_off) per month
    badges_rows = (
        db.query(
            func.strftime("%Y-%m", ProgressEntry.signed_off_at),
            func.count(ProgressEntry.id),
        )
        .filter(ProgressEntry.status == "signed_off", ProgressEntry.signed_off_at.isnot(None))
        .group_by(func.strftime("%Y-%m", ProgressEntry.signed_off_at))
        .order_by(func.strftime("%Y-%m", ProgressEntry.signed_off_at))
        .all()
    )
    badges_over_time = [{"month": m or "?", "count": c} for m, c in badges_rows]

    return {
        "total_users": total_users,
        "users_by_group": users_by_group,
        "users_by_status": users_by_status,
        "users_over_time": users_over_time,
        "signoff_over_time": signoff_over_time,
        "badges_over_time": badges_over_time,
    }


def find_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email.strip().lower()).first()


def delete_user(db: Session, user_id: str) -> None:
    """Delete a user and all owned data; null out non-cascading FK back-references."""
    user = db.get(User, user_id)
    if not user:
        return

    # Null out non-cascading back-references so the delete doesn't violate FK constraints
    db.execute(
        update(ProgressEntry)
        .where(ProgressEntry.signed_off_by_id == user_id)
        .values(signed_off_by_id=None, signed_off_at=None)
    )
    db.execute(update(User).where(User.created_by_id == user_id).values(created_by_id=None))
    db.execute(
        update(GroupMembership)
        .where(GroupMembership.invited_by_id == user_id)
        .values(invited_by_id=None)
    )
    db.execute(
        update(SpeltakMembership)
        .where(SpeltakMembership.invited_by_id == user_id)
        .values(invited_by_id=None)
    )
    db.execute(
        update(SpeltakMembership)
        .where(SpeltakMembership.source_scout_id == user_id)
        .values(source_scout_id=None)
    )
    db.execute(
        update(MembershipRequest)
        .where(MembershipRequest.reviewed_by_id == user_id)
        .values(reviewed_by_id=None)
    )

    # Delete mentor sign-off requests (not cascaded from User)
    db.query(SignoffRequest).filter_by(mentor_id=user_id).delete()

    # Delete progress entries — cascades SignoffRequest and SignoffRejection per entry
    for entry in db.query(ProgressEntry).filter_by(user_id=user_id).all():
        db.delete(entry)

    # Delete user — cascades memberships, tokens, email_change_requests, membership_requests
    db.delete(user)
    db.commit()
