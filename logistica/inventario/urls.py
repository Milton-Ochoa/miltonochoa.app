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

    # Entradas (+ adjuntos con descarga proxiada)
    path('entradas/', views.entradas_lista, name='log_entradas_lista'),
    path('entradas/nueva/', views.entrada_nueva, name='log_entradas_nueva'),
    path('entradas/<int:pk>/', views.entrada_detalle, name='log_entradas_detalle'),
    path('entradas/<int:pk>/adjuntos/subir/', views.entrada_adjunto_subir,
         name='log_entrada_adjunto_subir'),
    path('entradas/adjuntos/<int:adjunto_id>/eliminar/',
         views.entrada_adjunto_eliminar, name='log_entrada_adjunto_eliminar'),
    path('entradas/adjuntos/<int:adjunto_id>/descargar/',
         views.entrada_adjunto_descargar, name='log_entrada_adjunto_descargar'),

    # Salidas
    path('salidas/', views.salidas_lista, name='log_salidas_lista'),
    path('salidas/nueva/', views.salida_nueva, name='log_salidas_nueva'),
    path('salidas/<int:pk>/', views.salida_detalle, name='log_salidas_detalle'),

    # Traslados
    path('traslados/', views.traslados_lista, name='log_traslados_lista'),
    path('traslados/nuevo/', views.traslado_nuevo, name='log_traslados_nuevo'),
    path('traslados/<int:pk>/', views.traslado_detalle, name='log_traslados_detalle'),

    # Kardex y ledger global
    path('articulos/<int:pk>/kardex/', views.item_kardex, name='log_item_kardex'),
    path('movimientos/', views.movimientos, name='log_movimientos'),

    # Ajuste manual (modal en stock.html)
    path('ajustes/nuevo/', views.ajuste_crear, name='log_ajuste_crear'),
]
