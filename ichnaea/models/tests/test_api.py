from ichnaea.tests.base import DBTestCase


class TestApiKey(DBTestCase):

    def _make_one(self, **kw):
        from ichnaea.models import ApiKey
        return ApiKey(**kw)

    def test_constructor(self):
        key = self._make_one(valid_key='foo')
        self.assertEqual(key.valid_key, 'foo')
        self.assertEqual(key.maxreq, None)

    def test_fields(self):
        key = self._make_one(
            valid_key='foo-bar', maxreq=10, shortname='foo',
            email='Test <test@test.com>', description='A longer text.',
        )
        session = self.db_master_session
        session.add(key)
        session.commit()

        result = session.query(key.__class__).first()
        self.assertEqual(result.valid_key, 'foo-bar')
        self.assertEqual(result.shortname, 'foo')
        self.assertEqual(result.email, 'Test <test@test.com>')
        self.assertEqual(result.description, 'A longer text.')
