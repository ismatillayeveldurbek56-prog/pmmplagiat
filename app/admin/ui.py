# ruff: noqa: E501
from html import escape
from urllib.parse import urlencode

from app.admin.security import ROLE_LABELS, AdminIdentity
from app.branding import BRAND_NAME, brand_logo_data_uri


def number(value: int | float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def badge(status: str) -> str:
    labels = {
        "pending": "Kutilmoqda",
        "approved": "Tasdiqlangan",
        "rejected": "Rad etilgan",
        "awaiting_receipt": "Chek kutilmoqda",
        "cancelled": "Bekor qilingan",
        "completed": "Yakunlangan",
        "failed": "Xato",
        "active": "Faol",
        "revoked": "Bekor qilingan",
    }
    css = "ok" if status in {"approved", "completed", "active"} else "bad" if status in {"rejected", "failed", "revoked"} else "warn"
    return f'<span class="badge {css}">{escape(labels.get(status, status))}</span>'


def csrf_field(identity: AdminIdentity) -> str:
    return f'<input type="hidden" name="csrf" value="{escape(identity.csrf)}">'


def flash(message: str, kind: str = "ok") -> str:
    return f'<div class="flash {escape(kind)}">{escape(message)}</div>' if message else ""


def pagination(path: str, page: int, total: int, per_page: int, **params: str) -> str:
    pages = max(1, (total + per_page - 1) // per_page)
    if pages <= 1:
        return ""
    links = []
    for candidate in range(max(1, page - 2), min(pages, page + 2) + 1):
        query = {**params, "page": str(candidate)}
        active = " active" if candidate == page else ""
        links.append(f'<a class="page{active}" href="{path}?{urlencode(query)}">{candidate}</a>')
    return '<nav class="pagination">' + "".join(links) + "</nav>"


def page(
    *,
    title: str,
    body: str,
    identity: AdminIdentity,
    active: str,
    subtitle: str = "",
) -> str:
    logo_uri = brand_logo_data_uri()
    logo = f'<img src="{logo_uri}" alt="Logo">' if logo_uri else '<div class="logo-fallback">Q</div>'
    nav_items = [
        ("dashboard", "Dashboard", "/admin/dashboard", "dashboard"),
        ("users", "Foydalanuvchilar", "/admin/users", "users"),
        ("payments", "To‘lovlar", "/admin/payments", "payments"),
        ("tariffs", "Tariflar", "/admin/tariffs", "tariffs"),
        ("scans", "Tekshiruvlar", "/admin/scans", "scans"),
        ("certificates", "Sertifikatlar", "/admin/certificates", "certificates"),
        ("broadcast", "Xabar yuborish", "/admin/broadcast", "broadcast"),
        ("reports", "Hisobotlar", "/admin/reports", "reports"),
        ("audit", "Audit jurnali", "/admin/audit", "audit"),
        ("admins", "Administratorlar", "/admin/admins", "admins"),
    ]
    links = "".join(
        f'<a class="nav-link {"active" if active == key else ""}" href="{url}"><span>{label}</span></a>'
        for key, label, url, permission in nav_items
        if identity.can(permission) or permission in {"tariffs", "admins"} and identity.can("*")
    )
    return f"""<!doctype html><html lang="uz"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)} — Admin</title>
<style>
:root{{--nav:#07182f;--nav2:#0b2446;--bg:#f3f6fb;--card:#fff;--text:#10223e;--muted:#64748b;--line:#dce5f0;--primary:#0a66c2;--cyan:#0891b2;--green:#15803d;--red:#b91c1c;--amber:#b45309}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}}a{{color:inherit;text-decoration:none}}.layout{{display:grid;grid-template-columns:255px minmax(0,1fr);min-height:100vh}}.sidebar{{background:linear-gradient(180deg,var(--nav),var(--nav2));color:#dbeafe;padding:22px 16px;position:sticky;top:0;height:100vh}}.brand{{display:flex;gap:12px;align-items:center;padding:0 8px 22px;border-bottom:1px solid #25466f}}.brand img,.logo-fallback{{width:48px;height:48px;border-radius:50%;background:white;object-fit:contain}}.logo-fallback{{display:grid;place-items:center;color:var(--nav);font-weight:900}}.brand b{{display:block;font-size:13px;line-height:1.35}}.brand small{{color:#7dd3fc}}.nav{{display:grid;gap:5px;margin-top:18px}}.nav-link{{padding:11px 13px;border-radius:10px;color:#bfdbfe;font-size:14px;font-weight:600}}.nav-link:hover,.nav-link.active{{background:#164b7e;color:white}}.profile{{position:absolute;bottom:18px;left:16px;right:16px;border-top:1px solid #25466f;padding-top:14px;font-size:12px;color:#93c5fd}}.content{{padding:28px;min-width:0}}.topbar{{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:22px}}h1{{font-size:27px;margin:0}}.subtitle{{color:var(--muted);font-size:14px;margin-top:5px}}h2{{font-size:18px;margin:0 0 16px}}.card{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px;box-shadow:0 5px 20px rgba(15,35,65,.05)}}.cards{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-bottom:18px}}.metric small{{display:block;color:var(--muted);font-weight:600}}.metric b{{display:block;font-size:27px;margin-top:8px}}.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.toolbar{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:16px}}input,select,textarea{{width:100%;padding:10px 12px;border:1px solid #cbd5e1;border-radius:9px;background:white;font:inherit;color:var(--text)}}textarea{{min-height:130px;resize:vertical}}label{{display:grid;gap:6px;color:#334155;font-size:13px;font-weight:650}}.toolbar input{{max-width:320px}}.toolbar select{{width:auto;min-width:160px}}button,.btn{{border:0;border-radius:9px;padding:10px 14px;background:var(--primary);color:white;font:inherit;font-weight:700;cursor:pointer;display:inline-block}}.btn.secondary,button.secondary{{background:#e2e8f0;color:#1e293b}}.btn.danger,button.danger{{background:var(--red)}}.btn.small,button.small{{padding:7px 10px;font-size:12px}}.table-wrap{{overflow:auto}}table{{width:100%;border-collapse:collapse;font-size:13px}}th{{text-align:left;color:#64748b;font-size:11px;text-transform:uppercase;letter-spacing:.04em;background:#f8fafc}}th,td{{padding:12px 10px;border-bottom:1px solid #e7edf4;vertical-align:middle}}tr:hover td{{background:#fbfdff}}.badge{{display:inline-block;padding:5px 8px;border-radius:999px;font-size:11px;font-weight:800;background:#e2e8f0}}.badge.ok{{background:#dcfce7;color:#166534}}.badge.bad{{background:#fee2e2;color:#991b1b}}.badge.warn{{background:#fef3c7;color:#92400e}}.muted{{color:var(--muted)}}.flash{{padding:12px 14px;border-radius:10px;margin-bottom:16px;background:#dcfce7;color:#166534}}.flash.bad{{background:#fee2e2;color:#991b1b}}.actions{{display:flex;gap:7px;flex-wrap:wrap}}form.inline{{display:inline}}.form-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}}.form-grid .wide{{grid-column:1/-1}}.pagination{{display:flex;gap:6px;margin-top:16px}}.page{{padding:7px 10px;background:white;border:1px solid var(--line);border-radius:7px}}.page.active{{background:var(--primary);color:white}}.empty{{padding:35px;text-align:center;color:var(--muted)}}.receipt{{max-width:100%;max-height:580px;border-radius:12px;border:1px solid var(--line)}}.mobile-menu{{display:none}}.confirm{{accent-color:var(--primary);width:auto}}@media(max-width:1050px){{.cards{{grid-template-columns:repeat(2,1fr)}}.grid2{{grid-template-columns:1fr}}}}@media(max-width:760px){{.layout{{display:block}}.sidebar{{position:relative;height:auto}}.profile{{position:static;margin-top:14px}}.content{{padding:18px 12px}}.cards,.form-grid{{grid-template-columns:1fr}}.form-grid .wide{{grid-column:auto}}.topbar{{align-items:flex-start}}h1{{font-size:22px}}}}
</style></head><body><div class="layout"><aside class="sidebar"><div class="brand">{logo}<div><b>{escape(BRAND_NAME)}</b><small>Web-admin panel</small></div></div><nav class="nav">{links}</nav><div class="profile"><b>{escape(identity.username)}</b><br>{escape(ROLE_LABELS.get(identity.role, identity.role))}<form action="/admin/logout" method="post" style="margin-top:10px">{csrf_field(identity)}<button class="secondary small">Chiqish</button></form></div></aside><main class="content"><header class="topbar"><div><h1>{escape(title)}</h1><div class="subtitle">{escape(subtitle)}</div></div><a class="btn secondary" href="/admin/dashboard">Bosh sahifa</a></header>{body}</main></div></body></html>"""


def login_page(error: str = "") -> str:
    logo_uri = brand_logo_data_uri()
    logo = f'<img src="{logo_uri}" alt="Logo">' if logo_uri else ""
    return f"""<!doctype html><html lang="uz"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Admin panelga kirish</title><style>*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:linear-gradient(135deg,#06152b,#103c68);font-family:Inter,system-ui;color:#10223e}}.box{{width:min(410px,92vw);background:white;padding:30px;border-radius:22px;box-shadow:0 30px 80px #0005}}img{{width:78px;height:78px;display:block;margin:0 auto 15px;object-fit:contain;border-radius:50%}}h1{{font-size:23px;text-align:center;margin:0}}p{{text-align:center;color:#64748b;font-size:13px;line-height:1.5}}label{{display:grid;gap:6px;margin-top:14px;font-size:13px;font-weight:700}}input{{padding:12px;border:1px solid #cbd5e1;border-radius:10px;font:inherit}}button{{width:100%;margin-top:20px;padding:12px;border:0;border-radius:10px;background:#0a66c2;color:white;font:inherit;font-weight:800}}.err{{background:#fee2e2;color:#991b1b;padding:10px;border-radius:9px;text-align:center;font-size:13px}}</style></head><body><form class="box" method="post" action="/admin/login">{logo}<h1>Admin panel</h1><p>{escape(BRAND_NAME)} boshqaruv tizimi</p>{f'<div class="err">{escape(error)}</div>' if error else ''}<label>Login<input name="username" autocomplete="username" required></label><label>Parol<input type="password" name="password" autocomplete="current-password" required></label><button>Kirish</button></form></body></html>"""
