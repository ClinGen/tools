# How-To Guides

## How to Create and Destroy Cloud Infrastructure

- Configure your AWS credentials using the `~/.aws/credentials` file or using
  environment variables. ClinGen Tools uses two profiles: `stanford-clingen-projects`
  for the server and backups, and `route-53` for the clinicalgenome.org DNS records. See
  the AWS docs for more information.

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

Initialization starts two systemd services: `gunicorn.service`, which serves every tool,
and `poll-clinvar.service`, the CSS's ClinVar poller. To check on the poller, SSH in and
run `systemctl status poll-clinvar` or `journalctl -u poll-clinvar`.

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

Every deploy backs up the database just before it migrates. The deploy output prints the
backup's name, for example:

```
Pre-deployment backup: pre-deployment/tools-3f2a9c1-to-88c5e47-2026-09-25T180102Z.sqlite3.gz
```

The first SHA is the code the backup's data matches, and the second is the code being
deployed. If the backup fails, the deploy stops before it migrates, so the server needs
its backup credentials first (see How to Configure Backup Credentials).

Every deploy restarts Gunicorn and the ClinVar poller. The poller finishes the batch
it's polling before it stops.

## How to Load Sample CSS Records and Batches Locally

- Apply the migrations:

  ```
  just django-migrate
  ```

- Load the test fixtures:

  ```
  just django-loaddata-test
  ```

  This adds a VCI API key, records from five affiliations, and eight batches of them.
  Two batches never reached ClinVar (`not_sent_to_clinvar` and
  `send_to_clinvar_failed`), and six were sent (`submitted_to_clinvar`,
  `processing_at_clinvar`, `processed_by_clinvar`, and `error_at_clinvar`). Records are
  in every status: some wait for a batch, one was withdrawn, some are in a batch, and
  some ClinVar accepted, with SCVs. One record failed in an earlier batch and was
  retried in a later one, and one failed and is waiting again. Two affiliations have
  ClinVar settings. The affiliation IDs and ClinVar IDs are made up, and none of the
  batches is due to poll, so a local poller leaves them alone. The API key has no raw
  value, so it can't call the API; create a key in the Django admin for that.

- Open `/css/` to see them. Loading the fixtures again resets them: it deletes every CSS
  batch, record, and affiliation setting first, including ones you made in the UI, but
  keeps API keys.

## How to Try the CSS Workflow Locally

This sends dummy records to your local CSS, as the VCI would, and has a simulated
ClinVar accept and process the batches you send, so nothing reaches the VCI or ClinVar.

- Make an API key for the dummy records. Run `just django-runserver`, open
  `/admin/clinvar_submission_service/apikey/add/`, name it `Dummy VCI`, and save. Copy
  the key from the message at the top of the page; it's shown only once.
- In `.env`, set:

  ```
  CSS_DUMMY_API_KEY=<the key>
  CSS_SIMULATE_CLINVAR=1
  ```

- Restart the development server, so it reads `.env`:

  ```
  just django-runserver
  ```

  Every CSS page now says ClinVar is simulated.

- In a second terminal, run the poller:

  ```
  just django-poll-clinvar
  ```

  While ClinVar is simulated, it checks every few seconds instead of every few minutes.

- In a third terminal, send some dummy records:

  ```
  just css-send-dummy-records --count 10
  ```

  Add `--resend` to send about half of them again with a new classification, which
  replaces the waiting records and keeps the old versions in their history.

- Open `/css/records/` to see the records waiting for a batch.
- Open `/css/affiliations/`, click an affiliation's gear, and set its assertion
  criteria, such as PubMed 25741868. A batch takes these settings when it's made.
- On `/css/records/`, pick that affiliation in the select and click **New Batch**. Pick
  records, or click **Add Every Waiting Record**, review them, and click **Send to
  ClinVar**.
- On the batch's page, watch it move from Submitted to Processing to Processed or Error
  as the poller checks on it. Reload to see each step. Most records get Success with a
  made-up SCV; the rest get Error and go back to waiting, ready for a later batch.
- About one send in ten fails on purpose, so the batch shows Send Failed. Click
  **Resend** on its page to try again.
- To stop simulating, empty `CSS_SIMULATE_CLINVAR` in `.env` and restart the server and
  the poller. To clear the records and batches, run `just django-loaddata-test`, which
  replaces them with the sample fixture.
