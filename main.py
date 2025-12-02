import os
import asyncio
import math
import time
from datetime import datetime
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import Config
from database import *
from helper import *
from shortener import shorten
import logging

# Optional NSFW classifier
NSFW_CLASSIFIER = None
if Config.USE_NSFW:
    try:
        from nudenet import NudeClassifier
        NSFW_CLASSIFIER = NudeClassifier()
    except Exception:
        NSFW_CLASSIFIER = None

# ensure dirs
ensure_dirs()

# logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Client("rename_bot",
             api_id=Config.API_ID,
             api_hash=Config.API_HASH,
             bot_token=Config.BOT_TOKEN,
             workdir=".")

# Inline buttons used across flows
def main_buttons():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏ Rename", callback_data="act_rename"),
         InlineKeyboardButton("🗜 Compress", callback_data="act_compress")],
        [InlineKeyboardButton("✂ Split", callback_data="act_split"),
         InlineKeyboardButton("📸 Set Thumb", callback_data="act_setthumb")],
        [InlineKeyboardButton("⚙️ Save Caption", callback_data="act_save_caption"),
         InlineKeyboardButton("❌ Cancel", callback_data="act_cancel")]
    ])

# Force-subscribe check
async def force_sub_check(msg):
    if not Config.FS_CHANNEL_ID:
        return False
    try:
        member = await app.get_chat_member(Config.FS_CHANNEL_ID, msg.from_user.id)
        if member.status in (enums.ChatMemberStatus.MEMBER, enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
            return False
    except Exception:
        pass
    # send join prompt
    try:
        chat = await app.get_chat(Config.FS_CHANNEL_ID)
        url = f"https://t.me/{chat.username}" if chat.username else f"https://t.me/c/{str(Config.FS_CHANNEL_ID)[4:]}"
    except Exception:
        url = "https://t.me/{}".format(Config.FS_CHANNEL_ID)
    await msg.reply_text("⚠️ Please join our channel to use this bot.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Join Channel", url=url)]]))
    return True

# START
@app.on_message(filters.private & filters.command("start"))
async def start_handler(_, message):
    if await force_sub_check(message): return
    ensure_user(message.from_user.id)
    await message.reply_text(
        "👋 Send a file and choose an action.\n"
        "Use /me to view quota. Admins use /broadcast, /setlimit, /promote, /demote.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Help", callback_data="help")]])
    )

@app.on_callback_query(filters.regex("^help$"))
async def help_cb(_, callback):
    await callback.message.edit(
        "Send a file → choose action: Rename / Compress / Split / Set Thumb / Save Caption.\n"
        "Commands:\n"
        "/me - show quota\n"
        "/setlimit <id> <limit> - (admin)\n"
        "/broadcast <message> - (admin)\n"
        "/promote <id> - (admin)\n"
        "/demote <id> - (admin)\n"
    )

# Save thumbnail command
@app.on_message(filters.private & filters.command("thumbnail"))
async def ask_thumbnail(_, message):
    if await force_sub_check(message): return
    await message.reply_text("Send the image you want to save as your default thumbnail (will be used for uploads).")

@app.on_message(filters.private & filters.photo)
async def save_thumb(_, message):
    # Save per-user thumb
    ensure_user(message.from_user.id)
    path = os.path.join(Config.THUMB_DIR, f"{message.from_user.id}.jpg")
    await app.download_media(message.photo.file_id, file_name=path)
    set_thumb(message.from_user.id, path)
    await message.reply_text("✅ Thumbnail saved.")

# When a file arrives, show inline menu (reply)
@app.on_message(filters.private & (filters.document | filters.video | filters.audio | filters.photo))
async def file_handler(_, message):
    if await force_sub_check(message): return
    ensure_user(message.from_user.id)
    # optional extension filter (not implemented here)
    await message.reply_text("Choose an action for this file:", reply_markup=main_buttons(), quote=True)

