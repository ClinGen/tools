// Manages subdomains for the tools app.

data "aws_route53_zone" "tools" {
  provider     = aws.route-53
  name         = "clinicalgenome.org"
  private_zone = false
}

resource "aws_route53_record" "tools" {
  provider = aws.route-53
  zone_id  = data.aws_route53_zone.tools.id
  name     = "${terraform.workspace == "prod" ? "tools" : "tools-test"}.clinicalgenome.org"
  type     = "A"
  ttl      = 300

  records = [
    aws_lightsail_static_ip.tools.ip_address
  ]
}
