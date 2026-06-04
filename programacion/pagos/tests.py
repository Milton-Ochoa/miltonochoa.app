"""
Tests — app: pagos (sub-app propia, extraída de `exportar`).

Cubre el modelo de soporte y la vista de SOLO LECTURA de programación: ver el
detalle de un pago y sus soportes, pero sin poder marcar ni subir (eso es de
financiera).
"""
from datetime import date

from django.test import TestCase, Client
from django.contrib.auth.models import User

from programacion.configuracion.models import Colegio, ColegioAnio, Profesor
from programacion.pagos.models import (
    ExtraPago, LotePagos, PagoRealizado, SoportePagoProfesor,
    _pago_soporte_upload_to,
)


class PagoLifecycleModelTest(TestCase):
    """Lifecycle de la fila base: valor base (con/sin override), desglose de extras,
    `fecha_pago` nullable y la convención de fila histórica (`lote IS NULL`)."""

    def setUp(self):
        colegio = Colegio.objects.create(
            nombre='Colegio Central', departamento='Santander', ciudad='Bucaramanga')
        self.colegio_anio = ColegioAnio.objects.create(colegio=colegio, anio=2025)
        self.profesor = Profesor.objects.create(nombre='Ana', apellido='Pérez')

    def _pago(self, **kw):
        return PagoRealizado.objects.create(
            profesor=self.profesor, colegio=self.colegio_anio,
            fecha=date(2025, 3, 14), horas=2, valor=80000, **kw)

    def test_valor_base_usa_calculado_sin_override(self):
        pago = self._pago()
        self.assertEqual(pago.valor_base, 80000)
        self.assertEqual(pago.total, 80000)

    def test_valor_base_editado_sobrescribe(self):
        pago = self._pago(valor_base_editado=95000)
        self.assertEqual(pago.valor_base, 95000)
        self.assertEqual(pago.total, 95000)

    def test_total_suma_extras_al_valor_base(self):
        pago = self._pago(valor_base_editado=90000)
        ExtraPago.objects.create(pago=pago, concepto='Desplazamiento', valor=15000)
        ExtraPago.objects.create(pago=pago, concepto='Refrigerio', valor=5000, orden=1)
        self.assertEqual(pago.total_extras, 20000)
        self.assertEqual(pago.total, 110000)

    def test_fecha_pago_es_nullable_y_marca_pagada(self):
        pago = self._pago()
        self.assertIsNone(pago.fecha_pago)
        self.assertFalse(pago.pagada)

    def test_fila_historica_sin_lote(self):
        # Convención: lote IS NULL AND fecha_pago IS NOT NULL = histórico pagado.
        from django.utils import timezone
        pago = self._pago(fecha_pago=timezone.now())
        self.assertIsNone(pago.lote)
        self.assertTrue(pago.pagada)


class LotePagosModelTest(TestCase):
    """El lote ancla el estado semanal BORRADOR→ENVIADO; sus filas se acceden por `filas`."""

    def test_estado_por_defecto_y_envio(self):
        lote = LotePagos.objects.create(
            fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 3, 14))
        self.assertEqual(lote.estado, LotePagos.Estado.BORRADOR)
        self.assertFalse(lote.enviado)
        lote.estado = LotePagos.Estado.ENVIADO
        self.assertTrue(lote.enviado)


