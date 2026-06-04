from rest_framework import serializers
from programacion.pagos.models import PagoRealizado


class PagoRealizadoSerializer(serializers.ModelSerializer):
    profesor_nombre = serializers.SerializerMethodField()
    colegio_nombre = serializers.CharField(source='colegio.colegio.nombre', read_only=True)
    colegio_anio = serializers.IntegerField(source='colegio.anio', read_only=True)
    marcado_por_username = serializers.CharField(source='marcado_por.username', read_only=True, default=None)

    class Meta:
        model = PagoRealizado
        fields = [
            'id', 'profesor', 'colegio', 'fecha', 'horas', 'valor', 'fecha_pago',
            'profesor_nombre', 'colegio_nombre', 'colegio_anio',
            'marcado_por_username',
        ]
        read_only_fields = [
            'id', 'fecha_pago', 'profesor_nombre', 'colegio_nombre',
            'colegio_anio', 'marcado_por_username',
        ]

    def get_profesor_nombre(self, obj):
        nombre = (obj.profesor.nombre or '').split()
        apellido = (obj.profesor.apellido or '').split()
        partes = []
        if nombre:
            partes.append(nombre[0])
        if apellido:
            partes.append(apellido[0])
        return ' '.join(partes) or None

