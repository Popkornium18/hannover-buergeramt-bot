"""A telegram bot that can send notifications about early appointments at the
citizen centres (Bürgerämter) in Hannover, Germany"""
import threading
import logging
import datetime
from time import sleep
import telebot
import schedule
from crawler import download_all_appointments
from notification import (
    notification_apps_diff,
    notification_earliest,
    notification_stored_apps,
)
from sqlalchemy.orm import Session
from buergeramt_termine.repositories import (
    AppointmentRepository,
    UserRepository,
)
from buergeramt_termine.models import User
from buergeramt_termine import SessionMaker
from config import cfg

if cfg["LOG"] == "systemd":
    from cysystemd.journal import JournaldLogHandler

    log_handler = JournaldLogHandler()
    log_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
else:
    log_handler = logging.StreamHandler()
    log_handler.setFormatter(
        logging.Formatter("[%(name)s:%(asctime)s:%(levelname)s] %(message)s")
    )

BOT = telebot.AsyncTeleBot(cfg["API_KEY"], parse_mode="HTML")

logger = logging.getLogger("buergeramt_termine")
logger.addHandler(log_handler)
log_handler.setLevel(cfg["LOG_LEVEL"])
telebot.logger.handlers = []
telebot.logger.parent = logger
log_handler.setLevel(cfg["LOG_LEVEL"])
logger.setLevel(cfg["LOG_LEVEL"])
telebot.logger.setLevel(logging.INFO)


@BOT.message_handler(commands=["start", "Start", "help", "Help", "hilfe", "Hilfe"])
def usage(message: telebot.types.Message) -> None:
    """Replies with usage information"""
    logger.info("Requesting usage info")
    next_week: str = (datetime.date.today() + datetime.timedelta(7)).strftime(
        "%d.%m.%Y"
    )
    reply: str = f"""Du suchst dringend einen <b>Bürgeramt-Termin</b> in Hannover?
Dieser Bot kann dir dabei helfen! Schick einfach eine Nachricht mit deiner Deadline:

/deadline {next_week} (Das Datumsformat ist wichtig!)

Danach wird der Bot dich über alle spontanen Termine vor deiner Deadline informieren.
Wenn du deinen Termin bekommen hast und keine weiteren Benachrichtigungen bekommen willst, dann schicke /stop.

Den Quellcode dieses Bots findest du auf <a href='https://github.com/Popkornium18/hannover-buergeramt-bot'>GitHub</a>."""

    BOT.send_message(message.chat.id, reply, disable_web_page_preview=True)


@BOT.message_handler(commands=["termine", "Termine"])
def earliest_appointments(message: telebot.types.Message) -> None:
    """Sends the earliest 10 appointments currently available"""
    logger.info("Requesting earliest appointments")
    reply = notification_earliest()
    BOT.send_message(message.chat.id, reply)


@BOT.message_handler(commands=["deadline", "Deadline"])
def new_deadline(message: telebot.types.Message) -> None:
    """Adds a new user or modifies the deadline of an existing one"""
    request = message.text.split()
    if len(request) < 2:
        logger.warning(
            "Invalid request: %s requires a parameter", new_deadline.__name__
        )
        next_week: str = (datetime.date.today() + datetime.timedelta(7)).strftime(
            "%d.%m.%Y"
        )
        BOT.send_message(message.chat.id, f"Benutzung: /deadline {next_week}")
        return

    try:
        deadline = datetime.datetime.strptime(request[1], "%d.%m.%Y").date()
        deadline_str = request[1]
        logger.info("Invalid request: %s requires a parameter", new_deadline.__name__)
    except ValueError:
        logger.warning(
            "Invalid request: The deadline %s could not be parsed", request[1]
        )
        next_week: str = (datetime.date.today() + datetime.timedelta(7)).strftime(
            "%d.%m.%Y"
        )
        BOT.send_message(
            message.chat.id,
            f"Das Datum hat nicht das richtige Format. Benutzung: /datum {next_week}",
        )
        return

    session: Session = SessionMaker()
    user_repo = UserRepository(session)

    app_repo = AppointmentRepository(session)
    date_considered_early = app_repo.get_date_considered_early()
    if deadline > date_considered_early:
        app_early = app_repo.appointments_earlier_than(deadline)
        reply = ""
        if len(app_early) == 1:
            reply = "Vor deiner Deadline gibt es <i>einen Termin</i>.\n"
        else:
            reply = f"Vor deiner Deadline gibt es <i>{len(app_early)} Termine</i>.\n"
        reply += (
            f"Späteste Deadline: <b>{date_considered_early.strftime('%d.%m.%Y')}</b>.\n"
        )
        reply += "Benutze /termine um die frühesten Termine anzuzeigen."
        BOT.send_message(message.chat.id, reply)
        session.close()
        return

    user = user_repo.get_by_chat_id(message.chat.id)

    try:
        if not user:
            user = User(chat_id=message.chat.id, deadline=deadline)
            user_repo.add(user)
            BOT.send_message(
                message.chat.id,
                f"Du bekommst jetzt eine Benachrichtigung über alle Termine vor dem {deadline_str}.",
            )
        else:
            logger.info("Changing deadline of user %i", user.chat_id)
            user.deadline = deadline
            BOT.send_message(
                message.chat.id,
                f"Deine Deadline wurde aktualisiert: {deadline_str}.",
            )
    except ValueError:
        logger.warning("Invalid request: Deadline %s is in the past", deadline_str)
        BOT.send_message(
            message.chat.id,
            "Die Deadline darf nicht in der Vergangenheit liegen.",
        )
        session.close()
        return

    notification = notification_stored_apps(deadline=user.deadline)
    session.commit()
    session.close()

    if notification:
        BOT.send_message(message.chat.id, notification)


