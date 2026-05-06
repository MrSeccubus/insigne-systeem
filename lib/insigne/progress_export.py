"""Export and import of a user's progress data."""

import io
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from .models import ProgressEntry, User

_STATUS_RANK = {"in_progress": 1, "work_done": 2, "signed_off": 3}

_STATUS_LABEL = {
    "in_progress": "In uitvoering",
    "work_done": "Werk gedaan",
    "signed_off": "Afgetekend",
}


# ── helpers ───────────────────────────────────────────────────────────────────

def find_or_create_nameholder(db: Session, name: str) -> User:
    """Return an emailless user with this name, creating one if needed.

    Matches only emailless users to avoid false positives against real accounts.
    Nameholders have no group or speltak memberships.
    """
    user = db.query(User).filter(User.email.is_(None), User.name == name).first()
    if not user:
        user = User(email=None, name=name, status="active")
        db.add(user)
        db.flush()
    return user


# ── export ────────────────────────────────────────────────────────────────────

def export_data(db: Session, user_id: str) -> dict:
    """Return a serialisable dict of the user's non-pending progress."""
    user = db.get(User, user_id)
    entries = (
        db.query(ProgressEntry)
        .filter(
            ProgressEntry.user_id == user_id,
            ProgressEntry.status != "pending_signoff",
        )
        .order_by(
            ProgressEntry.badge_slug,
            ProgressEntry.level_index,
            ProgressEntry.step_index,
        )
        .all()
    )

    progress = []
    for e in entries:
        item: dict = {
            "badge_slug": e.badge_slug,
            "level_index": e.level_index,
            "step_index": e.step_index,
            "status": e.status,
            "notes": e.notes,
            "signed_off_by": e.signed_off_by.name if e.signed_off_by else None,
            "signed_off_at": e.signed_off_at.isoformat() if e.signed_off_at else None,
        }
        progress.append(item)

    return {
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user": {"name": user.name if user else None},
        "progress": progress,
    }


def to_yaml(data: dict) -> str:
    return yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)


