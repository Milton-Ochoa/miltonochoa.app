"""
Tests — app: usuarios (endurecimiento de seguridad)
Rate limiting (decorador, login, admin), telemetría de errores del navegador
(incluido el blindaje anti-abuso) y el mínimo de la clave asignada por el staff.
"""
import json
from django.test import TestCase, Client, RequestFactory
from django.contrib.auth.models import User
from django.core.cache import cache
from programacion.configuracion.models import Colegio
from usuarios.models import ErrorCliente
from usuarios.ratelimit import rate_limit


# ── Rate Limiting ─────────────────────────────────────────────

class RateLimitTest(TestCase):

    def tearDown(self):
        cache.clear()

    def test_permite_llamadas_dentro_del_limite(self):
        factory = RequestFactory()

        @rate_limit(max_calls=3, periodo=60)
        def vista_test(request):
            from django.http import JsonResponse
            return JsonResponse({'ok': True})

        for _ in range(3):
            request = factory.get('/')
            request.META['REMOTE_ADDR'] = '127.0.0.1'
            r = vista_test(request)
            self.assertEqual(r.status_code, 200)

    def test_bloquea_cuando_supera_limite(self):
        factory = RequestFactory()

        @rate_limit(max_calls=2, periodo=60)
        def vista_test(request):
            from django.http import JsonResponse
            return JsonResponse({'ok': True})

        for _ in range(2):
            request = factory.get('/')
            request.META['REMOTE_ADDR'] = '10.0.0.1'
            vista_test(request)

        request = factory.get('/')
        request.META['REMOTE_ADDR'] = '10.0.0.1'
        r = vista_test(request)
        self.assertEqual(r.status_code, 429)

    def test_carrera_ttl_entre_add_e_incr_no_revienta(self):
        """Con Redis la clave puede expirar entre cache.add y cache.incr (dos
        round-trips de red): incr lanza ValueError. El decorador debe reponer el
        contador y atender la request, no propagar un 500 (visto en prod 2026-07-08)."""
        from unittest import mock
        from django.http import JsonResponse
        factory = RequestFactory()

        @rate_limit(max_calls=2, periodo=60)
        def vista_test(request):
            return JsonResponse({'ok': True})

        incr_real = cache.incr
        estado = {'primera': True}

        def incr_con_expiracion(key, *args, **kwargs):
            if estado['primera']:
                estado['primera'] = False
                cache.delete(key)  # simula el TTL venciendo justo tras el add
                raise ValueError(f"Key '{key}' not found")
            return incr_real(key, *args, **kwargs)

        request = factory.get('/')
        request.META['REMOTE_ADDR'] = '10.7.7.7'
        with mock.patch.object(cache, 'incr', side_effect=incr_con_expiracion):
            r = vista_test(request)
        self.assertEqual(r.status_code, 200)

        # El contador quedó bien repuesto: el límite sigue aplicando después.
        request = factory.get('/')
        request.META['REMOTE_ADDR'] = '10.7.7.7'
        self.assertEqual(vista_test(request).status_code, 200)
        request = factory.get('/')
        request.META['REMOTE_ADDR'] = '10.7.7.7'
        self.assertEqual(vista_test(request).status_code, 429)

    def test_proxy_cgnat_railway_usa_xff(self):
        """El proxy de Railway llega desde 100.64.0.0/10 (CGNAT, no 'privado' para
        ipaddress): debe tomarse el XFF para que cada cliente tenga su propio contador
        y no compartan todos el límite bajo la IP del proxy."""
        factory = RequestFactory()

        @rate_limit(max_calls=2, periodo=60)
        def vista_test(request):
            from django.http import JsonResponse
            return JsonResponse({'ok': True})

        def peticion(ip_cliente):
            request = factory.get('/')
            request.META['REMOTE_ADDR'] = '100.64.0.4'
            request.META['HTTP_X_FORWARDED_FOR'] = ip_cliente
            return vista_test(request)

        # El cliente A agota su límite…
        for _ in range(2):
            self.assertEqual(peticion('203.0.113.10').status_code, 200)
        self.assertEqual(peticion('203.0.113.10').status_code, 429)

        # …pero el cliente B no se ve afectado (contadores independientes).
        self.assertEqual(peticion('203.0.113.20').status_code, 200)

    def test_cdn_railway_toma_primer_xff(self):
        """Vía la capa CDN de Railway el XFF llega como 'cliente, pop_cdn': debe usarse
        el PRIMER valor (el cliente real); con el último todos los usuarios detrás del
        mismo POP regional compartirían contador."""
        factory = RequestFactory()

        @rate_limit(max_calls=2, periodo=60)
        def vista_test(request):
            from django.http import JsonResponse
            return JsonResponse({'ok': True})

        def peticion(ip_cliente):
            request = factory.get('/')
            request.META['REMOTE_ADDR'] = '100.64.0.4'
            # mismo POP del CDN al final para ambos clientes
            request.META['HTTP_X_FORWARDED_FOR'] = f'{ip_cliente}, 84.17.44.225'
            return vista_test(request)

        for _ in range(2):
            self.assertEqual(peticion('203.0.113.10').status_code, 200)
        self.assertEqual(peticion('203.0.113.10').status_code, 429)
        # Cliente distinto detrás del MISMO POP: contador propio.
        self.assertEqual(peticion('203.0.113.20').status_code, 200)

    def test_xff_invalido_cae_a_remote_addr(self):
        """Un primer valor de XFF que no parsea como IP no debe romper la vista ni
        usarse como llave: se cae a REMOTE_ADDR."""
        factory = RequestFactory()

        @rate_limit(max_calls=2, periodo=60)
        def vista_test(request):
            from django.http import JsonResponse
            return JsonResponse({'ok': True})

        request = factory.get('/')
        request.META['REMOTE_ADDR'] = '100.64.0.4'
        request.META['HTTP_X_FORWARDED_FOR'] = 'no-soy-una-ip, 84.17.44.225'
        self.assertEqual(vista_test(request).status_code, 200)

    def test_cloudflare_usa_cf_connecting_ip(self):
        """miltonochoa.app está proxied por Cloudflare: el primer XFF es el nodo CF
        (Railway lo pone), y la IP real del usuario viaja en CF-Connecting-IP. Dos
        usuarios detrás del MISMO nodo CF deben tener contadores independientes."""
        factory = RequestFactory()

        @rate_limit(max_calls=2, periodo=60)
        def vista_test(request):
            from django.http import JsonResponse
            return JsonResponse({'ok': True})

        def peticion(ip_usuario):
            request = factory.get('/')
            request.META['REMOTE_ADDR'] = '100.64.0.4'
            # 172.68.12.53 ∈ 172.64.0.0/13 (rango publicado de Cloudflare)
            request.META['HTTP_X_FORWARDED_FOR'] = '172.68.12.53, 84.17.44.225'
            request.META['HTTP_CF_CONNECTING_IP'] = ip_usuario
            return vista_test(request)

        for _ in range(2):
            self.assertEqual(peticion('203.0.113.10').status_code, 200)
        self.assertEqual(peticion('203.0.113.10').status_code, 429)
        self.assertEqual(peticion('203.0.113.20').status_code, 200)

    def test_cf_connecting_ip_falso_sin_cloudflare_se_ignora(self):
        """Quien llega DIRECTO a Railway (primer XFF = su IP real, no un nodo CF) no
        puede evadir el límite rotando un CF-Connecting-IP inventado."""
        factory = RequestFactory()

        @rate_limit(max_calls=2, periodo=60)
        def vista_test(request):
            from django.http import JsonResponse
            return JsonResponse({'ok': True})

        def peticion(cf_falso):
            request = factory.get('/')
            request.META['REMOTE_ADDR'] = '100.64.0.4'
            request.META['HTTP_X_FORWARDED_FOR'] = '203.0.113.66, 84.17.44.225'
            request.META['HTTP_CF_CONNECTING_IP'] = cf_falso
            return vista_test(request)

        # Rota el header falso en cada request: igual lo cuenta su IP real → 429.
        self.assertEqual(peticion('9.9.9.1').status_code, 200)
        self.assertEqual(peticion('9.9.9.2').status_code, 200)
        self.assertEqual(peticion('9.9.9.3').status_code, 429)


