from rest_framework import mixins, viewsets
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from programacion.exportar.models import PagoRealizado
from programacion.api.serializers import PagoRealizadoSerializer


class PagoRealizadoViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = PagoRealizadoSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['profesor', 'colegio']
    ordering_fields = ['fecha', 'fecha_pago', 'valor']
    ordering = ['-fecha']

    def get_queryset(self):
        qs = (PagoRealizado.objects
              .select_related('profesor', 'colegio__colegio', 'marcado_por')
              .all())
        desde = self.request.query_params.get('desde')
        hasta = self.request.query_params.get('hasta')
        if desde:
            qs = qs.filter(fecha__gte=desde)
        if hasta:
            qs = qs.filter(fecha__lte=hasta)
        return qs

    def perform_create(self, serializer):
        serializer.save(marcado_por=self.request.user)
