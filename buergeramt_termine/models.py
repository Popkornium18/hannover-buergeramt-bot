"""All classes necessary for the Hannover Buergeramt Bot"""
from __future__ import annotations
from typing import List
import datetime
from sqlalchemy import Column, Date, DateTime, String, BigInteger, Integer, ForeignKey
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Location(Base):

    __tablename__ = "locations"
    id = Column(Integer, primary_key=True)
    name = Column(String(512), nullable=False)
    appointments: List[Appointment] = relationship(
        "Appointment", back_populates="location"
    )

    def __init__(self, name: str):
        self.name = name
        self.appointments_new: List[Appointment] = []
        self.appointments_gone: List[Appointment] = []

    def __repr__(self):
        return f"Location({self.name}, {self.id})"


class Appointment(Base):

    __tablename__ = "appointments"
    id = Column(Integer, primary_key=True)
    date_time = Column(DateTime, nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"))
    location: Location = relationship("Location", back_populates="appointments")

    def __eq__(self, other):
        return (
            self.date_time == other.date_time and self.location_id == other.location_id
        )

    def __gt__(self, other):
        if self.date_time == other.date_time:
            return self.location.name > other.location.name
        return self.date_time > other.date_time

    def __repr__(self):
        return f"Appointment({self.date_time.strftime('%Y/%m/%d %H:%M')}, {self.location_id})"


class User(Base):
    """Stores chat_id's of telegram users and their deadlines"""

    __tablename__ = "users"
    chat_id = Column(BigInteger, primary_key=True)
    __deadline = Column(Date, nullable=False)

    def __init__(self, chat_id: int, deadline: datetime.date):
        self.chat_id = chat_id
        self.deadline = deadline

    @property
    def deadline(self) -> datetime.date:
        return self.__deadline

    @deadline.setter
    def deadline(self, deadline: datetime.date) -> None:
        if deadline < datetime.date.today():
            raise ValueError("The deadline must not be in the past")
        self.__deadline = deadline

    def __repr__(self):
        return f"User({self.chat_id}, {self.deadline.strftime('%Y/%m/%d')})"
