# Deployment
This directory contains the deployment configuration for Agent Studio, including Docker Compose files and the installation script.

- `install.sh`: The main installation script. It is safe to run multiple times (idempotent).
- `docker-compose.yml`: Defines the services (app, db, proxy).

See `docs/OPERATIONS.md` for detailed instructions on starting, stopping, deploying, and reading logs.
