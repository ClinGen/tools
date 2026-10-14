// Attaches a static IP address to the Lightsail instance.

resource "aws_lightsail_static_ip_attachment" "tools" {
  provider       = aws.stanford-clingen-projects
  instance_name  = aws_lightsail_instance.tools.id
  static_ip_name = aws_lightsail_static_ip.tools.id
}

resource "aws_lightsail_static_ip" "tools" {
  name     = "tools-ip-${terraform.workspace}"
  provider = aws.stanford-clingen-projects
}
