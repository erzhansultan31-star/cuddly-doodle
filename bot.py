import os
import io
import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TPE1, TIT2, error as ID3Error

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---- Баптаулар (баптауларды осында немесе .env / хостинг env vars арқылы өзгертуге болады) ----
BOT_TOKEN = os.environ["BOT_TOKEN"]
PERFORMER_NAME = os.environ.get("PERFORMER_NAME", "@sharapatmuzz")
THUMBNAIL_PATH = os.path.join(os.path.dirname(__file__), "placeholder.jpg")


def rewrite_id3_tags(audio_bytes: bytes, thumbnail_path: str, performer: str, title: str) -> bytes:
    """
    MP3 файлдың ID3 тегін нақты өзгертеді:
    - ескі ендірілген мұқаба суретті (APIC) толық жояды
    - жаңа суретті ендіреді
    - performer (TPE1) және title (TIT2) тегтерін орнатады

    Тек mp3 форматына қолданылады. Басқа форматтар (voice/ogg және т.б.)
    үшін бұл функция шақырылмайды, себебі ID3 тек mp3-ке тән.
    """
    buf = io.BytesIO(audio_bytes)
    audio = MP3(buf)

    if audio.tags is None:
        audio.add_tags()

    tags = audio.tags

    # Ескі мұқаба суреттердің бәрін жою (APIC фреймдері бірнеше болуы мүмкін)
    tags.delall("APIC")

    with open(thumbnail_path, "rb") as img_file:
        img_data = img_file.read()

    tags.add(
        APIC(
            encoding=3,          # UTF-8
            mime="image/jpeg",
            type=3,              # 3 = мұқаба (front cover)
            desc="Cover",
            data=img_data,
        )
    )

    tags.setall("TPE1", [TPE1(encoding=3, text=[performer])])
    tags.setall("TIT2", [TIT2(encoding=3, text=[title])])

    out_buf = io.BytesIO()
    audio.save(out_buf)
    return out_buf.getvalue()


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
        raw_bytes = bytes(await tg_file.download_as_bytearray())

        file_path = getattr(audio_obj, "file_path", "") or (tg_file.file_path or "")
        is_mp3 = file_path.lower().endswith(".mp3") or getattr(audio_obj, "mime_type", "") == "audio/mpeg"

        if is_mp3:
            try:
                # Файлдың өз ішіндегі ескі мұқабаны нақты ауыстырамыз
                final_bytes = rewrite_id3_tags(raw_bytes, THUMBNAIL_PATH, PERFORMER_NAME, title)
            except Exception:
                logger.exception("ID3 тегін өзгерту сәтсіз болды, түпнұсқа файлмен жалғастырамыз")
                final_bytes = raw_bytes
        else:
            # mp3 болмаса (мыс. voice/ogg), ID3 қолданылмайды - Telegram-нің
            # thumbnail/performer параметрлеріне сүйенеміз
            final_bytes = raw_bytes

        with open(THUMBNAIL_PATH, "rb") as thumb:
            await message.reply_audio(
                audio=final_bytes,
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
