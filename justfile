# Provides a simple way to run commands for this project.
#
# This file also documents command line "recipes" for this project. In order to use it,
# you must install the `just` program: https://github.com/casey/just.
#
# To list the available recipes and what they do, invoke `just -l` at the command line.
# (The dashes after the comment describing the recipe are there to help the formatting
# of the output of the `just -l` command.)
#
# NOTE: For the sake of simplicity, we assume the user of this justfile is invoking the
# recipes from the root of the repository.

# Load the .env file before we run commands.
set dotenv-load := true

#=====================================================================
# Pre-Commit Recipe
#=====================================================================

# Run all checks and tests. ------------------------------------------
pre-commit: env-check src-all test-all infra-all
alias pre := pre-commit

#=====================================================================
# Continuous Integration Recipe
#=====================================================================

# Run all checks and tests that are run in CI. -----------------------
continuous-integration: env-check py-format-check js-format-check py-lint js-lint py-type-check django-check django-collectstatic test-all
alias ci := continuous-integration

#=====================================================================
# Python Recipes
#=====================================================================

# Run all Python code quality checks. --------------------------------
[group('python')]
py-all: py-format-check py-lint py-type-check
alias pyal := py-all

# Format the Python code. --------------------------------------------
[group('python')]
py-format:
    uv run ruff format
alias pyfm := py-format

# Check the Python code for formatting issues. -----------------------
[group('python')]
py-format-check:
    uv run ruff format --check
alias pyfc := py-format-check

# Check the Python code for lint errors. -----------------------------
[group('python')]
py-lint:
    uv run ruff check
alias pylt := py-lint

# Try to fix lint errors in the Python code. -------------------------
[group('python')]
py-lint-fix:
    uv run ruff check --fix
alias pylf := py-lint-fix

# Check Python type hints. -------------------------------------------
[group('python')]
py-type-check:
    cd src && uv run ty check
alias pytc := py-type-check

#=====================================================================
# JavaScript Recipes
#=====================================================================

# Run all JavaScript checks. -----------------------------------------
[group('javascript')]
js-all: js-format-check js-lint
alias jal := js-all

# Format JavaScript code. --------------------------------------------
[group('javascript')]
js-format:
    npx biome format --write .
alias jsfm := js-format

# Check the JavaScript code for formatting issues. -------------------
[group('javascript')]
js-format-check:
    npx biome format .
alias jsfc := js-format-check

# Check the JavaScript code for lint errors. -------------------------
[group('javascript')]
js-lint:
    npx biome lint .
alias jslt := js-lint

# Try to fix lint errors in the JavaScript code. ---------------------
[group('javascript')]
js-lint-fix:
    npx biome lint --write .
alias jslf := js-lint-fix

# Build our JavaScript dependencies. ---------------------------------
[group('javascript')]
js-build:
    node build.js
alias jsbl := js-build

#=====================================================================
# Combined Source Code Recipes
#=====================================================================

# Run all source code checks. ----------------------------------------
[group('src')]
src-all: src-format-check src-lint src-type-check src-build
alias sal := src-all

# Format the source code. --------------------------------------------
[group('src')]
src-format: py-format js-format
alias sfm := src-format

# Check the source code for formatting issues. -----------------------
[group('src')]
src-format-check: py-format-check js-format-check
alias sfc := src-format-check

# Check the source code for lint errors. -----------------------------
[group('src')]
src-lint: py-lint js-lint
alias slt := src-lint

# Try to fix lint errors in the source code. -------------------------
[group('src')]
src-lint-fix: py-lint-fix js-lint-fix
alias slf := src-lint-fix

# Check source code types. -------------------------------------------
[group('src')]
src-type-check: py-type-check
alias stc := src-type-check

# Run source code build steps. ---------------------------------------
[group('src')]
src-build: js-build
alias sbl := src-build

#=====================================================================
# Test Recipes
#=====================================================================

# Run all tests. -----------------------------------------------------
[group('test')]
test-all:
    uv run pytest -n auto
alias tal := test-all

#=====================================================================
# Coverage Recipes
#=====================================================================

# Collect new coverage, build new site, and open new site. -----------
[group('coverage')]
coverage-new: coverage-clean coverage-collect coverage-build-html coverage-open-html
alias cnw := coverage-new

# Collect test coverage stats. ---------------------------------------
[group('coverage')]
coverage-collect:
    uv run coverage run -m pytest
alias cco := coverage-collect

# Print test coverage stats. -----------------------------------------
[group('coverage')]
coverage-report:
    uv run coverage report
alias crp := coverage-report

# Build the test coverage site. --------------------------------------
[group('coverage')]
coverage-build-html:
    uv run coverage html
alias cbh := coverage-build-html

# Open the test coverage site in your browser. -----------------------
[group('coverage')]
coverage-open-html:
    open coverage/index.html
