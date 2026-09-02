import os
import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---- Баптаулар (баптауларды осында немесе .env / хостинг env vars арқылы өзгертуге болады) ----
BOT_TOKEN = os.environ["BOT_TOKEN"]
PERFORMER_NAME = os.environ.get("PERFORMER_NAME", "Сенің атың осында")
THUMBNAIL_PATH = os.path.join(os.path.dirname(__file__), "placeholder.jpg")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Сәлем! Маған кез келген аудио файл (mp3, voice, т.б.) жібер — "
        "мен саған мұқаба фото мен әнші атын өзгертіп қайтарамын."
    )


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message

    # Аудионы әр түрлі форматтан анықтау (audio / voice / audio-document)
    audio_obj = None
    if message.audio:
        audio_obj = message.audio
    elif message.voice:
        audio_obj = message.voice
    elif message.document and (message.document.mime_type or "").startswith("audio"):
        audio_obj = message.document

    if not audio_obj:
        await message.reply_text(
            "Бұл аудио файл емес сияқты. Маған тікелей аудио (mp3 және т.б.) жіберіңізші."
        )
        return

    title = getattr(audio_obj, "title", None) or "Атаусыз ән"

    status_msg = await message.reply_text("Өңдеп жатырмын, күте тұрыңыз...")

    try:
        tg_file = await audio_obj.get_file()
        audio_bytes = await tg_file.download_as_bytearray()

        with open(THUMBNAIL_PATH, "rb") as thumb:
            await message.reply_audio(
                audio=bytes(audio_bytes),
                filename=f"{title}.mp3",
                thumbnail=thumb,
                performer=PERFORMER_NAME,
                title=title,
            )

        await status_msg.delete()
    except Exception as e:
        logger.exception("Аудионы өңдеу кезінде қате шықты")
        await status_msg.edit_text(f"Кешіріңіз, қате шықты: {e}")


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(
            filters.AUDIO | filters.VOICE | filters.Document.AUDIO,
            handle_audio,
        )
    )

    logger.info("Бот іске қосылды...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
