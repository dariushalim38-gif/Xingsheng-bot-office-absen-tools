import asyncio
import sqlite3
import logging
import random
from datetime import datetime, timedelta
from typing import Dict, List

from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = "8716960621:AAG7cFdVeb0Tio7lBBMoUSfiH32VpCqjfL8"
ADMIN_IDS = [7938242756, 8226764474, 6071806272]

JAM_KERJA_MULAI = "10:00"
ISTIRAHAT_1_MULAI = "11:00"
ISTIRAHAT_1_SELESAI = "12:00"
ISTIRAHAT_2_MULAI = "17:00"
ISTIRAHAT_2_SELESAI = "18:00"
JAM_PULANG = "22:00"

UCAPAN_PULANG_LIST = ["✨ Kerja keras hari ini cukup ✨", "🚀 Pamit dulu, beban berat 😅", "😌 Hati lega, kerjaan beres", "🏃 Jalan-jalan ke Semanggi", "🎉 Saat melihat jam pulang, hatiku lega"]
UCAPAN_TELAT_PAGI = ["🌅 Matahari sudah tinggi", "⏰ Telat nih", "🔔 Alarmnya disetel lebih awal"]
UCAPAN_NYANYI = ["🎤 Nyiurin @{} : 'Balonku ada lima...'", "🎶 @{} dinyanyiin: 'Halo-halo Bandung'", "🎼 Untuk @{}: 'Ibu kita Kartini'"]
DEFAULT_DURASI_WC = 10
DEFAULT_DURASI_ROKOK = 5
MAX_IZIN_PER_HARI = 6
DB_PATH = "absen_bot.db"
logging.basicConfig(level=logging.INFO)

