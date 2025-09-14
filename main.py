import os
import asyncio
import logging
import base64
from pathlib import Path
import yt_dlp
import imageio_ffmpeg
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Берём токен из переменной окружения (для Render)
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан. На Render добавь переменную окружения BOT_TOKEN.")

# Логирование для отладки
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Папка для временных видео
VIDEO_DIR = Path("videos")
VIDEO_DIR.mkdir(exist_ok=True)

# Папка для cookies
COOKIE_DIR = Path("cookies")
COOKIE_DIR.mkdir(exist_ok=True)
COOKIE_FILE = COOKIE_DIR / "cookies.txt"

def setup_cookies():
    """Создаем файл cookies из переменной окружения"""
    cookies_b64 = os.environ.get('COOKIES_B64')
    if not cookies_b64:
        logger.warning("⚠️ COOKIES_B64 не установлена - Instagram может блокировать запросы")
        return False
    
    try:
        # Декодируем из base64
        cookies_data = base64.b64decode(cookies_b64)
        # Сохраняем в файл
        with open(COOKIE_FILE, 'wb') as f:
            f.write(cookies_data)
        logger.info("✅ Cookies успешно созданы")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка создания cookies: {e}")
        return False

def _ffmpeg_path() -> str:
    """Путь к ffmpeg из imageio-ffmpeg."""
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"

def download_video_blocking(url: str) -> str:
    """Скачиваем видео с уникальным именем и ремультиплексируем в mp4."""
    ffmpeg_path = _ffmpeg_path()
    
    # Проверяем, есть ли cookies файл
    use_cookies = COOKIE_FILE.exists() and os.path.getsize(COOKIE_FILE) > 0
    
    ydl_opts = {
        "outtmpl": str(VIDEO_DIR / "%(id)s.%(ext)s"),
        "format": "mp4/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "ffmpeg_location": ffmpeg_path,
    }
    
    # Добавляем cookies если они есть
    if use_cookies:
        ydl_opts["cookiefile"] = str(COOKIE_FILE)
        logger.info("Использую cookies для скачивания")
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        base, _ = os.path.splitext(filename)
        candidate = base + ".mp4"
        if os.path.exists(candidate):
            filename = candidate
    return filename

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Пришли ссылку на Instagram Reels или TikTok — скачаю и пришлю видео.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = (update.message.text or "").strip()
    if not url:
        await update.message.reply_text("Пришли ссылку на видео.")
        return
    if ("instagram.com" not in url) and ("tiktok.com" not in url):
        await update.message.reply_text("Я понимаю только ссылки с instagram.com или tiktok.com. Пришли такую.")
        return

    notice = await update.message.reply_text("⏳ Скачиваю видео...")
    try:
        path = await asyncio.to_thread(download_video_blocking, url)
        if not os.path.exists(path):
            raise RuntimeError("Файл не найден после скачивания.")
        with open(path, "rb") as f:
            await update.message.reply_video(video=f)
        await notice.edit_text("✅ Готово!")
    except Exception as e:
        logger.exception("Ошибка при скачивании/отправке:")
        error_msg = f"❌ Ошибка: {e}"
        
        # Более понятное сообщение об ошибке cookies
        if "cookies" in str(e).lower() or "login" in str(e).lower():
            error_msg += "\n\n⚠️ Instagram требует авторизации. Нужно обновить cookies."
            
        await notice.edit_text(error_msg)
    finally:
        try:
            if "path" in locals() and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

def main():
    # Настраиваем cookies при старте
    setup_cookies()
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Бот запущен…")
    app.run_polling()

if __name__ == "__main__":
    main(
