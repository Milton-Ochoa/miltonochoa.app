# Área `financiera` (placeholder)

Área **futura** del edificio AAMO. Todavía **no implementada**: no tiene apps,
modelos, urls ni rutas activas.

Cuando se implemente:
1. Crear las sub-apps dentro de este paquete (igual que `programacion/`).
2. Crear `financiera/urls.py` agrupando sus rutas.
3. Montarla en `core/urls.py`: `path('financiera/', include('financiera.urls'))`.
4. Registrar el área en `core/views.py` (`AREAS`) y crear el grupo
   `area:financiera` para controlar el acceso desde `seleccion_area`.
