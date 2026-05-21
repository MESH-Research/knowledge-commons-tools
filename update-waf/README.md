# update-waf

A small Python script plus shell wrapper that registers a container's egress
IP in an AWS WAFv2 IPSet at startup and removes it again on graceful
shutdown. The use case: when an ECS task needs to talk outwards through a
WAF-protected endpoint, the WAF has to know which IPs to let through; on a
Fargate task each ENI gets its own egress IP, so the task itself is the only
thing that knows what to add.

There are two files of interest:

- `update_waf_ip.py` — fetches the egress IP from an echo service
  (`https://checkip.amazonaws.com` by default), then calls
  `wafv2:GetIPSet` / `wafv2:UpdateIPSet` to add or remove that single
  `/32` (or `/128`) entry. The remove path leaves every other CIDR in the
  set alone. Both paths retry on `WAFOptimisticLockException` with
  exponential backoff.
- `entrypoint.sh` — runs the script in add mode, then `exec`s nothing —
  instead it stays as PID 1, runs the supplied command in the background,
  forwards `SIGTERM`/`SIGINT` to that child, waits for the child to exit,
  and then runs the script in remove mode. If the child exits on its
  own (success or crash), the remove step does not run, so the IPSet
  entry stays in place for inspection or external reconciliation.

## Required environment

| Var | Required | Notes |
| --- | --- | --- |
| `WAF_IP_SET_NAME` | yes | Name of the IPSet |
| `WAF_IP_SET_ID` | yes | Id of the IPSet (WAFv2 needs both) |
| `WAF_IP_SET_SCOPE` | no | `REGIONAL` (default) or `CLOUDFRONT` |
| `AWS_REGION` | yes for `REGIONAL` | Standard boto3 region resolution |
| `IP_CHECK_URL` | no | Override the echo service if your egress can't reach AWS |
| `LOG_LEVEL` | no | Python logging level, defaults to `INFO` |

AWS credentials come from the standard boto3 resolution chain. On ECS that
means the task role; locally it means whatever you have in `~/.aws` or in
the environment.

The task role needs `wafv2:GetIPSet` and `wafv2:UpdateIPSet` on the IPSet's
ARN, nothing else.

## Integrating with Knowledge Commons Works

