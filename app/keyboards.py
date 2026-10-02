from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📄 Faylni tekshirish")],
            [
                KeyboardButton(text="🕘 Tekshiruvlarim"),
                KeyboardButton(text="💰 Balansim"),
            ],
            [
                KeyboardButton(text="💳 To‘lov qilish"),
                KeyboardButton(text="ℹ️ Yordam"),
            ],
            [KeyboardButton(text="💬 Muammo va takliflar")],
        ],
        resize_keyboard=True,
        input_field_placeholder="PDF, DOCX yoki TXT fayl yuboring",
    )
