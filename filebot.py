from dotenv import load_dotenv
load_dotenv()
import os
import vobject
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
    CallbackQueryHandler
)

# Bot Token
TOKEN = os.getenv("BOT_TOKEN") or "7666117905:AAFxnfJ6lW7d1HducI9t2_1D1YYDzjqbcmo"

# Flask App for UptimeRobot ping
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot aktif!"

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# States
GET_BASE_NAME, GET_FILE, ASK_REPEAT = range(3)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Halo! Saya akan membantu membuat kontak VCF dari nomor telepon.
"
        "Silakan kirim nama dasar untuk kontak (contoh: 'Eky' akan menghasilkan 'Eky 1', 'Eky 2', dst)."
    )
    return GET_BASE_NAME

async def get_base_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['base_name'] = update.message.text.strip()
    await update.message.reply_text(
        f"Baik, nama dasar kontak: {context.user_data['base_name']}
"
        "Sekarang silakan kirim file TXT berisi nomor telepon (satu nomor per baris)."
    )
    return GET_FILE

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if 'base_name' not in context.user_data:
        await update.message.reply_text("Silakan mulai dengan perintah /start")
        return ConversationHandler.END

    file = await update.message.document.get_file()
    os.makedirs('downloads', exist_ok=True)
    user_id = update.message.from_user.id
    file_path = os.path.join('downloads', f"temp_{user_id}.txt")
    await file.download_to_drive(file_path)

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            phone_lines = [line.strip() for line in f.readlines() if line.strip()]

        if not phone_lines:
            await update.message.reply_text("File tidak berisi nomor telepon yang valid.")
            return GET_FILE

        contacts = []
        base_name = context.user_data['base_name']
        admin_count = 1
        navy_count = 1
        normal_count = 1

        for line in phone_lines:
            line_lower = line.lower()
            phone = ''.join(filter(str.isdigit, line))

            if 'admin' in line_lower:
                contact_name = f"admin {base_name} {admin_count}"
                admin_count += 1
            elif 'navy' in line_lower:
                contact_name = f"navy {base_name} {navy_count}"
                navy_count += 1
            else:
                contact_name = f"{base_name} {normal_count}"
                normal_count += 1

            contacts.append({
                'name': contact_name,
                'phone': phone
            })

        safe_base_name = ''.join(c if c.isalnum() or c in [' ', '_', '-'] else '_' for c in base_name)
        vcf_filename = f"{safe_base_name}.vcf"
        vcf_path = os.path.join('downloads', vcf_filename)
        create_vcf(contacts, vcf_path)

        await update.message.reply_text(f"Berhasil membuat {len(contacts)} kontak!")
        await update.message.reply_document(
            document=open(vcf_path, 'rb'),
            filename=vcf_filename,
            caption=f"File VCF dengan {len(contacts)} kontak"
        )

        if os.path.getsize(vcf_path) > 50000000:
            split_files = split_vcf(contacts, base_name)
            for idx, split_path in enumerate(split_files, 1):
                split_filename = os.path.basename(split_path)
                await update.message.reply_document(
                    document=open(split_path, 'rb'),
                    filename=split_filename,
                    caption=f"Bagian {idx} dari {len(split_files)}"
                )
                os.remove(split_path)

        keyboard = [
            [InlineKeyboardButton("Ya", callback_data="repeat_yes"),
             InlineKeyboardButton("Tidak", callback_data="repeat_no")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Apakah Anda ingin membuat VCF lagi?",
            reply_markup=reply_markup
        )

        if os.path.exists(file_path):
            os.remove(file_path)
        if os.path.exists(vcf_path):
            os.remove(vcf_path)

        return ASK_REPEAT

    except Exception as e:
        await update.message.reply_text(f"Terjadi kesalahan: {str(e)}")
        if os.path.exists(file_path):
            os.remove(file_path)
        context.user_data.clear()
        return ConversationHandler.END

async def handle_repeat_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "repeat_yes":
        await query.edit_message_text(text="Silakan kirim nama dasar untuk kontak baru.")
        return GET_BASE_NAME
    else:
        await query.edit_message_text(text="Terima kasih telah menggunakan layanan kami!")
        context.user_data.clear()
        return ConversationHandler.END

def create_vcf(contacts, output_path):
    with open(output_path, 'w', encoding='utf-8') as f:
        for contact in contacts:
            vcard = vobject.vCard()
            name_parts = contact['name'].split()
            given_name = ' '.join(name_parts[:-1]) if len(name_parts) > 1 else contact['name']
            family_name = name_parts[-1] if len(name_parts) > 1 else ''
            vcard.add('fn').value = contact['name']
            vcard.add('n').value = vobject.vcard.Name(family=family_name, given=given_name)
            tel = vcard.add('tel')
            tel.value = contact['phone']
            tel.type_param = 'CELL'
            f.write(vcard.serialize() + '\n')

def split_vcf(contacts, base_name, max_contacts=500):
    split_files = []
    safe_base_name = ''.join(c if c.isalnum() or c in [' ', '_', '-'] else '_' for c in base_name)
    chunks = [contacts[i:i + max_contacts] for i in range(0, len(contacts), max_contacts)]
    for idx, chunk in enumerate(chunks, 1):
        file_path = os.path.join('downloads', f"{safe_base_name}_part{idx}.vcf")
        create_vcf(chunk, file_path)
        split_files.append(file_path)
    return split_files

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Operasi dibatalkan.")
    context.user_data.clear()
    return ConversationHandler.END

def main():
    try:
        application = Application.builder().token(TOKEN).build()
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                GET_BASE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_base_name)],
                GET_FILE: [MessageHandler(filters.Document.TEXT, handle_document)],
                ASK_REPEAT: [CallbackQueryHandler(handle_repeat_choice)],
            },
            fallbacks=[CommandHandler('cancel', cancel)],
        )
        application.add_handler(conv_handler)
        print("Bot dimulai! Tekan Ctrl+C untuk menghentikan.")
        application.run_polling()
    except Exception as e:
        print(f"Terjadi kesalahan saat menjalankan bot: {str(e)}")

if __name__ == '__main__':
    threading.Thread(target=run_flask).start()
    main()
