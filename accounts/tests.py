from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase


class UserModelTests(TestCase):
    def test_create_user_lowercases_email_and_uses_email_login(self):
        User = get_user_model()
        user = User.objects.create_user("Elif@Example.COM", "gizli-parola-123", first_name="Elif")
        self.assertEqual(user.email, "elif@example.com")
        self.assertTrue(self.client.login(username="elif@example.com", password="gizli-parola-123"))

    def test_email_is_case_insensitive_unique(self):
        User = get_user_model()
        User.objects.create_user("elif@example.com", "gizli-parola-123", first_name="Elif")
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create(email="ELIF@example.com", first_name="Baska")
