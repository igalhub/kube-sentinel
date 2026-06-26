# Home Lab Deployment (Proxmox + k3s)

This guide covers deploying kube-sentinel on a Proxmox home lab running
k3s on Ubuntu Server 24.04 in a VM — tested on a Beelink SER mini PC
with Proxmox VE 9.2.3.

## Environment

| Component | Version |
|---|---|
| Hypervisor | Proxmox VE 9.2.3 |
| OS | Ubuntu Server 24.04.3 LTS |
| Kubernetes | k3s v1.35.5 |
| Terraform | 1.15.7 |
| Helm | 3.21.2 |
| Docker | 29.6.0 |

## Prerequisites

- Ubuntu Server VM with Docker installed
- Static IP configured
- SSH access from your main machine

## Install k3s

```bash
curl -sfL https://get.k3s.io | sh -
```

Configure kubectl without sudo:

```bash
sudo chmod 644 /etc/rancher/k3s/k3s.yaml
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER:$USER ~/.kube/config
kubectl get nodes
```

Expected output:

```
NAME            STATUS   ROLES           AGE   VERSION
ubuntu-server   Ready    control-plane   1m    v1.35.5+k3s1
```

## Install Terraform and Helm

```bash
# Helm
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Terraform
wget -O - https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com noble main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt update && sudo apt install -y terraform
```

## Build and import the exporter image

Unlike minikube, k3s uses containerd rather than Docker as its runtime.
The image must be built with Docker and then imported into k3s's
containerd:

```bash
git clone git@github.com:igalhub/kube-sentinel.git
cd kube-sentinel

# Build the image
docker build -t kube-sentinel:latest .

# Import into k3s containerd
docker save kube-sentinel:latest | sudo k3s ctr images import -
```

This replaces the `eval $(minikube docker-env)` step from the minikube
guide — k3s has no equivalent command since it uses a separate container
runtime.

## Deploy with Terraform

```bash
cd terraform
terraform init
terraform apply
```

## Access the dashboards

k3s exposes services as NodePort, accessible directly via the VM IP.
Get the assigned ports:

```bash
kubectl get svc -n monitoring
```

Then access via:

```
Grafana:       http://<VM_IP>:<grafana-nodeport>
Prometheus:    http://<VM_IP>:<prometheus-nodeport>
Alertmanager:  http://<VM_IP>:<alertmanager-nodeport>
kube-sentinel: http://<VM_IP>:<kube-sentinel-nodeport>/metrics
```

Replace `<VM_IP>` with your VM's static IP and the nodeport values from
`kubectl get svc -n monitoring`.

Default Grafana credentials: `admin` / `admin` (change on first login).

## Terraform output note

After `terraform apply`, the output will show minikube-style URLs:

```
grafana_url = "minikube service grafana -n monitoring --url"
```

These are hardcoded in the Terraform outputs and do not apply to k3s.
Use `kubectl get svc -n monitoring` instead to find the actual NodePort
values.

## Verify

```bash
kubectl get pods -n monitoring
```

All pods should show `Running` status:

```
NAME                                 READY   STATUS    RESTARTS   AGE
grafana-xxx                          2/2     Running   0          1m
kube-sentinel-xxx                    1/1     Running   0          1m
prometheus-alertmanager-0            1/1     Running   0          1m
prometheus-server-xxx                2/2     Running   0          1m
```

## Teardown

```bash
cd terraform
terraform destroy
```

## Notes

- The Terraform output URLs reference minikube commands — ignore them
  on k3s and use `kubectl get svc -n monitoring` instead
- k3s uses containerd, not Docker, as its runtime — the image import
  step (`docker save | sudo k3s ctr images import`) is required every
  time the image is rebuilt
- k3s installs kubectl automatically — no separate kubectl install needed
- No issues encountered deploying the full monitoring stack on a single
  k3s node with 4 vCPUs and 8GB RAM

## Running alongside other projects

Tested running simultaneously with:
- **vault-secrets-demo** (ports 8000, 8200)
- **expiry-watcher** (port 8080)
- **docker-sentinel** (port 8081)
- **Portainer** (port 9000)

No conflicts — kube-sentinel and the monitoring stack run inside k3s
and are accessed via NodePort, completely separate from the Docker-based
projects.
