import os

class Config:
    API_ID = int(os.environ.get("API_ID", "28467838"))
    API_HASH = os.environ.get("API_HASH", "89bcade52a8284a981c94a80f40fd676")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "6576656517:AAEJYpjxYK-KEy3d8ZYNRZJoLi7bIKmRrMY")

    # Optional
    SHORTNER_API = os.environ.get("SHORTNER_API", "fc8615a8e5996ddd180167f66153bd1d123ba009")
    SHORTNER_URL = os.environ.get("SHORTNER_URL", "https://linkshortify.com")

    BOT_USERNAME = "@Merge_Paradox_Bot"
    OWNER_ID = int(os.environ.get("OWNER_ID", "916551125"))
