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

## Google Cloud Storage adapter

`GCSVideoStorage` is implemented but is not enabled in the live service until a
bucket and the following environment variables are configured:

```text
GYMBROMATICS_GCS_BUCKET=<private-bucket-name>
GYMBROMATICS_GCS_PREFIX=staging
GYMBROMATICS_GCS_SIGNING_SERVICE_ACCOUNT=<signer-service-account-email>
```

The API creates a 15-minute V4 Signed URL for a `PUT`. The browser sends the video
directly to GCS with signed `Content-Type`, SHA-256 metadata, and a create-only
generation precondition. The API verifies the stored size and SHA-256 metadata
before queueing the job. The worker reads inputs and writes results through the
same `VideoStorage` interface.

Before using browser uploads, apply [`gcs-cors.json`](gcs-cors.json) to the bucket
and replace/add origins if the service URL changes:

```powershell
gcloud storage buckets update gs://BUCKET_NAME --cors-file=infra/gcs-cors.json
```

The runtime identity needs object read/write/delete permissions on the bucket. To
sign without downloading a service-account key, enable the IAM Service Account
Credentials API and grant the runtime identity `iam.serviceAccounts.signBlob`
(normally through `roles/iam.serviceAccountTokenCreator`) on the configured signing
account. Signed URLs are bearer credentials, so the 15-minute expiry and private
bucket must be retained.

Creating a bucket, storing videos, API operations, and network egress can incur
Google Cloud charges. The repository does not create or configure these cloud
resources automatically.
