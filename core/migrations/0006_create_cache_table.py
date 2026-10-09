from django.core.management import call_command
from django.db import migrations

CACHE_TABLE = "rotam_cache"  # must match CACHES["default"]["LOCATION"] in settings


def create_cache_table(apps, schema_editor):
    """The database cache (used for rate limiting) needs its table; `migrate` creates it so no extra step is needed."""
    call_command("createcachetable", CACHE_TABLE, database=schema_editor.connection.alias, verbosity=0)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_enable_rls_reviews"),
    ]

    operations = [
        migrations.RunPython(create_cache_table, migrations.RunPython.noop),
    ]
