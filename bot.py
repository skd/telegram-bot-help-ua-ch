#!/usr/bin/env python

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ParseMode,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
    Filters,
    MessageHandler,
    Updater,
)
from typing import Set
import google.protobuf.text_format as text_format
import logging
import os
import proto.conversation_pb2 as conversation_proto
import telegram.error

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

CHOOSING, START_FEEDBACK, COLLECT_FEEDBACK = range(3)

BACK = "Назад"
START_OVER = "Вернуться в начало"
FEEDBACK = "Оставить отзыв боту"
PROMPT_FEEDBACK = "Пишите свой отзыв прямо тут."
CONTINUE_FEEDBACK = "Пишите дальше, если хотите что-то добавить. " + \
    "Нажмите «Послать отзыв», если готовы послать отзыв."
SEND_FEEDBACK = "✅ Послать отзыв"
THANK_FOR_FEEDBACK = "Спасибо вам за отзыв!"
PROMPT_REPLY = "Выберите пункт"
ERROR_OCCURED = "Извините, произошла ошибка. Попробуйте начать сначала."

START_NODE = "/start"

CONVERSATION_DATA = {}
PHOTO_CACHE = {}
FEEDBACK_CHANNEL_ID = None


def handle_error(update: object, context: CallbackContext):
    logger.error(msg="Exception while handling an update:",
                 exc_info=context.error)
    if not FEEDBACK_CHANNEL_ID is None:
        update_text = update.to_dict() if isinstance(update, Update) else str(update)
        message = (
            f"An exception was raised when handling an update:\n"
            f"update={update_text}\n"
            f"context.user_data={context.user_data}\n"
            f"Error: {context.error}"
        )
        context.bot.send_message(
            chat_id=FEEDBACK_CHANNEL_ID, text=message)
    update.message.reply_text(
        ERROR_OCCURED,
        reply_markup=ReplyKeyboardMarkup(
            [[START_OVER]], one_time_keyboard=True))


def back_choice(update: Update, context: CallbackContext) -> int:
    user_data = context.user_data
    user_data["nav_stack"] = user_data["nav_stack"][:-1] \
        if len(user_data["nav_stack"]) > 1 else user_data["nav_stack"]
    new_node_name = user_data["nav_stack"][-1]
    user_data["current_node"] = new_node_name
    return choice(update, context)


def start(update: Update, context: CallbackContext) -> int:
    context.user_data["current_node"] = START_NODE
    context.user_data["nav_stack"] = [START_NODE]
    return choice(update, context)


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
        with open("photo/%s" % answer.photo, 'rb') as photo_file:
            photob = photo_file.read()
            PHOTO_CACHE[answer.photo] = photob
        update.message.reply_photo(photob)


def choice(update: Update, context: CallbackContext) -> int:
    user_data = context.user_data
    next_node_name = user_data["current_node"]
    if update.message.text in CONVERSATION_DATA["node_by_name"]:
        next_node_name = update.message.text
    if next_node_name in CONVERSATION_DATA["keyboard_by_name"]:
        user_data["current_node"] = next_node_name
        try:
            existing_index = user_data["nav_stack"].index(next_node_name)
            user_data["nav_stack"] = user_data["nav_stack"][:existing_index]
        except ValueError:
            pass
        user_data["nav_stack"].append(next_node_name)
    current_node_name = user_data["current_node"]

    current_node = CONVERSATION_DATA["node_by_name"][next_node_name]
    current_keyboard_options = [
        *CONVERSATION_DATA["keyboard_by_name"][current_node_name]]
    if len(user_data["nav_stack"]) > 1:
        current_keyboard_options.append([BACK])
    if next_node_name != START_NODE:
        current_keyboard_options.append([START_OVER])
    elif not FEEDBACK_CHANNEL_ID is None:
        current_keyboard_options.append([FEEDBACK])
    current_keyboard = ReplyKeyboardMarkup(
        current_keyboard_options, one_time_keyboard=True)

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
        keyboard_options.append([SEND_FEEDBACK])
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

    for msg in context.user_data["feedback"]:
        try:
            msg.forward(int(FEEDBACK_CHANNEL_ID))
        except telegram.error.TelegramError as e:
            logger.warning(
                "Error when trying to forward feedback to channel %s",
                FEEDBACK_CHANNEL_ID, exc_info=e)

    context.user_data["feedback"] = []
    update.message.reply_text(THANK_FOR_FEEDBACK)
    return start(update, context)


def start_bot():
    api_key = os.getenv('TELEGRAM_BOT_API_KEY')
    updater = Updater(
        token=api_key, use_context=True)
    dispatcher = updater.dispatcher

    conv_handler = ConversationHandler(
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
                    Filters.text & ~Filters.regex(f"^{START_OVER}$"), choice),
            ],
            COLLECT_FEEDBACK: [
                MessageHandler(
                    Filters.chat_type.private &
                    Filters.regex(f"^{SEND_FEEDBACK}$"), send_feedback),
                MessageHandler(
                    Filters.chat_type.private &
                    Filters.all &
                    ~Filters.regex(f"^{START_OVER}$"), collect_feedback),
            ]
        },
        fallbacks=[
            MessageHandler(
                Filters.chat_type.private &
                Filters.regex('%s$' % (START_OVER)), start),
        ],
    )
    dispatcher.add_handler(conv_handler)
    dispatcher.add_error_handler(handle_error)

    if os.getenv('USE_WEBHOOK', '') == 'true':
        port = int(os.environ.get('PORT', 5000))
        logger.info("Starting webhook at port %s", port)
        updater.start_webhook(listen='0.0.0.0',
                              port=int(port),
                              url_path=api_key,
                              webhook_url=f"https://{os.environ.get('HEROKU_APP_NAME', 'telegram-bot-help-ua-ch')}.herokuapp.com/{api_key}")
    else:
        updater.start_polling()

    updater.idle()


def visit_node(node: conversation_proto.ConversationNode, consumer, visited: Set = set()):
    visited.add(node.name)
    consumer(node)
    if len(node.link) > 0:
        for subnode in node.link:
            if len(subnode.branch.name) > 0 and not subnode.branch.name in visited:
                visit_node(subnode.branch, consumer, visited)


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


if __name__ == "__main__":
    with open('conversation_tree.textproto', 'r') as f:
        f_buffer = f.read()
        conversation = text_format.Parse(
            f_buffer, conversation_proto.Conversation())
    CONVERSATION_DATA["node_by_name"] = create_node_by_name(conversation)
    CONVERSATION_DATA["keyboard_by_name"] = create_keyboard_options(
        CONVERSATION_DATA["node_by_name"])

    FEEDBACK_CHANNEL_ID = os.getenv('FEEDBACK_CHANNEL_ID', None)
    if not FEEDBACK_CHANNEL_ID is None:
        FEEDBACK_CHANNEL_ID = int(FEEDBACK_CHANNEL_ID)

    start_bot()
