from netbox.plugins import PluginMenu, PluginMenuItem, PluginMenuButton

role_settings_buttons = (
    PluginMenuButton(
        link='plugins:netbox_librenms:role_settings_add',
        title='Add Role',
        icon_class='mdi mdi-plus-thick',
        permissions=['dcim.view_devicerole']
    ),
)

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
                link_text='Synced Device Roles',
                buttons=role_settings_buttons,
                permissions=['dcim.view_devicerole']
            ),
        ),),
    ),
)
