-- Runs only when Docker initializes a new PostgreSQL volume.
SELECT 'CREATE DATABASE alba_os_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'alba_os_test')
\gexec

COMMENT ON DATABASE alba_os_test IS 'alba-os-disposable-test-database';
