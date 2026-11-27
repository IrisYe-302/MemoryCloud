import tempfile
import unittest
from delivery import Delivery


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name + '/jobs.db'
        self.d = Delivery(self.path)

    def tearDown(self):
        self.d.db.close()
        self.tmp.cleanup()

    def test_offline_consent_and_restart(self):
        a = self.d.submit('a', 'p', 'photo1', False, 10, 20)
        b = self.d.submit('b', 'p', 'photo2', True, 10, 100)
        self.assertEqual(self.d.dispatch('p', False, 11), [])
        self.assertEqual(self.d.state(a), 'skipped')
        self.d.db.close()
        self.d = Delivery(self.path)
        self.assertEqual([j['id'] for j in self.d.dispatch('p', True, 30)], [b])

    def test_schedule_and_expiry(self):
        a = self.d.submit('a', 'p', 'photo', False, 10, 20)
        self.assertEqual(self.d.dispatch('p', True, 9), [])
        self.assertEqual(self.d.dispatch('p', True, 20), [])
        self.assertEqual(self.d.state(a), 'expired')

    def test_duplicate_and_idempotency(self):
        a = self.d.submit('a', 'p', 'photo', True, 0, 100)
        self.assertEqual(a, self.d.submit('a', 'p', 'photo', True, 0, 100))
        with self.assertRaises(ValueError):
            self.d.submit('a', 'other', 'photo', True, 0, 100)
        with self.assertRaises(ValueError):
            self.d.submit('b', 'p', 'photo', True, 0, 100)
        self.d.submit('b', 'other', 'photo', True, 0, 100)
        self.d.submit('c', 'p', 'photo', True, 0, 100, reprint=True)

    def test_uncertain_never_retried_and_ack_scoped(self):
        a = self.d.submit('a', 'p', 'photo', True, 0, 100)
        self.d.dispatch('p', True, 1)
        self.d.mark_uncertain('p')
        self.assertEqual(self.d.dispatch('p', True, 2), [])
        self.d.acknowledge(a, 'wrong')
        self.assertEqual(self.d.state(a), 'uncertain')
        self.d.acknowledge(a, 'p')
        self.assertEqual(self.d.state(a), 'printed')
