#!/bin/sh
# Warn about fragment options that did not end up in the final .config
# (usually an unmet dependency). Any symbol prefix: CONFIG_ (U-Boot,
# Linux), BR2_ (Buildroot). Usage: kconfig-check.sh .config frag...
cfg=$1; shift
for frag; do
	grep -E '^([A-Z][A-Za-z0-9_]*=|# [A-Z][A-Za-z0-9_]* is not set$)' "$frag" | while read -r line; do
		case "$line" in
		"# "*)
			sym=${line#\# }; sym=${sym%% *}
			grep -q "^$sym=" "$cfg" && echo "WARNING: ${frag##*/}: $sym is still enabled"
			;;
		*)
			grep -qxF "$line" "$cfg" && continue
			sym=${line%%=*}
			got=$(grep -E "^$sym=|^# $sym is not set" "$cfg" || echo "not available")
			echo "WARNING: ${frag##*/}: requested $line, got: $got"
			;;
		esac
	done
done
exit 0
