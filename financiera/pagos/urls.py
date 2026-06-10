from django.urls import path

from . import views

urlpatterns = [
    path('pagos/',          views.fin_pagos_lista,    name='fin_pagos_lista'),
    path('pagos/marcar/',   views.fin_pagos_marcar,   name='fin_pagos_marcar'),
    path('pagos/exportar/', views.fin_pagos_exportar, name='fin_pagos_exportar'),
    path('pagos/proyeccion/',          views.fin_pagos_proyeccion,          name='fin_pagos_proyeccion'),
    path('pagos/proyeccion/exportar/', views.fin_pagos_proyeccion_exportar, name='fin_pagos_proyeccion_exportar'),
    path('pagos/<int:pago_id>/',         views.fin_pagos_detalle,       name='fin_pagos_detalle'),
    path('pagos/<int:pago_id>/soporte/', views.fin_pagos_subir_soporte, name='fin_pagos_subir_soporte'),
    path('pagos/soporte/<int:soporte_id>/eliminar/',  views.fin_pagos_eliminar_soporte, name='fin_pagos_eliminar_soporte'),
    path('pagos/soporte/<int:soporte_id>/descargar/', views.fin_pago_soporte_descargar, name='fin_pago_soporte_descargar'),
]
