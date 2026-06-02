# Registro de progreso — PLAN_MEJORAS_AAMO

> Bitácora viva. Cada sesión actualiza esto al terminar una tarea, por si la sesión
> se corta y otra debe continuar. Fuente del plan: `C:\Users\Usuario\Desktop\PLAN_MEJORAS_AAMO.md`.
> Rama de trabajo: **dev**.

## Baseline a mantener
- `python manage.py check` → 0 issues.
- `python manage.py makemigrations --check --dry-run` → No changes detected.
- `python manage.py test` → **202 tests OK**.

## Estado de tareas

| # | Tarea | Estado | Commit |
|---|-------|--------|--------|
| 0 | Baseline confirmado | ✅ hecho | — (202 OK) |
| 1 | CI GitHub Actions (gate + pip-audit) | ✅ hecho | 6cfc15f |
| 2 | Gunicorn 1 worker + hilos | ✅ hecho | 6cfc15f |
| 3 | connection.close() en hilos _sync_safe | ✅ hecho | 6cfc15f |
| 4 | Eliminar PASSWORD_ENCRYPT_KEY | ✅ hecho | 6cfc15f |
| 5 | json_script en dashboard | ✅ hecho | 9a6dfc4 |
| 6 | AnonRateThrottle en DRF | ✅ hecho | 6cfc15f |
| 7 | Acotar except Exception en informes | ✅ hecho | 6cfc15f |

Leyenda: ⬜ pendiente · ⏳ en curso · ✅ hecho

## Notas de sesión

- (inicio) Sesión arrancada en rama `dev`, working tree limpio. Baseline 202 OK.
- Tarea 1: creado `.github/workflows/ci.yml` (Python 3.13, gate + pip-audit informativo). Se verifica en verde tras push (pestaña Actions).
- Tarea 2: `railway.json` startCommand → `--workers 1 --threads 3 -k gthread`. `.env.example` comentario de caché actualizado. README ajustado (línea de gunicorn).
- Tarea 3: `connection.close()` en `finally` de ambos `_sync_safe` (auditoria/views.py y colegios/views.py).
- Tarea 4: borrada lectura en `core/settings.py`; quitada de `.env.example` y de README (3 referencias). grep sin resultados fuera de docs.
- Tarea 6: añadido `AnonRateThrottle` + `'anon': '30/hour'` en `core/settings.py`.
- Tarea 7: `except ObjectDoesNotExist` (con import) en `informes/views.py` (2 bloques).
- Tarea 5: `colegios/views.py` pasa objetos (no `json.dumps`) en `profesores_por_materia`,
  `bloques_data`, `stats_data`, `libros_especiales_data`. `dashboard.html` usa `{{ x|json_script:"id" }}`
  + `JSON.parse(getElementById(...).textContent)`. Se preservaron los guards `{% if sel_col %}` y
  `{% if not stats_vacio and request.user.is_staff %}` (STATS_JSON sigue siendo `let` y se reasigna
  en el refresh HTMX desde `data.stats`). **Verificación:** render del dashboard real (colegio Altair,
  superusuario) vía test client a través de todo el stack → status 200, los 4 `json_script` con JSON
  válido, IDs del JS coinciden, sin `|safe` residual, contenido escapado. Pendiente solo el chequeo
  visual de consola del navegador por el dueño (riesgo bajo; el patrón JSON.parse es estándar).

### Gate final (todas las tareas)
- `python manage.py check` → 0 issues.
- `python manage.py makemigrations --check --dry-run` → No changes detected.
- `python manage.py test` → **202 OK**.