# Callback handler to route actions
@app.on_callback_query()
async def callback_router(_, callback):
    data = callback.data
    user_id = callback.from_user.id
    ensure_user(user_id)
    udoc = users.find_one({"_id": user_id})
    reset_if_needed(udoc)

    # must be reply to a file message
    if not callback.message.reply_to_message:
        await callback.answer("Reply must be to a file message.", show_alert=True)
        return

    file_msg = callback.message.reply_to_message
    media = file_msg.document or file_msg.video or file_msg.audio or file_msg.photo
    if not media:
        await callback.answer("Invalid media.", show_alert=True)
        return

    # cancel
    if data == "act_cancel":
        await callback.message.edit("Cancelled.")
        await callback.answer()
        return

    # set thumb
    if data == "act_setthumb":
        await callback.message.reply_text("Send /thumbnail and then the image. Or just send the image now.")
        await callback.answer()
        return

    # save caption
    if data == "act_save_caption":
        await callback.message.reply_text("Reply to this message with the caption text you'd like saved as your default caption.")
        await callback.answer()
        return

    # For operations that produce an upload, check daily limit (unless admin or premium)
    if data in ("act_rename","act_compress","act_split"):
        udoc = users.find_one({"_id": user_id})
        reset_if_needed(udoc)
        if udoc.get("daily_count",0) >= udoc.get("limit", Config.DEFAULT_DAILY_LIMIT) and not udoc.get("is_admin", False) and not udoc.get("premium", False):
            await callback.answer("🚫 Daily limit reached. Ask admin to increase your limit or purchase premium.", show_alert=True)
            return

    # rename flow prompt
    if data == "act_rename":
        await callback.message.reply_text("✍ Send the desired filename (without extension) as a reply to this message.")
        await callback.answer()
        return

    # compress prompt
    if data == "act_compress":
        await callback.message.reply_text("🗜 Reply with the word `compress` to create a zip of the file and send it.")
        await callback.answer()
        return

    # split prompt
    if data == "act_split":
        await callback.message.reply_text(f"✂ Reply with the word `split` to split the file into {Config.SPLIT_SIZE_MB}MB chunks.")
        await callback.answer()
        return

    await callback.answer()

# Helper: quick NSFW check
async def is_safe_media(file_msg):
    if not Config.USE_NSFW:
        return True
    # Basic filename filter
    fname = getattr(file_msg, "document", None) and file_msg.document.file_name or ""
    if any(k in (fname or "").lower() for k in ("porn","xxx","adult","nsfw")):
        return False
    # If NSFW classifier available, try visual check for photos or thumbnails
    if NSFW_CLASSIFIER:
        try:
            preview = None
            if file_msg.photo:
                preview = await app.download_media(file_msg.photo.file_id, file_name=os.path.join(Config.TMP_DIR, f"nsfw_{file_msg.message_id}.jpg"))
            else:
                thumb = getattr(file_msg, "thumbnail", None)
                if thumb:
                    preview = await app.download_media(thumb.file_id, file_name=os.path.join(Config.TMP_DIR, f"nsfw_{file_msg.message_id}.jpg"))
            if preview:
                res = NSFW_CLASSIFIER.classify(preview)
                # nudenet returns dict path->{'safe':p, 'unsafe':q} or similar
                for r in res.values():
                    if isinstance(r, dict) and (r.get("unsafe",0) > 0.7 or r.get("porn",0) > 0.7):
                        try: os.remove(preview)
                        except: pass
                        return False
                try: os.remove(preview)
                except: pass
        except Exception:
            pass
    return True

