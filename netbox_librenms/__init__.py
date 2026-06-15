try:
    from netbox.plugins import PluginConfig
except ImportError:
    from extras.plugins import PluginConfig


class NetBoxLibreNMSConfig(PluginConfig):
    name = 'netbox_librenms'
    verbose_name = 'LibreNMS Integration'
    description = 'Integrates LibreNMS device status, alerts, interfaces, and LLDP neighbors into NetBox Device views.'
    version = '0.1.0'
    author = 'Antigravity'
    author_email = 'antigravity@example.com'
    base_url = 'librenms'
    required_settings = ['libre_nms_url', 'libre_nms_api_token']
    default_settings = {
        'verify_ssl': True,
        'allow_unauth_graphs': False,
    }

config = NetBoxLibreNMSConfig
