import asyncio
import os
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserIsBlocked, InputUserDeactivated, FloodWait
from aiohttp import web

# --- CONFIG & DATABASE ---
try:
    from config import *
    from database import users, files, plans
except ImportError:
    API_ID = int(os.environ.get("API_ID", "18063763"))
    API_HASH = os.environ.get("API_HASH", "f8bbe42c559b4c7dbddda61b7f0481bb")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "8532782504:AAFTrD-xzud3XANvY_j24G-G_...")

# --- FIXED ADMIN ID ---
MY_ID = 7207674086 

# Bot initialization
app = Client("bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

# States
user_wait = {}
edit_state = {}

# ---------------- WEB SERVER (For Koyeb Health Check) ----------------

async def handle_web(request):
    return web.Response(text="Bot Status: Online and Healthy")

async def web_server():
    server = web.Application()
    server.add_routes([web.get("/", handle_web)])
    runner = web.AppRunner(server)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8000)
    await site.start()
    print("✅ Web Server started on port 8000")

# ---------------- START MENU ----------------

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    user_id = message.from_user.id
    await users.update_one({"user_id": user_id}, {"$set": {"active": True}}, upsert=True)
    
    if user_id in user_wait: del user_wait[user_id]
    if user_id in edit_state: del edit_state[user_id]
        
    settings = await plans.find_one({"plan_id": "settings"})
    support_id = settings.get("support_id", "@Admin") if settings else "@Admin"
    support_url = f"https://t.me/{support_id.replace('@','')}"

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Watch Now", callback_data="watch")],
        [InlineKeyboardButton("🔗 Share Bot", switch_inline_query="Check this!")],
        [InlineKeyboardButton("🆘 Help / Support", url=support_url)]
    ])
    
    await message.reply_text(
        f"👋 **Welcome {message.from_user.mention}!**\n\nYour ID is: `{user_id}`\nAccess premium content easily with our plans.",
        reply_markup=buttons
    )

# ---------------- NAVIGATION ----------------

@app.on_callback_query(filters.regex("^back_home$|^watch$"))
async def navigation(client, query):
    await query.answer()
    if query.data == "back_home":
        await start(client, query.message)
        await query.message.delete()
    else:
        buttons = [[InlineKeyboardButton(f"Plan {i}", callback_data=f"plan_{i}")] for i in range(1, 5)]
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back_home")])
        await query.message.edit_text("⚡ **Select Your Plan:**", reply_markup=InlineKeyboardMarkup(buttons))

# ---------------- PLAN & UNLOCK ----------------

@app.on_callback_query(filters.regex("^plan_|^unlock_"))
async def plan_unlock(client, query):
    await query.answer()
    data = query.data.split("_")
    pid = int(data[1])
    
    if data[0] == "plan":
        p = await plans.find_one({"plan_id": pid})
        if not p: return await query.message.edit_text("❌ Please run /init first!")
        text = f"📋 **{p.get('text')}**\n\n💰 Price: {p.get('price')}\n📞 Contact: {p.get('contact')}"
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Pay Now", callback_data=f"pay_{pid}"), InlineKeyboardButton("🔓 Unlock", callback_data=f"unlock_{pid}")],
            [InlineKeyboardButton("🔙 Back", callback_data="watch")]
        ])
        await query.message.edit_text(text, reply_markup=buttons)
    else:
        user_wait[query.from_user.id] = pid 
        await query.message.reply(f"🔑 **Send Unlock Code for Plan {pid}:**")

# ---------------- TEXT HANDLER (ADMIN & USER) ----------------

