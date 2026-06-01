from rest_framework import serializers
from programacion.configuracion.models import Colegio, ColegioAnio


class ColegioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Colegio
        fields = ['id', 'codigo', 'nombre', 'departamento', 'ciudad', 'direccion']
        read_only_fields = fields


class ColegioAnioSerializer(serializers.ModelSerializer):
    nombre = serializers.CharField(source='colegio.nombre', read_only=True)
    ciudad = serializers.CharField(source='colegio.ciudad', read_only=True)
    departamento = serializers.CharField(source='colegio.departamento', read_only=True)

    class Meta:
        model = ColegioAnio
        fields = ['id', 'nombre', 'ciudad', 'departamento', 'anio', 'activo', 'valor_hora']
        read_only_fields = fields
