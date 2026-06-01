from rest_framework import serializers
from colegios.models import Clase, ClaseParticular


class ClaseSerializer(serializers.ModelSerializer):
    materia_nombre = serializers.CharField(source='materia.nombre', read_only=True)
    materia_color = serializers.CharField(source='materia.color', read_only=True)
    profesor_nombre = serializers.SerializerMethodField()
    colegio_nombre = serializers.CharField(source='colegio.colegio.nombre', read_only=True)
    colegio_anio = serializers.IntegerField(source='colegio.anio', read_only=True)
    valor_hora = serializers.IntegerField(source='colegio.valor_hora', read_only=True)
    grado = serializers.CharField(source='bloque.grado.nombre', read_only=True)
    hora = serializers.CharField(source='bloque.hora', read_only=True)
    duracion_minutos = serializers.IntegerField(source='bloque.duracion_minutos', read_only=True)

    class Meta:
        model = Clase
        fields = [
            'id', 'fecha', 'grado', 'hora', 'duracion_minutos',
            'materia_nombre', 'materia_color',
            'profesor_nombre',
            'colegio_nombre', 'colegio_anio', 'valor_hora',
            'unidad', 'es_evento', 'titulo_evento', 'cancelada', 'comentarios',
        ]
        read_only_fields = fields

    def get_profesor_nombre(self, obj):
        if not obj.profesor_id:
            return None
        nombre = (obj.profesor.nombre or '').split()
        apellido = (obj.profesor.apellido or '').split()
        partes = []
        if nombre:
            partes.append(nombre[0])
        if apellido:
            partes.append(apellido[0])
        return ' '.join(partes) or None


class ClaseParticularSerializer(serializers.ModelSerializer):
    profesor_nombre = serializers.SerializerMethodField()
    grado_nombre = serializers.CharField(source='grado.nombre', read_only=True)

    class Meta:
        model = ClaseParticular
        fields = [
            'id', 'fecha', 'hora_inicio', 'hora_fin',
            'profesor_nombre', 'grado_nombre',
            'estudiante', 'ciudad', 'material',
        ]
        read_only_fields = fields

    def get_profesor_nombre(self, obj):
        nombre = (obj.profesor.nombre or '').split()
        apellido = (obj.profesor.apellido or '').split()
        partes = []
        if nombre:
            partes.append(nombre[0])
        if apellido:
            partes.append(apellido[0])
        return ' '.join(partes) or None
