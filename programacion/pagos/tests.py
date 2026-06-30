"""
Tests — app: pagos (sub-app propia, extraída de `exportar`).

Cubre el modelo de soporte y la vista de SOLO LECTURA de programación: ver el
detalle de un pago y sus soportes, pero sin poder marcar ni subir (eso es de
financiera).
"""
from datetime import date, timedelta

from django.test import TestCase, Client
from django.contrib.auth.models import User

from programacion.configuracion.models import Colegio, ColegioAnio, Profesor
from programacion.pagos.models import (
    ExtraPago, LotePagos, PagoRealizado, SoportePagoProfesor,
    _pago_soporte_upload_to,
)


def _informe_de(clase, actividades='Clase dictada.'):
    """Informe completado de una clase: requisito para que su fila de pago sea enviable
    (gate por informe en `enviar_lote`/`construir_contexto_pagos`)."""
    from programacion.informes.models import Informe
    return Informe.objects.create(
        profesor=clase.profesor, clase=clase,
        colegio_nombre='Colegio Central', grado='11-1', fecha=clase.fecha,
        materia='Matemáticas', tematica='Unidad 1', material='Libro 1',
        actividades=actividades)


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

    def test_preparar_pendientes_materializa_clases_de_fin_de_semana(self):
        # Regresión: con la semana lunes–viernes, las clases de sábado/domingo caían fuera
        # de la ventana de su propia semana y NUNCA se materializaban → su informe no podía
        # llegar a "por enviar". La semana completa (lunes–domingo) debe incluirlas.
        from programacion.colegios.models import Clase
        from programacion.pagos.views import preparar_pendientes
        hoy = date.today()
        # Sábado más reciente con fecha <= hoy (preparar_pendientes filtra fecha__lte=hoy).
        sabado = hoy - timedelta(days=(hoy.weekday() + 2) % 7)
        if sabado > hoy:
            sabado -= timedelta(days=7)
        clase_finde = Clase.objects.create(
            colegio=self.ca, bloque=self.bloque, profesor=self.prof, fecha=sabado)
        preparar_pendientes()
        fila = PagoRealizado.objects.filter(
            profesor=self.prof, colegio=self.ca, fecha=sabado).first()
        self.assertIsNotNone(fila, 'La clase de fin de semana debe materializar su fila de pago')
        self.assertEqual(fila.lote.estado, LotePagos.Estado.BORRADOR)
        # El lote ancla la semana completa lunes–domingo que contiene el sábado.
        lunes = sabado - timedelta(days=sabado.weekday())
        self.assertEqual(fila.lote.fecha_inicio, lunes)
        self.assertEqual(fila.lote.fecha_fin, lunes + timedelta(days=6))

    def test_lote_enviado_no_se_remateriliza(self):
        from programacion.pagos.views import preparar_lote_semana, enviar_lote
        _informe_de(self.clase)
        lote = preparar_lote_semana(self.inicio, self.fin)
        self.assertTrue(enviar_lote(lote, None))
        # Agregar otra clase y re-preparar: el lote enviado queda intacto (la fila nueva
        # cae en un BORRADOR aparte de la misma semana).
        from programacion.colegios.models import Clase
        nueva = Clase.objects.create(colegio=self.ca, bloque=self.bloque,
                                     profesor=self.prof, fecha=date(2025, 3, 12))
        borrador = preparar_lote_semana(self.inicio, self.fin)
        self.assertNotEqual(borrador.id, lote.id)
        self.assertEqual(borrador.estado, LotePagos.Estado.BORRADOR)
        self.assertEqual(PagoRealizado.objects.filter(lote=lote).count(), 1)
        self.assertEqual(PagoRealizado.objects.filter(lote=borrador).count(), 1)
        self.assertEqual(PagoRealizado.objects.get(lote=borrador).fecha, nueva.fecha)

    def test_financiera_solo_ve_lotes_enviados(self):
        from programacion.pagos.views import (
            preparar_lote_semana, enviar_lote, construir_contexto_pagos)
        get = {'semana': '2025-03-10', 'tab': 'pendiente'}
        _informe_de(self.clase)
        lote = preparar_lote_semana(self.inicio, self.fin)
        # BORRADOR → financiera no ve nada.
        ctx = construir_contexto_pagos(get, modo='financiera')
        self.assertEqual(len(ctx['filas_pendientes']), 0)
        # ENVIADO → financiera ve la fila.
        enviar_lote(lote, None)
        ctx = construir_contexto_pagos(get, modo='financiera')
        self.assertEqual(len(ctx['filas_pendientes']), 1)

    def test_preparar_pendientes_materializa_backlog(self):
        from programacion.pagos.views import preparar_pendientes
        # No depende de la semana: prepara todas las semanas con clases hasta hoy.
        n = preparar_pendientes(None)
        self.assertGreaterEqual(n, 1)
        self.assertEqual(PagoRealizado.objects.filter(
            lote__estado=LotePagos.Estado.BORRADOR).count(), 1)