# ── Telemetría: capturador de errores del navegador ───────────
class TelemetriaErrorClienteTest(TestCase):

    def setUp(self):
        # Host de área: el endpoint debe ser accesible aunque el middleware de acceso
        # restrinja a colegio/profesor (va en RUTAS_PUBLICAS).
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.url = '/usuarios/telemetria/error/'

    def test_post_valido_crea_registro(self):
        payload = {
            'tipo': 'fetch',
            'mensaje': 'Fallo de red en POST /colegios/ajax/guardar/',
            'stack': 'TypeError: failed to fetch',
            'url': 'https://programacion.testserver/colegios/',
            'breadcrumbs': [{'t': '2026-06-04T17:00:00Z', 'tipo': 'click', 'detalle': 'button «Guardar»'}],
        }
        r = self.client.post(self.url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ErrorCliente.objects.count(), 1)
        e = ErrorCliente.objects.first()
        self.assertEqual(e.tipo, 'fetch')
        self.assertEqual(len(e.breadcrumbs), 1)

    def test_usuario_anonimo_se_registra_sin_user(self):
        # Sin sesión: el reporte igual se guarda (usuario=None), no se pierde el error.
        r = self.client.post(self.url, data=json.dumps({'tipo': 'error', 'mensaje': 'x'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(ErrorCliente.objects.first().usuario)

    def test_json_invalido_no_revienta(self):
        # Tolerante: cuerpo basura → 400 controlado, nunca un 500.
        r = self.client.post(self.url, data='no-es-json{', content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(ErrorCliente.objects.count(), 0)

    def test_get_no_permitido(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)


# ── Endurecimiento de seguridad (telemetría, logins, claves) ──

class TelemetriaAbuseTest(TestCase):
    """El endpoint es público y anónimo (RUTAS_PUBLICAS): sin rate limit ni topes de
    tamaño, cualquiera podría llenar la BD con megabytes por request."""

    def setUp(self):
        cache.clear()
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.url = '/usuarios/telemetria/error/'

    def tearDown(self):
        cache.clear()

    def _post(self, payload):
        return self.client.post(self.url, data=json.dumps(payload),
                                content_type='application/json')

    def test_rate_limit_corta_la_rafaga(self):
        for _ in range(20):
            self.assertEqual(self._post({'tipo': 'error', 'mensaje': 'x'}).status_code, 200)
        r = self._post({'tipo': 'error', 'mensaje': 'x'})
        self.assertEqual(r.status_code, 429)
        self.assertEqual(ErrorCliente.objects.count(), 20)  # el 21º no se guardó

    def test_extra_gigante_se_descarta_pero_el_error_se_guarda(self):
        r = self._post({'tipo': 'error', 'mensaje': 'real',
                        'extra': {'relleno': 'A' * 50000}})
        self.assertEqual(r.status_code, 200)
        e = ErrorCliente.objects.first()
        self.assertEqual(e.mensaje, 'real')   # el reporte no se pierde
        self.assertEqual(e.extra, {})         # el campo inflado sí

    def test_breadcrumbs_gigantes_se_descartan(self):
        crumbs = [{'t': 'x', 'tipo': 'click', 'detalle': 'B' * 5000} for _ in range(10)]
        r = self._post({'tipo': 'error', 'mensaje': 'real', 'breadcrumbs': crumbs})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ErrorCliente.objects.first().breadcrumbs, [])

    def test_extra_normal_sigue_pasando(self):
        r = self._post({'tipo': 'fetch', 'mensaje': 'x', 'extra': {'status': 502, 'ms': 1200}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ErrorCliente.objects.first().extra, {'status': 502, 'ms': 1200})


class LoginRateLimitTest(TestCase):
    """vista_login responde 429 en HTML (es un form de navegador, no AJAX) y el login
    de /admin/ (form propio de Django) también queda rate-limited."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_login_429_es_html(self):
        for _ in range(10):
            self.client.post('/usuarios/login/', {'username': 'nadie', 'password': 'mala'})
        r = self.client.post('/usuarios/login/', {'username': 'nadie', 'password': 'mala'})
        self.assertEqual(r.status_code, 429)
        self.assertIn('text/html', r['Content-Type'])

    def test_admin_login_tiene_rate_limit(self):
        for _ in range(10):
            self.client.get('/admin/login/')
        r = self.client.get('/admin/login/')
        self.assertEqual(r.status_code, 429)


class PasswordTemporalMinimaTest(TestCase):
    """El staff asigna la clave a mano, pero el login es público en internet:
    se exige un mínimo de 8 caracteres (sin el resto de validadores de Django)."""

    def setUp(self):
        cache.clear()
        User.objects.create_superuser(username='admin', password='adminpass')
        self.client.login(username='admin', password='adminpass')
        self.colegio = Colegio.objects.create(nombre='Colegio Min', ciudad='Bogotá')

    def test_crear_usuario_con_clave_corta_falla(self):
        r = self.client.post('/usuarios/ajax/crear/', {
            'tipo': 'colegio', 'username': 'col_corto',
            'password': 'corta12',  # 7 caracteres
            'colegio_id': self.colegio.id,
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn('8 caracteres', r.json()['error'])
        self.assertFalse(User.objects.filter(username='col_corto').exists())

    def test_crear_usuario_con_clave_de_8_pasa(self):
        r = self.client.post('/usuarios/ajax/crear/', {
            'tipo': 'colegio', 'username': 'col_ok',
            'password': 'clave123',  # 8 justos
            'colegio_id': self.colegio.id,
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(User.objects.filter(username='col_ok').exists())

