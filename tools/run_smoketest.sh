#!/bin/bash
# Go-live chat smoke-test CLI (ugyanaz, mint az admin-panel gombja).
# Hasznalat:  bash tools/run_smoketest.sh <client_id>
# Eredmeny:   https://codexpress.cloud/chatbot/reports/chat-teszt-<cid>-<datum>.xlsx
set -e
CID="${1:?Hasznalat: run_smoketest.sh <client_id>}"
cd /docker/chatbot-prod
docker compose -f docker-compose.prod.yml run --rm -T api \
  python -m app.smoketest "$CID" --base http://chatbot-api-prod:8000 --out /reports
