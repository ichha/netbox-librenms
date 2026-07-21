from django import forms
from dcim.models import DeviceRole
from utilities.forms.fields import DynamicModelChoiceField
from netbox.forms import NetBoxModelForm
from .models import SyncedDeviceRole


class SyncedDeviceRoleForm(NetBoxModelForm):
    role = DynamicModelChoiceField(
        queryset=DeviceRole.objects.all(),
        label='Device Role'
    )

    class Meta:
        model = SyncedDeviceRole
        fields = ('role', 'enabled', 'description')