# Text replies handler: receives rename/compress/split/caption saving commands as replies
@app.on_message(filters.private & filters.text & filters.reply)
async def text_reply(_, message):
    if await force_sub_check(message): return
    ensure_user(message.from_user.id)
    udoc = users.find_one({"_id": message.from_user.id})
    reset_if_needed(udoc)

    txt = message.text.strip()
    replied = message.reply_to_message
    file_msg = replied
    media = file_msg.document or file_msg.video or file_msg.audio or file_msg.photo
    if not media:
        # may be saving caption when replying to bot prompt
        if message.text and message.reply_to_message and "save as your default caption" in message.reply_to_message.text.lower():
            set_caption(message.from_user.id, message.text)
            await message.reply_text("✅ Default caption saved.")
        return

    # NSFW check
    if not await is_safe_media(file_msg):
        await message.reply_text("🚫 File flagged NSFW. Operation aborted.")
        return

    # Determine extension
    ext = ""
    if file_msg.photo:
        ext = ".jpg"
    else:
        ext = os.path.splitext(getattr(media, "file_name", "") or "")[1]

    # If user typed 'compress' or 'split', run those flows
    if txt.lower() == "compress":
        status = await message.reply_text("⏳ Compressing: downloading file...")
        # download
        local = await app.download_media(file_msg, file_name=os.path.join(Config.TMP_DIR, f"{file_msg.message_id}_orig"))
        zip_path = os.path.join(Config.TMP_DIR, f"{file_msg.message_id}.zip")
        try:
            from helper import zip_file
            zip_file(local, zip_path)
        except Exception:
            # fallback manual zip
            import zipfile
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                arcname = getattr(media,"file_name", f"file_{file_msg.message_id}")
                zf.write(local, arcname=arcname)
        size_mb = os.path.getsize(zip_path)/(1024*1024)
        if size_mb <= Config.MAX_UPLOAD_MB:
            sent = await app.send_document(chat_id=message.chat.id, document=zip_path, caption=f"🗜 Compressed: {os.path.basename(zip_path)}")
            increment_count(message.from_user.id)
            log_action({"user": message.from_user.id, "action":"compress", "file": os.path.basename(zip_path)})
            # generate short link to message (works if bot message visible public)
            try:
                link = f"https://t.me/{Config.BOT_USERNAME}/{sent.message_id}"
                short = shorten(link)
                await message.reply_text(f"🔗 Short link: {short}")
            except Exception:
                pass
            await status.delete()
            # cleanup
            try: os.remove(local)
            except: pass
            try: os.remove(zip_path)
            except: pass
            return
        else:
            # split zip
            parts = split_file(zip_path, Config.SPLIT_SIZE_MB*1024*1024)
            await message.reply_text(f"✂ Sending {len(parts)} parts...")
            for i,p in enumerate(parts, start=1):
                await app.send_document(chat_id=message.chat.id, document=p, caption=f"Part {i}/{len(parts)}")
                await asyncio.sleep(0.6)
            increment_count(message.from_user.id)
            log_action({"user": message.from_user.id, "action":"compress_split", "file": os.path.basename(zip_path), "parts": len(parts)})
            await status.delete()
            # cleanup
            for f in parts:
                try: os.remove(f)
                except: pass
            try: os.remove(local)
            except: pass
            try: os.remove(zip_path)
            except: pass
            return

    if txt.lower() == "split":
        status = await message.reply_text("✂ Splitting: downloading file...")
        local = await app.download_media(file_msg, file_name=os.path.join(Config.TMP_DIR, f"{file_msg.message_id}_orig"))
        parts = split_file(local, Config.SPLIT_SIZE_MB*1024*1024)
        for i,p in enumerate(parts, start=1):
            await app.send_document(chat_id=message.chat.id, document=p, caption=f"Part {i}/{len(parts)}")
            await asyncio.sleep(0.6)
        increment_count(message.from_user.id)
        log_action({"user": message.from_user.id, "action":"split", "file": os.path.basename(local), "parts": len(parts)})
        await status.delete()
        # cleanup
        for f in parts:
            try: os.remove(f)
            except: pass
        try: os.remove(local)
        except: pass
        return

    # Otherwise treat text as rename filename
    new_name = message.text.strip()
    final_name = f"{new_name}{ext}"
    progress_msg = await message.reply_text("⬇️ Downloading...")
    local_path = await app.download_media(file_msg, file_name=os.path.join(Config.TMP_DIR, final_name))
    await progress_msg.edit("⬆️ Uploading renamed file...")
    # load user thumb if exists
    udoc = users.find_one({"_id": message.from_user.id})
    thumb = udoc.get("thumb") if udoc else None
    # caption
    saved_caption = udoc.get("caption") if udoc else None
    caption_text = saved_caption or f"✅ Renamed: {final_name}"
    # srt hint: if .srt rename to keep same basename but .srt extension handling
    if final_name.lower().endswith(".srt"):
        # send as document preserving name
        sent = await app.send_document(chat_id=message.chat.id, document=local_path, caption=caption_text, thumb=thumb)
    else:
        sent = await app.send_document(chat_id=message.chat.id, document=local_path, caption=caption_text, thumb=thumb)
    # increment and log
    increment_count(message.from_user.id)
    log_action({"user": message.from_user.id, "action":"rename", "new_name": final_name, "size": os.path.getsize(local_path)})
    # build a share link and shorten it
    try:
        link = f"https://t.me/{Config.BOT_USERNAME}/{sent.message_id}"
        short = shorten(link)
        try:
            await message.reply_text(f"🔗 Short link: {short}")
        except:
            pass
    except Exception:
        pass

    await progress_msg.delete()
    try:
        os.remove(local_path)
    except:
        pass

