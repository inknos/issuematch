# OpenShift Deployment

Manifests for deploying IssueMatch on an OpenShift cluster with
internal-only routing. Two environments are provided:

| Environment | Manifest prefix          | Image tag  |
|-------------|--------------------------|------------|
| Production  | `inknos-issuematch-`     | `v0`       |
| Development | `inknos-issuematch-dev-` | `latest`   |

## Architecture

```
Browser (VPN/internal network)
  |
  v
internal-router-shard (edge TLS termination)
  |  (plain HTTP)
  v
Service inknos-issuematch:9473
  |
  v
Deployment inknos-issuematch (uvicorn on port 9473)
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

**inknos-issuematch-secrets** (or **inknos-issuematch-dev-secrets** for
dev) -- application secrets:

| Key                | Description                              |
|--------------------|------------------------------------------|
| `session_secret`   | Random string for session cookie signing |
| `admin_username`   | Initial admin account username           |
| `admin_password`   | Initial admin account password           |

See `inknos-issuematch-secrets.yaml.example` (or
`inknos-issuematch-dev-secrets.yaml.example`) for the template.

**inknos-issuematch-postgres-18-pguser-issuematch** (or
**inknos-issuematch-dev-postgres-18-pguser-issuematch** for dev) --
created automatically by the Crunchy PGO PostgreSQL operator. Contains
`host`, `port`, `user`, `password`, and `dbname` keys.

### PostgreSQL

A Crunchy PGO `PostgresCluster` must be running in the namespace (or
reachable cross-namespace). The Deployment references the PGO-managed user
secret above for database connectivity. Alembic migrations run
automatically on container startup (`alembic upgrade head`).

### HTTP Proxy

The `--runtime-int` namespace blocks direct outbound connections to the
public internet. The Deployments include `HTTPS_PROXY` / `HTTP_PROXY` env
vars pointing to the DIS Squid Proxy
(`proxy.squi-001.prod.iad2.dc.redhat.com:3128`). `NO_PROXY` is set to
`.svc,.cluster.local,localhost,127.0.0.1` so that in-cluster traffic
(e.g. to PostgreSQL) bypasses the proxy. `httpx` honours these env vars
automatically.

### Container Image

The Deployment pulls `ghcr.io/inknos/issuematch`. Production uses a
pinned tag (e.g. `:v0`), while development uses `:latest`. Ensure the
namespace has pull access to this registry (e.g. via an image pull secret
or public access).

## Manifests

### Init SQL (`inknos-issuematch-init-sql.yaml`) -- apply first

| Resource    | Kind | Name                              | Purpose                             |
|-------------|------|-----------------------------------|-------------------------------------|
| ConfigMap   | v1   | `inknos-issuematch-init-sql`      | SQL init script for database grants |
| ConfigMap   | v1   | `inknos-issuematch-dev-init-sql`  | SQL init script for database grants |

### Production (`inknos-issuematch-app.yaml`)

| Resource    | Kind                    | Name                          | Purpose                              |
|-------------|-------------------------|-------------------------------|--------------------------------------|
| Deployment  | apps/v1                 | `inknos-issuematch`           | Application pod (uvicorn, port 9473) |
| Service     | v1                      | `inknos-issuematch`           | ClusterIP service exposing port 9473 |
| Route       | route.openshift.io/v1   | `inknos-issuematch-route-1`   | Edge-terminated TLS route via internal router |

### Development (`inknos-issuematch-dev-app.yaml`)

| Resource    | Kind                    | Name                              | Purpose                              |
|-------------|-------------------------|-----------------------------------|--------------------------------------|
| Deployment  | apps/v1                 | `inknos-issuematch-dev`           | Application pod (uvicorn, port 9473) |
| Service     | v1                      | `inknos-issuematch-dev`           | ClusterIP service exposing port 9473 |
| Route       | route.openshift.io/v1   | `inknos-issuematch-dev-route-1`   | Edge-terminated TLS route via internal router |

Both Routes use `shard: internal` label and a `spec.host` on the
`.apps.int.<cluster-domain>` domain to target the internal router shard.

## Deploying

### Step 1: Switch to the runtime-int namespace

```bash
oc project <tenant>--runtime-int
```

### Step 2: Apply init SQL ConfigMaps

```bash
oc apply -f oc/inknos-issuematch-init-sql.yaml
```

Verify:

```bash
oc get configmaps -o name | grep issuematch
# Expected:
#   configmap/inknos-issuematch-init-sql
#   configmap/inknos-issuematch-dev-init-sql
```

### Step 3: Apply secrets

```bash
oc apply -f oc/inknos-issuematch-secrets.yaml
oc apply -f oc/inknos-issuematch-dev-secrets.yaml
```

Verify:

```bash
oc get secrets -o name | grep issuematch
# Expected:
#   secret/inknos-issuematch-secrets
#   secret/inknos-issuematch-dev-secrets
```

### Step 4: Create PostgreSQL clusters

Create the PGO `PostgresCluster` resources (prod cluster name
`inknos-issuematch-postgres-18`, dev cluster name
`inknos-issuematch-dev-postgres-18`, both with a user called
`issuematch`).

Verify:

```bash
oc get postgresclusters
# Expected:
#   inknos-issuematch-postgres-18
#   inknos-issuematch-dev-postgres-18

oc get secrets -o name | grep pguser
# Expected:
#   secret/inknos-issuematch-postgres-18-pguser-issuematch
#   secret/inknos-issuematch-dev-postgres-18-pguser-issuematch
```

### Step 5: Apply app manifests

```bash
oc apply -f oc/inknos-issuematch-app.yaml
oc apply -f oc/inknos-issuematch-dev-app.yaml
```

Verify:

```bash
# Production
oc get pods -l app=inknos-issuematch
oc get endpoints inknos-issuematch
oc get route inknos-issuematch-route-1

# Development
oc get pods -l app=inknos-issuematch-dev
oc get endpoints inknos-issuematch-dev
oc get route inknos-issuematch-dev-route-1
```

## MCP Server (Cursor integration)

The dev deployment exposes an MCP endpoint at `/mcp` (via
`fastapi-mcp`). To use it from Cursor, port-forward the dev service
locally:

```bash
oc port-forward svc/inknos-issuematch-dev 19473:9473
```

The MCP server is then available at `http://localhost:19473/mcp`.
Cursor picks up the connection config from `.cursor/mcp.json` in the
project root. A Bearer API token is required for authentication.

## Troubleshooting

| Symptom | Likely cause |
|---------|-------------|
| Pod stuck in `CreateContainerConfigError` | A referenced Secret does not exist |
| Pod in `CrashLoopBackOff` | Missing env var (check `oc logs`) or DB unreachable |
| Route returns 503 "Application is not available" | NetworkPolicy blocking the router -- check both the `shard: internal` label and the `.int.` host |
| Route only admitted by `default` | Missing `shard: internal` label or `spec.host` doesn't include `.int.` subdomain |
| Route has no host | IngressController did not admit the route; verify namespace is `--runtime-int` type |
| Deployed to `--pipeline` namespace | Move to `--runtime-int`; internal router only serves runtime namespaces |
