#!/usr/bin/env python

from collections import deque
from bot_redis_persistence import RedisPersistence
from node_util import visit_node
from morpho_index import MorphoIndex
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MAX_MESSAGE_LENGTH,
    MessageEntity,
    ParseMode,
    ReplyKeyboardMarkup,
    Update,
    User,
)
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
    Filters,
    MessageHandler,
    Updater,
)
from typing import Dict, Set
from urllib.parse import urlparse
import google.protobuf.text_format as text_format
import html
import json
import logging
import os
import proto.conversation_pb2 as conversation_proto
import redis
import ssl
import telegram.error
import traceback
import urllib.request
import stats

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
bot_stats: stats.Stats = None
morpho_index: MorphoIndex = None

CONVERSATION_TREE_URL = "https://raw.githubusercontent.com/skd/telegram-bot-help-ua-ch/main/conversation_tree.textproto"
DEFAULT_WEBHOOK_URL = "https://telegram-bot-help-ua-ch.herokuapp.com"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", DEFAULT_WEBHOOK_URL)
API_KEY = os.getenv('TELEGRAM_BOT_API_KEY')
FEEDBACK_CHANNEL_ID = os.getenv("FEEDBACK_CHANNEL_ID", None)
if FEEDBACK_CHANNEL_ID is not None:
    FEEDBACK_CHANNEL_ID = int(FEEDBACK_CHANNEL_ID)

CHOOSING, START_FEEDBACK, COLLECT_FEEDBACK, ADMIN_MENU = range(4)

BACK = "Назад"
START_OVER = "Вернуться в начало"
FEEDBACK = "Оставить отзыв боту"
PROMPT_FEEDBACK = "Пишите свой отзыв прямо тут."
CONTINUE_FEEDBACK = "Пишите дальше, если хотите что-то добавить. " + \
    "Нажмите «Послать отзыв», если готовы послать отзыв."
SEND_FEEDBACK = "✅ Послать отзыв"
SEND_FEEDBACK_ANONYMOUSLY = "🥷 Послать отзыв анонимно"
THANK_FOR_FEEDBACK = "Спасибо вам за отзыв! 🙏"
EMPTY_SEARCH_RESULTS = "По вашему запросу ничего не нашлось 🤔 Пожалуйста, введите новый запрос или выберите пункт меню."
SEARCH_RESULT_HEADER_TEMPLATE = "По вашему запросу найдена статья \"{}\":"
DATA_REFRESHED = "Не получается перейти назад, поскольку данные были обновлены. Пожалуйста, вернитесь в начало."
PROMPT_REPLY = "Выберите пункт"
ERROR_OCCURED = "Извините, произошла ошибка. Попробуйте начать сначала."
STATISTICS = "Статистика"
ADMIN = "Админ"
ADMIN_PROMPT = "Давно не виделись! Как поживаете?"
RELOAD = "Обновить данные разговора"

START_NODE = "/start"


ADMIN_USERS = [
    "SymbioticMe",
    "lr2kate",
    "edgnkv",
    "Zygimantas",
    "thecrdev",
]

CONVERSATION_DATA = {}
PHOTO_CACHE = {}
BOT_PERSISTENCE_DATABASE, BOT_METRICS_DATABASE = range(2)


def redis_instance(redis_db: int):
    redis_url = os.getenv("REDIS_TLS_URL", "redis://localhost:6379")

    url = urlparse(redis_url)
    use_ssl = url.scheme == 'rediss'
    logger.info(
        f"Enabling Redis-based bot persistence.\nRedis on: {url.hostname}:{url.port}\nUse SSL: {use_ssl}")
    return redis.Redis(
        db=redis_db,
        host=url.hostname, port=url.port,
        username=url.username, password=url.password,
        ssl=use_ssl, ssl_cert_reqs=None,
    )


