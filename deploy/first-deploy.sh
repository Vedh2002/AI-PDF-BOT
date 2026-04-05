#!/usr/bin/env bash
# =============================================================================
# deploy/first-deploy.sh  –  Manual first deployment (run once after setup.sh)
#
# After this you'll have live Cloud Run URLs to put in cloudbuild.yaml,
# which handles all future deployments automatically via Cloud Build triggers.
# =============================================================================
set -euo pipefail

# ── EDIT THESE to match your setup.sh values ──────────────────────────────────
PROJECT_ID="your-gcp-project-id"
REGION="us-central1"
REPOSITORY="ai-pdf-bot"
BACKEND_SERVICE="ai-pdf-bot-backend"
FRONTEND_SERVICE="ai-pdf-bot-frontend"
SQL_INSTANCE="ai-pdf-bot-db"
DATA_BUCKET="${PROJECT_ID}-ai-pdf-bot-data"
SA_EMAIL="ai-pdf-bot-sa@${PROJECT_ID}.iam.gserviceaccount.com"
IMAGE_TAG="first"
# ──────────────────────────────────────────────────────────────────────────────

REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}"
CONN_NAME="${PROJECT_ID}:${REGION}:${SQL_INSTANCE}"

gcloud config set project "${PROJECT_ID}"

# ── Step 1: Authenticate Docker with Artifact Registry ────────────────────────
echo "▶ Configuring Docker for Artifact Registry..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# ── Step 2: Build and push backend ────────────────────────────────────────────
echo "▶ Building backend image..."
docker build -t "${REGISTRY}/backend:${IMAGE_TAG}" -t "${REGISTRY}/backend:latest" ./backend
docker push --all-tags "${REGISTRY}/backend"

# ── Step 3: Deploy backend (no frontend URL yet – we'll update after step 5) ──
echo "▶ Deploying backend to Cloud Run..."
gcloud run deploy "${BACKEND_SERVICE}" \
  --image="${REGISTRY}/backend:${IMAGE_TAG}" \
  --region="${REGION}" \
  --platform=managed \
  --execution-environment=gen2 \
  --service-account="${SA_EMAIL}" \
  --add-cloudsql-instances="${CONN_NAME}" \
  --add-volume="name=data,type=cloud-storage,bucket=${DATA_BUCKET}" \
  --add-volume-mount="volume=data,mount-path=/app/data" \
  --set-env-vars="ENVIRONMENT=gcp,PORT=8080,CLOUD_SQL_CONNECTION_NAME=${CONN_NAME},DB_NAME=ai_pdf_bot,RESEND_FROM_EMAIL=aidocchat@hireplz.live" \
  --set-secrets="DB_USER=DB_USER:latest,DB_PASSWORD=DB_PASSWORD:latest,SECRET_KEY=JWT_SECRET_KEY:latest,GROQ_API_KEY=GROQ_API_KEY:latest,RESEND_API_KEY=RESEND_API_KEY:latest" \
  --allow-unauthenticated \
  --memory=2Gi \
  --cpu=2 \
  --min-instances=1 \
  --max-instances=10 \
  --timeout=300 \
  --quiet

BACKEND_URL=$(gcloud run services describe "${BACKEND_SERVICE}" \
  --region="${REGION}" --format="value(status.url)")
echo "✓ Backend URL: ${BACKEND_URL}"

# ── Step 4: Build and push frontend (with backend URL baked in) ───────────────
echo "▶ Building frontend image..."
docker build \
  --build-arg "NEXT_PUBLIC_API_BASE_URL=${BACKEND_URL}" \
  -t "${REGISTRY}/frontend:${IMAGE_TAG}" \
  -t "${REGISTRY}/frontend:latest" \
  ./frontend
docker push --all-tags "${REGISTRY}/frontend"

# ── Step 5: Deploy frontend ────────────────────────────────────────────────────
echo "▶ Deploying frontend to Cloud Run..."
gcloud run deploy "${FRONTEND_SERVICE}" \
  --image="${REGISTRY}/frontend:${IMAGE_TAG}" \
  --region="${REGION}" \
  --platform=managed \
  --service-account="${SA_EMAIL}" \
  --set-env-vars="NODE_ENV=production,PORT=3000" \
  --allow-unauthenticated \
  --memory=512Mi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=5 \
  --timeout=60 \
  --quiet

FRONTEND_URL=$(gcloud run services describe "${FRONTEND_SERVICE}" \
  --region="${REGION}" --format="value(status.url)")
echo "✓ Frontend URL: ${FRONTEND_URL}"

# ── Step 6: Update backend CORS/email with real frontend URL ──────────────────
echo "▶ Updating backend with frontend URL..."
gcloud run services update "${BACKEND_SERVICE}" \
  --region="${REGION}" \
  --update-env-vars="ALLOWED_ORIGINS=${FRONTEND_URL},FRONTEND_URL=${FRONTEND_URL}" \
  --quiet

echo ""
echo "=================================================="
echo " First deployment complete!"
echo "=================================================="
echo "  Backend  → ${BACKEND_URL}"
echo "  Frontend → ${FRONTEND_URL}"
echo ""
echo " Now update cloudbuild.yaml substitutions:"
echo "   _BACKEND_URL  = ${BACKEND_URL}"
echo "   _FRONTEND_URL = ${FRONTEND_URL}"
echo ""
echo " Then connect your GitHub repo to Cloud Build."
echo "=================================================="
