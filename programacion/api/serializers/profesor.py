from rest_framework import serializers
from configuracion.models import Profesor, Materia


class ProfesorSerializer(serializers.ModelSerializer):
    nombre_corto = serializers.SerializerMethodField()
    materias_nombres = serializers.SerializerMethodField()

    class Meta:
        model = Profesor
        fields = [
            'id', 'nombre', 'apellido', 'nombre_corto',
            'documento', 'email', 'celular',
            'departamento', 'ciudad',
            'banco', 'tipo_cuenta', 'cuenta_bancaria',
            'materias_nombres',
        ]
        read_only_fields = [
            'id', 'nombre', 'apellido', 'nombre_corto',
            'documento', 'email', 'celular',
            'departamento', 'ciudad',
            'banco', 'tipo_cuenta', 'cuenta_bancaria',
            'materias_nombres',
        ]

    def get_nombre_corto(self, obj):
        nombre = (obj.nombre or '').split()
        apellido = (obj.apellido or '').split()
        partes = []
        if nombre:
            partes.append(nombre[0])
        if apellido:
            partes.append(apellido[0])
        return ' '.join(partes)

    def get_materias_nombres(self, obj):
        return list(obj.materias.values_list('nombre', flat=True))
