# Staging infrastructure

The staging service runs in Google Cloud project `gymbromatics-staging-itay`,
region `me-west1`.

- Cloud Run service: `gymbromatics-staging`
- Artifact Registry repository: `gymbromatics`
- Runtime service account: `gymbromatics-api`
- Secret Manager secret: `gemini-api-key`
- Public URL: <https://gymbromatics-staging-314205128886.me-west1.run.app>

The service uses request-based CPU allocation, 1 vCPU, 512 MiB memory,
concurrency 20, a 90-second request timeout, zero minimum instances and one
maximum instance. The Gemini key is mounted from Secret Manager version 1.

`artifact-cleanup-policy.json` deletes image versions older than seven days but
always preserves the three most recent versions of each package.

To stop runtime usage without deleting the project:

```powershell
gcloud run services delete gymbromatics-staging --region=me-west1 --project=gymbromatics-staging-itay
```

Deleting the Cloud Run service does not delete Artifact Registry images or the
Secret Manager secret.