class ReenvioYGateInformeTest(TestCase):
    """Filas re-enviables (N lotes ENVIADO por semana, máx. 1 BORRADOR) y gate por
    informe: solo se envían filas cuyo día tiene todos los informes completados."""

    def setUp(self):
        from programacion.colegios.models import Bloque, Clase, Grado
        from datetime import time
        self.colegio = Colegio.objects.create(
            nombre='Colegio Central', departamento='Santander', ciudad='Bucaramanga')
        self.ca = ColegioAnio.objects.create(colegio=self.colegio, anio=2025, valor_hora=40000)
        self.prof_a = Profesor.objects.create(nombre='Ana', apellido='Pérez')
        self.prof_b = Profesor.objects.create(nombre='Luis', apellido='Gómez')
        grado = Grado.objects.create(nombre='11-1')
        self.bloque = Bloque.objects.create(
            colegio=self.ca, grado=grado, hora_inicio=time(8, 0), hora_fin=time(10, 0))
        # Dos filas en la misma semana (10–14 mar 2025): una por profesor.
        self.clase_a = Clase.objects.create(colegio=self.ca, bloque=self.bloque,
                                            profesor=self.prof_a, fecha=date(2025, 3, 11))
        self.clase_b = Clase.objects.create(colegio=self.ca, bloque=self.bloque,
                                            profesor=self.prof_b, fecha=date(2025, 3, 12))
        self.inicio, self.fin = date(2025, 3, 10), date(2025, 3, 14)

    def _preparar(self):
        from programacion.pagos.views import preparar_lote_semana
        return preparar_lote_semana(self.inicio, self.fin)

    def test_enviar_desacopla_excluidas_y_reenvio_posterior(self):
        from programacion.pagos.views import enviar_lote
        _informe_de(self.clase_a)
        _informe_de(self.clase_b)
        lote = self._preparar()
        fila_b = PagoRealizado.objects.get(profesor=self.prof_b)
        fila_b.excluida = True
        fila_b.save()

        self.assertTrue(enviar_lote(lote, None))
        fila_b.refresh_from_db()
        # La excluida quedó desacoplada (no muere con el lote enviado).
        self.assertIsNone(fila_b.lote)
        self.assertEqual(PagoRealizado.objects.filter(lote=lote).count(), 1)

        # Re-preparar la re-adopta a un BORRADOR nuevo, aún excluida.
        borrador = self._preparar()
        self.assertNotEqual(borrador.id, lote.id)
        fila_b.refresh_from_db()
        self.assertEqual(fila_b.lote_id, borrador.id)
        self.assertTrue(fila_b.excluida)

        # Re-incluir y enviar de nuevo: dos lotes ENVIADO en la misma semana.
        fila_b.excluida = False
        fila_b.save()
        self.assertTrue(enviar_lote(borrador, None))
        self.assertEqual(LotePagos.objects.filter(
            estado=LotePagos.Estado.ENVIADO,
            fecha_inicio=self.inicio, fecha_fin=self.fin).count(), 2)

    def test_fila_sin_informe_no_se_envia_y_aparece_en_su_tab(self):
        from programacion.pagos.views import construir_contexto_pagos, enviar_lote
        _informe_de(self.clase_a)   # la clase B queda sin informe
        lote = self._preparar()

        ctx = construir_contexto_pagos({}, modo='programacion')
        self.assertEqual(len(ctx['filas_pendientes']), 1)       # solo A es enviable
        self.assertEqual(len(ctx['filas_sin_informe']), 1)
        self.assertTrue(ctx['filas_sin_informe'][0]['sin_informe'])
        self.assertEqual(ctx['filas_sin_informe'][0]['docente'], self.prof_b.nombre_corto)

        self.assertTrue(enviar_lote(lote, None))
        fila_b = PagoRealizado.objects.get(profesor=self.prof_b)
        self.assertIsNone(fila_b.lote)                          # desacoplada, no enviada
        self.assertEqual(PagoRealizado.objects.filter(lote=lote).count(), 1)

        # Completar el informe la vuelve enviable: re-preparar + segundo envío.
        _informe_de(self.clase_b)
        borrador = self._preparar()
        ctx = construir_contexto_pagos({}, modo='programacion')
        self.assertEqual(len(ctx['filas_sin_informe']), 0)
        self.assertEqual(len(ctx['filas_pendientes']), 1)
        self.assertTrue(enviar_lote(borrador, None))

        # Regresión financiera: ambas filas (en lotes distintos) son visibles/pagables.
        ctx_fin = construir_contexto_pagos({}, modo='financiera')
        self.assertEqual(len(ctx_fin['filas_pendientes']), 2)

    def test_informe_vacio_cuenta_como_sin_informe(self):
        from programacion.pagos.views import _claves_sin_informe
        _informe_de(self.clase_a, actividades='')   # borrador sin diligenciar
        claves = _claves_sin_informe(self.inicio, self.fin)
        self.assertIn((self.clase_a.fecha, self.prof_a.id, self.ca.id), claves)

    def test_enviar_sin_filas_enviables_no_marca_enviado(self):
        from programacion.pagos.views import enviar_lote
        lote = self._preparar()                     # ninguna clase tiene informe
        self.assertFalse(enviar_lote(lote, None))
        lote.refresh_from_db()
        self.assertEqual(lote.estado, LotePagos.Estado.BORRADOR)
        self.assertEqual(PagoRealizado.objects.filter(lote__isnull=True).count(), 2)

    def test_preparar_idempotente_no_toca_filas_enviadas(self):
        from programacion.pagos.views import enviar_lote
        _informe_de(self.clase_a)
        _informe_de(self.clase_b)
        lote = self._preparar()
        self.assertTrue(enviar_lote(lote, None))
        for _ in range(2):
            self._preparar()
        # Las dos filas siguen congeladas en el lote enviado; ningún duplicado.
        self.assertEqual(PagoRealizado.objects.count(), 2)
        self.assertEqual(PagoRealizado.objects.filter(lote=lote).count(), 2)

    def test_constraint_un_solo_borrador_por_semana(self):
        from django.db import IntegrityError, transaction
        LotePagos.objects.create(fecha_inicio=self.inicio, fecha_fin=self.fin,
                                 estado=LotePagos.Estado.ENVIADO)
        LotePagos.objects.create(fecha_inicio=self.inicio, fecha_fin=self.fin,
                                 estado=LotePagos.Estado.ENVIADO)   # 2 ENVIADO: permitido
        LotePagos.objects.create(fecha_inicio=self.inicio, fecha_fin=self.fin)
        with self.assertRaises(IntegrityError), transaction.atomic():
            LotePagos.objects.create(fecha_inicio=self.inicio, fecha_fin=self.fin)

    def test_preparar_pendientes_borra_borradores_vacios(self):
        from programacion.pagos.views import preparar_pendientes
        # Semana pasada sin clases con un BORRADOR vacío huérfano.
        LotePagos.objects.create(fecha_inicio=date(2025, 1, 6), fecha_fin=date(2025, 1, 10))
        preparar_pendientes(None)
        self.assertFalse(LotePagos.objects.filter(
            fecha_inicio=date(2025, 1, 6), filas__isnull=True).exists())


