#!/usr/bin/env bash
# Quick sanity test for the fleet CLI against a running API.
# Usage: ./scripts/test-fleet-cli.sh
#
# Prereqs:
#   docker compose up --build -d
#   export LEGION_FLEET_API_URL=http://127.0.0.1:8000  (default)
set -euo pipefail

CLI="uv run legion-cli"
OUTPUT="json"

echo "=== Fleet CLI Sanity Test ==="
echo ""

# =====================================================================
# Part 1: Verify seeded defaults
# =====================================================================
echo "--- discover seeded default org ---"
DEFAULT_ORG_ID=$($CLI org list -o $OUTPUT | jq -r '.[] | select(.slug=="default") | .id')
echo "DEFAULT_ORG_ID=$DEFAULT_ORG_ID"
echo ""

echo "--- discover seeded default project ---"
DEFAULT_PROJECT_ID=$($CLI project list --org-id "$DEFAULT_ORG_ID" -o $OUTPUT | jq -r '.[] | select(.slug=="default") | .id')
echo "DEFAULT_PROJECT_ID=$DEFAULT_PROJECT_ID"
echo ""

echo "--- agent-group create (under defaults) ---"
AG_DEFAULT_JSON=$($CLI agent-group create \
  --org-id "$DEFAULT_ORG_ID" \
  --project-id "$DEFAULT_PROJECT_ID" \
  --name "Default Monitoring" \
  --slug "default-monitoring" \
  --environment "dev" \
  --provider "on-prem" \
  -o $OUTPUT)
echo "$AG_DEFAULT_JSON"
AG_DEFAULT_ID=$(echo "$AG_DEFAULT_JSON" | jq -r '.id')
echo "AG_DEFAULT_ID=$AG_DEFAULT_ID"
echo ""

echo "--- agent-group list (under default project) ---"
$CLI agent-group list --org-id "$DEFAULT_ORG_ID" -o $OUTPUT
echo ""

echo "--- agent-group delete (default-monitoring) ---"
$CLI agent-group delete --id "$AG_DEFAULT_ID" -o $OUTPUT
echo ""

# =====================================================================
# Part 2: Custom org/project/agent-group lifecycle
# =====================================================================

# --- Organizations ---
echo "--- org create ---"
ORG_JSON=$($CLI org create --name "Legion" --slug "legion" -o $OUTPUT)
echo "$ORG_JSON"
ORG_ID=$(echo "$ORG_JSON" | jq -r '.id')
echo "ORG_ID=$ORG_ID"
echo ""

echo "--- org list ---"
$CLI org list -o $OUTPUT
echo ""

echo "--- org update ---"
$CLI org update --id "$ORG_ID" --name "Legion Corp" -o $OUTPUT
echo ""

# --- Projects ---
echo "--- project create (platform) ---"
PROJ1_JSON=$($CLI project create \
  --org-id "$ORG_ID" \
  --name "Platform" \
  --slug "platform" \
  -o $OUTPUT)
echo "$PROJ1_JSON"
PROJ1_ID=$(echo "$PROJ1_JSON" | jq -r '.id')
echo "PROJ1_ID=$PROJ1_ID"
echo ""

echo "--- project create (data-infra) ---"
PROJ2_JSON=$($CLI project create \
  --org-id "$ORG_ID" \
  --name "Data Infrastructure" \
  --slug "data-infra" \
  -o $OUTPUT)
echo "$PROJ2_JSON"
PROJ2_ID=$(echo "$PROJ2_JSON" | jq -r '.id')
echo "PROJ2_ID=$PROJ2_ID"
echo ""

echo "--- project list ---"
$CLI project list --org-id "$ORG_ID" -o $OUTPUT
echo ""

echo "--- project update (data-infra → data-platform) ---"
$CLI project update --id "$PROJ2_ID" --name "Data Platform" --slug "data-platform" -o $OUTPUT
echo ""

# --- Agent Groups (under platform project) ---
echo "--- agent-group create (prod-us-east / eks) ---"
AG1_JSON=$($CLI agent-group create \
  --org-id "$ORG_ID" \
  --project-id "$PROJ1_ID" \
  --name "Production US-East" \
  --slug "prod-us-east" \
  --environment "production" \
  --provider "eks" \
  -o $OUTPUT)
