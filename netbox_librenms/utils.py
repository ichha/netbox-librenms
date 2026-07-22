import logging
import requests
from django.conf import settings
from django.core.cache import cache

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

    def _request(self, method, endpoint, params=None, stream=False, json_data=None):
        if not self.is_configured():
            raise ValueError("LibreNMS plugin is not configured in PLUGINS_CONFIG.")
        
        # Simple circuit breaker check
        if cache.get("librenms_circuit_broken"):
            raise requests.exceptions.ConnectionError("LibreNMS connection is temporarily suspended (circuit breaker active).")

        url = f"{self.base_url}/api/v0/{endpoint.lstrip('/')}"
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                params=params,
                json=json_data,
                verify=self.verify_ssl,
                timeout=15 if method in ['POST', 'PATCH', 'PUT'] else 5,
                stream=stream
            )
            response.raise_for_status()
            if stream:
                return response
            return response.json()
        except requests.exceptions.RequestException as e:
            status_code = getattr(e.response, 'status_code', None) if e.response is not None else None
            
            # If it's a 404, log at warning/info level and raise
            if status_code == 404:
                logger.info(f"LibreNMS API 404 (Not Found) for {url}")
            else:
                logger.error(f"LibreNMS API Error for {url}: {str(e)}")
                
                # If it's a connection error or timeout, trigger circuit breaker
                if status_code is None or status_code >= 500:
                    logger.warning("LibreNMS connection error/timeout. Activating circuit breaker for 30 seconds.")
                    cache.set("librenms_circuit_broken", True, 30)
            
            raise e

    def get_device(self, ip_or_name):
        """
        Retrieves a device from LibreNMS.
        Accepts IP address or hostname.
        """
        if not ip_or_name:
            return None

        # Clean key for cache
        cache_key = f"librenms_device_lookup_{ip_or_name}"
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            if cached_result == "NOT_FOUND":
                return None
            return cached_result

        dev = None
        try:
            # First try direct retrieval
            res = self._request('GET', f"devices/{ip_or_name}")
            if res.get('status') == 'ok' and res.get('devices'):
                dev = res['devices'][0]
        except Exception:
            pass
        
        if not dev:
            # If that fails, search the global devices list
            try:
                # Cache the list of all devices for 60 seconds to avoid repeating heavy load
                devices_list_key = "librenms_all_devices_list"
                all_devices = cache.get(devices_list_key)
                if all_devices is None:
                    res = self._request('GET', 'devices')
                    if res.get('status') == 'ok' and res.get('devices'):
                        all_devices = res['devices']
                        cache.set(devices_list_key, all_devices, 60)
                    else:
                        all_devices = []

                if all_devices:
                    target_lower = str(ip_or_name).lower().strip()
                    for d in all_devices:
                        hostname = str(d.get('hostname') or '').lower().strip()
                        sysname = str(d.get('sysName') or '').lower().strip()
                        display = str(d.get('display') or '').lower().strip()
                        ip = str(d.get('ip') or '').lower().strip()
                        
                        if (target_lower == hostname or 
                            target_lower == sysname or 
                            target_lower == display or 
                            target_lower == ip):
                            dev = d
                            break
            except Exception:
                pass
            
        if dev:
            cache.set(cache_key, dev, 300) # Cache hit for 5 minutes
            return dev
        else:
            cache.set(cache_key, "NOT_FOUND", 60) # Cache miss for 1 minute
            return None

    def get_device_ports(self, hostname_or_id):
        """
        Retrieves ports/interfaces for a device.
        Explicitly requests all required columns to override default minimal API responses.
        """
        columns = "port_id,device_id,ifName,ifIndex,ifDescr,ifAlias,ifSpeed,ifAdminStatus,ifOperStatus,ifPhysAddress,ifVlan,ifVrf"
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
                return res.get('addresses') or res.get('ip') or []
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

    def add_device_v2(self, ip, community):
        """
        Adds a device to LibreNMS using SNMPv2c.
        """
        payload = {
            "hostname": ip,
            "version": "v2c",
            "community": community
        }
        return self._request('POST', 'devices', params=None, stream=False, json_data=payload)

    def add_device_v3(self, ip, cf):
        """
        Adds a device to LibreNMS using SNMPv3.
        """
        payload = {
            "hostname": ip,
            "version": "v3",
            "authlevel": cf.get("security_level", "authPriv"),
            "authname": cf.get("security_name", ""),
            "authpass": cf.get("authentication_passphrase", ""),
            "authalgo": cf.get("authentication_protocol", "SHA"),
            "cryptopass": cf.get("privacy_passphrase", ""),
            "cryptoalgo": cf.get("privacy_protocol", "AES"),
            "contextname": cf.get("context_name", "")
        }
        return self._request('POST', 'devices', params=None, stream=False, json_data=payload)

    def update_device_purpose(self, ip_or_id, purpose_text):
        """
        Updates the purpose field of a device in LibreNMS.
        """
        import urllib.parse
        encoded_id = urllib.parse.quote(str(ip_or_id), safe='')
        payload = {
            "field": "purpose",
            "data": purpose_text
        }
        return self._request('PATCH', f"devices/{encoded_id}", params=None, stream=False, json_data=payload)

    def create_device_group(self, group_name):
        """
        Creates a dynamic device group in LibreNMS matching purpose.
        """
        import json
        rules_dict = {
            "condition": "AND",
            "rules": [
                {
                    "id": "devices.purpose",
                    "field": "devices.purpose",
                    "type": "string",
                    "input": "text",
                    "operator": "contains",
                    "value": group_name
                }
            ],
            "valid": True
        }

        payload = {
            "name": group_name,
            "desc": group_name,
            "type": "dynamic",
            "rules": json.dumps(rules_dict)
        }
        return self._request('POST', 'devicegroups', params=None, stream=False, json_data=payload)

    def get_device_groups(self):
        """
        Retrieves all device groups from LibreNMS.
        """
        try:
            res = self._request('GET', 'devicegroups')
            if isinstance(res, dict):
                return res.get("groups") or res.get("devicegroups") or []
        except Exception as e:
            logger.error(f"Failed to retrieve LibreNMS device groups: {str(e)}")
        return []

    def get_devices_in_group(self, group_name):
        """
        Retrieves devices belonging to a specific LibreNMS group.
        """
        import urllib.parse
        try:
            encoded_name = urllib.parse.quote(group_name, safe='')
            res = self._request('GET', f"devicegroups/{encoded_name}")
            if isinstance(res, dict):
                return res.get("devices", [])
        except Exception as e:
            logger.error(f"Failed to retrieve devices in group '{group_name}': {str(e)}")
        return []

    def discover_device(self, ip_or_id):
        """
        Triggers discovery for a device in LibreNMS.
        """
        import urllib.parse
        try:
            encoded_id = urllib.parse.quote(str(ip_or_id), safe='')
            return self._request('GET', f"devices/{encoded_id}/discover")
        except Exception as e:
            logger.error(f"Failed to discover device '{ip_or_id}': {str(e)}")
            return None

    def get_all_librenms_devices_map(self):
        """
        Returns a dictionary mapping hostname, sysName, display, and IP to device objects in LibreNMS.
        """
        devices_map = {}
        try:
            res = self._request('GET', 'devices')
            if isinstance(res, dict) and res.get('status') == 'ok':
                for dev in res.get('devices', []):
                    hostname = str(dev.get('hostname') or '').lower().strip()
                    sysname = str(dev.get('sysName') or '').lower().strip()
                    display = str(dev.get('display') or '').lower().strip()
                    ip = str(dev.get('ip') or '').lower().strip()

                    if hostname:
                        devices_map[hostname] = dev
                    if sysname:
                        devices_map[sysname] = dev
                    if display:
                        devices_map[display] = dev
                    if ip:
                        devices_map[ip] = dev
        except Exception as e:
            logger.error(f"Failed to fetch all LibreNMS devices map: {str(e)}")
        return devices_map

    def rename_device(self, device_id_or_old_ip, new_ip):
        """
        Renames a device hostname/IP in LibreNMS.
        """
        try:
            # Route 1: PUT /devices/{id}/rename
            payload = {"hostname": new_ip}
            res = self._request('PUT', f"devices/{device_id_or_old_ip}/rename", json_data=payload)
            if isinstance(res, dict) and res.get('status') == 'ok':
                return res
        except Exception:
            pass
        try:
            # Route 2: PUT /devices/{id}
            payload = {"field": "hostname", "value": new_ip}
            res = self._request('PUT', f"devices/{device_id_or_old_ip}", json_data=payload)
            if isinstance(res, dict) and res.get('status') == 'ok':
                return res
        except Exception:
            pass
        return None

    def delete_device(self, device_id_or_ip):
        """
        Deletes a device from LibreNMS.
        """
        try:
            return self._request('DELETE', f"devices/{device_id_or_ip}")
        except Exception as e:
            logger.error(f"Failed to delete LibreNMS device {device_id_or_ip}: {str(e)}")
            return None


