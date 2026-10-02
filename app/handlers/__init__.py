from aiogram import Router

from app.handlers import admin, common, documents, feedback, payments, start


def build_router() -> Router:
    router = Router(name="root")
    router.include_router(start.router)
    router.include_router(payments.router)
    router.include_router(documents.router)
    router.include_router(admin.router)
    router.include_router(feedback.router)
    router.include_router(common.router)
    return router
