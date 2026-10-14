// Stores database backups in a private S3 bucket, one per workspace, and creates
// the IAM users that read and write them. Lightsail instances can't have IAM
// instance roles, so each server uses an IAM user's access key instead.

data "aws_caller_identity" "current" {
  provider = aws.stanford-clingen-projects
}

//==============================================================================
// Configure the bucket.
// -----------------------------------------------------------------------------
// Bucket names are global across all AWS accounts, so the name ends with our
// account ID to keep it from clashing with someone else's bucket.
//==============================================================================

resource "aws_s3_bucket" "backups" {
  provider = aws.stanford-clingen-projects
  bucket   = "tools-backups-${terraform.workspace}-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_ownership_controls" "backups" {
  provider = aws.stanford-clingen-projects
  bucket   = aws_s3_bucket.backups.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "backups" {
  provider                = aws.stanford-clingen-projects
  bucket                  = aws_s3_bucket.backups.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  provider = aws.stanford-clingen-projects
  bucket   = aws_s3_bucket.backups.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

// Every backup name is unique, so we don't need versioning. Backups are kept
// for 90 days.
resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  provider = aws.stanford-clingen-projects
  bucket   = aws_s3_bucket.backups.id

  rule {
    id     = "expire-backups"
    status = "Enabled"

    // An empty prefix matches every backup.
    filter {
      prefix = ""
    }

    expiration {
      days = 90
    }
  }
}

//==============================================================================
// Configure the writer.
// -----------------------------------------------------------------------------
// The server uses this user to take, list, and restore backups.
//==============================================================================

resource "aws_iam_user" "backup_writer" {
  provider = aws.stanford-clingen-projects
  name     = "tools-backup-writer-${terraform.workspace}"
}

resource "aws_iam_user_policy" "backup_writer" {
  provider = aws.stanford-clingen-projects
  name     = "tools-backup-writer-${terraform.workspace}"
  user     = aws_iam_user.backup_writer.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.backups.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.backups.arn}/*"
      },
    ]
  })
}

resource "aws_iam_access_key" "backup_writer" {
  provider = aws.stanford-clingen-projects
  user     = aws_iam_user.backup_writer.name
}

//==============================================================================
// Configure the reader.
// -----------------------------------------------------------------------------
// The weekly restore check in GitHub Actions uses this user to download prod
// backups. It can't change or delete them.
//==============================================================================

resource "aws_iam_user" "backup_reader" {
  count    = terraform.workspace == "prod" ? 1 : 0
  provider = aws.stanford-clingen-projects
  name     = "tools-backup-reader-prod"
}

resource "aws_iam_user_policy" "backup_reader" {
  count    = terraform.workspace == "prod" ? 1 : 0
  provider = aws.stanford-clingen-projects
  name     = "tools-backup-reader-prod"
  user     = aws_iam_user.backup_reader[0].name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.backups.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.backups.arn}/*"
      },
    ]
  })
}

resource "aws_iam_access_key" "backup_reader" {
  count    = terraform.workspace == "prod" ? 1 : 0
  provider = aws.stanford-clingen-projects
  user     = aws_iam_user.backup_reader[0].name
}

//==============================================================================
// Configure the outputs.
// -----------------------------------------------------------------------------
// The secrets are stored in the Terraform state, which is kept encrypted in
// the stanford-infra bucket. Read one with, for example:
// terraform output -raw backup_writer_secret_access_key
//==============================================================================

output "backup_bucket_name" {
  value = aws_s3_bucket.backups.bucket
}

output "backup_writer_access_key_id" {
  value = aws_iam_access_key.backup_writer.id
}

output "backup_writer_secret_access_key" {
  value     = aws_iam_access_key.backup_writer.secret
  sensitive = true
}

output "backup_reader_access_key_id" {
  value = one(aws_iam_access_key.backup_reader[*].id)
}

output "backup_reader_secret_access_key" {
  value     = one(aws_iam_access_key.backup_reader[*].secret)
  sensitive = true
}
