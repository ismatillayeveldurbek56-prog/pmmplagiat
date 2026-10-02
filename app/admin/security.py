import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import parse_qs

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import AdminAccount

COOKIE_NAME = "qvpmm_admin"
ROLE_LABELS = {
    "owner": "Bosh administrator",
    "finance": "Moliya",
    "operator": "Operator",
    "support": "Yordam xizmati",
    "auditor": "Auditor",
}
ROLE_PERMISSIONS = {
    "owner": {"*"},
    "finance": {
        "dashboard", "payments", "payment_manage", "users", "balance", "reports", "audit"
    },
    "operator": {
        "dashboard", "users", "user_manage", "scans", "scan_manage",
        "certificates", "certificate_manage", "broadcast",
    },
    "support": {"dashboard", "users", "payments", "scans", "certificates"},
    "auditor": {"dashboard", "users", "payments", "scans", "certificates", "reports", "audit"},
}


@dataclass(frozen=True)
class AdminIdentity:
    username: str
    role: str
    csrf: str

    def can(self, permission: str) -> bool:
        allowed = ROLE_PERMISSIONS.get(self.role, set())
        return "*" in allowed or permission in allowed


def hash_password(password: str, *, salt: str | None = None) -> str:
    raw_salt = bytes.fromhex(salt) if salt else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), raw_salt, 240_000)
    return f"pbkdf2_sha256${raw_salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt, digest = encoded.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hash_password(password, salt=salt).rsplit("$", 1)[-1]
    return hmac.compare_digest(candidate, digest)


def _secret(settings: Settings) -> bytes:
    return settings.admin_web_secret.encode("utf-8")


def create_session(identity: AdminIdentity, settings: Settings) -> str:
    payload = {
        "u": identity.username,
        "r": identity.role,
        "c": identity.csrf,
        "e": int(time.time()) + settings.admin_session_hours * 3600,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    signature = hmac.new(_secret(settings), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def read_session(token: str, settings: Settings) -> AdminIdentity | None:
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(_secret(settings), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        if int(payload["e"]) < int(time.time()):
            return None
        return AdminIdentity(
            username=str(payload["u"]),
            role=str(payload["r"]),
            csrf=str(payload["c"]),
        )
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def require_admin(
    request: Request,
    settings: Settings,
    permission: str | None = None,
) -> AdminIdentity:
    if not settings.admin_web_ready:
        raise HTTPException(status_code=503, detail="Web-admin sozlanmagan.")
    identity = read_session(request.cookies.get(COOKIE_NAME, ""), settings)
    if identity is None:
        raise HTTPException(status_code=401, detail="Kirish talab qilinadi.")
    if permission and not identity.can(permission):
        raise HTTPException(status_code=403, detail="Bu amal uchun ruxsat yo‘q.")
    return identity


async def parse_form(request: Request) -> dict[str, str]:
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" not in content_type:
        raise HTTPException(status_code=415, detail="Forma formati noto‘g‘ri.")
    parsed = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}


def verify_csrf(identity: AdminIdentity, form: dict[str, str]) -> None:
    if not hmac.compare_digest(identity.csrf, form.get("csrf", "")):
        raise HTTPException(status_code=403, detail="Xavfsizlik tokeni noto‘g‘ri.")


async def authenticate(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    settings: Settings,
) -> AdminIdentity | None:
    account = await session.scalar(
        select(AdminAccount).where(
            AdminAccount.username == username,
            AdminAccount.is_active.is_(True),
        )
    )
    if account and verify_password(password, account.password_hash):
        return AdminIdentity(
            username=account.username,
            role=account.role,
            csrf=secrets.token_urlsafe(24),
        )
    if hmac.compare_digest(username, settings.admin_web_username) and hmac.compare_digest(
        password, settings.admin_web_password
    ):
        return AdminIdentity(username=username, role="owner", csrf=secrets.token_urlsafe(24))
    return None
