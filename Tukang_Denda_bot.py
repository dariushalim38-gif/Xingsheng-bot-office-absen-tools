import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = "8716960621:AAG7cFdVeb0Tio7lBBMoUSfiH32VpCqjfL8"
logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot hidup! Silakan gunakan perintah /WC, /rokok, dll. (fitur lengkap sedang diperbaiki)")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    print("Bot berjalan...")
    app.run_polling()

if __name__ == "__main__":
    main()
