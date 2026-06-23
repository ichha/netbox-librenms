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
                target_lower = str(ip_or_name).lower().strip()
                for dev in res['devices']:
                    hostname = str(dev.get('hostname') or '').lower().strip()
                    sysname = str(dev.get('sysName') or '').lower().strip()
                    display = str(dev.get('display') or '').lower().strip()
                    ip = str(dev.get('ip') or '').lower().strip()
                    
                    if (target_lower == hostname or 
                        target_lower == sysname or 
                        target_lower == display or 
                        target_lower == ip):
                        return dev
        except Exception:
            pass
            
        return None

    def get_device_ports(self, hostname_or_id):
        """
        Retrieves ports/interfaces for a device.
        Explicitly requests all required columns to override default minimal API responses.
        """
        columns = "port_id,device_id,ifName,ifIndex,ifDescr,ifAlias,ifSpeed,ifAdminStatus,ifOperStatus,ifPhysAddress"
        try:
            res = self._request('GET', f"devices/{hostname_or_id}/ports", params={'with': 'vlans', 'columns': columns})
            if res.get('status') == 'ok':
                return res.get('ports', [])
        except Exception:
            try:
                res = self._request('GET', f"devices/{hostname_or_id}/ports", params={'columns': columns})
                if res.get('status') == 'ok':
                    return res.get('ports', [])
            except Exception:
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

    def _normalize_interface_name(self, name):
        if not name:
            return ""
        n = name.lower().strip()
        n = "".join(c for c in n if c.isalnum() or c == '/')
        
        prefixes = {
            "hundredgigabitethernet": "hu",
            "hundredgige": "hu",
            "fortygigabitethernet": "fo",
            "fortygige": "fo",
            "fiftygigabitethernet": "fi",
            "fiftygige": "fi",
            "tengigabitethernet": "te",
            "tengige": "te",
            "gigabitethernet": "ge",
            "fastethernet": "fa",
            "ethernet": "eth",
            "portchannel": "po",
            "loopback": "lo",
            "vlan": "vl",
            "gi": "ge",
        }
        for full, short in prefixes.items():
            if n.startswith(full):
                n = short + n[len(full):]
                break
        return n

    def _parse_rate_str_to_bps(self, rate_str):
        try:
            parts = rate_str.strip().split()
            if not parts:
                return 0.0
            value = float(parts[0])
            if len(parts) > 1:
                unit = parts[1].lower()
                if "gbps" in unit:
                    value *= 1e9
                elif "mbps" in unit:
                    value *= 1e6
                elif "kbps" in unit:
                    value *= 1e3
            return value
        except Exception as e:
            logger.warning(f"Failed to parse rate string '{rate_str}': {str(e)}")
            return 0.0

    def get_port_statistics(self, device_id, port_name):
        columns = "port_id,ifSpeed,ifName,ifDescr,ifAlias,ifInOctets_rate,ifOutOctets_rate"
        res = self._request('GET', f"devices/{device_id}/ports", params={'columns': columns})
        ports = res.get("ports", []) if isinstance(res, dict) else []
        
        matched_port = None
        target_norm = self._normalize_interface_name(port_name)
        
        for port in ports:
            ifName_norm = self._normalize_interface_name(port.get("ifName"))
            ifDescr_norm = self._normalize_interface_name(port.get("ifDescr"))
            if target_norm == ifName_norm or target_norm == ifDescr_norm:
                matched_port = port
                break
                
        if not matched_port:
            for port in ports:
                ifAlias_norm = self._normalize_interface_name(port.get("ifAlias"))
                if target_norm == ifAlias_norm:
                    matched_port = port
                    break

        if not matched_port:
            for port in ports:
                ifName_norm = self._normalize_interface_name(port.get("ifName"))
                ifDescr_norm = self._normalize_interface_name(port.get("ifDescr"))
                
                if ifName_norm and ifName_norm.startswith(target_norm):
                    matched_port = port
                    break
                if ifDescr_norm and ifDescr_norm.startswith(target_norm):
                    matched_port = port
                    break
                    
        if not matched_port:
            logger.warning(f"Port '{port_name}' not found for device '{device_id}' in LibreNMS.")
            return None
            
        in_octets_rate = matched_port.get("ifInOctets_rate")
        out_octets_rate = matched_port.get("ifOutOctets_rate")
        
        in_bps = 0.0
        out_bps = 0.0
        
        if in_octets_rate is not None:
            try:
                in_bps = float(in_octets_rate) * 8
            except (ValueError, TypeError):
                pass
        else:
            in_rate_str = matched_port.get("in_rate")
            if in_rate_str:
                in_bps = self._parse_rate_str_to_bps(in_rate_str)
                
        if out_octets_rate is not None:
            try:
                out_bps = float(out_octets_rate) * 8
            except (ValueError, TypeError):
                pass
        else:
            out_rate_str = matched_port.get("out_rate")
            if out_rate_str:
                out_bps = self._parse_rate_str_to_bps(out_rate_str)
                
        return {
            "in_bps": in_bps,
            "out_bps": out_bps,
            "port_id": matched_port.get("port_id"),
            "ifSpeed": matched_port.get("ifSpeed")
        }

    def get_port_graph_image(self, device_id, port_name, time_range, double_encode=False, width=1100, height=300):
        range_map = {
            "1d": "-1d",
            "2d": "-2d",
            "7d": "-7d",
            "30d": "-30d",
            "1y": "-1y"
        }
        from_time = range_map.get(time_range, "-1d")
        
        import urllib.parse
        encoded_port = urllib.parse.quote(port_name, safe='')
        if double_encode:
            encoded_port = urllib.parse.quote(encoded_port, safe='')
            
        endpoint = f"devices/{urllib.parse.quote(str(device_id), safe='')}/ports/{encoded_port}/port_bits"
        
        params = {
            "from": from_time,
            "width": width,
            "height": height,
            'inverse': '0',
            'stacked': '1',
            'graph_stacked': '1',
        }
        
        return self._request('GET', endpoint, params=params, stream=True)
