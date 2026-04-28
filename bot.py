import asyncio
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserIsBlocked, InputUserDeactivated, FloodWait
from aiohttp import web
from config import *
from database import users, files, plans

# Bot initialization
app = Client("bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

# States
user_wait = {} # {user_id: plan_id}
edit_state = {} # {user_id: (action, pid)}

# ---------------- HELPER FUNCTIONS ----------------

async def add_user(user_id):
    await users.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "active": True, "blocked": False}},
        upsert=True
    )

async def get_support_id():
    settings = await plans.find_one({"plan_id": "settings"})
    return settings.get("support_id", "@AdminUsername") if settings else "@AdminUsername"

# ---------------- START MENU ----------------

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    user_id = message.from_user.id
    await add_user(user_id)
    
    # Clear any previous wait states
    if user_id in user_wait: del user_wait[user_id]
    if user_id in edit_state: del edit_state[user_id]
        
    support_id = await get_support_id()
    support_url = f"https://t.me/{support_id.replace('@','')}"

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Watch Now", callback_data="watch")],
        [InlineKeyboardButton("🔗 Share Bot", switch_inline_query="Check this!")],
        [InlineKeyboardButton("🆘 Contact Admin / Help", url=support_url)]
    ])
    
    await message.reply_text(
        f"👋 **Welcome {message.from_user.mention}!**\n\nAccess premium content easily with our plan-based system.",
        reply_markup=buttons
    )

# ---------------- NAVIGATION ----------------

@app.on_callback_query(filters.regex("^back_home$"))
async def back_home(client, query):
    user_id = query.from_user.id
    if user_id in user_wait: del user_wait[user_id]
    await query.answer()
    await start(client, query.message)
    await query.message.delete()

@app.on_callback_query(filters.regex("^watch$"))
async def watch_menu(client, query):
    user_id = query.from_user.id
    if user_id in user_wait: del user_wait[user_id]
    await query.answer()
    
    buttons = [[InlineKeyboardButton(f"Plan {i}", callback_data=f"plan_{i}")] for i in range(1, 5)]
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back_home")])
    
    await query.message.edit_text("⚡ **Select Your Plan:**", reply_markup=InlineKeyboardMarkup(buttons))

# ---------------- PLAN DETAILS & UNLOCK ----------------

@app.on_callback_query(filters.regex("^plan_"))
async def plan_details(client, query):
    await query.answer()
    pid = int(query.data.split("_")[1])
    p = await plans.find_one({"plan_id": pid})
    if not p: return await query.message.edit_text("❌ Plan not found!")

    text = f"📋 **{p.get('text')}**\n\n💰 **Price:** {p.get('price')}\n📞 **Admin:** {p.get('contact')}"
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Pay Now", callback_data=f"pay_{pid}"),
         InlineKeyboardButton("🔓 Unlock", callback_data=f"unlock_{pid}")],
        [InlineKeyboardButton("🔙 Back", callback_data="watch")]
    ])
    await query.message.edit_text(text, reply_markup=buttons)

@app.on_callback_query(filters.regex("^unlock_"))
async def ask_unlock(client, query):
    await query.answer()
    pid = int(query.data.split("_")[1])
    user_wait[query.from_user.id] = pid 
    await query.message.reply(f"🔑 **Please send your Unlock Code for Plan {pid}:**\n(To cancel, send /start)")

# ---------------- TEXT HANDLER (ADMIN & USER) ----------------

@app.on_message(filters.text & filters.private)
async def handle_text(client, message):
    user_id = message.from_user.id

    # 1. Skip if it's a command (Fixes Admin Command Issue)
    if message.text.startswith("/"):
        return

    # 2. ADMIN EDIT LOGIC
    if user_id in ADMIN_IDS and user_id in edit_state:
        action, pid = edit_state[user_id]
        new_val = message.text.strip()
        
        if pid == "settings":
            await plans.update_one({"plan_id": "settings"}, {"$set": {action: new_val}}, upsert=True)
            await message.reply(f"✅ Support ID updated to: {new_val}")
        elif action == "add_code":
            await plans.update_one({"plan_id": pid}, {"$push": {"codes": new_val.upper()}})
            await message.reply(f"✅ Code `{new_val.upper()}` added to Plan {pid}")
        else:
            await plans.update_one({"plan_id": pid}, {"$set": {action: new_val}})
            await message.reply(f"✅ Plan {pid} {action} updated!")
        
        del edit_state[user_id]
        return

    # 3. USER UNLOCK LOGIC (Strict - Only works after clicking Unlock)
    if user_id in user_wait:
        pid = user_wait[user_id]
        code = message.text.strip().upper()
        
        plan_data = await plans.find_one({"plan_id": pid, "codes": {"$in": [code]}})
        
        if not plan_data:
            return await message.reply("❌ **Invalid Code for this Plan!**\nMake sure you are entering the correct code.")

        await message.reply("✅ **Verified!** Sending exclusive files...")
        
        file_cursor = files.find({"plan": pid})
        async for f in file_cursor:
            try:
                await client.copy_message(
                    chat_id=message.chat.id, 
                    from_chat_id=f["chat_id"], 
                    message_id=f["message_id"], 
                    protect_content=True
                )
                await asyncio.sleep(0.5) 
            except Exception as e:
                print(f"Error: {e}")
        
        del user_wait[user_id] # State cleared after success
    else:
        # Prevent confusion for normal users
        if user_id not in ADMIN_IDS:
            await message.reply("❓ Please select a plan and click the **Unlock** button before sending a code.")

