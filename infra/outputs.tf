output "public_ip" {
  value = oci_core_instance.studio.public_ip
}

output "ssh" {
  value = "ssh ubuntu@${oci_core_instance.studio.public_ip}"
}

# Free HTTPS hostname that resolves to the VM's IP (no domain purchase needed).
output "studio_hostname" {
  value = "${replace(oci_core_instance.studio.public_ip, ".", "-")}.sslip.io"
}

output "image_used" {
  value = data.oci_core_images.ubuntu_arm.images[0].display_name
}
