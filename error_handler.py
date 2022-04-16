from telegram import (
    MAX_MESSAGE_LENGTH,
    ParseMode,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import CallbackContext
import bot_messages
import config
import html
import json
import logging
import traceback


def max_arg_length(template_text):
    return MAX_MESSAGE_LENGTH - len(template_text) + 2


UPDATE_TEMPLATE = "Update:\n<pre>{}</pre>"
MAX_UPDATE_MESSAGE_LENGTH = max_arg_length(UPDATE_TEMPLATE)
CONTEXT_TEMPLATE = "context.user_data:\n<pre>{}</pre>"
MAX_CONTEXT_MESSAGE_LENGTH = max_arg_length(CONTEXT_TEMPLATE)
ERROR_TEMPLATE = "Error:\n<pre>{}</pre>"
MAX_ERROR_MESSAGE_LENGTH = max_arg_length(ERROR_TEMPLATE)

logger = logging.getLogger(__name__)


def handle_error(update: object, context: CallbackContext):
    logger.error(msg="Exception while handling an update:",
                 exc_info=context.error)

    if config.FEEDBACK_CHANNEL_ID is not None:
        tb_list = traceback.format_exception(None, context.error,
                                             context.error.__traceback__)
        tb_string = ''.join(tb_list)
        update_str = update.to_dict() if isinstance(update,
                                                    Update) else str(update)
        try:
            context.bot.send_message(
                chat_id=config.FEEDBACK_CHANNEL_ID,
                text="An exception was raised when handling an update:")
            update_msg = (UPDATE_TEMPLATE.format(
                html.escape(
                    json.dumps(update_str,
                               indent=2,
                               ensure_ascii=False,
                               default=str))[:MAX_UPDATE_MESSAGE_LENGTH]))
            context.bot.send_message(chat_id=config.FEEDBACK_CHANNEL_ID,
                                     text=update_msg,
                                     parse_mode=ParseMode.HTML)
            context_msg = (CONTEXT_TEMPLATE.format(
                json.dumps(context.user_data,
                           indent=2,
                           ensure_ascii=False,
                           default=str)[:MAX_CONTEXT_MESSAGE_LENGTH]))
            context.bot.send_message(chat_id=config.FEEDBACK_CHANNEL_ID,
                                     text=context_msg,
                                     parse_mode=ParseMode.HTML)
            error_msg = ERROR_TEMPLATE.format(
                html.escape(tb_string)[:MAX_ERROR_MESSAGE_LENGTH])
            context.bot.send_message(chat_id=config.FEEDBACK_CHANNEL_ID,
                                     text=error_msg,
                                     parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.warning(msg="Can't send a message to a feedback channel.",
                           exc_info=e)
    if isinstance(update, Update) and update.message is not None:
        update.message.reply_text(bot_messages.ERROR_OCCURRED,
                                  reply_markup=ReplyKeyboardMarkup(
                                      [[bot_messages.START_OVER]],
                                      one_time_keyboard=True))
