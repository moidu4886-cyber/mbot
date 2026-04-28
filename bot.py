from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import *
from database import users, files, plans

import asyncio
from aiohttp import web

app = Client("bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

# =========================
# START
# =========================
@app.on_message(filters.command("start"))
async def start(client, message):
    user_id = message.from_user.id

    await users.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id}},
        upsert=True
    )

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Watch Now", callback_data="watch")],
        [InlineKeyboardButton("🆘 Help", callback_data="help")],
        [InlineKeyboardButton("🔗 Share Bot", switch_inline_query="")]
    ])

    await message.reply_text("Hello Boss 👋", reply_markup=buttons)


# =========================
# WATCH NOW
# =========================
@app.on_callback_query(filters.regex("watch"))
async def watch(client, query):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Plan 1", callback_data="plan_1")],
        [InlineKeyboardButton("Plan 2", callback_data="plan_2")],
        [InlineKeyboardButton("Plan 3", callback_data="plan_3")],
        [InlineKeyboardButton("Plan 4", callback_data="plan_4")]
    ])
    await query.message.edit_text("Choose Plan:", reply_markup=buttons)


# =========================
# PLAN DETAILS
# =========================
@app.on_callback_query(filters.regex("plan_"))
async def plan_details(client, query):
    plan_id = int(query.data.split("_")[1])

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Pay", callback_data=f"pay_{plan_id}")],
        [InlineKeyboardButton("🔓 Unlock", callback_data=f"unlock_{plan_id}")]
    ])

    await query.message.edit_text(
        f"Plan {plan_id}\nPrice: ₹99\nDuration: 30 Days",
        reply_markup=buttons
    )


# =========================
# PAYMENT QR
# =========================
@app.on_callback_query(filters.regex("pay_"))
async def pay(client, query):
    await query.message.reply_photo(
        "https://via.placeholder.com/300",
        caption="Scan & Pay then enter unlock code"
    )


# =========================
# UNLOCK SYSTEM
# =========================
user_plan_wait = {}

@app.on_callback_query(filters.regex("unlock_"))
async def unlock(client, query):
    plan_id = int(query.data.split("_")[1])
    user_plan_wait[query.from_user.id] = plan_id
    await query.message.reply("Send your unlock code:")


@app.on_message(filters.text & filters.private)
async def check_code(client, message):

    user_id = message.from_user.id

    if user_id not in user_plan_wait:
        return

    code = message.text.strip()

    # Find plan using code
    plan_data = await plans.find_one({"codes": code})

    if not plan_data:
        await message.reply("Invalid code ❌")
        return

    plan_id = plan_data["plan_id"]

    await message.reply("Access granted ✅ Sending files...")

    # Send all files of that plan
    async for file in files.find({"plan": plan_id}):

        await client.copy_message(
            chat_id=user_id,
            from_chat_id=file["chat_id"],
            message_id=file["message_id"],
            protect_content=True
        )


# =========================
# INDEX FILE (ADMIN)
# =========================
@app.on_message(filters.command("index") & filters.user(ADMIN_IDS))
async def index_file(client, message):

    if not message.reply_to_message:
        return await message.reply("Reply to a file")

    try:
        plan_id = int(message.text.split()[1])
    except:
        return await message.reply("Use: /index 1")

    msg = message.reply_to_message

    await files.insert_one({
        "plan": plan_id,
        "chat_id": msg.chat.id,
        "message_id": msg.id
    })

    await message.reply(f"File indexed to Plan {plan_id} ✅")


# =========================
# STATS
# =========================
@app.on_message(filters.command("stats"))
async def stats(client, message):
    total = await users.count_documents({})
    await message.reply(f"Total Users: {total}")


# =========================
# BROADCAST
# =========================
@app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast(client, message):

    if len(message.command) < 2:
        return await message.reply("Use: /broadcast message")

    text = message.text.split(None, 1)[1]

    count = 0
    async for user in users.find({}):
        try:
            await client.send_message(user["user_id"], text)
            count += 1
        except:
            pass

    await message.reply(f"Sent to {count} users")


# =========================
# SETUP PLANS (RUN ONCE)
# =========================
@app.on_message(filters.command("setup") & filters.user(ADMIN_IDS))
async def setup_plans(client, message):

    data = [
        {"plan_id": 1, "codes": ["P1A", "P1B", "P1C", "P1D"]},
        {"plan_id": 2, "codes": ["P2A", "P2B", "P2C", "P2D"]},
        {"plan_id": 3, "codes": ["P3A", "P3B", "P3C", "P3D"]},
        {"plan_id": 4, "codes": ["P4A", "P4B", "P4C", "P4D"]}
    ]

    for p in data:
        await plans.update_one(
            {"plan_id": p["plan_id"]},
            {"$set": p},
            upsert=True
        )

    await message.reply("Plans + Codes Setup Done ✅")


# =========================
# WEB SERVER (KOYEB FIX)
# =========================
async def handle(request):
    return web.Response(text="Bot is running ✅")

async def start_web():
    web_app = web.Application()
    web_app.router.add_get("/", handle)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8000)
    await site.start()


# =========================
# MAIN RUN (FINAL FIX)
# =========================
from pyrogram import idle

async def main():
    await app.start()
    await start_web()
    print("Bot Started ✅")
    await idle()

if __name__ == "__main__":
    app.run(main())
