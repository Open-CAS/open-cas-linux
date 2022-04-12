#!/bin/bash

#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

YEAR=$(date +"%Y")
REGEX="Copyright\(c\) [0-9]{4}-([0-9]{4}) |Copyright\(c\) ([0-9]{4}) "

while read -r line; do
    if [[ "$line" =~ $REGEX ]]; then
        echo ${BASH_REMATCH[0]}
        if [[ $YEAR == ${BASH_REMATCH[1]} || $YEAR == ${BASH_REMATCH[2]} ]]; then
            echo $1 have appropriate license header
            exit 0
        fi
        echo $1 have wrong license header year
    fi
done < "$1"

echo $1 does not contain appropriate license header
exit 1