KC Works (https://github.com/MESH-Research/knowledge-commons-works) is an
InvenioRDM-based application running as several ECS services — at minimum
an API container (`startup_api.sh`), a UI container (`startup_ui.sh`) and
a Celery worker (`startup_worker.sh`). Each of those startup scripts ends
in an `exec` call to `uwsgi` or `celery`, and each of them is what we want
to wrap.

The KC Works `Dockerfile` is already based on
`ghcr.io/astral-sh/uv:python3.12-bookworm`, so `uv` is on `$PATH` and the
PEP 723 shebang in `update_waf_ip.py` will resolve `boto3` on first run
without us adding anything else to the image.

### 1. Vendor the two files into the KC Works tree

Drop `update_waf_ip.py` and `entrypoint.sh` into `docker/waf/` in the KC
Works repo:

```
docker/waf/
├── entrypoint.sh
└── update_waf_ip.py
```

Keep the names. The shell script resolves its sibling Python script by
its own directory.

### 2. Wire them into the Dockerfile

In the KC Works `Dockerfile`, after the existing block that copies the
startup scripts into `${INVENIO_INSTANCE_PATH}`, add:

```dockerfile
COPY docker/waf/entrypoint.sh docker/waf/update_waf_ip.py \
     ${INVENIO_INSTANCE_PATH}/
RUN chmod +x ${INVENIO_INSTANCE_PATH}/entrypoint.sh
```

Then change the existing `ENTRYPOINT` line at the bottom of the file from

```dockerfile
ENTRYPOINT ["/bin/bash", "-c"]
```

to

```dockerfile
ENTRYPOINT ["/opt/invenio/var/instance/entrypoint.sh", "/bin/bash", "-c"]
```

Docker concatenates `ENTRYPOINT` with `CMD` (or with the task definition's
`command`), so the existing invocation `["startup_api.sh"]`, etc., keeps
working — `bash -c startup_api.sh` is just preceded by our wrapper. The
wrapper does its WAF-add step, then runs `bash -c startup_api.sh` as a
child, then on `SIGTERM` does its WAF-remove step before exiting.

### 3. Task definition changes

In each ECS task definition that needs the egress IP allow-listed, add the
environment variables and bump the stop timeout so the WAF remove call has
room to complete before SIGKILL arrives. For example, in JSON:

```json
"environment": [
  { "name": "WAF_IP_SET_NAME", "value": "kcworks-egress" },
  { "name": "WAF_IP_SET_ID",   "value": "abcd1234-..." },
  { "name": "AWS_REGION",      "value": "us-east-1" }
],
"stopTimeout": 60
```

Three caveats on `stopTimeout`:

- The default is 30 seconds. uWSGI in graceful mode wants several seconds
  to drain in-flight requests, and the WAFv2 call itself can take a
  noticeable fraction of a second on top of that, more if there is lock
  contention with another task starting up at the same moment. 60 is a
  comfortable margin; 90 if you have long-running uWSGI workers.
- Celery worker shutdown is slower than uWSGI. For `startup_worker.sh`
  bump it to at least 120, matching whatever the longest task you let
  through is.
- ECS hard-caps `stopTimeout` at 120 seconds on Fargate. If your worker
  needs more than that, treat the WAF entry as best-effort on shutdown
  and run a reconciliation job (see below) rather than relying on
  in-task removal.

### 4. IAM

Add the two WAFv2 actions to the task role used by whichever services
need WAF allow-listing. The minimum policy:

```json
{
  "Effect": "Allow",
  "Action": ["wafv2:GetIPSet", "wafv2:UpdateIPSet"],
  "Resource": "arn:aws:wafv2:us-east-1:<account-id>:regional/ipset/kcworks-egress/abcd1234-..."
}
```

KC Works's existing task roles already have wide-ish permissions for S3
and similar, so this is one more statement added to that policy, not a
new role.

### 5. Which KC Works services need this?

Probably not all three. In practice:

- **Worker** (`startup_worker.sh`): yes. Workers make outbound HTTP calls
  to other Commons services and to ORCID, DataCite, etc. If any of those
  upstreams have IP allow-listing on a WAF you operate, the worker is the
  most likely candidate.
- **API** (`startup_api.sh`): only if the API itself fetches external
  resources that go through a WAF you control. Inbound traffic to the
  API is governed by a different WAF and isn't what this tool deals
  with.
- **UI** (`startup_ui.sh`): usually not. The UI uwsgi front renders
  templates and proxies to the API over the internal network.

Start by adding the wrapper to just the worker's task definition. The
Dockerfile change is image-wide, but the wrapper is inert without the
required env vars set — `update_waf_ip.py` returns non-zero if
`WAF_IP_SET_NAME` and `WAF_IP_SET_ID` aren't present, which would prevent
the container from starting. So either ship the env vars to every
service, or guard the wrapper with a check on the env var being set
before running the add/remove. The simplest version of that guard, at the
top of `entrypoint.sh`:

```sh
if [ -z "${WAF_IP_SET_NAME:-}" ]; then
    exec "$@"
fi
```

That makes the image safe to deploy across all task definitions and only
active where the env vars exist.

## What happens on a deploy

When ECS does a force-new-deployment, the existing tasks receive
`SIGTERM`, drain, and exit. The wrapper catches the signal, lets uWSGI
or Celery finish what it is doing, and then calls `update_waf_ip.py
--remove`, which fetches the same egress IP it saw on startup and removes
that one `/32` from the IPSet. New tasks come up, run the add path, and
register their own (new, different) IPs.

If something goes wrong during shutdown — the task is `SIGKILL`'d after
`stopTimeout`, the WAFv2 API rate-limits, network out from the dying
task is already gone — the IPSet keeps the stale entry. This needs pruning
manually at present.

## Tests

```
uv run --with pytest --with boto3 pytest test_update_waf_ip.py
```

The tests cover the add path, the remove path, optimistic-lock retry and
token refresh on both, the CLI dispatch in `main()`, and the env var
validation. The `entrypoint.sh` signal-handling behaviour isn't covered
by the Python tests; there's a short smoke procedure in the commit
message that stubs `uv` and verifies the add-only / add+remove /
add-on-crash branches.
