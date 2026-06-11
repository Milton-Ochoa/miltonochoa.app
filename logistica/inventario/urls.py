from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='log_home'),

    # Artículos (lista + alta/edición vía modal)
    path('articulos/', views.items_lista, name='log_items_lista'),
    path('articulos/guardar/', views.item_guardar, name='log_item_guardar'),

    # Catálogos
    path('catalogos/bodegas/', views.bodegas, name='log_bodegas'),
    path('catalogos/categorias/', views.categorias, name='log_categorias'),
    path('terceros/', views.terceros, name='log_terceros'),
    path('terceros/ajax/crear/', views.tercero_ajax_crear,
         name='log_tercero_ajax_crear'),

    # Existencias
    path('stock/', views.stock, name='log_stock'),
]