# ---------------- ADMIN COMMANDS ----------------

@app.on_message(filters.command("setup") & filters.user(ADMIN_IDS))
async def admin_panel(client, message):
    buttons = [
        [InlineKeyboardButton("📊 Stats", callback_data="admin_stats")],
        [InlineKeyboardButton("✏️ Plan 1", callback_data="edit_1"), InlineKeyboardButton("✏️ Plan 2", callback_data="edit_2")],
        [InlineKeyboardButton("✏️ Plan 3", callback_data="edit_3"), InlineKeyboardButton("✏️ Plan 4", callback_data="edit_4")],
        [InlineKeyboardButton("👤 Global Support ID", callback_data="set_global_admin")]
    ]
    await message.reply("🛠 **Admin Dashboard**", reply_markup=InlineKeyboardMarkup(buttons))

@app.on_callback_query(filters.regex("^edit_"))
async def edit_plan_menu(client, query):
    await query.answer()
    pid = int(query.data.split("_")[1])
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Text", callback_data=f"set_text_{pid}"), InlineKeyboardButton("Price", callback_data=f"set_price_{pid}")],
        [InlineKeyboardButton("QR", callback_data=f"set_qr_{pid}"), InlineKeyboardButton("Contact", callback_data=f"set_contact_{pid}")],
        [InlineKeyboardButton("➕ Add Code", callback_data=f"add_code_{pid}")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_admin")]
    ])
    await query.message.edit_text(f"⚙️ **Editing Plan {pid}**", reply_markup=buttons)

@app.on_callback_query(filters.regex("^set_|^add_code_"))
async def ask_update(client, query):
    await query.answer()
    data = query.data.split("_")
    if data[0] == "add":
        edit_state[query.from_user.id] = ("add_code", int(data[2]))
    else:
        edit_state[query.from_user.id] = (data[1], int(data[2]))
    await query.message.reply("💬 Send the new value/code:")

@app.on_callback_query(filters.regex("^set_global_admin$"))
async def set_global_admin(client, query):
    await query.answer()
    edit_state[query.from_user.id] = ("support_id", "settings")
    await query.message.reply("💬 Send new Support ID (eg: @MyUser):")

@app.on_callback_query(filters.regex("^admin_stats$|^back_admin$"))
async def admin_stats(client, query):
    await query.answer()
    if query.data == "back_admin":
        return await admin_panel(client, query.message)
        
    total = await users.count_documents({})
    file_info = ""
    for i in range(1, 5):
        c = await files.count_documents({"plan": i})
        file_info += f"Plan {i}: {c} files\n"
        
    await query.message.edit_text(f"📊 **Stats**\n\nUsers: {total}\n\n{file_info}", 
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_admin")]]))

@app.on_message(filters.command("index") & filters.user(ADMIN_IDS))
async def index_file(client, message):
    if not message.reply_to_message: return await message.reply("Reply to a file.")
    try:
        pid = int(message.text.split()[1])
        reply = message.reply_to_message
        await files.insert_one({"plan": pid, "chat_id": reply.chat.id, "message_id": reply.id})
        await message.reply(f"✅ File indexed to Plan {pid}")
    except: await message.reply("Usage: `/index 1`")

@app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast(client, message):
    if len(message.text.split()) < 2: return
    text = message.text.split(None, 1)[1]
    success = 0
    msg = await message.reply("Sending...")
    async for user in users.find():
        try:
            await client.send_message(user["user_id"], text)
            success += 1
            await asyncio.sleep(0.1)
        except: pass
    await msg.edit_text(f"📢 Broadcast Done. Success: {success}")

@app.on_message(filters.command("init") & filters.user(ADMIN_IDS))
async def initialize_db(client, message):
    for i in range(1, 5):
        await plans.update_one({"plan_id": i}, {"$setOnInsert": {"plan_id": i, "text": f"Plan {i}", "price": "₹0", "qr": "N/A", "contact": "@Admin", "codes": []}}, upsert=True)
    await plans.update_one({"plan_id": "settings"}, {"$setOnInsert": {"support_id": "@Admin"}}, upsert=True)
    await message.reply("✅ Bot Database Initialized!")

# ---------------- WEB SERVER ----------------

async def web_server():
    app_web = web.Application()
    app_web.router.add_get("/", lambda r: web.Response(text="Bot is running!"))
    runner = web.AppRunner(app_web)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()

async def main():
    await app.start()
    await web_server()
    print("BOT STARTED")
    await idle()

if __name__ == "__main__":
    app.run(main())
