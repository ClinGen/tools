# `email_transfer_service`

This app is the Email Transfer Service (ETS), mounted at `/ets/` with the URL namespace
`ets`. It moves a GCI or VCI user's account from an old email to a new one by changing
the user pool in Cognito and the user records in DynamoDB. Only users with
`has_ets_permissions` can use it. "The Email Transfer Service" in `docs/design.md`
describes how a transfer works.

### `__init__.py`

Empty file that marks `email_transfer_service` as a Python package.

### `admin.py`

Registers `EmailTransfer` in the Django admin, with its history.

### `apps.py`

Configures the `email_transfer_service` app.

### `clients.py`

Wraps the boto3 Cognito and DynamoDB clients in `EtsClient`, with one method for each
AWS call a transfer makes: find a Cognito user or a DynamoDB user record by email,
retire a record, set a record's email, and disable or enable a Cognito user.
`EtsClient.from_settings()` builds one from the `ETS_` settings.

### `fakes.py`

Defines `FakeEtsClient`, which holds Cognito users and DynamoDB records in memory and
records each write, so tests never reach AWS. It can be told to fail a write.

### `forms.py`

Defines `TransferForm`, which takes the old and new emails. They must be valid, must
differ, and can't contain quotes or backslashes, which would break Cognito's filter.

### `models.py`

Defines `EmailTransfer`, one run of a transfer: the old and new emails, who ran it,
whether it was a dry run, its status, each step's result, and any error. Its slug is `T`
and a zero-padded number, such as `T000001`, and it keeps its change history.

### `templates/email_transfer_service/index.html`

The ETS's home page: the transfer form, and after a preview, either every failed
precondition or the steps the transfer will run and a button to confirm it.

### `templates/email_transfer_service/partials/dry_run.html`

The banner that says the ETS is in dry-run mode, shown while `ETS_DRY_RUN` is on.

### `test_transfers.py`

Tests the preconditions (each failure, the `requested activation` record, other
statuses, and an already-enabled new user) and the preview page.

### `tests.py`

Tests each `EtsClient` method against stubbed AWS clients, including DynamoDB pagination
and users that aren't found; the `EmailTransfer` slug and history; and that only users
with ETS permissions can open the home page.

### `transfers.py`

Checks a transfer's preconditions with `check_preconditions()`, which returns a
`Preview`: every failure, or a `Plan` whose `steps()` lists what the transfer will
change, naming the Cognito usernames and DynamoDB PKs.

### `urls.py`

Routes the ETS's pages under the `ets` namespace.

### `views.py`

Serves the ETS's home page to users with ETS permissions. Submitting the form previews
the transfer; AWS errors become error flash messages.
