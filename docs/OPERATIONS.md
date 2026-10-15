# Agent Studio operations

This guide covers the product deployment managed by deploy/install.sh. Run its commands from the Agent Studio checkout. The script requires root and supports Ubuntu 24.04; it installs Docker Engine and the Compose plugin if needed, enables Docker, installs the agent-studio.service systemd unit, validates the Compose configuration, starts the service, and waits for an HTTP health check.

## Install on Ubuntu 24.04

1. Connect to the Ubuntu 24.04 VM with a user that can run sudo. Ensure the VM can reach package repositories and the Docker image/build sources.
2. Clone the repository, then change to its root directory:

       git clone https://github.com/vyomya/agent-studio.git
       cd agent-studio

   If the repository is already present, update it first with git pull --ff-only origin main.
3. Run the installer as root:

       sudo deploy/install.sh

   The installer checks the OS and Compose file, installs Docker/Compose when absent, enables and starts Docker, writes /etc/systemd/system/agent-studio.service, enables that unit, runs docker compose config, restarts the service, and checks the configured health URL. It exits with an error if the health check does not succeed.
4. The health URL defaults to https://localhost/. Set DEPLOY_URL to override the complete URL, or DEPLOY_HOST to set the HTTPS host used by the installer. For example, export DEPLOY_HOST to the VM hostname before invoking sudo with the environment preserved as appropriate for your sudo policy. The installer uses curl --insecure for this initial check because a local or newly provisioned TLS endpoint may not yet have a trusted certificate.

The installer is safe to re-run: it checks required tools, updates the generated systemd unit only when it differs, validates Compose, and restarts the service. It does not pull the Git repository automatically; update the checkout before running it to deploy a newer revision.

## Start, stop, deploy, and logs

The installer creates and enables agent-studio.service. Manage the Compose application through systemd:

       sudo systemctl start agent-studio.service
       sudo systemctl stop agent-studio.service
       sudo systemctl restart agent-studio.service
       sudo systemctl status agent-studio.service --no-pager

To deploy the latest main revision, update the checkout and run the installer again:

       cd /path/to/agent-studio
       git pull --ff-only origin main
       sudo deploy/install.sh

The installer runs Compose in detached mode. Follow the unit's output with:

       sudo journalctl -u agent-studio.service -f

For container output, from the repository root run:

       sudo docker compose -f deploy/docker-compose.yml logs --follow

The Compose definition is [deploy/docker-compose.yml](../deploy/docker-compose.yml). The checked-in deployment currently exposes the web service on port 8000; the Caddy reverse-proxy/public HTTPS endpoint is available when the full stack configuration is deployed. Do not treat a successful localhost health check as proof that public DNS or HTTPS is working.

## Verify after install or reboot

Check that both Docker and the application unit are enabled and running:

       sudo systemctl is-enabled docker agent-studio.service
       sudo systemctl is-active docker agent-studio.service
       sudo systemctl status agent-studio.service --no-pager

The current web-only Compose service can be checked locally with:

       curl -fsS http://127.0.0.1:8000/

After the full Caddy stack and VM hostname are configured, also verify the public HTTPS endpoint (replace the example with the VM's IP-with-dashes sslip.io hostname):

       curl -fsS https://<ip-with-dashes>.sslip.io/

For a reboot check, run sudo reboot, reconnect after the VM returns, and repeat the systemctl checks and the applicable local/public curl checks above. If the unit is not active or a request fails, inspect sudo journalctl -u agent-studio.service -b and sudo docker compose -f deploy/docker-compose.yml logs.
