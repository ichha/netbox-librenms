import logging
import requests
from django.conf import settings

logger = logging.getLogger('netbox.plugins.netbox_librenms')

class LibreNMSClient:
    def __init__(self):
        config = settings.PLUGINS_CONFIG.get('netbox_librenms', {})
        self.base_url = config.get('libre_nms_url', '').rstrip('/')
        self.api_token = config.get('libre_nms_api_token', '')
        self.verify_ssl = config.get('verify_ssl', True)
        
        self.headers = {
            'X-Auth-Token': self.api_token,
            'Accept': 'application/json',
        }

    def is_configured(self):
        return bool(self.base_url and self.api_token)

    def _request(self, method, endpoint, params=None, stream=False):
        if not self.is_configured():
            raise ValueError("LibreNMS plugin is not configured in PLUGINS_CONFIG.")
        
        url = f"{self.base_url}/api/v0/{endpoint.lstrip('/')}"
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                params=params,
                verify=self.verify_ssl,
                timeout=5,
                stream=stream
            )
            response.raise_for_status()
            if stream:
                return response
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"LibreNMS API Error for {url}: {str(e)}")
            raise e

    def get_device(self, ip_or_name):
        """
        Retrieves a device from LibreNMS.
        Accepts IP address or hostname.
        """
        try:
            # First try direct retrieval
            res = self._request('GET', f"devices/{ip_or_name}")
            if res.get('status') == 'ok' and res.get('devices'):
                return res['devices'][0]
        except Exception:
            pass
        
        # If that fails, search the global devices list
        try:
            res = self._request('GET', 'devices')
            if res.get('status') == 'ok' and res.get('devices'):
                for dev in res['devices']:
                    if str(dev.get('ip')) == str(ip_or_name) or str(dev.get('hostname')) == str(ip_or_name):
                        return dev
        except Exception:
            pass
            
        return None

    def get_device_ports(self, hostname_or_id):
        """
        Retrieves ports/interfaces for a device.
        """
        try:
            res = self._request('GET', f"devices/{hostname_or_id}/ports", params={'with': 'vlans'})
            if res.get('status') == 'ok':
                return res.get('ports', [])
        except Exception:
            # Fallback without params if with=vlans is not supported
            try:
                res = self._request('GET', f"devices/{hostname_or_id}/ports")
                if res.get('status') == 'ok':
                    return res.get('ports', [])
            except Exception:
                pass
        return []

    def get_device_ips(self, hostname_or_id):
        """
        Retrieves all configured IP addresses for a device.
        """
        try:
            res = self._request('GET', f"devices/{hostname_or_id}/ip")
            if res.get('status') == 'ok':
                return res.get('ip', [])
        except Exception:
            pass
        return []

    def get_device_vlans(self, hostname_or_id):
        """
        Retrieves VLANs configured on a device.
        """
        try:
            res = self._request('GET', f"devices/{hostname_or_id}/vlans")
            if res.get('status') == 'ok':
                return res.get('vlans', [])
        except Exception:
            pass
        return []

    def get_links(self):
        """
        Retrieves all link connections (LLDP/CDP neighbours) from LibreNMS.
        """
        # Try /api/v0/resources/links first
        try:
            res = self._request('GET', "resources/links")
            if res.get('status') == 'ok' and res.get('links'):
                return res.get('links', [])
        except Exception:
            pass
        
        # Fallback to /api/v0/links
        try:
            res = self._request('GET', "links")
            if res.get('status') == 'ok' and res.get('links'):
                return res.get('links', [])
        except Exception:
            pass
            
        return []

    def get_device_alerts(self, device_id):
        """
        Retrieves active alerts for a device.
        """
        try:
            res = self._request('GET', "alerts")
            if res.get('status') == 'ok':
                alerts = res.get('alerts', [])
                # Filter alerts for this specific device
                return [a for a in alerts if str(a.get('device_id')) == str(device_id)]
        except Exception:
            pass
        return []

    def get_graph_image(self, hostname_or_id, graph_type, from_range='-1d'):
        """
        Retrieves graph image binary data.
        """
        endpoint = f"devices/{hostname_or_id}/{graph_type}"
        params = {
            'from': from_range,
            'width': 600,
            'height': 200,
        }
        return self._request('GET', endpoint, params=params, stream=True)
