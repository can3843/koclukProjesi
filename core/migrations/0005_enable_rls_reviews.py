from django.db import migrations

from core.rls import enable_rls


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_enable_rls_tasks"),
        ("planner", "0003_studentprofile_rescope_proposal_and_more"),
    ]

    operations = [
        migrations.RunPython(enable_rls, migrations.RunPython.noop),
    ]
