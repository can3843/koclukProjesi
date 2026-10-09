from django.db import migrations

from core.rls import enable_rls


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_enable_rls_planner"),
        ("planner", "0002_reviewitem_task_mockexam_task_and_more"),
    ]

    operations = [
        migrations.RunPython(enable_rls, migrations.RunPython.noop),
    ]
