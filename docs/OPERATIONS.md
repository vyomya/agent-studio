# Operations

## Deployment
To deploy the application, run:
```bash
sudo deploy/install.sh
```
This script is idempotent and can be run multiple times to update or repair the installation.

## Services
The application runs as a set of Docker containers defined in `deploy/docker-compose.yml`.
- Start/Stop: `docker compose -f deploy/docker-compose.yml up -d` / `down`
- Logs: `docker compose -f deploy/docker-compose.yml logs -f`

## Reboot
The system is configured to restart all services automatically upon VM reboot via systemd units.
