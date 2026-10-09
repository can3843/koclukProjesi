from django.db import migrations

from core.rls import enable_rls


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_enable_rls"),
        ("catalog", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(enable_rls, migrations.RunPython.noop),
    ]
