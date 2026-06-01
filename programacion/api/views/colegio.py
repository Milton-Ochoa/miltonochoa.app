from rest_framework import mixins, viewsets
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from programacion.configuracion.models import Colegio, ColegioAnio
from programacion.api.serializers import ColegioSerializer, ColegioAnioSerializer


class ColegioViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ColegioSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['ciudad', 'departamento']
    search_fields = ['nombre', 'ciudad']
    ordering_fields = ['nombre']
    ordering = ['nombre']
    queryset = Colegio.objects.all()


class ColegioAnioViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ColegioAnioSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['anio', 'activo']
    ordering_fields = ['anio', 'colegio__nombre']
    ordering = ['-anio', 'colegio__nombre']

    def get_queryset(self):
        return ColegioAnio.objects.select_related('colegio').all()
