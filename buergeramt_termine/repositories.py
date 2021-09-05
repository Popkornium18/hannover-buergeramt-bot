"""Repository classes for all models"""
import logging
import datetime
from typing import List
from sqlalchemy.orm import Session
from buergeramt_termine.models import Appointment, Location, User

logger = logging.getLogger("buergeramt_termine.repositories")


class AppointmentRepository:
    """Repository for Appointment objects"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, appointment: Appointment) -> None:
        """Persist a new Appointment object"""
        self.session.add(appointment)
        logger.info("Added new appointment %s", appointment)

    def delete(self, appointment: Appointment) -> None:
        """Delete an existing Appointment object from the database"""
        self.session.delete(appointment)
        logger.info("Deleted appointment %s", appointment)

    def list(self) -> List[Appointment]:
        """Get all Appointment objects"""
        return self.session.query(Appointment).all()

    def appointments_earlier_than(self, date: datetime.date) -> List[Appointment]:
        """Get all appointments earlier than a date"""
        earlier = [a for a in self.list() if a.date_time.date() < date]
        logger.debug(
            "Appointments earlier than %s: %i", date.strftime("%Y-%m-%d"), len(earlier)
        )
        return earlier

    def store_new_appointments(self, app_cur: List[Appointment]) -> None:
        """Store a new list of appointments in the database"""
        loc_repo = LocationRepository(self.session)

        app_old = self.list()
        app_new = [a for a in app_cur if a not in app_old]
        app_gone = [a for a in app_old if a not in app_cur]

        for loc in loc_repo.list():
            app_new_loc = [a for a in app_new if a.location_id == loc.id]
            app_gone_loc = [a for a in app_gone if a.location_id == loc.id]
            if not app_new_loc and not app_gone_loc:
                continue
            loc.appointments.extend(app_new_loc)
            for app in app_gone_loc:
                self.delete(app)

    def earliest(self, count: int = 1) -> List[Appointment]:
        """Return the n earliest appointments"""
        return (
            self.session.query(Appointment)
            .order_by(Appointment.date_time)
            .limit(count)
            .all()
        )

    def get_date_considered_early(self) -> datetime.date:
        """Returns all early appointments. An appointment is considered
        early if there is a gap of at least one week between 2 subsequent
        appointments later than the appointment."""
        apps_sorted_rev = sorted(self.list(), reverse=True)
        date_consider_early = apps_sorted_rev[-1].date_time.date()
        for later, earlier in zip(apps_sorted_rev, apps_sorted_rev[1:]):
            if (later.date_time - earlier.date_time).days > 6:
                date_consider_early = later.date_time.date()
                break

        logger.debug(
            "Everything before %s can be considered early",
            date_consider_early.strftime("%Y-%m-%d"),
        )
        return date_consider_early

    @property
    def empty(self) -> bool:
        """Checks if there are appointments in the database"""
        apps = self.list()
        logger.debug("Current appointments: %i", len(apps))
        return len(apps) == 0


class LocationRepository:
    """Repository for Location objects"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, location: Location) -> None:
        """Persist a new Location object"""
        self.session.add(location)
        logger.info("Added new Location for %s", location)

    def get_by_id(self, query: int) -> Location:
        """Get the Location with a specific id"""
        return self.session.query(Location).filter_by(id=query).first()

    def get_by_name(self, query: str) -> Location:
        """Get the Location with a specific name"""
        return self.session.query(Location).filter_by(name=query).first()

    def list(self) -> List[Location]:
        """Get all Location objects"""
        return self.session.query(Location).all()


class UserRepository:
    """Repository for User objects"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, user: User) -> None:
        """Persist a new User object"""
        self.session.add(user)
        logger.info("Added new user %s", user)

    def delete(self, user: User) -> None:
        """Delete an existing User object from the database"""
        self.session.delete(user)
        logger.info("Deleted user %s", user)

    def get_by_chat_id(self, chat_id: int) -> User:
        """Get the Subscriber with a specific ID"""
        logger.debug("Looking up user with chat id %i", chat_id)
        user = self.session.query(User).filter_by(chat_id=chat_id).first()
        if not user:
            logger.warning("No user with chat id %i found", chat_id)
        return user

    @property
    def empty(self) -> bool:
        """Checks if the bot has users"""
        users = self.list()
        logger.debug("Current users: %i", len(users))
        return len(users) == 0

    def list(self) -> List[User]:
        """Get all User objects"""
        users = self.session.query(User).all()
        logger.debug("Current users: %i", len(users))
        return users
