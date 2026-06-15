from django.urls import path
from . import views

urlpatterns = [
    # NetBox registers tabs based on name patterns
    path('devices/<int:pk>/librenms-overview/', views.DeviceLibreNMSOverviewView.as_view(), name='device_librenms-overview'),
    path('devices/<int:pk>/librenms-interfaces/', views.DeviceLibreNMSInterfacesView.as_view(), name='device_librenms-interfaces'),
    path('devices/<int:pk>/librenms-neighbors/', views.DeviceLibreNMSNeighborsView.as_view(), name='device_librenms-neighbors'),
]
