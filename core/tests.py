from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from planner.models import StudentProfile


class HomePageTests(TestCase):
    def test_landing_page_for_guests(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        # the second half of the slogan is highlighted in its own element, so check the halves
        self.assertContains(response, "Sınavına giden <em>en kısa rota.</em>", html=False)
        self.assertContains(response, "Hemen başla")
        self.assertContains(response, 'href="/kayit/"')

    def test_authenticated_user_is_redirected_to_today(self):
        user = get_user_model().objects.create_user("elif@example.com", "gizli-parola-123", first_name="Elif")
        StudentProfile.objects.create(user=user, onboarding_step=5, onboarding_completed_at=timezone.now())
        self.client.force_login(user)
        self.assertRedirects(self.client.get("/"), "/bugun/", fetch_redirect_response=False)

    def test_admin_login_page_available_at_yonetim(self):
        response = self.client.get("/yonetim/login/")
        self.assertEqual(response.status_code, 200)


class TodayPageTests(TestCase):
    def test_today_page_greets_user_and_shows_tabbar(self):
        user = get_user_model().objects.create_user("elif@example.com", "gizli-parola-123", first_name="Elif")
        StudentProfile.objects.create(user=user, onboarding_step=5, onboarding_completed_at=timezone.now())
        self.client.force_login(user)
        response = self.client.get("/bugun/")
        self.assertContains(response, "Elif")
        self.assertContains(response, "Bugün")
        self.assertContains(response, "İlerleme")
        # logout is a POST form with CSRF protection
        self.assertContains(response, 'action="/cikis/"')


class ErrorPageTests(TestCase):
    def test_unknown_page_uses_the_branded_404(self):
        response = self.client.get("/bu-sayfa-yok/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Bu rota haritada yok", status_code=404)
        self.assertContains(response, "Ana sayfaya dön", status_code=404)

    def test_server_error_page_is_standalone_and_in_turkish(self):
        from django.test import RequestFactory
        from django.views.defaults import server_error

        response = server_error(RequestFactory().get("/"))
        self.assertEqual(response.status_code, 500)
        html = response.content.decode()
        self.assertIn("Bir şeyler ters gitti", html)
        self.assertNotIn("{% ", html)
        self.assertNotIn("/static/", html)  # no dependency on static files, database or sessions


class DesignSystemTests(TestCase):
    def test_pages_ship_the_icon_sprite_manifest_and_social_tags(self):
        html = self.client.get("/").content.decode()
        for needle in ('id="i-flame"', "site.webmanifest", 'property="og:image"', "theme-color", "css/tokens.css", "Figtree"):
            self.assertIn(needle, html)

    def test_no_emoji_is_used_as_an_interface_icon_on_the_landing_page(self):
        import re

        html = self.client.get("/").content.decode()
        body = html[html.index("<main"):]
        self.assertIsNone(re.search("[\U0001F300-\U0001FAFF☀-➿]", re.sub(r"<[^>]+>", "", body)))
