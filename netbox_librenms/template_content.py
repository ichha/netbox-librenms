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

        # Fetch current In/Out rates and Port Speed
        in_bps = 0.0
        out_bps = 0.0
        if_speed = 0.0
        try:
            port_stats = client.get_port_statistics(librenms_device['device_id'], interface.name)
            if port_stats:
                in_bps = port_stats.get('in_bps', 0.0)
                out_bps = port_stats.get('out_bps', 0.0)
                if_speed = port_stats.get('ifSpeed')
        except Exception:
            pass

        if not if_speed and interface.speed:
            if_speed = float(interface.speed) * 1000 # convert kbps to bps
            
        return self.render('netbox_librenms/interface_graph.html', extra_context={
            'object': interface,
            'device_name': interface.device.name,
            'interface_name': interface.name,
            'current_in_bps': in_bps,
            'current_out_bps': out_bps,
            'if_speed_bps': if_speed or 0.0,
        })

    def right_page(self):
        return self.render_graph()

template_extensions = [InterfaceTrafficGraphExtension]
