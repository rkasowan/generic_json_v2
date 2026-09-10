#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then echo "Run as root: sudo ./install.sh" >&2; exit 1; fi

prompt() {
  label=$1; default=${2-}
  if [ -n "$default" ]; then printf '%s [%s]: ' "$label" "$default" >&2; else printf '%s: ' "$label" >&2; fi
  IFS= read -r answer
  [ -n "$answer" ] || answer=$default
  printf '%s' "$answer"
}
prompt_secret() {
  printf '%s (blank keeps existing): ' "$1" >&2
  stty -echo; IFS= read -r answer; stty echo; printf '\n' >&2
  printf '%s' "$answer"
}
encode() { printf '%s' "$1" | base64 | tr -d '\n'; }
escape_env() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
existing_value() {
  file=$1; key=$2
  [ -f "$file" ] || return 0
  sed -n "s/^${key}=\"\(.*\)\"$/\1/p" "$file" | head -1
}

shared_username=$(prompt "Shared ServiceNow username")
assignment_group=$(prompt "DTI assignment group name or sys_id" "Event Management")
email_to=$(prompt "Failure email recipient")
email_from=$(prompt "Failure email sender" "generic-json-v2-synthetic@localhost")
smtp_host=$(prompt "SMTP relay host")
smtp_port=$(prompt "SMTP relay port" "25")
smtp_tls=$(prompt "Use SMTP STARTTLS (true/false)" "false")
[ -n "$shared_username" ] && [ -n "$email_to" ] && [ -n "$smtp_host" ] || { echo "Username, failure email, and SMTP host are required." >&2; exit 1; }

install -d -m 0755 /opt/generic-json-v2-dti-synthetic
install -d -m 0700 /etc/generic-json-v2-dti-synthetic
install -m 0755 generic_json_v2_dti_synthetic.py /opt/generic-json-v2-dti-synthetic/
install -m 0644 generic-json-v2-dti-synthetic@.service /etc/systemd/system/
install -m 0644 generic-json-v2-dti-synthetic@.timer /etc/systemd/system/

index=1
while [ "$index" -le 4 ]; do
  env_file="/etc/generic-json-v2-dti-synthetic/$index.env"
  name=$(prompt "Environment $index label" "production-$index")
  url=$(prompt "Environment $index ServiceNow URL" "$(existing_value "$env_file" SN_INSTANCE_URL)")
  password=$(prompt_secret "Environment $index password")
  password_b64=$(encode "$password")
  [ -n "$password" ] || password_b64=$(existing_value "$env_file" SN_PASSWORD_B64)
  [ -n "$url" ] && [ -n "$password_b64" ] || { echo "URL and initial password are required for environment $index." >&2; exit 1; }
  umask 077
  {
    printf 'SN_INSTANCE_URL="%s"\n' "$(escape_env "$url")"
    printf 'SN_USERNAME_B64="%s"\n' "$(encode "$shared_username")"
    printf 'SN_PASSWORD_B64="%s"\n' "$password_b64"
    printf 'DTI_ENVIRONMENT_NAME="%s"\n' "$(escape_env "$name")"
    printf 'DTI_ASSIGNMENT_GROUP="%s"\n' "$(escape_env "$assignment_group")"
    printf 'DTI_FAILURE_EMAIL_TO="%s"\n' "$(escape_env "$email_to")"
    printf 'DTI_FAILURE_EMAIL_FROM="%s"\n' "$(escape_env "$email_from")"
    printf 'DTI_SMTP_HOST="%s"\nDTI_SMTP_PORT="%s"\nDTI_SMTP_STARTTLS="%s"\n' "$(escape_env "$smtp_host")" "$(escape_env "$smtp_port")" "$(escape_env "$smtp_tls")"
    printf 'DTI_CONNECTOR_SOURCE="genericJsonV2"\nDTI_EVENT_SOURCE="Generic JSON V2 DTI Synthetic"\n'
  } > "$env_file"
  chmod 0600 "$env_file"
  index=$((index + 1))
done

systemctl daemon-reload
for index in 1 2 3 4; do
  systemctl enable "generic-json-v2-dti-synthetic@$index.timer"
  systemctl restart "generic-json-v2-dti-synthetic@$index.timer"
done
echo "Installed or updated four five-minute synthetic timers."
