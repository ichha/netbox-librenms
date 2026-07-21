from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('dcim', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='SyncedDeviceRole',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('created', models.DateTimeField(auto_now_add=True, null=True)),
                ('last_updated', models.DateTimeField(auto_now=True, null=True)),
                ('custom_field_data', models.JSONField(blank=True, default=dict)),
                ('enabled', models.BooleanField(default=True)),
                ('description', models.CharField(blank=True, max_length=200, null=True)),
                ('role', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='librenms_sync_config', to='dcim.devicerole')),
            ],
            options={
                'verbose_name': 'Synced Device Role',
                'verbose_name_plural': 'Synced Device Roles',
                'ordering': ['role__name'],
            },
        ),
    ]
