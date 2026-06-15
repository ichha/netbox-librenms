from django.conf import settings
from django.contrib import messages
from django.urls import reverse
from django.http import HttpResponseRedirect
from dcim.models import Device, Interface
from ipam.models import IPAddress
from netbox.views import generic
from utilities.views import ViewTab, register_model_view
from .utils import LibreNMSClient

def get_librenms_device(client, netbox_device):
    """
    Find corresponding device in LibreNMS.
    First tries primary IPv4, then primary IPv6, then falls back to name.
    """
    # Try matching by IPv4
    if netbox_device.primary_ip4 and netbox_device.primary_ip4.address:
        ip = str(netbox_device.primary_ip4.address.ip)
        dev = client.get_device(ip)
        if dev:
            return dev
            
    # Try matching by IPv6
    if netbox_device.primary_ip6 and netbox_device.primary_ip6.address:
        ip = str(netbox_device.primary_ip6.address.ip)
        dev = client.get_device(ip)
        if dev:
            return dev
            
    # Fallback to device name
    if netbox_device.name:
        dev = client.get_device(netbox_device.name)
        if dev:
            return dev
            
    return None

def find_netbox_device_by_name_or_ip(name, ip=None):
    """
    Cross-references LLDP neighbor info back to a NetBox device object.
    Automatically handles case where the hostname is returned as an IP address.
    """
    if not name:
        return None
        
    # Check if name is actually an IP address
    is_ip = False
    if '.' in name or ':' in name:
        import re
        if not re.search('[a-zA-Z]', name):
            is_ip = True
            
    if is_ip:
        ip = name
        name = None

    if name:
        dev = Device.objects.filter(name__iexact=name).first()
        if dev:
            return dev
    if ip:
        ip_clean = ip.split('/')[0].strip()
        try:
            ip_addr = IPAddress.objects.filter(address__host=ip_clean).first()
            if ip_addr and ip_addr.assigned_object:
                if hasattr(ip_addr.assigned_object, 'device'):
                    return ip_addr.assigned_object.device
        except Exception:
            pass
    return None

def format_uptime(seconds):
    """
    Formats uptime in seconds to a human-readable format.
    """
    if not seconds:
        return "Unknown"
    try:
        seconds = int(seconds)
    except ValueError:
        return str(seconds)
        
    days, r = divmod(seconds, 86400)
    hours, r = divmod(r, 3600)
    minutes, seconds = divmod(r, 60)
    
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if len(parts) == 0:
        return f"{seconds}s"
    return " ".join(parts)


def clean_mac(mac_str):
    if not mac_str:
        return None
    cleaned = ''.join(c for c in mac_str if c.isalnum()).lower()
    if len(cleaned) == 12:
        return ':'.join(cleaned[i:i+2] for i in range(0, 12, 2))
    return None


@register_model_view(Device, name='librenms-overview', path='librenms-overview')
class DeviceLibreNMSOverviewView(generic.ObjectView):
    queryset = Device.objects.all()
    template_name = 'netbox_librenms/device_overview.html'
    tab = ViewTab(
        label='LibreNMS-Overview',
        badge=None,
        weight=2000,
        hide_if_empty=False
    )

    def get_extra_context(self, request, instance):
        client = LibreNMSClient()
        if not client.is_configured():
            return {
                'active_tab': 'librenms-overview',
                'configured': False,
                'error_msg': 'LibreNMS integration settings are not configured in configuration.py.'
            }

        librenms_device = get_librenms_device(client, instance)
        if not librenms_device:
            return {
                'active_tab': 'librenms-overview',
                'configured': True,
                'device_found': False,
            }

        # Uptime calculation
        uptime_raw = librenms_device.get('uptime')
        uptime_str = format_uptime(uptime_raw)

        return {
            'active_tab': 'librenms-overview',
            'configured': True,
            'device_found': True,
            'librenms_device': librenms_device,
            'uptime_str': uptime_str,
            'libre_nms_web_url': f"{client.base_url}/device/device={librenms_device.get('device_id')}"
        }


