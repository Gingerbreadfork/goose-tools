#!/usr/bin/env bash
# One-shot server health report, readable without root. Used by the server-health recipe.
# Env: OPENAI_BASE_URL (model server to health-check), HEALTH_CONTAINERS (space-separated container names), HEALTH_USER_UNITS
H="${OPENAI_BASE_URL:-http://127.0.0.1:8080/v1}"; H="${H%/v1}"
CONTAINERS="${HEALTH_CONTAINERS:-}"; UNITS="${HEALTH_USER_UNITS:-goose-serve}"
echo "== $(hostname) health $(date '+%a %d %b %Y %H:%M %Z') =="
echo "uptime: $(uptime -p | sed 's/^up //') | load: $(cut -d' ' -f1-3 /proc/loadavg)"
echo "reboot required: $(test -f /var/run/reboot-required && echo YES || echo no)"
echo
echo "-- disk --"; df -h --output=target,size,used,avail,pcent / /srv 2>/dev/null | sed 1d | sort -u
echo "-- memory --"; free -g | awk 'NR==2{printf "ram: %s/%s GiB used, %s GiB available\n",$3,$2,$7} NR==3{printf "swap: %s/%s GiB used\n",$3,$2}'
g=$(cat /sys/class/drm/card*/device/mem_info_gtt_used 2>/dev/null | sort -n | tail -1); [ -n "$g" ] && echo "gpu gtt in use: $(numfmt --to=iec $g)"
echo "-- temperatures --"; for h in /sys/class/hwmon/hwmon*; do n=$(cat $h/name 2>/dev/null); t=$(cat $h/temp1_input 2>/dev/null); [ -n "$t" ] && case $n in k10temp|amdgpu|nvme) printf "%s: %dC  " "$n" $((t/1000));; esac; done; echo
echo "-- services --"
f=$(systemctl --failed --no-legend --plain | awk "{print \$1}" | tr "\n" " "); echo "failed system units: ${f:-none}"
fu=$(systemctl --user --failed --no-legend --plain | awk "{print \$1}" | tr "\n" " "); echo "failed user units: ${fu:-none}"
for u in $UNITS; do printf "%s: %s  " "$u" "$(systemctl --user is-active "$u" 2>/dev/null)"; done; echo
echo "model server /health: $(curl -s -m 8 $H/health | head -c 120 || echo UNREACHABLE)"
echo "-- containers --"
if [ -n "$CONTAINERS" ]; then for c in $CONTAINERS; do echo "$c: $(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo missing)"; done; fi
echo "containers total: $(docker ps -a -q 2>/dev/null | wc -l) (running: $(docker ps -q 2>/dev/null | wc -l))"
echo "-- security (last 24h) --"
echo "ssh failed logins: $(journalctl -u ssh --since '24 hours ago' --no-pager 2>/dev/null | grep -ci 'failed password\|invalid user')"
echo "fail2ban bans: $(journalctl -u fail2ban --since '24 hours ago' --no-pager 2>/dev/null | grep -c ' Ban ')"
echo "ssh logins ok: $(journalctl -u ssh --since '24 hours ago' --no-pager 2>/dev/null | grep -c 'Accepted ')"
echo "-- updates --"
echo "last apt run: $(grep -E '^Start-Date' /var/log/apt/history.log 2>/dev/null | tail -1 | cut -d' ' -f2-3)"
echo "upgradable packages: $(apt list --upgradable 2>/dev/null | grep -c upgradable)"
echo "-- errors in system journal (last 24h, top 5) --"
journalctl -p err --since '24 hours ago' --no-pager -o cat 2>/dev/null | sed -E 's/[0-9]+/N/g' | sort | uniq -c | sort -rn | head -5 | cut -c1-140
