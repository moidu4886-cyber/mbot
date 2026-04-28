import asyncio
import os
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserIsBlocked, InputUserDeactivated, FloodWait
from aiohttp import web

# --- DATABASE & CONFIG ---
# (നിങ്ങളുടെ config.py, database.py എന്നിവയിലെ വിവരങ്ങൾ ഇവിടെ ഉപയോഗിക്കുന്നു)
try:
    from config import *
    from database import users, files, plans
except ImportError:
    # നേരിട്ട് വേരിയബിൾസ് എടുക്കുന്നു (Fallback)
    API_ID = int(os.environ.get("API_ID"))
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("BOT_TOKEN")

# --- ADMIN ID FIX ---
# Koyeb-ൽ നിന്ന് വരുന്ന സ്ട്രിംഗിനെ ലിസ്റ്റ് ആക്കി മാറ്റുന്നു
raw_admin_ids = os.environ.get("ADMIN_IDS", "7207674086")
ADMIN_IDS = [int(i.strip()) for i in raw_admin_ids.split(",") if i.strip()]

# Bot initialization
app = Client("bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

# States
user_wait = {}
edit_state = {}

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
        f"👋 **Welcome {message.from_user.mention}!**\n\nAccess premium content easily.",
        reply_markup=buttons
    )

# ---------------- NAVIGATION ----------------

@app.on_callback_query(filters.regex("^back_home$|^watch$"))
async def navigation(client, query):
    user_id = query.from_user.id
    if user_id in user_wait: del user_wait[user_id]
    await query.answer()
    
    if query.data == "back_home":
        await start(client, query.message)
        await query.message.delete()
    else:
        buttons = [[InlineKeyboardButton(f"Plan {i}", callback_data=f"plan_{i}")] for i in range(1, 5)]
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back_home")])
        await query.message.edit_text("⚡ **Select Your Plan:**", reply_markup=InlineKeyboardMarkup(buttons))

# ---------------- PLAN DETAILS & UNLOCK ----------------

@app.on_callback_query(filters.regex("^plan_"))
async def plan_details(client, query):
    await query.answer()
    pid = int(query.data.split("_")[1])
    p = await plans.find_one({"plan_id": pid})
    if not p: return await query.message.edit_text("❌ Plan not found! Run /init first.")

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

    if message.text.startswith("/"):
        return

    # ADMIN EDIT LOGIC
    if user_id in ADMIN_IDS and user_id in edit_state:
        action, pid = edit_state[user_id]
        if pid == "settings":
            await plans.update_one({"plan_id": "settings"}, {"$set": {action: message.text.strip()}}, upsert=True)
            await message.reply(f"✅ Updated Support ID to: {message.text}")
        elif action == "add_code":
            await plans.update_one({"plan_id": pid}, {"$push": {"codes": message.text.strip().upper()}})
            await message.reply(f"✅ Code added to Plan {pid}")
        else:
            await plans.update_one({"plan_id": pid}, {"$set": {action: message.text.strip()}})
            await message.reply(f"✅ Updated Plan {pid} {action}")
        del edit_state[user_id]
        return

    # USER UNLOCK LOGIC
    if user_id in user_wait:
        pid = user_wait[user_id]
        code = message.text.strip().upper()
        plan_data = await plans.find_one({"plan_id": pid, "codes": {"$in": [code]}})
        
        if not plan_data:
            return await message.reply("❌ **Invalid Code!** Try again.")

        await message.reply("✅ **Verified!** Sending files...")
        async for f in files.find({"plan": pid}):
            try:
                await client.copy_message(message.chat.id, f["chat_id"], f["message_id"], protect_content=True)
                await asyncio.sleep(0.5) 
            except: pass
        del user_wait[user_id]
    else:
        if user_id not in ADMIN_IDS:
            await message.reply("❓ Select a plan and click **Unlock** first.")

# ---------------- ADMIN COMMANDS (FIXED FILTERS) ----------------

@app.on_message(filters.command("setup") & filters.private)
async def admin_panel(client, message):
    if message.from_user.id not in ADMIN_IDS: return
    buttons = [
        [InlineKeyboardButton("📊 Stats", callback_data="admin_stats")],
        [InlineKeyboardButton("✏️ Plan 1", callback_data="edit_1"), InlineKeyboardButton("✏️ Plan 2", callback_data="edit_2")],
        [InlineKeyboardButton("✏️ Plan 3", callback_data="edit_3"), InlineKeyboardButton("✏️ Plan 4", callback_data="edit_4")],
        [InlineKeyboardButton("👤 Support ID", callback_data="set_global_admin")]
    ]
    await message.reply("🛠 **Admin Dashboard**", reply_markup=InlineKeyboardMarkup(buttons))

@app.on_callback_query(filters.regex("^edit_|^set_|^add_code_|^admin_stats|^back_admin"))
async def admin_callbacks(client, query):
    if query.from_user.id not in ADMIN_IDS: return
    await query.answer()
    data = query.data

    if data.startswith("edit_"):
        pid = int(data.split("_")[1])
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("Text", callback_data=f"set_text_{pid}"), InlineKeyboardButton("Price", callback_data=f"set_price_{pid}")],
            [InlineKeyboardButton("QR", callback_data=f"set_qr_{pid}"), InlineKeyboardButton("Contact", callback_data=f"set_contact_{pid}")],
            [InlineKeyboardButton("➕ Add Code", callback_data=f"add_code_{pid}")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_admin")]
        ])
        await query.message.edit_text(f"⚙️ Editing Plan {pid}", reply_markup=buttons)

    elif data.startswith("set_") or data.startswith("add_code_"):
        s = data.split("_")
        if s[0] == "add": edit_state[query.from_user.id] = ("add_code", int(s[2]))
        else: edit_state[query.from_user.id] = (s[1], int(s[2]))
        await query.message.reply("💬 Send the new value:")

    elif data == "set_global_admin":
        edit_state[query.from_user.id] = ("support_id", "settings")
        await query.message.reply("💬 Send new Support ID:")

    elif data == "admin_stats":
        total = await users.count_documents({})
        await query.message.edit_text(f"📊 Total Users: {total}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_admin")]]))
    
    elif data == "back_admin":
        await admin_panel(client, query.message)
        await query.message.delete()

@app.on_message(filters.command("index") & filters.private)
async def index_file(client, message):
    if message.from_user.id not in ADMIN_IDS: return
    if not message.reply_to_message: return await message.reply("Reply to a file.")
    try:
        pid = int(message.text.split()[1])
        reply = message.reply_to_message
        await files.insert_one({"plan": pid, "chat_id": reply.chat.id, "message_id": reply.id})
        await message.reply(f"✅ Indexed to Plan {pid}")
    except: await message.reply("Usage: `/index 1`")

@app.on_message(filters.command("init") & filters.private)
async def initialize_db(client, message):
    if message.from_user.id not in ADMIN_IDS: return
    for i in range(1, 5):
        await plans.update_one({"plan_id": i}, {"$setOnInsert": {"plan_id": i, "text": f"Plan {i}", "price": "₹0", "codes": []}}, upsert=True)
    await plans.update_one({"plan_id": "settings"}, {"$setOnInsert": {"support_id": "@Admin"}}, upsert=True)
    await message.reply("✅ Database Initialized!")

# ---------------- RUN ----------------

async def main():
    await app.start()
    # aiohttp server logic... (if needed)
    print("BOT STARTED SUCCESSFULLY")
    await idle()

if __name__ == "__main__":
    app.run(main())