def parse_time(t): return datetime.strptime(t, "%H:%M").time()
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER UNIQUE, username TEXT, first_name TEXT, last_name TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS absensi (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, tanggal TEXT, shift TEXT, waktu_masuk TEXT, status TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS izin_aktif (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, jenis TEXT, start_time TEXT, expected_end_time TEXT, chat_id INTEGER, durasi_menit INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS counter_harian (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, tanggal TEXT, jenis TEXT, jumlah INTEGER, UNIQUE(user_id, tanggal, jenis))''')
    c.execute('''CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER UNIQUE, chat_type TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pulang_log (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, tanggal TEXT, UNIQUE(chat_id, tanggal))''')
    conn.commit()
    conn.close()

def get_or_create_user(u):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE telegram_id = ?", (u.id,))
    row = c.fetchone()
    if row: uid = row[0]
    else:
        c.execute("INSERT INTO users (telegram_id, username, first_name, last_name) VALUES (?, ?, ?, ?)", (u.id, u.username, u.first_name, u.last_name))
        uid = c.lastrowid
        conn.commit()
    conn.close()
    return uid

def sudah_absen(uid, tanggal, shift):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM absensi WHERE user_id = ? AND tanggal = ? AND shift = ?", (uid, tanggal, shift))
    ok = c.fetchone() is not None
    conn.close()
    return ok

def catat_absen(uid, tanggal, shift, waktu, status):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO absensi (user_id, tanggal, shift, waktu_masuk, status) VALUES (?, ?, ?, ?, ?)", (uid, tanggal, shift, waktu, status))
    conn.commit()
    conn.close()

def register_chat(cid, ctype):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO chats (chat_id, chat_type) VALUES (?, ?)", (cid, ctype))
    conn.commit()
    conn.close()

def get_all_chats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT chat_id FROM chats")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def sudah_kirim_pulang_today(cid, tgl):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM pulang_log WHERE chat_id = ? AND tanggal = ?", (cid, tgl))
    ok = c.fetchone() is not None
    conn.close()
    return ok

def catat_kirim_pulang(cid, tgl):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO pulang_log (chat_id, tanggal) VALUES (?, ?)", (cid, tgl))
    conn.commit()
    conn.close()

def get_izin_count(uid, tgl, jenis):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT jumlah FROM counter_harian WHERE user_id = ? AND tanggal = ? AND jenis = ?", (uid, tgl, jenis))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def increment_izin_count(uid, tgl, jenis):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO counter_harian (user_id, tanggal, jenis, jumlah) VALUES (?, ?, ?, 1) ON CONFLICT(user_id, tanggal, jenis) DO UPDATE SET jumlah = jumlah + 1", (uid, tgl, jenis))
    conn.commit()
    conn.close()

def reset_counter_hari_ini_admin(tgl):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM counter_harian WHERE tanggal = ?", (tgl,))
    c.execute("DELETE FROM izin_aktif")
    conn.commit()
    conn.close()

def get_active_izin(uid):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, jenis, expected_end_time, chat_id, durasi_menit FROM izin_aktif WHERE user_id = ? ORDER BY start_time DESC LIMIT 1", (uid,))
    row = c.fetchone()
    conn.close()
    return row

def add_active_izin(uid, jenis, start, end, chat_id, durasi):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO izin_aktif (user_id, jenis, start_time, expected_end_time, chat_id, durasi_menit) VALUES (?, ?, ?, ?, ?, ?)", (uid, jenis, start.isoformat(), end.isoformat(), chat_id, durasi))
    izin_id = c.lastrowid
    conn.commit()
    conn.close()
    return izin_id

def remove_active_izin(izin_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM izin_aktif WHERE id = ?", (izin_id,))
    conn.commit()
    conn.close()

active_timers = {}

async def schedule_reminder(app, chat_id, user_id, username, jenis, durasi, izin_id, delay):
    async def reminder():
        await asyncio.sleep(delay)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id FROM izin_aktif WHERE id = ?", (izin_id,))
        row = c.fetchone()
        conn.close()
        if row:
            mention = f"@{username}" if username else f"User {user_id}"
            await app.bot.send_message(chat_id=chat_id, text=f"{mention} ⏰ {jenis} {durasi} menit habis! Selesaikan segera.")
    task = asyncio.create_task(reminder())
    active_timers[user_id] = task

async def restore_timers(app):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT izin.id, izin.jenis, izin.expected_end_time, izin.durasi_menit, izin.chat_id, users.telegram_id, users.username
                 FROM izin_aktif izin JOIN users ON izin.user_id = users.id''')
    rows = c.fetchall()
    for izin_id, jenis, exp_str, durasi, chat_id, tgid, username in rows:
        exp = datetime.fromisoformat(exp_str)
        now = datetime.now()
        if exp > now:
            sisa = (exp - now).total_seconds()
            await schedule_reminder(app, chat_id, tgid, username, jenis, durasi, izin_id, sisa)
    conn.close()

async def cmd_izin(update, context, jenis, default_dur, nama_izin, emoji):
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat: return
    uid = get_or_create_user(user)
    tgl = datetime.now().strftime("%Y-%m-%d")
    used = get_izin_count(uid, tgl, jenis)
    if used >= MAX_IZIN_PER_HARI:
        await update.message.reply_text(f"{emoji} Kuota {nama_izin} habis (max {MAX_IZIN_PER_HARI}x).")
        return
    aktif = get_active_izin(uid)
    if aktif:
        await update.message.reply_text(f"⚠️ Masih ada izin {aktif[1]} aktif. Selesaikan dulu.")
        return
    args = context.args
    durasi = default_dur
    if args and args[0].isdigit():
        durasi = int(args[0])
        if durasi <= 0:
            await update.message.reply_text("Durasi harus positif.")
            return
    start = datetime.now()
    end = start + timedelta(minutes=durasi)
    izin_id = add_active_izin(uid, jenis, start, end, chat.id, durasi)
    mention = f"@{user.username}" if user.username else user.first_name
    await update.message.reply_text(
        f"{mention} {emoji} {nama_izin} {durasi} menit mulai {start.strftime('%H:%M')}. Selesai maksimal {end.strftime('%H:%M')}.\n"
        f"Sisa kuota hari ini: {MAX_IZIN_PER_HARI - used -1}/{MAX_IZIN_PER_HARI}\n"
        f"Selesai? /selesai_{jenis}"
    )
    if user.id in active_timers:
        if not active_timers[user.id].done():
            active_timers[user.id].cancel()
        del active_timers[user.id]
    await schedule_reminder(context.application, chat.id, user.id, user.username, nama_izin, durasi, izin_id, durasi*60)
    increment_izin_count(uid, tgl, jenis)

async def cmd_WC(update, context): await cmd_izin(update, context, "WC", DEFAULT_DURASI_WC, "WC 🚽", "🚽")
async def cmd_rokok(update, context): await cmd_izin(update, context, "rokok", DEFAULT_DURASI_ROKOK, "rokok 🚬", "🚬")

async def cmd_selesai(update, context, jenis, nama_izin):
    user = update.effective_user
    uid = get_or_create_user(user)
    aktif = get_active_izin(uid)
    if not aktif:
        await update.message.reply_text("Tidak ada izin aktif.")
        return
    izin_id, aktif_jenis, exp_str, chat_id, dur = aktif
    if aktif_jenis != jenis:
        await update.message.reply_text(f"Anda sedang izin {aktif_jenis}, bukan {nama_izin}.")
        return
    exp = datetime.fromisoformat(exp_str)
    now = datetime.now()
    if now > exp:
        selisih = int((now - exp).total_seconds() // 60)
        await update.message.reply_text(f"⚠️ Melebihi batas {selisih} menit. Pelanggaran tercatat.")
    else:
        await update.message.reply_text(f"✅ {nama_izin.capitalize()} selesai tepat waktu.")
    remove_active_izin(izin_id)
    if user.id in active_timers:
        if not active_timers[user.id].done():
            active_timers[user.id].cancel()
        del active_timers[user.id]

async def cmd_selesai_WC(update, context): await cmd_selesai(update, context, "WC", "WC")
async def cmd_selesai_rokok(update, context): await cmd_selesai(update, context, "rokok", "rokok")

async def cmd_reset_hari_ini(update, context):
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Hanya admin.")
        return
    tgl = datetime.now().strftime("%Y-%m-%d")
    reset_counter_hari_ini_admin(tgl)
    for uid, task in list(active_timers.items()):
        if not task.done(): task.cancel()
    active_timers.clear()
    await update.message.reply_text(f"✅ Data {tgl} direset, izin aktif dibatalkan.")

async def cmd_nyanyi(update, context):
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Hanya admin.")
        return
    if not context.args:
        await update.message.reply_text("/nyanyi @username")
        return
    target = context.args[0].lstrip('@')
    await update.message.reply_text(random.choice(UCAPAN_NYANYI).format(target))

async def cmd_start(update, context):
    chat = update.effective_chat
    if chat: register_chat(chat.id, chat.type)
    await update.message.reply_text(
        "🌟 Bot Absen & Denda 🌟\n\n"
        "/Absen_Pagi – Absen pagi (10:00)\n"
        "/istirahat_siang_mulai – Mulai siang (11-12)\n"
        "/absen_istirahat_siang – Kembali siang\n"
        "/istirahat_sore_mulai – Mulai sore (17-18)\n"
        "/absen_istirahat_sore – Kembali sore\n"
        "/WC 🚽 – Izin WC (10 menit, max 6/hari)\n"
        "/rokok 🚬 – Izin rokok (5 menit, max 6/hari)\n"
        "/selesai_WC – Selesai WC\n"
        "/selesai_rokok – Selesai rokok\n"
        "/pulang – Pulang (≥22:00)\n"
        "/laporan_bulanan – Laporan admin\n"
        "/nyanyi @user – Admin\n"
        "/reset_hari_ini – Admin"
    )

async def cmd_Absen_Pagi(update, context):
    user = update.effective_user
    if not user: return
    uid = get_or_create_user(user)
    now = datetime.now()
    tgl = now.strftime("%Y-%m-%d")
    jam_kerja = parse_time(JAM_KERJA_MULAI)
    jam_sekarang = now.time()
    status = "telat" if jam_sekarang > jam_kerja else "tepat"
    if sudah_absen(uid, tgl, "pagi"):
        await update.message.reply_text("⚠️ Sudah absen pagi.")
        return
    catat_absen(uid, tgl, "pagi", now.isoformat(), status)
    msg = f"✅ Absen pagi: {now.strftime('%H:%M:%S')} – {status.upper()}"
    if status == "telat":
        telat = int((now - datetime.combine(now.date(), jam_kerja)).total_seconds() // 60)
        msg += f"\n⚠️ Telat {telat} menit! {random.choice(UCAPAN_TELAT_PAGI)}"
    await update.message.reply_text(msg)

async def cmd_mulai_istirahat(update, context, shift, mulai_str, selesai_str, nama):
    user = update.effective_user
    now = datetime.now()
    tgl = now.strftime("%Y-%m-%d")
    mulai = parse_time(mulai_str)
    selesai = parse_time(selesai_str)
    jam = now.time()
    if jam < mulai or jam >= selesai:
        await update.message.reply_text(f"❌ {nama} hanya antara {mulai_str} – {selesai_str}.")
        return
    if sudah_absen(get_or_create_user(user), tgl, shift):
        await update.message.reply_text(f"⚠️ Sudah absen {nama}.")
        return
    catat_absen(get_or_create_user(user), tgl, shift, now.isoformat(), "tepat")
    await update.message.reply_text(f"✅ {nama} mulai: {now.strftime('%H:%M:%S')}")

async def cmd_istirahat_siang_mulai(update, context): await cmd_mulai_istirahat(update, context, "siang_mulai", ISTIRAHAT_1_MULAI, ISTIRAHAT_1_SELESAI, "Istirahat siang")
async def cmd_istirahat_sore_mulai(update, context): await cmd_mulai_istirahat(update, context, "sore_mulai", ISTIRAHAT_2_MULAI, ISTIRAHAT_2_SELESAI, "Istirahat sore")

async def cmd_kembali(update, context, shift, selesai_str, nama):
    user = update.effective_user
    now = datetime.now()
    tgl = now.strftime("%Y-%m-%d")
    selesai = parse_time(selesai_str)
    jam = now.time()
    if jam > selesai:
        status = "telat"
        telat = int((now - datetime.combine(now.date(), selesai)).total_seconds() // 60)
        await update.message.reply_text(f"⚠️ Telat {nama} {telat} menit.")
    else:
        status = "tepat"
    if sudah_absen(get_or_create_user(user), tgl, shift):
        await update.message.reply_text(f"⚠️ Sudah absen {nama}.")
        return
    catat_absen(get_or_create_user(user), tgl, shift, now.isoformat(), status)
    await update.message.reply_text(f"✅ {nama}: {now.strftime('%H:%M:%S')} – {status.upper()}")

async def cmd_absen_siang(update, context): await cmd_kembali(update, context, "siang", ISTIRAHAT_1_SELESAI, "Kembali siang")
async def cmd_absen_sore(update, context): await cmd_kembali(update, context, "sore", ISTIRAHAT_2_SELESAI, "Kembali sore")

async def cmd_pulang(update, context):
    now = datetime.now()
    jam_pulang = parse_time(JAM_PULANG)
    if now.time() < jam_pulang:
        await update.message.reply_text(f"❌ Pulang jam {JAM_PULANG}.")
    else:
        await update.message.reply_text(f"🎉 Pulang! {random.choice(UCAPAN_PULANG_LIST)}")

async def cmd_laporan_bulanan(update, context):
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Hanya admin.")
        return
    args = context.args
    if len(args) >= 2:
        tahun, bulan = int(args[0]), int(args[1])
    else:
        skrg = datetime.now()
        tahun, bulan = skrg.year, skrg.month
    start = f"{tahun}-{bulan:02d}-01"
    end = f"{tahun+1}-01-01" if bulan == 12 else f"{tahun}-{bulan+1:02d}-01"
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, telegram_id, username, first_name FROM users")
    users = c.fetchall()
    laporan = f"📊 Laporan {tahun}-{bulan:02d}\n\n"
    for uid, _, username, first in users:
        nama = username or first
        c.execute("SELECT COUNT(*) FROM absensi WHERE user_id=? AND tanggal>=? AND tanggal<? AND shift='pagi' AND status='telat'", (uid, start, end))
        telat = c.fetchone()[0]
        c.execute("SELECT SUM(jumlah) FROM counter_harian WHERE user_id=? AND tanggal>=? AND tanggal<? AND jenis='WC'", (uid, start, end))
        wc = c.fetchone()[0] or 0
        c.execute("SELECT SUM(jumlah) FROM counter_harian WHERE user_id=? AND tanggal>=? AND tanggal<? AND jenis='rokok'", (uid, start, end))
        rokok = c.fetchone()[0] or 0
        laporan += f"👤 {nama}\n   Telat: {telat}\n   WC: {wc}\n   Rokok: {rokok}\n\n"
    conn.close()
    await update.message.reply_text(laporan)

async def daily_pulang_checker(app):
    while True:
        now = datetime.now()
        jam_pulang = parse_time(JAM_PULANG)
        if now.hour == jam_pulang.hour and now.minute == jam_pulang.minute:
            tgl = now.strftime("%Y-%m-%d")
            for cid in get_all_chats():
                if not sudah_kirim_pulang_today(cid, tgl):
                    await app.bot.send_message(chat_id=cid, text=f"🎉 Pulang kerja! {random.choice(UCAPAN_PULANG_LIST)}")
                    catat_kirim_pulang(cid, tgl)
        await asyncio.sleep(60)

async def set_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Mulai"),
        BotCommand("Absen_Pagi", "Absen pagi 10:00"),
        BotCommand("istirahat_siang_mulai", "Mulai siang 11:00"),
        BotCommand("absen_istirahat_siang", "Kembali siang max 12:00"),
        BotCommand("istirahat_sore_mulai", "Mulai sore 17:00"),
        BotCommand("absen_istirahat_sore", "Kembali sore max 18:00"),
        BotCommand("WC", "Izin WC 🚽"),
        BotCommand("rokok", "Izin rokok 🚬"),
        BotCommand("selesai_WC", "Selesai WC"),
        BotCommand("selesai_rokok", "Selesai rokok"),
        BotCommand("pulang", "Pulang kerja ≥22:00"),
        BotCommand("laporan_bulanan", "Laporan admin"),
        BotCommand("nyanyi", "Admin nyanyi"),
        BotCommand("reset_hari_ini", "Admin reset data"),
    ])

def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("Absen_Pagi", cmd_Absen_Pagi))
    app.add_handler(CommandHandler("istirahat_siang_mulai", cmd_istirahat_siang_mulai))
    app.add_handler(CommandHandler("absen_istirahat_siang", cmd_absen_siang))
    app.add_handler(CommandHandler("istirahat_sore_mulai", cmd_istirahat_sore_mulai))
    app.add_handler(CommandHandler("absen_istirahat_sore", cmd_absen_sore))
    app.add_handler(CommandHandler("WC", cmd_WC))
    app.add_handler(CommandHandler("rokok", cmd_rokok))
    app.add_handler(CommandHandler("selesai_WC", cmd_selesai_WC))
    app.add_handler(CommandHandler("selesai_rokok", cmd_selesai_rokok))
    app.add_handler(CommandHandler("pulang", cmd_pulang))
    app.add_handler(CommandHandler("laporan_bulanan", cmd_laporan_bulanan))
    app.add_handler(CommandHandler("nyanyi", cmd_nyanyi))
    app.add_handler(CommandHandler("reset_hari_ini", cmd_reset_hari_ini))

    async def post_init(app):
        await restore_timers(app)
        await set_commands(app)
        asyncio.create_task(daily_pulang_checker(app))

    app.post_init = post_init
    print("🚀 Bot aktif")
    app.run_polling()

if __name__ == "__main__":
    main()