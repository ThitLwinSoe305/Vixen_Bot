import asyncio
import logging
import os
import re
import threading
from urllib.parse import quote_plus
from flask import Flask
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient

_flask_app = Flask(__name__)

@_flask_app.route('/')
def _alive():
    return "I am alive!"

_port = int(os.environ.get("PORT", 8000))
threading.Thread(
    target=lambda: _flask_app.run(host='0.0.0.0', port=_port, use_reloader=False),
    daemon=True
).start()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

API_ID = int(os.environ.get("API_ID", 38738409))
API_HASH = os.environ.get("API_HASH", "5f2a2d513c80c5452f190f03d95976e2")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8635268994:AAEK1DkLk_sX11h9kdnq4QtBJh8G6hsicRk")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", -1004036970586))

def _fix_mongo_uri(uri: str) -> str:
    from urllib.parse import unquote
    if "://" not in uri:
        return uri
    scheme, rest = uri.split("://", 1)
    at_idx = rest.rfind("@")
    if at_idx == -1:
        return uri
    userinfo = rest[:at_idx]
    host = rest[at_idx + 1:]
    colon_idx = userinfo.find(":")
    if colon_idx == -1:
        return uri
    user = userinfo[:colon_idx]
    password = userinfo[colon_idx + 1:]
    password = unquote(password)
    return f"{scheme}://{quote_plus(user)}:{quote_plus(password)}@{host}"

MONGO_URI = _fix_mongo_uri(os.environ.get("MONGO_URI", "mongodb+srv://admin:17204@305@vixenstars.foeqljn.mongodb.net/?appName=VixenStars"))

db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client["VixenMovieDB"]
collection = db["movies"]

