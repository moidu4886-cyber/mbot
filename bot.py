import asyncio
import os
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserNotParticipant
from aiohttp import web

# --- CONFIG & DATABASE ---
API_ID = int(os.environ.get("API_ID", "18063763"))
API_HASH = os.environ.get("API_HASH", "f8bbe42c559b4c7dbddda61b7f0481bb")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8532782504:AAFTrD-xzud3XANvY_j24G-G_...")
ADMIN_ID = 7207674086 # നിങ്ങളുടെ ഐഡി ലോക്ക് ചെയ്തിരിക്കുന്നു

# മോംഗോ ഡിബി കണക്ഷൻ മുൻപ് ഉപയോഗിച്ച രീതിയിൽ തന്നെ തുടരും
try:
    from database import users, files, plans
except ImportError:
    pass

app = Client("bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

user_wait = {}
edit_state = {}

# --- WEB SERVER ---
async def handle_web(request): return web.Response(text="Bot Status: Online")
async def web_server():
    server = web.Application()
    server.add_routes([web.get("/", handle_web)])
    runner = web.AppRunner(server)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()

# --- HELPERS ---
async def is_subscribed(user_id):
    settings = await plans.find_one({"plan_id": "settings"})
    channel = settings.get("channel_id")
    if not channel or user_id == ADMIN_ID: return True
    try:
        await app.get_chat_member(channel, user_id)
        return True
    except UserNotParticipant: return False
    except: return True

# ==========================================
# 1. ADMIN COMMANDS (Locked to 7207674086)
# ==========================================

@app.on_message(filters.command("admin") & filters.user(ADMIN_ID))
async def admin_panel(client, message):
    buttons = [
        [InlineKeyboardButton("⚙️ Manage Plans", callback_data="manage_plans")],
        [InlineKeyboardButton("📊 Bot Stats & Contents", callback_data="full_stats")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="broadcast_msg")],
        [InlineKeyboardButton("🛠 Settings (QR/Channel)", callback_data="bot_settings")]
    ]
    await message.reply("👑 **Admin Control Panel**", reply_markup=InlineKeyboardMarkup(buttons))

@app.on_message(filters.command("init") & filters.user(ADMIN_ID))
async def init_db(client, message):
    for i in range(1, 5):
        await plans.update_one({"plan_id": i}, {"$setOnInsert": {"plan_id": i, "text": f"Plan {i}", "price": "0", "codes": []}}, upsert=True)
    await plans.update_one({"plan_id": "settings"}, {"$setOnInsert": {"support_id": "@Admin", "channel_id": "", "qr_file_id": ""}}, upsert=True)
    await message.reply("✅ Database Ready!")

@app.on_message(filters.command("index") & filters.user(ADMIN_ID))
async def index_file(client, message):
    if not message.reply_to_message or len(message.command) < 2:
        return await message.reply("Reply to a file: `/index 1`")
    pid = int(message.command[1])
    await files.insert_one({"plan": pid, "chat_id": message.reply_to_message.chat.id, "message_id": message.reply_to_message.id})
    await message.reply(f"✅ Saved to Plan {pid}")

# ==========================================
# 2. USER SIDE (Force Subscribe included)
# ==========================================

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    user_id = message.from_user.id
    await users.update_one({"user_id": user_id}, {"$set": {"active": True}}, upsert=True)
    
    if not await is_subscribed(user_id):
        settings = await plans.find_one({"plan_id": "settings"})
        channel_link = settings.get("channel_id").replace("@", "https://t.me/")
        btn = [[InlineKeyboardButton("📢 Join Channel", url=channel_link)], [InlineKeyboardButton("🔄 Check Again", callback_data="back_home")]]
        return await message.reply("⚠️ Please join our channel to use this bot!", reply_markup=InlineKeyboardMarkup(btn))

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Watch Now", callback_data="watch")],
        [InlineKeyboardButton("🆘 Support", callback_data="support_info")]
    ])
    await message.reply_text(f"👋 Welcome {message.from_user.mention}!", reply_markup=buttons)

# ==========================================
# 3. CALLBACK HANDLERS (Full Logic)
# ==========================================

