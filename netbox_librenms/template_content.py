from netbox.plugins import PluginTemplateExtension
from .utils import LibreNMSClient
from .views import get_librenms_device

class InterfaceTrafficGraphExtension(PluginTemplateExtension):
    models = ['dcim.interface']

    def left_page(self):
        interface = self.context['object']
        client = LibreNMSClient()
        if not client.is_configured():
            return ''
            
        librenms_device = get_librenms_device(client, interface.device)
        if not librenms_device:
            return ''
            
        return self.render('netbox_librenms/interface_graph.html', extra_context={
            'object': interface,
        })

template_extensions = [InterfaceTrafficGraphExtension]
