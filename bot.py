#!/usr/bin/env python

from collections import deque
from conversation_data import ConversationData
from bot_redis_persistence import RedisPersistence
from functools import reduce
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
    CallbackQueryHandler,
    ConversationHandler,
    Filters,
    MessageHandler,
    Updater,
)
from urllib.parse import urlparse
import bot_messages
import config
import error_handler
import google.protobuf.text_format as text_format
import logging
import proto.conversation_pb2 as conversation_proto
import redis
import ssl
import telegram.error
import urllib.request
import stats

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=config.LOGLEVEL,
)
logger = logging.getLogger(__name__)
bot_stats: stats.Stats = None
morpho_index: MorphoIndex = None
convo_data: ConversationData = None

CHOOSING, START_FEEDBACK, COLLECT_FEEDBACK, ADMIN_MENU, SEARCH_FAILED = \
    range(5)
TOP_N_SEARCH_RESULTS = 3

START_NODE = "/start"

PHOTO_CACHE = {}
BOT_PERSISTENCE_DATABASE, BOT_METRICS_DATABASE = range(2)


def redis_instance(redis_db: int):
    url = urlparse(config.REDIS_URL)
    use_ssl = url.scheme == 'rediss'
    logger.info(
        f"Enabling Redis-based bot persistence.\nRedis on: {url.hostname}:{url.port}\nUse SSL: {use_ssl}"
    )
    return redis.Redis(
        db=redis_db,
        host=url.hostname,
        port=url.port,
        username=url.username,
        password=url.password,
        ssl=use_ssl,
        ssl_cert_reqs=None,
    )


def redis_persistence():
    encryption_key_bytes = None
    if config.BOT_STATE_ENCRYPTION_KEY is None:
        logger.error(
            "*** EMPTY BOT_STATE_ENCRYPTION_KEY *** YOU SHOULD NEVER SEE THIS IN PROD ***"
        )
    else:
        encryption_key_bytes = config.BOT_STATE_ENCRYPTION_KEY.encode()
    rd = redis_instance(BOT_PERSISTENCE_DATABASE)
    return RedisPersistence(rd, encryption_key_bytes)


persistence = redis_persistence() if config.PERSIST_SESSIONS else None


def handle_error(update: object, context: CallbackContext):
    error_handler.handle_error(update, context)
    reset_user_state(context)


def back_choice(update: Update, context: CallbackContext) -> int:
    user_data = context.user_data
    user_data["nav_stack"] = user_data["nav_stack"][:-1] \
        if len(user_data["nav_stack"]) > 1 else user_data["nav_stack"]

    new_node_name = user_data["nav_stack"][-1]
    user_data["current_node"] = new_node_name
    update_state_and_send_conversation(update, context,
                                       context.user_data["current_node"])
    return CHOOSING


def start(update: Update, context: CallbackContext) -> int:
    reset_user_state(context)
    update_state_and_send_conversation(update, context,
                                       context.user_data["current_node"])
    return CHOOSING


def show_admin_menu(update: Update, context: CallbackContext) -> int:
    keyboard_opts = [
        [bot_messages.RELOAD],
        [bot_messages.STATISTICS],
        [bot_messages.START_OVER],
    ]
    update.message.reply_text(bot_messages.ADMIN_PROMPT,
                              parse_mode=ParseMode.HTML,
                              reply_markup=ReplyKeyboardMarkup(keyboard_opts))
    return ADMIN_MENU


def show_stats(update: Update, context: CallbackContext) -> int:
    keyboard_opts = [[bot_messages.START_OVER]]
    update.message.reply_text(bot_stats.compute(),
                              parse_mode=ParseMode.HTML,
                              reply_markup=ReplyKeyboardMarkup(keyboard_opts))

    return show_admin_menu(update, context)


def pull_conversation():
    logger.info(
        f"Loading conversation model from {config.CONVERSATION_MODEL_URL}")
    try:
        with urllib.request.urlopen(config.CONVERSATION_MODEL_URL,
                                    context=ssl.create_default_context()) as f:
            return f.read().decode("utf-8")
    except urllib.error.URLError as e:
        logger.error(
            f"Failed to load conversation from {config.CONVERSATION_MODEL_URL}",
            exc_info=e)
        raise e


def reload_conversation(update: Update, context: CallbackContext) -> int:
    username = update.message.from_user.username

    logger.info(f"Reloading conversation from {config.CONVERSATION_MODEL_URL}")
    try:
        convo_buffer = pull_conversation()
        reset_bot_data(convo_buffer, update)
        bot_stats.conversation_reloaded(username)
        logger.info(f"Conversation reload successful ({username})")
    except urllib.error.URLError as e:
        update.message.reply_text(f"Ошибка загрузки диалога:\n{e}",
                                  reply_markup=ReplyKeyboardMarkup(
                                      [[bot_messages.START_OVER]],
                                      one_time_keyboard=True))
        start(update, context)

    return show_admin_menu(update, context)


