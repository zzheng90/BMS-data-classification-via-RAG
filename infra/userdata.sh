#!/bin/bash
# Bootstraps a single-node k3s "cluster" on Amazon Linux 2023.
set -euxo pipefail

# --- swap: give a 2 GiB t3.small some headroom for the ML models -------------
if [ ! -f /swapfile ]; then
  dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

dnf install -y git

# --- k3s -------------------------------------------------------------------
# --disable traefik        : we expose the app via NodePort, no ingress needed
# --write-kubeconfig-mode  : let ec2-user read the kubeconfig
# fail-swap-on=false       : tolerate the swap we just enabled
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server \
  --disable traefik \
  --write-kubeconfig-mode 644 \
  --kubelet-arg=fail-swap-on=false" sh -

# Make kubectl usable for the ec2-user (default ~/.kube/config path).
install -d -o ec2-user -g ec2-user /home/ec2-user/.kube
cp /etc/rancher/k3s/k3s.yaml /home/ec2-user/.kube/config
chown ec2-user:ec2-user /home/ec2-user/.kube/config

echo "k3s bootstrap complete" > /var/log/bms-rag-bootstrap.done
