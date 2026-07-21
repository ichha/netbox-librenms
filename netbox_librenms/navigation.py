from netbox.plugins import PluginMenu, PluginMenuItem

menu = PluginMenu(
    label='LibreNMS',
    icon_class='mdi mdi-server-network',
    groups=(
        ('SYNCHRONIZATION', (
            PluginMenuItem(
                link='plugins:netbox_librenms:device_sync_status',
                link_text='Device Sync Status',
                permissions=['dcim.view_device']
            ),
            PluginMenuItem(
                link='plugins:netbox_librenms:role_settings',
                link_text='Device Role Settings',
                permissions=['dcim.view_devicerole']
            ),
        ),),
    ),
)
