#!/bin/bash
set -e

# Uses environment variables passed from docker-compose / .env
TOOLS_DB="${TOOLS_DB_DATABASE:-tools_db}"
TOOLS_USER="${TOOLS_DB_USERNAME:-tools_user}"
TOOLS_PASS="${TOOLS_DB_PASSWORD:-tools_password}"

echo "Initializing Tools database '$TOOLS_DB' with user '$TOOLS_USER'..."

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$TOOLS_USER') THEN
            CREATE USER $TOOLS_USER WITH PASSWORD '$TOOLS_PASS';
        END IF;
    END
    \$\$;

    SELECT 'CREATE DATABASE $TOOLS_DB OWNER $TOOLS_USER'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$TOOLS_DB')\gexec

    GRANT ALL PRIVILEGES ON DATABASE $TOOLS_DB TO $TOOLS_USER;
EOSQL
