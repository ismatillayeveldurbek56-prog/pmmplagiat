import hashlib
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.branding import BRAND_NAME, BRAND_TAGLINE, brand_logo_bytes
from app.services.ai_risk import AIStyleAssessment, language_name
from app.services.assessment import build_professional_conclusion
from app.services.internal_similarity import MultiSourceResult
from app.services.quetext import InternetScanResult
from app.services.unicode_safety import html_fragment_to_text

NAVY = colors.HexColor("#123B5D")
TURQUOISE = colors.HexColor("#1F8E8A")
GOLD = colors.HexColor("#B88A3B")
GREEN = colors.HexColor("#2E6D54")
RED = colors.HexColor("#9A4E43")
AMBER = colors.HexColor("#9A6A27")
SLATE = colors.HexColor("#384A55")
MUTED = colors.HexColor("#6C7A80")
BORDER = colors.HexColor("#D8D2C4")
PAPER = colors.HexColor("#FFFEF8")
PALE_TURQUOISE = colors.HexColor("#F0F8F6")
PALE_GOLD = colors.HexColor("#FBF7EC")
PALE_RED = colors.HexColor("#FCF4F2")
MAX_TABLE_FRAGMENT_CHARS = 900


def _fonts() -> tuple[str, str, str]:
    regular_paths = (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
    )
    bold_paths = (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    )
    display_paths = (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSerif-Bold.ttf"),
    )
    regular = "Helvetica"
    bold = "Helvetica-Bold"
    display = bold
    for path in regular_paths:
        if path.exists():
            if "PlagiAI-Regular" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("PlagiAI-Regular", str(path)))
            regular = "PlagiAI-Regular"
            break
    for path in bold_paths:
        if path.exists():
            if "PlagiAI-Bold" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("PlagiAI-Bold", str(path)))
            bold = "PlagiAI-Bold"
            break
    for path in display_paths:
        if path.exists():
            if "PlagiAI-Display" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("PlagiAI-Display", str(path)))
            display = "PlagiAI-Display"
            break
    return regular, bold, display


def _styles(regular: str, bold: str, display: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "body": ParagraphStyle("Body", parent=base["BodyText"], fontName=regular, fontSize=8.2, leading=11.4, textColor=SLATE, spaceAfter=0.25 * mm),
        "small": ParagraphStyle("Small", parent=base["BodyText"], fontName=regular, fontSize=7, leading=9, textColor=MUTED),
        "title": ParagraphStyle("ReportTitle", parent=base["Title"], fontName=display, fontSize=16.8, leading=20, textColor=NAVY, alignment=TA_LEFT, spaceAfter=1.2 * mm),
        "subtitle": ParagraphStyle("Subtitle", parent=base["BodyText"], fontName=regular, fontSize=8.5, leading=11, textColor=MUTED, spaceAfter=3 * mm),
        "heading": ParagraphStyle("SectionHeading", parent=base["Heading2"], fontName=bold, fontSize=10.5, leading=13.2, textColor=NAVY, spaceBefore=1.2 * mm, spaceAfter=1.0 * mm, keepWithNext=True),
        "metric_value": ParagraphStyle("MetricValue", parent=base["BodyText"], fontName=display, fontSize=14.5, leading=16, textColor=NAVY, alignment=TA_CENTER),
        "metric_label": ParagraphStyle("MetricLabel", parent=base["BodyText"], fontName=regular, fontSize=6.8, leading=9, textColor=MUTED, alignment=TA_CENTER),
        "banner_title": ParagraphStyle("BannerTitle", parent=base["BodyText"], fontName=bold, fontSize=10.5, leading=13, textColor=NAVY),
        "banner_body": ParagraphStyle("BannerBody", parent=base["BodyText"], fontName=regular, fontSize=8, leading=10.5, textColor=SLATE),
        "table": ParagraphStyle("TableText", parent=base["BodyText"], fontName=regular, fontSize=6.9, leading=8.8, textColor=SLATE),
        "table_bold": ParagraphStyle("TableBold", parent=base["BodyText"], fontName=bold, fontSize=6.9, leading=8.8, textColor=NAVY),
    }


