# Infrastructure

One VM runs everything: the six agents, the test database, and the live product (Docker Compose: app, PostgreSQL,
Caddy with HTTPS on `<ip-with-dashes>.sslip.io`). Each folder is a complete Terraform configuration for one provider.

| Folder | Status | What it creates |
|---|---|---|
| `google/` | **In use** | Static external IP, firewall rules (SSH from `admin_cidr` only; HTTP and HTTPS from anywhere), one `e2-standard-2` VM (2 vCPU, 8 GB, 30 GB `pd-balanced`, Ubuntu 24.04) with `cloud-init.yaml` |
| `oracle/` | Kept for the record, not in use | Always Free `VM.Standard.A1.Flex`; `apply` failed for about six hours with `Out of host capacity` in every availability domain |

The AWS Free plan attempt is described in `DELIVERY.md` (section 5.1); that account was locked during verification
and its Terraform is not part of this repo.

## Use

```bash
cd infra/google
cp terraform.tfvars.example terraform.tfvars    # project_id, region, zone, ssh_public_key_path, admin_cidr
terraform init && terraform apply
terraform output studio_hostname                 # https://<ip-with-dashes>.sslip.io
ssh ubuntu@$(terraform output -raw public_ip)    # then follow "Reproduce" in DELIVERY.md
```

Variables: `project_id`, `region`, `zone`, `machine_type` (default `e2-standard-2`), `ssh_public_key_path`,
`admin_cidr` (your IP in CIDR form, for SSH), `disk_gbs` (default 30).

`terraform.tfvars` and state files are ignored by git. Tear down with `terraform destroy` in the same folder.