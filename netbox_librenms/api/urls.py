from django.urls import path
from .views import DeviceGraphProxyView

app_name = 'netbox_librenms'

urlpatterns = [
    # Route: /api/plugins/librenms/device/<pk>/graph/
    path('device/<int:pk>/graph/', DeviceGraphProxyView.as_view(), name='device_graph_proxy'),
]
