#!/bin/sh
# Buildroot post-build hook of the ODROID-GO Ultra, after the common one.
#   $1  target dir
# The mdev daemon and the module coldplug start early, in the background
# (the overlay's /etc/init.d/S03mdev): Buildroot's S10mdev would do them a
# second time.
set -e
rm -f "$1/etc/init.d/S10mdev"
