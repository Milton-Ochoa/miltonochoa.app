# Esta app ya no define modelos propios.
#
# `PagoRealizado` y `SoportePagoProfesor` se movieron a la sub-app `programacion.pagos`
# (tablas `prog_pagos`/`prog_pagos_soportes` intactas; el movimiento se hizo con
# `SeparateDatabaseAndState` en exportar.0004 + pagos.0001). `exportar` queda solo con
# la exportación masiva de horarios.
