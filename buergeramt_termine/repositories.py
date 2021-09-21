"""Repository classes for all models"""
from __future__ import annotations
from typing import TYPE_CHECKING
import logging
import datetime
from buergeramt_termine.models import Appointment, Location, User
from sqlalchemy import func

if TYPE_CHECKING:
    from typing import List, Set
    from sqlalchemy.orm import Session


logger = logging.getLogger("buergeramt_termine.repositories")


class AppointmentRepository:
    """Repository for Appointment objects"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, appointment: Appointment) -> None:
        """Persist a new Appointment object"""
        self.session.add(appointment)
        logger.debug("Added new appointment %s", appointment)

    def delete(self, appointment: Appointment) -> None:
        """Delete an existing Appointment object from the database"""
        self.session.delete(appointment)
        logger.debug("Deleted appointment %s", appointment)

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

    def get_by_deadline(self, deadline: datetime.date) -> List[User]:
        """Get all users with a specific deadline"""
        logger.debug("Looking up user with deadline %s", deadline.strftime("%Y-%m-%d"))
        users = self.session.query(User).filter(User.deadline == deadline).all()
        if not users:
            logger.info(
                "No users with deadline %s found", deadline.strftime("%Y-%m-%d")
            )
        return users

    def get_deadlines(self) -> Set[datetime.date]:
        """Returns the deadlines of all users as a set"""
        return {u.deadline for u in self.list()}

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
