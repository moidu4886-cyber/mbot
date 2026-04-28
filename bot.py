import asyncio
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserIsBlocked, InputUserDeactivated, FloodWait
from aiohttp import web
from config import *
from database import users, files, plans

# Bot initialization
app = Client("bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

# States to track admin/user actions
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
    await add_user(message.from_user.id)
    
    support_id = await get_support_id()
    support_url = f"https://t.me/{support_id.replace('@','')}"

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Watch Now", callback_data="watch")],
        [InlineKeyboardButton("🔗 Share Bot", switch_inline_query="Check this premium bot!")],
        [InlineKeyboardButton("🆘 Contact Admin / Help", url=support_url)] # Permanent Help Button
    ])
    
    await message.reply_text(
        f"👋 **Welcome {message.from_user.mention}!**\n\nAccess premium content easily with our plan-based system.",
        reply_markup=buttons
    )

# ---------------- NAVIGATION ----------------

@app.on_callback_query(filters.regex("^back_home$"))
async def back_home(client, query):
    await start(client, query.message)
    await query.message.delete()

@app.on_callback_query(filters.regex("^watch$"))
async def watch_menu(client, query):
    buttons = [
        [InlineKeyboardButton(f"Plan {i}", callback_data=f"plan_{i}")] for i in range(1, 5)
    ]
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back_home")])
    
    await query.message.edit_text(
        "⚡ **Select Your Plan:**\nChoose a plan to unlock exclusive content.",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ---------------- PLAN DETAILS ----------------

@app.on_callback_query(filters.regex("^plan_"))
async def plan_details(client, query):
    pid = int(query.data.split("_")[1])
    p = await plans.find_one({"plan_id": pid})
    
    if not p:
        return await query.answer("❌ Plan data not initialized!", show_alert=True)

    text = (
        f"📋 **{p.get('text', 'Premium Plan')}**\n\n"
        f"💰 **Price:** {p.get('price', 'N/A')}\n"
        f"📞 **Admin:** {p.get('contact', 'Contact Admin')}\n\n"
        "Click Pay to see payment details or Unlock if you have a code."
    )
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Pay Now", callback_data=f"pay_{pid}"),
         InlineKeyboardButton("🔓 Unlock", callback_data=f"unlock_{pid}")],
        [InlineKeyboardButton("🔙 Back", callback_data="watch")]
    ])
    
    await query.message.edit_text(text, reply_markup=buttons)

@app.on_callback_query(filters.regex("^pay_"))
async def pay_info(client, query):
    pid = int(query.data.split("_")[1])
    p = await plans.find_one({"plan_id": pid})
    
    back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"plan_{pid}")]])
    await query.message.edit_text(
        f"💳 **Payment Details for Plan {pid}**\n\n{p.get('qr', 'Contact admin for payment details.')}",
        reply_markup=back_btn
    )

# ---------------- UNLOCK SYSTEM ----------------

@app.on_callback_query(filters.regex("^unlock_"))
async def ask_unlock(client, query):
    pid = int(query.data.split("_")[1])
    user_wait[query.from_user.id] = pid
    await query.message.reply("🔑 **Please send your Unlock Code:**")

@app.on_message(filters.text & filters.private)
async def handle_text(client, message):
    user_id = message.from_user.id

    # --- ADMIN EDITING LOGIC ---
    if user_id in ADMIN_IDS and user_id in edit_state:
        action, pid = edit_state[user_id]
        
        if pid == "settings":
            await plans.update_one({"plan_id": "settings"}, {"$set": {action: message.text}}, upsert=True)
            await message.reply(f"✅ **Global Support ID updated to: {message.text}**")
        else:
            await plans.update_one({"plan_id": pid}, {"$set": {action: message.text}})
            await message.reply(f"✅ **Plan {pid} {action} updated successfully!**")
        
        del edit_state[user_id]
        return

    # --- USER UNLOCK LOGIC ---
    if user_id in user_wait:
        pid = user_wait[user_id]
        code = message.text.strip()
        
        plan_data = await plans.find_one({"plan_id": pid, "codes": {"$in": [code]}})
        
        if not plan_data:
            return await message.reply("❌ **Invalid Code!** Please try again or contact admin.")

        await message.reply("✅ **Code Verified!** Sending your files now...")
        
        file_list = files.find({"plan": pid})
        async for f in file_list:
            try:
                await client.copy_message(
                    chat_id=message.chat.id,
                    from_chat_id=f["chat_id"],
                    message_id=f["message_id"],
                    protect_content=True
                )
                await asyncio.sleep(0.5) # Protection against flood
            except:
                pass
        
        del user_wait[user_id]

# ---------------- ADMIN: INDEXING ----------------

@app.on_message(filters.command("index") & filters.user(ADMIN_IDS))
async def index_file(client, message):
    if not message.reply_to_message:
        return await message.reply("❌ Reply to a file to index it.")
    
    try:
        pid = int(message.text.split()[1])
    except:
        return await message.reply("❌ Usage: `/index 1` (reply to a file)")

    reply = message.reply_to_message
    await files.insert_one({
        "plan": pid,
        "chat_id": reply.chat.id,
        "message_id": reply.id
    })
    await message.reply(f"✅ File indexed to **Plan {pid}**")

