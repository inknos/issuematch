# OpenShift Deployment

Manifests for deploying IssueMatch on an OpenShift cluster with
internal-only routing.

## Architecture

```
Browser (VPN/internal network)
  |
  v
internal-router-shard (edge TLS termination)
  |  (plain HTTP)
  v
Service issuematch:9473
  |
  v
Deployment issuematch (uvicorn on port 9473)
  |
  v
PostgreSQL (Crunchy PGO operator)
```

The namespace's NetworkPolicy only allows ingress from the
`internal-router-shard` IngressController. Traffic from the `default`
(external) router is blocked. Two things are required for internal routing:

1. The Route must carry the label `shard: internal`.
2. The Route's `spec.host` must include the `.int.` subdomain
   (e.g. `<name>.apps.int.<cluster-domain>`).

The internal router serves on `*.apps.int.<cluster-domain>` and resolves
to an internal IP, so you need VPN or internal network access to reach the
application.

**Important:** Deploy to a `--runtime-int` namespace (type `runtime`,
security zone `internal`), not a `--pipeline` namespace. The internal
router shard only serves routes in internal runtime namespaces. You can
verify namespace configuration via `TenantNamespace` resources in the
`--config` namespace.

## Prerequisites

### Secrets

Two secrets must exist in the target namespace before applying the
manifests.

**issuematch-secrets** -- application secrets:

| Key                    | Description                                 |
|------------------------|---------------------------------------------|
| `github_client_id`     | GitHub OAuth App client ID                  |
| `github_client_secret` | GitHub OAuth App client secret              |
| `session_secret`       | Random string for session cookie signing    |
| `base_url`             | Public URL of the app (used for OAuth redirect) |

See `issuematch-secrets.yaml.example` for the template.

**inknos-issuematch-postgres-18-pguser-issuematch** -- created
automatically by the Crunchy PGO PostgreSQL operator. Contains `host`,
`port`, `user`, `password`, and `dbname` keys.

### PostgreSQL

A Crunchy PGO `PostgresCluster` must be running in the namespace (or
reachable cross-namespace). The Deployment references the PGO-managed user
secret above for database connectivity. Alembic migrations run
automatically on container startup (`alembic upgrade head`).

### Container Image

The Deployment pulls `ghcr.io/inknos/issuematch`. Ensure the namespace
has pull access to this registry (e.g. via an image pull secret or public
access).

## Manifests

`issuematch-app.yaml` contains four resources:

| Resource    | Kind       | Name                        | Purpose                              |
|-------------|------------|-----------------------------|--------------------------------------|
| ConfigMap   | v1         | `issuematch-init-sql`       | SQL init script for database grants  |
| Deployment  | apps/v1    | `issuematch`                | Application pod (uvicorn, port 9473) |
| Service     | v1         | `issuematch`                | ClusterIP service exposing port 9473 |
| Route       | route.openshift.io/v1 | `inknos-issuematch-route-1` | Edge-terminated TLS route via internal router |

The Route uses `shard: internal` label and a `spec.host` on the
`.apps.int.<cluster-domain>` domain to target the internal router shard.

## Deploying

```bash
# Switch to your runtime-int namespace
oc project <tenant>--runtime-int

# Create the application secret (from your own values, NOT the example file)
oc create secret generic issuematch-secrets \
  --from-literal=github_client_id=... \
  --from-literal=github_client_secret=... \
  --from-literal=session_secret=... \
  --from-literal=base_url=...

# Apply all manifests
oc apply -f oc/issuematch-app.yaml
```

## Verification

```bash
# Pod should be Running 1/1
oc get pods -l app=issuematch

# Service should have endpoints
oc get endpoints issuematch

# Route should be admitted by internal-router-shard
oc get route inknos-issuematch-route-1
oc get route inknos-issuematch-route-1 -o jsonpath='{.status.ingress[*].routerName}'
# Expected output should include: internal-router-shard

# The host should be on the internal domain (*.apps.int.*)
oc get route inknos-issuematch-route-1 -o jsonpath='{.status.ingress[0].host}'
```

## Troubleshooting

| Symptom | Likely cause |
|---------|-------------|
| Pod stuck in `CreateContainerConfigError` | A referenced Secret does not exist |
| Pod in `CrashLoopBackOff` | Missing env var (check `oc logs`) or DB unreachable |
| Route returns 503 "Application is not available" | NetworkPolicy blocking the router -- check both the `shard: internal` label and the `.int.` host |
| Route only admitted by `default` | Missing `shard: internal` label or `spec.host` doesn't include `.int.` subdomain |
| Route has no host | IngressController did not admit the route; verify namespace is `--runtime-int` type |
| Deployed to `--pipeline` namespace | Move to `--runtime-int`; internal router only serves runtime namespaces |
