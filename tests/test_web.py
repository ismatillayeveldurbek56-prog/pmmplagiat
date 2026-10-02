import httpx

from app.branding import BRAND_NAME
from app.web import create_web_app


async def test_health_endpoint_identifies_quetext_provider() -> None:
    app = create_web_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        root = await client.get("/")
        health = await client.get("/health")
        old_webhook = await client.post("/webhooks/copyleaks/completed", json={})

    assert root.status_code == 200
    assert health.json() == {
        "status": "ok",
        "service": f"{BRAND_NAME} boti",
        "provider": "Quetext",
    }
    assert old_webhook.status_code == 404
