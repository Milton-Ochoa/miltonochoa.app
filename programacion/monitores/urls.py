from django.urls import path

from .views import (configuracion_colegios_simulacro, configuracion_monitores,
                    colegios_simulacro_plantilla, simulacros_lista)
from .pagos_views import (
    monitores_pagos_lista, monitores_pagos_preparar, monitores_pagos_enviar,
    monitores_pagos_excluir_fila, monitores_pagos_agregar_extra,
    monitores_pagos_eliminar_extra, monitores_pago_detalle,
    monitores_pago_soporte_descargar,
)

urlpatterns = [
    path('configuracion/', configuracion_monitores, name='configuracion_monitores'),
    path('colegios/', configuracion_colegios_simulacro,
         name='configuracion_colegios_simulacro'),
    path('colegios/plantilla/', colegios_simulacro_plantilla,
         name='colegios_simulacro_plantilla'),

    # ── Pagos de monitores (Reportes → Pagos → Monitores) ──
    path('pagos/', monitores_pagos_lista, name='monitores_pagos_lista'),
    path('pagos/preparar/', monitores_pagos_preparar, name='monitores_pagos_preparar'),
    path('pagos/enviar/', monitores_pagos_enviar, name='monitores_pagos_enviar'),
    path('pagos/<int:pago_id>/excluir/', monitores_pagos_excluir_fila,
         name='monitores_pagos_excluir_fila'),
    path('pagos/<int:pago_id>/extra/', monitores_pagos_agregar_extra,
         name='monitores_pagos_agregar_extra'),
    path('pagos/extra/<int:extra_id>/eliminar/', monitores_pagos_eliminar_extra,
         name='monitores_pagos_eliminar_extra'),
    path('pagos/<int:pago_id>/', monitores_pago_detalle, name='monitores_pago_detalle'),
    path('pagos/soporte/<int:soporte_id>/', monitores_pago_soporte_descargar,
         name='monitores_pago_soporte_descargar'),

    path('', simulacros_lista, name='simulacros_lista'),
]
