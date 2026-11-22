"""Transactional storage and role-scoped API for customer deliveries."""
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
import os
import secrets
import smtplib
import ssl
from time import time

import requests
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import JSON, Column, Float, Integer, String, Table, delete, insert, select, update

from .auth import digest
from .database import accounts, auth_database, schema
from .tracking import Position
from services.predictor_logic import PredictionError
from services.routing_api import RoutingError
from services.weather_api import WeatherError

deliveries = Table('deliveries', schema, Column('id', String, primary_key=True),
                   Column('owner', Integer, nullable=False), Column('driver', String, unique=True),
                   Column('viewer', String, unique=True), Column('expires', Float, nullable=False),
                   Column('created', Float, nullable=False), Column('data', JSON, nullable=False))
DAY = 86400


class NewDelivery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    departure: str = Field(min_length=1, max_length=300)
    arrival: str = Field(min_length=1, max_length=300)
    departure_time: str = Field(min_length=16, max_length=60)
    urban: bool
    phone: str = Field(pattern=r'^\+?[\d ()-]{7,22}$')
    driver_email: str = Field(default='', max_length=254)
    recipient_email: str = Field(default='', max_length=254)

    @field_validator('phone')
    @classmethod
    def valid_phone(cls, number):
        if not 7 <= sum(character.isdigit() for character in number) <= 15:
            raise ValueError('Numéro de téléphone invalide')
        return number

    @field_validator('driver_email', 'recipient_email')
    @classmethod
    def valid_email(cls, address):
        import re
        if address and not re.fullmatch(r'[^@\s<>;,]+@[^@\s<>;,]+\.[^@\s<>;,]+', address):
            raise ValueError('Adresse e-mail invalide')
        return address


class Fix(Position):
    captured: float = Field(strict=True, allow_inf_nan=False)


def mail_enabled():
    return bool(os.getenv('WASEL_MAIL_FROM') and (os.getenv('RESEND_API_KEY') or os.getenv('SMTP_HOST')))


def send_link(address, url, driver=False):
    subject = 'Wasel · ' + ('Démarrer la livraison' if driver else 'Suivre la livraison')
    body = f'Bonjour, voici votre lien privé pour cette livraison : {url}'
    sender = os.environ['WASEL_MAIL_FROM']
    if os.getenv('RESEND_API_KEY'):
        requests.post('https://api.resend.com/emails', headers={
            'Authorization': 'Bearer ' + os.environ['RESEND_API_KEY']},
            json={'from': sender, 'to': [address], 'subject': subject, 'text': body}, timeout=8).raise_for_status()
    else:
        message = EmailMessage()
        message['Subject'], message['From'], message['To'] = subject, sender, address
        message.set_content(body)
        with smtplib.SMTP(os.environ['SMTP_HOST'], int(os.getenv('SMTP_PORT', '587')), timeout=8) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if os.getenv('SMTP_USER'):
                smtp.login(os.environ['SMTP_USER'], os.environ['SMTP_PASSWORD'])
            smtp.send_message(message)


def distance_m(point, destination):
    a, b = radians(point['latitude']), radians(destination['lat'])
    delta = radians(destination['lon'] - point['longitude'])
    chord = sin((b-a)/2)**2 + cos(a)*cos(b)*sin(delta/2)**2
    return 12742000 * asin(sqrt(min(1, chord)))


def snapshot(data, now):
    return {key: data[key] for key in ('origin', 'destination', 'planned', 'eta', 'events', 'paused',
                                       'position', 'updated', 'eta_at')} | {
        'stale': data['updated'] is not None and now - data['position']['captured'] >= 30,
    }


