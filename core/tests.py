from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from planner.models import StudentProfile


class HomePageTests(TestCase):
    def test_landing_page_for_guests(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sınavına giden en kısa rota.")
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
