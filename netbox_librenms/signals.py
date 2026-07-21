import logging
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from dcim.models import Device
from .utils import LibreNMSClient

logger = logging.getLogger('netbox_librenms.signals')


@receiver(post_save, sender=Device)
def auto_sync_device_to_librenms(sender, instance, created, **kwargs):
    """
    Real-time signal handler to automatically sync newly created or updated
    NetBox devices to LibreNMS when a primary IP and valid SNMP fields exist.
    """
    config = settings.PLUGINS_CONFIG.get('netbox_librenms', {})
    if not config.get('auto_sync_enabled', True):
        return

    # Extract Primary IP
    ip = ""
    if instance.primary_ip4 and instance.primary_ip4.address:
        ip = str(instance.primary_ip4.address.ip)
    elif instance.primary_ip6 and instance.primary_ip6.address:
        ip = str(instance.primary_ip6.address.ip)

    if not ip:
        return

    # Check configured device role filter if specified in settings
    configured_roles = config.get('device_roles', []) or config.get('device_role_slugs', [])
    if configured_roles and instance.role:
        role_slug = getattr(instance.role, 'slug', '')
        role_id_str = str(getattr(instance.role, 'id', ''))
        configured_str_list = [str(x) for x in configured_roles]
        if role_slug not in configured_roles and role_id_str not in configured_str_list:
            return

    client = LibreNMSClient()
    if not client.is_configured():
        return

    try:
        lnms_map = client.get_all_librenms_devices_map()
        ip_clean = ip.strip().lower()
        name_clean = str(instance.name or "").strip().lower()

        # If device already exists in LibreNMS, update purpose if role changed
        if lnms_map.get(ip_clean) or lnms_map.get(name_clean):
            if instance.role and instance.role.name:
                try:
                    client.update_device_purpose(ip, instance.role.name)
                except Exception:
                    pass
            return

        role_name = instance.role.name if instance.role else ""

        # Ensure dynamic device group exists in LibreNMS
        if role_name:
            try:
                lnms_groups = client.get_device_groups()
                group_names = {g.get("name") for g in lnms_groups if isinstance(g, dict) and "name" in g}
                if role_name not in group_names:
                    client.create_device_group(role_name)
            except Exception:
                pass

        cf = instance.custom_field_data or {}
        community = cf.get("snmp_community")
        res = None

        if community:
            res = client.add_device_v2(ip, community)
        elif cf.get("security_name"):
            res = client.add_device_v3(ip, cf)

        if res is not None:
            logger.info(f"[LibreNMS Auto-Sync] Successfully pushed device {instance.name} ({ip}) to LibreNMS.")
            if role_name:
                try:
                    client.update_device_purpose(ip, role_name)
                except Exception:
                    pass
            try:
                client.discover_device(ip)
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[LibreNMS Auto-Sync Error] Failed to auto-sync device {instance.name} ({ip}): {str(e)}")