@register_model_view(Device, name='librenms-interfaces', path='librenms-interfaces')
class DeviceLibreNMSInterfacesView(generic.ObjectView):
    queryset = Device.objects.all()
    template_name = 'netbox_librenms/device_interfaces.html'
    tab = ViewTab(
        label='LibreNMS-Interface',
        badge=None,
        weight=2010,
        hide_if_empty=False
    )

    def get_extra_context(self, request, instance):
        client = LibreNMSClient()
        if not client.is_configured():
            return {
                'active_tab': 'librenms-interfaces',
                'configured': False,
                'error_msg': 'LibreNMS integration settings are not configured.'
            }

        librenms_device = get_librenms_device(client, instance)
        if not librenms_device:
            return {
                'active_tab': 'librenms-interfaces',
                'configured': True,
                'device_found': False
            }

        device_id = librenms_device.get('device_id')
        ports = client.get_device_ports(device_id)
        ips = client.get_device_ips(device_id)

        # Get existing interfaces registered in NetBox
        existing_interfaces = set(instance.interfaces.values_list('name', flat=True))

        # Map IP addresses to interface names or interface indices
        ip_map = {}
        for ip_info in ips:
            ifname = ip_info.get('ifName')
            ifindex = ip_info.get('ifIndex')
            
            # Form IP string
            v4 = ip_info.get('ipv4_address')
            v4_len = ip_info.get('ipv4_prefixlen')
            v6 = ip_info.get('ipv6_address')
            v6_len = ip_info.get('ipv6_prefixlen')
            
            ip_str_list = []
            if v4:
                ip_str_list.append(f"{v4}/{v4_len}" if v4_len else v4)
            if v6:
                ip_str_list.append(f"{v6}/{v6_len}" if v6_len else v6)

            for key in [ifname, ifindex]:
                if key:
                    if key not in ip_map:
                        ip_map[key] = []
                    ip_map[key].extend(ip_str_list)

        # Build list of ports with integrated IP info
        interfaces_data = []
        for port in ports:
            ifname = port.get('ifName') or port.get('ifname') or port.get('port_name_raw') or port.get('port_name') or port.get('ifDescr') or port.get('ifdescr') or ''
            ifindex = port.get('ifIndex') or port.get('ifindex')
            
            # Find IPs for this port
            port_ips = []
            if ifname in ip_map:
                port_ips.extend(ip_map[ifname])
            if ifindex in ip_map:
                port_ips.extend(ip_map[ifindex])
            # De-duplicate
            port_ips = list(set(port_ips))

            # Grab VLAN info from LibreNMS port object
            vlan = None
            vlan_list = port.get('vlans')
            if isinstance(vlan_list, list) and vlan_list:
                vlans_extracted = []
                for v in vlan_list:
                    vid = v.get('vlan_id') or v.get('vlan')
                    if vid:
                        vlans_extracted.append(str(vid))
                if vlans_extracted:
                    vlan = ", ".join(vlans_extracted)
            
            if not vlan:
                vlan = port.get('port_vlan') or port.get('port_vlan_id') or port.get('vlan') or port.get('vlan_id') or "N/A"
                
            if vlan == "1":
                vlan = "1 (Default)"

            # Support both camelCase and lowercase field names
            descr = port.get('ifAlias') or port.get('ifalias') or port.get('ifDescr') or port.get('ifdescr') or ''
            
            raw_speed = port.get('ifSpeed') or port.get('ifspeed') or 0
            try:
                speed = int(raw_speed)
            except ValueError:
                speed = 0
                
            mac = port.get('ifPhysAddress') or port.get('ifphysaddress') or ''
            admin_status = port.get('ifAdminStatus') or port.get('ifadminstatus') or 'unknown'
            oper_status = port.get('ifOperStatus') or port.get('ifoperstatus') or 'unknown'

            exists_in_netbox = ifname in existing_interfaces

            interfaces_data.append({
                'name': ifname,
                'descr': descr,
                'speed': speed,
                'mac': mac,
                'admin_status': admin_status,
                'oper_status': oper_status,
                'ips': port_ips,
                'vlan': vlan,
                'exists_in_netbox': exists_in_netbox,
            })

        return {
            'active_tab': 'librenms-interfaces',
            'configured': True,
            'device_found': True,
            'interfaces': interfaces_data,
            'libre_nms_web_url': f"{client.base_url}/device/device={device_id}/tab=ports"
        }

    def post(self, request, pk):
        device = self.get_object(pk=pk)
        selected_interfaces = request.POST.getlist('selected_interfaces')
        
        if not selected_interfaces:
            messages.warning(request, "No interfaces selected.")
            return HttpResponseRedirect(request.path)
            
        client = LibreNMSClient()
        if not client.is_configured():
            messages.error(request, "LibreNMS integration settings are not configured.")
            return HttpResponseRedirect(request.path)
            
        librenms_device = get_librenms_device(client, device)
        if not librenms_device:
            messages.error(request, "Device not found in LibreNMS.")
            return HttpResponseRedirect(request.path)
            
        device_id = librenms_device.get('device_id')
        ports = client.get_device_ports(device_id)
        
        # Build a map of port name -> port details
        ports_map = {}
        for p in ports:
            ifname = p.get('ifName') or p.get('ifname') or p.get('port_name_raw') or p.get('port_name') or p.get('ifDescr') or p.get('ifdescr') or ''
            if ifname:
                ports_map[ifname] = p
                
        # Get existing interfaces
        existing_interfaces = set(device.interfaces.values_list('name', flat=True))
        
        added_count = 0
        for name in selected_interfaces:
            if name in existing_interfaces:
                continue
                
            port_info = ports_map.get(name, {})
            
            # Determine speed
            speed = 0
            try:
                speed = int(port_info.get('ifSpeed') or port_info.get('ifspeed') or 0)
            except ValueError:
                pass
                
            # Simple interface type mapping
            name_lower = name.lower()
            if any(x in name_lower for x in ['loopback', 'lo0', 'lo.']):
                iftype = 'virtual'
            elif any(x in name_lower for x in ['tunnel', 'tun']):
                iftype = 'virtual'
            elif 'null' in name_lower:
                iftype = 'virtual'
            elif any(x in name_lower for x in ['bundle-ether', 'bundle', 'be']):
                iftype = 'virtual'
            elif speed >= 100000000000:
                iftype = '100gige'
            elif speed >= 40000000000:
                iftype = '40gige'
            elif speed >= 25000000000:
                iftype = '25gige'
            elif speed >= 10000000000:
                iftype = '10gige'
            elif speed >= 1000000000:
                iftype = '1gige'
            else:
                iftype = 'other'

            # Clean and validate MAC address format
            raw_mac = port_info.get('ifPhysAddress') or port_info.get('ifphysaddress') or ''
            mac_clean = clean_mac(raw_mac)
            
            # Prioritize alias (user description) over name
            descr = port_info.get('ifAlias') or port_info.get('ifalias') or port_info.get('ifDescr') or port_info.get('ifdescr') or ''
            
            try:
                Interface.objects.create(
                    device=device,
                    name=name,
                    type=iftype,
                    description=descr[:200] if descr else '',
                    mac_address=mac_clean,
                    enabled=True
                )
                added_count += 1
            except Exception as e:
                messages.error(request, f"Failed to add interface {name}: {str(e)}")
                
        if added_count > 0:
            messages.success(request, f"Successfully added {added_count} interfaces to {device.name} in NetBox.")
            
        return HttpResponseRedirect(request.path)


