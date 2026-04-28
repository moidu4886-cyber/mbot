from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import *
from database import users, files, plans

import asyncio
from aiohttp import web

app = Client("bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

# ---------------- USER ADD ----------------
async def add_user(user_id):
    await users.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "active": True}},
        upsert=True
    )

# ---------------- START ----------------
@app.on_message(filters.command("start"))
async def start(client, message):
    await add_user(message.from_user.id)

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Watch Now", callback_data="watch")],
        [InlineKeyboardButton("🔗 Share Bot", switch_inline_query="")]
    ])

    await message.reply_text("👋 Welcome to Bot", reply_markup=buttons)


# ---------------- WATCH ----------------
@app.on_callback_query(filters.regex("^watch$"))
async def watch(client, query):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Plan 1", callback_data="plan_1")],
        [InlineKeyboardButton("Plan 2", callback_data="plan_2")],
        [InlineKeyboardButton("Plan 3", callback_data="plan_3")],
        [InlineKeyboardButton("Plan 4", callback_data="plan_4")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_home")]
    ])
    await query.message.edit_text("Choose Plan:", reply_markup=buttons)


# ---------------- PLAN ----------------
@app.on_callback_query(filters.regex("^plan_"))
async def plan(client, query):
    pid = int(query.data.split("_")[1])
    p = await plans.find_one({"plan_id": pid})

    if not p:
        return await query.message.edit_text("❌ Plan not found")

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Pay", callback_data=f"pay_{pid}")],
        [InlineKeyboardButton("🔓 Unlock", callback_data=f"unlock_{pid}")],
        [InlineKeyboardButton("🔙 Back", callback_data="watch")]
    ])

    await query.message.edit_text(
        f"{p.get('text')}\n\n💰 {p.get('price')}\n📞 Contact: {p.get('contact')}",
        reply_markup=buttons
    )


# ---------------- PAY ----------------
@app.on_callback_query(filters.regex("^pay_"))
async def pay(client, query):
    pid = int(query.data.split("_")[1])
    p = await plans.find_one({"plan_id": pid})

    await query.message.reply_text(f"💳 Pay using:\n{p.get('qr')}")


# ---------------- UNLOCK ----------------
user_wait = {}

@app.on_callback_query(filters.regex("^unlock_"))
async def unlock(client, query):
    user_wait[query.from_user.id] = True
    await query.message.reply("Send unlock code")


@app.on_message(filters.text & filters.private & ~filters.command(["start","setup","broadcast","index"]))
async def check(client, message):

    await add_user(message.from_user.id)

    if message.from_user.id not in user_wait:
        return

    code = message.text.strip().upper()

    plan = await plans.find_one({"codes": {"$in":[code]}})

    if not plan:
        return await message.reply("❌ Invalid code")

    await message.reply("✅ Access granted")

    tasks = []
    async for f in files.find({"plan": plan["plan_id"]}):
        tasks.append(
            client.copy_message(
                message.chat.id,
                f["chat_id"],
                f["message_id"],
                protect_content=True
            )
        )

    if tasks:
        await asyncio.gather(*tasks)
    else:
        await message.reply("No files found")


# ---------------- INDEX ----------------
@app.on_message(filters.command("index") & filters.user(ADMIN_IDS))
async def index(client, message):

    if not message.reply_to_message:
        return await message.reply("Reply to media")

    pid = int(message.text.split()[1])

    msg = message.reply_to_message

    await files.insert_one({
        "plan": pid,
        "chat_id": msg.chat.id,
        "message_id": msg.id
    })

    await message.reply("Indexed ✅")


# ---------------- BROADCAST ----------------
@app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast(client, message):

    text = message.text.split(None, 1)[1]

    count = 0
    async for user in users.find({}):
        try:
            await client.send_message(user["user_id"], text)
            count += 1
        except:
            pass

    await message.reply(f"Broadcast sent to {count}")


# ---------------- ADMIN PANEL ----------------
@app.on_message(filters.command("setup") & filters.user(ADMIN_IDS))
async def admin_panel(client, message):

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Stats", callback_data="admin_stats")],
        [InlineKeyboardButton("✏️ Edit Plan 1", callback_data="edit_1")],
        [InlineKeyboardButton("✏️ Edit Plan 2", callback_data="edit_2")],
        [InlineKeyboardButton("✏️ Edit Plan 3", callback_data="edit_3")],
        [InlineKeyboardButton("✏️ Edit Plan 4", callback_data="edit_4")]
    ])

    await message.reply("⚙️ Admin Dashboard", reply_markup=buttons)


# ---------------- STATS ----------------
@app.on_callback_query(filters.regex("admin_stats"))
async def stats(client, query):

    total_users = await users.count_documents({})
    total_files = await files.count_documents({})

    p1 = await files.count_documents({"plan":1})
    p2 = await files.count_documents({"plan":2})
    p3 = await files.count_documents({"plan":3})
    p4 = await files.count_documents({"plan":4})

    await query.message.edit_text(f"""
📊 BOT STATS

👥 Users: {total_users}

📂 Files:
Plan1: {p1}
Plan2: {p2}
Plan3: {p3}
Plan4: {p4}

Total Files: {total_files}
""")


# ---------------- EDIT PLAN ----------------
edit_state = {}

@app.on_callback_query(filters.regex("^edit_"))
async def edit_plan(client, query):

    pid = int(query.data.split("_")[1])

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Text", callback_data=f"text_{pid}")],
        [InlineKeyboardButton("Price", callback_data=f"price_{pid}")],
        [InlineKeyboardButton("QR", callback_data=f"qr_{pid}")],
        [InlineKeyboardButton("Contact", callback_data=f"contact_{pid}")]
    ])

    await query.message.edit_text(f"Editing Plan {pid}", reply_markup=buttons)


@app.on_callback_query(filters.regex("(text_|price_|qr_|contact_)"))
async def ask_edit(client, query):

    action, pid = query.data.split("_")
    edit_state[query.from_user.id] = (action, int(pid))

    await query.message.reply(f"Send new {action}")


@app.on_message(filters.text & filters.user(ADMIN_IDS))
async def save_edit(client, message):

    if message.from_user.id not in edit_state:
        return

    action, pid = edit_state[message.from_user.id]

    await plans.update_one(
        {"plan_id": pid},
        {"$set": {action: message.text}}
    )

    await message.reply("Updated ✅")
    del edit_state[message.from_user.id]


# ---------------- SETUP DEFAULT ----------------
@app.on_message(filters.command("init") & filters.user(ADMIN_IDS))
async def init(client, message):

    data = [
        {"plan_id":1,"price":"₹99","text":"Basic","qr":"UPI1","contact":"@admin","codes":["P1A"]},
        {"plan_id":2,"price":"₹199","text":"Standard","qr":"UPI2","contact":"@admin","codes":["P2A"]},
        {"plan_id":3,"price":"₹299","text":"Premium","qr":"UPI3","contact":"@admin","codes":["P3A"]},
        {"plan_id":4,"price":"₹499","text":"VIP","qr":"UPI4","contact":"@admin","codes":["P4A"]}
    ]

    for d in data:
        await plans.update_one({"plan_id": d["plan_id"]}, {"$set": d}, upsert=True)

    await message.reply("Plans initialized ✅")


# ---------------- WEB ----------------
async def handle(request):
    return web.Response(text="Running")

async def start_web():
    app_web = web.Application()
    app_web.router.add_get("/", handle)
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8000)
    await site.start()


# ---------------- MAIN ----------------
async def main():
    await app.start()
    await start_web()
    print("Bot Started")
    await idle()

if __name__ == "__main__":
    app.run(main())
