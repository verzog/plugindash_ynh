#!/bin/bash

#=================================================
# COMMON VARIABLES AND CUSTOM HELPERS
#=================================================

# Where the code lives inside $install_dir. Only www/ is served by nginx.
#   $install_dir/app/          Python collector (run.py + plugindash/)
#   $install_dir/www/          index.html, app.js, style.css + generated status.json, history.json, metrics
#   $install_dir/config.json   Generated from the app settings; mode 600, holds the tokens
#   $data_dir/history.sqlite   Daily history
#   $data_dir/extensions/      Your own checks (checks/*.py) and alert channels (notify/*.py)

# Fill in any setting that doesn't exist yet (safe on install and upgrade).
plugindash_set_defaults() {
    ynh_app_setting_set_default --key=github_token --value=""
    ynh_app_setting_set_default --key=github_owners --value=""
    ynh_app_setting_set_default --key=include_forks --value=1
    ynh_app_setting_set_default --key=exclude_repos --value=""
    ynh_app_setting_set_default --key=gitlab_enabled --value=0
    ynh_app_setting_set_default --key=gitlab_url --value=""
    ynh_app_setting_set_default --key=gitlab_token --value=""
    ynh_app_setting_set_default --key=disabled_checks --value=""
    ynh_app_setting_set_default --key=severity_overrides --value=""
    ynh_app_setting_set_default --key=stale_days --value=30
    ynh_app_setting_set_default --key=ci_ignore_workflows --value="release.yml"
    ynh_app_setting_set_default --key=timezone --value="UTC"
    ynh_app_setting_set_default --key=run_time --value="06:30"
    ynh_app_setting_set_default --key=alert_on --value="worse"
    ynh_app_setting_set_default --key=ntfy_url --value=""
    ynh_app_setting_set_default --key=ntfy_topic --value=""
    ynh_app_setting_set_default --key=ntfy_token --value=""
    ynh_app_setting_set_default --key=email_to --value=""
    ynh_app_setting_set_default --key=matrix_homeserver --value=""
    ynh_app_setting_set_default --key=matrix_room --value=""
    ynh_app_setting_set_default --key=matrix_token --value=""
    ynh_app_setting_set_default --key=metrics_allow --value="127.0.0.1,::1"
}

# Prints an error if $1 isn't a time zone this server knows (an IANA name such as
# Australia/Brisbane). Used by the install script and the config panel. The character
# check also stops odd input reaching the systemd timer, which uses the time zone.
plugindash_timezone_error() {
    if [[ ! "$1" =~ ^[A-Za-z0-9_+/-]+$ ]] || [ ! -f "/usr/share/zoneinfo/$1" ]; then
        echo "Unknown time zone '$1'. Use an IANA name such as Australia/Brisbane."
    fi
}

# Copy the collector and the static page from the package into $install_dir.
# Generated files (status.json, history.json, metrics) are left alone.
plugindash_deploy_code() {
    mkdir -p "$install_dir/app" "$install_dir/www" "$data_dir/extensions/checks" "$data_dir/extensions/notify"
    ynh_safe_rm "$install_dir/app/plugindash"
    cp -r "$YNH_APP_BASEDIR/sources/plugindash" "$install_dir/app/plugindash"
    cp "$YNH_APP_BASEDIR/sources/run.py" "$install_dir/app/run.py"
    find "$install_dir/app" -name "__pycache__" -type d -prune -exec rm -rf {} +
    local static
    for static in index.html app.js style.css favicon.svg; do
        cp "$YNH_APP_BASEDIR/sources/www/$static" "$install_dir/www/$static"
    done
    if [ ! -e "$data_dir/extensions/README.md" ]; then
        cp "$YNH_APP_BASEDIR/sources/extensions-example/README.md" "$data_dir/extensions/README.md"
        cp "$YNH_APP_BASEDIR/sources/extensions-example/checks/example_changes_file.py.disabled" \
            "$data_dir/extensions/checks/example_changes_file.py.disabled"
    fi
    plugindash_fix_permissions
}

plugindash_fix_permissions() {
    # Code: owned by root, readable by the app user only.
    chown -R root:"$app" "$install_dir/app"
    chmod -R u=rwX,g=rX,o= "$install_dir/app"
    # Web root: the app writes, nginx (www-data) reads. setgid keeps new files in the www-data group.
    chown -R "$app:www-data" "$install_dir/www"
    chmod 2750 "$install_dir/www"
    find "$install_dir/www" -type f -exec chmod 640 {} +
    # Install folder: root-owned so the app user can't swap out its own code.
    # 751 lets the app user and nginx pass through to the parts each one needs.
    chown root:www-data "$install_dir"
    chmod 751 "$install_dir"
    # Data: the app only.
    chown -R "$app:$app" "$data_dir"
    chmod -R u=rwX,g=rX,o= "$data_dir"
}

