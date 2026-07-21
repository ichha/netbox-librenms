import django_tables2 as tables
from netbox.tables import NetBoxTable, columns
from .models import SyncedDeviceRole


class SyncedDeviceRoleTable(NetBoxTable):
    role = tables.Column(linkify=True)
    device_count = tables.Column(verbose_name='Total Devices in NetBox', empty_values=())
    actions = columns.ActionsColumn(actions=('edit', 'delete'))

    class Meta(NetBoxTable.Meta):
        model = SyncedDeviceRole
        fields = ('pk', 'id', 'role', 'device_count', 'enabled', 'description', 'actions')
        default_columns = ('role', 'device_count', 'enabled', 'description', 'actions')

    def render_device_count(self, record):
        return record.role.devices.filter(status='active').count()
