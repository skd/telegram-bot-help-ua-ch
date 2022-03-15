## Developer Guide
### Developing data model

`conversation.proto` is a schema for the data model. It tells how you should write the data model.
The data model is in `conversation_tree.textproto`

Before commiting, run `python3 validate.py` to ensure you did not introduce any problems.

### Testing your bot

[Telegram guide](https://core.telegram.org/bots#3-how-do-i-create-a-bot)

- Talk to [@BotFather](http://t.me/BotFather). Issue a command `/newbot` then follow the wizard, where you will set your bot username.
- At the end you will get a token. This will allow to start a bot on the username you specified in the wizard.
- Assuming you have cloned the git repo, run `env TELEGRAM_BOT_API_KEY="<token>" python3 bot.py`

## Functionality wishlist