def to_pdf(data: dict, data_dir: Path | None = None) -> bytes:
    """Render a human-readable PDF of the export data."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    GREEN = colors.HexColor("#00A651")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title",
        parent=styles["Title"],
        textColor=GREEN,
        fontSize=20,
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        textColor=colors.HexColor("#555555"),
        fontSize=10,
        spaceAfter=16,
    )
    badge_style = ParagraphStyle(
        "Badge",
        parent=styles["Heading2"],
        textColor=GREEN,
        fontSize=13,
        spaceBefore=14,
        spaceAfter=4,
        borderPad=2,
    )
    step_style = ParagraphStyle("Step", parent=styles["Normal"], fontSize=9, leading=13)
    note_style = ParagraphStyle(
        "Note",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#555555"),
        leftIndent=12,
        leading=11,
    )

    badge_cache: dict = {}

    def _badge(slug: str) -> dict | None:
        if slug not in badge_cache:
            if data_dir:
                from insigne.badges import get_badge
                badge_cache[slug] = get_badge(data_dir, slug)
            else:
                badge_cache[slug] = None
        return badge_cache[slug]

    def _step_text(slug: str, level_index: int, step_index: int) -> str:
        b = _badge(slug)
        if b:
            try:
                return b["levels"][level_index]["steps"][step_index]["text"]
            except (IndexError, KeyError):
                pass
        return f"Stap {step_index + 1}"

    def _badge_title(slug: str) -> str:
        b = _badge(slug)
        return b["title"] if b else slug

    def _level_name(slug: str, level_index: int) -> str:
        b = _badge(slug)
        if b:
            try:
                return b["levels"][level_index]["name"]
            except (IndexError, KeyError):
                pass
        return f"Niveau {level_index + 1}"

    user_name = data.get("user", {}).get("name") or "—"
    exported_at = data.get("exported_at", "")
    try:
        dt = datetime.fromisoformat(exported_at)
        date_str = dt.strftime("%-d %B %Y")
    except (ValueError, AttributeError):
        date_str = exported_at

    story = [
        Paragraph("Voortgangsoverzicht", title_style),
        Paragraph(f"<b>{user_name}</b> · geëxporteerd op {date_str}", subtitle_style),
    ]

    # Group entries by badge slug
    by_badge: dict[str, list[dict]] = {}
    for item in data.get("progress", []):
        by_badge.setdefault(item["badge_slug"], []).append(item)

    for slug, items in by_badge.items():
        story.append(Paragraph(_badge_title(slug), badge_style))

        table_data = [["Niveau", "Stap", "Status", "Afgetekend door", "Datum"]]
        for item in items:
            level_lbl = _level_name(slug, item["level_index"])
            step_lbl = _step_text(slug, item["level_index"], item["step_index"])
            status_lbl = _STATUS_LABEL.get(item["status"], item["status"])
            signer = item.get("signed_off_by") or ""
            signed_at = ""
            if item.get("signed_off_at"):
                try:
                    signed_at = datetime.fromisoformat(item["signed_off_at"]).strftime("%-d-%m-%Y")
                except ValueError:
                    signed_at = item["signed_off_at"]

            table_data.append([
                Paragraph(level_lbl, step_style),
                Paragraph(step_lbl, step_style),
                Paragraph(status_lbl, step_style),
                Paragraph(signer, step_style),
                Paragraph(signed_at, step_style),
            ])

            if item.get("notes"):
                table_data.append([
                    "",
                    Paragraph(f"<i>Aantekeningen: {item['notes']}</i>", note_style),
                    "", "", "",
                ])

        col_widths = [3.0 * cm, 6.5 * cm, 2.8 * cm, 3.5 * cm, 2.2 * cm]
        tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), GREEN),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(tbl)

    if not by_badge:
        story.append(Paragraph("Geen voortgang gevonden.", styles["Normal"]))

    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(
        "<font color='#aaaaaa' size='7'>Dit bestand bevat een ingebedde YAML-bijlage die kan worden geïmporteerd.</font>",
        styles["Normal"],
    ))

    doc.build(story)
    return buf.getvalue()


# ── PDF ↔ YAML attachment ─────────────────────────────────────────────────────

_ATTACHMENT_NAME = "insigne_progress.yml"


def embed_yaml_in_pdf(pdf_bytes: bytes, yaml_str: str) -> bytes:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.append(reader)
    writer.add_attachment(_ATTACHMENT_NAME, yaml_str.encode())
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def extract_yaml_from_pdf(pdf_bytes: bytes) -> str | None:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    for name, chunks in reader.attachments.items():
        if name.endswith(".yml") or name.endswith(".yaml"):
            return b"".join(chunks).decode()
    return None


# ── import ────────────────────────────────────────────────────────────────────

def import_progress(db: Session, user_id: str, data: dict) -> int:
    """Upsert progress entries from export data. Returns count of created/updated rows."""
    count = 0
    for item in data.get("progress", []):
        badge_slug = item.get("badge_slug")
        level_index = item.get("level_index")
        step_index = item.get("step_index")
        status = item.get("status")

        if badge_slug is None or level_index is None or step_index is None or status is None:
            continue
        if status not in _STATUS_RANK:
            continue

        import_rank = _STATUS_RANK[status]

        entry = (
            db.query(ProgressEntry)
            .filter_by(
                user_id=user_id,
                badge_slug=badge_slug,
                level_index=level_index,
                step_index=step_index,
            )
            .first()
        )

        if entry:
            current_rank = _STATUS_RANK.get(entry.status, 0)
            if import_rank <= current_rank:
                continue
            entry.status = status
            if item.get("notes") and not entry.notes:
                entry.notes = item["notes"]
        else:
            entry = ProgressEntry(
                user_id=user_id,
                badge_slug=badge_slug,
                level_index=level_index,
                step_index=step_index,
                status=status,
                notes=item.get("notes"),
            )
            db.add(entry)
            db.flush()

        if status == "signed_off":
            signed_off_by_name = item.get("signed_off_by")
            if signed_off_by_name:
                holder = find_or_create_nameholder(db, signed_off_by_name)
                entry.signed_off_by_id = holder.id
            signed_off_at = item.get("signed_off_at")
            if signed_off_at:
                try:
                    entry.signed_off_at = datetime.fromisoformat(str(signed_off_at))
                except ValueError:
                    pass

        count += 1

    db.commit()
    return count
