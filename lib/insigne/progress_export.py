"""Export and import of a user's progress data."""

import io
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from .models import Jaarinsigne2026Inclusion, ProgressEntry, User

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
    from . import groups as groups_svc

    user = db.get(User, user_id)
    primary_speltak_type = (
        groups_svc.get_user_primary_speltak_type(db, user_id) if user else None
    )
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

    inclusion_rows = (
        db.query(Jaarinsigne2026Inclusion)
        .filter(Jaarinsigne2026Inclusion.user_id == user_id)
        .order_by(
            Jaarinsigne2026Inclusion.badge_slug,
            Jaarinsigne2026Inclusion.level_index,
            Jaarinsigne2026Inclusion.step_index,
        )
        .all()
    )
    jaarinsigne_2026_inclusions = [
        {
            "badge_slug": inc.badge_slug,
            "level_index": inc.level_index,
            "step_index": inc.step_index,
        }
        for inc in inclusion_rows
    ]

    return {
        "version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user": {
            "name": user.name if user else None,
            "primary_speltak_type": primary_speltak_type,
        },
        "progress": progress,
        "jaarinsigne_2026_inclusions": jaarinsigne_2026_inclusions,
    }


def to_yaml(data: dict) -> str:
    return yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)


def to_pdf(data: dict, catalogue=None, base_url: str = "") -> bytes:
    """Render a PDF resembling the home page badge grid.

    Per badge: a table with 5 eis-group rows × 3 niveau columns.
    Column headers show the badge images (.1/.2/.3) and niveau labels.
    Cells show the step text, status, date, signer, and notes.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image as RLImage, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    GREEN = colors.HexColor("#00A651")
    MARGIN = 2.5 * cm
    CONTENT_W = A4[0] - 2 * MARGIN
    ROW_LABEL_W = 3.0 * cm
    STEP_COL_W = (CONTENT_W - ROW_LABEL_W) / 3
    IMG_H = 45  # pt — badge image height in column header

    STATUS_BG = {
        "signed_off": colors.HexColor("#16a34a"),
        "work_done":  colors.HexColor("#bbf7d0"),
        "in_progress": colors.HexColor("#bfdbfe"),
    }
    STATUS_LABEL_NL = {
        "signed_off":  "Afgetekend",
        "work_done":   "Ik ben klaar",
        "in_progress": "Mee bezig",
        None:          "Niet begonnen",
    }

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=2.5 * cm, bottomMargin=2.5 * cm,
    )
    styles = getSampleStyleSheet()

    def _ps(name, **kw):
        return ParagraphStyle(name, parent=styles["Normal"], **kw)

    title_st   = _ps("PTitle",  textColor=GREEN, fontSize=20, spaceAfter=12, fontName="Helvetica-Bold")
    sub_st     = _ps("PSub",    textColor=colors.HexColor("#555555"), fontSize=10, spaceAfter=16)
    cat_st     = _ps("PCat",    textColor=GREEN, fontSize=13, spaceBefore=16, spaceAfter=6, fontName="Helvetica-Bold")
    badge_st   = _ps("PBadge",  textColor=GREEN, fontSize=12, spaceBefore=14, spaceAfter=4, fontName="Helvetica-Bold")
    rowlbl_st  = _ps("PRowLbl", fontSize=8, leading=10, fontName="Helvetica-Bold")
    hdr_dk_st  = _ps("PHdrDk",  fontSize=8, leading=10, fontName="Helvetica-Bold", textColor=colors.HexColor("#1a1a1a"), alignment=1)

    # Text styles per status (step text, status label, detail lines, notes)
    def _sts(suffix, step_color, stat_color, detail_color):
        return {
            "step":   _ps(f"PStep{suffix}",   fontSize=7,   leading=9,  textColor=step_color,   fontName="Helvetica-Oblique"),
            "status": _ps(f"PStat{suffix}",   fontSize=7,   leading=9,  textColor=stat_color,   fontName="Helvetica-Bold"),
            "detail": _ps(f"PDetail{suffix}", fontSize=6.5, leading=8,  textColor=detail_color),
            "notes":  _ps(f"PNotes{suffix}",  fontSize=6.5, leading=8,  textColor=detail_color, fontName="Helvetica-Oblique"),
        }

    CSTS = {
        None:          _sts("None", colors.HexColor("#aaaaaa"), colors.HexColor("#aaaaaa"), colors.HexColor("#aaaaaa")),
        "in_progress": _sts("IP",   colors.HexColor("#1e40af"), colors.HexColor("#1e40af"), colors.HexColor("#1d4ed8")),
        "work_done":   _sts("WD",   colors.HexColor("#166534"), colors.HexColor("#166534"), colors.HexColor("#166534")),
        "signed_off":  _sts("SO",   colors.white,               colors.white,               colors.HexColor("#bbf7d0")),
    }

    def _format_date(iso_str) -> str:
        try:
            return datetime.fromisoformat(str(iso_str)).strftime("%-d-%m-%Y")
        except (ValueError, AttributeError):
            return str(iso_str)

    def _badge_img(slug: str, n: int):
        """Return a downscaled RLImage for badge image n (1/2/3), or None."""
        if not catalogue:
            return None
        img_path = catalogue.data_dir / "images" / f"{slug}.{n}.png"
        if not img_path.exists():
            return None
        try:
            from PIL import Image as PILImage
            with PILImage.open(img_path) as pil_img:
                iw, ih = pil_img.size
                ratio = iw / ih
                display_w = min(STEP_COL_W - 8, IMG_H * ratio)
                display_h = display_w / ratio
                # 2× display resolution for crispness; much smaller than source
                px_w = max(1, int(display_w * 2))
                px_h = max(1, int(display_h * 2))
                resized = pil_img.convert("RGBA").resize((px_w, px_h), PILImage.LANCZOS)
                img_buf = io.BytesIO()
                resized.save(img_buf, format="PNG", optimize=True)
                img_buf.seek(0)
                return RLImage(img_buf, width=display_w, height=display_h)
        except Exception:
            iw, ih = ImageReader(str(img_path)).getSize()
            ratio = iw / ih
            w = min(STEP_COL_W - 8, IMG_H * ratio)
            return RLImage(str(img_path), width=w, height=w / ratio)

    def _jaarinsigne_img(slug: str):
        """Return a downscaled RLImage for the jaarinsigne meta-image ({slug}.png), or None.

        Jaarinsigne images are not per-niveau — one image per badge — so this
        is rendered once at the top of the badge section rather than in a
        per-niveau header row.
        """
        if not catalogue:
            return None
        img_path = catalogue.data_dir / "images" / f"{slug}.png"
        if not img_path.exists():
            return None
        target_h = 60  # pt
        try:
            from PIL import Image as PILImage
            with PILImage.open(img_path) as pil_img:
                iw, ih = pil_img.size
                ratio = iw / ih
                display_h = target_h
                display_w = display_h * ratio
                px_w = max(1, int(display_w * 2))
                px_h = max(1, int(display_h * 2))
                resized = pil_img.convert("RGBA").resize((px_w, px_h), PILImage.LANCZOS)
                img_buf = io.BytesIO()
                resized.save(img_buf, format="PNG", optimize=True)
                img_buf.seek(0)
                return RLImage(img_buf, width=display_w, height=display_h)
        except Exception:
            iw, ih = ImageReader(str(img_path)).getSize()
            ratio = iw / ih
            return RLImage(str(img_path), width=target_h * ratio, height=target_h)

    # Build progress lookup: (badge_slug, level_index, step_index) → item
    progress_map: dict[tuple, dict] = {}
    for item in data.get("progress", []):
        key = (item["badge_slug"], item["level_index"], item["step_index"])
        progress_map[key] = item

    user_name = data.get("user", {}).get("name") or "—"
    exported_at = data.get("exported_at", "")
    _MONTHS_NL = ["januari","februari","maart","april","mei","juni",
                  "juli","augustus","september","oktober","november","december"]
    try:
        dt = datetime.fromisoformat(exported_at)
        date_hdr = f"{dt.day} {_MONTHS_NL[dt.month - 1]} {dt.year}"
    except (ValueError, AttributeError):
        date_hdr = exported_at

    site_line = f"Geëxporteerd op {date_hdr}"
    if base_url:
        site_line += f" van {base_url}"

    story: list = [
        Paragraph(f"Voortgangsoverzicht {user_name}", title_st),
        Paragraph(site_line, sub_st),
    ]

    # Per-badge slug_progress: filter progress_map to entries on this badge,
    # keyed by (level_index, step_index) — same shape jaarinsigne_levels_for_scout expects.
    def _slug_progress(slug: str) -> dict:
        return {
            (li, si): item for (s, li, si), item in progress_map.items() if s == slug
        }

    speltak_slug = (data.get("user") or {}).get("primary_speltak_type")

    def _cell_for(item: dict | None) -> tuple[list, str | None]:
        status = item["status"] if item else None
        sts = CSTS[status]
        cell = [Paragraph(f"Status: {STATUS_LABEL_NL[status]}", sts["status"])]
        if item and item.get("signed_off_at"):
            cell.append(Paragraph(f"Op: {_format_date(item['signed_off_at'])}", sts["detail"]))
        if item and item.get("signed_off_by"):
            cell.append(Paragraph(f"Door: {item['signed_off_by']}", sts["detail"]))
        if item and item.get("notes"):
            cell.append(Paragraph(item["notes"], sts["notes"]))
        return cell, status

    if catalogue:
        from .badges import jaarinsigne_levels_for_scout

        badges_by_cat = catalogue.list()
        for category, badge_list in badges_by_cat.items():
            cat_label = {"gewoon": "Gewone insignes", "buitengewoon": "Buitengewone insignes", "explorers": "Explorers"}.get(category, category)
            cat_para = Paragraph(cat_label, cat_st)

            for badge_idx, badge_info in enumerate(badge_list):
                slug = badge_info["slug"]
                badge_full = catalogue.get(slug)
                if not badge_full:
                    continue

                badge_title_para = Paragraph(badge_info["title"], badge_st)
                badge_type = badge_full.get("type", "gewoon")

                # ── Jaarinsigne (per-speltak, one mini-table per level) ──────
                # Jaarinsigne_2026 (meta-insigne) shares this path; the
                # inclusion list is appended as a final section below.
                if badge_type == "jaarinsigne":
                    slug_progress = _slug_progress(slug)
                    resolved_level_index = catalogue.resolve_jaarinsigne_level_index(badge_full, speltak_slug)
                    levels_to_show = jaarinsigne_levels_for_scout(badge_full, slug_progress, resolved_level_index)
                    inclusions = data.get("jaarinsigne_2026_inclusions") or [] if slug == "jaarinsigne_2026" else []
                    if not levels_to_show and not inclusions:
                        continue
                    block: list = [badge_title_para]
                    meta_img = _jaarinsigne_img(slug)
                    if meta_img:
                        block.append(meta_img)
                    for level in levels_to_show:
                        li = level["level_index"]
                        n_steps = len(level["steps"])
                        sub_rows = [[
                            Paragraph("<b>Eis</b>", hdr_dk_st),
                            Paragraph("<b>Voortgang</b>", hdr_dk_st),
                        ]]
                        sub_ts = [
                            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("TOPPADDING", (0, 0), (-1, -1), 3),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                            ("LEFTPADDING", (0, 0), (-1, -1), 4),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ]
                        for step_idx in range(n_steps):
                            step = level["steps"][step_idx]
                            eis_para = Paragraph(
                                f"{step_idx + 1}. {step.get('titel') or ''}".strip().rstrip("."),
                                rowlbl_st,
                            )
                            item = progress_map.get((slug, li, step_idx))
                            cell, status = _cell_for(item)
                            sub_rows.append([eis_para, cell])
                            bg = STATUS_BG.get(status)
                            if bg:
                                row_num = len(sub_rows) - 1
                                sub_ts.append(("BACKGROUND", (1, row_num), (1, row_num), bg))
                        sub_tbl = Table(sub_rows, colWidths=[ROW_LABEL_W, CONTENT_W - ROW_LABEL_W])
                        sub_tbl.setStyle(TableStyle(sub_ts))
                        block.append(Paragraph(
                            f"<b>{level['name']}</b>",
                            _ps("PJaarLvl", fontSize=10, leading=12, spaceBefore=8, spaceAfter=2, fontName="Helvetica-Bold"),
                        ))
                        block.append(sub_tbl)
                    # Jaarinsigne_2026 only: appendix listing the scout's
                    # inclusion picks. The inclusion set is shared across
                    # levels, so render once for the whole badge.
                    if inclusions:
                        inc_rows: list = [[
                            Paragraph("<b>Insigne</b>", hdr_dk_st),
                            Paragraph("<b>Niveau</b>", hdr_dk_st),
                            Paragraph("<b>Eis</b>", hdr_dk_st),
                        ]]
                        for inc in inclusions:
                            ib_slug = inc.get("badge_slug")
                            li = inc.get("level_index")
                            si = inc.get("step_index")
                            ref_badge = catalogue.get(ib_slug) if ib_slug else None
                            ref_title = ref_badge["title"] if ref_badge else (ib_slug or "?")
                            try:
                                ref_step = ref_badge["levels"][li]["steps"][si]
                                ref_eis = ref_step.get("titel") or ref_step.get("text", "")
                            except (TypeError, IndexError, KeyError):
                                ref_eis = ""
                            inc_rows.append([
                                Paragraph(ref_title, _ps("PIncBadge", fontSize=8, leading=10)),
                                Paragraph(f"Niveau {(li or 0) + 1}", _ps("PIncLvl", fontSize=8, leading=10)),
                                Paragraph(f"Eis {(si or 0) + 1}: {ref_eis}", _ps("PIncEis", fontSize=8, leading=10)),
                            ])
                        inc_tbl = Table(inc_rows, colWidths=[CONTENT_W * 0.30, CONTENT_W * 0.18, CONTENT_W * 0.52])
                        inc_tbl.setStyle(TableStyle([
                            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("TOPPADDING", (0, 0), (-1, -1), 3),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ]))
                        block.append(Paragraph(
                            "Insignes die meetellen voor dit jaarinsigne:",
                            _ps("PInc2026Caption", fontSize=9, textColor=colors.HexColor("#555555"),
                                spaceBefore=8, spaceAfter=2),
                        ))
                        block.append(inc_tbl)
                    if badge_idx == 0:
                        block.insert(0, cat_para)
                    story.append(KeepTogether(block))
                    continue

                # ── Regular badge: 5 eisen × 3 niveau grid ───────────────────
                niveau_label = badge_full.get("niveau_label", "Niveau")
                header = [Paragraph("", hdr_dk_st)]
                for step_i in range(3):
                    img = _badge_img(slug, step_i + 1)
                    cell: list = []
                    if img:
                        cell.append(img)
                    cell.append(Paragraph(f"<b>{niveau_label} {step_i + 1}</b>", hdr_dk_st))
                    header.append(cell)

                tbl_data = [header]
                ts = [
                    ("ALIGN",      (0, 0), (-1, 0),   "CENTER"),
                    ("VALIGN",     (0, 0), (-1, 0),   "MIDDLE"),
                    ("GRID",       (0, 0), (-1, -1),  0.25, colors.HexColor("#cccccc")),
                    ("VALIGN",     (0, 1), (-1, -1),  "TOP"),
                    ("TOPPADDING",    (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LEFTPADDING",   (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
                    # Row-label column: subtle gray, vertically centred
                    ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#f3f4f6")),
                    ("VALIGN",     (0, 1), (0, -1), "MIDDLE"),
                ]

                for lvl_i, level in enumerate(badge_full["levels"]):
                    row_num = lvl_i + 1
                    row = [Paragraph(f"{lvl_i + 1}. {level['name']}", rowlbl_st)]
                    for step_i in range(3):
                        col_num = step_i + 1
                        item = progress_map.get((slug, lvl_i, step_i))
                        cell, status = _cell_for(item)
                        row.append(cell)
                        bg = STATUS_BG.get(status)
                        if bg:
                            ts.append(("BACKGROUND", (col_num, row_num), (col_num, row_num), bg))
                    tbl_data.append(row)

                tbl = Table(tbl_data, colWidths=[ROW_LABEL_W, STEP_COL_W, STEP_COL_W, STEP_COL_W])
                tbl.setStyle(TableStyle(ts))
                block = [badge_title_para, tbl]
                if badge_idx == 0:
                    block.insert(0, cat_para)
                story.append(KeepTogether(block))
    else:
        # Fallback: no badge data available — list slugs that have progress.
        by_badge: dict[str, list] = {}
        for item in data.get("progress", []):
            by_badge.setdefault(item["badge_slug"], []).append(item)
        if not by_badge:
            story.append(Paragraph("Geen voortgang gevonden.", styles["Normal"]))
        else:
            for slug in by_badge:
                story.append(Paragraph(slug, badge_st))

    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(
        "<font color='#aaaaaa' size='7'>Dit bestand bevat een ingebedde YAML-bijlage die kan worden geïmporteerd.</font>",
        styles["Normal"],
    ))
    doc.build(story)
    return buf.getvalue()


# ── PDF ↔ YAML attachment ─────────────────────────────────────────────────────

_ATTACHMENT_NAME = "insigne_progress.yml"


def embed_yaml_in_pdf(pdf_bytes: bytes, yaml_str: str, base_url: str = "") -> bytes:
    """Attach the YAML to the PDF and write PDF metadata.

    Adds both a document-level embedded file (for re-import) and a
    /FileAttachment annotation (visible as a paperclip in macOS Preview).
    """
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (
        ArrayObject, DecodedStreamObject, DictionaryObject,
        NameObject, NumberObject, ByteStringObject,
    )

    # Derive metadata from the embedded YAML
    try:
        _meta = yaml.safe_load(yaml_str)
    except Exception:
        _meta = {}

    user_name   = _meta.get("user", {}).get("name") or ""
    exported_at = _meta.get("exported_at", "")
    _MONTHS_NL  = ["januari","februari","maart","april","mei","juni",
                   "juli","augustus","september","oktober","november","december"]
    try:
        _dt      = datetime.fromisoformat(exported_at)
        _date_nl = f"{_dt.day} {_MONTHS_NL[_dt.month - 1]} {_dt.year}"
        _pdf_dt  = _dt.strftime("D:%Y%m%d%H%M%S+00'00'")
    except (ValueError, AttributeError):
        _date_nl = exported_at
        _pdf_dt  = ""

    _title   = f"Insignesysteem voortgangs export van {user_name} - {_date_nl}"
    _author  = f"Insignesysteem - {base_url}" if base_url else "Insignesysteem"
    _subject = (
        f"Voortgangsoverzicht {user_name}\n"
        f"Geëxporteerd op {_date_nl}" + (f" van {base_url}" if base_url else "")
    )

    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.append(reader)

    # ── document-level embedded file (used by extract_yaml_from_pdf) ──────────
    writer.add_attachment(_ATTACHMENT_NAME, yaml_str.encode())

    # ── /FileAttachment annotation (visible in macOS Preview) ─────────────────
    yaml_bytes = yaml_str.encode()
    ef = DecodedStreamObject()
    ef.set_data(yaml_bytes)
    ef.update({
        NameObject("/Type"):    NameObject("/EmbeddedFile"),
        NameObject("/Subtype"): NameObject("/text#2Fyaml"),
        NameObject("/Params"):  DictionaryObject({
            NameObject("/Size"): NumberObject(len(yaml_bytes)),
        }),
    })
    ef_ref = writer._add_object(ef)

    fname = ByteStringObject(_ATTACHMENT_NAME.encode())
    filespec = DictionaryObject({
        NameObject("/Type"): NameObject("/Filespec"),
        NameObject("/F"):    fname,
        NameObject("/UF"):   fname,
        NameObject("/EF"):   DictionaryObject({
            NameObject("/F"):  ef_ref,
            NameObject("/UF"): ef_ref,
        }),
    })
    fs_ref = writer._add_object(filespec)

    page_h = float(writer.pages[0].mediabox.top)
    annot = DictionaryObject({
        NameObject("/Type"):     NameObject("/Annot"),
        NameObject("/Subtype"):  NameObject("/FileAttachment"),
        NameObject("/Rect"):     ArrayObject([
            NumberObject(10), NumberObject(page_h - 20),
            NumberObject(25), NumberObject(page_h - 5),
        ]),
        NameObject("/FS"):       fs_ref,
        NameObject("/Contents"): fname,
        NameObject("/Name"):     NameObject("/Paperclip"),
    })
    annot_ref = writer._add_object(annot)

    first_page = writer.pages[0]
    if "/Annots" not in first_page:
        first_page[NameObject("/Annots")] = ArrayObject([annot_ref])
    else:
        existing = first_page["/Annots"]
        if hasattr(existing, "get_object"):
            existing = existing.get_object()
        existing.append(annot_ref)

    # ── PDF metadata ──────────────────────────────────────────────────────────
    pdf_meta = {
        "/Title":   _title,
        "/Author":  _author,
        "/Subject": _subject,
    }
    if _pdf_dt:
        pdf_meta["/CreationDate"] = _pdf_dt
        pdf_meta["/ModDate"]      = _pdf_dt
    writer.add_metadata(pdf_meta)

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

EXPORT_VERSION = 3


def import_progress(db: Session, user_id: str, data: dict) -> int:
    """Upsert progress entries and jaarinsigne_2026 inclusions from export data.

    Returns count of created/updated ProgressEntry rows (inclusions are not
    counted in the return value, to preserve the v2 API contract).
    """
    file_version = data.get("version", 1)
    if file_version > EXPORT_VERSION:
        raise ValueError(
            f"Export versie {file_version} wordt niet ondersteund door deze installatie "
            f"(ondersteunt t/m versie {EXPORT_VERSION}). Upgrade de applicatie eerst."
        )
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

    # ── jaarinsigne_2026 inclusions (added in export v3) ──────────────────────
    # Older exports (v1/v2) simply don't carry this key — the loop is a no-op.
    for inc in data.get("jaarinsigne_2026_inclusions", []) or []:
        badge_slug = inc.get("badge_slug")
        level_index = inc.get("level_index")
        step_index = inc.get("step_index")
        if badge_slug is None or level_index is None or step_index is None:
            continue
        existing = (
            db.query(Jaarinsigne2026Inclusion)
            .filter_by(
                user_id=user_id,
                badge_slug=badge_slug,
                level_index=level_index,
                step_index=step_index,
            )
            .first()
        )
        if existing is None:
            db.add(Jaarinsigne2026Inclusion(
                user_id=user_id,
                badge_slug=badge_slug,
                level_index=level_index,
                step_index=step_index,
            ))

    db.commit()
    return count
