from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI

client = AsyncIOMotorClient(MONGO_URI)
db = client["video_bot"]

users = db["users"]
files = db["files"]
plans = db["plans"]
