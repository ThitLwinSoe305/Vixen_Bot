import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient
from keep_alive import keep_alive

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID = 38738409
API_HASH = "5f2a2d513c80c5452f190f03d95976e2"
BOT_TOKEN = "8635268994:AAGvqGssbqfrcFmJp_JmiXNHmzJ4pyWgruo"
MONGO_URI = "mongodb+srv://admin:17204@305@vixenstars.foeqljn.mongodb.net/?appName=VixenStars"
CHANNEL_ID = -1004036970586

db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client["VixenMovieDB"]
collection = db["movies"]

app = Client("vixen_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply("Vixen Movie Bot မှ ကြိုဆိုပါတယ် 🍿\n\nကြည့်ရှုလိုသော ဇာတ်ကား သို့မဟုတ် Series ၏ Code ကို ရိုက်ထည့်ပေးပါ။")

@app.on_message(filters.chat(CHANNEL_ID) & filters.video)
async def save_video(client, message):
    if message.caption:
        v_code = message.caption.strip().upper()
        v_id = message.video.file_id
        existing = await collection.find_one({"code": v_code, "file_id": v_id})
        if not existing:
            await collection.insert_one({"code": v_code, "file_id": v_id, "message_id": message.id})
            logger.info(f"✅ Saved Code: {v_code}")

@app.on_message(filters.private & filters.text)
async def search_video(client, message):
    user_query = message.text.strip().upper()
    cursor = collection.find({"code": user_query}).sort("_id", 1)
    results = await cursor.to_list(length=500)
    if not results:
        return await message.reply("❌ စိတ်မရှိပါနဲ့၊ ဒီ Code နဲ့ ဗီဒီယို မရှိသေးပါဘူး။")
    to_send = results[:5]
    for result in to_send:
        try:
            await client.send_video(chat_id=message.chat.id, video=result["file_id"])
            await asyncio.sleep(1.5)
        except Exception as e:
            logger.error(f"Error sending video: {e}")
    if len(results) > 5:
        button = [[InlineKeyboardButton("ဆက်လက်ကြည့်ရှုရန် ➡️", callback_data=f"next_{user_query}_5")]]
        await message.reply(f"🎬 {user_query}\nစုစုပေါင်း: {len(results)} ပိုင်းရှိပါတယ်။\nအောက်ပါခလုတ်ကိုနှိပ်ပြီး နောက်ထပ်အပိုင်းများကို ကြည့်ပါ။", reply_markup=InlineKeyboardMarkup(button))
    else:
        await message.reply(f"✅ {user_query} အပိုင်းအားလုံး ပို့ဆောင်ပြီးပါပြီ။")

@app.on_callback_query(filters.regex(r"^next_"))
async def next_page(client, callback_query):
    data = callback_query.data.split("_")
    code, skip_count = data[1], int(data[2])
    cursor = collection.find({"code": code}).sort("_id", 1)
    results = await cursor.to_list(length=500)
    to_send = results[skip_count : skip_count + 5]
    for result in to_send:
        try:
            await client.send_video(chat_id=callback_query.message.chat.id, video=result["file_id"])
            await asyncio.sleep(1.5)
        except Exception as e:
            logger.error(f"Error sending video: {e}")
    new_skip = skip_count + 5
    if len(results) > new_skip:
        button = [[InlineKeyboardButton("ဆက်လက်ကြည့်ရှုရန် ➡️", callback_data=f"next_{code}_{new_skip}")]]
        await callback_query.message.edit_text(f"🎥 နောက်ထပ်အပိုင်းများကို ပို့ပေးနေပါတယ်...", reply_markup=InlineKeyboardMarkup(button))
    else:
        await callback_query.message.edit_text("✅ အပိုင်းအားလုံး ပို့ဆောင်ပြီးပါပြီ။")

if __name__ == "__main__":
    keep_alive()
    app.run()
