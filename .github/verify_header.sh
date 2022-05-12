#!/bin/bash

#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

# COPYRIGHT_REGEX is lowercase, because the whole line is
# converted to lowercase before test against this regex.
COPYRIGHT_REGEX="(copyright|\(c\))\s*([0-9]{4}(\s*-\s*([0-9]{4}))?)"
LICENSE_REGEX="SPDX-License-Identifier: BSD-3-Clause$"
YEAR=$(date +"%Y")

unset copyright_header license_header

# Read lines until proper copyright and license headers are found.
while read -r line && [[ ! "$copyright_header" || ! "$license_header" ]]; do
	if [[ "${line,,}" =~ $COPYRIGHT_REGEX ]]; then
		# If the fourth regex group (from year range) doesn't exist,
		# use the second regex group instead (from a single year).
		copyright_year=${BASH_REMATCH[4]:-${BASH_REMATCH[2]}}

		if [[ $copyright_year == $YEAR ]]; then
			copyright_header="correct_copyright_header_found"
		fi
	elif [[ "$line" =~ $LICENSE_REGEX ]]; then
		license_header="correct_license_header_found"
	fi
done < "$1"

# Proper copyright and license info were found - all good.
[[ "$copyright_header" && "$license_header" ]] && exit 0

[[ ! "$copyright_header" ]] && echo >&2 "error: file '$1' does not contain any appropriate copyright info"
[[ ! "$license_header" ]] && echo >&2 "error: file '$1' does not contain appropriate license identifier"
exit 1