@BOT.message_handler(commands=["stop", "Stop"])
def delete_user(message: telebot.types.Message) -> None:
    """Deletes an existing user"""
    session: Session = SessionMaker()
    repo = UserRepository(session)
    user = repo.get_by_chat_id(message.chat.id)
    if user is None:
        logger.warning("Invalid request: User %i does not exist", message.chat.id)
        BOT.send_message(
            message.chat.id,
            "Du bekommst noch keine Benachrichtigungen. Benutze /deadline um die Benachrichtigungen zu aktivieren.",
        )
        session.close()
        return

    repo.delete(user)
    BOT.send_message(
        message.chat.id,
        "Du bekommst keine weiteren Benachrichtigungen. Benutze /deadline um die Benachrichtigungen wieder zu aktivieren.",
    )
    session.commit()
    session.close()


def check_appointments_and_notify() -> None:
    """Loads the current appointments and sends each user a notification about
    new appointments and appointments that are no longer available"""
    session: Session = SessionMaker()
    user_repo = UserRepository(session)
    if user_repo.empty:
        session.close()
        logger.debug(
            "No current users, skipping %s", check_appointments_and_notify.__name__
        )
        return

    app_repo = AppointmentRepository(session)
    apps_old = app_repo.list()
    apps_cur = download_all_appointments()

    if apps_cur == apps_old:
        logger.debug("No changes in appointments")
        return

    users = user_repo.list()
    logger.info("Creating notifications for %i users", len(users))
    for usr in users:
        reply = notification_apps_diff(deadline=usr.deadline, apps_cur=apps_cur)
        if not reply:
            logger.debug("No notification for %i", usr.chat_id)
            continue
        logger.debug("Sending notification to %i", usr.chat_id)
        BOT.send_message(usr.chat_id, reply)

    app_repo.store_new_appointments(apps_cur)
    session.commit()
    session.close()


def _refresh_db() -> None:
    """Loads new Appointments and stores them in the database"""
    session = SessionMaker()
    app_repo = AppointmentRepository(session)
    app_cur = download_all_appointments()
    app_repo.store_new_appointments(app_cur)
    session.commit()
    session.close()


def _import_appointments_if_db_empty() -> None:
    """Does an initial import of all appointments if the database is empty"""
    session = SessionMaker()
    app_repo = AppointmentRepository(session)
    if app_repo.empty:
        logger.info("No appointments in database. Refreshing.")
        _refresh_db()
    session.close()


def refresh_if_unused() -> None:
    """Refreshes the database if nobody is using the bot"""
    session = SessionMaker()
    user_repo = UserRepository(session)
    if user_repo.empty:
        logger.info("No users, only downloading appointments once a day")
        _refresh_db()
    session.close()


def _setup_schedule() -> None:
    """Sets up and runs recurring jobs"""
    schedule.every(5).minutes.do(check_appointments_and_notify)
    schedule.every(4).hours.do(refresh_if_unused)
    while True:
        schedule.run_pending()
        sleep(1)


def main():
    _import_appointments_if_db_empty()
    thread_schedule = threading.Thread(target=_setup_schedule)
    thread_schedule.start()
    BOT.polling(none_stop=True)


if __name__ == "__main__":
    main()
