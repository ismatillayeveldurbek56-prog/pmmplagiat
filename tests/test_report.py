from io import BytesIO

import pytest
from pypdf import PdfReader

from app.branding import BRAND_NAME
from app.services.ai_risk import AIStyleAssessment
from app.services.quetext import InternetScanResult, InternetSource
from app.services.report import build_report


def _completed_result() -> InternetScanResult:
    return InternetScanResult(
        similarity=24.5,
        originality=75.5,
        sources=[
            InternetSource("Ochiq manba", "https://example.uz", 31),
        ],
        status="completed",
    )


def test_v6_pdf_contains_completed_multisource_sections() -> None:
    ai_assessment = AIStyleAssessment(
        score=38,
        verdict="Natija noaniq - qo‘shimcha mualliflik tekshiruvi kerak",
        reasons=["Gap tuzilishida bir xillik kuzatildi."],
        language="uz",
        provider="Qashqadaryo PMM stilometriyasi",
    )
    report = build_report(
        "v6.docx",
        500,
        internet_result=_completed_result(),
        ai_assessment=ai_assessment,
        authorship_questions=["Asosiy xulosani tushuntiring."],
    )

    assert report.startswith(b"%PDF")
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(report)).pages)
    normalized = " ".join(text.split())
    assert "V6 MULTI-SOURCE" in text
    assert BRAND_NAME in text
    assert "Quetext DeepSearch" in text
    assert "UMUMIY ORIGINALLIK" in text
    assert "PLAGAI ICHKI BAZA" not in text
    assert "PlagAI ichki hujjatlar bazasi" not in text
    assert "Takrorlanmaydigan mos so‘zlar" not in text
    assert "Internet tekshiruvi yakunlanmadi" not in normalized


def test_failed_or_pending_scan_cannot_generate_pdf() -> None:
    for status in ("failed", "pending", "disabled"):
        internet = InternetScanResult(
            similarity=None,
            originality=None,
            status=status,
            error_message="Insufficient credits",
        )
        with pytest.raises(ValueError, match="faqat muvaffaqiyatli"):
            build_report("xato.docx", 1200, internet_result=internet)


def test_pdf_cleans_html_from_legacy_quetext_snippets() -> None:
    internet = InternetScanResult(
        similarity=32.0,
        originality=68.0,
        sources=[
            InternetSource(
                "Academic source",
                "https://example.org/study",
                36,
                introduction=(
                    "<b>In</b>&nbsp;MC, <b>Carol</b> &amp; "
                    "<strong>Brayne</strong> studied 958 people aged over 90."
                ),
            )
        ],
        status="completed",
    )

    report = build_report("legacy.docx", 300, internet_result=internet)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(report)).pages)
    normalized = " ".join(text.split())

    assert "In MC, Carol & Brayne studied 958 people aged over 90." in normalized
    assert "<b>" not in text
    assert "</b>" not in text
    assert "&nbsp;" not in text
    assert "&amp;" not in text


def test_pdf_groups_duplicate_urls_and_keeps_fragments() -> None:
    internet = InternetScanResult(
        similarity=4.61,
        originality=95.39,
        sources=[
            InternetSource(
                "Bir sahifa — birinchi fragment",
                "https://example.uz/article/",
                13,
                introduction="Birinchi mos fragment.",
                similarity=61.0,
            ),
            InternetSource(
                "Bir sahifa — ikkinchi fragment",
                "https://example.uz/article",
                9,
                introduction="Ikkinchi mos fragment.",
                similarity=80.0,
            ),
        ],
        status="completed",
    )

    report = build_report("duplicate.docx", 442, internet_result=internet)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(report)).pages)
    normalized = " ".join(text.split())

    assert "1 ta noyob ochiq sahifa va 2 ta mos fragment" in normalized
    assert "Fragment 1" in normalized
    assert "Fragment 2" in normalized
    assert "mutlaq plagiatsiz" in normalized
