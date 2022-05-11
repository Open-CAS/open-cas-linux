#!/bin/bash
#
# Copyright(c) 2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

VERSION=$1
MERGE=$(echo "$VERSION" | cut -d. -f 4)
SHA=$(git log --merges --oneline | tac | sed "${MERGE}q;d" | cut -d " " -f 1)

[[ -z "$SHA" ]] && exit 1

echo "$SHA"
