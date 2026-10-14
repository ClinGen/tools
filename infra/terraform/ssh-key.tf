// Adds our SSH key for Ansible.

resource "aws_lightsail_key_pair" "tools" {
  name       = "tools-ansible-key-${terraform.workspace}"
  public_key = file("~/.ssh/tools_ansible_${terraform.workspace}_ed25519.pub")
}