import os
import io
import re
import logging
import threading
import http.server
import socketserver

from PIL import Image

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
PERFORMER_NAME = os.environ.get("PERFORMER_NAME", "Сенің атың осында")
SOURCE_IMAGE_PATH = os.path.join(os.path.dirname(__file__), "placeholder.jpg")

# Каналға автоматты жариялау үшін
CHANNEL_ID = os.environ["CHANNEL_ID"]  # мыс. "@meningkanalym" немесе "-1001234567890"
AUTHOR_CAPTION = os.environ.get("AUTHOR_CAPTION", "🎵 Жаңа ән")


def prepare_images(source_path: str):
    """
    Пайдаланушы қандай форматта (png/webp/т.б.) сурет салса да,
    оны PIL арқылы ашып, дұрыс JPEG-ке айналдырамыз. Екі нұсқа жасаймыз:
    - cover_bytes: ID3-ке ендіру үшін (толық өлшем)
    - thumb_bytes: Telegram-нің thumbnail параметріне арналған,
      max 320x320px және <200KB болуы керек (Telegram шегі)
    """
    img = Image.open(source_path)
    img = img.convert("RGB")  # RGBA/CMYK/т.б. болса, JPEG-ке сай RGB-ге келтіреміз

    # --- ID3 cover (толық өлшем, бірақ тым үлкен болмасын) ---
    cover_img = img.copy()
    cover_img.thumbnail((800, 800))
    cover_buf = io.BytesIO()
    cover_img.save(cover_buf, format="JPEG", quality=90)
    cover_bytes = cover_buf.getvalue()

    # --- Telegram thumbnail (Telegram шегі: max 320x320, <200KB) ---
    thumb_img = img.copy()
    thumb_img.thumbnail((320, 320))
    thumb_buf = io.BytesIO()
    quality = 85
    thumb_img.save(thumb_buf, format="JPEG", quality=quality)
    # 200KB-тан аспауын қамтамасыз етеміз
    while thumb_buf.tell() > 200 * 1024 and quality > 30:
        quality -= 10
        thumb_buf = io.BytesIO()
        thumb_img.save(thumb_buf, format="JPEG", quality=quality)
    thumb_bytes = thumb_buf.getvalue()

    return cover_bytes, thumb_bytes


COVER_IMAGE_BYTES, THUMB_IMAGE_BYTES = prepare_images(SOURCE_IMAGE_PATH)
logging.getLogger(__name__).info(
    "Суреттер дайындалды: cover=%d байт, thumb=%d байт",
    len(COVER_IMAGE_BYTES),
    len(THUMB_IMAGE_BYTES),
)


def rewrite_id3_tags(audio_bytes: bytes, cover_bytes: bytes, performer: str, title: str) -> bytes:
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

    tags.add(
        APIC(
            encoding=3,          # UTF-8
            mime="image/jpeg",
            type=3,              # 3 = мұқаба (front cover)
            desc="Cover",
            data=cover_bytes,
        )
    )

    tags.setall("TPE1", [TPE1(encoding=3, text=[performer])])
    tags.setall("TIT2", [TIT2(encoding=3, text=[title])])

    # МАҢЫЗДЫ: тегті сол баста аудио деректері бар buf-тың өзіне сақтаймыз,
    # бос жаңа буферге емес - әйтпесе нақты аудио фреймдер жоғалып кетеді
    # және дыбыс ойналмай қалады.
    audio.save(buf)
    buf.seek(0)
    return buf.read()


DATE_LIKE_PATTERN = re.compile(
    r"""
    \d{1,2}[./-]\d{1,2}[./-]\d{2,4}   # 03.09.2026, 03/09/2026, 03-09-2026
    |
    \d{4}-\d{1,2}-\d{1,2}             # 2026-09-03
    |
    \d{1,2}:\d{2}(:\d{2})?            # 11:54, 11:54:30
    """,
    re.VERBOSE,
)


