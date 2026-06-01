"""
Tests de autenticación y permisos de la API.
Verifica que todos los endpoints requieren auth y que JWT funciona.
"""
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient


class AuthRequiredTest(TestCase):
    """Todos los endpoints deben devolver 401 sin autenticación."""

    ENDPOINTS = [
        '/programacion/api/v1/profesores/',
        '/programacion/api/v1/colegios/',
        '/programacion/api/v1/colegios-anio/',
        '/programacion/api/v1/clases/',
        '/programacion/api/v1/clases-particulares/',
        '/programacion/api/v1/pagos/',
    ]

    def setUp(self):
        self.client = APIClient()

    def test_endpoints_sin_auth_devuelven_401(self):
        for url in self.ENDPOINTS:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 401, f"Esperaba 401 en {url}, got {resp.status_code}")


class JWTAuthTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testapi', password='testpass123!', is_staff=True
        )

    def test_obtain_token_ok(self):
        resp = self.client.post('/programacion/api/v1/auth/token/', {
            'username': 'testapi', 'password': 'testpass123!'
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('access', resp.data)
        self.assertIn('refresh', resp.data)

    def test_obtain_token_credenciales_invalidas(self):
        resp = self.client.post('/programacion/api/v1/auth/token/', {
            'username': 'testapi', 'password': 'wrong'
        }, format='json')
        self.assertEqual(resp.status_code, 401)

    def test_refresh_token_ok(self):
        r1 = self.client.post('/programacion/api/v1/auth/token/', {
            'username': 'testapi', 'password': 'testpass123!'
        }, format='json')
        refresh = r1.data['refresh']
        r2 = self.client.post('/programacion/api/v1/auth/token/refresh/', {'refresh': refresh}, format='json')
        self.assertEqual(r2.status_code, 200)
        self.assertIn('access', r2.data)

    def test_acceso_con_jwt_ok(self):
        r1 = self.client.post('/programacion/api/v1/auth/token/', {
            'username': 'testapi', 'password': 'testpass123!'
        }, format='json')
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r1.data['access']}")
        resp = self.client.get('/programacion/api/v1/profesores/')
        self.assertEqual(resp.status_code, 200)

    def test_acceso_con_token_invalido_401(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer tokeninvalido')
        resp = self.client.get('/programacion/api/v1/profesores/')
        self.assertEqual(resp.status_code, 401)
