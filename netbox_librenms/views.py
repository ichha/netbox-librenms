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
    Always checks Device based on IP first (matching primary IP or assigned interface IP),
    then falls back to hostname.
    """
    from django.db.models import Q

    # 1. Prioritize IP match across all matching IPAddress objects in the database
    if ip:
        ip_clean = ip.split('/')[0].strip()
        try:
            ip_addrs = IPAddress.objects.filter(Q(address__startswith=f"{ip_clean}/") | Q(address=ip_clean))
            for ip_addr in ip_addrs:
                # Check if this IP is primary_ip4 or primary_ip6 on any Device
                dev = Device.objects.filter(primary_ip4=ip_addr).first()
                if dev:
                    return dev
                dev = Device.objects.filter(primary_ip6=ip_addr).first()
                if dev:
                    return dev
                
                # Check if this IP is assigned to an interface of a Device
                if ip_addr.assigned_object and hasattr(ip_addr.assigned_object, 'device'):
                    return ip_addr.assigned_object.device
        except Exception:
            pass

    # 2. Check if name is actually an IP address
    if name:
        is_ip = False
        if '.' in name or ':' in name:
            import re
            if not re.search('[a-zA-Z]', name):
                is_ip = True
                
        if is_ip:
            ip_clean = name.split('/')[0].strip()
            try:
                ip_addrs = IPAddress.objects.filter(Q(address__startswith=f"{ip_clean}/") | Q(address=ip_clean))
                for ip_addr in ip_addrs:
                    dev = Device.objects.filter(primary_ip4=ip_addr).first()
                    if dev:
                        return dev
                    dev = Device.objects.filter(primary_ip6=ip_addr).first()
                    if dev:
                        return dev
                    if ip_addr.assigned_object and hasattr(ip_addr.assigned_object, 'device'):
                        return ip_addr.assigned_object.device
            except Exception:
                pass
        else:
            # 3. Fallback to device name match
            dev = Device.objects.filter(name__iexact=name).first()
            if dev:
                return dev
                
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
                # Create the interface in NetBox
                interface = Interface.objects.create(
                    device=device,
                    name=name,
                    type=iftype,
                    description=descr[:200] if descr else '',
                    enabled=True
                )
                added_count += 1
                
                # Assign MAC address if it exists (using NetBox v4.2+ MACAddress model)
                if mac_clean:
                    try:
                        from dcim.models import MACAddress
                        from django.contrib.contenttypes.models import ContentType
                        
                        interface_type = ContentType.objects.get_for_model(Interface)
                        MACAddress.objects.create(
                            mac_address=mac_clean,
                            assigned_object_type=interface_type,
                            assigned_object_id=interface.id
                        )
                    except Exception:
                        # Don't fail the interface import if MAC assignment fails
                        pass
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
        
        # Pre-fetch local interfaces with their associated cables to avoid N+1 queries
        local_interfaces = {i.name.lower(): i for i in instance.interfaces.prefetch_related('cable')}

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
                
                # Check if this neighbor exists inside NetBox (prioritizing IP matching)
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

                # Match local interface
                local_iface = local_interfaces.get(local_port_name.lower()) if local_port_name else None
                local_iface_id = local_iface.id if local_iface else None
                
                # Match remote interface on nb_device
                remote_iface = None
                if nb_device and remote_port and remote_port != 'Unknown':
                    remote_iface = nb_device.interfaces.filter(name__iexact=remote_port).first()
                    if not remote_iface:
                        # Try cleaning remote port name from parenthesis (e.g. "1/1/28 (4cd587785a80)" -> "1/1/28")
                        cleaned_remote_port = remote_port.split('(')[0].strip()
                        remote_iface = nb_device.interfaces.filter(name__iexact=cleaned_remote_port).first()
                remote_iface_id = remote_iface.id if remote_iface else None

                # Check if cable exists on local or remote interface
                cable_exists = False
                if local_iface and local_iface.cable is not None:
                    cable_exists = True
                elif remote_iface and remote_iface.cable is not None:
                    cable_exists = True

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
                    'librenms_url': f"{client.base_url}/device/device={link.get('remote_device_id')}" if link.get('remote_device_id') else None,
                    'local_interface_id': local_iface_id,
                    'remote_interface_id': remote_iface_id,
                    'remote_device_id': nb_device.id if nb_device else None,
                    'cable_exists': cable_exists
                })

        return {
            'active_tab': 'librenms-neighbors',
            'configured': True,
            'device_found': True,
            'neighbors': neighbors,
            'libre_nms_web_url': f"{client.base_url}/device/device={device_id}/tab=chassis"
        }

    def post(self, request, pk):
        device = self.get_object(pk=pk)
        selected_cables = request.POST.getlist('selected_cables')
        
        if not selected_cables:
            messages.warning(request, "No cables selected.")
            return HttpResponseRedirect(request.path)
            
        from django.db import transaction
        from dcim.models import Cable, CableTermination, Interface
        
        # We will import CableStatusChoices if available, or fall back to 'connected' or 'active'
        try:
            from dcim.choices import CableStatusChoices
            status_value = CableStatusChoices.STATUS_CONNECTED
        except (ImportError, AttributeError):
            try:
                from dcim.choices import CableStatusChoices
                status_value = 'active'
            except ImportError:
                status_value = 'connected'

        added_count = 0
        errors = []
        
        for item in selected_cables:
            try:
                parts = item.split(':::')
                if len(parts) < 4:
                    errors.append(f"Invalid cable selection format: {item}")
                    continue
                    
                local_port = parts[0]
                remote_name = parts[1]
                remote_ip = parts[2]
                remote_port = parts[3]
                
                # 1. Resolve local interface (create if missing)
                local_iface = device.interfaces.filter(name__iexact=local_port).first()
                if not local_iface:
                    # Simple type mapping by name
                    name_lower = local_port.lower()
                    if any(x in name_lower for x in ['loopback', 'lo0', 'lo.']):
                        iftype = 'virtual'
                    elif any(x in name_lower for x in ['tunnel', 'tun']):
                        iftype = 'virtual'
                    elif 'null' in name_lower:
                        iftype = 'virtual'
                    elif any(x in name_lower for x in ['bundle-ether', 'bundle', 'be']):
                        iftype = 'virtual'
                    else:
                        iftype = 'other'
                        
                    local_iface = Interface.objects.create(
                        device=device,
                        name=local_port,
                        type=iftype,
                        enabled=True
                    )
                
                # 2. Resolve remote device
                remote_device = find_netbox_device_by_name_or_ip(remote_name, remote_ip)
                if not remote_device:
                    errors.append(f"Remote device '{remote_name}' ({remote_ip}) not found in NetBox. Please create the device first.")
                    continue
                    
                # 3. Resolve remote interface (create if missing)
                remote_iface = remote_device.interfaces.filter(name__iexact=remote_port).first()
                if not remote_iface:
                    cleaned_remote_port = remote_port.split('(')[0].strip()
                    remote_iface = remote_device.interfaces.filter(name__iexact=cleaned_remote_port).first()
                    
                if not remote_iface:
                    cleaned_remote_port = remote_port.split('(')[0].strip()
                    name_lower = remote_port.lower()
                    if any(x in name_lower for x in ['loopback', 'lo0', 'lo.']):
                        iftype = 'virtual'
                    elif any(x in name_lower for x in ['tunnel', 'tun']):
                        iftype = 'virtual'
                    elif 'null' in name_lower:
                        iftype = 'virtual'
                    elif any(x in name_lower for x in ['bundle-ether', 'bundle', 'be']):
                        iftype = 'virtual'
                    else:
                        iftype = 'other'
                        
                    remote_iface = Interface.objects.create(
                        device=remote_device,
                        name=cleaned_remote_port if cleaned_remote_port else remote_port,
                        type=iftype,
                        enabled=True
                    )
                    
                # 4. Check if cable already exists on either endpoint
                if local_iface.cable is not None:
                    errors.append(f"Interface {local_iface.name} already has a cable connection.")
                    continue
                if remote_iface.cable is not None:
                    errors.append(f"Interface {remote_iface.name} on remote device {remote_device.name} already has a cable connection.")
                    continue
                
                with transaction.atomic():
                    # Create the Cable
                    try:
                        cable = Cable.objects.create(status=status_value)
                    except Exception:
                        try:
                            # Try with 'active' status
                            cable = Cable.objects.create(status='active')
                        except Exception:
                            # Try with default
                            cable = Cable.objects.create()
                            
                    CableTermination.objects.create(
                        cable=cable,
                        cable_end='A',
                        termination=local_iface
                    )
                    CableTermination.objects.create(
                        cable=cable,
                        cable_end='B',
                        termination=remote_iface
                    )
                    
                    # Force NetBox to rebuild paths for this cable
                    cable._terminations_modified = True
                    cable.save()
                added_count += 1
            except Exception as e:
                errors.append(f"Failed to connect {item}: {str(e)}")
                
        if added_count > 0:
            messages.success(request, f"Successfully created {added_count} cable connections in NetBox.")
            
        for err in errors:
            messages.error(request, err)
            
        return HttpResponseRedirect(request.path)


from django.views import View
from django.http import HttpResponse, Http404

def normalize_interface_name(name):
    if not name:
        return ""
    # Lowercase and strip whitespace
    n = name.lower().strip()
    # Remove all spaces and special punctuation except forward slashes
    n = "".join(c for c in n if c.isalnum() or c == '/')
    
    # Standardize common interface name prefixes to their standard short versions
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
        "gige": "ge",
        "fastethernet": "fa",
        "ethernet": "eth",
        "portchannel": "po",
        "port-channel": "po",
        "loopback": "lo",
        "vlan": "vl",
        "gi": "ge", # Map gi -> ge for consistency
    }
    for full, short in prefixes.items():
        if n.startswith(full):
            n = short + n[len(full):]
            break
    return n

def match_interface_to_port(netbox_iface_name, port_list):
    if not netbox_iface_name:
        return None

    # First try exact case-insensitive match on Name/Description keys
    nb_name = netbox_iface_name.lower().strip()
    for p in port_list:
        names = []
        for key in ['ifName', 'ifname', 'port_name_raw', 'port_name', 'ifDescr', 'ifdescr']:
            val = p.get(key)
            if val:
                names.append(str(val).lower().strip())
        if nb_name in names:
            return p

    # Second pass: normalize names and try matching
    target_norm = normalize_interface_name(netbox_iface_name)
    
    # Try exact normalized match
    for p in port_list:
        for key in ['ifName', 'ifname', 'port_name_raw', 'port_name', 'ifDescr', 'ifdescr']:
            val = p.get(key)
            if val and normalize_interface_name(str(val)) == target_norm:
                return p

    # Try exact normalized match on ifAlias (Description)
    for p in port_list:
        val = p.get('ifAlias') or p.get('ifalias')
        if val and normalize_interface_name(str(val)) == target_norm:
            return p

    # Try prefix match (e.g. database description starts with target)
    for p in port_list:
        for key in ['ifName', 'ifname', 'port_name_raw', 'port_name', 'ifDescr', 'ifdescr']:
            val = p.get(key)
            if val:
                val_norm = normalize_interface_name(str(val))
                if val_norm and val_norm.startswith(target_norm):
                    return p
                    
    # Try abbreviation fallback check
    abbrevs = {
        'gigabitethernet': 'gi',
        'fastethernet': 'fa',
        'ethernet': 'et',
        'hundredgigabitethernet': 'hu',
        'hundredgige': 'hu',
        'fiftygigabitethernet': 'fi',
        'tengigabitethernet': 'te',
        'fortygigabitethernet': 'fo',
        'loopback': 'lo',
        'vlan': 'vl',
        'port-channel': 'po',
        'bundle-ether': 'be',
    }
    def abbreviate(name):
        for full, short in abbrevs.items():
            if name.startswith(full):
                return name.replace(full, short, 1)
        return name
        
    nb_abbrev = abbreviate(nb_name)
    for p in port_list:
        names = []
        for key in ['ifName', 'ifname', 'port_name_raw', 'port_name', 'ifDescr', 'ifdescr']:
            val = p.get(key)
            if val:
                names.append(str(val).lower().strip())
        for name in names:
            if nb_abbrev == abbreviate(name):
                return p

    return None

class InterfaceLibreNMSGraphView(View):
    def get(self, request, pk):
        import logging
        logger = logging.getLogger('netbox.plugins.netbox_librenms')
        
        try:
            interface = Interface.objects.get(pk=pk)
        except Interface.DoesNotExist:
            logger.error(f"Interface with PK {pk} not found in NetBox")
            raise Http404("Interface not found")
            
        logger.info(f"Fetching LibreNMS graph for interface {interface.name} (device: {interface.device.name})")
            
        client = LibreNMSClient()
        if not client.is_configured():
            logger.error("LibreNMS integration settings are not configured in NetBox")
            return HttpResponse("LibreNMS not configured", status=500)
            
        librenms_device = get_librenms_device(client, interface.device)
        if not librenms_device:
            logger.error(f"Device {interface.device.name} not found in LibreNMS")
            return HttpResponse("Device not found in LibreNMS", status=404)
            
        device_id = librenms_device.get('device_id')
        ports = client.get_device_ports(device_id)
        
        logger.info(f"Retrieved {len(ports)} ports for device {interface.device.name} from LibreNMS")
        
        target_port = match_interface_to_port(interface.name, ports)
        
        # Translate time range query parameter to 'from' parameter
        time_range = request.GET.get('range', '24h')
        range_map = {
            '24h': '-1d',
            '48h': '-2d',
            '7d': '-7d',
            '30d': '-30d',
            '1y': '-1y',
            '1d': '-1d',
            '2d': '-2d',
        }
        from_val = range_map.get(time_range, '-1d')
        
        # Prepare query parameters (dimensions and range)
        width = request.GET.get('width')
        height = request.GET.get('height')
        api_params = {'from': from_val}
        if width:
            api_params['width'] = width
        if height:
            api_params['height'] = height

        # 1. Try port ID first if target_port exists (very reliable, avoids name encoding issues)
        if target_port and target_port.get('port_id'):
            port_id = target_port.get('port_id')
            endpoint = f"ports/{port_id}/port_bits"
            try:
                logger.info(f"Attempting to fetch graph by port ID: {endpoint} with params {api_params}")
                response = client._request('GET', endpoint, params=api_params, stream=True)
                return HttpResponse(response.content, content_type='image/png')
            except Exception as e:
                logger.warning(f"Failed to fetch graph by port ID: {str(e)}. Trying name-based endpoints...")

        # Resolve interface name to use
        librenms_ifname = target_port.get('ifName') if target_port else interface.name
        if not librenms_ifname and target_port:
            for key in ['ifname', 'port_name_raw', 'port_name', 'ifDescr', 'ifdescr']:
                if target_port.get(key):
                    librenms_ifname = target_port.get(key)
                    break
        if not librenms_ifname:
            librenms_ifname = interface.name
            
        import urllib.parse
        
        # 2. Try single-encoded name route
        try:
            ifname_encoded = urllib.parse.quote(librenms_ifname, safe='')
            endpoint = f"devices/{device_id}/ports/{ifname_encoded}/port_bits"
            logger.info(f"Attempting single-encoded fallback to device port endpoint: {endpoint}")
            response = client._request('GET', endpoint, params=api_params, stream=True)
            return HttpResponse(response.content, content_type='image/png')
        except Exception as single_err:
            logger.warning(f"Single encoded port graph query failed: {str(single_err)}. Retrying with double-encoding...")
            
            # 3. Try double-encoded name route
            try:
                ifname_double_encoded = urllib.parse.quote(urllib.parse.quote(librenms_ifname, safe=''), safe='')
                endpoint = f"devices/{device_id}/ports/{ifname_double_encoded}/port_bits"
                logger.info(f"Attempting double-encoded fallback to device port endpoint: {endpoint}")
                response = client._request('GET', endpoint, params=api_params, stream=True)
                return HttpResponse(response.content, content_type='image/png')
            except Exception as double_err:
                err_msg = f"Failed to fetch graph via both single and double encoded routes. Single error: {str(single_err)}. Double error: {str(double_err)}"
                logger.error(err_msg)
                return HttpResponse(err_msg, status=500, content_type="text/plain")




