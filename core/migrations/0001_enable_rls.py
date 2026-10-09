from django.db import migrations

from core.rls import enable_rls


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("admin", "0003_logentry_add_action_flag_choices"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("sessions", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(enable_rls, migrations.RunPython.noop),
    ]
