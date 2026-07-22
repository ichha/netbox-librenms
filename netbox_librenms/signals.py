import logging
from django.conf import settings
from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver
from dcim.models import Device
from .utils import LibreNMSClient

logger = logging.getLogger('netbox_librenms.signals')


@receiver(pre_save, sender=Device)
def capture_old_ip(sender, instance, **kwargs):
    """
    Django pre-save signal to determine the device's IP before it is written
    to the database so we can detect IP updates in post_save.
    """
    if instance.pk:
        try:
            # Query the database for the current state before the save is committed
            old_device = Device.objects.filter(pk=instance.pk).select_related('primary_ip4', 'primary_ip6').first()
            if old_device:
                old_ip = ""
                if old_device.primary_ip4 and old_device.primary_ip4.address:
                    old_ip = str(old_device.primary_ip4.address.ip)
                elif old_device.primary_ip6 and old_device.primary_ip6.address:
                    old_ip = str(old_device.primary_ip6.address.ip)
                
                # Cache the old IP on the instance object in memory
                instance._old_primary_ip = old_ip
        except Exception as e:
            logger.debug(f"Failed to capture pre-save device state: {str(e)}")


@receiver(post_save, sender=Device)
def auto_sync_device_to_librenms(sender, instance, created, **kwargs):
    """
    Real-time signal handler to automatically sync newly created or updated
    NetBox devices to LibreNMS when a primary IP and valid SNMP fields exist.
    Also handles updating the device IP in LibreNMS if changed in NetBox.
    """
    config = settings.PLUGINS_CONFIG.get('netbox_librenms', {})
    if not config.get('auto_sync_enabled', True):
        return

    # Extract new Primary IP
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

        # Handle IP Address UPDATE
        old_ip = getattr(instance, '_old_primary_ip', '')
        if old_ip and old_ip != ip:
            old_ip_clean = old_ip.strip().lower()
            matched_lnms_dev = lnms_map.get(old_ip_clean) or lnms_map.get(name_clean)
            if matched_lnms_dev:
                lnms_id = matched_lnms_dev.get('device_id')
                logger.info(f"[LibreNMS Auto-Sync] Detected IP change for {instance.name} from {old_ip} to {ip}. Updating LibreNMS...")
                
                # Attempt to update the IP/hostname in LibreNMS
                rename_res = client.rename_device(lnms_id or old_ip, ip)
                if rename_res:
                    logger.info(f"[LibreNMS Auto-Sync] Successfully updated device IP/hostname in LibreNMS.")
                    return
                else:
                    # Fallback: Delete old IP and recreate with new IP
                    logger.warning(f"[LibreNMS Auto-Sync] Rename API failed. Recreating device under new IP {ip}...")
                    client.delete_device(lnms_id or old_ip)
                    # Proceed to create logic below

        # If device already exists in LibreNMS under current IP/name, just update purpose/group
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


@receiver(post_delete, sender=Device)
def auto_delete_device_from_librenms(sender, instance, **kwargs):
    """
    Real-time signal handler to automatically delete the device from LibreNMS
    when it is deleted in NetBox.
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

    client = LibreNMSClient()
    if not client.is_configured():
        return

    try:
        lnms_map = client.get_all_librenms_devices_map()
        ip_clean = ip.strip().lower()
        name_clean = str(instance.name or "").strip().lower()

        matched_lnms_dev = lnms_map.get(ip_clean) or lnms_map.get(name_clean)
        if matched_lnms_dev:
            lnms_id = matched_lnms_dev.get('device_id') or ip
            logger.info(f"[LibreNMS Auto-Sync] Device {instance.name} deleted in NetBox. Deleting from LibreNMS (ID/IP: {lnms_id})...")
            client.delete_device(lnms_id)
    except Exception as e:
        logger.warning(f"[LibreNMS Auto-Sync Error] Failed to delete device {instance.name} from LibreNMS: {str(e)}")