def sanitize_title(raw_title: str, fallback: str = "Атаусыз ән") -> str:
    """
    Кейбір аудио файлдардың ID3 title тегіне (жүктеп алған кезде) қате
    түрде дата/уақыт жазылып қалуы мүмкін (мыс. "03.09.2026 11:54").
    Бұл функция сондай жағдайды анықтап, орнына бейтарап атау қояды -
    әйтпесе сол дата тікелей трек атауы ретінде каналда көрінеді.
    """
    if not raw_title or not raw_title.strip():
        return fallback

    if DATE_LIKE_PATTERN.search(raw_title):
        return fallback

    return raw_title.strip()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Сәлем! Маған кез келген аудио файл (mp3, voice, т.б.) жібер — "
        "мен саған мұқаба фото мен әнші атын өзгертіп қайтарамын, "
        "әрі ол автоматты түрде каналға да жарияланады. 🎵"
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

    title = sanitize_title(getattr(audio_obj, "title", None))

    status_msg = await message.reply_text("Өңдеп жатырмын, күте тұрыңыз...")

    try:
        tg_file = await audio_obj.get_file()
        raw_bytes = bytes(await tg_file.download_as_bytearray())

        file_path = getattr(audio_obj, "file_path", "") or (tg_file.file_path or "")
        is_mp3 = file_path.lower().endswith(".mp3") or getattr(audio_obj, "mime_type", "") == "audio/mpeg"

        if is_mp3:
            try:
                # Файлдың өз ішіндегі ескі мұқабаны нақты ауыстырамыз
                final_bytes = rewrite_id3_tags(raw_bytes, COVER_IMAGE_BYTES, PERFORMER_NAME, title)
            except Exception:
                logger.exception("ID3 тегін өзгерту сәтсіз болды, түпнұсқа файлмен жалғастырамыз")
                final_bytes = raw_bytes
        else:
            # mp3 болмаса (мыс. voice/ogg), ID3 қолданылмайды - Telegram-нің
            # thumbnail/performer параметрлеріне сүйенеміз
            final_bytes = raw_bytes

        await message.reply_audio(
            audio=final_bytes,
            filename=f"{title}.mp3",
            thumbnail=io.BytesIO(THUMB_IMAGE_BYTES),
            performer=PERFORMER_NAME,
            title=title,
        )

        await status_msg.delete()

        # --- Каналға автоматты жариялау ---
        try:
            await context.bot.send_audio(
                chat_id=CHANNEL_ID,
                audio=final_bytes,
                filename=f"{title}.mp3",
                thumbnail=io.BytesIO(THUMB_IMAGE_BYTES),
                performer=PERFORMER_NAME,
                title=title,
                caption=AUTHOR_CAPTION,
            )
        except Exception:
            logger.exception(
                "Каналға жариялау сәтсіз болды - бот каналда админ екенін тексеріңіз"
            )
    except Exception as e:
        logger.exception("Аудионы өңдеу кезінде қате шықты")
        await status_msg.edit_text(f"Кешіріңіз, қате шықты: {e}")


def run_dummy_server():
    """
    Render 'Web Service' түрі HTTP порт ашылғанын күтеді. Біздің бот
    тек Telegram polling арқылы жұмыс істейді, нақты порт ашпайды.
    Сондықтан Render процесті "сәтсіз" деп есептеп, үнемі қайта
    іске қосып, бірнеше бот данасын қатар жіберіп жатыр еді
    (сол 409 Conflict қатесінің басты себебі).

    Бұл функция тек Render-дің порт тексерісін қанағаттандыру үшін
    минималды HTTP сервер ашады, ешқандай нақты жұмыс істемейді.
    """
    port = int(os.environ.get("PORT", 10000))
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("0.0.0.0", port), handler) as httpd:
        logging.getLogger(__name__).info("Dummy HTTP server %s портта ашылды", port)
        httpd.serve_forever()


def main():
    # Dummy HTTP серверді бөлек thread-те іске қосамыз, ол бот polling-ке
    # кедергі келтірмеу үшін
    server_thread = threading.Thread(target=run_dummy_server, daemon=True)
    server_thread.start()

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