def delivery_router(signed_in, get_service, clock=time):
    router = APIRouter(prefix='/api/deliveries')
    database = lru_cache(maxsize=1)(auth_database)

    def owner(request):
        if not signed_in(request):
            raise HTTPException(401, 'Connectez-vous pour accéder à vos livraisons.')
        return 1  # First-account installation in Phase 4.

    def access(conn, role, header):
        token = (header or '').removeprefix('Bearer ')
        if not header or not header.startswith('Bearer ') or len(token) != 43:
            raise HTTPException(404, 'Lien indisponible ou expiré.')
        row = conn.execute(select(deliveries).where(deliveries.c[role] == digest(token),
                           deliveries.c.expires > clock())).mappings().first()
        if not row:
            raise HTTPException(404, 'Lien indisponible ou expiré.')
        return row

    def save(conn, row, **changes):
        conn.execute(update(deliveries).where(deliveries.c.id == row['id']).values(data=row['data'], **changes))

    @router.get('')
    def listing(request: Request):
        customer = owner(request)
        with database().begin() as conn:
            expired = conn.execute(select(deliveries).where(deliveries.c.expires <= clock(),
                                  deliveries.c.driver.is_not(None))).mappings().all()
            for row in expired:
                row['data'].update(position=None, updated=None, history=[], phone=None)
                save(conn, row, driver=None, viewer=None)
            rows = conn.execute(select(deliveries).where(deliveries.c.owner == customer)
                                .order_by(deliveries.c.created.desc())).mappings()
            return {'deliveries': [{'id': row['id'], 'expired': row['expires'] <= clock(), **snapshot(row['data'], clock())} for row in rows],
                    'email_enabled': mail_enabled()}

    @router.post('', status_code=201)
    def create(body: NewDelivery, request: Request):
        customer = owner(request)
        prediction = get_service().predict_trip(body.departure, body.arrival, body.departure_time, urban=body.urban)
        route = prediction['route']
        planned = datetime.fromisoformat(prediction['estimated_arrival_time']).timestamp()
        now = clock()
        state = dict(origin=route['departure']['label'], destination=route['arrival']['label'],
                     target=route['arrival'], urban=body.urban, planned=planned, eta=planned, eta_at=None,
                     sharing=False, paused=False, position=None, history=[], updated=None, eta_requested=0,
                     events={'created': now}, phone=body.phone)
        driver, viewer = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        identifier = secrets.token_hex(12)
        with database().begin() as conn:
            conn.execute(insert(deliveries).values(id=identifier, owner=customer, driver=digest(driver),
                         viewer=digest(viewer), expires=now+DAY, created=now, data=state))
            address = conn.execute(select(accounts.c.email).where(accounts.c.id == customer)).scalar_one()
        base = os.getenv('WASEL_PUBLIC_URL', 'http://127.0.0.1:8000').rstrip('/')
        links = {'driver': base + '/livreur/' + driver, 'viewer': base + '/suivi/' + viewer}
        outcomes = []
        if mail_enabled():
            recipients = [(address, 'viewer')]
            if body.driver_email:
                recipients.append((body.driver_email, 'driver'))
            if body.recipient_email:
                recipients.append((body.recipient_email, 'viewer'))
            for recipient, role in dict.fromkeys(recipients):
                try:
                    send_link(recipient, links[role], role == 'driver')
                    outcomes.append('sent')
                except (requests.RequestException, OSError, ValueError, KeyError):
                    outcomes.append('failed')
        return {'id': identifier, 'links': links, 'mail': outcomes}

    @router.get('/viewer')
    def viewer(authorization: str | None = Header(None)):
        with database().connect() as conn:
            return snapshot(access(conn, 'viewer', authorization)['data'], clock())

    def driver_action(action, header, fix=None):
        now = clock()
        with database().begin() as conn:
            conn.exec_driver_sql('BEGIN IMMEDIATE')
            row = access(conn, 'driver', header)
            data = row['data']
            events = data['events']
            expires = row['expires']
            recalculate = False
            if 'delivered' in events:
                if action not in ('connect', 'deliver'):
                    raise HTTPException(410, 'Livraison terminée.')
            else:
                events.setdefault('connected', now)
                if action == 'start':
                    data.update(paused=False, sharing=True)
                elif action == 'position':
                    if not data['sharing']:
                        raise HTTPException(409, 'Partage en pause.')
                    if not now - 60 <= fix.captured <= now + 5:
                        raise HTTPException(422, 'Position trop ancienne ou heure incorrecte.')
                    last_write = data.get('last_write', data['updated'])
                    if last_write is not None and now - last_write < 4.5:
                        raise HTTPException(429, 'Patientez avant le prochain envoi.')
                    if data['position'] and fix.captured <= data['position']['captured']:
                        raise HTTPException(422, 'Position déjà reçue.')
                    point = fix.model_dump()
                    data.update(position=point, updated=now, last_write=now, paused=False,
                                history=(data['history'] + [point])[-12:])
                    events.setdefault('started', now)
                    if distance_m(point, data['target']) < 500:
                        events.setdefault('near', now)
                    recalculate = now - data['eta_requested'] >= 60
                    if recalculate:
                        data['eta_requested'] = now
                    expires = now + DAY
                elif action == 'pause':
                    data.update(paused=True, sharing=False, position=None, history=[], updated=None)
                elif action == 'deliver':
                    events['delivered'] = now
                    data.update(position=None, updated=None, history=[], paused=True, eta=now)
                    expires = now + 7200
                save(conn, row, expires=expires)
            return snapshot(data, now), (row['id'], now, data) if recalculate else None

    def update_eta(identifier, stamp, data):
        origin = dict(label='Position du livreur', lat=data['position']['latitude'], lon=data['position']['longitude'])
        start = datetime.fromtimestamp(stamp, timezone.utc) + timedelta(minutes=1)
        try:
            result = get_service().predict_trip(origin, data['target'], start.isoformat(), urban=data['urban'])
        except (PredictionError, RoutingError, WeatherError, requests.RequestException):
            return
        with database().begin() as conn:
            conn.exec_driver_sql('BEGIN IMMEDIATE')
            row = conn.execute(select(deliveries).where(deliveries.c.id == identifier)).mappings().first()
            if row and row['data']['sharing'] and 'delivered' not in row['data']['events'] and row['data']['eta_requested'] == stamp:
                row['data'].update(eta=stamp+60*result['duree_estimee_min'], eta_at=stamp)
                save(conn, row)

    @router.post('/driver/{action}')
    def driver(action: str, authorization: str | None = Header(None)):
        if action not in ('connect', 'start', 'pause', 'deliver'):
            raise HTTPException(404)
        state, _ = driver_action(action, authorization)
        return {key: state[key] for key in ('origin', 'destination', 'events')}

    @router.post('/position', status_code=204)
    def position(body: Fix, background: BackgroundTasks, authorization: str | None = Header(None)):
        _, job = driver_action('position', authorization, body)
        if job:
            background.add_task(update_eta, *job)
        return Response(status_code=204)

    return router
