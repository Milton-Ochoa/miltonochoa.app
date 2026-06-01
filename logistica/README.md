# Área `logistica` (placeholder)

Área **futura** del edificio AAMO. Todavía **no implementada**: no tiene apps,
modelos, urls ni rutas activas.

Cuando se implemente:
1. Crear las sub-apps dentro de este paquete (igual que `programacion/`).
2. Crear `logistica/urls.py` agrupando sus rutas.
3. Montarla en `core/urls.py`: `path('logistica/', include('logistica.urls'))`.
4. Registrar el área en `core/views.py` (`AREAS`) y crear el grupo
   `area:logistica` para controlar el acceso desde `seleccion_area`.
