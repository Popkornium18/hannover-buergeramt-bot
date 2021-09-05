from buergeramt_termine.models import Base
from config import cfg
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine(cfg["DB"], pool_pre_ping=True, future=True)
SessionMaker = sessionmaker(bind=engine)

Base.metadata.create_all(engine)
