#!/usr/bin/env bash
set -euo pipefail

# toggle-alb-rule.sh
#
# Enables/disables an ALB listener rule by adding/removing an http-request-method
# condition matching only FOOBARFOO.
#
# Requirements: awscli v2, jq
#
# Usage:
#   ./toggle-alb-rule.sh enable  arn:aws:elasticloadbalancing:...
#   ./toggle-alb-rule.sh disable arn:aws:elasticloadbalancing:...
#   ./toggle-alb-rule.sh status  arn:aws:elasticloadbalancing:...

ACTION="${1:-}"
RULE_ARN="${2:-arn:aws:elasticloadbalancing:us-east-1:755997884632:listener-rule/app/hcommons-prod-alb/cd92f60f938442a3/7bf51009f05e0d44/a33ced76e84ab9c3}"

if [[ -z "${ACTION}" ]]; then
  echo "Usage: $0 <enable|disable|status> <rule-arn>"
  exit 2
fi

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing dependency: $1" >&2; exit 3; }; }
need aws
need jq

describe_rule_json() {
  aws elbv2 describe-rules --rule-arns "$RULE_ARN" --output json
}

# Sanitize conditions so we never send both legacy .Values and the newer *Config blocks.
# AWS rejects e.g. {Field:"path-pattern", Values:[...], PathPatternConfig:{Values:[...]}}.
sanitize_conditions() {
  jq -c '
    (. // []) | map(
      if (.Field=="path-pattern" and (.PathPatternConfig? != null)) then del(.Values)
      elif (.Field=="host-header" and (.HostHeaderConfig? != null)) then del(.Values)
      elif (.Field=="http-header" and (.HttpHeaderConfig? != null)) then del(.Values)
      elif (.Field=="http-request-method" and (.HttpRequestMethodConfig? != null)) then del(.Values)
      elif (.Field=="query-string" and (.QueryStringConfig? != null)) then del(.Values)
      elif (.Field=="source-ip" and (.SourceIpConfig? != null)) then del(.Values)
      else .
      end
    )
  '
}

RULE_JSON="$(describe_rule_json)"
RULE_OBJ="$(echo "$RULE_JSON" | jq -e '.Rules[0]')"

ACTIONS_JSON="$(echo "$RULE_OBJ" | jq -c '.Actions')"

# Pull current conditions, then sanitize them for safe round-tripping.
CONDS_JSON="$(echo "$RULE_OBJ" | jq -c '.Conditions' | sanitize_conditions)"

is_disabled() {
  echo "$CONDS_JSON" | jq -e '
    any(.Field=="http-request-method"
        and (.HttpRequestMethodConfig.Values // []) == ["FOOBARFOO"])
  ' >/dev/null
}

print_status() {
  if is_disabled; then
    echo "DISABLED (http-request-method == FOOBARFOO)"
  else
    echo "ENABLED (no FOOBARFOO http-request-method condition)"
  fi
}

case "$ACTION" in
  status)
    print_status
    exit 0
    ;;
  enable)
    # Remove ANY http-request-method conditions.
    NEW_CONDITIONS_JSON="$(echo "$CONDS_JSON" | jq -c 'map(select(.Field != "http-request-method"))')"
    ;;
  disable)
    # Remove any existing http-request-method, then add FOOBARFOO.
    NEW_CONDITIONS_JSON="$(echo "$CONDS_JSON" | jq -c '
      map(select(.Field != "http-request-method"))
      + [{"Field":"http-request-method","HttpRequestMethodConfig":{"Values":["FOOBARFOO"]}}]
    ')"
    ;;
  *)
    echo "Unknown action: $ACTION"
    echo "Usage: $0 <enable|disable|status> <rule-arn>"
    exit 2
    ;;
esac

aws elbv2 modify-rule \
  --rule-arn "$RULE_ARN" \
  --conditions "$NEW_CONDITIONS_JSON" \
  --actions "$ACTIONS_JSON" \
  --output json >/dev/null

# Re-read and report
RULE_JSON="$(describe_rule_json)"
RULE_OBJ="$(echo "$RULE_JSON" | jq -e '.Rules[0]')"
CONDS_JSON="$(echo "$RULE_OBJ" | jq -c '.Conditions' | sanitize_conditions)"

echo "Updated rule:"
print_status
