---
name: java-delivery
pack: java
description: >-
  Build, ship, and operate the Quarkus backend: Maven Wrapper and parent POM setup, enforcer
  and Spotless and JaCoCo and dependency-check plugins, CI pipeline stages and quality gates,
  environment promotion, semantic versioning and changelogs, systemd and container
  deployment, secret delivery, health probes, and rollback strategy. Use when setting up or
  fixing a build, adding a CI stage, preparing a release, deploying to staging or production,
  writing a runbook, or planning a rollback. Do not use for application security in code
  (quarkus-security) or runtime telemetry design (quarkus-observability).
keywords: build, maven, mvnw, pom, ci, cd, pipeline, deploy, deployment, release, versioning, rollback, docker, container, systemd, artifact, staging, production, runbook, enforcer
---

# Java Delivery

Full rules: `.agents/standards/java/build-ci.md`. This is the workflow.

## Use when
- Setting up or fixing the Maven build
- Adding or debugging a CI stage
- Preparing a release
- Deploying to staging or production
- Writing a runbook or planning a rollback

---

## Build setup

The wrapper is committed and is the only supported entry point:

```bash
./mvnw verify        # not: mvn verify
```

Developer machines and CI runners do not reliably have Maven, and when they do the versions
differ. On this machine, for example, Java 21 is present but `mvn` is not — the wrapper is
what makes the build work anyway.

### Parent POM essentials

```xml
<properties>
  <maven.compiler.release>21</maven.compiler.release>
  <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  <quarkus.platform.version>3.33.3.2</quarkus.platform.version>
  <jacoco.line.min>0.80</jacoco.line.min>
</properties>
```

Every version pinned. No ranges, no `LATEST`. A build today and a build in three months
produce the same artifact.

### Plugins that gate the build

| Plugin | Gate |
|---|---|
| `maven-enforcer-plugin` | Java 21, `dependencyConvergence`, no duplicate versions |
| `spotless-maven-plugin` | Formatting |
| `jacoco-maven-plugin` | Coverage thresholds |
| `dependency-check-maven` | CVSS ≥ 7 |
| `maven-failsafe-plugin` | Integration tests (`*IT`) |
| `spotbugs-maven-plugin` | High-priority static findings |

`dependencyConvergence` is the one people want to disable first. What it prevents is two
libraries pulling different versions of the same transitive dependency, producing a
`NoSuchMethodError` in production on a rarely-exercised path.

---

## Pipeline

```
push / MR
  |- build       ./mvnw -B verify -DskipITs      (~2 min)
  |- format      ./mvnw spotless:check
  |- unit        ./mvnw test + JaCoCo gate
  |- integration ./mvnw verify -Pit              (Testcontainers, needs Docker)
  |- openapi     generate + diff vs docs/openapi/ -> fail on difference
  |- security    dependency-check + secret scan
  \- package     JAR + image (main only)
```

Nightly: OWASP database refresh, k6 load tests, dependency update report.

Rules:
- **A red job blocks the merge.** Not "we'll fix it after".
- Full pipeline under 10 minutes. Beyond that people find shortcuts around it.
- Cache `~/.m2`; use `-B` so logs stay readable.

### Verify Docker on the runner before Stage 2

Integration tests need Testcontainers, which needs Docker. `[PENDING CLIENT]` — confirm the
client's GitLab/Jenkins runner permits it. If it does not, that changes the test strategy,
and it must be known before development starts, not discovered during Stage 4 when the
integration environment is being assembled.

---

## Environments

| Env | Source | Database | Deploy |
|---|---|---|---|
| `dev` | Local, Dev Services | Throwaway container | — |
| `test` | CI | Testcontainers | Automatic per MR |
| `staging` | `main` | Separate PostgreSQL | Automatic |
| `prod` | `v*` tag | Production PostgreSQL | **Manual approval** |

**The same artifact goes to staging and production.** Differences come only from environment
variables. If production rebuilds from source, what was tested in staging is not what
shipped.

## Releases

Semantic versioning, tagged `v1.4.0`:

- `MAJOR` — breaking API contract change
- `MINOR` — new endpoints or features, compatible
- `PATCH` — bug fixes

Changelog generated from Conventional Commits (`git-workflow`).

Release checklist:

- [ ] Pipeline green on `main`
- [ ] Migrations tested against a copy of production data
- [ ] OpenAPI spec regenerated and committed
- [ ] No CVSS ≥ 7 findings
- [ ] Previous artifact retained and redeployable
- [ ] Runbook updated if operational behaviour changed
- [ ] Rollback path confirmed (see below)

---

## Deployment

`[PENDING CLIENT]` — the client's DevOps sets the target. Two supported shapes.

**systemd**, as in the demo:

```ini
[Unit]
Description=Application API
After=network.target postgresql.service

[Service]
User=app
ExecStart=/usr/bin/java -jar /opt/app/app-api.jar
EnvironmentFile=/etc/app/api.env     # chmod 600, root:app — secrets live here
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Container:**

```dockerfile
FROM registry.access.redhat.com/ubi9/openjdk-21-runtime:latest
COPY --chown=185 target/quarkus-app/lib/      /deployments/lib/
COPY --chown=185 target/quarkus-app/*.jar     /deployments/
COPY --chown=185 target/quarkus-app/app/      /deployments/app/
COPY --chown=185 target/quarkus-app/quarkus/  /deployments/quarkus/
EXPOSE 8080
USER 185
ENTRYPOINT ["java", "-jar", "/deployments/quarkus-run.jar"]
```

Copy the four `quarkus-app` directories separately so Docker layer caching works — the
`lib/` layer changes rarely, application code changes on every build.

Run as non-root. Secrets come from the environment or a secret manager, **never** baked into
an image — an image layer keeps them even after a later layer deletes the file.

### Probes

```
startupProbe    /q/health/started    generous timeout; JVM startup is not instant
livenessProbe   /q/health/live       process only, no dependency checks
readinessProbe  /q/health/ready      DB, storage, dependent services
```

A liveness probe that checks the database will restart every instance when the database has
a hiccup, turning a recoverable incident into an outage (`quarkus-observability`).

---

## Rollback

Every release must be reversible before it is released.

**Application rollback:** redeploy the previous artifact. This only works if the previous
artifact still exists and if the database schema it expects is still valid.

**That is why migrations are backward-compatible by one release:**

```
Release N:    add the new column, write to both old and new, read from old
Release N+1:  read from the new column
Release N+2:  drop the old column
```

Dropping a column in the same release that stops using it means release N+1 cannot be rolled
back — the old code would query a column that no longer exists. Spreading it over three
releases costs almost nothing and keeps rollback available at every point.

**Database rollback is not a plan.** Restoring a production database loses every transaction
since the backup. Design so that the application can go back without the database having to.

### Rollback runbook

1. Confirm the symptom is caused by the release (check `traceId`s and metrics, not
   intuition).
2. Redeploy the previous tag.
3. Verify readiness and the error rate returning to baseline.
4. Only then investigate — with the system already stable.
5. Record what happened in `docs/adr/` if it changes a decision.

---

## Pitfalls

| Pitfall | Consequence |
|---|---|
| `mvn` instead of `./mvnw` | Different Maven version, non-reproducible build |
| Unpinned dependency versions | Build output changes without a code change |
| Rebuilding for production | What shipped is not what was tested |
| Secrets in an image | Retained in layer history even after deletion |
| Liveness checking the DB | A database hiccup becomes a full outage |
| Dropping a column too early | Rollback impossible |
| No retained previous artifact | Rollback impossible |
| Pipeline over 10 minutes | People route around the gates |