class PrepararLoteTest(TestCase):
    """Materialización idempotente del borrador semanal desde las clases."""

    def setUp(self):
        from programacion.colegios.models import Bloque, Clase, Grado
        from datetime import time
        self.colegio = Colegio.objects.create(
            nombre='Colegio Central', departamento='Santander', ciudad='Bucaramanga')
        self.ca = ColegioAnio.objects.create(colegio=self.colegio, anio=2025, valor_hora=40000)
        self.prof = Profesor.objects.create(nombre='Ana', apellido='Pérez')
        self.grado = Grado.objects.create(nombre='11-1')
        self.bloque = Bloque.objects.create(
            colegio=self.ca, grado=self.grado, hora_inicio=time(8, 0), hora_fin=time(10, 0))
        # Una clase de 2 h el martes de la semana 10–14 mar 2025.
        self.clase = Clase.objects.create(
            colegio=self.ca, bloque=self.bloque, profesor=self.prof, fecha=date(2025, 3, 11))
        self.inicio, self.fin = date(2025, 3, 10), date(2025, 3, 14)

    def test_preparar_crea_lote_y_filas(self):
        from programacion.pagos.views import preparar_lote_semana
        lote = preparar_lote_semana(self.inicio, self.fin)
        self.assertEqual(lote.estado, LotePagos.Estado.BORRADOR)
        fila = PagoRealizado.objects.get(lote=lote)
        self.assertEqual(fila.horas, 2)
        self.assertEqual(fila.valor, 80000)  # 2 h × 40000

    def test_preparar_es_idempotente_y_respeta_override_y_excluida(self):
        from programacion.pagos.views import preparar_lote_semana
        lote = preparar_lote_semana(self.inicio, self.fin)
        fila = PagoRealizado.objects.get(lote=lote)
        fila.valor_base_editado = 99000
        fila.excluida = True
        fila.save()
        # Re-preparar no debe pisar el override ni resucitar exclusión.
        preparar_lote_semana(self.inicio, self.fin)
        fila.refresh_from_db()
        self.assertEqual(fila.valor_base_editado, 99000)
        self.assertTrue(fila.excluida)
        self.assertEqual(PagoRealizado.objects.filter(lote=lote).count(), 1)

    def test_preparar_elimina_autogenerada_si_se_cancela_la_clase(self):
        from programacion.pagos.views import preparar_lote_semana
        lote = preparar_lote_semana(self.inicio, self.fin)
        self.assertEqual(PagoRealizado.objects.filter(lote=lote).count(), 1)
        self.clase.cancelada = True
        self.clase.save()
        preparar_lote_semana(self.inicio, self.fin)
        self.assertEqual(PagoRealizado.objects.filter(lote=lote).count(), 0)

    def test_lote_enviado_no_se_remateriliza(self):
        from programacion.pagos.views import preparar_lote_semana, enviar_lote
        lote = preparar_lote_semana(self.inicio, self.fin)
        enviar_lote(lote, None)
        # Agregar otra clase y re-preparar: el lote enviado queda intacto.
        from programacion.colegios.models import Clase
        Clase.objects.create(colegio=self.ca, bloque=self.bloque, profesor=self.prof,
                             fecha=date(2025, 3, 12))
        preparar_lote_semana(self.inicio, self.fin)
        self.assertEqual(PagoRealizado.objects.filter(lote=lote).count(), 1)

    def test_financiera_solo_ve_lotes_enviados(self):
        from programacion.pagos.views import (
            preparar_lote_semana, enviar_lote, construir_contexto_pagos)
        get = {'semana': '2025-03-10', 'tab': 'pendiente'}
        lote = preparar_lote_semana(self.inicio, self.fin)
        # BORRADOR → financiera no ve nada.
        ctx = construir_contexto_pagos(get, modo='financiera')
        self.assertEqual(len(ctx['filas_pendientes']), 0)
        # ENVIADO → financiera ve la fila.
        enviar_lote(lote, None)
        ctx = construir_contexto_pagos(get, modo='financiera')
        self.assertEqual(len(ctx['filas_pendientes']), 1)

    def test_desenviar_bloqueado_si_hay_pago(self):
        from django.utils import timezone
        from programacion.pagos.views import preparar_lote_semana, enviar_lote, desenviar_lote
        lote = preparar_lote_semana(self.inicio, self.fin)
        enviar_lote(lote, None)
        fila = PagoRealizado.objects.get(lote=lote)
        fila.fecha_pago = timezone.now()
        fila.save()
        self.assertFalse(desenviar_lote(lote))
        fila.fecha_pago = None
        fila.save()
        self.assertTrue(desenviar_lote(lote))


class SoportePagoProfesorModelTest(TestCase):
    """El comprobante de pago se ata a un `PagoRealizado` y construye una ruta limpia."""

    def setUp(self):
        colegio = Colegio.objects.create(
            nombre='Colegio Central', departamento='Santander', ciudad='Bucaramanga')
        self.colegio_anio = ColegioAnio.objects.create(colegio=colegio, anio=2025)
        self.profesor = Profesor.objects.create(nombre='Ana María', apellido='Pérez Gómez')
        self.pago = PagoRealizado.objects.create(
            profesor=self.profesor, colegio=self.colegio_anio,
            fecha=date(2025, 3, 14), horas=2, valor=80000)

    def test_str_y_relacion(self):
        soporte = SoportePagoProfesor.objects.create(
            pago=self.pago, nombre_original='comprobante.pdf')
        self.assertEqual(list(self.pago.soportes.all()), [soporte])
        self.assertIn('comprobante.pdf', str(soporte))

    def test_upload_to_usa_docente_y_fecha(self):
        soporte = SoportePagoProfesor(pago=self.pago)
        ruta = _pago_soporte_upload_to(soporte, 'Recibo Original.PDF')
        self.assertEqual(ruta, 'pagos/pago-ana-perez-2025-03-14.pdf')


class PagosProgramacionSoloLecturaTest(TestCase):
    """Programación ve el detalle del pago y sus soportes, pero NO puede marcar
    (esa acción se movió a financiera) ni subir comprobantes."""

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        User.objects.create_superuser(username='admin_prog', password='pass123')
        self.client.login(username='admin_prog', password='pass123')

        colegio = Colegio.objects.create(
            nombre='Colegio Central', departamento='Santander', ciudad='Bucaramanga')
        colegio_anio = ColegioAnio.objects.create(colegio=colegio, anio=2025)
        profesor = Profesor.objects.create(nombre='Ana', apellido='Pérez')
        self.pago = PagoRealizado.objects.create(
            profesor=profesor, colegio=colegio_anio,
            fecha=date(2025, 3, 14), horas=2, valor=80000)

    def test_detalle_solo_lectura_accesible(self):
        r = self.client.get(f'/pagos/{self.pago.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Soporte de pago')
        # Programación no muestra formulario de subida (lo gestiona financiera).
        self.assertNotContains(r, 'enctype="multipart/form-data"')

    def test_pagina_pagos_es_solo_lectura(self):
        r = self.client.get('/pagos/')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Marcar como pagado')

    def test_endpoint_marcar_ya_no_existe(self):
        # La ruta de marcar se retiró de programación (404).
        r = self.client.post('/pagos/marcar/', {
            'accion': 'marcar', 'profesor_id': self.pago.profesor_id,
            'colegio_id': self.pago.colegio_id, 'fecha': '2025-03-15',
            'horas': '2', 'valor': '80000',
        })
        self.assertEqual(r.status_code, 404)