# Build config.json from the app settings. Values are passed as environment
# variables and written by Python, so quotes or commas in tokens can't break the JSON.
plugindash_write_config() {
    local public_url="https://$domain${path%/}/"
    local dest="$install_dir/config.json"
    env -i PATH=/usr/bin:/bin \
        PD_PUBLIC_URL="$public_url" \
        PD_TIMEZONE="$timezone" \
        PD_WWW_DIR="$install_dir/www" \
        PD_DATA_DIR="$data_dir" \
        PD_EXTENSIONS_DIR="$data_dir/extensions" \
        PD_GITHUB_ENABLED=1 \
        PD_GITHUB_TOKEN="$github_token" \
        PD_GITHUB_OWNERS="$github_owners" \
        PD_INCLUDE_FORKS="$include_forks" \
        PD_EXCLUDE_REPOS="$exclude_repos" \
        PD_GITLAB_ENABLED="$gitlab_enabled" \
        PD_GITLAB_URL="$gitlab_url" \
        PD_GITLAB_TOKEN="$gitlab_token" \
        PD_DISABLED_CHECKS="$disabled_checks" \
        PD_SEVERITY_OVERRIDES="$severity_overrides" \
        PD_STALE_DAYS="$stale_days" \
        PD_CI_IGNORE_WORKFLOWS="$ci_ignore_workflows" \
        PD_ALERT_ON="$alert_on" \
        PD_NTFY_URL="$ntfy_url" \
        PD_NTFY_TOPIC="$ntfy_topic" \
        PD_NTFY_TOKEN="$ntfy_token" \
        PD_EMAIL_TO="$email_to" \
        PD_EMAIL_FROM="$app@$domain" \
        PD_MATRIX_HOMESERVER="$matrix_homeserver" \
        PD_MATRIX_ROOM="$matrix_room" \
        PD_MATRIX_TOKEN="$matrix_token" \
        python3 -I "$install_dir/app/run.py" write-config --output "$dest"
    chown "$app:$app" "$dest"
    chmod 600 "$dest"
}

# Turn the metrics_allow setting into nginx allow/deny lines (one line, so the
# __METRICS_ALLOW_RULES__ placeholder can be replaced safely).
plugindash_metrics_rules() {
    local rules="" entry
    local IFS=","
    for entry in $metrics_allow; do
        entry="$(echo "$entry" | tr -d '[:space:]')"
        [ -n "$entry" ] && rules="${rules}allow ${entry}; "
    done
    echo "${rules}deny all;"
}

plugindash_add_nginx() {
    metrics_allow_rules="$(plugindash_metrics_rules)"
    ynh_config_add_nginx
}

# The collector is a oneshot service started by a daily timer. A second, always-on
# service (plugindash-run) is the localhost endpoint behind the "Run check now" button.
plugindash_add_systemd() {
    on_calendar="*-*-* ${run_time}:00 ${timezone}"
    # Not ynh_config_add_systemd: that would `enable` the service itself, which has no
    # [Install] section on purpose (only the timer should start it).
    ynh_config_add --template="systemd.service" --destination="/etc/systemd/system/$app.service"
    ynh_config_add --template="systemd.timer" --destination="/etc/systemd/system/$app.timer"
    ynh_config_add --template="systemd-run.service" --destination="/etc/systemd/system/$app-run.service"
    systemctl daemon-reload
    systemctl enable "$app.timer" --quiet
    # Restart so a changed schedule takes effect straight away.
    systemctl restart "$app.timer"
    systemctl enable "$app-run.service" --quiet
    systemctl restart "$app-run.service"
}

plugindash_remove_systemd() {
    if [ -e "/etc/systemd/system/$app.timer" ]; then
        systemctl disable --now "$app.timer" --quiet || true
        ynh_safe_rm "/etc/systemd/system/$app.timer"
    fi
    if [ -e "/etc/systemd/system/$app-run.service" ]; then
        systemctl disable --now "$app-run.service" --quiet || true
        ynh_safe_rm "/etc/systemd/system/$app-run.service"
    fi
    ynh_config_remove_systemd
    systemctl daemon-reload
}