def _metric_card(value: str, label: str, styles: dict[str, ParagraphStyle], background: colors.Color, width: float = 56 * mm) -> Table:
    card = Table([[Paragraph(escape(value), styles["metric_value"])], [Paragraph(escape(label), styles["metric_label"])]], colWidths=[width], rowHeights=[9 * mm, 6.5 * mm])
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), background),
        ("LINEABOVE", (0, 0), (-1, 0), 0.7, GOLD),
        ("LINEBELOW", (0, -1), (-1, -1), 0.7, NAVY),
        ("LINEBEFORE", (0, 0), (0, -1), 0.35, BORDER),
        ("LINEAFTER", (-1, 0), (-1, -1), 0.35, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return card


def _report_id(filename: str, checked_at: datetime) -> str:
    return hashlib.sha256(f"{filename}|{checked_at.isoformat()}".encode()).hexdigest()[:12].upper()


def _split_table_fragment(text: str, limit: int = MAX_TABLE_FRAGMENT_CHARS) -> list[str]:
    value = text.strip()
    if not value:
        return ["-"]
    chunks: list[str] = []
    while len(value) > limit:
        split_at = value.rfind(" ", 0, limit + 1)
        if split_at < limit // 2:
            split_at = limit
        chunks.append(value[:split_at])
        value = value[split_at:]
        if value.startswith(" "):
            value = value[1:]
    if value:
        chunks.append(value)
    return chunks


def _draw_step_motif(canvas, x: float, y: float, size: float) -> None:
    canvas.saveState(); canvas.translate(x, y); canvas.setStrokeColor(TURQUOISE); canvas.setLineWidth(0.35)
    upper = canvas.beginPath(); upper.moveTo(-size, 0); upper.lineTo(-size * 0.5, size * 0.34); upper.lineTo(0, 0); upper.lineTo(size * 0.5, size * 0.34); upper.lineTo(size, 0); canvas.drawPath(upper, stroke=1, fill=0)
    canvas.setStrokeColor(GOLD); canvas.setLineWidth(0.28)
    lower = canvas.beginPath(); lower.moveTo(-size * 0.72, -size * 0.27); lower.lineTo(-size * 0.34, -size * 0.04); lower.lineTo(0, -size * 0.27); lower.lineTo(size * 0.34, -size * 0.04); lower.lineTo(size * 0.72, -size * 0.27); canvas.drawPath(lower, stroke=1, fill=0); canvas.restoreState()


def _page_decorator(regular: str, bold: str, report_id: str):
    def draw(canvas, document) -> None:
        canvas.saveState(); width, height = A4; canvas.setFillColor(PAPER); canvas.rect(0, 0, width, height, stroke=0, fill=1)
        canvas.setStrokeColor(GOLD); canvas.setLineWidth(0.5); canvas.line(18 * mm, height - 21 * mm, width - 18 * mm, height - 21 * mm)
        _draw_step_motif(canvas, 20.5 * mm, height - 21 * mm, 2.5 * mm); _draw_step_motif(canvas, width - 20.5 * mm, height - 21 * mm, 2.5 * mm)
        logo = brand_logo_bytes()
        if logo:
            canvas.drawImage(ImageReader(BytesIO(logo)), 18 * mm, height - 19.5 * mm, width=16.5 * mm, height=16.5 * mm, preserveAspectRatio=True, anchor="c", mask="auto"); brand_x = 37 * mm
        else: brand_x = 18 * mm
        canvas.setFont(bold, 6.5); canvas.setFillColor(NAVY); canvas.drawString(brand_x, height - 9.7 * mm, BRAND_NAME)
        canvas.setFont(regular, 5.4); canvas.setFillColor(MUTED); canvas.drawString(brand_x, height - 13 * mm, BRAND_TAGLINE)
        canvas.setFont(regular, 7); canvas.setFillColor(MUTED); canvas.drawRightString(width - 18 * mm, height - 11 * mm, f"Hisobot № {report_id}")
        canvas.setStrokeColor(GOLD); canvas.line(18 * mm, 13 * mm, width - 18 * mm, 13 * mm); canvas.drawString(18 * mm, 9 * mm, "Elektron hujjat  •  Akademik ekspertiza uchun"); canvas.drawRightString(width - 18 * mm, 9 * mm, f"V6 MULTI-SOURCE  |  {document.page}-sahifa"); canvas.restoreState()
    return draw


def build_report(filename: str, word_count: int, checked_at: datetime | None = None, internet_result: InternetScanResult | None = None, ai_assessment: AIStyleAssessment | None = None, authorship_questions: list[str] | None = None, multi_source_result: MultiSourceResult | None = None) -> bytes:
    if internet_result is None or internet_result.status != "completed" or internet_result.similarity is None or internet_result.originality is None:
        raise ValueError("Yakuniy PDF faqat muvaffaqiyatli internet tekshiruvidan keyin yaratiladi.")
    checked_at = checked_at or datetime.now(UTC)
    if multi_source_result is None:
        similarity = float(internet_result.similarity)
        multi_source_result = MultiSourceResult(internet_similarity=similarity, internal_similarity=0.0, combined_similarity=similarity, combined_originality=float(internet_result.originality), internet_matched_words=round(word_count * similarity / 100.0), internal_matched_words=0, deduplicated_matched_words=round(word_count * similarity / 100.0), total_words=word_count, internal_sources=[])
    regular, bold, display = _fonts(); styles = _styles(regular, bold, display)
    conclusion = build_professional_conclusion(internet_result, ai_assessment, overall_similarity=multi_source_result.combined_similarity)
    report_id = _report_id(filename, checked_at); buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=25 * mm, bottomMargin=16 * mm, title=f"{BRAND_NAME} tekshiruv hisoboti — {filename}", author=BRAND_NAME, subject="Internet va akademik manbalar bo‘yicha o‘xshashlik hisoboti")
    detected_language = ai_assessment.language if ai_assessment else "unknown"; scan_mode = "QUETEXT DEEPSEARCH"
    story: list[object] = [Spacer(1, 0.8 * mm), Paragraph("TO‘LIQ TEKSHIRUV HISOBOTI", styles["title"]), Paragraph("Internet va akademik manbalar bo‘yicha o‘xshashlik, mos fragmentlar va AI indikatori bo‘yicha elektron qayd", styles["subtitle"])]
    metadata = Table([
        [Paragraph("HUJJAT", styles["small"]), Paragraph(escape(filename), styles["table_bold"])],
        [Paragraph("TEKSHIRUV MA’LUMOTI", styles["small"]), Paragraph(checked_at.strftime("%d.%m.%Y • %H:%M") + f"  •  {word_count:,} so‘z  •  " + escape(language_name(detected_language)), styles["table"])],
        [Paragraph("TEKSHIRUV REJIMI", styles["small"]), Paragraph(escape(scan_mode), styles["table_bold"])],
    ], colWidths=[38 * mm, 136 * mm])
    metadata.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), PALE_GOLD), ("BOX", (0, 0), (-1, -1), 0.6, BORDER), ("INNERGRID", (0, 0), (-1, -1), 0.35, BORDER), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]))
    story.extend([metadata, Spacer(1, 2 * mm)])
    banner = Table([[Paragraph(f"<font color='{GREEN.hexval()}'><b>{escape(conclusion.status_label)}</b></font><br/><font size='12'><b>{escape(conclusion.headline)}</b></font>", styles["banner_title"])], [Paragraph(escape(conclusion.conclusion), styles["banner_body"])]], colWidths=[174 * mm])
    banner.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PALE_TURQUOISE), ("LINEBEFORE", (0, 0), (0, -1), 2.2, GREEN), ("LINEABOVE", (0, 0), (-1, 0), 0.45, BORDER), ("LINEBELOW", (0, -1), (-1, -1), 0.45, BORDER), ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, 0), (-1, 0), 2), ("TOPPADDING", (0, 1), (-1, 1), 1), ("BOTTOMPADDING", (0, 1), (-1, 1), 6)]))
    story.extend([banner, Spacer(1, 2 * mm)])
    ai_value = "MAVJUD EMAS" if not ai_assessment or ai_assessment.score is None else f"{ai_assessment.score:.1f}%"
    card_width = 56 * mm; no_public_matches = not internet_result.sources and multi_source_result.internet_similarity <= 0
    metric_cards = [
        _metric_card(f"{len(internet_result.sources)} ta", "TOPILGAN OCHIQ MANBA", styles, PAPER, card_width) if no_public_matches else _metric_card(f"{multi_source_result.combined_originality:.2f}%", "ANIQLANGAN ORIGINALLIK*", styles, PAPER, card_width),
        _metric_card(f"{multi_source_result.combined_similarity:.2f}%", "UMUMIY O‘XSHASHLIK", styles, PAPER, card_width),
        _metric_card(f"{multi_source_result.internet_similarity:.2f}%", "INTERNET / AKADEMIK", styles, PAPER, card_width),
    ]
    metrics = Table([metric_cards], colWidths=[58 * mm] * 3); metrics.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 1 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 1 * mm), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    story.extend([metrics, Paragraph(f"AI indikatori: <b>{escape(ai_value)}</b>", styles["small"]), Paragraph("1. Internet manbalari bo‘yicha natija", styles["heading"]), Paragraph(f"Quetext DeepSearch tashqi skani yakunlandi. {len(internet_result.sources)} ta ochiq manba qaytdi. Dalil darajasi: <b>{escape(conclusion.evidence_level)}</b>.", styles["body"])])
    if internet_result.sources:
        source_rows: list[list[object]] = [[Paragraph("№", styles["table_bold"]), Paragraph("INTERNET MANBASI", styles["table_bold"]), Paragraph("MOSLIK", styles["table_bold"]), Paragraph("MOS FRAGMENT", styles["table_bold"])]]
        for number, source in enumerate(internet_result.sources, start=1):
            title = escape(source.title)
            if source.url:
                title = f"<link href={quoteattr(source.url)} color='#2563EB'>{title}</link><br/><font size='6' color='#64748B'>{escape(source.url[:140])}</font>"
            similarity_text = f"{source.matched_words} so‘z" + (f"<br/><b>{source.similarity:.2f}%</b>" if source.similarity is not None else "")
            snippet_chunks = _split_table_fragment(html_fragment_to_text(source.introduction or ""))
            for chunk_number, snippet in enumerate(snippet_chunks, start=1):
                first_chunk = chunk_number == 1; source_cell = title if first_chunk else f"(davomi {chunk_number}/{len(snippet_chunks)})"
                source_rows.append([Paragraph(str(number) if first_chunk else "", styles["table"]), Paragraph(source_cell, styles["table"]), Paragraph(similarity_text if first_chunk else "", styles["table"]), Paragraph(escape(snippet), styles["table"])])
        source_table = LongTable(source_rows, colWidths=[8 * mm, 69 * mm, 23 * mm, 74 * mm], repeatRows=1)
        source_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), PALE_TURQUOISE), ("TEXTCOLOR", (0, 0), (-1, 0), NAVY), ("BOX", (0, 0), (-1, -1), 0.5, BORDER), ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        for row in range(2, len(source_rows), 2): source_table.setStyle(TableStyle([("BACKGROUND", (0, row), (-1, row), PALE_GOLD)]))
        story.append(source_table)
    else:
        story.append(Paragraph("Tekshiruv yakunlandi: ochiq internet/akademik veb manbalaridan mos fragment topilmadi. Ushbu natija faqat qamrab olingan ochiq manbalar doirasidagi moslikni bildiradi; uni mutlaq plagiatsiz yoki 100% original degan hukm sifatida talqin qilib bo‘lmaydi.", styles["body"]))
    story.append(Paragraph("2. AIga o‘xshashlik indikatori (stilometrik baho)", styles["heading"]))
    if ai_assessment is None:
        story.append(Paragraph("AI tahlili ushbu tekshiruvda bajarilmadi. Plagiat natijasi AI tahlili o‘rnini bosmaydi.", styles["body"]))
    else:
        ai_score_text = "Foiz mavjud emas" if ai_assessment.score is None else f"{ai_assessment.score:.2f}%"
        ai_table = Table([[Paragraph("PROVAYDER", styles["small"]), Paragraph(escape(ai_assessment.provider), styles["table_bold"])], [Paragraph("NATIJA", styles["small"]), Paragraph(escape(ai_score_text), styles["table_bold"])], [Paragraph("ISHONCH", styles["small"]), Paragraph(escape(ai_assessment.confidence), styles["table"])], [Paragraph("TALQIN", styles["small"]), Paragraph(escape(ai_assessment.verdict), styles["table"]) ]], colWidths=[32 * mm, 142 * mm])
        ai_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), PALE_GOLD), ("BOX", (0, 0), (-1, -1), 0.5, BORDER), ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        story.append(ai_table)
        for reason in ai_assessment.reasons[:6]: story.append(Paragraph(f"• {escape(reason)}", styles["body"]))
        story.append(Paragraph(f"<i>{escape(ai_assessment.disclaimer)}</i>", styles["small"]))
    story.append(Paragraph("3. Natijani to‘g‘ri talqin qilish", styles["heading"]))
    for line in ["O‘xshashlik foizi — tekshiruv qamrab olgan manbalardan topilgan moslik ulushi; u avtomatik plagiat hukmi emas.", "Ochiq manba topilmagani — yopiq bazalar, chop etilmagan ishlar yoki indekslanmagan sahifalar tekshirilmagan bo‘lishi mumkinligini anglatadi.", "AI indikatori uslubiy-statistik baho bo‘lib, mualliflikni isbotlamaydi; yakuniy qaror inson eksperti tomonidan beriladi."]:
        story.append(Paragraph(f"• {escape(line)}", styles["body"]))
    story.append(Paragraph("4. Ekspert tavsiyalari", styles["heading"]))
    for number, recommendation in enumerate(conclusion.recommendations, start=1): story.append(Paragraph(f"<b>{number}.</b> {escape(recommendation)}", styles["body"]))
    if authorship_questions:
        story.append(Paragraph("5. Mualliflikni tekshirish savollari", styles["heading"]))
        question_lines = "<br/>".join(f"<b>{number}.</b> {escape(question)}" for number, question in enumerate(authorship_questions[:3], start=1))
        story.append(Paragraph(question_lines, styles["small"]))
    document.build(story, onFirstPage=_page_decorator(regular, bold, report_id), onLaterPages=_page_decorator(regular, bold, report_id))
    return buffer.getvalue()