# Admin commands
def admin_only(func):
    async def wrapper(_, message):
        uid = message.from_user.id
        ensure_user(uid)
        u = users.find_one({"_id": uid})
        if not u.get("is_admin", False):
            return await message.reply_text("🚫 Admins only.")
        return await func(_, message)
    return wrapper

@app.on_message(filters.private & filters.command("setlimit"))
@admin_only
async def cmd_setlimit(_, message):
    try:
        parts = message.text.split()
        target = int(parts[1]); lim = int(parts[2])
    except Exception:
        return await message.reply_text("Usage: /setlimit <user_id> <limit>")
    ensure_user(target)
    set_limit(target, lim)
    await message.reply_text(f"✅ Set limit for {target} to {lim}.")

@app.on_message(filters.private & filters.command("promote"))
@admin_only
async def cmd_promote(_, message):
    try:
        target = int(message.text.split()[1])
    except:
        return await message.reply_text("Usage: /promote <user_id>")
    ensure_user(target)
    set_admin(target, True)
    await message.reply_text(f"✅ Promoted {target} to admin.")

@app.on_message(filters.private & filters.command("demote"))
@admin_only
async def cmd_demote(_, message):
    try:
        target = int(message.text.split()[1])
    except:
        return await message.reply_text("Usage: /demote <user_id>")
    set_admin(target, False)
    await message.reply_text(f"✅ Demoted {target} from admin.")

@app.on_message(filters.private & filters.command("premium"))
@admin_only
async def cmd_premium(_, message):
    try:
        parts = message.text.split()
        target = int(parts[1]); flag = parts[2].lower() in ("1","true","yes","on")
    except:
        return await message.reply_text("Usage: /premium <user_id> <on/off>")
    set_premium(target, flag)
    await message.reply_text(f"✅ Premium set to {flag} for {target}.")

@app.on_message(filters.private & filters.command("broadcast"))
@admin_only
async def cmd_broadcast(_, message):
    # usage: /broadcast <text>
    txt = message.text.partition(" ")[2]
    if not txt:
        return await message.reply_text("Usage: /broadcast <message text>")
    await message.reply_text("Broadcast started...")
    count = 0
    cursor = users.find({}, {"_id":1})
    for u in cursor:
        uid = u["_id"]
        try:
            await app.send_message(uid, txt)
            count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            # skip unreachable
            await asyncio.sleep(0.05)
    await message.reply_text(f"Broadcast finished. Sent to {count} users.")
    log_action({"user": message.from_user.id, "action":"broadcast", "sent": count})

@app.on_message(filters.private & filters.command("me"))
async def cmd_me(_, message):
    ensure_user(message.from_user.id)
    u = users.find_one({"_id": message.from_user.id})
    reset_if_needed(u)
    await message.reply_text(f"Your daily usage: {u.get('daily_count',0)}/{u.get('limit', Config.DEFAULT_DAILY_LIMIT)}\nPremium: {u.get('premium',False)}\nAdmin: {u.get('is_admin',False)}")

# Run
if __name__ == "__main__":
    print("Starting Rename Bot...")
    app.run()
