from environs import Env

import logging

_env = Env()
_env.read_env()


API_KEY = _env("TELEGRAM_BOT_API_KEY")
PORT = _env.int("PORT", 5000)
LOGLEVEL = _env.log_level("LOGLEVEL", logging.INFO)

CONVERSATION_MODEL_LOCAL_URL = "file:conversation_tree.textproto"
CONVERSATION_MODEL_URL = _env.str("CONVERSATION_MODEL_URL",
                                  CONVERSATION_MODEL_LOCAL_URL)

REDIS_URL = _env.str("REDIS_TLS_URL", "redis://localhost:6379")
PERSIST_SESSIONS = _env.bool("PERSIST_SESSIONS", False)
PERSIST_METRICS = _env.bool("PERSIST_METRICS", False)

DEFAULT_WEBHOOK_URL = "https://telegram-bot-help-ua-ch.herokuapp.com"
WEBHOOK_URL = _env.str("WEBHOOK_URL", DEFAULT_WEBHOOK_URL)
USE_WEBHOOK = _env.bool("USE_WEBHOOK", False)
FEEDBACK_CHANNEL_ID = _env.int("FEEDBACK_CHANNEL_ID", None)
BOT_STATE_ENCRYPTION_KEY = _env.str("BOT_STATE_ENCRYPTION_KEY", None)
ADMIN_USERS = _env.list("ADMIN_USERS", [
    "edgnkv",
    "lr2kate",
    "rprokofyev",
    "SymbioticMe",
    "thecrdev",
    "Zygimantas",
])
