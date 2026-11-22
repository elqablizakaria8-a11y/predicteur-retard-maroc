import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.tracking import LIFETIME_SECONDS, STALE_SECONDS, tracking_router


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.now = 1700000000
        app = FastAPI()
        app.include_router(tracking_router(clock=lambda: self.now, signed_in=lambda request: self.signed_in))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.signed_in = True

    def call(self, method, path, token=None, **kwargs):
        headers = {'Authorization': f'Bearer {token}'} if token else {}
        return self.client.request(method, '/api/tracking' + path, headers=headers, **kwargs)

    def create(self):
        response = self.call('POST', '/session')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        return response.json()

    def test_updates_roles_staleness_stop_and_replacement(self):
        session = self.create()
        driver = session['driver_token']
        viewer = session['viewer_token']
        point = {'latitude': 33.57, 'longitude': -7.59, 'accuracy': 12}
        self.assertEqual(self.call('POST', '/session').status_code, 409)
        self.assertEqual(self.call('GET', '/position', driver).status_code, 404)
        self.assertEqual(self.call('PUT', '/position', viewer, json=point).status_code, 404)
        self.assertEqual(self.call('POST', '/stop', viewer).status_code, 404)
        self.assertEqual(self.call('GET', '/position', viewer).json()['status'], 'waiting')
        self.assertEqual(self.call('PUT', '/position', driver, json=point).status_code, 204)
        self.now += 3
        moved = dict(point, latitude=33.58)
        self.assertEqual(self.call('PUT', '/position', driver, json=moved).status_code, 204)
        response = self.call('GET', '/position', viewer)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(response.json()['position'], moved)
        self.assertEqual(response.json()['status'], 'live')
        self.assertIsNotNone(response.json()['updated_at'])
        self.now += STALE_SECONDS
        self.assertEqual(self.call('GET', '/position', viewer).json()['status'], 'stale')
        self.assertEqual(self.call('POST', '/stop', driver).status_code, 204)
        self.assertEqual(self.call('GET', '/position', viewer).json(),
                         {'status': 'stopped', 'position': None, 'updated_at': None})
        self.assertEqual(self.call('PUT', '/position', driver, json=point).status_code, 410)
        self.assertNotEqual(self.create()['viewer_token'], viewer)
        self.assertEqual(self.call('GET', '/position', viewer).status_code, 404)

    def test_expiry_and_validation(self):
        self.signed_in = False
        self.assertEqual(self.call('POST', '/session').status_code, 401)
        self.signed_in = True
        session = self.create()
        point = {'latitude': True, 'longitude': -7.59, 'accuracy': 12}
        self.assertEqual(self.call('PUT', '/position', session['driver_token'], json=point).status_code, 422)
        self.now += LIFETIME_SECONDS
        self.assertEqual(self.call('GET', '/position', session['viewer_token']).status_code, 404)
        self.create()

    def test_signout_blocks_creation_but_keeps_delivery_links(self):
        delivery = self.create()
        self.assertEqual(self.call('GET', '/session').json(), {'delivery': delivery})
        self.signed_in = False
        self.assertEqual(self.call('POST', '/session').status_code, 401)
        self.assertEqual(self.call('GET', '/session').status_code, 401)
        self.assertEqual(self.call('GET', '/position', delivery['viewer_token']).status_code, 200)
