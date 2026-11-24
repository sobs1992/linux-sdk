# keep-sectors.sh (sourced by flash.sh): the image written to a device,
# and the sectors of the device that belong to the unit, not to the image,
# kept when an image is written over them. KEEP="SECTOR:PREFIX ...": a
# sector the write covers whose content starts with PREFIX (the GO Ultra's
# DDR tune line, configs/ogu_defconfig IMAGE_KEEP_SECTORS) is read before
# the write and put back after it, also when the write stops half way or
# a signal ends it (flash.sh: keep_traps). $SUDO runs dd (flash.sh: sudo;
# scripts/test-ddr-tune.py: nothing, on files).

KEPT_SECTORS=()
KEPT_FILES=()
KEPT_DEV=
KEPT_DUE=	# 1: kept sectors read, the image may be over them, not written back yet

# keep_check: KEEP's entries are SECTOR:PREFIX (before anything is asked)
keep_check() {
	local k s prefix
	for k in ${KEEP:-}; do
		s=${k%%:*} prefix=${k#*:}
		if ! [[ $s =~ ^[0-9]+$ ]] || [ -z "$prefix" ] || [ "$prefix" = "$k" ]; then
			echo "flash: KEEP entry '$k' is not SECTOR:PREFIX" >&2
			return 1
		fi
	done
}

# keep_read DEV BYTES START: the KEEP sectors that BYTES written at sector
# START cover and that hold their prefix, each copied to a file of its own
keep_read() {
	local dev=$1 bytes=$2 start=$3 k s prefix end f
	keep_check || return 1
	KEPT_DEV=$dev
	end=$(( start + (bytes + 511) / 512 ))
	for k in ${KEEP:-}; do
		s=${k%%:*} prefix=${k#*:}
		[ "$s" -ge "$start" ] && [ "$s" -lt "$end" ] || continue
		f=$(mktemp)
		KEPT_FILES+=("$f")
		$SUDO dd if="$dev" of="$f" bs=512 skip="$s" count=1 status=none || return 1
		if printf '%s' "$prefix" | cmp -s -n "${#prefix}" - "$f"; then
			echo "Keeping sector $s of $dev: $(tr -d '\0' < "$f" | tr '\n' ' ')"
			KEPT_SECTORS+=("$s")
		else
			KEPT_SECTORS+=("")
		fi
	done
	[ -z "${KEPT_SECTORS[*]}" ] || KEPT_DUE=1
}

# keep_write: the sectors keep_read kept, back where they were
keep_write() {
	local i
	for i in "${!KEPT_FILES[@]}"; do
		[ -n "${KEPT_SECTORS[$i]}" ] || continue
		$SUDO dd if="${KEPT_FILES[$i]}" of="$KEPT_DEV" bs=512 seek="${KEPT_SECTORS[$i]}" count=1 \
			conv=notrunc,fsync status=none || return 1
	done
	KEPT_DUE=
}

# keep_finish STATUS (the EXIT trap): kept sectors not written back yet (a
# write that failed, a signal: bash runs the trap once dd has ended) go back
# now; if they cannot, their files stay and what they hold is said in full.
# Then the files go. Not $?: after a signal the EXIT trap sees 0.
keep_finish() {
	local st=$1 i f
	trap - EXIT INT TERM HUP
	if [ -n "$KEPT_DUE" ]; then
		[ "$st" -ne 0 ] || st=1
		if keep_write; then
			echo "flash: the write stopped; the kept sectors are back on $KEPT_DEV" >&2
		else
			for i in "${!KEPT_FILES[@]}"; do
				[ -n "${KEPT_SECTORS[$i]}" ] || continue
				echo "flash: sector ${KEPT_SECTORS[$i]} could not be put back; it is kept in" \
					"${KEPT_FILES[$i]}: $(tr -d '\0' < "${KEPT_FILES[$i]}" | tr '\n' ' ')" >&2
				KEPT_FILES[$i]=
			done
		fi
	fi
	for f in "${KEPT_FILES[@]}"; do
		[ -z "$f" ] || rm -f -- "$f"
	done
	KEPT_FILES=()
	KEPT_SECTORS=()
	return "$st"
}

# keep_traps: the trap a script that calls flash_write sets first (bash
# runs it at every exit, after a signal too, once dd has ended)
keep_traps() {
	trap 'keep_finish $?' EXIT
}

# flash_write FILE DEV SECTOR: FILE onto DEV at SECTOR, the KEEP sectors
# it covers kept (the caller has set keep_traps)
flash_write() {
	local file=$1 dev=$2 sector=$3
	keep_read "$dev" "$(stat -c %s "$file")" "$sector"
	$SUDO dd if="$file" of="$dev" bs=4M seek=$(( sector * 512 )) oflag=seek_bytes conv=notrunc,fsync \
		status="${DD_STATUS:-progress}"
	keep_write
}
