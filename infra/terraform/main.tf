// Configures our AWS providers, and it sets up the main Terraform block where
// the Terraform "backend" is set up.

//==============================================================================
// Configure the providers.
// -----------------------------------------------------------------------------
// These are our cloud service providers.
//==============================================================================

// This is the 10K Stanford AWS credits account.
provider "aws" {
  alias   = "stanford-clingen-projects"
  region  = "us-west-2"
  profile = "stanford-clingen-projects"
  default_tags {
    tags = {
      Environment = terraform.workspace
      Project     = "Tools"
    }
  }
}

// This is the AWS account that manages the clinicalgenome.org domain
// and all of its subdomains.
provider "aws" {
  alias   = "route-53"
  region  = "us-west-2"
  profile = "route-53"
}

//==============================================================================
// Configure Terraform.
// -----------------------------------------------------------------------------
// This is the main block of the file. It sets up the Terraform backend, which
// is where we store the Terraform state file. This file is used to keep track
// of the resources that Terraform has created. It is stored in an S3 bucket
// and locked using a DynamoDB table to prevent concurrent writes.
//==============================================================================

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.79"
    }
  }
  // This is the S3 bucket where the Terraform state file will be stored.
  backend "s3" {
    bucket         = "stanford-infra"
    key            = "tools/terraform.tfstate"
    profile        = "stanford-clingen-projects"
    region         = "us-west-2"
    dynamodb_table = "tools_terraform_lock" // We store the lock file in a DynamoDB table.
    encrypt        = true
  }

  required_version = ">= 1.2.0"
}