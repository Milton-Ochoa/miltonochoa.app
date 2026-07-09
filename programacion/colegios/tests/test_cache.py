"""
Tests — app: colegios (caché del dashboard)
Invalidación de la matriz/stats cacheadas en todas las rutas que mutan datos.
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from datetime import date, time

from programacion.configuracion.models import Colegio, ColegioAnio, Profesor, Materia
from programacion.colegios.models import Bloque, Clase, Grado


# ── Invalidación de caché del dashboard (matriz/stats) ────────────

class InvalidacionCacheDashboardTest(TestCase):
    """Regresión: matriz/stats cacheadas del dashboard deben invalidarse en TODAS
    las rutas que mutan los datos que las alimentan: la ruta no-JS de
    dashboard_colegios, los POST de configurar_colegio y el recálculo de
    secuencias (bulk_update no dispara signals)."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.admin = User.objects.create_superuser('admin_cache', password='pass')
        self.client.login(username='admin_cache', password='pass')
        col = Colegio.objects.create(
            nombre='Col Cache', departamento='Santander', ciudad='BGA')
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)
        self.grado = Grado.objects.create(nombre='11-1')
        self.bloque = Bloque.objects.create(
            colegio=self.colegio, grado=self.grado,
            hora_inicio=time(8, 0), hora_fin=time(10, 0))
        self.materia = Materia.objects.create(nombre='Física', color='#3498db')
        self.profesor = Profesor.objects.create(nombre='Luis', apellido='Ruiz')

    def _sembrar_cache(self):
        from django.core.cache import cache
        from programacion.colegios.views import _matriz_cache_key, _stats_cache_key
        self._ck_matriz = _matriz_cache_key(self.colegio.id, self.colegio.anio)
        self._ck_stats = _stats_cache_key(self.colegio.id, self.colegio.anio)
        cache.set(self._ck_matriz, {'sentinel': True}, 300)
        cache.set(self._ck_stats, {'sentinel': True}, 300)

    def _cache_invalidada(self):
        from django.core.cache import cache
        return cache.get(self._ck_matriz) is None and cache.get(self._ck_stats) is None

    def test_guardar_clase_ruta_no_js_invalida(self):
        # POST directo a dashboard_colegios (fallback sin JS), no al endpoint AJAX.
        self._sembrar_cache()
        r = self.client.post(f'/colegios/?id_col={self.colegio.id}', {
            'guardar_clase': '1',
            'bloque_id': str(self.bloque.id),
            'fecha_clase': '2026-05-15',
            'materia': 'Física',
            'profesor': str(self.profesor.id),
            'unidad': '1',
            'eliminar_clase': '0',
            'material_especial': '0',
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Clase.objects.filter(colegio=self.colegio).exists())
        self.assertTrue(self._cache_invalidada())

    def test_configurar_colegio_post_invalida(self):
        self._sembrar_cache()
        r = self.client.post(f'/colegios/configurar-colegio/{self.colegio.id}/', {
            'accion': 'set_valor_hora', 'valor_hora': '50000'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(self._cache_invalidada())

    def test_recalcular_secuencia_invalida(self):
        from django.core.cache import cache
        from core.views import _vg_cache_key
        Clase.objects.create(
            colegio=self.colegio, bloque=self.bloque, fecha=date(2026, 5, 15),
            materia=self.materia, profesor=self.profesor, unidad='3',
        )
        self._sembrar_cache()
        # bulk_update no dispara signals: también debe invalidar vista_general.
        ck_vg = _vg_cache_key(2026, 5)
        cache.set(ck_vg, {'sentinel': True}, 300)
        r = self.client.post(f'/colegios/ajax/recalcular-secuencia/{self.colegio.id}/', {
            'grado': '11-1', 'materia': 'Física',
            'fecha_desde': '2026-05-01', 'unidad_inicio': '1',
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Clase.objects.get(colegio=self.colegio).unidad, '1')
        self.assertTrue(self._cache_invalidada())
        self.assertIsNone(cache.get(ck_vg))

