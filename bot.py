#!/usr/bin/env python

from asyncio import run_coroutine_threadsafe
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    CallbackContext,
    CommandHandler,
    ConversationHandler,
    Filters,
    MessageHandler,
    Updater,
)
from typing import Dict, Set
import google.protobuf.text_format as text_format
import logging
import os
import proto.conversation_pb2 as conversation_proto

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

CHOOSING = range(1)

BACK = "Back"
DONE = "Done"
PROMPT_REPLY = "What will you say?"

CONVERSATION_DATA = {}
PHOTO_CACHE = {}


def done(update: Update, context: CallbackContext) -> int:
    user_data = context.user_data

    update.message.reply_text(
        "Until next time! Type /start to start over.",
        reply_markup=ReplyKeyboardRemove(),
    )

    user_data.clear()
    return ConversationHandler.END


def back_choice(update: Update, context: CallbackContext) -> int:
    current_node = context.user_data["current_node"]
    new_node = CONVERSATION_DATA["back_nav"][current_node] \
        if current_node in CONVERSATION_DATA["back_nav"] else "/start"
    context.user_data["current_node"] = new_node
    return choice(update, context)


def start(update: Update, context: CallbackContext) -> int:
    context.user_data["current_node"] = "/start"
    return choice(update, context)


def handle_answer(answer, update: Update):
    if len(answer.text) > 0:
        update.message.reply_text(answer.text)
    elif len(answer.links.text):
        links = answer.links
        buttons = []
        for url in links.url:
            buttons.append([InlineKeyboardButton(url.label, url=url.url)])
        reply_markup = InlineKeyboardMarkup(buttons)
        update.message.reply_text(
            links.text,
            reply_markup=reply_markup,
        )
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
    current_node_name = user_data["current_node"]

    current_node = CONVERSATION_DATA["node_by_name"][next_node_name]
    current_keyboard = CONVERSATION_DATA["keyboard_by_name"][current_node_name]

    for answer in current_node.answer[:-1]:
        handle_answer(answer, update)

    answer = current_node.answer[-1]
    if len(answer.text) == 0:
        handle_answer(answer, update)
        update.message.reply_text(
            PROMPT_REPLY,
            reply_markup=current_keyboard,
        )
    else:
        update.message.reply_text(
            answer.text,
            reply_markup=current_keyboard,
        )

    return CHOOSING


def start_bot():

    updater = Updater(
        token=os.getenv('TELEGRAM_BOT_API_KEY'), use_context=True)
    dispatcher = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSING: [
                MessageHandler(
                    Filters.regex('^(' + BACK + ')$'), back_choice),
                MessageHandler(
                    Filters.text & ~Filters.regex('^%s$' % (DONE)), choice),
            ],
        },
        fallbacks=[MessageHandler(Filters.regex('%s$' % (DONE)), done)],
    )

    dispatcher.add_handler(conv_handler)

    updater.start_polling()
    updater.idle()


def visit_node(node: conversation_proto.ConversationNode, consumer, visited: Set=set()):
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


def create_keyboards(node_by_name):
    keyboard_by_name = {}
    for name in node_by_name:
        if len(node_by_name[name].link) > 0:
            options = []
            for link in node_by_name[name].link:
                if len(link.name) > 0:
                    options.append([link.name])
                elif len(link.branch.name) > 0:
                    options.append([link.branch.name])
            if name in CONVERSATION_DATA["back_nav"]:
                options.append([BACK])
            options.append([DONE])
            keyboard_by_name[name] = ReplyKeyboardMarkup(
                options, one_time_keyboard=True)
    return keyboard_by_name


def create_back_nav_visitor(prev: conversation_proto.ConversationNode,
                            node: conversation_proto.ConversationNode, consumer,
                            visited: Set=set()):
    visited.add(node.name)
    consumer(prev, node)
    if len(node.link) > 0:
        for subnode in node.link:
            if len(subnode.branch.name) > 0 and not subnode.branch.name in visited:
                create_back_nav_visitor(node, subnode.branch, consumer)
            elif len(subnode.name) > 0 and not subnode.name in visited:
                create_back_nav_visitor(
                    node, CONVERSATION_DATA["node_by_name"][subnode.name], consumer)


def create_back_nav(root: conversation_proto.ConversationNode):
    back_nav = {}

    def updater(prev, node):
        if not prev is None:
            back_nav[node.name] = prev.name
    create_back_nav_visitor(None, root, updater)
    return back_nav


if __name__ == "__main__":
    with open('conversation_tree.textproto', 'r') as f:
        f_buffer = f.read()
        conversation = text_format.Parse(
            f_buffer, conversation_proto.Conversation())
    CONVERSATION_DATA["node_by_name"] = create_node_by_name(conversation)
    CONVERSATION_DATA["back_nav"] = create_back_nav(
        CONVERSATION_DATA["node_by_name"]["/start"])
    CONVERSATION_DATA["keyboard_by_name"] = create_keyboards(
        CONVERSATION_DATA["node_by_name"])
    start_bot()
