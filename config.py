from environs import Env

import logging

env = Env()
env.read_env()


API_KEY = env("TELEGRAM_BOT_API_KEY")
PORT = env.int("PORT", 5000)
LOGLEVEL = env.log_level("LOGLEVEL", logging.INFO)

CONVERSATION_MODEL_LOCAL_URL = "file:conversation_tree.textproto"
CONVERSATION_MODEL_URL = env.str("CONVERSATION_MODEL_URL",
                                 CONVERSATION_MODEL_LOCAL_URL)

REDIS_URL = env.str("REDIS_TLS_URL", "redis://localhost:6379")
PERSIST_SESSIONS = env.bool("PERSIST_SESSIONS", False)
PERSIST_METRICS = env.bool("PERSIST_METRICS", False)

DEFAULT_WEBHOOK_URL = "https://telegram-bot-help-ua-ch.herokuapp.com"
WEBHOOK_URL = env.str("WEBHOOK_URL", DEFAULT_WEBHOOK_URL)
USE_WEBHOOK = env.bool("USE_WEBHOOK", False)
FEEDBACK_CHANNEL_ID = env.int("FEEDBACK_CHANNEL_ID", None)
BOT_STATE_ENCRYPTION_KEY = env.str("BOT_STATE_ENCRYPTION_KEY", None)
ADMIN_USERS = env.list("ADMIN_USERS", [
    "edgnkv",
    "lr2kate",
    "rprokofyev",
    "SymbioticMe",
    "thecrdev",
    "Zygimantas",
])
