#!/bin/bash
#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


THIS=$(basename "$0")
SOURCES_DIR="$(realpath ../)"
MANUAL_VERSION_INPUT="$SOURCES_DIR/version"
VERSION_FILE="$SOURCES_DIR/.metadata/cas_version"
SUBMODULES=(
    "ocf"
)


warning() {
    echo -e "\e[33mWARNING\e[0m: $THIS: $*" >&2
}

error() {
    echo -e "\e[31mERROR\e[0m: $THIS: $*" >&2
    exit 1
}


# Check if we're inside a git repository
if [[ -d "$SOURCES_DIR/.git" ]] && which git &>/dev/null &&\
        (cd "$SOURCES_DIR" && git rev-parse --is-inside-work-tree &>/dev/null); then
    if [[ ! -r "$MANUAL_VERSION_INPUT" ]]; then
        error "can't read version input file '$MANUAL_VERSION_INPUT'"
    fi
    . "$MANUAL_VERSION_INPUT"
    if [[ ! "$CAS_VERSION_MAIN" || ! "$CAS_VERSION_MAJOR" || ! "$CAS_VERSION_MINOR" ]]; then
        error "'$MANUAL_VERSION_INPUT' - wrong version input file format;"\
            "file should contain CAS_VERSION_MAIN, CAS_VERSION_MAJOR and CAS_VERSION_MINOR"\
            "variables along with their respective values"
    fi

    CAS_VERSION_BUILD=$(cd "$SOURCES_DIR" && git log --merges --oneline | wc -l)
    LAST_COMMIT_HASH=$(cd "$SOURCES_DIR" && git log -1 --pretty=format:%H)
    LAST_COMMIT_HASH_ABBR=$(cd "$SOURCES_DIR" && git log -1 --pretty=format:%h)
    LAST_COMMIT_DATE=$(cd "$SOURCES_DIR" && git log -1 --pretty=format:%ci |\
                       sed "s/ /T/" | sed "s/ //" | sed "s/00$/:00/")
    LAST_COMMIT_TIMESTAMP=$(cd "$SOURCES_DIR" && git log -1 --pretty=format:%ct)
    for SUBMOD in ${SUBMODULES[@]}; do
        LAST_SUB_COMMIT_HASHES+=($(cd "$SOURCES_DIR/$SUBMOD" && git log -1 --pretty=format:%H))
        LAST_SUB_COMMIT_HASHES_ABBR+=($(cd "$SOURCES_DIR/$SUBMOD" && git log -1 --pretty=format:%h))
    done
    if [[ $(cd "$SOURCES_DIR" && git tag --points-at HEAD) ]]; then
        CAS_VERSION_RELEASE="release"
    elif [[ $(cd "$SOURCES_DIR" && git log -1 --pretty=format:%H)\
            == $(cd "$SOURCES_DIR" && git log -1 --merges --pretty=format:%H) ]]; then
        CAS_VERSION_RELEASE="master"
    else
        CAS_VERSION_RELEASE="devel"
    fi

    CAS_VERSION=$(printf "%02d.%02d.%01d.%04d.%s" $CAS_VERSION_MAIN $CAS_VERSION_MAJOR\
                $CAS_VERSION_MINOR $CAS_VERSION_BUILD $CAS_VERSION_RELEASE)

    mkdir -p $(dirname "$VERSION_FILE")
    if ! touch "$VERSION_FILE"; then
        error "couldn't create version file '$VERSION_FILE'"
    fi
    echo "CAS_VERSION_MAIN=$CAS_VERSION_MAIN" > "$VERSION_FILE"
    echo "CAS_VERSION_MAJOR=$CAS_VERSION_MAJOR" >> "$VERSION_FILE"
    echo "CAS_VERSION_MINOR=$CAS_VERSION_MINOR" >> "$VERSION_FILE"
    echo "CAS_VERSION_BUILD=$CAS_VERSION_BUILD" >> "$VERSION_FILE"
    echo "CAS_VERSION_RELEASE=$CAS_VERSION_RELEASE" >> "$VERSION_FILE"
    echo "CAS_VERSION=$CAS_VERSION" >> "$VERSION_FILE"
    echo "LAST_COMMIT_HASH=$LAST_COMMIT_HASH" >> "$VERSION_FILE"
    echo "LAST_COMMIT_HASH_ABBR=$LAST_COMMIT_HASH_ABBR" >> "$VERSION_FILE"
    echo "LAST_COMMIT_DATE=$LAST_COMMIT_DATE" >> "$VERSION_FILE"
    echo "LAST_COMMIT_TIMESTAMP=$LAST_COMMIT_TIMESTAMP" >> "$VERSION_FILE"
    echo "LAST_SUB_COMMIT_HASHES=(${LAST_SUB_COMMIT_HASHES[@]})" >> "$VERSION_FILE"
    echo "LAST_SUB_COMMIT_HASHES_ABBR=(${LAST_SUB_COMMIT_HASHES_ABBR[@]})" >> "$VERSION_FILE"
    FILE_CREATION_DATE=$(date --iso-8601=seconds)
    FILE_CREATION_TIMESTAMP=$(date +%s)
    echo "FILE_CREATION_DATE=$FILE_CREATION_DATE" >> "$VERSION_FILE"
    echo "FILE_CREATION_TIMESTAMP=$FILE_CREATION_TIMESTAMP" >> "$VERSION_FILE"
elif [[ -r "$VERSION_FILE" ]]; then
    . "$VERSION_FILE" >/dev/null
    if [[ ! "$CAS_VERSION" ]]; then
        error "'$VERSION_FILE' - wrong version file format; file does not contain CAS_VERSION"
    fi
else
    error "couldn't obtain CAS version - no git tree nor readable version file found"
fi

# Check if this script was called during building of OpenCAS...
if [[ "$1" == "build" ]]; then
    if ! touch "$VERSION_FILE"; then
        warning "couldn't edit version file '$VERSION_FILE'"
    fi
    # ...and if so, add (or substitute if exist) a build time to version file
    CAS_BUILD_DATE=$(date --iso-8601=seconds)
    CAS_BUILD_TIMESTAMP=$(date +%s)
    if grep CAS_BUILD_DATE "$VERSION_FILE" &>/dev/null; then
        sed -i "s/CAS_BUILD_DATE=.*/CAS_BUILD_DATE=$CAS_BUILD_DATE/" "$VERSION_FILE"
        sed -i "s/CAS_BUILD_TIMESTAMP=.*/CAS_BUILD_TIMESTAMP=$CAS_BUILD_TIMESTAMP/" "$VERSION_FILE"
    else
        echo "CAS_BUILD_DATE=$CAS_BUILD_DATE" >> "$VERSION_FILE"
        echo "CAS_BUILD_TIMESTAMP=$CAS_BUILD_TIMESTAMP" >> "$VERSION_FILE"
    fi
fi
