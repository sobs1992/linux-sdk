#!/bin/sh
# apps-config.sh: Buildroot settings for the applications of a firmware config.
#
#   apps-config.sh fragment EXTERNAL "APPS" "APPS_AUTOSTART" "APPS_CONFIG"
#       Print a defconfig fragment: every application package of the
#       BR2_EXTERNAL tree is either enabled (listed in APPS) or disabled.
#   apps-config.sh strip EXTERNAL FILE
#       Remove the application lines from a saved defconfig: they belong to
#       the firmware config, not to the board's Buildroot defconfig.
#   apps-config.sh list EXTERNAL
#       Application packages and what they support.
#   apps-config.sh changed EXTERNAL OLD NEW
#       Applications whose lines differ between two fragments.
#   apps-config.sh purge ROOTFS_OUT PACKAGE
#       Remove the files a package installed from Buildroot's target/.
#       Buildroot never does that itself, so a disabled application or a
#       switched-off autostart would otherwise stay in the rootfs.
#   apps-config.sh dropped ROOTFS_OUT OLD.config NEW.config
#       Packages (any, not only applications) that were BR2_PACKAGE_X=y in
#       the old .config, are not in the new one and have files in target/
#       (Buildroot's packages-file-list.txt): what to purge after a
#       reconfiguration. Nothing if there is no old .config.
#
# An application package is a package of EXTERNAL/package/ whose sources
# come from apps/ (its *_SITE points there). APPS and APPS_AUTOSTART hold
# package names (bare-app, oga-pad); APPS_CONFIG holds package options as
# "package.OPTION=value", e.g. bare-app.DEFCONFIG=oga_minimal_defconfig for
# BR2_PACKAGE_BARE_APP_DEFCONFIG.
set -e

die() { echo "apps-config: $*" >&2; exit 1; }

symbol() { echo "BR2_PACKAGE_$(echo "$1" | tr 'a-z-' 'A-Z_')"; }

apps() {
	for mk in "$1"/package/*/*.mk; do
		if grep -qE '_SITE[[:space:]]*=.*/apps/' "$mk"; then
			basename "$(dirname "$mk")"
		fi
	done
}

# type of a Kconfig symbol in the package's Config.in, empty if not defined there
symtype() {
	awk -v sym="config $2" '
		$0 == sym { found = 1; next }
		found && $1 ~ /^(bool|string|int|hex|tristate)$/ { print $1; exit }
		found && /^config / { exit }' "$1/package/$3/Config.in"
}

contains() {
	for w in $1; do [ "$w" = "$2" ] && return 0; done
	return 1
}

# lines of one application in a fragment, without those of an application
# whose symbol extends this one (bare-app vs bare-app-games)
app_lines() {
	others=
	for o in $known; do
		case $(symbol "$o") in "$(symbol "$1")"_*) others="$others|$(symbol "$o")" ;; esac
	done
	grep -E "^(# )?$(symbol "$1")(_[A-Z0-9_]+)?( is not set|=)" "$2" 2>/dev/null | {
		if [ -n "$others" ]; then
			grep -vE "^(# )?(${others#|})(_[A-Z0-9_]+)?( is not set|=)"
		else
			cat
		fi
	} || true
}

cmd=$1
if [ "$cmd" = purge ]; then
	out=$2 pkg=$3 list=$2/build/packages-file-list.txt
	[ -f "$list" ] || exit 0
	# only the files no other package installed too (alsa-lib and alsa-utils
	# both bring /usr/share/alsa/*.conf): the other one stays and is not
	# installed again. Buildroot keeps the list from the last target-finalize;
	# a package rebuilt by hand (X-rebuild, X-reinstall) has an empty one
	# until its next configure, so its files are not found then.
	awk -F, -v pkg="$pkg" '{ path = substr($0, length($1) + 2); owners[path]++;
			if ($1 == pkg) mine[path] = 1 }
		END { for (p in mine) if (owners[p] == 1) print p }' "$list" | while read -r f; do
		[ -f "$out/target/$f" ] || [ -L "$out/target/$f" ] || continue
		rm -f "$out/target/$f"
	done
	exit 0
