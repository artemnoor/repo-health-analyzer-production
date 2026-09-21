# Deployment

The smallest production deployment is one Python API process, one SQLite file
and optional worker processes sharing the task database. The API, worker and
scheduler use the same typed production composition. Use the supplied
`Dockerfile` for a non-root image; it contains Python and Git only and has a
`/healthz` healthcheck.

```powershell
docker build -t repo-health-analyzer .
docker run --rm -p 8000:8000 -v repo-health-data:/data repo-health-analyzer
```

For multiple workers, use a database with safe transactional locking and keep
checkout/tool resource limits bounded. SQLite is the supported local mode;
multi-instance database validation is a separate deployment gate. Install Vale,
PyDriller, and git-sizer as required by the target image, and configure
`SONAR_URL`/`SONAR_TOKEN` and `SOURCECRAFT_URL`/`SOURCECRAFT_TOKEN` only when
the corresponding services are reachable. Missing optional capabilities appear
in `/readyz` as degradation and leave explicit partial/unavailable facts.
No queue, service mesh, Kubernetes, Node runtime or frontend is required.