class RevisionProgramacionTest(TestCase):
    """Flujo de revisión por HTTP (backlog): preparar → excluir/extra → enviar (definitivo)."""

    def setUp(self):
        from programacion.colegios.models import Bloque, Clase, Grado
        from datetime import time
        self.client = Client(HTTP_HOST='programacion.testserver')
        User.objects.create_superuser(username='admin_prog', password='pass123')
        self.client.login(username='admin_prog', password='pass123')

        colegio = Colegio.objects.create(
            nombre='Colegio Central', departamento='Santander', ciudad='Bucaramanga')
        self.ca = ColegioAnio.objects.create(colegio=colegio, anio=2025, valor_hora=40000)
        self.prof = Profesor.objects.create(nombre='Ana', apellido='Pérez')
        grado = Grado.objects.create(nombre='11-1')
        bloque = Bloque.objects.create(
            colegio=self.ca, grado=grado, hora_inicio=time(8, 0), hora_fin=time(10, 0))
        self.clase = Clase.objects.create(colegio=self.ca, bloque=bloque,
                                          profesor=self.prof, fecha=date(2025, 3, 11))
        _informe_de(self.clase)   # con informe: la fila es enviable
        self.semana = '2025-03-10'

    def _preparar(self):
        self.client.post('/pagos/preparar/', {'tab': 'pendiente'})
        return PagoRealizado.objects.get()

    def test_preparar_crea_borrador(self):
        r = self.client.post('/pagos/preparar/', {'tab': 'pendiente'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(LotePagos.objects.count(), 1)
        self.assertEqual(PagoRealizado.objects.count(), 1)

    def test_pagina_backlog_renderiza_controles(self):
        self._preparar()
        r = self.client.get('/pagos/?tab=pendiente')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'btn-detalle')   # modal (i) de detalle
        self.assertContains(r, 'btn-extras')    # gestión de costos extra
        self.assertContains(r, 'modalExtras')
        self.assertNotContains(r, 'btn-editar-valor')  # editar valor base retirado

    def test_excluir_saca_la_fila_del_envio(self):
        pago = self._preparar()
        self.client.post(f'/pagos/{pago.pk}/excluir/', {'tab': 'pendiente'})
        pago.refresh_from_db()
        self.assertTrue(pago.excluida)

    def test_agregar_extra_suma_al_total(self):
        pago = self._preparar()
        self.client.post(f'/pagos/{pago.pk}/extra/',
                         {'concepto': 'Desplazamiento', 'valor': '15000', 'tab': 'pendiente'})
        pago.refresh_from_db()
        self.assertEqual(pago.total_extras, 15000)
        self.assertEqual(pago.total, 95000)  # 80000 + 15000

    def test_enviar_bloquea_edicion(self):
        pago = self._preparar()
        self.client.post('/pagos/enviar/', {'tab': 'pendiente'})
        pago.refresh_from_db()
        self.assertEqual(pago.lote.estado, LotePagos.Estado.ENVIADO)
        # Agregar un extra tras enviar no debe hacer nada (fila ya no editable).
        self.client.post(f'/pagos/{pago.pk}/extra/',
                         {'concepto': 'Tarde', 'valor': '1', 'tab': 'pendiente'})
        pago.refresh_from_db()
        self.assertEqual(pago.extras.count(), 0)

    def test_enviar_es_definitivo_sin_reabrir(self):
        # La ruta de reabrir ya no existe (404).
        self._preparar()
        self.client.post('/pagos/enviar/', {'tab': 'pendiente'})
        r = self.client.post('/pagos/reabrir/', {'tab': 'pendiente'})
        self.assertEqual(r.status_code, 404)


class BadgePagosProgramacionTest(TestCase):
    """El badge del menú Pagos cuenta filas por enviar (lote BORRADOR) y se apaga al enviar."""

    def setUp(self):
        from programacion.colegios.models import Bloque, Clase, Grado
        from datetime import time
        self.client = Client(HTTP_HOST='programacion.testserver')
        User.objects.create_superuser(username='admin_prog', password='pass123')
        self.client.login(username='admin_prog', password='pass123')
        colegio = Colegio.objects.create(
            nombre='Colegio Central', departamento='Santander', ciudad='Bucaramanga')
        self.ca = ColegioAnio.objects.create(colegio=colegio, anio=2025, valor_hora=40000)
        prof = Profesor.objects.create(nombre='Ana', apellido='Pérez')
        grado = Grado.objects.create(nombre='11-1')
        bloque = Bloque.objects.create(
            colegio=self.ca, grado=grado, hora_inicio=time(8, 0), hora_fin=time(10, 0))
        hoy = date.today()
        self.lunes = hoy - timedelta(days=hoy.weekday())
        clase = Clase.objects.create(colegio=self.ca, bloque=bloque, profesor=prof,
                                     fecha=self.lunes)
        _informe_de(clase)   # enviable: el badge debe apagarse tras un envío real

    def test_badge_pendiente_y_se_apaga_al_enviar(self):
        from programacion.pagos.views import preparar_lote_semana, enviar_lote
        # Antes de preparar no hay filas materializadas → 0.
        r = self.client.get('/pagos/')
        self.assertEqual(r.context['pagos_por_revisar_count'], 0)
        lote = preparar_lote_semana(self.lunes, self.lunes + timedelta(days=4))
        r = self.client.get('/pagos/')
        self.assertEqual(r.context['pagos_por_revisar_count'], 1)  # BORRADOR por enviar
        enviar_lote(lote, None)
        r = self.client.get('/pagos/')
        self.assertEqual(r.context['pagos_por_revisar_count'], 0)  # ya enviado


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

    def test_nombre_mostrar_es_el_basename_en_storage(self):
        # Sin tocar storage: basta asignar el name del FileField.
        soporte = SoportePagoProfesor(
            pago=self.pago, archivo='pagos/pago-ana-perez-2025-03-14.pdf',
            nombre_original='Recibo Original.PDF')
        self.assertEqual(soporte.nombre_mostrar, 'pago-ana-perez-2025-03-14.pdf')
        # Fallback cuando aún no hay archivo (filas de prueba/antiguas).
        self.assertEqual(SoportePagoProfesor(pago=self.pago).nombre_mostrar, 'archivo')


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
