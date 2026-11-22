"""Customer account storage for the GPS pilot."""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
schema = MetaData()
accounts = Table('accounts', schema,
                 Column('id', Integer, primary_key=True),
                 Column('email', String, nullable=False, unique=True),
                 Column('password_hash', String, nullable=False),
                 Column('google_subject', String))
tokens = Table('auth_tokens', schema,
               Column('digest', String, primary_key=True),
               Column('purpose', String, nullable=False),
               Column('expires', Integer, nullable=False))
attempts = Table('auth_attempts', schema,
                 Column('key', String, primary_key=True),
                 Column('count', Integer, nullable=False),
                 Column('expires', Integer, nullable=False))


def auth_database():
    path = Path(os.getenv('WASEL_AUTH_DB', str(ROOT / 'cache' / 'accounts.sqlite3')))
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(URL.create('sqlite', database=str(path)), poolclass=NullPool)
    schema.create_all(engine)
    return engine
