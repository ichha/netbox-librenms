from django.urls import path
from . import views

urlpatterns = [
    # Navigation views
    path('device-sync-status/', views.DeviceSyncStatusView.as_view(), name='device_sync_status'),
    path('role-settings/', views.RoleSettingsListView.as_view(), name='role_settings'),
    path('role-settings/add/', views.RoleSettingsEditView.as_view(), name='role_settings_add'),
    path('role-settings/<int:pk>/edit/', views.RoleSettingsEditView.as_view(), name='role_settings_edit'),
    path('role-settings/<int:pk>/delete/', views.RoleSettingsDeleteView.as_view(), name='role_settings_delete'),
    path('sync-devices/', views.SyncDevicesActionView.as_view(), name='sync_devices'),

    # Device & Interface Tab Views
    path('devices/<int:pk>/librenms-overview/', views.DeviceLibreNMSOverviewView.as_view(), name='device_librenms-overview'),
    path('devices/<int:pk>/librenms-interfaces/', views.DeviceLibreNMSInterfacesView.as_view(), name='device_librenms-interfaces'),
    path('devices/<int:pk>/librenms-neighbors/', views.DeviceLibreNMSNeighborsView.as_view(), name='device_librenms-neighbors'),
    path('interfaces/<int:pk>/librenms-graph/', views.InterfaceLibreNMSGraphView.as_view(), name='interface_librenms-graph'),
]
