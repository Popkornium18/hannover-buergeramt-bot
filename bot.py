"""A telegram bot that can send notifications about early appointments at the
citizen centres (Bürgerämter) in Hannover, Germany"""
import threading
from typing import List
import logging
import datetime
from time import sleep
import telebot
import schedule
from telebot.types import Location, Message
from crawler import get_all_appointments
from sqlalchemy.orm import Session
from buergeramt_termine.repositories import (
    AppointmentRepository,
    LocationRepository,
    UserRepository,
)
from buergeramt_termine.models import Appointment, User
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
    reply: str = f"""<b>Der Bot ist noch nicht ganz fertig, solange der Text hier steht brauchst du den Bot nicht nutzen</b>

Du suchst dringend einen Bürgeramt-Termin in Hannover?
Dieser Bot kann dir dabei helfen! Schick einfach eine Nachricht mit deiner Deadline:

/deadline {next_week}

Danach wird der Bot dich über alle spontanen Termine vor deiner Deadline informieren.
Wenn du deinen Termin bekommen hast und keine weiteren Benachrichtigungen bekommen willst, dann schicke /stop."""

    BOT.send_message(message.chat.id, reply)


@BOT.message_handler(commands=["termine", "Termine"])
def earliest_appointments(message: telebot.types.Message) -> None:
    """Sends the earliest 10 appointments currently available"""
    logger.info("Requesting earliest appointments")
    session = SessionMaker()
    app_repo = AppointmentRepository(session)
    loc_repo = LocationRepository(session)
    earliest = app_repo.earliest(10)
    earliest_loc_id = sorted({a.location_id for a in earliest})

    reply = "<b><u>Die 10 frühesten Termine:</u></b>\n"
    for loc_id in earliest_loc_id:
        loc = loc_repo.get_by_id(loc_id)
        loc_earliest_app = [a for a in earliest if a.location_id == loc.id]

        if loc_earliest_app:
            reply += _format_app_list_location(app_list=loc_earliest_app, loc=loc)

    BOT.send_message(message.chat.id, reply)
    session.close()


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

    notification = _format_notification(deadline=user.deadline)
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


def _format_app_list_date(app_list: List[Appointment], date: datetime.date) -> str:
    max_app_reply = 5
    app_list_date = [a for a in app_list if a.date_time.date() == date]
    reply = f"• {date.strftime('%d.%m.%Y')}: "
    if len(app_list_date) <= max_app_reply:
        times = ", ".join([a.date_time.strftime("%H:%M") for a in app_list_date])
        reply += f"<i>{times}</i>\n"
    else:
        split = 3
        app_list_date_first = app_list_date[:split]
        app_list_date_rest = app_list_date[split:]
        times = ", ".join([a.date_time.strftime("%H:%M") for a in app_list_date_first])
        reply += f"<i>{times}, ... (+{len(app_list_date_rest)})</i>\n"
    return reply


def _format_app_list_location(app_list: List[Appointment], loc: Location) -> str:
    app_list_dates: List[datetime.date] = sorted({a.date_time.date() for a in app_list})
    reply = f"🏢 <b>{loc.name}:</b>\n"
    split = 5
    loc_first = app_list_dates[:split]
    loc_rest = app_list_dates[split:]
    for date in loc_first:
        reply += _format_app_list_date(app_list=app_list, date=date)

    if loc_rest:
        app_rest = [a for a in app_list if a.date_time.date() in loc_rest]
        if len(app_rest) == 1:
            reply += "• <i>Ein weiterer Termin</i>\n"
        else:
            reply += f"• <i>{len(app_rest)} weitere Termine</i>\n"

    return reply


def _format_notification(
    deadline: datetime.date,
    app_cur: List[Appointment] = None,
    app_old: List[Appointment] = None,
) -> str:
    """Formats a notification message about appointments earlier than a deadline.
    app_cur defaults to the currently stored appointments.
    app_old defaults to []."""
    logger.info(
        "Requesting notification for deadline %s", deadline.strftime("%d.%m.%Y")
    )
    session = SessionMaker()
    loc_repo = LocationRepository(session)
    app_repo = AppointmentRepository(session)
    app_early = app_repo.appointments_earlier_than(deadline)
    app_old = [] if app_old is None else app_early
    app_cur = app_early if app_cur is None else app_cur
    app_new = [a for a in app_cur if a not in app_old]
    app_gone = [a for a in app_old if a not in app_cur]
    logger.debug("app_old: %i appointments", len(app_old))
    logger.debug("app_cur: %i appointments", len(app_cur))
    logger.debug("app_new: %i appointments", len(app_new))
    logger.debug("app_gone: %i appointments", len(app_gone))

    early_loc_ids = sorted(
        {a.location_id for a in app_new + app_gone if a.date_time.date() < deadline}
    )

    if not early_loc_ids:
        logger.info(
            "No appointments earlier than %s have changed",
            deadline.strftime("%d.%m.%Y"),
        )
        return ""

    reply_new = reply_gone = ""
    for loc_id in early_loc_ids:
        cur_loc = loc_repo.get_by_id(loc_id)
        app_new_early_loc = [
            a
            for a in app_new
            if a.location_id == loc_id and a.date_time.date() < deadline
        ]
        app_gone_early_loc = [
            a
            for a in app_gone
            if a.location_id == loc_id and a.date_time.date() < deadline
        ]
        logger.debug(
            "%s: %i new early appointments", cur_loc.name, len(app_new_early_loc)
        )
        logger.debug(
            "%s: %i early appointments gone", cur_loc.name, len(app_gone_early_loc)
        )

        if app_new_early_loc:
            reply_new += _format_app_list_location(
                app_list=app_new_early_loc, loc=cur_loc
            )

        if app_gone_early_loc:
            reply_gone += _format_app_list_location(
                app_list=app_gone_early_loc, loc=cur_loc
            )

    if reply_new:
        reply_new = "<b><u>Neue Termine:</u></b>\n" + reply_new
    if reply_gone:
        reply_gone = "<b><u>Diese Temine sind weg:</u></b>\n" + reply_gone

    session.close()
    reply = reply_new + reply_gone
    logger.debug("Reply has length %i", len(reply))
    return reply


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

    users = user_repo.list()

    app_cur = get_all_appointments()

    app_repo = AppointmentRepository(session)
    app_old = app_repo.list()

    if app_cur == app_old:
        logger.debug("No changes in appointments")
        return

    logger.info("Creating notifications for %i users", len(users))
    for usr in users:
        reply = _format_notification(
            deadline=usr.deadline, app_old=app_old, app_cur=app_cur
        )
        if not reply:
            logger.debug("No notification for %i", usr.chat_id)
            continue
        logger.debug("Sending notification to %i", usr.chat_id)
        BOT.send_message(usr.chat_id, reply)

    app_repo.store_new_appointments(app_cur)
    session.commit()
    session.close()


def _refresh_db() -> None:
    """Loads new Appointments and stores them in the database"""
    session = SessionMaker()
    app_repo = AppointmentRepository(session)
    app_cur = get_all_appointments()
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
