# NetBox LibreNMS Integration Plugin

A NetBox plugin to retrieve and display live monitoring data, active alerts, interfaces (including IPs/VLANs), and LLDP neighbor connections from LibreNMS directly inside the NetBox Device detail page views.

## Features

- **LibreNMS-Overview Tab**: Show SNMP status, uptime, system description, hardware, OS details, active alerts, and real-time CPU/Memory usage graphs.
- **LibreNMS-Interface Tab**: Displays all interfaces found in LibreNMS, their admin/oper status (with pulsing colored badges), raw description, speed, MAC address, configured IP addresses, and untagged/tagged VLANs. Includes a responsive client-side interface filter.
- **LibreNMS-Neighbour Tab**: Lists discovered LLDP/CDP/FDP neighbors. Automatically cross-references neighbor names or IP addresses back to other devices registered inside NetBox to enable direct in-app navigation.
- **Secure Graph Proxying**: Streams performance charts from LibreNMS securely through the NetBox backend to prevent exposing the LibreNMS API token to the user's browser.

## Installation

1. Clone this repository or copy the `netbox-librenms` package into your NetBox server.
2. Install the package using `pip` inside your NetBox virtual environment:
   ```bash
   pip install -e /path/to/netbox-librenms
   ```
3. Enable the plugin in your NetBox `configuration.py`:
   ```python
   PLUGINS = [
       'netbox_librenms',
   ]
   ```
4. Configure the plugin in the `PLUGINS_CONFIG` block in `configuration.py`:
   ```python
   PLUGINS_CONFIG = {
       'netbox_librenms': {
           'libre_nms_url': 'http://10.26.20.146:8000',
           'libre_nms_api_token': 'cf58c40f98f2d586e39cd11c05fea47f',
           'verify_ssl': False,          # Set to True if using HTTPS with a trusted cert
           'allow_unauth_graphs': False,  # If True, attempts to display graphs directly from LibreNMS URL
       }
   }
   ```
5. Restart the NetBox services (gunicorn/rq-worker):
   ```bash
   sudo systemctl restart netbox netbox-rq
   ```

## Development and Structure

The plugin utilizes NetBox's custom view registration framework (`@register_model_view`) to attach custom tabs directly to the core `dcim.Device` model.

For security and CORS compatibility, client browsers do not query the LibreNMS API directly. Instead:
- Views render HTML immediately and request graph images from the NetBox plugin api: `/api/plugins/librenms/device/<id>/graph/`.
- The backend view queries LibreNMS securely using the backend API token, filters variables, and formats responses correctly.
