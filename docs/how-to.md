# How-To Guides

## How to Create and Destroy Cloud Infrastructure

- Configure your AWS credentials using the `~/.aws/credentials` file or using
  environment variables. ClinGen Tools uses two profiles: `stanford-clingen-projects`
  for the server and backups, and `route-53` for the clinicalgenome.org DNS records.
  See the AWS docs for more information.

- Install [Terraform](https://developer.hashicorp.com/terraform) if you don't have it
  installed.

- The first time anyone sets up ClinGen Tools, create the DynamoDB table that locks the
  Terraform state. It needs a string partition key named `LockID`:

  ```
  aws dynamodb create-table \
    --profile stanford-clingen-projects \
    --region us-west-2 \
    --table-name tools_terraform_lock \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST
  ```

- Create the SSH key pair that Ansible uses for the workspace. Terraform reads its
  public key. For the `test` workspace, run:

  ```
  ssh-keygen -t ed25519 -f ~/.ssh/tools_ansible_test_ed25519
  ```

- Go to the Terraform directory:

  ```
  cd infra/terraform
  ```

- If you don't have a `.terraform` directory, run:

  ```
  terraform init
  ```

- To see possible workspaces, run:

  ```
  terraform workspace list
  ```

- If you want to create or destroy infrastructure for the `foo` workspace, run:

  ```
  terraform workspace select foo
  ```

- If you want to create a new workspace named `bar`, run:

  ```
  terraform workspace new bar
  ```

  We use two workspaces: `test` (tools-test.clinicalgenome.org) and `prod`
  (tools.clinicalgenome.org).

- To create infrastructure, run:

  ```
  terraform apply
  ```

- To destroy infrastructure, run:

  ```
  terraform destroy
  ```

## How to Configure Backup Credentials

Each server backs up its database to its own S3 bucket. The bucket and the IAM users
that use it are created by `infra/terraform/backup.tf`. After you run `terraform apply`
in a workspace, give that workspace's server its credentials:

- In `infra/terraform`, select the workspace (`test` or `prod`) and read the outputs:

  ```
  terraform workspace select test
  terraform output backup_bucket_name
  terraform output backup_writer_access_key_id
  terraform output -raw backup_writer_secret_access_key
  ```

- SSH into that workspace's server and add these lines to the `.env` file in the root of
  the repository. Use `tools` for `SUBDOMAIN` on prod and `tools-test` on test. It's
  used in backup names.

  ```
  AWS_ACCESS_KEY_ID=<backup_writer_access_key_id>
  AWS_SECRET_ACCESS_KEY=<backup_writer_secret_access_key>
  DBBACKUP_BUCKET_NAME=<backup_bucket_name>
  SUBDOMAIN=tools-test
  ```

- Check that the server can reach the bucket. It should print an empty list, or the
  backups taken so far, with no error:

  ```
  cd ~/tools/src
  ~/.local/bin/uv run manage.py listbackups
  ```

The `prod` workspace also creates a read-only backup user for checking that backups
restore. Read `backup_reader_access_key_id` and `backup_reader_secret_access_key` from
the `prod` outputs when you set that check up.

## How to Set Up a Server for the First Time

- Create the cloud infrastructure for the server if you haven't already done so.

- Copy `infra/ansible/inventory.example.ini` to `infra/ansible/inventory.ini` and fill
  in the server IP addresses. Git ignores `inventory.ini`.

- To set up the test site, run the following command from the root of the repository:

  ```
  just server-test-init
  ```

- To set up the production site, run the following command from the root of the
  repository:

  ```
  just server-prod-init
  ```

- If a task fails during initialization, it's usually easier to SSH in and fix it
  manually than to futz with Ansible tasks.

- Make sure to add the Ansible SSH key to the `authorized_keys` file.

## How to Manually Deploy ClinGen Tools

If you need to deploy ClinGen Tools by hand, follow the steps below. Every tool is
deployed at once; there's no way to deploy one tool on its own.

- Create the cloud infrastructure for the server if you haven't already done so.

- Set up the server if you haven't already done so.

- To deploy the test site, run the following command from the root of the repository:

  ```
  just server-test-deploy
  ```

- To deploy the production site, run the following command from the root of the
  repository:

  ```
  just server-prod-deploy
  ```

Every deploy backs up the database just before it migrates. The deploy output prints
the backup's name, for example:

```
Pre-deployment backup: pre-deployment/tools-3f2a9c1-to-88c5e47-2026-09-25T180102Z.sqlite3.gz
```

The first SHA is the code the backup's data matches, and the second is the code being
deployed. If the backup fails, the deploy stops before it migrates, so the server needs
its backup credentials first (see How to Configure Backup Credentials).
