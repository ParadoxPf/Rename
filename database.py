from pymongo import MongoClient
from datetime import datetime, timedelta
from config import Config

client = MongoClient(Config.MONGO_URI)
db = client[Config.MONGO_DBNAME]

users = db["users"]         # {_id: user_id, daily_count, daily_reset, limit, is_admin, premium, thumb, caption}
logs = db["logs"]           # logging actions
broadcasts = db["broadcasts"]

def ensure_user(user_id):
    u = users.find_one({"_id": user_id})
    if not u:
        users.insert_one({
            "_id": user_id,
            "daily_count": 0,
            "daily_reset": datetime.utcnow(),
            "limit": Config.DEFAULT_DAILY_LIMIT,
            "is_admin": user_id in Config.ADMINS,
            "premium": False,
            "thumb": None,
            "caption": None
        })
        return users.find_one({"_id": user_id})
    return u

def reset_if_needed(user_doc):
    reset_at = user_doc.get("daily_reset", datetime.utcnow() - timedelta(days=1))
    if datetime.utcnow() - reset_at >= timedelta(days=1):
        users.update_one({"_id": user_doc["_id"]}, {"$set": {"daily_count": 0, "daily_reset": datetime.utcnow()}})

def increment_count(user_id):
    users.update_one({"_id": user_id}, {"$inc": {"daily_count": 1}})

def set_limit(user_id, limit):
    users.update_one({"_id": user_id}, {"$set": {"limit": int(limit)}})

def set_admin(user_id, is_admin=True):
    users.update_one({"_id": user_id}, {"$set": {"is_admin": bool(is_admin)}})

def set_premium(user_id, premium=True):
    users.update_one({"_id": user_id}, {"$set": {"premium": bool(premium)}})

def set_thumb(user_id, thumb_path):
    users.update_one({"_id": user_id}, {"$set": {"thumb": thumb_path}})

def set_caption(user_id, caption):
    users.update_one({"_id": user_id}, {"$set": {"caption": caption}})

def log_action(doc):
    doc["time"] = datetime.utcnow()
    logs.insert_one(doc)
