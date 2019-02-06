from django.test import TestCase


class BillingTest(TestCase):
    def setUp(self):
        self.check_value = 1

    def test_check_value(self):
        self.assertEqual(self.check_value, 1)