@register_model_view(Device, name='librenms-neighbors', path='librenms-neighbors')
class DeviceLibreNMSNeighborsView(generic.ObjectView):
    queryset = Device.objects.all()
    template_name = 'netbox_librenms/device_neighbors.html'
    tab = ViewTab(
        label='LibreNMS-Neighbour',
        badge=None,
        weight=2020,
        hide_if_empty=False
    )

    def get_extra_context(self, request, instance):
        client = LibreNMSClient()
        if not client.is_configured():
            return {
                'active_tab': 'librenms-neighbors',
                'configured': False,
                'error_msg': 'LibreNMS integration settings are not configured.'
            }

        librenms_device = get_librenms_device(client, instance)
        if not librenms_device:
            return {
                'active_tab': 'librenms-neighbors',
                'configured': True,
                'device_found': False
            }

        device_id = librenms_device.get('device_id')
        ports = client.get_device_ports(device_id)
        
        # Build local port IDs mapping for this device (support multiple port ID keys)
        port_id_map = {}
        for p in ports:
            pid = p.get('port_id') or p.get('port_id') or p.get('id')
            if pid:
                port_id_map[str(pid)] = p
        
        # Fetch all devices from LibreNMS to build a map of device_id -> hostname/ip/hardware
        device_map = {}
        try:
            devices_res = client._request('GET', 'devices')
            if devices_res.get('status') == 'ok' and devices_res.get('devices'):
                for dev in devices_res['devices']:
                    did = dev.get('device_id')
                    if did:
                        device_map[str(did)] = dev
        except Exception:
            pass

        # Fetch all links from LibreNMS
        all_links = client.get_links()
        
        # Filter links belonging to this device
        neighbors = []
        for link in all_links:
            # Check local device match or local port match
            link_local_dev_id = str(link.get('local_device_id') or link.get('device_id') or '')
            link_local_port_id = str(link.get('local_port_id') or link.get('port_id') or '')
            
            is_match = False
            if link_local_dev_id and link_local_dev_id == str(device_id):
                is_match = True
            elif link_local_port_id and link_local_port_id in port_id_map:
                is_match = True
                
            if is_match:
                local_port_name = 'Unknown'
                local_port = {}
                if link_local_port_id in port_id_map:
                    local_port = port_id_map[link_local_port_id]
                    local_port_name = local_port.get('ifName') or local_port.get('ifname') or local_port.get('port_name_raw') or local_port.get('ifDescr')
                elif link.get('local_port'):
                    local_port_name = link.get('local_port')
                
                remote_name = link.get('remote_hostname') or link.get('remote_device_name') or f"Device ID {link.get('remote_device_id')}"
                remote_port = link.get('remote_port') or 'Unknown'
                
                remote_dev_id = str(link.get('remote_device_id') or '')
                remote_ip = ''
                remote_platform = link.get('remote_platform') or ''
                
                if remote_dev_id in device_map:
                    remote_ip = device_map[remote_dev_id].get('hostname') or device_map[remote_dev_id].get('ip') or ''
                    if not remote_platform:
                        remote_platform = device_map[remote_dev_id].get('hardware') or ''
                
                # Check if this neighbor exists inside NetBox
                nb_device = find_netbox_device_by_name_or_ip(remote_name, remote_ip)
                nb_url = None
                if nb_device:
                    nb_url = reverse('dcim:device', kwargs={'pk': nb_device.pk})

                # Support both camelCase and lowercase field names
                descr = local_port.get('ifAlias') or local_port.get('ifalias') or local_port.get('ifDescr') or local_port.get('ifdescr') or ''
                
                raw_speed = local_port.get('ifSpeed') or local_port.get('ifspeed') or 0
                try:
                    speed = int(raw_speed)
                except ValueError:
                    speed = 0
                    
                mac = local_port.get('ifPhysAddress') or local_port.get('ifphysaddress') or ''
                admin_status = local_port.get('ifAdminStatus') or local_port.get('ifadminstatus') or 'unknown'
                oper_status = local_port.get('ifOperStatus') or local_port.get('ifoperstatus') or 'unknown'

                neighbors.append({
                    'local_port': local_port_name,
                    'local_descr': descr,
                    'local_speed': speed,
                    'local_mac': mac,
                    'local_admin_status': admin_status,
                    'local_oper_status': oper_status,
                    'remote_device_name': remote_name,
                    'remote_device_ip': remote_ip,
                    'remote_platform': remote_platform,
                    'remote_port': remote_port,
                    'netbox_url': nb_url,
                    'librenms_url': f"{client.base_url}/device/device={link.get('remote_device_id')}" if link.get('remote_device_id') else None
                })

        return {
            'active_tab': 'librenms-neighbors',
            'configured': True,
            'device_found': True,
            'neighbors': neighbors,
            'libre_nms_web_url': f"{client.base_url}/device/device={device_id}/tab=chassis"
        }
