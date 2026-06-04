# Área `financiera`

Área del edificio AAMO servida en su propio subdominio
(`financiera.miltonochoa.app`; dev: `financiera.lvh.me:8000`).

## Estado

- Arranque del área: subdominio funcional con el mismo *chrome* que programación
  (sidebar, header, footer; ver `templates/base_chrome.html` /
  `templates/base_financiera.html`).
- **Viáticos** (`fin_viaticos_lista`): gestión completa (listar/ver/devolver/aprobar/
  pagar/editar + soportes en `PAGADA` + exportar a Excel + badge de pendientes).
- **Pagos a profesores** (`fin_pagos_lista`): liquidaciones semanales de clases.
  Financiera **solo ve las semanas que programación ya revisó y envió** (`LotePagos`
  ENVIADO), con su **desglose** (base + costos extra). Por fila **marca el pago** (fija
  `fecha_pago` vía `fin_pagos_marcar` con `pago_id`) y **sube/elimina el soporte**;
  desmarcar limpia el pago y sus soportes pero **conserva la fila**. Exporta a Excel.
  **Sin emails.** Badge = filas **enviadas y no pagadas** de la semana actual.

## Cómo está montada

- `financiera/urls.py` → `include('financiera.viaticos.urls')` + `include('financiera.pagos.urls')`
  en la raíz `/` (rutas sin colisión: `''`/`viaticos/…` vs `pagos/…`).
- `financiera/viaticos/` (label `fin_viaticos`) y `financiera/pagos/` (label `fin_pagos`)
  son sub-apps **sin modelos propios**: importan los de programación
  (`programacion.viaticos` y `programacion.pagos` respectivamente; BD única, mismo
  patrón que `usuarios` → `programacion.configuracion`).
- `financiera/pagos/` reutiliza el cálculo de programación (`construir_contexto_pagos`,
  `filas_pagos_por_tab`, `_generar_excel_pagos` de `programacion/pagos/views.py`) con
  `modo='financiera'` (solo lotes ENVIADO) y la validación/descarga de soportes
  (`programacion/viaticos/soportes.py`, `_responder_soporte`). El comprobante es el modelo
  `SoportePagoProfesor` (`prog_pagos_soportes`, FK→`PagoRealizado`). El flujo de revisión
  (preparar/editar/excluir/extras/enviar) vive en programación; ver `CLAUDE.md`.
- Registro del área en `core/areas.py` (`AREAS['financiera']`); urlconf del
  subdominio en `core/urls_financiera.py`; ambas sub-apps en `INSTALLED_APPS`.

## Acceso

- Por grupo `area:financiera` (creado por `usuarios/migrations/0006_grupo_area_financiera.py`)
  o superusuario. Predicado `core.areas.es_personal_financiera`.
- Asignación de usuarios al grupo: por ahora vía `/admin/` de Django.
- `usuarios/middleware.py` ramifica por `request.area`: en `financiera`, superusuario
  y miembros del grupo pasan; el resto va al selector de área del apex.

> Crear un usuario de prueba (dev):
> ```python
> from django.contrib.auth.models import User, Group
> u = User.objects.create_user('finan', 'x', 'finan123')
> u.groups.add(Group.objects.get(name='area:financiera'))
> ```
