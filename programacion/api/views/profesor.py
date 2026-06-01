from rest_framework import mixins, viewsets
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from programacion.configuracion.models import Profesor
from programacion.api.serializers import ProfesorSerializer


class ProfesorViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ProfesorSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['ciudad', 'departamento']
    search_fields = ['nombre', 'apellido', 'documento']
    ordering_fields = ['nombre', 'apellido']
    ordering = ['nombre']

    def get_queryset(self):
        return Profesor.objects.prefetch_related('materias').all()
