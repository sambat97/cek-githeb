"""
Telegram Bot - GitHub Email Registration Checker
Bot menerima file .txt, cek email apakah terdaftar di GitHub,
lalu kirim hasilnya kembali ke user.

Deploy: Railway
"""

import os
import sys
import logging
import asyncio
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()
from io import BytesIO

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from github_checker_api import parse_entries, check_emails_batch

# ============ CONFIG ============
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("❌ BOT_TOKEN belum di-set! Set environment variable BOT_TOKEN.")
    sys.exit(1)

# ============ LOGGING ============
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ============ STATES ============
WAITING_FILE = 0

# Emoji mapping
STATUS_EMOJI = {
    "registered": "🔴",
    "available": "🟢",
    "invalid": "🟡",
    "error": "⚠️",
    "rate_limited": "⏳",
}

STATUS_LABEL = {
    "registered": "Terdaftar",
    "available": "Belum Terdaftar",
    "invalid": "Email Tidak Valid",
    "error": "Error",
    "rate_limited": "Rate Limited",
}


# ============ HANDLERS ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /start"""
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) memulai bot")

    await update.message.reply_text(
        f"👋 Halo <b>{user.first_name}</b>!\n\n"
        f"🔍 Bot ini mengecek apakah email sudah <b>terdaftar di GitHub</b> atau belum.\n\n"
        f"<b>Cara pakai:</b>\n"
        f"1️⃣ Langsung kirim file <code>.txt</code>\n"
        f"2️⃣ Tunggu bot selesai mengecek\n"
        f"3️⃣ Bot akan kirim file hasil\n\n"
        f"<b>Format file:</b>\n"
        f"<code>email@domain.com</code> (email saja)\n"
        f"<code>email@domain.com:password</code> (email + password)\n\n"
        f"📎 Langsung kirim file .txt kamu sekarang!",
        parse_mode="HTML",
    )


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /check — minta user upload file"""
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) mulai /check")

    await update.message.reply_text(
        "📄 Kirim file <code>.txt</code> kamu sekarang.\n\n"
        "Format:\n"
        "<code>email@domain.com</code> (email saja)\n"
        "<code>email@domain.com:password</code>\n\n"
        "⏳ Menunggu file...",
        parse_mode="HTML",
    )
    return WAITING_FILE


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler ketika user upload file .txt"""
    user = update.effective_user
    document = update.message.document

    # Validasi file
    if not document:
        await update.message.reply_text("❌ Kirim file .txt, bukan pesan teks!")
        return WAITING_FILE

    if not document.file_name.endswith(".txt"):
        await update.message.reply_text(
            "❌ File harus berformat <code>.txt</code>!\n"
            "Kirim ulang file yang benar.",
            parse_mode="HTML",
        )
        return WAITING_FILE

    logger.info(
        f"User {user.id} ({user.username}) upload file: {document.file_name} "
        f"({document.file_size} bytes)"
    )

    # Download file
    file = await document.get_file()
    file_bytes = await file.download_as_bytearray()
    text_content = file_bytes.decode("utf-8", errors="ignore")

    # Parse entries
    entries = parse_entries(text_content)

    if not entries:
        await update.message.reply_text(
            "❌ Tidak ada email valid ditemukan di file!\n\n"
            "Pastikan format:\n"
            "<code>email@domain.com</code> atau\n"
            "<code>email@domain.com:password</code>",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    total = len(entries)

    # Kirim pesan awal
    status_msg = await update.message.reply_text(
        f"✅ Ditemukan <b>{total}</b> email.\n"
        f"⏳ Mulai mengecek...\n\n"
        f"<code>Progress: 0/{total} (0%)</code>",
        parse_mode="HTML",
    )

    # Kumpulkan hasil per email untuk ditampilkan live
    result_lines = []
    last_edit_time = [0]

    async def progress_callback(current, total_count, email, result):
        emoji = STATUS_EMOJI.get(result, "⚪")
        label = STATUS_LABEL.get(result, "Unknown")

        # Tambahkan ke result lines
        result_lines.append(f"{emoji} <code>{email}</code> — {label}")

        # Update pesan setiap email, tapi max 1x per 1.5 detik (anti rate limit Telegram)
        import time
        now = time.time()
        if now - last_edit_time[0] >= 1.5 or current == total_count:
            last_edit_time[0] = now
            pct = int((current / total_count) * 100)

            # Tampilkan max 15 hasil terakhir supaya pesan tidak terlalu panjang
            visible_lines = result_lines[-15:]
            if len(result_lines) > 15:
                hidden = len(result_lines) - 15
                lines_text = f"<i>...{hidden} hasil sebelumnya...</i>\n" + "\n".join(visible_lines)
            else:
                lines_text = "\n".join(visible_lines)

            try:
                await status_msg.edit_text(
                    f"⏳ Mengecek... <b>{current}/{total_count}</b> ({pct}%)\n\n"
                    f"{lines_text}",
                    parse_mode="HTML",
                )
            except Exception:
                pass

    # Jalankan pengecekan
    results = await check_emails_batch(entries, progress_callback=progress_callback)

    # Hitung hasil
    reg_count = len(results["registered"])
    avail_count = len(results["available"])
    inv_count = len(results["invalid"])
    err_count = len(results["error"])

    # Kirim ringkasan final
    summary = (
        f"✅ <b>Pengecekan Selesai!</b>\n\n"
        f"📊 <b>Hasil:</b>\n"
        f"🟢 Belum Terdaftar: <b>{avail_count}</b>\n"
        f"🔴 Sudah Terdaftar: <b>{reg_count}</b>\n"
    )
    if inv_count > 0:
        summary += f"🟡 Email Tidak Valid: <b>{inv_count}</b>\n"
    if err_count > 0:
        summary += f"⚠️ Error: <b>{err_count}</b>\n"
    summary += f"\n📁 Total: <b>{total}</b> email"

    await status_msg.edit_text(summary, parse_mode="HTML")

    # Kirim file hasil — Registered
    if results["registered"]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        reg_content = f"# Email SUDAH TERDAFTAR di GitHub\n"
        reg_content += f"# Total: {reg_count}\n"
        reg_content += f"# Tanggal: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        reg_content += "\n".join(results["registered"])

        reg_bytes = BytesIO(reg_content.encode("utf-8"))
        reg_bytes.name = f"registered_{timestamp}.txt"
        await update.message.reply_document(
            document=reg_bytes,
            caption=f"🔴 Email yang SUDAH TERDAFTAR ({reg_count})",
        )

    # Kirim file hasil — Available
    if results["available"]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        avail_content = f"# Email BELUM TERDAFTAR di GitHub\n"
        avail_content += f"# Total: {avail_count}\n"
        avail_content += f"# Tanggal: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        avail_content += "\n".join(results["available"])

        avail_bytes = BytesIO(avail_content.encode("utf-8"))
        avail_bytes.name = f"available_{timestamp}.txt"
        await update.message.reply_document(
            document=avail_bytes,
            caption=f"🟢 Email yang BELUM TERDAFTAR ({avail_count})",
        )

    # Kirim file hasil — Invalid + Error (jika ada)
    if results["invalid"] or results["error"]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        other_content = ""
        if results["invalid"]:
            other_content += f"# Email TIDAK VALID\n"
            other_content += "\n".join(results["invalid"])
            other_content += "\n\n"
        if results["error"]:
            other_content += f"# Email ERROR (gagal dicek)\n"
            other_content += "\n".join(results["error"])

        other_bytes = BytesIO(other_content.encode("utf-8"))
        other_bytes.name = f"errors_{timestamp}.txt"
        await update.message.reply_document(
            document=other_bytes,
            caption=f"⚠️ Email Error/Invalid ({inv_count + err_count})",
        )

    logger.info(
        f"User {user.id} selesai cek {total} email: "
        f"registered={reg_count}, available={avail_count}, "
        f"invalid={inv_count}, error={err_count}"
    )

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /cancel"""
    await update.message.reply_text("❌ Dibatalkan. Kirim file .txt untuk mulai lagi.")
    return ConversationHandler.END


async def handle_direct_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk file yang dikirim langsung tanpa /check"""
    await handle_file(update, context)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /help"""
    await update.message.reply_text(
        "📖 <b>Panduan Bot GitHub Checker</b>\n\n"
        "<b>Cara pakai:</b>\n"
        "Langsung kirim file <code>.txt</code> ke bot!\n\n"
        "<b>Format file:</b>\n"
        "<code>email@domain.com</code> (email saja)\n"
        "<code>email@domain.com:password</code> (email + password)\n\n"
        "<b>Perintah:</b>\n"
        "/start — Pesan selamat datang\n"
        "/check — Mulai cek (upload file .txt)\n"
        "/cancel — Batalkan proses\n"
        "/help — Bantuan",
        parse_mode="HTML",
    )


def main():
    """Start the bot."""
    logger.info("🚀 Starting GitHub Checker Bot...")

    # Build application
    app = Application.builder().token(BOT_TOKEN).build()

    # Conversation handler untuk /check -> upload file
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("check", check_command)],
        states={
            WAITING_FILE: [
                MessageHandler(filters.Document.ALL, handle_file),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(conv_handler)
    # Handler untuk file yang dikirim langsung (tanpa /check)
    app.add_handler(MessageHandler(filters.Document.ALL, handle_direct_file))

    # Run bot
    logger.info("✅ Bot is running! Waiting for messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
