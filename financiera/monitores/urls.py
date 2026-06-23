from django.urls import path

from . import views

urlpatterns = [
    path('monitores/pagos/',          views.fin_monitores_pagos_lista,    name='fin_monitores_pagos_lista'),
    path('monitores/pagos/marcar/',   views.fin_monitores_pagos_marcar,   name='fin_monitores_pagos_marcar'),
    path('monitores/pagos/exportar/', views.fin_monitores_pagos_exportar, name='fin_monitores_pagos_exportar'),
    path('monitores/pagos/<int:pago_id>/',         views.fin_monitores_pago_detalle,       name='fin_monitores_pago_detalle'),
    path('monitores/pagos/<int:pago_id>/soporte/', views.fin_monitores_pago_subir_soporte, name='fin_monitores_pago_subir_soporte'),
    path('monitores/pagos/soporte/<int:soporte_id>/eliminar/',  views.fin_monitores_pago_eliminar_soporte, name='fin_monitores_pago_eliminar_soporte'),
    path('monitores/pagos/soporte/<int:soporte_id>/descargar/', views.fin_monitores_pago_soporte_descargar, name='fin_monitores_pago_soporte_descargar'),
]