@app.on_message(filters.text & filters.private)
async def handle_text(client, message):
    user_id = message.from_user.id
    if message.text.startswith("/"): return

    # 1. ADMIN EDIT LOGIC
    if user_id == MY_ID and user_id in edit_state:
        action, pid = edit_state[user_id]
        val = message.text.strip()
        if pid == "settings":
            await plans.update_one({"plan_id": "settings"}, {"$set": {action: val}}, upsert=True)
        elif action == "add_code":
            await plans.update_one({"plan_id": pid}, {"$push": {"codes": val.upper()}})
        else:
            await plans.update_one({"plan_id": pid}, {"$set": {action: val}})
        await message.reply(f"✅ Updated {action} successfully!")
        del edit_state[user_id]
        return

    # 2. USER UNLOCK LOGIC
    if user_id in user_wait:
        pid = user_wait[user_id]
        code = message.text.strip().upper()
        plan_data = await plans.find_one({"plan_id": pid, "codes": code})
        
        if plan_data:
            await message.reply("✅ **Code Verified!** Sending files...")
            async for f in files.find({"plan": pid}):
                try:
                    await client.copy_message(message.chat.id, f["chat_id"], f["message_id"], protect_content=True)
                    await asyncio.sleep(0.5)
                except: pass
            del user_wait[user_id]
        else:
            await message.reply("❌ **Invalid Code!**")
    else:
        if user_id != MY_ID:
            await message.reply("❓ Please select a plan and click **Unlock** first.")

# ---------------- ADMIN COMMANDS (STRICT FILTER) ----------------

@app.on_message(filters.command("setup") & filters.user(MY_ID))
async def setup_cmd(client, message):
    buttons = [[InlineKeyboardButton(f"⚙️ Manage Plan {i}", callback_data=f"edit_{i}")] for i in range(1, 5)]
    buttons.append([InlineKeyboardButton("👤 Global Support ID", callback_data="set_global_admin")])
    await message.reply("🛠 **Admin Control Panel**", reply_markup=InlineKeyboardMarkup(buttons))

@app.on_message(filters.command("init") & filters.user(MY_ID))
async def init_cmd(client, message):
    for i in range(1, 5):
        await plans.update_one({"plan_id": i}, {"$setOnInsert": {"plan_id": i, "text": f"Plan {i}", "price": "₹0", "contact": "@Admin", "codes": []}}, upsert=True)
    await plans.update_one({"plan_id": "settings"}, {"$setOnInsert": {"support_id": "@Admin"}}, upsert=True)
    await message.reply("✅ **Database Initialized!**")

@app.on_message(filters.command("index") & filters.user(MY_ID))
async def index_cmd(client, message):
    if not message.reply_to_message or len(message.command) < 2:
        return await message.reply("Reply to a file with `/index 1`")
    pid = int(message.command[1])
    await files.insert_one({"plan": pid, "chat_id": message.reply_to_message.chat.id, "message_id": message.reply_to_message.id})
    await message.reply(f"✅ File indexed to **Plan {pid}**")

# ---------------- ADMIN CALLBACKS ----------------

@app.on_callback_query(filters.regex("^edit_|^set_|^add_code_|^back_admin"))
async def admin_callbacks(client, query):
    if query.from_user.id != MY_ID: return
    await query.answer()
    data = query.data

    if data.startswith("edit_"):
        pid = int(data.split("_")[1])
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("Edit Text", callback_data=f"set_text_{pid}"), InlineKeyboardButton("Edit Price", callback_data=f"set_price_{pid}")],
            [InlineKeyboardButton("➕ Add Code", callback_data=f"add_code_{pid}")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_admin")]
        ])
        await query.message.edit_text(f"⚙️ **Managing Plan {pid}**", reply_markup=buttons)
    elif data == "back_admin":
        await setup_cmd(client, query.message)
        await query.message.delete()
    elif "set_" in data or "add_code_" in data:
        s = data.split("_")
        action = s[1] if "set" in data else "add_code"
        pid = int(s[2])
        edit_state[query.from_user.id] = (action, pid)
        await query.message.reply(f"💬 Send the new value for **{action}**:")

# ---------------- RUNNER ----------------

async def main():
    await web_server()
    await app.start()
    print("🚀 BOT IS LIVE")
    await idle()
    await app.stop()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
