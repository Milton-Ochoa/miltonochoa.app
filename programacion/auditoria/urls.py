from django.urls import path
from . import views

# Prefijo del namespace: /auditoria/ (configurado en el urls.py raíz).
urlpatterns = [
    path('', views.lista_alertas, name='lista_alertas'),
    # Solo POST — ver ajax_ignorar_alerta en views.py para la justificación.
    path('ajax/ignorar/<int:alerta_id>/', views.ajax_ignorar_alerta, name='ajax_ignorar_alerta'),
]
