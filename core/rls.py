"""Enable Row Level Security on every table in the public schema (PostgreSQL only).

Supabase exposes the public schema through its REST API; with RLS on, anon/authenticated roles
are denied everything that no policy allows. Every table also gets one explicit deny-all policy
(`rotam_deny_all`), which has the same effect but keeps the Security Advisor's "RLS Enabled No
Policy" notice quiet. Django connects as the table owner (postgres role), which is not affected by RLS.
Safe to run again: it is what every phase that adds tables calls.
"""

ENABLE_RLS_SQL = """
DO $$
DECLARE
    tbl record;
BEGIN
    FOR tbl IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
        EXECUTE 'ALTER TABLE public.' || quote_ident(tbl.tablename) || ' ENABLE ROW LEVEL SECURITY';
        EXECUTE 'DROP POLICY IF EXISTS rotam_deny_all ON public.' || quote_ident(tbl.tablename);
        EXECUTE 'CREATE POLICY rotam_deny_all ON public.' || quote_ident(tbl.tablename)
            || ' FOR ALL TO PUBLIC USING (false) WITH CHECK (false)';
    END LOOP;
END
$$;
"""


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(ENABLE_RLS_SQL)
