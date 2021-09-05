# Hannover Bürgeramt Bot

This Telegram bot allows you to subscribe to notifications about early
appointments at the citizen centres (Bürgerämter) in Hannover, Germany.
Please note that all texts except the documentation are in _german_.

## Usage

You can add [@hannover\_buergeramt\_bot](https://t.me/hannover_buergeramt_bot)
on Telegram.
The bot provides the following commands:

- `/deadline`: Subscribe to notifications about appointments earlier than a
given deadline. The date format is `DD.MM.YYYY`.
- `/termine`: Query the 10 earliest appointments
- `/stop`: Disable notifications
- `/start`, `/hilfe`: Print a help message

## Hosting

If you want to host this bot yourself you have to clone the repository and
create a new virtual environment in the directory of the cloned repo.

```
git clone https://github.com/Popkornium18/hannover-buergeramt-bot
cd hannover-buergeramt-bot
python -m venv venv
. venv/bin/activate
pip install wheel
pip install -r requirements.txt
```

If you intend to use `systemd` for logging, you have to install the optional
dependencies as well.
Make sure that you have the `systemd` header files installed.
On Debian/Ubuntu these headers are provided by `libsystemd-dev`.

```
pip install -r optional-requirements.txt
```

Next you have to copy the default configuration and add the API token of your bot.
Available configuration options are documented in the example config file as comments.

```
cp config.py{.example,}
```

Now you can run the bot like this:

```
python bot.py
```

If you want to use a systemd service to autostart the bot at boot time (which is _highly_ recommended), feel free to copy this template:

```
[Unit]
Description=Hannover Bürgeramt Bot
After=network.target

[Service]
Type=simple
User=YOUR_USER
Group=YOUR_GROUP
WorkingDirectory=/PATH/TO/hannover-buergeramt-bot
ExecStart=/PATH/TO/hannover-buergeramt-bot/venv/bin/python bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```
