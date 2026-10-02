# Linux examiner deployment

Docker Compose is the primary, reproducible Linux path. Native Bash is an optional Ubuntu/Debian path for researchers who accept host-level package installation. Do not run both modes against the same working directory at once.

## Package boundary

`Deploy/backend` and `Deploy/frontend` must contain the reviewed application snapshot. The package must not contain `.env`, virtual environments, database volumes, credentials, empirical/examiner data, restricted raw text, or model caches. Only explicitly labelled demo fixtures may be public. The scripts never seed empirical records.

## Docker Compose (preferred)

Target: a clean Ubuntu 22.04 or 24.04 x86-64 host with an ordinary sudo-enabled examiner account, at least 8 GB RAM, and at least 30 GiB free on Docker's storage filesystem before the first build (more may be needed for later evidence and empirical data). Run the scripts as that account, never as root. If Docker Engine and Compose v2 are absent, `bootstrap-docker.sh` installs them from Docker's official Ubuntu repository, enables the service, and adds the account to the `docker` group. This host-level installation requires internet access and one sign-out/sign-in before bootstrap is rerun. The Docker path uses container-pinned application runtimes, so it does not require the host's Python or PostgreSQL version. Bootstrap checks Docker's actual storage root and fails before building when the free-space requirement is unmet.

Do not use `chmod -R 777`. The bootstrap rejects a world-writable package. If files were copied as root, repair them first (replace `future` if the examiner account has another name):

```bash
sudo chown -R future:future /future
sudo find /future -type d -exec chmod 755 {} +
sudo find /future -type f -exec chmod 644 {} +
sudo find /future/deploy -type f -name '*.sh' -exec chmod 755 {} +
```

The top-level entry scripts require their executable bit. Internal bootstrap helpers are invoked explicitly through Bash so a Windows-origin copy cannot fail solely because a helper's executable metadata was lost.

```bash
cd Deploy
./deploy/linux/bootstrap-docker.sh
# When Docker was installed: sign out, sign in, return to this directory,
# and run bootstrap-docker.sh again.
# bootstrap creates .env with non-displayed random local secrets and builds images.
./deploy/linux/start-docker.sh
./deploy/linux/create-admin-docker.sh
./deploy/linux/health-docker.sh
./deploy/linux/stop-docker.sh
```

Repeated bootstrap/start/configure operations are safe. Bootstrap owns image construction; ordinary start uses only already-built/local images and therefore remains offline-capable after bootstrap. Migrations use `alembic upgrade head`; PostgreSQL and application data are named volumes and `stop` preserves them. Destructive volume deletion is deliberately absent.

### Database identity and validation boundary

A clean virtual machine does not guarantee an empty database after the demo smoke test has
been run. Docker named volumes survive stop/start, rebuilds, package replacement and normal
bootstrap reruns. The demo smoke workflow deliberately creates records titled `SYNTHETIC
DEMO` and those records must never coexist with, or be counted as, empirical validation
evidence.

Before beginning an empirical or historical-curriculum validation run:

1. Record the existing environment as the Phase 1 synthetic plumbing-test environment.
2. Use a separately named Compose project/database volume for the validation run, or have
   an authorised administrator perform a documented destructive reset after exporting any
   required test evidence.
3. Sign in and verify that curriculum documents, programmes, labour records, processing
   jobs, mappings, labels, forecasts and recommendations are all zero before uploading the
   first validation source.
4. Record the dataset purpose, time boundary and source manifest. A 2022 subject guide is
   historical 2022 curriculum evidence; it is not evidence of the current curriculum.

Do not delete a Docker volume merely to make a dashboard look clean. Volume deletion is a
destructive, separately authorised action. Do not run `deploy/smoke` against the validation
database.

For the 2022 Advanced Diploma validation, the existing synthetic environment can be
preserved non-destructively while a new database volume is selected:

```bash
cd /future
./deploy/linux/stop-docker.sh
sed -i 's/^COMPOSE_PROJECT_NAME=.*/COMPOSE_PROJECT_NAME=future_validation_2022/' .env
./deploy/linux/bootstrap-docker.sh
./deploy/linux/start-docker.sh
./deploy/linux/create-admin-docker.sh
./deploy/linux/health-docker.sh
```

The Compose project name must contain only lowercase letters, digits, hyphens or
underscores. Changing it changes the names of the PostgreSQL and backend-data volumes; it
does not erase the preserved `future_prototype` volumes. The validation project will
therefore start with a newly migrated database and require a newly created administrator.
Bootstrap must be rerun after changing the Compose project name because Compose assigns
project-scoped names to locally built images as well as to containers, networks and
volumes. The ordinary start script deliberately uses `--no-build` and cannot start a new
project until those image names exist.
Before any upload, confirm through the portal that all evidence and processing counts are
zero and capture that state. To return to the synthetic environment, stop the validation
project and restore `COMPOSE_PROJECT_NAME=future_prototype` before starting again.

`configure-docker.sh` may be run explicitly if `.env` needs to be created before bootstrap. It replaces only template `CHANGE_ME` values, preserves already configured values, restricts `.env` to the current account, and never prints the generated database password or signing key.
Placeholder validation examines active `KEY=value` assignments and ignores explanatory comments.

## Native Bash alternative

The alternative is deliberately bounded to Ubuntu 24.04, where PostgreSQL 16, pgvector and Python 3.12 packages are available from the standard repositories. It modifies the host and therefore requires `sudo`. Other distributions must use Docker Compose until a distribution-specific path is tested.

```bash
cd Deploy
./deploy/linux/bootstrap-native.sh
cp .env.example .env
# edit .env; never commit it
./deploy/linux/configure-native.sh
./deploy/linux/start-native.sh
./deploy/linux/create-admin-native.sh
./deploy/linux/health-native.sh
./deploy/linux/stop-native.sh
```

Native mode binds the API to loopback and serves the application through nginx on port 8080. Both deployment choices use local HTTP for examiner evaluation. A reviewed nginx/TLS configuration is required before network exposure; production publication requires a separate TLS and secret-management profile.

## Failure and evidence behaviour

Missing code, tools, secrets, failed Compose validation, failed migrations, unhealthy services, or unavailable pgvector stop the scripts with a non-zero exit. Logs and status may be inspected with `docker compose logs` / `docker compose ps` or `Deploy/run/backend.log`. Do not attach empirical input until the demo chain and the Phase 1 acceptance tests pass.
