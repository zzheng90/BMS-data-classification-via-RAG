output "public_ip" {
  description = "Public IP of the k3s node"
  value       = aws_instance.node.public_ip
}

output "ssh" {
  description = "SSH into the node"
  value       = "ssh ec2-user@${aws_instance.node.public_ip}"
}

output "app_url" {
  description = "Open the app here once the deploy pipeline has run"
  value       = "http://${aws_instance.node.public_ip}"
}

output "github_secrets" {
  description = "Values to add under GitHub repo -> Settings -> Secrets and variables -> Actions"
  value = {
    EC2_HOST = aws_instance.node.public_ip
    EC2_USER = "ec2-user"
  }
}
