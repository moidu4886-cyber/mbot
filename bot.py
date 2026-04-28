from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import *
from database import users, files, plans

import asyncio
from aiohttp import web

app = Client("bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

# ---------------------------
# START (WITH IMAGE UI)
# ---------------------------
@app.on_message(filters.command("start"))
async def start(client, message):
    await users.update_one(
        {"user_id": message.from_user.id},
        {"$set": {"user_id": message.from_user.id}},
        upsert=True
    )

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Watch Now", callback_data="watch")],
        [InlineKeyboardButton("🆘 Help", callback_data="help")],
        [InlineKeyboardButton("🔗 Share Bot", switch_inline_query="")]
    ])

    await message.reply_photo(
        "https://via.placeholder.com/600x300?text=WELCOME",
        caption="🔥 Welcome Boss 👋\nChoose your option:",
        reply_markup=buttons
    )


# ---------------------------
# WATCH NOW (BETTER UI)
# ---------------------------
@app.on_callback_query(filters.regex("watch"))
async def watch(client, query):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Plan 1 - Basic", callback_data="plan_1")],
        [InlineKeyboardButton("🔵 Plan 2 - Standard", callback_data="plan_2")],
        [InlineKeyboardButton("🟣 Plan 3 - Premium", callback_data="plan_3")],
        [InlineKeyboardButton("🟡 Plan 4 - VIP", callback_data="plan_4")]
    ])
    await query.message.edit_text("💼 Choose Your Plan:", reply_markup=buttons)


# ---------------------------
# PLAN DETAILS
# ---------------------------
@app.on_callback_query(filters.regex("plan_"))
async def plan_details(client, query):
    plan_id = int(query.data.split("_")[1])
    plan = await plans.find_one({"plan_id": plan_id})

    text = plan.get("text", "No data")
    price = plan.get("price", "₹0")
    duration = plan.get("duration", "30 Days")

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Pay Now", callback_data=f"pay_{plan_id}")],
        [InlineKeyboardButton("🔓 Unlock", callback_data=f"unlock_{plan_id}")]
    ])

    await query.message.edit_text(
        f"📦 {text}\n\n💰 Price: {price}\n⏱ Duration: {duration}",
        reply_markup=buttons
    )


# ---------------------------
# PAY (QR PER PLAN)
# ---------------------------
@app.on_callback_query(filters.regex("pay_"))
async def pay(client, query):
    plan_id = int(query.data.split("_")[1])
    plan = await plans.find_one({"plan_id": plan_id})

    await query.message.reply_photo(
        plan["qr"],
        caption=f"💳 {plan['text']}\n\nScan & Pay then enter code"
    )


# ---------------------------
# UNLOCK SYSTEM
# ---------------------------
user_wait = {}

@app.on_callback_query(filters.regex("unlock_"))
async def unlock(client, query):
    plan_id = int(query.data.split("_")[1])
    user_wait[query.from_user.id] = plan_id
    await query.message.reply("🔐 Send your unlock code:")


@app.on_message(filters.text & filters.private & ~filters.command(["start","setup","admin"]))
async def check_code(client, message):

    if message.from_user.id not in user_wait:
        return

    code = message.text.strip().upper()

    plan_data = await plans.find_one({"codes": {"$in": [code]}})

    if not plan_data:
        return await message.reply("❌ Invalid code")

    await message.reply("✅ Access granted\nSending files...")

    async for file in files.find({"plan": plan_data["plan_id"]}):
        await client.copy_message(
            chat_id=message.chat.id,
            from_chat_id=file["chat_id"],
            message_id=file["message_id"],
            protect_content=True
        )


# ---------------------------
# ADMIN PANEL
# ---------------------------
@app.on_message(filters.command("admin") & filters.user(ADMIN_IDS))
async def admin(client, message):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Edit Plan 1", callback_data="edit_1")],
        [InlineKeyboardButton("✏️ Edit Plan 2", callback_data="edit_2")],
        [InlineKeyboardButton("✏️ Edit Plan 3", callback_data="edit_3")],
        [InlineKeyboardButton("✏️ Edit Plan 4", callback_data="edit_4")]
    ])
    await message.reply("⚙️ Admin Panel", reply_markup=buttons)


# ---------------------------
# EDIT PLAN
# ---------------------------
edit_state = {}

@app.on_callback_query(filters.regex("edit_"))
async def edit_plan(client, query):
    pid = int(query.data.split("_")[1])

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Price", callback_data=f"price_{pid}")],
        [InlineKeyboardButton("📝 Text", callback_data=f"text_{pid}")],
        [InlineKeyboardButton("🖼 QR", callback_data=f"qr_{pid}")]
    ])

    await query.message.edit_text(f"Editing Plan {pid}", reply_markup=buttons)


@app.on_callback_query(filters.regex("(price_|text_|qr_)"))
async def ask_input(client, query):
    action, pid = query.data.split("_")
    edit_state[query.from_user.id] = (action, int(pid))
    await query.message.reply(f"Send new {action} for Plan {pid}")


@app.on_message(filters.text & filters.user(ADMIN_IDS))
async def save_edit(client, message):

    if message.from_user.id not in edit_state:
        return

    action, pid = edit_state[message.from_user.id]
    value = message.text

    await plans.update_one({"plan_id": pid}, {"$set": {action: value}})

    await message.reply("✅ Updated successfully")
    del edit_state[message.from_user.id]


# ---------------------------
# SETUP DEFAULT PLANS
# ---------------------------
@app.on_message(filters.command("setup") & filters.user(ADMIN_IDS))
async def setup(client, message):

    data = [
        {"plan_id":1,"price":"₹99","duration":"30 Days","text":"Basic Plan","qr":"https://via.placeholder.com/300?text=P1","codes":["P1A"]},
        {"plan_id":2,"price":"₹199","duration":"30 Days","text":"Standard Plan","qr":"https://via.placeholder.com/300?text=P2","codes":["P2A"]},
        {"plan_id":3,"price":"₹299","duration":"30 Days","text":"Premium Plan","qr":"https://via.placeholder.com/300?text=P3","codes":["P3A"]},
        {"plan_id":4,"price":"₹499","duration":"30 Days","text":"VIP Plan","qr":"https://via.placeholder.com/300?text=P4","codes":["P4A"]}
    ]

    for d in data:
        await plans.update_one({"plan_id":d["plan_id"]},{"$set":d},upsert=True)

    await message.reply("✅ Setup Done")


# ---------------------------
# WEB SERVER (KOYEB)
# ---------------------------
async def handle(request):
    return web.Response(text="Bot running")

async def start_web():
    app_web = web.Application()
    app_web.router.add_get("/", handle)
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8000)
    await site.start()


# ---------------------------
# MAIN
# ---------------------------
async def main():
    await app.start()
    await start_web()
    print("Bot Started")
    await idle()

if __name__ == "__main__":
    app.run(main())
