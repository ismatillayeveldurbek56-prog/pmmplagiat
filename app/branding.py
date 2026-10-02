import base64
import os
from functools import lru_cache
from pathlib import Path

BRAND_NAME = "Qashqadaryo viloyat pedagogik mahorat markazi"
BRAND_SHORT_NAME = "Qashqadaryo PMM"
BRAND_TAGLINE = "Akademik halollik va raqamli verifikatsiya tizimi"
CERTIFICATE_PREFIX = "QVPMM"

BOT_DESCRIPTION = (
    "Qashqadaryo viloyat pedagogik mahorat markazining akademik hujjatlarni "
    "tekshirish boti. PDF, DOCX va TXT fayllar uchun o‘xshashlik hisoboti hamda "
    "QR-verifikatsiyali sertifikat tayyorlaydi."
)
BOT_SHORT_DESCRIPTION = "Akademik hujjat tekshiruvi, PDF hisobot va QR-sertifikat."


@lru_cache(maxsize=1)
def brand_logo_bytes() -> bytes | None:
    """Load the official markaz logo with a backwards-compatible override."""
    override = (
        os.getenv("MARKAZ_LOGO_FILE", "").strip()
        or os.getenv("PLAGIAI_LOGO_FILE", "").strip()
    )
    if override:
        path = Path(override)
        if path.is_file():
            return path.read_bytes()

    assets = Path(__file__).resolve().parent / "assets"
    logo_path = assets / "qashqadaryo_pmm_logo.png"
    if logo_path.is_file():
        return logo_path.read_bytes()

    return None


def brand_logo_data_uri() -> str | None:
    logo = brand_logo_bytes()
    if not logo:
        return None
    return "data:image/png;base64," + base64.b64encode(logo).decode("ascii")
