# keep-sectors.sh (sourced by flash.sh): the sectors of a device that
# belong to the unit, not to the image, kept when an image is written
# over them. KEEP="SECTOR:PREFIX ...": a sector the write covers whose
# content starts with PREFIX (the GO Ultra's DDR tune line, configs/
# ogu_defconfig IMAGE_KEEP_SECTORS) is read before the write and put back
# after it. $SUDO runs dd (flash.sh: sudo; scripts/test-keep-sectors.sh:
# nothing, on files).

KEPT_SECTORS=()
KEPT_FILES=()

# keep_read DEV BYTES START: the KEEP sectors that BYTES written at sector
# START cover and that hold their prefix, each copied to a file of its own
keep_read() {
	local dev=$1 bytes=$2 start=$3 k s prefix end f
	end=$(( start + (bytes + 511) / 512 ))
	for k in ${KEEP:-}; do
		s=${k%%:*} prefix=${k#*:}
		if ! [[ $s =~ ^[0-9]+$ ]] || [ -z "$prefix" ] || [ "$prefix" = "$k" ]; then
			echo "flash: KEEP entry '$k' is not SECTOR:PREFIX" >&2
			return 1
		fi
		[ "$s" -ge "$start" ] && [ "$s" -lt "$end" ] || continue
		f=$(mktemp)
		KEPT_FILES+=("$f")
		$SUDO dd if="$dev" of="$f" bs=512 skip="$s" count=1 status=none || return 1
		if [ "$(head -c ${#prefix} "$f")" = "$prefix" ]; then
			echo "Keeping sector $s of $dev: $(tr -d '\0' < "$f" | tr '\n' ' ' | head -c 72)"
			KEPT_SECTORS+=("$s")
		else
			KEPT_SECTORS+=("")
		fi
	done
}

# keep_write DEV: the sectors keep_read kept, back where they were
keep_write() {
	local dev=$1 i
	for i in "${!KEPT_FILES[@]}"; do
		[ -n "${KEPT_SECTORS[$i]}" ] || continue
		$SUDO dd if="${KEPT_FILES[$i]}" of="$dev" bs=512 seek="${KEPT_SECTORS[$i]}" count=1 \
			conv=notrunc,fsync status=none || return 1
	done
}

# keep_clean: keep_read's files gone
keep_clean() {
	local f
	for f in "${KEPT_FILES[@]}"; do
		rm -f -- "$f"
	done
	KEPT_FILES=()
	KEPT_SECTORS=()
}
