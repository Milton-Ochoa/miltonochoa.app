from django.urls import path

from . import views

urlpatterns = [
    path('pagos/',          views.fin_pagos_lista,    name='fin_pagos_lista'),
    path('pagos/marcar/',   views.fin_pagos_marcar,   name='fin_pagos_marcar'),
    path('pagos/exportar/', views.fin_pagos_exportar, name='fin_pagos_exportar'),
]
