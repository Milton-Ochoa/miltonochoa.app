from rest_framework import mixins, viewsets
from rest_framework.filters import OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from django_filters import rest_framework as filters
from colegios.models import Clase, ClaseParticular
from api.serializers import ClaseSerializer, ClaseParticularSerializer


class ClaseFilter(filters.FilterSet):
    desde = filters.DateFilter(field_name='fecha', lookup_expr='gte', label='Desde (YYYY-MM-DD)')
    hasta = filters.DateFilter(field_name='fecha', lookup_expr='lte', label='Hasta (YYYY-MM-DD)')
    profesor = filters.NumberFilter(field_name='profesor_id', label='ID Profesor')

    class Meta:
        model = Clase
        fields = ['colegio', 'cancelada', 'es_evento']


class ClaseParticularFilter(filters.FilterSet):
    desde = filters.DateFilter(field_name='fecha', lookup_expr='gte', label='Desde (YYYY-MM-DD)')
    hasta = filters.DateFilter(field_name='fecha', lookup_expr='lte', label='Hasta (YYYY-MM-DD)')

    class Meta:
        model = ClaseParticular
        fields = ['profesor']


class ClaseViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Clases programadas. Paginación: 200/página por defecto, override con ?page_size=N (max 1000)."""
    serializer_class = ClaseSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = ClaseFilter
    ordering_fields = ['fecha', 'colegio']
    ordering = ['fecha']

    def get_queryset(self):
        return (Clase.objects
                .select_related('materia', 'profesor', 'colegio__colegio', 'bloque__grado')
                .all())


class ClaseParticularViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Clases particulares. Paginación: 200/página por defecto, override con ?page_size=N (max 1000)."""
    serializer_class = ClaseParticularSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = ClaseParticularFilter
    ordering_fields = ['fecha', 'hora_inicio']
    ordering = ['fecha', 'hora_inicio']

    def get_queryset(self):
        return (ClaseParticular.objects
                .select_related('profesor', 'grado')
                .all())
