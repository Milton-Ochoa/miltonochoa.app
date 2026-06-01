from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from programacion.api.views import (
    ProfesorViewSet,
    ColegioViewSet,
    ColegioAnioViewSet,
    ClaseViewSet,
    ClaseParticularViewSet,
    PagoRealizadoViewSet,
)

router = DefaultRouter()
router.register('profesores', ProfesorViewSet, basename='profesor')
router.register('colegios', ColegioViewSet, basename='colegio')
router.register('colegios-anio', ColegioAnioViewSet, basename='colegioanio')
router.register('clases', ClaseViewSet, basename='clase')
router.register('clases-particulares', ClaseParticularViewSet, basename='claseparticular')
router.register('pagos', PagoRealizadoViewSet, basename='pago')

urlpatterns = router.urls + [
    path('auth/token/', TokenObtainPairView.as_view(), name='api_token_obtain'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='api_token_refresh'),
    path('schema/', SpectacularAPIView.as_view(), name='api_schema'),
    path('docs/', SpectacularSwaggerView.as_view(url_name='api_schema'), name='api_swagger'),
    path('redoc/', SpectacularRedocView.as_view(url_name='api_schema'), name='api_redoc'),
]
