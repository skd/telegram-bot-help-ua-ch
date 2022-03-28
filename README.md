## Developer Guide
### Prerequisites

Install the required Python dependencies:

```
$ pip3 install -r requirements.txt
```

### Developing data model

`conversation.proto` is a schema for the data model. It tells how you should write the data model.
The data model is in `conversation_tree.textproto`

Before committing, run `python3 -m pytest` to ensure you did not introduce any problems.

### Testing your bot

[Telegram guide](https://core.telegram.org/bots#3-how-do-i-create-a-bot)

- Talk to [@BotFather](http://t.me/BotFather). Issue a command `/newbot` then follow the wizard, where you will set your bot username.
- At the end you will get a token. This will allow to start a bot on the username you specified in the wizard.
- Assuming you have cloned the git repo, run `env TELEGRAM_BOT_API_KEY="<token>" python3 bot.py`

#### Testing feedback collection

Feedback is forwarded to a channel of choice, which is controlled via
an env variable `FEEDBACK_CHANNEL_ID`. Here's how you test the bot:

- Create a new channel on telegram and invite your bot to it.
- Invite a bot `@RawDataBot` to your channel. It should print out your channel id (int) upon joining the channel.
- Start your bot by running `env TELEGRAM_BOT_API_KEY="<token>" FEEDBACK_CHANNEL_ID="<your channel id>" python3 bot.py`
- Go to a private chat with your bot, click on enter feedback, and follow-through the flow.
- Your bot should have forwarded the feedback to your channel.

## Functionality wishlist

- [ ] GUI editor of a conversation tree
- [X] Data pulls of conversation tree from GitHub on command
- [ ] Inline buttons. A scripter should be allowed to choose what kind of buttons to have attached. They should work same as keyboard buttons.
- [ ] Persistent stats collection to redis.
- [x] Simple Stats collection. We should collect basic stats (number of users, etc). Stats could be made accessible via a command.
- [x] Persistent sessions. Persist bot state across restarts (in an encrypted form).
- [x] Option to collect feedback.
- [x] Handle errors by forwarding them to a feedback channel.
- [x] Better back navigation. We should track the user nav and have a proper "back" support, that works fine not only in Trees but also DAGs. Back should also support inline buttons. (Credit: Alex)
- [x] Send a map pointer with addresses. (Credit: Alex)
- [x] Tests on pull request. We run validate.py manually, often we forget, makes deployment harder. It should be converted to a test and ran automatically. (Credit: Alex)

### Nice to have

- [ ] Move strings displayed to the user from the code to a config (conversation_tree.textproto). START_NODE should be also configurable.
- [ ] conversation_tree.textproto formatter.
