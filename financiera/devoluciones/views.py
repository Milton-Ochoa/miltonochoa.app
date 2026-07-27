"""Devoluciones de colegios en el área **financiera**: SOLO LECTURA.

El material que un colegio devuelve sin usar lo registra logística (esa escritura
suma al stock y deja rastro en el ledger). Financiera solo necesita **consultarlo**
para ajustar cobros y comisiones de los asesores comerciales, así que aquí no hay
alta ni edición: lista + export, ambos GET/POST-de-lectura.

Sin modelos propios: `DevolucionColegio` es de `logistica.inventario`, y tanto el
queryset anotado como el builder del Excel se importan de `logistica.devoluciones`
para que las dos áreas muestren exactamente lo mismo (BD única, misma hoja).

Gate: superusuario o grupo `area:financiera` (`core.areas.es_personal_financiera`).
"""
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.areas import es_personal_financiera
from logistica.devoluciones.export import generar_excel_devoluciones
from logistica.devoluciones.views import (contexto_detalle,
                                          devoluciones_anotadas,
                                          devoluciones_para_export)
from logistica.inventario.views import _respuesta_xlsx

solo_financiera = user_passes_test(es_personal_financiera, login_url='login')


@solo_financiera
@require_GET  # explícito: en esta área la devolución no se edita por ninguna vía
def fin_devoluciones_lista(request):
    return render(request, 'financiera/devoluciones.html', {
        'devoluciones': devoluciones_anotadas(),
    })


@solo_financiera
@require_GET
def fin_devoluciones_detallado(request):
    """El detalle por material y grado en pantalla — misma tabla que logística
    (parcial compartido) para no tener que bajar el Excel solo para verlo."""
    return render(request, 'financiera/devoluciones_detalle.html',
                  contexto_detalle())


@solo_financiera
@require_POST
def fin_devoluciones_exportar(request):
    """POST "de lectura" (produce el Excel, no escribe nada) → declarado en
    `posts_lectura` del módulo, así el nivel LECTURA también puede exportar."""
    hoy = timezone.localdate().strftime('%Y%m%d')
    return _respuesta_xlsx(
        generar_excel_devoluciones(devoluciones_para_export(request.POST)),
        f'Devoluciones_{hoy}.xlsx')
