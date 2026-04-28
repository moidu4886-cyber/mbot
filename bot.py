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
user_wait = {}
edit_state = {}

# ---------------- HELPER FUNCTIONS ----------------

async def add_user(user_id):
    await users.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "active": True, "blocked": False}},
        upsert=True
    )

# ---------------- START MENU ----------------

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await add_user(message.from_user.id)
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Watch Now", callback_data="watch")],
        [InlineKeyboardButton("🔗 Share Bot", switch_inline_query="Check this out!")]
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

    # Admin Editing Logic
    if user_id in ADMIN_IDS and user_id in edit_state:
        action, pid = edit_state[user_id]
        await plans.update_one({"plan_id": pid}, {"$set": {action: message.text}})
        del edit_state[user_id]
        return await message.reply(f"✅ **Plan {pid} {action} updated successfully!**")

    # Code Unlock Logic
    if user_id in user_wait:
        pid = user_wait[user_id]
        code = message.text.strip()
        
        # Check if code exists in that specific plan
        plan_data = await plans.find_one({"plan_id": pid, "codes": {"$in": [code]}})
        
        if not plan_data:
            return await message.reply("❌ **Invalid Code!** Please try again or contact admin.")

        await message.reply("✅ **Code Verified!** Sending your files now...")
        
        # Parallel File Sending with Protection
        file_list = files.find({"plan": pid})
        tasks = []
        async for f in file_list:
            tasks.append(client.copy_message(
                chat_id=message.chat.id,
                from_chat_id=f["chat_id"],
                message_id=f["message_id"],
                protect_content=True
            ))
        
        if tasks:
            await asyncio.gather(*tasks)
            # Optional: Remove code after use to prevent reuse
            # await plans.update_one({"plan_id": pid}, {"$pull": {"codes": code}})
        else:
            await message.reply("⚠️ No files found in this plan.")
        
        del user_wait[user_id]

# ---------------- ADMIN: INDEXING ----------------

@app.on_message(filters.command("index") & filters.user(ADMIN_IDS))
async def index_file(client, message):
    if not message.reply_to_message:
        return await message.reply("❌ Reply to a file/media to index it.")
    
    try:
        pid = int(message.text.split()[1])
    except:
        return await message.reply("❌ Usage: `/index 1` (replying to a file)")

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
        return await message.reply("❌ Usage: `/broadcast Hello Users`Color")
    
    broadcast_msg = message.text.split(None, 1)[1]
    msg = await message.reply("🚀 **Broadcast Started...**")
    
    success, blocked, failed = 0, 0, 0
    async for user in users.find():
        try:
            await client.send_message(user["user_id"], broadcast_msg)
            success += 1
        except UserIsBlocked:
            blocked += 1
            await users.update_one({"user_id": user["user_id"]}, {"$set": {"active": False, "blocked": True}})
        except InputUserDeactivated:
            failed += 1
            await users.update_one({"user_id": user["user_id"]}, {"$set": {"active": False, "deleted": True}})
        except FloodWait as e:
            await asyncio.sleep(e.value)
            await client.send_message(user["user_id"], broadcast_msg)
            success += 1
        except:
            failed += 1
        
    await msg.edit_text(
        f"📢 **Broadcast Completed!**\n\n"
        f"✅ Success: {success}\n"
        f"🚫 Blocked: {blocked}\n"
        f"❌ Failed/Deleted: {failed}"
    )

# ---------------- ADMIN: DASHBOARD ----------------

@app.on_message(filters.command("setup") & filters.user(ADMIN_IDS))
async def admin_panel(client, message):
    buttons = [
        [InlineKeyboardButton("📊 Detailed Stats", callback_data="admin_stats")],
        [InlineKeyboardButton("✏️ Edit Plan 1", callback_data="edit_1"), InlineKeyboardButton("✏️ Edit Plan 2", callback_data="edit_2")],
        [InlineKeyboardButton("✏️ Edit Plan 3", callback_data="edit_3"), InlineKeyboardButton("✏️ Edit Plan 4", callback_data="edit_4")]
    ]
    await message.reply("🛠 **Admin Control Panel**", reply_markup=InlineKeyboardMarkup(buttons))

@app.on_callback_query(filters.regex("^admin_stats$"))
async def admin_stats(client, query):
    total = await users.count_documents({})
    active = await users.count_documents({"active": True})
    blocked = await users.count_documents({"blocked": True})
    deleted = await users.count_documents({"deleted": True})
    
    file_counts = ""
    for i in range(1, 5):
        count = await files.count_documents({"plan": i})
        file_counts += f"Plan {i}: {count} files\n"

    await query.message.edit_text(
        f"📊 **Bot Statistics**\n\n"
        f"👥 Total Users: {total}\n"
        f"🟢 Active: {active}\n"
        f"🚫 Blocked: {blocked}\n"
        f"🗑 Deleted: {deleted}\n\n"
        f"📂 **Plan-wise Files:**\n{file_counts}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_admin")]])
    )

@app.on_callback_query(filters.regex("^back_admin$"))
async def back_admin(client, query):
    await admin_panel(client, query.message)
    await query.message.delete()

# ---------------- ADMIN: EDITING ----------------

@app.on_callback_query(filters.regex("^edit_"))
async def edit_plan_menu(client, query):
    pid = int(query.data.split("_")[1])
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Description", callback_data=f"set_text_{pid}"),
         InlineKeyboardButton("Price", callback_data=f"set_price_{pid}")],
        [InlineKeyboardButton("QR/Payment", callback_data=f"set_qr_{pid}"),
         InlineKeyboardButton("Admin Contact", callback_data=f"set_contact_{pid}")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_admin")]
    ])
    await query.message.edit_text(f"⚙️ **Editing Plan {pid}**\nSelect what to change:", reply_markup=buttons)

@app.on_callback_query(filters.regex("^set_"))
async def ask_for_update(client, query):
    _, action, pid = query.data.split("_")
    edit_state[query.from_user.id] = (action, int(pid))
    await query.message.reply(f"💬 Send the new **{action}** for Plan {pid}:")

# ---------------- INITIALIZATION ----------------

@app.on_message(filters.command("init") & filters.user(ADMIN_IDS))
async def initialize_db(client, message):
    for i in range(1, 5):
        default_plan = {
            "plan_id": i,
            "text": f"Standard Plan {i}",
            "price": "₹499",
            "qr": "Send payment to UPI ID: example@upi",
            "contact": "@AdminUsername",
            "codes": [f"CODE{i}ABC", f"PREMIUM{i}"]
        }
        await plans.update_one({"plan_id": i}, {"$setOnInsert": default_plan}, upsert=True)
    await message.reply("✅ **Default Plans Initialized!**")

# ---------------- WEB SERVER & RUN ----------------

async def web_server():
    app_web = web.Application()
    app_web.router.add_get("/", lambda r: web.Response(text="Bot is running!"))
    runner = web.AppRunner(app_web)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()

async def main():
    await app.start()
    await web_server()
    print(">>> BOT STARTED SUCCESSFULLY <<<")
    await idle()

if __name__ == "__main__":
    app.run(main())
