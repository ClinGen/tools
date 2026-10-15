<div align=center>
<h1>ClinGen Tools</h1>

[Production Site](https://tools.clinicalgenome.org/) |
[Test Site](https://tools-test.clinicalgenome.org/)
</div>

ClinGen Tools is one Django web application that houses the internal tools the Stanford
ClinGen team builds and maintains. Keeping the tools in one application means one
codebase, one set of dependencies, one server, and one deployment to look after, instead
of one of each per tool.

- **Affiliations Service (AS)**, at [`/as/`](https://tools.clinicalgenome.org/as/): the
  source of truth for ClinGen affiliations (expert panels and working groups), with a
  REST API for other ClinGen tools and a UI for ClinGen staff.
- **ClinVar Submission Service (CSS)**, at
  [`/css/`](https://tools.clinicalgenome.org/css/): accepts ClinVar submissions from
  ClinGen clients through an API, forwards them to ClinVar, and tracks each one until
  ClinVar has processed it.
- **Email Transfer Service (ETS)**, at [`/ets/`](https://tools.clinicalgenome.org/ets/):
  moves a GCI/VCI user's account from an old email to a new one.

The landing page at [tools.clinicalgenome.org](https://tools.clinicalgenome.org/) links
to each tool. `docs/design.md` describes the design.

ClinGen Tools is maintained by the Stanford contingent of
[ClinGen](https://clinicalgenome.org).

## Getting Started

- Install [uv](https://github.com/astral-sh/uv).
- Install [Node.js](https://nodejs.org) (see `.nvmrc` for the version).
- Install [just](https://github.com/casey/just).
- Install [bd (Beads)](https://github.com/gastownhall/beads), which we use to track
  work.
- Clone the repository.
- Install JavaScript dependencies: `npm ci`.
- Install Python dependencies: `uv sync`.
- Copy `.env.example` to `.env` in the root of the repository and fill in the values.
  When you add or remove a key, change both files; `just env-check` reports any
  differences.
- Build the static assets: `just js-build`.
- Apply migrations: `just django-migrate`.
- Run the development server: `just django-runserver`.

Run `just --list` to see every recipe. `docs/how-to.md` covers infrastructure and
deployment.

## Contributing

You are welcome to submit a [bug report](https://github.com/ClinGen/tools/issues/new) or
a [pull request](https://github.com/ClinGen/tools/compare).
