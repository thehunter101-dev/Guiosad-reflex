CREATE EXTENSION IF NOT EXISTS vector;
SELECT 'CREATE DATABASE guiosad_test' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'guiosad_test')\gexec
\c guiosad_test
CREATE EXTENSION IF NOT EXISTS vector;
