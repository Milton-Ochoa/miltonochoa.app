from django.urls import path
from .views import exportar_view, exportar_contar

urlpatterns = [
    path('', exportar_view, name='exportar'),
    path('contar/', exportar_contar, name='exportar_contar'),
]
