from typing import List
import logging
import re
import urllib.parse as urlparse
from urllib.parse import parse_qs
from mechanize import Browser, HTMLForm, Link
from sqlalchemy.orm import Session
import datetime
from buergeramt_termine.models import Location, Appointment
from buergeramt_termine.repositories import LocationRepository
from buergeramt_termine import SessionMaker

logger = logging.getLogger("buergeramt_termine.crawler")

COMPANY = "stadt-hannover"
CAUSES = "0|1|2|3|4|5|6|7|15|34|33|31|32|28|23"
START_URL = f"https://e-government.hannover-stadt.de/online-terminvergabe/index.php?company={COMPANY}&cur_causes={CAUSES}"
FORM_ELEMENTS = {"number_of_people": "casetype_774", "cause_random": "casetype_801"}
BR = Browser()


def _get_datetime_from_url(url: str) -> datetime.datetime:
    """Extract the date and time from an appointment link"""
    parsed = parse_qs(urlparse.urlparse(url).query)
    return datetime.datetime.strptime(
        f"{parsed['year'][0]}-{parsed['month'][0]}-{parsed['day'][0]}T{parsed['time'][0]}",
        "%Y-%m-%dT%H:%M",
    )


def _get_appointments_for_date_link(date_link: Link) -> List[datetime.date]:
    """Load all appointments of a given date link"""
    BR.follow_link(date_link)
    appointment_links: List[Link] = list(
        BR.links(text_regex=re.compile(r"^(([01]\d|2[0-3]):([0-5]\d)|24:00)$"))
    )
    dates: List[datetime.date] = [
        _get_datetime_from_url(a.url) for a in appointment_links
    ]

    # Go back to date selection
    BR.back()
    return dates


def _handle_location(loc_link: Link, loc_id: int) -> List[Appointment]:
    """Load all appointments for a given location"""
    app: List[Appointment] = []
    BR.follow_link(loc_link)
    date_links: List[Link] = list(BR.links(text_regex=re.compile("Termine am")))
    for date_link in date_links:
        app = app + [
            Appointment(date_time=dt, location_id=loc_id)
            for dt in _get_appointments_for_date_link(date_link)
        ]

    nav_links: List[Link] = [
        l for l in BR.links() if ("class", "nat_navigation_button") in l.attrs
    ]
    if len(nav_links) > 1:
        # There's more
        app.extend(_handle_location(loc_link=nav_links[-1], loc_id=loc_id))
    logger.info("Found %i appointments", len(app))
    return app


def get_all_appointments() -> List[Appointment]:
    """Load all appointments from the e-government.hannover-stadt.de"""
    BR.open(START_URL)
    BR.select_form(name="frm_casetype")
    form: HTMLForm = BR.form
    # TODO: Check if you get other appointments with more people
    form[FORM_ELEMENTS["number_of_people"]] = ["1"]
    # I believe it doesn't matter what cause you pick, so we pick "Vorläufiger Personalausweis"
    form.find_control(FORM_ELEMENTS["cause_random"]).get().selected = True
    BR.submit()

    session: Session = SessionMaker()
    loc_repo = LocationRepository(session)
    app: List[Appointment] = []
    loc_links: List[Link] = list(BR.links(text_regex=re.compile("Bürgeramt")))
    for loc_link in loc_links:
        loc_name = loc_link.text.split(" ", 1)[1]
        loc = loc_repo.get_by_name(loc_name)
        if loc is None:
            loc = Location(name=loc_name)
            loc_repo.add(loc)
            session.commit()

        logger.info("Getting appointments for %s", loc)
        app.extend(_handle_location(loc_link, loc.id))

    session.close()
    return app