alias coh := coverage-open-html

# Remove test coverage artifacts. ------------------------------------
[group('coverage')]
coverage-clean:
    rm -rf coverage.db coverage/
alias ccl := coverage-clean

#=====================================================================
# Django Recipes
#=====================================================================

# Inspect the project for common problems. ---------------------------
[group('django')]
django-check:
    cd src && uv run manage.py check
alias djch := django-check

# Collect static files. ----------------------------------------------
[group('django')]
django-collectstatic: js-build
    rm -rf src/public/
    cd src && uv run manage.py collectstatic --noinput
alias djcs := django-collectstatic

# Make migrations. ---------------------------------------------------
[group('django')]
django-makemigrations:
    cd src && uv run manage.py makemigrations
alias djmm := django-makemigrations

# Apply migrations. --------------------------------------------------
[group('django')]
django-migrate:
    cd src && uv run manage.py migrate
alias djmi := django-migrate

# Run the development server. ----------------------------------------
[group('django')]
django-runserver:
    cd src && uv run manage.py runserver
alias djru := django-runserver

# Enter the shell. ---------------------------------------------------
[group('django')]
django-shell:
    cd src && uv run manage.py shell
alias djsh := django-shell

#=====================================================================
# Docs Recipes
#=====================================================================

# Format the Markdown docs. ------------------------------------------
[group('docs')]
docs-format:
    uv run mdformat --wrap 88 --number docs src
alias dofm := docs-format

#=====================================================================
# Environment Recipes
#=====================================================================

# Check that .env and .env.example have the same keys. ---------------
[group('env')]
env-check:
    uv run scripts/env_check.py
alias envc := env-check

#=====================================================================
# Terraform Recipes
#=====================================================================

# Format the Terraform code. -----------------------------------------
[group('terraform')]
terraform-format:
    cd infra/terraform && terraform fmt
alias tffm := terraform-format

# Check the Terraform code for formatting issues. --------------------
[group('terraform')]
terraform-format-check:
    cd infra/terraform && terraform fmt -check
alias tffc := terraform-format-check

# Check the Terraform code for lint errors. --------------------------
[group('terraform')]
terraform-lint:
    cd infra/terraform && terraform validate
alias tflt := terraform-lint

#=====================================================================
# Ansible Recipes
#=====================================================================

# Format the Ansible YAML. -------------------------------------------
[group('ansible')]
ansible-format:
    cd infra/ansible && yamlfmt
alias anfm := ansible-format

# Check the Ansible YAML for formatting issues. ----------------------
[group('ansible')]
ansible-format-check:
    cd infra/ansible && yamlfmt -lint
alias anfc := ansible-format-check

# Check the Ansible YAML for lint errors. ----------------------------
[group('ansible')]
ansible-lint:
    cd infra/ansible && uv run ansible-lint
alias anlt := ansible-lint

# Try to fix lint errors in the Ansible YAML. ------------------------
[group('ansible')]
ansible-lint-fix:
    cd infra/ansible && uv run ansible-lint --fix
alias anlf := ansible-lint-fix

#=====================================================================
# Combined Infrastructure as Code Recipes
#=====================================================================

# Run all infra code quality checks. ---------------------------------
[group('infra')]
infra-all: infra-format-check infra-lint
alias ial := infra-all

# Format the infra code. ---------------------------------------------
[group('infra')]
infra-format: terraform-format ansible-format
alias ifm := infra-format

# Check the infra code for formatting issues. ------------------------
[group('infra')]
infra-format-check: terraform-format-check ansible-format-check
alias ifc := infra-format-check

# Check the infra code for lint errors. ------------------------------
[group('infra')]
infra-lint: terraform-lint ansible-lint
alias ilt := infra-lint

# Try to fix lint errors in infra code. ------------------------------
[group('infra')]
infra-lint-fix: ansible-lint-fix
alias ilf := infra-lint-fix

#=====================================================================
# Server Recipes
#=====================================================================

# Set up the test server for the first time. -------------------------
[group('server')]
server-test-init:
    cd infra/ansible && uv run ansible-playbook -i inventory.ini playbooks/init.yml --limit test_server
alias stei := server-test-init

# Set up the production server for the first time. -------------------
[group('server')]
server-prod-init:
    cd infra/ansible && uv run ansible-playbook -i inventory.ini playbooks/init.yml --limit prod_server
alias spri := server-prod-init

# Deploy latest changes to the test server. --------------------------
[group('server')]
server-test-deploy:
    cd infra/ansible && uv run ansible-playbook -i inventory.ini playbooks/deploy.yml --limit test_server
alias sted := server-test-deploy

# Deploy latest changes to the production server. --------------------
[group('server')]
server-prod-deploy:
    cd infra/ansible && uv run ansible-playbook -i inventory.ini playbooks/deploy.yml --limit prod_server
alias sprd := server-prod-deploy
