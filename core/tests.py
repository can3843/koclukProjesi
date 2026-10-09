from django.test import TestCase


class HomePageTests(TestCase):
    def test_home_page_renders(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sınavına giden en kısa rota.")

    def test_admin_login_page_available_at_yonetim(self):
        response = self.client.get("/yonetim/login/")
        self.assertEqual(response.status_code, 200)
