from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import *
from database import users, files, plans

import asyncio
from aiohttp import web

app = Client("bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

# ---------------- USER TRACK ----------------
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
        [InlineKeyboardButton("Watch Now", callback_data="watch")],
        [InlineKeyboardButton("Help", callback_data="help")]
    ])

    await message.reply_text("Welcome 👋", reply_markup=buttons)


# ---------------- WATCH ----------------
@app.on_callback_query(filters.regex("watch"))
async def watch(client, query):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Plan 1", callback_data="plan_1")],
        [InlineKeyboardButton("Plan 2", callback_data="plan_2")],
        [InlineKeyboardButton("Plan 3", callback_data="plan_3")],
        [InlineKeyboardButton("Plan 4", callback_data="plan_4")]
    ])
    await query.message.edit_text("Choose Plan:", reply_markup=buttons)


# ---------------- PLAN ----------------
@app.on_callback_query(filters.regex("plan_"))
async def plan(client, query):
    pid = int(query.data.split("_")[1])
    p = await plans.find_one({"plan_id": pid})

    await query.message.edit_text(
        f"{p['text']}\n\n💰 {p['price']}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Pay", callback_data=f"pay_{pid}")],
            [InlineKeyboardButton("Unlock", callback_data=f"unlock_{pid}")]
        ])
    )


# ---------------- PAY ----------------
@app.on_callback_query(filters.regex("pay_"))
async def pay(client, query):
    pid = int(query.data.split("_")[1])
    p = await plans.find_one({"plan_id": pid})

    await query.message.reply_text(f"Pay here:\n{p['qr']}")


# ---------------- UNLOCK ----------------
user_wait = {}

@app.on_callback_query(filters.regex("unlock_"))
async def unlock(client, query):
    pid = int(query.data.split("_")[1])
    user_wait[query.from_user.id] = pid
    await query.message.reply("Send code")


@app.on_message(filters.text & filters.private & ~filters.command(["start","stats"]))
async def check(client, message):

    await add_user(message.from_user.id)

    if message.from_user.id not in user_wait:
        return

    code = message.text.strip().upper()

    plan = await plans.find_one({"codes":{"$in":[code]}})

    if not plan:
        return await message.reply("Invalid")

    tasks=[]
    async for f in files.find({"plan":plan["plan_id"]}):
        tasks.append(
            client.copy_message(
                message.chat.id,
                f["chat_id"],
                f["message_id"],
                protect_content=True
            )
        )

    await asyncio.gather(*tasks)


# ---------------- PRO INDEX ----------------
@app.on_message(filters.command("index") & filters.user(ADMIN_IDS))
async def index(client, message):

    if not message.reply_to_message:
        return await message.reply("Reply to file")

    pid = int(message.text.split()[1])
    count = 0

    async for msg in client.get_chat_history(message.chat.id, limit=50):
        if msg.media:
            await files.insert_one({
                "plan": pid,
                "chat_id": msg.chat.id,
                "message_id": msg.id
            })
            count+=1

    await message.reply(f"Indexed {count} files")


# ---------------- STATS ----------------
@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats(client, message):

    total_users = await users.count_documents({})
    active_users = await users.count_documents({"active": True})
    blocked_users = await users.count_documents({"blocked": True})
    deleted_users = await users.count_documents({"deleted": True})

    p1 = await files.count_documents({"plan":1})
    p2 = await files.count_documents({"plan":2})
    p3 = await files.count_documents({"plan":3})
    p4 = await files.count_documents({"plan":4})

    total_files = await files.count_documents({})

    text = f"""
📊 BOT STATS

👥 Users:
Total: {total_users}
Active: {active_users}
Blocked: {blocked_users}
Deleted: {deleted_users}

📂 Files:
Plan1: {p1}
Plan2: {p2}
Plan3: {p3}
Plan4: {p4}

Total Files: {total_files}
"""

    await message.reply(text)


# ---------------- SETUP ----------------
@app.on_message(filters.command("setup") & filters.user(ADMIN_IDS))
async def setup(client, message):

    data = [
        {"plan_id":1,"price":"₹99","text":"Basic","qr":"UPI","codes":["P1A"]},
        {"plan_id":2,"price":"₹199","text":"Standard","qr":"UPI","codes":["P2A"]},
        {"plan_id":3,"price":"₹299","text":"Premium","qr":"UPI","codes":["P3A"]},
        {"plan_id":4,"price":"₹499","text":"VIP","qr":"UPI","codes":["P4A"]}
    ]

    for d in data:
        await plans.update_one({"plan_id":d["plan_id"]},{"$set":d},upsert=True)

    await message.reply("Setup Done")


# ---------------- WEB ----------------
async def handle(request):
    return web.Response(text="Running")

async def start_web():
    app_web = web.Application()
    app_web.router.add_get("/", handle)
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner,"0.0.0.0",8000)
    await site.start()


# ---------------- MAIN ----------------
async def main():
    await app.start()
    await start_web()
    print("Bot Started")
    await idle()

if __name__ == "__main__":
    app.run(main())
