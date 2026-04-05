#!/usr/bin/env bash
# =============================================================================
# deploy/setup.sh  –  One-time GCP infrastructure setup for AI PDF Bot
#
# Run this from Cloud Shell or any machine with gcloud + bash.
# Run it ONCE before the first deployment.
#
# Usage:
#   chmod +x deploy/setup.sh
#   ./deploy/setup.sh
# =============================================================================
set -euo pipefail

# ── 0. Configuration – EDIT THESE ─────────────────────────────────────────────
PROJECT_ID="your-gcp-project-id"          # gcloud projects list
REGION="us-central1"
ZONE="us-central1-a"

REPOSITORY="ai-pdf-bot"                   # Artifact Registry repo name
BACKEND_SERVICE="ai-pdf-bot-backend"
FRONTEND_SERVICE="ai-pdf-bot-frontend"

SQL_INSTANCE="ai-pdf-bot-db"              # Cloud SQL instance name
DB_NAME="ai_pdf_bot"
DB_USER="ai_pdf_bot_user"
DB_PASSWORD="$(openssl rand -base64 24)"  # auto-generated; save this!

DATA_BUCKET="${PROJECT_ID}-ai-pdf-bot-data"   # GCS bucket (must be globally unique)
SA_NAME="ai-pdf-bot-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# Secrets you must supply
GROQ_API_KEY="your-groq-api-key"
RESEND_API_KEY="your-resend-api-key"
JWT_SECRET_KEY="$(openssl rand -hex 32)"  # auto-generated; save this!

# ── 1. Set active project ──────────────────────────────────────────────────────
echo "▶ Setting project to ${PROJECT_ID}"
gcloud config set project "${PROJECT_ID}"

# ── 2. Enable required APIs ────────────────────────────────────────────────────
echo "▶ Enabling GCP APIs (this may take ~2 min)..."
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  iam.googleapis.com \
  cloudresourcemanager.googleapis.com

# ── 3. Create Artifact Registry repository ────────────────────────────────────
echo "▶ Creating Artifact Registry repository..."
gcloud artifacts repositories create "${REPOSITORY}" \
  --repository-format=docker \
  --location="${REGION}" \
  --description="Docker images for AI PDF Bot" \
  2>/dev/null || echo "  (already exists)"

# ── 4. Create service account ─────────────────────────────────────────────────
echo "▶ Creating service account ${SA_EMAIL}..."
gcloud iam service-accounts create "${SA_NAME}" \
  --display-name="AI PDF Bot Runtime SA" \
  2>/dev/null || echo "  (already exists)"

# Grant roles needed by Cloud Run services
for ROLE in \
  roles/cloudsql.client \
  roles/storage.objectAdmin \
  roles/secretmanager.secretAccessor \
  roles/artifactregistry.reader; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${ROLE}" \
    --quiet
done

# Grant Cloud Build permission to deploy Cloud Run and use the service account
CLOUDBUILD_SA="${PROJECT_ID}@cloudbuild.gserviceaccount.com"
for ROLE in \
  roles/run.admin \
  roles/iam.serviceAccountUser \
  roles/artifactregistry.writer; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${CLOUDBUILD_SA}" \
    --role="${ROLE}" \
    --quiet
done

# ── 5. Create Cloud SQL (MySQL 8) instance ────────────────────────────────────
echo "▶ Creating Cloud SQL instance ${SQL_INSTANCE} (takes ~5 min)..."
gcloud sql instances create "${SQL_INSTANCE}" \
  --database-version=MYSQL_8_0 \
  --tier=db-f1-micro \
  --region="${REGION}" \
  --storage-type=SSD \
  --storage-size=10GB \
  --no-backup \
  2>/dev/null || echo "  (already exists)"

echo "▶ Creating database ${DB_NAME}..."
gcloud sql databases create "${DB_NAME}" \
  --instance="${SQL_INSTANCE}" \
  2>/dev/null || echo "  (already exists)"

echo "▶ Creating DB user ${DB_USER}..."
gcloud sql users create "${DB_USER}" \
  --instance="${SQL_INSTANCE}" \
  --password="${DB_PASSWORD}" \
  2>/dev/null || echo "  (already exists)"

# ── 6. Create GCS bucket for data (uploads + FAISS indexes) ───────────────────
echo "▶ Creating GCS data bucket gs://${DATA_BUCKET}..."
gcloud storage buckets create "gs://${DATA_BUCKET}" \
  --location="${REGION}" \
  --uniform-bucket-level-access \
  2>/dev/null || echo "  (already exists)"

# Grant the service account admin access to the bucket
gcloud storage buckets add-iam-policy-binding "gs://${DATA_BUCKET}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/storage.objectAdmin"

# ── 7. Store secrets in Secret Manager ────────────────────────────────────────
echo "▶ Creating secrets in Secret Manager..."

store_secret() {
  local NAME="$1" VALUE="$2"
  echo -n "${VALUE}" | gcloud secrets create "${NAME}" \
    --data-file=- \
    --replication-policy=automatic \
    2>/dev/null || \
  echo -n "${VALUE}" | gcloud secrets versions add "${NAME}" --data-file=-
}

store_secret "DB_USER"        "${DB_USER}"
store_secret "DB_PASSWORD"    "${DB_PASSWORD}"
store_secret "JWT_SECRET_KEY" "${JWT_SECRET_KEY}"
store_secret "GROQ_API_KEY"   "${GROQ_API_KEY}"
store_secret "RESEND_API_KEY" "${RESEND_API_KEY}"

# ── 8. Create Cloud Build trigger ─────────────────────────────────────────────
echo "▶ Skipping Cloud Build trigger creation – connect your GitHub repo manually:"
echo "   https://console.cloud.google.com/cloud-build/triggers"
echo "   Point it at cloudbuild.yaml and set substitution variables."

# ── 9. Summary ────────────────────────────────────────────────────────────────
CONN_NAME="${PROJECT_ID}:${REGION}:${SQL_INSTANCE}"

echo ""
echo "=================================================="
echo " Setup complete!  Save these values:"
echo "=================================================="
echo "  PROJECT_ID            = ${PROJECT_ID}"
echo "  REGION                = ${REGION}"
echo "  SQL Connection Name   = ${CONN_NAME}"
echo "  DB_PASSWORD           = ${DB_PASSWORD}"
echo "  JWT_SECRET_KEY        = ${JWT_SECRET_KEY}"
echo "  Data Bucket           = gs://${DATA_BUCKET}"
echo "  Service Account       = ${SA_EMAIL}"
echo ""
echo " Next steps:"
echo "  1. Set cloudbuild.yaml substitution variables (especially _BACKEND_URL / _FRONTEND_URL)"
echo "     after first manual deploy (see deploy/first-deploy.sh)"
echo "  2. Connect your GitHub repo to Cloud Build trigger"
echo "  3. Push to main → pipeline builds + deploys automatically"
echo "=================================================="
