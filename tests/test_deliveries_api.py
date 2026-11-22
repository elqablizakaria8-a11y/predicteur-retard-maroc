import os
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import insert, select

from api.database import accounts, auth_database
from api.deliveries import deliveries, delivery_router


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ, {'WASEL_AUTH_DB': str(Path(temp.name) / 'test.sqlite3'),
                                     'WASEL_PUBLIC_URL': 'https://example.test',
                                     'RESEND_API_KEY': '', 'SMTP_HOST': ''})
        env.start()
        self.addCleanup(env.stop)
        self.now = 1800000000
        self.allowed = True
        self.service = Mock()
        self.service.predict_trip.return_value = {
            'route': {'departure': {'label':'Casablanca'},
                      'arrival': {'label':'Rabat', 'lat':34.02, 'lon':-6.85}},
            'estimated_arrival_time':'2027-01-15T12:00:00+00:00', 'duree_estimee_min':10}
        self.engine = auth_database()
        with self.engine.begin() as conn:
            conn.execute(insert(accounts).values(id=1,email='client@example.test',password_hash='fixture'))
        app = FastAPI()
        app.include_router(delivery_router(lambda _: self.allowed, lambda: self.service, lambda: self.now))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.form = dict(departure='Casablanca', arrival='Rabat', departure_time='2027-01-15T11:00',
                         urban=False, phone='+212612345678')

    def create(self):
        response = self.client.post('/api/deliveries', json=self.form)
        self.assertEqual(response.status_code,201,response.text if response.status_code != 201 else '')
        links = response.json()['links']
        return tuple(link.rsplit('/',1)[1] for link in (links['driver'],links['viewer']))

    def call(self, method, path, token, **kwargs):
        return self.client.request(method,'/api/deliveries/'+path,
                                   headers={'Authorization':'Bearer '+token},**kwargs)

    def test_roles_lifecycle_eta_expiry(self):
        driver, viewer = self.create()
        self.assertNotEqual(driver, viewer)
        with self.engine.connect() as conn:
            row = conn.execute(select(deliveries)).mappings().one()
            self.assertNotIn(driver,str(row))
            self.assertNotIn(viewer,str(row))
        self.allowed = False
        self.assertEqual(self.client.get('/api/deliveries').status_code,401)
        self.assertEqual(self.call('GET','viewer',driver).status_code,404)
        self.assertEqual(self.call('POST','driver/start',viewer).status_code,404)
        self.assertEqual(self.call('POST','driver/connect',driver).status_code,200)
        self.call('POST','driver/start',driver)
        point = dict(latitude=34.02,longitude=-6.85,accuracy=10,captured=self.now)
        self.assertEqual(self.call('POST','position',driver,json=dict(point,latitude=91)).status_code,422)
        self.assertEqual(self.call('POST','position',driver,json=dict(point,captured=self.now-61)).status_code,422)
        self.assertEqual(self.call('POST','position',driver,json=point).status_code,204)
        self.assertEqual(self.call('POST','position',driver,json=point).status_code,429)
        state = self.call('GET','viewer',viewer).json()
        self.assertEqual(state['eta'],self.now+600)
        self.assertIn('near',state['events'])
        self.assertNotIn('phone',state)
        self.now+=31
        self.assertTrue(self.call('GET','viewer',viewer).json()['stale'])
        self.call('POST','driver/pause',driver)
        self.assertIsNone(self.call('GET','viewer',viewer).json()['position'])
        self.assertEqual(self.call('POST','position',driver,json=point).status_code,409)
        self.call('POST','driver/deliver',driver)
        self.assertEqual(self.call('POST','position',driver,json=point).status_code,410)
        self.now+=7200
        self.assertEqual(self.call('GET','viewer',viewer).status_code,404)

    def test_unused_expiry_and_multiple_deliveries(self):
        _, viewer = self.create()
        self.create()
        self.now+=86400
        self.assertEqual(self.call('GET','viewer',viewer).status_code,404)
        rows=self.client.get('/api/deliveries').json()['deliveries']
        self.assertEqual(len(rows),2)
        self.assertTrue(all(r['expired'] for r in rows))

    @patch('api.deliveries.send_link')
    @patch('api.deliveries.mail_enabled',return_value=True)
    def test_role_specific_invitations(self, enabled, send):
        self.form.update(driver_email='driver@example.test',recipient_email='recipient@example.test')
        driver, viewer = self.create()
        sent = {args[0]:args[1] for args, kw in send.call_args_list}
        self.assertTrue(sent['driver@example.test'].endswith(driver))
        self.assertTrue(sent['recipient@example.test'].endswith(viewer))
        self.assertTrue(sent['client@example.test'].endswith(viewer))

    def test_history_limit_and_recalculation_cadence(self):
        driver, viewer = self.create()
        self.call('POST','driver/start',driver)
        for index in range(14):
            point = dict(latitude=33.5 + index / 1000, longitude=-7.5, accuracy=10, captured=self.now)
            self.assertEqual(self.call('POST','position',driver,json=point).status_code,204)
            self.now += 5
        with self.engine.connect() as conn:
            state = conn.execute(select(deliveries.c.data)).scalar_one()
        self.assertEqual(len(state['history']),12)
        self.assertEqual(self.service.predict_trip.call_count,3)
        self.assertNotIn('history',self.call('GET','viewer',viewer).json())
