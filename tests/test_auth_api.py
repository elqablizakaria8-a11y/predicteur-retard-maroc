import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import auth_router
from api.tracking import tracking_router


class CustomerAuthenticationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        settings = patch.dict(os.environ, {
            'WASEL_AUTH_DB': str(Path(temporary.name) / 'accounts.sqlite3'),
            'WASEL_TRACKING_SETUP_KEY': 'authentication-test-fixture-key',
            'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '',
        })
        settings.start()
        self.addCleanup(settings.stop)
        app = FastAPI()
        router, signed_in = auth_router()
        app.include_router(router)
        app.include_router(tracking_router(signed_in=signed_in))
        self.client = TestClient(app, base_url='https://testserver')
        self.addCleanup(self.client.close)
        self.credentials = {'email': 'test@example.com', 'password': 'example fixture password'}

    def test_first_account_cookie_and_logout(self):
        self.assertTrue(self.client.get('/api/auth/session').json()['setup_available'])
        self.assertEqual(self.client.post('/api/tracking/session').status_code, 401)
        payload = dict(self.credentials, setup_key=os.environ['WASEL_TRACKING_SETUP_KEY'])
        response = self.client.post('/api/auth/setup', json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn('HttpOnly', response.headers['set-cookie'])
        self.assertIn('Secure', response.headers['set-cookie'])
        self.assertEqual(self.client.post('/api/auth/setup', json=payload).status_code, 409)
        self.assertTrue(self.client.get('/api/auth/session').json()['signed_in'])
        delivery = self.client.post('/api/tracking/session')
        self.assertEqual(delivery.status_code, 201)
        self.assertEqual(self.client.delete('/api/auth/session').status_code, 204)
        self.assertFalse(self.client.get('/api/auth/session').json()['signed_in'])
        self.assertEqual(self.client.post('/api/tracking/session').status_code, 401)
        self.assertEqual(self.client.get('/api/tracking/position', headers={
            'Authorization': f"Bearer {delivery.json()['viewer_token']}",
        }).status_code, 200)
        remembered = self.client.post('/api/auth/session?remember=true', json=self.credentials)
        self.assertIn('Max-Age=', remembered.headers['set-cookie'])

    def test_generic_error_rate_limit_and_disabled_google(self):
        self.assertFalse(self.client.get('/api/auth/session').json()['google_available'])
        wrong = self.client.post('/api/auth/session', json=self.credentials)
        unknown = self.client.post('/api/auth/session', json=dict(self.credentials, email='other@example.com'))
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(wrong.json(), unknown.json())
        for _ in range(3):
            self.assertEqual(self.client.post('/api/auth/session', json=self.credentials).status_code, 401)
        self.assertEqual(self.client.post('/api/auth/session', json=self.credentials).status_code, 429)
