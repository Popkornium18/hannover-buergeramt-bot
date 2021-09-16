"""Functions for creating HTML formatted notifications for Telegram"""
from __future__ import annotations
from typing import TYPE_CHECKING
import datetime
import logging
from buergeramt_termine import SessionMaker
from buergeramt_termine.repositories import (
    AppointmentRepository,
    LocationRepository,
    UserRepository,
)
from crawler import download_all_appointments

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


def _format_apps(apps_loc: List[Appointment], split_at: int = 5) -> str:
    """Formats a list of appointments for use in nofications.
    The parameter split_at defines how different dates are printed completely
    and defaults to 5.
    It is assumed that every appointment has the same location"""
    apps_loc_dates: List[datetime.date] = sorted({a.date_time.date() for a in apps_loc})
    reply = f"🏢 <b>{apps_loc[0].location.name}:</b>\n"
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
    session = SessionMaker()
    app_repo = AppointmentRepository(session)
    earliest = app_repo.earliest(limit)
    earliest_loc_id = sorted({a.location_id for a in earliest})

    reply = f"<b><u>Die {limit} frühesten Termine:</u></b>\n"
    for loc_id in earliest_loc_id:
        loc_earliest_app = [a for a in earliest if a.location_id == loc_id]

        if loc_earliest_app:
            reply += _format_apps(apps_loc=loc_earliest_app)

    return reply


def notification_stored_apps(deadline: datetime.date) -> str:
    """Creates a notification a for all stored appointments earlier
    than the deadline"""
    session = SessionMaker()
    app_repo = AppointmentRepository(session)
    early_apps = app_repo.appointments_earlier_than(deadline)
    if not early_apps:
        return "Momentan gibt es leider keine Termine vor deiner Deadline."

    early_loc_ids = sorted({a.location_id for a in early_apps})

    reply = "<b><u>Termine vor deiner Deadline:</u></b>\n"
    for loc_id in early_loc_ids:
        app_gone_early_loc = [a for a in early_apps if a.location_id == loc_id]
        logger.debug(
            "Location %s: %i early appointments", loc_id, len(app_gone_early_loc)
        )
        reply += _format_apps(apps_loc=app_gone_early_loc)

    session.close()
    logger.debug("Reply has length %i", len(reply))
    return reply


def notification_apps_diff(
    deadline: datetime.date,
    apps_cur: List[Appointment],
) -> str:
    """Creates a notification about the differences between the currently
    stored appointments and a list of newly downloaded appointments"""
    logger.info(
        "Requesting notification for deadline %s", deadline.strftime("%d.%m.%Y")
    )
    session = SessionMaker()
    app_repo = AppointmentRepository(session)
    apps_stored_early = app_repo.appointments_earlier_than(deadline)
    apps_cur_early = [a for a in apps_cur if a.date_time.date() < deadline]

    app_new = [a for a in apps_cur_early if a not in apps_stored_early]
    app_gone = [a for a in apps_stored_early if a not in apps_cur_early]

    logger.debug("apps_stored_early: %i appointments", len(apps_stored_early))
    logger.debug("app_cur_early: %i appointments", len(apps_cur_early))
    logger.debug("app_new: %i appointments", len(app_new))
    logger.debug("app_gone: %i appointments", len(app_gone))

    early_loc_ids = sorted(
        {a.location_id for a in app_new + app_gone if a.date_time.date() < deadline}
    )

    logger.debug("early_loc_ids: %i ids", len(early_loc_ids))

    if not early_loc_ids:
        logger.info(
            "No appointments earlier than %s have changed",
            deadline.strftime("%d.%m.%Y"),
        )
        return ""

    reply_new = reply_gone = ""
    for loc_id in early_loc_ids:
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

        if app_new_early_loc:
            logger.debug(
                "Location %i: %i new appointments", loc_id, len(app_new_early_loc)
            )
            reply_new += _format_apps(apps_loc=app_new_early_loc)

        if app_gone_early_loc:
            logger.debug(
                "Location %s: %i appointments gone", loc_id, len(app_gone_early_loc)
            )
            reply_gone += _format_apps(apps_loc=app_gone_early_loc)

    if reply_new:
        reply_new = "<b><u>Neue Termine:</u></b>\n" + reply_new
    if reply_gone:
        reply_gone = "<b><u>Diese Termine sind weg:</u></b>\n" + reply_gone

    session.close()
    reply = reply_new + reply_gone
    logger.debug("Reply has length %i", len(reply))
    return reply