fi
if [ "$cmd" = dropped ]; then
	out=$2 old=$3 new=$4 list=$2/build/packages-file-list.txt
	[ -f "$old" ] && [ -f "$new" ] && [ -f "$list" ] || exit 0
	tmp=$(mktemp -d)
	# the package names of the file list by their symbols: the symbol of
	# "sdl2_mixer" and of a would-be "sdl2-mixer" is the same
	cut -d, -f1 "$list" | LC_ALL=C sort -u | while read -r pkg; do
		echo "$(symbol "$pkg") $pkg"
	done | LC_ALL=C sort > "$tmp/pkgs"
	grep -E '^BR2_PACKAGE_[A-Z0-9_]+=y$' "$old" | sed 's/=y$//' | LC_ALL=C sort > "$tmp/was"
	grep -E '^BR2_PACKAGE_[A-Z0-9_]+=y$' "$new" | sed 's/=y$//' | LC_ALL=C sort > "$tmp/is"
	LC_ALL=C comm -23 "$tmp/was" "$tmp/is" | LC_ALL=C join - "$tmp/pkgs" | cut -d' ' -f2
	rm -rf "$tmp"
	exit 0
fi
ext=$2
[ -d "$ext/package" ] || die "no BR2_EXTERNAL tree at '$ext'"
known=$(apps "$ext")

case $cmd in
fragment)
	want=$3 auto=$4 opts=$5
	for a in $want; do
		contains "$known" "$a" || die "APPS: unknown application '$a' (known: $(echo $known))"
	done
	for a in $auto; do
		contains "$want" "$a" || die "APPS_AUTOSTART: '$a' is not in APPS"
		[ "$(symtype "$ext" "$(symbol "$a")_AUTOSTART" "$a")" = bool ] ||
			die "APPS_AUTOSTART: '$a' cannot start at boot (no $(symbol "$a")_AUTOSTART)"
	done
	for a in $known; do
		sym=$(symbol "$a")
		if contains "$want" "$a"; then
			echo "$sym=y"
			if [ "$(symtype "$ext" "${sym}_AUTOSTART" "$a")" = bool ]; then
				contains "$auto" "$a" && echo "${sym}_AUTOSTART=y" ||
					echo "# ${sym}_AUTOSTART is not set"
			fi
		else
			echo "# $sym is not set"
		fi
	done
	for o in $opts; do
		a=${o%%.*} rest=${o#*.}
		opt=${rest%%=*} val=${rest#*=}
		[ "$a" != "$o" ] && [ "$opt" != "$rest" ] || die "APPS_CONFIG: '$o' is not package.OPTION=value"
		contains "$want" "$a" || die "APPS_CONFIG: '$a' is not in APPS"
		sym=$(symbol "$a")_$opt
		case $(symtype "$ext" "$sym" "$a") in
		string) echo "$sym=\"$val\"" ;;
		bool)   [ "$val" = y ] && echo "$sym=y" || echo "# $sym is not set" ;;
		int|hex) echo "$sym=$val" ;;
		*)      die "APPS_CONFIG: '$a' has no option $sym" ;;
		esac
	done
	;;
strip)
	file=$3
	for a in $known; do
		sym=$(symbol "$a")
		sed -i -E "/^(# )?${sym}(_[A-Z0-9_]+)?( is not set|=)/d" "$file"
	done
	;;
changed)
	old=$3 new=$4
	[ -f "$old" ] || exit 0		# first configuration: nothing to compare
	for a in $known; do
		[ "$(app_lines "$a" "$old")" = "$(app_lines "$a" "$new")" ] || echo "$a"
	done
	;;
list)
	for a in $known; do
		sym=$(symbol "$a")
		extra=
		[ "$(symtype "$ext" "${sym}_AUTOSTART" "$a")" = bool ] && extra=" autostart"
		opts=$(awk -v p="config ${sym}_" 'index($0, p) == 1 { sub(p, ""); print }' \
			"$ext/package/$a/Config.in" | grep -v '^AUTOSTART$' | xargs)
		echo "$a$extra${opts:+ options: $opts}"
	done
	;;
*)
	die "usage: apps-config.sh fragment|strip|list|changed EXTERNAL ... | purge ROOTFS_OUT PACKAGE | dropped ROOTFS_OUT OLD NEW"
	;;
esac
