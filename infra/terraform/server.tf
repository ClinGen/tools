// Configures the server we use for the tools app.

resource "aws_lightsail_instance" "tools" {
  name              = "tools-lightsail-${terraform.workspace}"
  provider          = aws.stanford-clingen-projects
  availability_zone = "us-west-2a"
  blueprint_id      = "ubuntu_24_04"
  bundle_id         = terraform.workspace == "prod" ? "medium_3_0" : "small_3_0"
}

resource "aws_lightsail_instance_public_ports" "tools" {
  provider      = aws.stanford-clingen-projects
  instance_name = aws_lightsail_instance.tools.name

  port_info {
    protocol  = "tcp"
    from_port = 22
    to_port   = 22
  }

  port_info {
    protocol  = "tcp"
    from_port = 80
    to_port   = 80
  }

  port_info {
    protocol  = "tcp"
    from_port = 443
    to_port   = 443
  }
}
