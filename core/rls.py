"""Enable Row Level Security on every table in the public schema (PostgreSQL only).

Supabase exposes the public schema through its REST API; with RLS on and no policies,
anon/authenticated roles are denied everything. Django connects as the table owner
(postgres role), which is not affected by RLS.
"""

ENABLE_RLS_SQL = """
DO $$
DECLARE
    tbl record;
BEGIN
    FOR tbl IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
        EXECUTE 'ALTER TABLE public.' || quote_ident(tbl.tablename) || ' ENABLE ROW LEVEL SECURITY';
    END LOOP;
END
$$;
"""


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(ENABLE_RLS_SQL)
