from django.urls import path

from .views import configuracion_monitores

urlpatterns = [
    path('configuracion/', configuracion_monitores, name='configuracion_monitores'),
]
