from netbox.plugins import PluginTemplateExtension
from .utils import LibreNMSClient
from .views import get_librenms_device

class InterfaceTrafficGraphExtension(PluginTemplateExtension):
    models = ['dcim.interface']

    def render_graph(self):
        # Retrieve the interface object being rendered in NetBox
        interface = self.context.get('object')
        
        # Defensive type checks to guarantee compatibility with all versions and page views
        if not interface or interface.__class__.__name__ != 'Interface':
            return ""
        if not hasattr(interface, 'device') or not interface.device:
            return ""

        client = LibreNMSClient()
        if not client.is_configured():
            return ""
            
        librenms_device = get_librenms_device(client, interface.device)
        if not librenms_device:
            return ""
            
        return self.render('netbox_librenms/interface_graph.html', extra_context={
            'object': interface,
            'device_name': interface.device.name,
            'interface_name': interface.name,
        })

    def right_page(self):
        return self.render_graph()

    def full_width_page(self):
        return self.render_graph()

template_extensions = [InterfaceTrafficGraphExtension]