echo "$AG1_JSON"
AG1_ID=$(echo "$AG1_JSON" | jq -r '.id')
echo "AG1_ID=$AG1_ID"
echo ""

echo "--- agent-group create (prod-us-west / eks) ---"
AG2_JSON=$($CLI agent-group create \
  --org-id "$ORG_ID" \
  --project-id "$PROJ1_ID" \
  --name "Production US-West" \
  --slug "prod-us-west" \
  --environment "production" \
  --provider "eks" \
  -o $OUTPUT)
echo "$AG2_JSON"
AG2_ID=$(echo "$AG2_JSON" | jq -r '.id')
echo "AG2_ID=$AG2_ID"
echo ""

# --- Agent Groups (under data-platform project) ---
echo "--- agent-group create (staging / gke) ---"
AG3_JSON=$($CLI agent-group create \
  --org-id "$ORG_ID" \
  --project-id "$PROJ2_ID" \
  --name "Staging" \
  --slug "staging" \
  --environment "staging" \
  --provider "gke" \
  -o $OUTPUT)
echo "$AG3_JSON"
AG3_ID=$(echo "$AG3_JSON" | jq -r '.id')
echo "AG3_ID=$AG3_ID"
echo ""

echo "--- agent-group create (dev / on-prem) ---"
AG4_JSON=$($CLI agent-group create \
  --org-id "$ORG_ID" \
  --project-id "$PROJ2_ID" \
  --name "Dev Lab" \
  --slug "dev-lab" \
  --environment "dev" \
  --provider "on-prem" \
  -o $OUTPUT)
echo "$AG4_JSON"
AG4_ID=$(echo "$AG4_JSON" | jq -r '.id')
echo "AG4_ID=$AG4_ID"
echo ""

echo "--- agent-group list (by org) ---"
$CLI agent-group list --org-id "$ORG_ID" -o $OUTPUT
echo ""

echo "--- agent-group update (staging → pre-prod) ---"
$CLI agent-group update --id "$AG3_ID" --name "Pre-Production" --slug "pre-prod" --environment "pre-prod" -o $OUTPUT
echo ""

# --- Agents ---
echo "--- agent list (by org-id, all groups) ---"
$CLI agent list --org-id "$ORG_ID" -o $OUTPUT
echo ""

echo "--- agent list (by agent-group-id, prod-us-east only) ---"
$CLI agent list --agent-group-id "$AG1_ID" -o $OUTPUT
echo ""

# --- Table output ---
echo "--- org list (table) ---"
$CLI org list
echo ""

echo "--- project list (table) ---"
$CLI project list --org-id "$ORG_ID"
echo ""

echo "--- agent-group list (table) ---"
$CLI agent-group list --org-id "$ORG_ID"
echo ""

# --- Cleanup (custom entities only, defaults remain) ---
echo "--- agent-group delete (dev-lab) ---"
$CLI agent-group delete --id "$AG4_ID" -o $OUTPUT
echo ""

echo "--- agent-group delete (pre-prod) ---"
$CLI agent-group delete --id "$AG3_ID" -o $OUTPUT
echo ""

echo "--- agent-group delete (prod-us-west) ---"
$CLI agent-group delete --id "$AG2_ID" -o $OUTPUT
echo ""

echo "--- agent-group delete (prod-us-east) ---"
$CLI agent-group delete --id "$AG1_ID" -o $OUTPUT
echo ""

echo "--- project delete (data-platform) ---"
$CLI project delete --id "$PROJ2_ID" -o $OUTPUT
echo ""

echo "--- project delete (platform) ---"
$CLI project delete --id "$PROJ1_ID" -o $OUTPUT
echo ""

echo "--- org delete ---"
$CLI org delete --id "$ORG_ID" -o $OUTPUT
echo ""

echo "--- org list (should show only seeded default) ---"
$CLI org list -o $OUTPUT
echo ""

echo "--- project list (should show only seeded default) ---"
$CLI project list --org-id "$DEFAULT_ORG_ID" -o $OUTPUT
echo ""

echo "=== Done ==="
