from django.urls import path

from . import views

urlpatterns = [
    path('',          views.fin_home,           name='fin_home'),
    path('viaticos/', views.fin_viaticos_lista,  name='fin_viaticos_lista'),
]
