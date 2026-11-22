"""Single-process, single-delivery GPS pilot."""
from dataclasses import dataclass
from datetime import datetime, timezone
import secrets
from threading import Lock
from time import time
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

LIFETIME_SECONDS = 2 * 60 * 60
STALE_SECONDS = 30
Token = Annotated[str | None, Header(alias='Authorization')]


class Position(BaseModel):
    model_config = ConfigDict(extra='forbid')
    latitude: float = Field(ge=-90, le=90, strict=True, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, strict=True, allow_inf_nan=False)
    accuracy: float = Field(ge=0, strict=True, allow_inf_nan=False)


@dataclass
class Session:
    driver: str
    viewer: str
    expires: float
    stopped: bool = False
    position: Position | None = None
    updated: float | None = None


def has_token(header, token):
    return bool(header and header.isascii() and secrets.compare_digest(header, f'Bearer {token}'))


def tracking_router(*, signed_in, clock=time):
    router = APIRouter(prefix='/api/tracking', tags=['tracking'])
    lock = Lock()
    session = None
    def current():
        nonlocal session
        if session and clock() >= session.expires:
            session = None
        return session

    def authorized(header, role):
        active = current()
        if active is None or not has_token(header, getattr(active, role)):
            raise HTTPException(404, 'Lien introuvable ou expiré.')
        return active

    @router.get('/session')
    def current_delivery(request: Request, response: Response):
        if not signed_in(request):
            raise HTTPException(401, 'Connectez-vous pour consulter la livraison.')
        response.headers['Cache-Control'] = 'no-store'
        with lock:
            active = current()
            return {'delivery': {'driver_token': active.driver, 'viewer_token': active.viewer}
                    if active and not active.stopped else None}

    @router.post('/session', status_code=201)
    def create_session(request: Request, response: Response):
        nonlocal session
        with lock:
            if not signed_in(request):
                raise HTTPException(401, 'Connectez-vous pour créer une livraison.')
            existing = current()
            if existing and not existing.stopped:
                raise HTTPException(409, 'Une livraison est déjà ouverte. Arrêtez son partage pour en créer une autre.')
            session = Session(secrets.token_urlsafe(32), secrets.token_urlsafe(32), clock() + LIFETIME_SECONDS)
            response.headers['Cache-Control'] = 'no-store'
            return {'driver_token': session.driver, 'viewer_token': session.viewer}

    @router.put('/position', status_code=204)
    def update_position(position: Position, authorization: Token = None):
        with lock:
            active = authorized(authorization, 'driver')
            if active.stopped:
                raise HTTPException(410, 'Ce partage a été arrêté.')
            active.position, active.updated = position, clock()
        return Response(status_code=204)

    @router.post('/stop', status_code=204)
    def stop(authorization: Token = None):
        with lock:
            active = authorized(authorization, 'driver')
            active.stopped, active.position, active.updated = True, None, None
        return Response(status_code=204)

    @router.get('/position')
    def latest(response: Response, authorization: Token = None):
        with lock:
            active = authorized(authorization, 'viewer')
            response.headers['Cache-Control'] = 'no-store'
            if active.stopped:
                return {'status': 'stopped', 'position': None, 'updated_at': None}
            if active.updated is None:
                return {'status': 'waiting', 'position': None, 'updated_at': None}
            status = 'stale' if clock() - active.updated >= STALE_SECONDS else 'live'
            return {'status': status, 'position': active.position,
                    'updated_at': datetime.fromtimestamp(active.updated, timezone.utc).isoformat()}

    return router
