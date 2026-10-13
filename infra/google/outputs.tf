output "public_ip" {
  value = google_compute_address.studio.address
}

output "ssh" {
  value = "ssh ubuntu@${google_compute_address.studio.address}"
}

output "studio_hostname" {
  value = "${replace(google_compute_address.studio.address, ".", "-")}.sslip.io"
}
