# ClinGen Tools Design Doc

## Context and Scope

ClinGen Tools is a web application built by the Stanford University ClinGen team. It
houses the team's internal tools in one Django project, served from
tools.clinicalgenome.org:

- **Affiliations Service (AS)**, at `/as/`: replaces `affiliations-service`
  (as.clinicalgenome.org).
- **ClinVar Submission Service (CSS)**, at `/css/`: replaces
  `clinvar-submission-service`.
- **Email Transfer Service (ETS)**, at `/ets/`: new; it replaces nothing.

The landing page at `/` links to each tool.

Before this project, each tool was its own Django application with its own repository,
server, and deployment. The AS and the CSS share the same stack, the same dependencies,
and most of the same supporting code (authentication, shared views, templates, and
infrastructure), all adapted from the HLA Curation Interface (HCI). Keeping them apart
meant making every dependency upgrade, security fix, and infrastructure change once per
tool.

This document is for engineers who are new to the codebase and for product owners who
want to understand the system's architecture and key design decisions. It covers what
the tools share and how they're kept apart. Each tool's own domain design (the AS's
affiliation model and legacy JSON format, the CSS's submission lifecycle and poller)
carries over from its standalone repository's `docs/design.md` unless this document
says otherwise.

## Goals

- Run every internal tool from one codebase, one set of dependencies, one server, and
  one deployment.
- Give each tool a stable URL prefix, so a tool's links and API base URL don't depend on
  which other tools exist.
- Keep each tool's code separate enough that a change to one tool can't break another
  without also changing shared code.
- Let ClinGen staff find every tool from one landing page.
- Run reliably on minimal infrastructure, using the same setup as the HCI.

## Non-Goals

- ClinGen Tools is not a home for public, curator-facing applications like the HCI.
  Those have their own users, uptime needs, and release schedules.
- The tools don't share domain data. Each tool owns its models; a shared app holds only
  supporting code such as authentication and common views.
- We don't keep the standalone AS deployment running once the AS has moved here. The
  standalone CSS was never deployed to production.

## Design

### System Context

ClinGen Tools is a single Django application on a single server. Caddy terminates TLS
for tools.clinicalgenome.org and proxies every request to Gunicorn, and Django routes
each request to a tool by its path prefix. Caddy doesn't know about the tools.

Each tool keeps the external integrations it had as a standalone service:

- **AS**: other ClinGen tools (the GCI, the VCI, and others) read and write affiliation
  data through its REST API. The Group and Personnel Management (GPM) system at UNC
  links to affiliations by UUID.
- **CSS**: ClinGen clients send submissions through its API, and the CSS forwards them
  to the NCBI ClinVar Submission API.
- **ETS**: reads and changes user accounts in the Gene Curation Interface (GCI) and
  the Variant Curation Interface (VCI). Those accounts live in two places: an AWS
  Cognito user pool, which handles sign-in, and the `GeneVariantCuration` DynamoDB
  table, which holds each user's record. The ETS calls both through boto3.

### Application Architecture

ClinGen Tools is a standard Django monolith, like the HCI. Server-rendered templates
are the UI, with HTMX where a page needs a little interactivity.

**Key libraries:**

- **Web framework**: Django
- **WSGI server**: Gunicorn
- **Database**: SQLite
- **Static files**: WhiteNoise (compressed, fingerprinted)
- **Backups**: django-dbbackup, to S3
- **Audit history**: django-simple-history
- **Error monitoring**: Sentry
- **Frontend CSS**: Bulma
- **Partial page updates**: HTMX
- **Authentication**: Clerk + custom `ClerkBackend`
- **API framework**: Django Ninja
- **AWS client (ETS)**: boto3

Every tool's API uses Django Ninja, as the CSS's already does. The standalone AS used
Django REST Framework, so porting it means rewriting its API in Ninja. Its URLs and
response formats, including the legacy JSON format, must stay the same apart from the
new `/as/` prefix, so that clients only have to change their base URL.

### URL Layout

`src/config/urls.py` mounts each tool's URLconf under its prefix, with a namespace
matching the prefix:

- `/`: the landing page (`core`).
- `/as/`: the AS UI. Its API lives under `/as/api/`.
- `/css/`: the CSS UI. Its API lives under `/css/api/`.
- `/ets/`: the ETS.
- `/admin/`: the Django admin, shared by every tool.

Because every tool lives under a prefix, templates and views must build URLs with
`{% url %}` and `reverse()` and never hard-code paths.

### Project Layout

The layout follows the HCI. Python code lives in `src/`, and tooling lives at the root.
`as` is a Python keyword, and `css` is easy to confuse with stylesheets, so Django apps
are named for what they hold rather than for a tool's abbreviation.

Shared apps:

- `src/config/`: URL routing, WSGI entry point, and layered settings (`base`, `dev`,
  `test`, `prod`).
- `src/auth_/`: authentication, `UserProfile`, and permission mixins.
- `src/common/`: shared views, tables, history diffing, template partials, and test
  mixins.
- `src/core/`: the landing page and other pages that belong to no tool.
- `src/templates/` and `src/static/`: the base layout, error pages, and vendored assets.

Tool apps:

- `src/affiliations_service/`: the AS.
- `src/clinvar_submission_service/`: the CSS, including its `poll_clinvar` command.
- `src/email_transfer_service/`: the ETS.

A tool may grow more than one app; prefix the extra apps' names so they sort with the
tool's main app. A tool app may import from shared apps but never from another tool's
app. If two tools need the same code, move it into a shared app.

### Data Model

All tools share one SQLite database. Each tool's tables are prefixed with its app label,
so they can't collide. No tool has a foreign key to another tool's models. If that ever
seems necessary, the data probably belongs in a shared app, and that's a design
decision worth recording here first.

Every model carries full change history via `django-simple-history`.

### Authentication and Authorization

Staff sign in once and can then use every tool they've been granted. Permissions are
per tool: being able to manage affiliations doesn't mean being able to resend ClinVar
submissions. Each tool's views check its own permission through the mixins in `auth_`.

Staff sign in with Clerk, the identity provider every ClinGen app is moving to. `auth_`
follows the CSS: sign-in uses Clerk's embedded widget, and a custom `ClerkBackend`
verifies the Clerk session on each request. The Django admin keeps Django's own staff
logins.

Machine clients use API keys, as they did with the standalone services. A key belongs to
one tool: an AS key can't call the CSS API. Keys are hashed at rest, and staff manage
them in the Django admin.

### The Email Transfer Service

Sometimes a GCI or VCI user needs to move their account from an old email to a new one.
By then, they've usually signed in with the new email, so both emails have a Cognito
user. The old email also has a DynamoDB user record, which holds the user's history. The
new email has either no record or one with `user_status` set to
`requested activation`. The transfer keeps the old record and points it at the new
email.

Before the ETS, a developer ran a script by hand to do this. The ETS turns that script
into a form ClinGen staff can use on their own. A transfer has three steps:

1. Staff enter the old and new emails.
2. The ETS checks the preconditions and shows the changes it would make, without making
   them. The preconditions are:
   - The old email has a Cognito user and a DynamoDB record.
   - The new email has a Cognito user.
   - The new email has no DynamoDB record, or one with `user_status` set to
     `requested activation`.
3. If staff confirm, the ETS makes the changes, in this order:
   1. If the new email has a `requested activation` record, retire it: set its `email`
      to `email.do.not.match`, its `user_status` to `inactive`, and its `status` to
      `deleted`.
   2. Set the `email` on the old email's DynamoDB record to the new email.
   3. Disable the old email's Cognito user.
   4. Enable the new email's Cognito user, if it isn't already enabled.

If a precondition fails, the ETS shows why and makes no changes. There's no override:
the script's `--force` flag, which skipped the `requested activation` check, has no
equivalent in the ETS. A transfer that doesn't meet the preconditions needs a
developer.

Cognito and DynamoDB can't be changed in one transaction, so a transfer can fail
partway through. The ETS saves each transfer as an `EmailTransfer` record before it
starts, and records each step's result as it goes. When a step fails, the ETS stops and
the record shows which steps finished, so staff can see what's left to fix. Like every
model, `EmailTransfer` keeps its change history, so there's a record of who transferred
which email and when.

The ETS reads its AWS credentials, region, user pool ID, and table name from the
environment, never from code. The credentials should belong to an IAM user that can do
only what a transfer needs: list, enable, and disable users in the one user pool, and
query and update items in the one table.

### Processes

Gunicorn serves every tool. The CSS also needs its poller, a long-running management
command (`poll_clinvar`) that checks ClinVar for status updates. It runs as its own
systemd service next to Gunicorn, and Ansible deploys and restarts it with the web
process. Any other tool that needs background work should follow the same pattern: a
management command run by systemd, not a task queue.

### Moving the Standalone Tools

Moving a standalone tool here means porting its code into its app, moving its data into
the shared database, and pointing its clients at the new base URL. Each move is its own
epic.

The AS is in production at as.clinicalgenome.org, so its clients need time to switch.
For six months after the move, as.clinicalgenome.org redirects each request to the same
path under tools.clinicalgenome.org/as/. The CSS was never in production, so it has no
old URLs to redirect.

## Alternatives Considered

### One Application per Tool

This is what we had: a repository, server, and deployment for each tool. It keeps the
tools fully isolated, so a bad deploy of one can't take down another. We gave it up
because the tools are small, share a stack, and are maintained by the same few people,
so the cost of maintaining each copy outweighed the isolation. The trade-off is that a
deploy or an outage now affects every tool at once.

### Separate Django Projects Behind One Caddy

Each tool could stay its own Django project on one shared server, with Caddy routing
each path prefix to that tool's Gunicorn. This saves on servers but not on maintenance:
there'd still be one set of dependencies, settings, and migrations per tool. One
project gets us the savings we want.

### Subdomains Instead of Path Prefixes

Each tool could have its own subdomain (as.tools.clinicalgenome.org, for example). Path
prefixes need only one DNS record and one TLS certificate, and they let staff sign in
once for every tool, so we chose them.

## Cross-Cutting Concerns

### Isolation Between Tools

Every tool runs in the same process and shares one database, so a slow query or a crash
in one tool affects the others. Tests for each tool must pass on their own, and
`just ci` runs every tool's tests on every change, including changes that touch only
one tool.

### Backups

Each server backs up its database to its own S3 bucket, as the HCI does. Every deploy
takes a backup just before it migrates; see `docs/how-to.md`. One database means one
backup covers every tool.

### Error Monitoring and Uptime

Sentry captures unhandled exceptions from every tool in one Sentry project. Each event
is tagged with the tool that raised it, so we can filter by tool. UptimeRobot monitors
the landing page and each tool's prefix separately, so an alert names the tool that's
down.
