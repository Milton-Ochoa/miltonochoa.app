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
| 1 | CI GitHub Actions (gate + pip-audit) | ✅ hecho | sin commit aún |
| 2 | Gunicorn 1 worker + hilos | ✅ hecho | sin commit aún |
| 3 | connection.close() en hilos _sync_safe | ✅ hecho | sin commit aún |
| 4 | Eliminar PASSWORD_ENCRYPT_KEY | ✅ hecho | sin commit aún |
| 5 | json_script en dashboard | ⏳ en curso | — |
| 6 | AnonRateThrottle en DRF | ✅ hecho | sin commit aún |
| 7 | Acotar except Exception en informes | ✅ hecho | sin commit aún |

Leyenda: ⬜ pendiente · ⏳ en curso · ✅ hecho

## Notas de sesión

- (inicio) Sesión arrancada en rama `dev`, working tree limpio. Baseline 202 OK.
- Tarea 1: creado `.github/workflows/ci.yml` (Python 3.13, gate + pip-audit informativo). Se verifica en verde tras push (pestaña Actions).
- Tarea 2: `railway.json` startCommand → `--workers 1 --threads 3 -k gthread`. `.env.example` comentario de caché actualizado. README ajustado (línea de gunicorn).
- Tarea 3: `connection.close()` en `finally` de ambos `_sync_safe` (auditoria/views.py y colegios/views.py).
- Tarea 4: borrada lectura en `core/settings.py`; quitada de `.env.example` y de README (3 referencias). grep sin resultados fuera de docs.
- Tarea 6: añadido `AnonRateThrottle` + `'anon': '30/hour'` en `core/settings.py`.
- Tarea 7: `except ObjectDoesNotExist` (con import) en `informes/views.py` (2 bloques).
- PENDIENTE Tarea 5 (json_script) — requiere editar view + template + JS y **probar dashboard en navegador**.