@app.on_callback_query()
async def cb_handler(client, query):
    data = query.data
    user_id = query.from_user.id

    if data == "manage_plans" and user_id == ADMIN_ID:
        btns = [[InlineKeyboardButton(f"Plan {i}", callback_data=f"setup_p_{i}")] for i in range(1, 5)]
        btns.append([InlineKeyboardButton("🔙 Back", callback_data="admin_back")])
        await query.message.edit_text("Select Plan to Edit:", reply_markup=InlineKeyboardMarkup(btns))

    elif data == "full_stats" and user_id == ADMIN_ID:
        total_u = await users.count_documents({})
        text = f"📊 **Bot Statistics**\n\nTotal Users: {total_u}\n\n**Contents:**\n"
        for i in range(1, 5):
            count = await files.count_documents({"plan": i})
            text += f"▪️ Plan {i}: {count} items\n"
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]]))

    elif data.startswith("setup_p_") and user_id == ADMIN_ID:
        pid = int(data.split("_")[2])
        p = await plans.find_one({"plan_id": pid})
        cnt = await files.count_documents({"plan": pid})
        text = f"⚙️ **Plan {pid}**\nItems: {cnt}\nPrice: ₹{p['price']}\nDesc: {p['text']}"
        btns = [
            [InlineKeyboardButton("Edit Text", callback_data=f"edit_txt_{pid}"), InlineKeyboardButton("Edit Price", callback_data=f"edit_prc_{pid}")],
            [InlineKeyboardButton("➕ Add Code", callback_data=f"add_cd_{pid}"), InlineKeyboardButton("🗑 Clear Codes", callback_data=f"clr_cd_{pid}")],
            [InlineKeyboardButton("🔙 Back", callback_data="manage_plans")]
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(btns))

    elif data == "bot_settings" and user_id == ADMIN_ID:
        btns = [
            [InlineKeyboardButton("📸 Update QR", callback_data="set_qr"), InlineKeyboardButton("📢 Set Channel", callback_data="set_ch")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ]
        await query.message.edit_text("🛠 Bot Settings:", reply_markup=InlineKeyboardMarkup(btns))

    elif data == "watch":
        if not await is_subscribed(user_id): return await query.answer("Join channel first!", show_alert=True)
        btns = [[InlineKeyboardButton(f"Plan {i}", callback_data=f"u_plan_{i}")] for i in range(1, 5)]
        await query.message.edit_text("Select your plan:", reply_markup=InlineKeyboardMarkup(btns))

    elif data.startswith("u_plan_"):
        pid = int(data.split("_")[2])
        p = await plans.find_one({"plan_id": pid})
        text = f"📋 **{p['text']}**\n\n💰 Price: ₹{p['price']}"
        btns = [[InlineKeyboardButton("💳 Pay Now", callback_data=f"u_pay_{pid}"), InlineKeyboardButton("🔓 Unlock", callback_data=f"u_unl_{pid}")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(btns))

    elif data.startswith("u_pay_"):
        pid = int(data.split("_")[2])
        p = await plans.find_one({"plan_id": pid})
        s = await plans.find_one({"plan_id": "settings"})
        if s.get("qr_file_id"):
            await query.message.reply_photo(s['qr_file_id'], caption=f"Scan & Pay ₹{p['price']} for Plan {pid}\nThen send the code.")
        else:
            await query.answer("QR Code not set by Admin!", show_alert=True)

    elif data.startswith("u_unl_"):
        user_wait[user_id] = int(data.split("_")[2])
        await query.message.reply("🔑 Send the Unlock Code:")

    elif data == "admin_back":
        await admin_panel(client, query.message)
        await query.message.delete()

    # Edit State Handlers
    if "edit_" in data or "set_" in data or "add_cd" in data:
        edit_state[user_id] = data
        await query.message.reply("💬 Send the new value/image:")

# ==========================================
# 4. TEXT & PHOTO HANDLER (For Settings)
# ==========================================

@app.on_message(filters.private)
async def handle_all(client, message):
    user_id = message.from_user.id
    if message.text and message.text.startswith("/"): return

    # Admin Settings Handler
    if user_id == ADMIN_ID and user_id in edit_state:
        state = edit_state[user_id]
        if state == "set_qr" and message.photo:
            await plans.update_one({"plan_id": "settings"}, {"$set": {"qr_file_id": message.photo.file_id}}, upsert=True)
            await message.reply("✅ QR Updated!")
        elif "edit_txt" in state:
            pid = int(state.split("_")[2])
            await plans.update_one({"plan_id": pid}, {"$set": {"text": message.text}})
            await message.reply("✅ Text Updated!")
        elif "edit_prc" in state:
            pid = int(state.split("_")[2])
            await plans.update_one({"plan_id": pid}, {"$set": {"price": message.text}})
            await message.reply("✅ Price Updated!")
        elif "add_cd" in state:
            pid = int(state.split("_")[2])
            await plans.update_one({"plan_id": pid}, {"$push": {"codes": message.text.upper()}})
            await message.reply("✅ Code Added!")
        elif state == "set_ch":
            await plans.update_one({"plan_id": "settings"}, {"$set": {"channel_id": message.text}})
            await message.reply("✅ Channel ID Set!")
        
        del edit_state[user_id]
        return

    # User Unlock Handler
    if user_id in user_wait:
        pid = user_wait[user_id]
        p = await plans.find_one({"plan_id": pid, "codes": message.text.upper()})
        if p:
            await message.reply("✅ Code Valid! Sending files...")
            async for f in files.find({"plan": pid}):
                await client.copy_message(user_id, f["chat_id"], f["message_id"])
            del user_wait[user_id]
        else:
            await message.reply("❌ Invalid Code!")

# --- RUN ---
async def main():
    await web_server()
    await app.start()
    print("🚀 PRO BOT LIVE")
    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
