# Build & CI/CD

## Maven Wrapper — mandatory

```bash
./mvnw verify        # not: mvn verify
```

The wrapper (`mvnw`, `mvnw.cmd`, `.mvn/wrapper/`) is **committed**. The reason is concrete:
developer machines and CI runners do not always have Maven installed, and when they do, the
versions differ. The wrapper makes everyone run the same Maven.

## Parent POM

```xml
<properties>
  <maven.compiler.release>21</maven.compiler.release>
  <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  <quarkus.platform.version>3.33.3.2</quarkus.platform.version>
  <jacoco.line.min>0.80</jacoco.line.min>
</properties>
```

**Every dependency version is pinned.** No version ranges, no `LATEST`. A build today and a
build in three months must produce the same artifact.

## Required plugins

| Plugin | Role | Fails the build when |
|---|---|---|
| `maven-enforcer-plugin` | `requireJavaVersion 21`, `dependencyConvergence`, `banDuplicatePomDependencyVersions` | Versions conflict |
| `spotless-maven-plugin` | google-java-format AOSP | Code is unformatted |
| `jacoco-maven-plugin` | Coverage | Below threshold |
| `dependency-check-maven` | OWASP CVEs | CVSS ≥ 7 |
| `maven-failsafe-plugin` | Integration tests (`*IT`) | Tests fail |
| `spotbugs-maven-plugin` | Static bug detection | High priority findings |

`dependencyConvergence` feels obstructive at first. What it prevents is two libraries
pulling different versions of the same dependency, and a `NoSuchMethodError` appearing in
production on a rarely-exercised code path.

## Pipeline

```
push / MR
  |- build       ./mvnw -B verify -DskipITs      (~2 min)
  |- format      ./mvnw spotless:check
  |- unit        ./mvnw test + JaCoCo gate
  |- integration ./mvnw verify -Pit              (Testcontainers, needs Docker)
  |- openapi     generate + diff vs docs/openapi/ -> fail on difference
  |- security    dependency-check + secret scan
  \- package     JAR + image (main branch only)
```

Nightly: OWASP database refresh, k6 load tests, dependency update report.

### Pipeline rules

- **Merges are blocked while any job is red.** Not "we'll fix it later".
- The full pipeline runs in under 10 minutes. Beyond that, people start finding shortcuts.
- Cache `~/.m2` between runs.
- Use `-B` (batch mode) so CI logs stay readable.

### The runner needs Docker

Integration tests use Testcontainers. `[PENDING CLIENT]` — confirm the client's runner
(GitLab/Jenkins) permits Docker. If it does not, that is a significant decision that must
be known **before** Stage 2, not during Stage 4.

## Environments

| Env | Source | Database | Deploy |
|---|---|---|---|
| `dev` | Local, Dev Services | Throwaway container | — |
| `test` | CI | Testcontainers | Automatic per MR |
| `staging` | `main` branch | Separate PostgreSQL | Automatic |
| `prod` | `v*` tag | Production PostgreSQL | **Manual approval** |

Per-environment differences come only from environment variables. **The artifact deployed
to staging and to production is the same file** — if it is rebuilt for production, what was
tested in staging is not what shipped.

## Release versioning

Semantic versioning: `MAJOR.MINOR.PATCH`, tagged `v1.4.0`.

- `MAJOR` — breaking change to the API contract
- `MINOR` — new endpoints or features, compatible
- `PATCH` — bug fixes

Every tag gets a changelog generated from Conventional Commits.

## Deployment

`[PENDING CLIENT]` — the target is set by the client's DevOps. Two supported shapes:

**systemd** (as in the demo):

```ini
[Service]
ExecStart=/usr/bin/java -jar /opt/app/app-api.jar
EnvironmentFile=/etc/app/api.env     # chmod 600, secrets live here
Restart=on-failure
```

**Container:**

```dockerfile
FROM registry.access.redhat.com/ubi9/openjdk-21-runtime:latest
COPY --chown=185 target/quarkus-app/ /deployments/
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/deployments/quarkus-run.jar"]
```

Run as non-root. Secrets come from the environment or a secret manager — **never** baked
into an image.

### Rollback

Every release must be reversible:

- The previous version's artifact is retained and redeployable.
- Flyway migrations are **forward-only and backward-compatible by one release**: do not
  drop a column in the same release that stops using it. Drop it in the next one.

That is what makes an application rollback possible without a database rollback — which
cannot be done safely against production data.
