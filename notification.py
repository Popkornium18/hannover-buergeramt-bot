"""Functions for creating HTML formatted notifications for Telegram"""
from __future__ import annotations
from typing import TYPE_CHECKING
import datetime
import logging
from urllib.error import URLError
from buergeramt_termine import SessionMaker
from buergeramt_termine.repositories import (
    AppointmentRepository,
    LocationRepository,
    UserRepository,
)
from crawler import DownloadException, download_all_appointments

if TYPE_CHECKING:
    from buergeramt_termine.models import Appointment
    from typing import Dict, List
    from sqlalchemy.orm import Session

logger = logging.getLogger("buergeramt_termine.notification")


def _format_apps_date(apps_loc_date: List[Appointment], split_at: int = 5) -> str:
    """Formats a list of appointments on a date for use in a notification.
    The parameter split_at defines how many appointment times are printed
    completely per date and defaults to 5.
    It is assumed that all appointments are on the same date and at the
    same location"""
    apps_loc_date.sort()

    date = apps_loc_date[0].date_time.date()
    reply = f"• {date.strftime('%d.%m.%Y')}: "

    if len(apps_loc_date) <= split_at:
        times = ", ".join([a.date_time.strftime("%H:%M") for a in apps_loc_date])
        reply += f"<i>{times}</i>\n"
    else:
        # 2 dates less roughly results in a similar line length when shortening
        shorten_after = split_at - 2
        app_list_date_first = apps_loc_date[:shorten_after]
        app_list_date_rest = apps_loc_date[shorten_after:]
        times = ", ".join([a.date_time.strftime("%H:%M") for a in app_list_date_first])
        reply += f"<i>{times}, ... (+{len(app_list_date_rest)})</i>\n"
    return reply


def _format_apps(apps_loc: List[Appointment], name: str, split_at: int = 5) -> str:
    """Formats a list of appointments for use in nofications.
    The parameter split_at defines how different dates are printed completely
    and defaults to 5.
    It is assumed that every appointment has the same location"""
    if not apps_loc:
        return ""
    apps_loc_dates: List[datetime.date] = sorted({a.date_time.date() for a in apps_loc})
    reply = f"🏢 <b>{name}:</b>\n"
    loc_first = apps_loc_dates[:split_at]
    loc_rest = apps_loc_dates[split_at:]
    for date in loc_first:
        apps_loc_date = [a for a in apps_loc if a.date_time.date() == date]
        reply += _format_apps_date(apps_loc_date=apps_loc_date)

    if loc_rest:
        app_rest = [a for a in apps_loc if a.date_time.date() in loc_rest]
        if len(app_rest) == 1:
            reply += "• <i>Ein weiterer Termin</i>\n"
        else:
            reply += f"• <i>{len(app_rest)} weitere Termine</i>\n"

    return reply


def notification_earliest(limit: int = 10) -> str:
    """Returns a notification about the n earliest appointments. The limit
    parameter specifies how many appointments should be included. By default
    10 appointments are returned"""
    session: Session = SessionMaker()
    app_repo = AppointmentRepository(session)
    loc_repo = LocationRepository(session)
    earliest = app_repo.earliest(limit)
    earliest_loc_id = sorted({a.location_id for a in earliest})

    reply = f"<b><u>Die {limit} frühesten Termine:</u></b>\n"
    for loc_id in earliest_loc_id:
        loc = loc_repo.get_by_id(loc_id)
        loc_earliest_app = [a for a in earliest if a.location_id == loc.id]

        if loc_earliest_app:
            reply += _format_apps(apps_loc=loc_earliest_app, name=loc.name)

    return reply


def notification_stored_apps(deadline: datetime.date) -> str:
    """Creates a notification a for all stored appointments earlier
    than the deadline"""
    session: Session = SessionMaker()
    app_repo = AppointmentRepository(session)
    loc_repo = LocationRepository(session)
    early_apps = app_repo.appointments_earlier_than(deadline)
    if not early_apps:
        return "Momentan gibt es leider keine Termine vor deiner Deadline."

    early_loc_ids = sorted({a.location_id for a in early_apps})

    reply = "<b><u>Termine vor deiner Deadline:</u></b>\n"
    for loc_id in early_loc_ids:
        loc = loc_repo.get_by_id(loc_id)
        app_gone_early_loc = [a for a in early_apps if a.location_id == loc.id]
        logger.debug(
            "Location %s: %i early appointments", loc.name, len(app_gone_early_loc)
        )
        reply += _format_apps(apps_loc=app_gone_early_loc, name=loc.name)

    session.close()
    logger.debug("Reply has length %i", len(reply))
    return reply


def create_notifications_new_gone() -> Dict[datetime.date, str]:
    """Downloads new appointments and returns a notification for each deadline
    in the database. After that the new appointments are persisted"""
    try:
        apps_cur = download_all_appointments()
    except DownloadException:
        return {}

    session: Session = SessionMaker()
    app_repo = AppointmentRepository(session)

    if apps_cur == app_repo.list():
        logger.debug("No changes in appointments")
        return {}

    loc_repo = LocationRepository(session)
    locs = loc_repo.list()

    for loc in locs:
        loc.set_apps_new_gone(apps=apps_cur)

    user_repo = UserRepository(session)
    deadlines_rev = sorted(user_repo.get_deadlines(), reverse=True)
    notifications: Dict[datetime.date, str] = {}
    for deadline in deadlines_rev:
        reply_new = reply_gone = ""

        for loc in locs:
            loc_new_early = [a for a in loc.apps_new if a.date_time.date() < deadline]
            loc_gone_early = [a for a in loc.apps_gone if a.date_time.date() < deadline]
            reply_new += _format_apps(apps_loc=loc_new_early, name=loc.name)
            reply_gone += _format_apps(apps_loc=loc_gone_early, name=loc.name)

        if reply_new:
            reply_new = "<b><u>Neue Termine:</u></b>\n" + reply_new + "\n"
        if reply_gone:
            reply_gone = "<b><u>Diese Termine sind weg:</u></b>\n" + reply_gone

        notification = reply_new + reply_gone
        if notification:
            notifications[deadline] = notification
        else:
            break

    for loc in locs:
        loc.appointments.extend(loc.apps_new)
        for app in loc.apps_gone:
            app_repo.delete(app)

    session.commit()
    session.close()
    return notifications