def redis_persistence():
    encryption_key_bytes = None
    encryption_key = os.getenv("BOT_STATE_ENCRYPTION_KEY")
    if encryption_key is None:
        logger.error(
            "*** EMPTY BOT_STATE_ENCRYPTION_KEY *** YOU SHOULD NEVER SEE THIS IN PROD ***")
    else:
        encryption_key_bytes = encryption_key.encode()
    rd = redis_instance(BOT_PERSISTENCE_DATABASE)
    return RedisPersistence(rd, encryption_key_bytes)


persistence = redis_persistence() if os.getenv(
    "PERSIST_SESSIONS", '') == 'true' else None


def handle_error(update: object, context: CallbackContext):
    logger.error(msg="Exception while handling an update:",
                 exc_info=context.error)

    if FEEDBACK_CHANNEL_ID is not None:
        tb_list = traceback.format_exception(
            None, context.error, context.error.__traceback__)
        tb_string = ''.join(tb_list)
        update_str = update.to_dict() if isinstance(update, Update) else str(update)
        try:
            context.bot.send_message(
                chat_id=FEEDBACK_CHANNEL_ID, text="An exception was raised when handling an update:")
            update_msg = (f"Update:\n<pre>"
                          f"{html.escape(json.dumps(update_str, indent=2, ensure_ascii=False, default=str))}"
                          f"</pre>"[:MAX_MESSAGE_LENGTH])
            context.bot.send_message(
                chat_id=FEEDBACK_CHANNEL_ID, text=update_msg, parse_mode=ParseMode.HTML)
            context_msg = (f"context.user_data:\n<pre>"
                           f"{json.dumps(context.user_data, indent=2, ensure_ascii=False, default=str)}"
                           f"</pre>"[:MAX_MESSAGE_LENGTH])
            context.bot.send_message(
                chat_id=FEEDBACK_CHANNEL_ID, text=context_msg, parse_mode=ParseMode.HTML)
            error_msg = (f"Error:\n<pre>{html.escape(tb_string)}"
                         f"</pre>"[:MAX_MESSAGE_LENGTH])
            context.bot.send_message(
                chat_id=FEEDBACK_CHANNEL_ID, text=error_msg, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.warning(
                msg="Can't send a message to a feedback channel.", exc_info=e)
    if isinstance(update, Update) and update.message is not None:
        update.message.reply_text(
            ERROR_OCCURED,
            reply_markup=ReplyKeyboardMarkup(
                [[START_OVER]], one_time_keyboard=True))
    reset_user_state(context)


def back_choice(update: Update, context: CallbackContext) -> int:
    user_data = context.user_data
    user_data["nav_stack"] = user_data["nav_stack"][:-1] \
        if len(user_data["nav_stack"]) > 1 else user_data["nav_stack"]

    new_node_name = user_data["nav_stack"][-1]
    user_data["current_node"] = new_node_name
    return choice(update, context, False)


def start(update: Update, context: CallbackContext) -> int:
    reset_user_state(context)
    return choice(update, context, False)


def show_admin_menu(update: Update, context: CallbackContext) -> int:
    if update.message.from_user.username not in ADMIN_USERS:
        return start(update, context)
    keyboard_opts = [
        [RELOAD],
        [STATISTICS],
        [START_OVER],
    ]
    update.message.reply_text(
        ADMIN_PROMPT, parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardMarkup(keyboard_opts))
    return ADMIN_MENU


def show_stats(update: Update, context: CallbackContext) -> int:
    if update.message.from_user.username not in ADMIN_USERS:
        return start(update, context)
    keyboard_opts = [[START_OVER]]
    update.message.reply_text(
        bot_stats.compute(), parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardMarkup(keyboard_opts))

    return show_admin_menu(update, context)


def pull_conversation():
    logger.info(f"Pulling conversation model from {CONVERSATION_TREE_URL}")
    with urllib.request.urlopen(CONVERSATION_TREE_URL,
                                context=ssl.create_default_context()) as f:
        return f.read().decode("utf-8")


def reload_conversation(update: Update, context: CallbackContext) -> int:
    username = update.message.from_user.username
    if username not in ADMIN_USERS:
        return start(update, context)

    logger.info(f"Reloading conversation from {CONVERSATION_TREE_URL}")
    try:
        convo_buffer = pull_conversation()
        reset_bot_data(convo_buffer, update)
        bot_stats.conversation_reloaded(username)
        logger.info(f"Conversation reload successful ({username})")
    except urllib.error.URLError as e:
        logger.error(
            "Failed to reload conversation from URL", exc_info=e)
        update.message.reply_text(
            f"Ошибка загрузки диалога:\n{e}",
            reply_markup=ReplyKeyboardMarkup(
                [[START_OVER]], one_time_keyboard=True))
        start(update, context)

    return show_admin_menu(update, context)


def reset_bot_data(conversation_textproto: str, update: Update = None):
    global CONVERSATION_DATA, morpho_index
    conversation = text_format.Parse(
        conversation_textproto, conversation_proto.Conversation())
    morpho_index = MorphoIndex(conversation)


    # Avoid bringing CONVERSATION_DATA into an inconsistent state.
    new_conversation_data = {}
    new_conversation_data["node_by_name"] = create_node_by_name(conversation)
    new_conversation_data["keyboard_by_name"] = create_keyboard_options(
        new_conversation_data["node_by_name"])
    CONVERSATION_DATA = new_conversation_data
    if update:
        update.message.reply_text("Диалог успешно перезагружен.")


def handle_answer(answer, update: Update):
    if len(answer.text) > 0:
        update.message.reply_text(answer.text, parse_mode=ParseMode.HTML)
    elif len(answer.links.text) > 0:
        links = answer.links
        buttons = []
        for url in links.url:
            buttons.append([InlineKeyboardButton(url.label, url=url.url)])
        reply_markup = InlineKeyboardMarkup(buttons)
        update.message.reply_text(
            links.text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    elif len(answer.venue.title) > 0:
        update.message.reply_venue(
            latitude=answer.venue.lat,
            longitude=answer.venue.lon,
            title=answer.venue.title,
            address=answer.venue.address,
            google_place_id=answer.venue.google_place_id)
    elif len(answer.photo) > 0:
        photob = None
        if answer.photo in PHOTO_CACHE:
            photob = PHOTO_CACHE[answer.photo]
        with open("photo/%s" % answer.photo, "rb") as photo_file:
            photob = photo_file.read()
            PHOTO_CACHE[answer.photo] = photob
        update.message.reply_photo(photob)


def is_admin_user(update: Update):
    return update.message.from_user.username in ADMIN_USERS


def choice(update: Update, context: CallbackContext, organic_call: bool=True) -> int:
    if not update.message:
        return CHOOSING

    user_data = context.user_data
    next_node_name = user_data["current_node"]

    if update.message.text in CONVERSATION_DATA["node_by_name"]:
        next_node_name = update.message.text
    elif organic_call:
        search_results = morpho_index.search(update.message.text)
        user_id = update.message.from_user.id
        if search_results:
            next_node_name = search_results[0][0]
            update.message.reply_text(SEARCH_RESULT_HEADER_TEMPLATE.format(next_node_name))
            bot_stats.collect_search(user_id, update.message.text, len(search_results))
        else:
            logger.info(f"Freetext search yielded nothing: [{update.message.text}]")
            bot_stats.collect_search(user_id, update.message.text, 0)
            update.message.reply_text(
                EMPTY_SEARCH_RESULTS,
                reply_markup=build_keyboard_options(
                    user_data["current_node"],
                    is_admin_user(update),
                    len(user_data["nav_stack"])))
            return CHOOSING

    if next_node_name in CONVERSATION_DATA["keyboard_by_name"]:
        user_data["current_node"] = next_node_name
        try:
            existing_index = user_data["nav_stack"].index(next_node_name)
            user_data["nav_stack"] = user_data["nav_stack"][:existing_index]
        except ValueError:
            pass
        user_data["nav_stack"].append(next_node_name)

    current_node_name = user_data["current_node"]
    user_id = update.message.from_user.id
    bot_stats.collect_interaction(user_id, next_node_name)

    current_node = CONVERSATION_DATA["node_by_name"].get(next_node_name)
    if not current_node:
        current_keyboard = ReplyKeyboardMarkup(
            [[START_OVER]], one_time_keyboard=True)
        update.message.reply_text(
            DATA_REFRESHED,
            reply_markup=current_keyboard)
        return CHOOSING

    current_keyboard = build_keyboard_options(
        current_node_name, is_admin_user(update), len(user_data["nav_stack"]))

    for answer in current_node.answer[:-1]:
        handle_answer(answer, update)

    answer = current_node.answer[-1]
    if len(answer.text) == 0:
        handle_answer(answer, update)
        update.message.reply_text(
            PROMPT_REPLY,
            reply_markup=current_keyboard)
    else:
        update.message.reply_text(
            answer.text,
            parse_mode=ParseMode.HTML,
            reply_markup=current_keyboard)

    return CHOOSING


def build_keyboard_options(keyboard_options_node: str, show_admin_button: bool, nav_stack_depth: int):
    current_keyboard_options = deque()
    current_keyboard_options.extend(
        CONVERSATION_DATA["keyboard_by_name"][keyboard_options_node])

    if nav_stack_depth <= 1:
        if show_admin_button:
            current_keyboard_options.appendleft([ADMIN])
        if FEEDBACK_CHANNEL_ID is not None:
            current_keyboard_options.append([FEEDBACK])
    if nav_stack_depth >= 2:
        current_keyboard_options.append([BACK])
    if nav_stack_depth > 2:
        current_keyboard_options.append([START_OVER])

    return ReplyKeyboardMarkup(
        current_keyboard_options, one_time_keyboard=True)


def start_feedback(update: Update, context: CallbackContext):
    if FEEDBACK_CHANNEL_ID is None:
        return start(update, context)
    context.user_data["feedback"] = []
    keyboard_options = [START_OVER]
    update.message.reply_text(
        PROMPT_FEEDBACK,
        reply_markup=ReplyKeyboardMarkup(
            [keyboard_options], one_time_keyboard=True))
    return COLLECT_FEEDBACK


def collect_feedback(update: Update, context: CallbackContext):
    if FEEDBACK_CHANNEL_ID is None:
        return start(update, context)
    context.user_data["feedback"].append(update.message)

    keyboard_options = []
    if len(context.user_data["feedback"]) > 0:
        keyboard_options.append([
            SEND_FEEDBACK,
            SEND_FEEDBACK_ANONYMOUSLY])
    keyboard_options.append([START_OVER])
    update.message.reply_text(
        CONTINUE_FEEDBACK,
        reply_markup=ReplyKeyboardMarkup(
            keyboard_options, one_time_keyboard=True))
    return COLLECT_FEEDBACK


def send_feedback(update: Update, context: CallbackContext):
    if FEEDBACK_CHANNEL_ID is None:
        return start(update, context)
    if len(context.user_data["feedback"]) == 0:
        return start(update, context)

    try:
        if update.message.text is not None and \
                update.message.text != SEND_FEEDBACK_ANONYMOUSLY:
            effective_user_name = update.effective_user.name
            text = f"Feedback from {effective_user_name}"
            context.bot.send_message(
                chat_id=FEEDBACK_CHANNEL_ID,
                text=text,
                entities = [MessageEntity(
                    offset=0,
                    length=len(text),
                    type="text_mention",
                    user=User(
                        update.effective_user.id,
                        effective_user_name,
                        False))])
        for msg in context.user_data["feedback"]:
            msg.forward(int(FEEDBACK_CHANNEL_ID))
    except telegram.error.TelegramError as e:
        logger.warning(
            "Error when trying to forward feedback to channel %s",
            FEEDBACK_CHANNEL_ID, exc_info=e)

    bot_stats.collect(update.message.from_user.id, "Send Feedback")

    context.user_data["feedback"] = []
    update.message.reply_text(THANK_FOR_FEEDBACK)
    return start(update, context)


def conversation_handler(persistent: bool):
    return ConversationHandler(
        entry_points=[MessageHandler(
            Filters.chat_type.private & Filters.all, start)],
        states={
            CHOOSING: [
                MessageHandler(
                    Filters.chat_type.private &
                    Filters.regex(f"^{BACK}$"), back_choice),
                MessageHandler(
                    Filters.chat_type.private &
                    Filters.regex(f"^{FEEDBACK}$"), start_feedback),
                MessageHandler(
                    Filters.chat_type.private &
                    Filters.regex(f"^{ADMIN}$"), show_admin_menu),
                MessageHandler(
                    Filters.chat_type.private &
                    Filters.text & ~Filters.regex(f"^{START_OVER}$"), choice),
            ],
            COLLECT_FEEDBACK: [
                MessageHandler(
                    Filters.chat_type.private &
                    Filters.regex(f"^{SEND_FEEDBACK}|{SEND_FEEDBACK_ANONYMOUSLY}$"), send_feedback),
                MessageHandler(
                    Filters.chat_type.private &
                    Filters.all &
                    ~Filters.regex(f"^{START_OVER}$"), collect_feedback),
            ],
            ADMIN_MENU: [
                MessageHandler(
                    Filters.chat_type.private &
                    Filters.regex(f"^{STATISTICS}$"), show_stats),
                MessageHandler(
                    Filters.chat_type.private &
                    Filters.regex(f"^{RELOAD}$"), reload_conversation),
            ],
        },
        fallbacks=[
            MessageHandler(
                Filters.chat_type.private &
                Filters.regex(f"^{START_OVER}$"), start),
        ],
        name="main",
        persistent=persistent,
    )


def init_stats():
    global bot_stats
    storage = stats.RedisStorage(redis_instance(BOT_METRICS_DATABASE)) \
        if os.getenv("PERSIST_METRICS", "") == "true" else stats.MemStorage()
    bot_stats = stats.Stats(storage)


def reset_user_state(context: CallbackContext):
    context.user_data["current_node"] = START_NODE
    context.user_data["nav_stack"] = [START_NODE]


def start_bot():
    updater = Updater(token=API_KEY, persistence=persistence, use_context=True)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(conversation_handler(persistence is not None))
    dispatcher.add_error_handler(handle_error)

    if os.getenv("USE_WEBHOOK", "") == "true":
        port = int(os.environ.get("PORT", 5000))
        logger.log(logging.INFO, f"Starting webhook at port {port}")
        updater.start_webhook(
            listen="0.0.0.0",
            port=int(port),
            url_path=API_KEY,
            webhook_url=f"{WEBHOOK_URL}/{API_KEY}",
        )
    else:
        updater.start_polling()

    updater.idle()


def create_node_by_name(conversation: conversation_proto.Conversation):
    node_by_name = {}

    def updater(node):
        node_by_name[node.name] = node
    for node in conversation.node:
        visit_node(node, updater)
    return node_by_name


def create_keyboard_options(node_by_name):
    keyboard_by_name = {}
    for name in node_by_name:
        if len(node_by_name[name].link) > 0:
            options = []
            for link in node_by_name[name].link:
                if len(link.name) > 0:
                    options.append([link.name])
                elif len(link.branch.name) > 0:
                    options.append([link.branch.name])
            keyboard_by_name[name] = options
    return keyboard_by_name


def main():
    try:
        convo_buffer = pull_conversation()
    except urllib.error.URLError as e:
        logger.error(
            "Failed to reload conversation from URL, falling back to a local conversation model",
            exc_info=e)
        convo_buffer = None
        with open("conversation_tree.textproto", "r") as f:
            convo_buffer = f.read()
    reset_bot_data(convo_buffer)
    init_stats()
    start_bot()


if __name__ == "__main__":
    main()
