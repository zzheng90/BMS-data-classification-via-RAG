variable "region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "eu-central-1"
}

variable "instance_type" {
  description = "EC2 size. t3.small = 2 vCPU / 2 GiB (~US$15/mo). Bump to t3.medium (4 GiB) if the pod OOMs."
  type        = string
  default     = "t3.small"
}

variable "my_ip" {
  description = "Your public IP in CIDR form (e.g. 1.2.3.4/32) — used to lock down SSH. Find it with: curl ifconfig.me"
  type        = string
}

variable "app_nodeport" {
  description = "NodePort the Service is pinned to (see k8s/service.yaml)"
  type        = number
  default     = 30080
}

variable "ssh_public_key_path" {
  description = "Local path to the SSH public key registered on the instance"
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "project" {
  description = "Name prefix for tagging"
  type        = string
  default     = "bms-rag-cicd"
}
