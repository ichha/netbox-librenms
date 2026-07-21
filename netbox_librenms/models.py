from django.db import models
from django.urls import reverse
from dcim.models import DeviceRole
from netbox.models import NetBoxModel


class SyncedDeviceRole(NetBoxModel):
    role = models.OneToOneField(
        to=DeviceRole,
        on_delete=models.CASCADE,
        related_name='librenms_sync_config',
        verbose_name='Device Role'
    )
    enabled = models.BooleanField(
        default=True,
        verbose_name='Sync Enabled',
        help_text='Enable synchronization of devices under this role to LibreNMS'
    )
    description = models.CharField(
        max_length=200,
        blank=True,
        null=True
    )

    class Meta:
        ordering = ['role__name']
        verbose_name = 'Synced Device Role'
        verbose_name_plural = 'Synced Device Roles'

    def __str__(self):
        return f"{self.role.name} ({'Enabled' if self.enabled else 'Disabled'})"

    def get_absolute_url(self):
        return reverse('plugins:netbox_librenms:role_settings')
