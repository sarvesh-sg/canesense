#!/usr/bin/env bash
# Deploy CaneSense to Cloud Run from source. Needs: gcloud logged in, a project with billing.
#   PROJECT=my-project REGION=asia-south1 AGENT_ENGINE=projects/<p>/locations/<region>/reasoningEngines/<id> ./deploy.sh
set -euo pipefail
: "${PROJECT:?set PROJECT}" "${REGION:=asia-south1}" "${SERVICE:=canesense}" "${GEMINI_LOCATION:=global}"
: "${GEMINI_MODELS:=gemini-3.5-flash,gemini-3.8-flash,gemini-2.5-flash}"
GCLOUD=${GCLOUD:-gcloud}
$GCLOUD config set project "$PROJECT" >/dev/null
$GCLOUD services enable run.googleapis.com cloudbuild.googleapis.com aiplatform.googleapis.com artifactregistry.googleapis.com >/dev/null
ENV="GOOGLE_GENAI_USE_VERTEXAI=TRUE|GOOGLE_CLOUD_PROJECT=$PROJECT|GOOGLE_CLOUD_LOCATION=$GEMINI_LOCATION|GEMINI_MODELS=$GEMINI_MODELS"
[ -n "${AGENT_ENGINE:-}" ] && ENV="$ENV|AGENT_ENGINE=$AGENT_ENGINE"
$GCLOUD run deploy "$SERVICE" --source . --region "$REGION" --allow-unauthenticated \
  --memory 1Gi --cpu 1 --timeout 3600 --concurrency 20 --min-instances 0 --max-instances 2 \
  --set-env-vars "^|^$ENV"
URL=$($GCLOUD run services describe "$SERVICE" --region "$REGION" --format 'value(status.url)')
echo "deployed: $URL"
curl -s "$URL/health"; echo
