#!/bin/bash
set -e

# Uses environment variables passed from docker-compose / .env
RAG_DB="${RAG_DB_DATABASE:-rag_db}"
RAG_USER="${RAG_DB_USERNAME:-rag_user}"
RAG_PASS="${RAG_DB_PASSWORD:-rag_password}"

echo "Initializing RAG database '$RAG_DB' with user '$RAG_USER'..."

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$RAG_USER') THEN
            CREATE USER $RAG_USER WITH PASSWORD '$RAG_PASS';
        END IF;
    END
    \$\$;

    SELECT 'CREATE DATABASE $RAG_DB OWNER $RAG_USER'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$RAG_DB')\gexec

    GRANT ALL PRIVILEGES ON DATABASE $RAG_DB TO $RAG_USER;
EOSQL
