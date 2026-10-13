resource "google_project_service" "compute" {
  service            = "compute.googleapis.com"
  disable_on_destroy = false
}

resource "google_compute_address" "studio" {
  name       = "agent-studio-ip"
  region     = var.region
  depends_on = [google_project_service.compute]
}

resource "google_compute_firewall" "ssh" {
  name          = "agent-studio-ssh"
  network       = "default"
  direction     = "INGRESS"
  source_ranges = [var.admin_cidr]
  target_tags   = ["agent-studio"]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
  depends_on = [google_project_service.compute]
}

resource "google_compute_firewall" "web" {
  name          = "agent-studio-web"
  network       = "default"
  direction     = "INGRESS"
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["agent-studio"]

  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }
  depends_on = [google_project_service.compute]
}

resource "google_compute_instance" "studio" {
  name         = "agent-studio"
  machine_type = var.machine_type
  zone         = var.zone
  tags         = ["agent-studio"]

  boot_disk {
    initialize_params {
      image = "ubuntu-os-cloud/ubuntu-2404-lts-amd64"
      size  = var.disk_gbs
      type  = "pd-balanced"
    }
  }

  network_interface {
    network = "default"
    access_config {
      nat_ip = google_compute_address.studio.address
    }
  }

  metadata = {
    ssh-keys  = "ubuntu:${trimspace(file(pathexpand(var.ssh_public_key_path)))}"
    user-data = file("${path.module}/cloud-init.yaml")
  }

  depends_on = [google_project_service.compute]
}
