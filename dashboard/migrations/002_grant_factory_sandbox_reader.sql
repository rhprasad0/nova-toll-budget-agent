DO $$
BEGIN
    IF to_regrole('factory_sandbox_reader') IS NOT NULL THEN
        GRANT USAGE ON SCHEMA dashboard TO factory_sandbox_reader;
        GRANT SELECT ON ALL TABLES IN SCHEMA dashboard TO factory_sandbox_reader;
    END IF;
END
$$;