app = Client("vixen_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


def parse_caption(caption: str):
    parts = caption.strip().upper().split()
    if len(parts) >= 2:
        code = parts[0]
        episode = " ".join(parts[1:])
        return code, episode
    return parts[0], None


async def send_media(client, chat_id, doc, caption=None):
    media_type = doc.get("media_type", "video")
    file_id = doc["file_id"]
    if media_type == "photo":
        await client.send_photo(chat_id=chat_id, photo=file_id, caption=caption)
    else:
        await client.send_video(chat_id=chat_id, video=file_id, caption=caption)


def make_episode_buttons(results, page=0, page_size=10):
    start = page * page_size
    end = start + page_size
    page_results = results[start:end]

    buttons = []
    row = []
    for i, r in enumerate(page_results):
        ep_label = r.get("episode") or f"EP{start + i + 1}"
        row.append(InlineKeyboardButton(ep_label, callback_data=f"ep_{r['_id']}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    nav_row = []
    if page > 0:
        code = results[0]["code"]
        nav_row.append(InlineKeyboardButton("⬅️ နောက်သို့", callback_data=f"eppage_{code}_{page - 1}"))
    if end < len(results):
        code = results[0]["code"]
        nav_row.append(InlineKeyboardButton("ရှေ့သို့ ➡️", callback_data=f"eppage_{code}_{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    return buttons


@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    welcome_text = (
        "Vixen Movie Bot မှ ကြိုဆိုပါတယ် 🍿\n\n"
        "ကြည့်ရှုလိုသော ဇာတ်ကား သို့မဟုတ် Series ၏ Code ကို ရိုက်ထည့်ပေးပါ။\n\n"
        "📌 ဥပမာ — VIXEN001"
    )
    await message.reply(welcome_text)


@app.on_message(filters.chat(CHANNEL_ID) & (filters.video | filters.photo))
async def save_media(client, message):
    if not message.caption:
        return

    code, episode = parse_caption(message.caption)

    if message.video:
        file_id = message.video.file_id
        media_type = "video"
    elif message.photo:
        file_id = message.photo.file_id
        media_type = "photo"
    else:
        return

    existing = await collection.find_one({"code": code, "file_id": file_id})
    if not existing:
        doc = {
            "code": code,
            "file_id": file_id,
            "media_type": media_type,
            "message_id": message.id
        }
        if episode:
            doc["episode"] = episode
        await collection.insert_one(doc)
        label = f"{code} {episode}" if episode else code
        logger.info(f"Saved [{media_type}]: {label}")
    else:
        logger.info(f"Already exists: {code}")


@app.on_message(filters.command("del") & filters.private)
async def delete_record(client, message):
    args = message.text.strip().split(None, 1)
    if len(args) < 2:
        return await message.reply(
            "❌ Usage:\n/del CODE — Code တစ်ခုလုံး ဖျက်ရန်\n/del CODE EP1 — Episode တစ်ခုတည်း ဖျက်ရန်"
        )

    parts = args[1].strip().upper().split()
    code = parts[0]

    if len(parts) >= 2:
        episode = " ".join(parts[1:])
        result = await collection.delete_many({"code": code, "episode": episode})
        label = f"{code} {episode}"
    else:
        result = await collection.delete_many({"code": code})
        label = code

    if result.deleted_count:
        await message.reply(f"🗑️ {label} — {result.deleted_count} ခု DB မှ ဖျက်ပြီးပါပြီ။")
    else:
        await message.reply(f"❌ {label} နဲ့ ဆိုင်သော record မတွေ့ပါ။")


@app.on_message(filters.command("dedup") & filters.private)
async def dedup_record(client, message):
    args = message.text.strip().split(None, 1)
    if len(args) < 2:
        return await message.reply(
            "❌ Usage:\n/dedup CODE — Code တစ်ခုလုံးမှ duplicate ဖျက်ရန်\n/dedup CODE EP1 — Episode တစ်ခုမှ duplicate ဖျက်ရန်"
        )

    parts = args[1].strip().upper().split()
    code = parts[0]
    episode = " ".join(parts[1:]) if len(parts) >= 2 else None

    query = {"code": code}
    if episode:
        query["episode"] = episode

    cursor = collection.find(query).sort("_id", 1)
    results = await cursor.to_list(length=500)

    if not results:
        return await message.reply("❌ မတွေ့ပါ။")

    seen = {}
    to_delete = []
    for r in results:
        key = (r["code"], r.get("episode", ""), r["file_id"])
        if key in seen:
            to_delete.append(r["_id"])
        else:
            seen[key] = r["_id"]

    if not to_delete:
        return await message.reply("✅ Duplicate မရှိပါ။")

    from bson import ObjectId
    result = await collection.delete_many({"_id": {"$in": to_delete}})
    label = f"{code} {episode}".strip() if episode else code
    await message.reply(f"🗑️ {label} — Duplicate {result.deleted_count} ခု ဖျက်ပြီးပါပြီ။")


@app.on_edited_message(filters.chat(CHANNEL_ID) & (filters.video | filters.photo))
async def update_media(client, message):
    if not message.caption:
        return

    code, episode = parse_caption(message.caption)

    if message.video:
        file_id = message.video.file_id
        media_type = "video"
    elif message.photo:
        file_id = message.photo.file_id
        media_type = "photo"
    else:
        return

    doc = {
        "code": code,
        "file_id": file_id,
        "media_type": media_type,
        "message_id": message.id
    }
    if episode:
        doc["episode"] = episode

    await collection.update_one(
        {"message_id": message.id},
        {"$set": doc},
        upsert=True
    )
    label = f"{code} {episode}" if episode else code
    logger.info(f"Updated [{media_type}]: {label}")


@app.on_message(filters.private & filters.text)
async def search_video(client, message):
    user_query = message.text.strip().upper()

    cursor = collection.find({"code": user_query}).sort("_id", 1)
    results = await cursor.to_list(length=500)

    if not results:
        return await message.reply("❌ စိတ်မရှိပါနဲ့၊ ဒီ Code နဲ့ ဗီဒီယို မရှိသေးပါဘူး။")

    to_send = results[:5]
    for r in to_send:
        try:
            ep_label = r.get("episode", "")
            caption = f"🎬 {r['code']} {ep_label}".strip()
            await send_media(client, message.chat.id, r, caption=caption)
            await asyncio.sleep(1.5)
        except Exception as e:
            logger.error(f"Error: {e}")

    if len(results) > 5:
        button = [[InlineKeyboardButton("ဆက်လက်ကြည့်ရှုရန် ➡️", callback_data=f"next_{user_query}_5")]]
        await message.reply(
            f"🎬 {user_query} — စုစုပေါင်း {len(results)} ပိုင်းရှိပါတယ်။\nနောက်ထပ်အပိုင်းများကို ကြည့်ရန် နှိပ်ပါ။",
            reply_markup=InlineKeyboardMarkup(button)
        )
    else:
        await message.reply(f"✅ {user_query} အပိုင်းအားလုံး ပို့ဆောင်ပြီးပါပြီ။")


@app.on_callback_query(filters.regex(r"^ep_"))
async def send_episode(client, callback_query):
    from bson import ObjectId
    doc_id = callback_query.data.split("ep_")[1]
    result = await collection.find_one({"_id": ObjectId(doc_id)})

    if not result:
        return await callback_query.answer("❌ ဗီဒီယို မတွေ့ပါ။", show_alert=True)

    await callback_query.answer()
    try:
        ep_label = result.get("episode", "")
        caption = f"🎬 {result['code']} {ep_label}".strip()
        await send_media(client, callback_query.message.chat.id, result, caption=caption)
    except Exception as e:
        logger.error(f"Error sending episode: {e}")
        await callback_query.answer("❌ ပို့မရဖြစ်နေပါတယ်။", show_alert=True)


@app.on_callback_query(filters.regex(r"^eppage_"))
async def episode_page(client, callback_query):
    _, code, page_str = callback_query.data.split("_", 2)
    page = int(page_str)

    cursor = collection.find({"code": code}).sort("_id", 1)
    results = await cursor.to_list(length=500)

    buttons = make_episode_buttons(results, page=page)
    await callback_query.message.edit_text(
        f"🎬 <b>{code}</b>\nစုစုပေါင်း {len(results)} ပိုင်းရှိပါတယ်။\nကြည့်ချင်သော Episode ကိုရွေးပါ။",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=enums.ParseMode.HTML
    )
    await callback_query.answer()


@app.on_callback_query(filters.regex(r"^next_"))
async def next_page(client, callback_query):
    data = callback_query.data.split("_")
    code = data[1]
    skip_count = int(data[2])

    cursor = collection.find({"code": code}).sort("_id", 1)
    results = await cursor.to_list(length=500)

    to_send = results[skip_count: skip_count + 5]
    for result in to_send:
        try:
            await send_media(client, callback_query.message.chat.id, result)
            await asyncio.sleep(1.5)
        except Exception as e:
            logger.error(f"Error: {e}")

    new_skip = skip_count + 5
    if len(results) > new_skip:
        button = [[InlineKeyboardButton("ဆက်လက်ကြည့်ရှုရန် ➡️", callback_data=f"next_{code}_{new_skip}")]]
        await callback_query.message.edit_text(
            f"🎥 နောက်ထပ်အပိုင်းများကို ပို့ပေးနေပါတယ်...",
            reply_markup=InlineKeyboardMarkup(button)
        )
    else:
        await callback_query.message.edit_text("✅ အပိုင်းအားလုံး ပို့ဆောင်ပြီးပါပြီ။")


if __name__ == "__main__":
    logger.info("Vixen Movie Bot စတင် အလုပ်လုပ်နေပါပြီး...")
    app.run()
