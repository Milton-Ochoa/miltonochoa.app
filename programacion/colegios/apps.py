from django.apps import AppConfig


class ColegiosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'programacion.colegios'
    label = 'colegios'

    def ready(self):
        # Importar el módulo de signals para que los @receiver queden registrados.
        # Sin este import, los signals no se conectan y la invalidación de caché
        # de auditoría no ocurre al guardar/eliminar Clases o Asignaciones.
        import programacion.colegios.signals  # noqa: F401
