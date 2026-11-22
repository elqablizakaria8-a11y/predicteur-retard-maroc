"""Sign-in for the single customer account in the GPS pilot."""
from hashlib import sha256
import os
import re
import secrets
from time import time
from urllib.parse import urlencode

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
import requests
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .database import accounts, attempts, auth_database, tokens

COOKIE = 'wasel_customer'
OAUTH_COOKIE = 'wasel_google_state'
HOUR = 3600
PASSWORDS = PasswordHasher()
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(32))
INVALID = 'Adresse e-mail ou mot de passe incorrect.'


def digest(value):
    return sha256(value.encode()).hexdigest()


class Email(BaseModel):
    email: str = Field(max_length=254)


class Credentials(Email):
    password: str = Field(max_length=256)


class Setup(Credentials):
    setup_key: str = Field(max_length=256)


class Reset(BaseModel):
    token: str = Field(max_length=128)
    password: str = Field(max_length=256)


def auth_router():
    router = APIRouter(prefix='/api/auth')
    engine = None

    def db():
        nonlocal engine
        if engine is None:
            engine = auth_database()
        return engine

    def account(connection):
        return connection.execute(select(accounts).where(accounts.c.id == 1)).mappings().first()

    def valid_email(raw):
        email = raw.strip().lower()
        if not re.fullmatch(r'[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+', email):
            raise HTTPException(422, 'Saisissez une adresse e-mail valide.')
        return email

    def valid_password(password):
        if len(password) < 12:
            raise HTTPException(422, 'Choisissez un mot de passe de 12 caractères minimum.')

    def throttle(request, action):
        now = int(time())
        peer = request.client.host if request.client else 'local'
        key = digest(f'{action}:{peer}')
        with db().begin() as conn:
            conn.execute(delete(attempts).where(attempts.c.expires <= now))
            result = conn.execute(sqlite_insert(attempts).values(key=key, count=1, expires=now + 60)
                                  .on_conflict_do_update(index_elements=['key'],
                                                        set_={'count': attempts.c.count + 1})
                                  .returning(attempts.c.count)).scalar_one()
        if result > 5:
            raise HTTPException(429, 'Trop de tentatives. Réessayez dans une minute.')

    def protected(request):
        raw = request.cookies.get(COOKIE)
        if not raw:
            return False
        with db().connect() as conn:
            return conn.execute(select(tokens.c.digest).where(tokens.c.digest == digest(raw),
                                tokens.c.purpose == 'session', tokens.c.expires > int(time()))).first() is not None

    def issue_token(kind, lifetime):
        raw = secrets.token_urlsafe(32)
        now = int(time())
        with db().begin() as conn:
            conn.execute(delete(tokens).where(tokens.c.expires <= now))
            conn.execute(insert(tokens).values(digest=digest(raw), purpose=kind, expires=now + lifetime))
        return raw

    def sign_in(request, response, remember=False):
        lifetime = 30 * 24 * HOUR if remember else 8 * HOUR
        response.set_cookie(COOKIE, issue_token('session', lifetime), httponly=True,
                            samesite='strict', secure=request.url.scheme == 'https',
                            max_age=lifetime if remember else None)
        response.headers['Cache-Control'] = 'no-store'

    def google_config():
        return os.getenv('GOOGLE_CLIENT_ID'), os.getenv('GOOGLE_CLIENT_SECRET')

    def public_url():
        return os.getenv('WASEL_PUBLIC_URL', 'http://127.0.0.1:8000').rstrip('/')

    @router.get('/session')
    def status(request: Request, response: Response):
        with db().connect() as conn:
            configured = account(conn) is not None
        response.headers['Cache-Control'] = 'no-store'
        return {'signed_in': protected(request), 'setup_available': not configured,
                'google_available': all(google_config()),
                'reset_available': bool(os.getenv('RESEND_API_KEY') and os.getenv('WASEL_MAIL_FROM'))}

    @router.post('/setup')
    def setup(body: Setup, request: Request, response: Response):
        throttle(request, 'setup')
        key = os.getenv('WASEL_TRACKING_SETUP_KEY', '')
        if len(key) < 24 or not secrets.compare_digest(key.encode(), body.setup_key.encode()):
            raise HTTPException(403, 'Clé d’installation invalide ou configuration indisponible.')
        email = valid_email(body.email)
        valid_password(body.password)
        try:
            with db().begin() as conn:
                conn.execute(insert(accounts).values(id=1, email=email,
                                                      password_hash=PASSWORDS.hash(body.password)))
        except IntegrityError:
            raise HTTPException(409, 'Le compte client est déjà configuré.') from None
        sign_in(request, response)
        return {'signed_in': True}

    @router.post('/session')
    def login(body: Credentials, request: Request, response: Response, remember: bool = False):
        throttle(request, 'login')
        with db().connect() as conn:
            client = account(conn)
        try:
            PASSWORDS.verify(client['password_hash'] if client else DUMMY_HASH, body.password)
        except VerificationError:
            raise HTTPException(401, INVALID) from None
        if not client or not secrets.compare_digest(client['email'].encode(), body.email.strip().lower().encode()):
            raise HTTPException(401, INVALID)
        sign_in(request, response, remember)
        return {'signed_in': True}

    @router.delete('/session', status_code=204)
    def logout(request: Request, response: Response) -> None:
        raw = request.cookies.get(COOKIE)
        if raw:
            with db().begin() as conn:
                conn.execute(delete(tokens).where(tokens.c.digest == digest(raw), tokens.c.purpose == 'session'))
        response.delete_cookie(COOKIE, httponly=True, samesite='strict', secure=request.url.scheme == 'https')

    @router.post('/forgot', status_code=204)
    def forgot(body: Email, request: Request) -> None:
        throttle(request, 'forgot')
        key, sender = os.getenv('RESEND_API_KEY'), os.getenv('WASEL_MAIL_FROM')
        if not key or not sender:
            raise HTTPException(503, 'La récupération par e-mail est indisponible.')
        with db().connect() as conn:
            client = account(conn)
        if client and client['email'] == body.email.strip().lower():
            link = f"{public_url()}/#/suivi?reset={issue_token('reset', 15 * 60)}"
            try:
                requests.post('https://api.resend.com/emails', headers={'Authorization': f'Bearer {key}'},
                              json={'from': sender, 'to': [client['email']],
                                    'subject': 'Réinitialisez votre mot de passe Wasel',
                                    'text': f'Ouvrez ce lien valable 15 minutes : {link}'}, timeout=8)
            except requests.RequestException:
                pass

    @router.post('/reset', status_code=204)
    def reset(body: Reset, request: Request) -> None:
        throttle(request, 'reset')
        valid_password(body.password)
        with db().begin() as conn:
            consumed = conn.execute(delete(tokens).where(tokens.c.digest == digest(body.token),
                                    tokens.c.purpose == 'reset', tokens.c.expires > int(time())))
            if consumed.rowcount != 1:
                raise HTTPException(400, 'Ce lien est invalide ou a expiré.')
            conn.execute(update(accounts).where(accounts.c.id == 1).values(password_hash=PASSWORDS.hash(body.password)))
            conn.execute(delete(tokens))

    @router.get('/google')
    def google_start(request: Request):
        client_id, secret = google_config()
        if not client_id or not secret:
            raise HTTPException(404)
        state = secrets.token_urlsafe(32)
        query = urlencode({'client_id': client_id, 'redirect_uri': public_url() + '/api/auth/google/callback',
                           'response_type': 'code', 'scope': 'openid email', 'state': state,
                           'nonce': digest(state)})
        response = RedirectResponse('https://accounts.google.com/o/oauth2/v2/auth?' + query)
        response.set_cookie(OAUTH_COOKIE, state, max_age=600, path='/api/auth/google/callback',
                            samesite='lax', httponly=True, secure=request.url.scheme == 'https')
        return response

    @router.get('/google/callback')
    def google_callback(request: Request, state: str = '', code: str = ''):
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2.id_token import verify_oauth2_token
        response = RedirectResponse('/#/suivi?google=erreur')
        response.delete_cookie(OAUTH_COOKIE, path='/api/auth/google/callback')
        response.headers['Referrer-Policy'] = 'no-referrer'
        client_id, secret = google_config()
        cookie = request.cookies.get(OAUTH_COOKIE, '')
        if not client_id or not secret or not code or not cookie or digest(cookie) != digest(state):
            return response
        try:
            exchange = requests.post('https://oauth2.googleapis.com/token', data={
                'code': code, 'client_id': client_id, 'client_secret': secret,
                'redirect_uri': public_url() + '/api/auth/google/callback',
                'grant_type': 'authorization_code'}, timeout=8)
            exchange.raise_for_status()
            claims = verify_oauth2_token(exchange.json()['id_token'], GoogleRequest(), client_id)
        except (requests.RequestException, ValueError, KeyError):
            return response
        if claims.get('nonce') != digest(state) or not claims.get('email_verified') or not claims.get('sub'):
            return response
        with db().begin() as conn:
            client = account(conn)
            if not client or client['email'] != claims.get('email', '').lower():
                return response
            google_owns_email = client['email'].endswith('@gmail.com') or bool(claims.get('hd'))
            if not client['google_subject'] and not google_owns_email:
                return response
            linked = conn.execute(update(accounts).where(accounts.c.id == 1,
                (accounts.c.google_subject.is_(None)) | (accounts.c.google_subject == claims['sub']))
                .values(google_subject=claims['sub']))
            if linked.rowcount != 1:
                return response
        response.headers['Location'] = '/#/suivi'
        sign_in(request, response)
        return response

    return router, protected
