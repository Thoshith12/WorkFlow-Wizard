# 🧙‍♂️ Workflow Wizard — Agentic Workflow Orchestration Platform

**Workflow Wizard** is an enterprise-grade, microservice-based **Agentic Workflow Orchestration Platform**. It provides containerized, highly scalable infrastructure for building, executing, and orchestrating intelligent AI workflows, Retrieval-Augmented Generation (RAG) pipelines, and autonomous agent tasks.

---

## 🏗️ Platform Architecture & Services

The platform operates as a suite of decoupled microservices and infrastructure adapters managed via Docker Compose:

| Service Name | Port | Description |
|---|---|---|
| **Workflow Backend** | `8000` | Core FastAPI microservice managing workflows, authentication integration, and task orchestration. |
| **RAG Service** | `8001` | Microservice dedicated to data source ingestion, document indexing, chunking, and vector retrieval. |
| **Keycloak IAM** | `8080` | Enterprise identity and access management provider with OIDC / OAuth2 authentication. |
| **MinIO Console** | `9001` | S3-compatible Object Storage Web Console (Login: `admin` / `minio_password`). |
| **MinIO S3 API** | `9000` | Internal S3 object storage endpoint for documents and binary artifacts. |
| **Qdrant Vector DB** | `6333` | Vector database engine for high-dimensional embedding storage and similarity search. |
| **Redis** | `6379` | High-performance in-memory cache and Celery task queue message broker. |
| **HashiCorp Vault** | `8201` | Secure secret engine for managing secrets, API keys, and environment tokens. |
| **PostgreSQL DB** | `5432` | Primary relational database hosting `keycloak` DB and dedicated `rag_db`. |
| **pgAdmin** | `5050` | Web-based administration UI for PostgreSQL databases. |

---

## 🛠️ Getting Started

### 1. Prerequisites
- Docker and Docker Compose installed and running on your system.

### 2. Environment Configuration
Verify or customize credentials in the [.env](.env) file:
- `DB_DATABASE`: Main database name (`keycloak`)
- `RAG_DB_DATABASE`: Dedicated RAG database name (`rag_db`)
- `RAG_DB_USERNAME`: RAG database username (`rag_user`)
- `RAG_DB_PASSWORD`: RAG database password (`rag_password`)
- `MINIO_ROOT_USER`: MinIO admin username (`admin`)
- `MINIO_ROOT_PASSWORD`: MinIO admin password (`minio_password`)
- `KEYCLOAK_ADMIN_USER`: Keycloak admin username (`admin`)

### 3. Launching the Platform
Start all microservices and infrastructure containers in the background:
```bash
docker compose up -d
```

### 4. Interactive Documentation & Dashboards
- **RAG Service Swagger UI**: [http://localhost:8001/docs](http://localhost:8001/docs)
- **Workflow Backend Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **MinIO Storage Console**: [http://localhost:9001](http://localhost:9001)
- **Keycloak IAM Console**: [http://localhost:8080](http://localhost:8080)
- **pgAdmin UI**: [http://localhost:5050](http://localhost:5050)

---

## 🧹 Managing Services

Stop services while preserving database and object storage volume data:
```bash
docker compose down
```

To perform a complete factory reset (removing persistent volume data):
```bash
docker compose down -v
```
