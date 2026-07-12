#!/bin/bash
# Tenant go-live chat smoke-test futtato wrapper.
# Hasznalat:  bash tools/run_smoketest.sh <client_id>
# Eredmeny:   XLSX a webrooton -> https://codexpress.cloud/chatbot/reports/chat-teszt-<cid>-<datum>.xlsx
set -e
CID="${1:?Hasznalat: run_smoketest.sh <client_id>}"
cd /docker/chatbot-prod
mkdir -p /root/weboldal_fajlok/chatbot/reports
chmod 755 /root/weboldal_fajlok/chatbot/reports
docker compose -f docker-compose.prod.yml run --rm -T \
  -v /docker/chatbot-prod/tools/tenant_smoketest.py:/tmp/st.py \
  -v /root/weboldal_fajlok/chatbot/reports:/out \
  api sh -c "pip install -q openpyxl --break-system-packages 2>/dev/null; python /tmp/st.py $CID --base http://chatbot-api-prod:8000 --out /out"