def reset_bot_data(conversation_textproto: str, update: Update = None):
    global convo_data, morpho_index
    conversation = text_format.Parse(conversation_textproto,
                                     conversation_proto.Conversation())
    morpho_index = MorphoIndex(conversation)

    convo_data = ConversationData(conversation)
    if update:
        update.message.reply_text("Диалог успешно перезагружен.")


def handle_answer(answer, update: Update):
    message = update.message if update.message else update.callback_query.message
    if len(answer.text) > 0:
        message.reply_text(answer.text, parse_mode=ParseMode.HTML)
    elif len(answer.links.text) > 0:
        links = answer.links
        buttons = []
        for url in links.url:
            buttons.append([InlineKeyboardButton(url.label, url=url.url)])
        reply_markup = InlineKeyboardMarkup(buttons)
        message.reply_text(
            links.text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    elif len(answer.venue.title) > 0:
        message.reply_venue(latitude=answer.venue.lat,
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
        message.reply_photo(photob)


def is_admin_user(username: str):
    return username in config.ADMIN_USERS


def choice(update: Update, context: CallbackContext) -> int:
    if not update.message:
        return CHOOSING

    user_data = context.user_data
    requested_node_name = update.message.text
    if convo_data.node_by_name(requested_node_name) is None:
        return search(update, context, requested_node_name)
    display_node_name = requested_node_name
    keyboard_node_name = user_data["current_node"]
    update_state_and_send_conversation(update, context, keyboard_node_name,
                                       display_node_name)
    return CHOOSING


def search(update: Update, context: CallbackContext, search_terms: str):
    search_results = morpho_index.search(search_terms)
    user_id = update.message.from_user.id
    if search_results:
        bot_stats.collect_search(user_id, search_terms, len(search_results))
        if len(search_results) == 1:
            display_node_name = search_results[0][0]
            update.message.reply_text(
                bot_messages.SINGLE_SEARCH_RESULT_HEADER_TEMPLATE.format(
                    display_node_name))
            update_state_and_send_conversation(
                update, context, context.user_data["current_node"],
                display_node_name)
        else:
            buttons = []
            for result in search_results[:TOP_N_SEARCH_RESULTS]:
                buttons.append([
                    InlineKeyboardButton(text=result.node_label,
                                         callback_data=hash(result.node_name))
                ])
            reply_markup = InlineKeyboardMarkup(buttons)
            update.message.reply_text(bot_messages.SEARCH_RESULT_HEADER,
                                      reply_markup=reply_markup)
        return CHOOSING
    else:
        logger.info(f"Freetext search yielded nothing: [{search_terms}]")
        bot_stats.collect_search(user_id, search_terms, 0)
        keyboard_options = []
        if config.FEEDBACK_CHANNEL_ID is not None:
            keyboard_options.append([bot_messages.FEEDBACK])
        keyboard_options.extend([[bot_messages.BACK],
                                 [bot_messages.START_OVER]])
        update.message.reply_text(
            bot_messages.EMPTY_SEARCH_RESULTS,
            reply_markup=ReplyKeyboardMarkup(keyboard_options,
                                             one_time_keyboard=True))
        return SEARCH_FAILED


def search_failed_back(update: Update, context: CallbackContext) -> int:
    update_state_and_send_conversation(update, context,
                                       context.user_data["current_node"])
    return CHOOSING


def search_again(update: Update, context: CallbackContext) -> int:
    return search(update, context, update.message.text)


def on_button(update: Update, context: CallbackContext):
    new_node = convo_data.node_by_hash(update.callback_query.data)
    if new_node is None:
        return
    current_node = context.user_data["current_node"]
    context.user_data["current_node"] = new_node.name
    update.callback_query.answer()
    update.callback_query.message.reply_text(f"<b>{new_node.name}</b>",
                                             parse_mode=ParseMode.HTML)
    update_state_and_send_conversation(update, context, current_node,
                                       new_node.name)


def update_state_and_send_conversation(update: Update,
                                       context: CallbackContext,
                                       keyboard_node_name: str,
                                       display_node_name: str = None):
    """Sends a conversation node contents with a keyboard attached.

    In case display_node_name does not have keyboard options, the code will
    display display_node_name content and fall-back to keyboard_node_name for
    keyboard options.

    Args:
        keyboard_node_name (str): a conversation node to use for keyboard
            options.
        display_node_name (str): a conversation node to use for contents. If
            None, keyboard_node_name is used.
    """
    if display_node_name is None:
        display_node_name = keyboard_node_name

    user_data = context.user_data
    if convo_data.keyboard_by_name(display_node_name) is not None:
        try:
            existing_index = user_data["nav_stack"].index(display_node_name)
            user_data["nav_stack"] = user_data["nav_stack"][:existing_index]
        except ValueError:
            pass
        user_data["nav_stack"].append(display_node_name)
        keyboard_node_name = display_node_name
    user_data["current_node"] = keyboard_node_name

    from_user = update.message.from_user if update.message else update.callback_query.from_user
    bot_stats.collect_interaction(from_user.id, display_node_name)

    display_node = convo_data.node_by_name(display_node_name)
    if not display_node:
        current_keyboard = ReplyKeyboardMarkup([[bot_messages.START_OVER]],
                                               one_time_keyboard=True)
        update.message.reply_text(bot_messages.DATA_REFRESHED,
                                  reply_markup=current_keyboard)
        return

    nav_stack_depth = len(user_data["nav_stack"])
    current_keyboard = build_keyboard_options(
        keyboard_node_name,
        nav_stack_depth,
        show_feedback_button=nav_stack_depth <= 1,
        show_admin_button=(nav_stack_depth <= 1
                           and is_admin_user(from_user.username)))

    for answer in display_node.answer[:-1]:
        handle_answer(answer, update)
    last_answer = display_node.answer[-1]
    message = update.message if update.message else update.callback_query.message
    if len(last_answer.text) == 0:
        handle_answer(last_answer, update)
        message.reply_text(bot_messages.PROMPT_REPLY,
                           reply_markup=current_keyboard)
    else:
        message.reply_text(last_answer.text,
                           parse_mode=ParseMode.HTML,
                           reply_markup=current_keyboard)


def build_keyboard_options(keyboard_options_node_name: str = None,
                           nav_stack_depth: int = 0,
                           show_feedback_button: bool = False,
                           show_admin_button: bool = False):
    current_keyboard_options = deque()
    if keyboard_options_node_name is not None:
        current_keyboard_options.extend(
            convo_data.keyboard_by_name(keyboard_options_node_name))
    if show_admin_button:
        current_keyboard_options.appendleft([bot_messages.ADMIN])
    if show_feedback_button and config.FEEDBACK_CHANNEL_ID is not None:
        current_keyboard_options.append([bot_messages.FEEDBACK])
    if nav_stack_depth >= 2:
        current_keyboard_options.append([bot_messages.BACK])
    if nav_stack_depth > 2:
        current_keyboard_options.append([bot_messages.START_OVER])
    return ReplyKeyboardMarkup(current_keyboard_options,
                               one_time_keyboard=True)


def start_feedback(update: Update, context: CallbackContext):
    if config.FEEDBACK_CHANNEL_ID is None:
        return start(update, context)
    keyboard_options = [bot_messages.START_OVER]
    update.message.reply_text(bot_messages.PROMPT_FEEDBACK,
                              reply_markup=ReplyKeyboardMarkup(
                                  [keyboard_options], one_time_keyboard=True))
    return COLLECT_FEEDBACK


def collect_feedback(update: Update, context: CallbackContext):
    if config.FEEDBACK_CHANNEL_ID is None:
        return start(update, context)
    if context.user_data["feedback"] is None:
        context.user_data["feedback"] = []
    context.user_data["feedback"].append(update.message)

    keyboard_options = []
    if len(context.user_data["feedback"]) > 0:
        keyboard_options.append([
            bot_messages.SEND_FEEDBACK, bot_messages.SEND_FEEDBACK_ANONYMOUSLY
        ])
    keyboard_options.append([bot_messages.START_OVER])
    update.message.reply_text(bot_messages.CONTINUE_FEEDBACK,
                              reply_markup=ReplyKeyboardMarkup(
                                  keyboard_options, one_time_keyboard=True))
    return COLLECT_FEEDBACK


def send_feedback(update: Update, context: CallbackContext):
    if config.FEEDBACK_CHANNEL_ID is None:
        return start(update, context)
    if len(context.user_data["feedback"]) == 0:
        return start(update, context)

    try:
        if update.message.text is not None and \
                update.message.text != bot_messages.SEND_FEEDBACK_ANONYMOUSLY:
            effective_user_name = update.effective_user.name
            text = f"Feedback from {effective_user_name}"
            context.bot.send_message(
                chat_id=config.FEEDBACK_CHANNEL_ID,
                text=text,
                entities=[
                    MessageEntity(offset=0,
                                  length=len(text),
                                  type="text_mention",
                                  user=User(update.effective_user.id,
                                            effective_user_name, False))
                ])
        for msg in context.user_data["feedback"]:
            msg.forward(config.FEEDBACK_CHANNEL_ID)
    except telegram.error.TelegramError as e:
        logger.warning("Error when trying to forward feedback to channel %s",
                       config.FEEDBACK_CHANNEL_ID,
                       exc_info=e)

    bot_stats.collect_interaction(update.message.from_user.id, "Send Feedback")

    context.user_data["feedback"] = []
    update.message.reply_text(bot_messages.THANK_FOR_FEEDBACK)
    return start(update, context)


def conversation_handler(persistent: bool):
    is_admin_filter = reduce(
        lambda a, b: a | b,
        [Filters.user(username=username) for username in config.ADMIN_USERS])
    return ConversationHandler(
        entry_points=[
            MessageHandler(Filters.chat_type.private & Filters.all, start)
        ],
        states={
            CHOOSING: [
                MessageHandler(
                    Filters.chat_type.private
                    & Filters.regex(f"^{bot_messages.BACK}$"), back_choice),
                MessageHandler(
                    Filters.chat_type.private
                    & Filters.regex(f"^{bot_messages.FEEDBACK}$"),
                    start_feedback),
                MessageHandler(
                    Filters.chat_type.private
                    & is_admin_filter
                    & Filters.regex(f"^{bot_messages.ADMIN}$"),
                    show_admin_menu),
                MessageHandler(
                    Filters.chat_type.private & Filters.text
                    & ~Filters.regex(f"^{bot_messages.START_OVER}$"), choice),
            ],
            COLLECT_FEEDBACK: [
                MessageHandler(
                    Filters.chat_type.private & Filters.regex(
                        f"^{bot_messages.SEND_FEEDBACK}|{bot_messages.SEND_FEEDBACK_ANONYMOUSLY}$"
                    ), send_feedback),
                MessageHandler(
                    Filters.chat_type.private & Filters.all
                    & ~Filters.regex(f"^{bot_messages.START_OVER}$"),
                    collect_feedback),
            ],
            SEARCH_FAILED: [
                MessageHandler(
                    Filters.chat_type.private
                    & Filters.regex(f"^{bot_messages.FEEDBACK}$"),
                    start_feedback),
                MessageHandler(
                    Filters.chat_type.private
                    & Filters.regex(f"^{bot_messages.BACK}$"),
                    search_failed_back),
                MessageHandler(
                    Filters.chat_type.private & Filters.all
                    & ~Filters.regex(f"^{bot_messages.START_OVER}$"),
                    search_again),
            ],
            ADMIN_MENU: [
                MessageHandler(
                    Filters.chat_type.private
                    & Filters.regex(f"^{bot_messages.STATISTICS}$"),
                    show_stats),
                MessageHandler(
                    Filters.chat_type.private
                    & Filters.regex(f"^{bot_messages.RELOAD}$"),
                    reload_conversation),
            ],
        },
        fallbacks=[
            MessageHandler(
                Filters.chat_type.private
                & Filters.regex(f"^{bot_messages.START_OVER}$"), start),
        ],
        name="main",
        persistent=persistent,
    )


def init_stats():
    global bot_stats
    storage = stats.RedisStorage(redis_instance(BOT_METRICS_DATABASE)) \
        if config.PERSIST_METRICS else stats.MemStorage()
    bot_stats = stats.Stats(storage)


def reset_user_state(context: CallbackContext):
    context.user_data["current_node"] = START_NODE
    context.user_data["nav_stack"] = [START_NODE]
    context.user_data["feedback"] = []


def start_bot():
    updater = Updater(token=config.API_KEY,
                      persistence=persistence,
                      use_context=True)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(conversation_handler(persistence is not None))
    dispatcher.add_handler(CallbackQueryHandler(on_button))
    dispatcher.add_error_handler(handle_error)

    if config.USE_WEBHOOK:
        logger.log(logging.INFO, f"Starting webhook at port {config.PORT}")
        updater.start_webhook(
            listen="0.0.0.0",
            port=config.PORT,
            url_path=config.API_KEY,
            webhook_url=f"{config.WEBHOOK_URL}/{config.API_KEY}",
        )
    else:
        updater.start_polling()

    updater.idle()


def main():
    logger.info(f"Admin users: {config.ADMIN_USERS}")
    reset_bot_data(pull_conversation())
    init_stats()
    start_bot()


if __name__ == "__main__":
    main()