# ---------------- ADMIN: BROADCAST ----------------

@app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast(client, message):
    if len(message.text.split()) < 2:
        return await message.reply("❌ Usage: `/broadcast Hello` ")
    
    broadcast_msg = message.text.split(None, 1)[1]
    msg = await message.reply("🚀 **Broadcast Started...**")
    
    success, blocked, failed = 0, 0, 0
    async for user in users.find():
        try:
            await client.send_message(user["user_id"], broadcast_msg)
            success += 1
            await asyncio.sleep(0.1)
        except UserIsBlocked:
            blocked += 1
        except:
            failed += 1
        
    await msg.edit_text(f"📢 **Broadcast Done!**\n\n✅ Success: {success}\n🚫 Blocked: {blocked}\n❌ Failed: {failed}")

# ---------------- ADMIN: DASHBOARD ----------------

@app.on_message(filters.command("setup") & filters.user(ADMIN_IDS))
async def admin_panel(client, message):
    buttons = [
        [InlineKeyboardButton("📊 Detailed Stats", callback_data="admin_stats")],
        [InlineKeyboardButton("✏️ Edit Plan 1", callback_data="edit_1"), InlineKeyboardButton("✏️ Edit Plan 2", callback_data="edit_2")],
        [InlineKeyboardButton("✏️ Edit Plan 3", callback_data="edit_3"), InlineKeyboardButton("✏️ Edit Plan 4", callback_data="edit_4")],
        [InlineKeyboardButton("👤 Change Global Support ID", callback_data="set_global_admin")]
    ]
    await message.reply("🛠 **Admin Control Panel**", reply_markup=InlineKeyboardMarkup(buttons))

@app.on_callback_query(filters.regex("^admin_stats$"))
async def admin_stats(client, query):
    total = await users.count_documents({})
    file_counts = ""
    for i in range(1, 5):
        count = await files.count_documents({"plan": i})
        file_counts += f"Plan {i}: {count} files\n"

    await query.message.edit_text(
        f"📊 **Bot Statistics**\n\n👥 Total Users: {total}\n\n📂 **Files:**\n{file_counts}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_admin")]])
    )

@app.on_callback_query(filters.regex("^back_admin$"))
async def back_admin(client, query):
    await admin_panel(client, query.message)
    await query.message.delete()

@app.on_callback_query(filters.regex("^edit_"))
async def edit_plan_menu(client, query):
    pid = int(query.data.split("_")[1])
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Description", callback_data=f"set_text_{pid}"),
         InlineKeyboardButton("Price", callback_data=f"set_price_{pid}")],
        [InlineKeyboardButton("QR/Payment", callback_data=f"set_qr_{pid}"),
         InlineKeyboardButton("Contact", callback_data=f"set_contact_{pid}")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_admin")]
    ])
    await query.message.edit_text(f"⚙️ **Editing Plan {pid}**", reply_markup=buttons)

@app.on_callback_query(filters.regex("^set_"))
async def ask_for_update(client, query):
    data = query.data.split("_")
    if len(data) == 3: # For Plans
        _, action, pid = data
        edit_state[query.from_user.id] = (action, int(pid))
    else: # For Global Support ID
        edit_state[query.from_user.id] = ("support_id", "settings")
    
    await query.message.reply(f"💬 Send the new value:")

@app.on_callback_query(filters.regex("^set_global_admin$"))
async def set_global_admin(client, query):
    edit_state[query.from_user.id] = ("support_id", "settings")
    await query.message.reply("💬 **അഡ്മിൻ കോൺടാക്ട് ഐഡി (Username) അയക്കുക:**\n(Example: @MyUsername)")

# ---------------- INITIALIZATION ----------------

@app.on_message(filters.command("init") & filters.user(ADMIN_IDS))
async def initialize_db(client, message):
    # Initialize Plans
    for i in range(1, 5):
        default_plan = {
            "plan_id": i,
            "text": f"Premium Plan {i}",
            "price": "₹499",
            "qr": "Send to UPI: example@upi",
            "contact": "@AdminUsername",
            "codes": [f"CODE{i}"]
        }
        await plans.update_one({"plan_id": i}, {"$setOnInsert": default_plan}, upsert=True)
    
    # Initialize Global Settings
    await plans.update_one(
        {"plan_id": "settings"},
        {"$setOnInsert": {"support_id": "@AdminUsername"}},
        upsert=True
    )
    await message.reply("✅ **Bot Initialized Successfully!**")

# ---------------- WEB SERVER & RUN ----------------

async def web_server():
    app_web = web.Application()
    app_web.router.add_get("/", lambda r: web.Response(text="Bot Alive"))
    runner = web.AppRunner(app_web)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()

async def main():
    await app.start()
    await web_server()
    print(">>> BOT RUNNING <<<")
    await idle()

if __name__ == "__main__":
    app.run(main())
