from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

User = get_user_model()

PASSWORD = "gizli-parola-123"


def make_user(email="elif@example.com", name="Elif"):
    return User.objects.create_user(email, PASSWORD, first_name=name)


class UserModelTests(TestCase):
    def test_create_user_lowercases_email_and_uses_email_login(self):
        user = User.objects.create_user("Elif@Example.COM", PASSWORD, first_name="Elif")
        self.assertEqual(user.email, "elif@example.com")
        self.assertTrue(self.client.login(username="elif@example.com", password=PASSWORD))

    def test_email_is_case_insensitive_unique(self):
        make_user()
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.bulk_create([User(email="ELIF@example.com", first_name="Baska")])

    def test_mixed_case_email_saved_via_save_is_lowercased(self):
        user = User(email="Mixed@Example.com", first_name="Mert")
        user.set_password(PASSWORD)
        user.save()
        self.assertEqual(User.objects.get(pk=user.pk).email, "mixed@example.com")


class RegisterTests(TestCase):
    def post(self, **overrides):
        data = {
            "first_name": "Elif",
            "email": "elif@example.com",
            "password1": PASSWORD,
            "password2": PASSWORD,
        }
        data.update(overrides)
        return self.client.post("/kayit/", data)

    def test_register_page_renders(self):
        response = self.client.get("/kayit/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hesap oluştur")

    def test_register_logs_in_and_redirects_to_today(self):
        response = self.post()
        self.assertRedirects(response, "/bugun/", fetch_redirect_response=False)
        # a new student has not finished onboarding yet, so the app sends them to step 1
        self.assertRedirects(self.client.get("/bugun/"), "/baslangic/1/", fetch_redirect_response=False)
        user = User.objects.get(email="elif@example.com")
        self.assertEqual(user.first_name, "Elif")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_register_normalizes_email_to_lowercase(self):
        self.post(email="  Elif@Example.COM ")
        self.assertTrue(User.objects.filter(email="elif@example.com").exists())

    def test_duplicate_email_is_rejected_case_insensitively(self):
        make_user("elif@example.com")
        response = self.post(email="ELIF@example.com", first_name="Baska")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "zaten bir hesap var")
        self.assertEqual(User.objects.count(), 1)

    def test_password_mismatch_is_rejected(self):
        response = self.post(password2="baska-parola-456")
        self.assertContains(response, "Parolalar eşleşmiyor.")
        self.assertEqual(User.objects.count(), 0)

    def test_weak_password_is_rejected_with_turkish_message(self):
        response = self.post(password1="123", password2="123")
        self.assertEqual(User.objects.count(), 0)
        self.assertContains(response, "En az 8 karakter")

    def test_name_length_is_validated(self):
        self.assertContains(self.post(first_name="E"), "2 ile 30 karakter")
        self.assertContains(self.post(first_name="E" * 31), "30 karakter")
        self.assertEqual(User.objects.count(), 0)

    def test_authenticated_user_is_redirected_away_from_register(self):
        self.client.force_login(make_user())
        self.assertRedirects(self.client.get("/kayit/"), "/bugun/", fetch_redirect_response=False)


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_login_page_renders(self):
        response = self.client.get("/giris/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Giriş yap")

    def test_login_with_email_case_insensitive(self):
        response = self.client.post("/giris/", {"username": "ELIF@Example.com", "password": PASSWORD})
        self.assertRedirects(response, "/bugun/", fetch_redirect_response=False)
        self.assertIn("_auth_user_id", self.client.session)

    def test_wrong_password_shows_error(self):
        response = self.client.post("/giris/", {"username": "elif@example.com", "password": "yanlis-parola"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "E-posta veya parola hatalı.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_next_redirect_is_followed(self):
        response = self.client.post(
            "/giris/", {"username": "elif@example.com", "password": PASSWORD, "next": "/yonetim/"}
        )
        self.assertRedirects(response, "/yonetim/", fetch_redirect_response=False)

    def test_external_next_is_ignored(self):
        response = self.client.post(
            "/giris/", {"username": "elif@example.com", "password": PASSWORD, "next": "https://evil.example/"}
        )
        self.assertRedirects(response, "/bugun/", fetch_redirect_response=False)

    def test_protected_page_redirects_to_login_with_next(self):
        response = self.client.get("/bugun/")
        self.assertRedirects(response, "/giris/?next=/bugun/", fetch_redirect_response=False)

    def test_login_page_keeps_next_in_form(self):
        response = self.client.get("/giris/?next=/bugun/")
        self.assertContains(response, 'name="next" value="/bugun/"')

    def test_authenticated_user_is_redirected_away_from_login(self):
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get("/giris/"), "/bugun/", fetch_redirect_response=False)

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/cikis/").status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)

    def test_logout_post_logs_out_and_redirects_home(self):
        self.client.force_login(self.user)
        response = self.client.post("/cikis/")
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)


class LoginRateLimitTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def fail(self, times, **extra):
        for _ in range(times):
            self.client.post("/giris/", {"username": "elif@example.com", "password": "yanlis-parola"}, **extra)

    def test_ten_failures_block_even_the_right_password(self):
        self.fail(10)
        response = self.client.post("/giris/", {"username": "elif@example.com", "password": PASSWORD})
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "Çok fazla deneme", status_code=429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_nine_failures_do_not_block(self):
        self.fail(9)
        response = self.client.post("/giris/", {"username": "elif@example.com", "password": PASSWORD})
        self.assertRedirects(response, "/bugun/", fetch_redirect_response=False)

    def test_successful_login_resets_the_counter(self):
        self.fail(9)
        self.client.post("/giris/", {"username": "elif@example.com", "password": PASSWORD})
        self.client.post("/cikis/")
        self.fail(9)
        response = self.client.post("/giris/", {"username": "elif@example.com", "password": PASSWORD})
        self.assertEqual(response.status_code, 302)

    def test_limit_is_per_client_address(self):
        self.fail(10, HTTP_X_FORWARDED_FOR="203.0.113.7")
        blocked = self.client.post("/giris/", {"username": "elif@example.com", "password": PASSWORD}, HTTP_X_FORWARDED_FOR="203.0.113.7")
        self.assertEqual(blocked.status_code, 429)
        other = self.client.post("/giris/", {"username": "elif@example.com", "password": PASSWORD}, HTTP_X_FORWARDED_FOR="198.51.100.9")
        self.assertEqual(other.status_code, 302)

    def test_old_failures_expire(self):
        from unittest.mock import patch

        import time as time_module

        self.fail(10)
        later = time_module.time() + 16 * 60
        with patch("accounts.ratelimit.time.time", return_value=later):
            response = self.client.post("/giris/", {"username": "elif@example.com", "password": PASSWORD})
        self.assertEqual(response.status_code, 302)


class RegisterHardeningTests(TestCase):
    def post(self, email="elif@example.com", **extra):
        data = {"first_name": "Elif", "email": email, "password1": PASSWORD, "password2": PASSWORD}
        data.update(extra)
        return self.client.post("/kayit/", data)

    def test_filled_honeypot_creates_no_account(self):
        response = self.post(website="http://spam.example")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kayıt tamamlanamadı")
        self.assertEqual(User.objects.count(), 0)

    def test_empty_honeypot_is_invisible_but_present(self):
        response = self.client.get("/kayit/")
        self.assertContains(response, 'name="website"')
        self.assertContains(response, "hp-field")
        self.assertContains(response, 'tabindex="-1"')

    def test_eleventh_attempt_within_an_hour_is_blocked(self):
        for i in range(10):
            self.client.post("/kayit/", {"first_name": "E", "email": f"x{i}@example.com"})  # invalid, still counted
        response = self.post(email="gercek@example.com")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(User.objects.count(), 0)

    def test_attempts_under_the_limit_work(self):
        for i in range(9):
            self.client.post("/kayit/", {"first_name": "E", "email": f"x{i}@example.com"})
        self.assertEqual(self.post(email="gercek@example.com").status_code, 302)
