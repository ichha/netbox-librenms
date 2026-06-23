from django.urls import path
from .views import DeviceGraphProxyView, LibreNMSTrafficDataView

app_name = 'netbox_librenms'

urlpatterns = [
    # Route: /api/plugins/librenms/device/<pk>/graph/
    path('device/<int:pk>/graph/', DeviceGraphProxyView.as_view(), name='device_graph_proxy'),
    # Route: /api/plugins/librenms/traffic-data/
    path('traffic-data/', LibreNMSTrafficDataView.as_view(), name='traffic_data'),
]
