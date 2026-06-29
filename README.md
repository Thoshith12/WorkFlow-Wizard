# Keycloak & PostgreSQL local development with Docker Compose

This repository provides a containerized development environment for PostgreSQL and Keycloak, eliminating the need to install these dependencies locally.

## Prerequisites
* Docker and Docker Compose installed and running on your system.

## Getting Started

1. **Configure Environment**:
   Verify or customize settings/credentials in the [.env](.env) file:
   * `DB_DATABASE`: The database name (default: `keycloak`)
   * `DB_USERNAME`: Database username (default: `keycloak`)
   * `DB_PASSWORD`: Database password
   * `KEYCLOAK_ADMIN_USER`: Admin console username (default: `admin`)
   * `KEYCLOAK_ADMIN_PASSWORD`: Admin console password

2. **Start Services**:
   Run the following command in the project directory to build (if using Dockerfile) and start services in the background:
   ```bash
   docker compose up -d
   ```

3. **Access Services**:
   * **Keycloak Admin Console**: Navigate to [http://localhost:8080](http://localhost:8080) and log in with your admin credentials.
   * **pgAdmin (Database UI)**: Navigate to [http://localhost:5050](http://localhost:5050).
     * Login: `admin@admin.com` / `admin` (or customized values in `.env`).
     * **To connect to the database in pgAdmin**:
       1. Click **Add New Server**.
       2. Set **Name** to `Keycloak Local`.
       3. In the **Connection** tab, enter:
          * **Host name/address**: `postgres` (use the service name defined in docker-compose.yml)
          * **Port**: `5432`
          * **Username**: `keycloak` (or value of `DB_USERNAME` in `.env`)
          * **Password**: `keycloak_password` (or value of `DB_PASSWORD` in `.env`)
       4. Save the connection to view databases, schemas, and tables.
   * **PostgreSQL Database (Direct)**: Direct connections can be made from your host machine via standard database clients (e.g. DBeaver, pgAdmin local app) at `localhost:5432` using credentials from the `.env` file.

4. **Shutdown Services**:
   To stop and remove containers while preserving database volume data:
   ```bash
   docker compose down
   ```
   To also remove the volume (factory reset database):
   ```bash
   docker compose down -v
   ```
