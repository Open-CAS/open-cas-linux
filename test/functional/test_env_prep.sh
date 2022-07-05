#!/bin/bash
#
# Copyright(c) 2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#


########## Configuration section (edit those values if needed):

# git repo URLs and destination directories (relative to sources root dir)
OPEN_CAS_GIT_REPO="https://github.com/Open-CAS/open-cas-linux.git"
TEST_FRAMEWORK_GIT_REPO="https://github.com/intel-innersource/frameworks.validation.opencas.test-framework.git"
TEST_FRAMEWORK_PLUGIN_GIT_REPO="https://github.com/intel-innersource/frameworks.validation.opencas.test-framework-plugins.git"
SUPERRUNNER_GIT_REPO="https://github.com/Open-CAS/superrunner4000.git"
TEST_FRAMEWORK_PATH="test/functional/test-framework"
TEST_FRAMEWORK_PLUGIN_PATH="test/functional/lib/external_plugins"
SUPERRUNNER_PATH="test/functional/superrunner4000"
# Python's requirements files locations (without external repo's)
REQ_FILES=(
	"requirements.txt"
	"test/functional/requirements.txt"
)
# pytest options
PYTEST_OPTS="-s -p no:warnings"
PYTEST_CONFIG_FILE="test/functional/pytest.ini"
# username for remote test execution platforms
REMOTE_USER="root"
# tools needed by this script
DEPS=(git grep pip sed ssh)

##########


set -e

unset sources_dir no_clone force get_cas_sources

this=$(basename "$0")

usage() {
	echo "Usage:"
	echo "	./$this [options] <dut_config.yml>"
	echo "	./$this -h/--help"
}

print_help() {
	echo "Test environment prepare for Open CAS Linux."
	usage
	echo
	echo "This script prapares the environment for local or remote Open CAS Linux"
	echo "tests execution. It reads given dut_config.yml file to determine the"
	echo "test execution type and remote IPs if needed, so you need to supply a"
	echo "pre-configured dut_config.yml file. Check the example config file"
	echo "(test/functional/config/example_dut_config.yml) for more info."
	echo
	echo "Options:"
	echo "  -s, --sources-dir <DIR>    use Open CAS Linux sources from DIR, instead"
	echo "                             of the current ones; if DIR doesn't contain"
	echo "                             proper sources or doesn't exist, sources are"
	echo "                             cloned from remote git repository"
	echo "  -n, --no-clone             don't clone any git repos; this is useful if"
	echo "                             you want to reconfigure your environment"
	echo "                             without overwriting any of your existing repos"
	echo "                             (as opposite to --force option)"
	echo "  -f, --force                WARNING: removes test-framework and other repos"
	echo "                             directories and fetches fresh git sources"
	echo "  -h, --help                 print this help message"
	echo
}

invalid_usage() {
	>&2 echo -e "$this: $*\nTry './$this --help' for more information."
	exit 2
}

error() {
	>&2 echo -e "\e[31mERROR\e[0m: $this: $*"
	exit 1
}

info() {
	echo -e "\e[33m$*\e[0m"
}

quit() {
	[ $2 -ne 0 ] && error "command '$1' exits with status $2"
	exit 0
}

check_config() {
	[ "$config" ] || invalid_usage "no dut_config.yml file given"

	while IFS= read -r line; do
		if [[ "$line" =~ ^"type: " ]]; then
			test_exec_type=${line#*: }
		elif [[ "$line" =~ ^"ip: " ]]; then
			local ip=${line#*: }; ip=${ip//\"}
			test_exec_remote_ip+=($ip)
		fi
	done < "$config"

	if [[ "$test_exec_type" =~ "local" ]]; then
		return
	elif [[ "$test_exec_type" =~ "ssh" ]]; then
		if [ ${#test_exec_remote_ip[@]} -eq 0 ]; then
			error "$config: no IP found for remote test execution"
		fi
	else
		error "$config: couldn't determine test execution type"
	fi
}

check_rootdir() {
	if [ "$sources_dir" ]; then
		rootdir="$sources_dir"
	elif git -C $(dirname "$0") rev-parse --is-inside-work-tree &>/dev/null; then
		rootdir=$(git -C $(dirname "$0") rev-parse --show-toplevel)
	else
		# if other methods fail, assume that this script
		# is located in 'test/functional/' directory
		rootdir=$(dirname $(dirname $(dirname $(realpath "$0"))))
	fi

	if [ -f "$rootdir" ] || [[ -d "$rootdir" && ! -w "$rootdir" ]]; then
		invalid_usage "$rootdir: file exists or no write permissions for given directory"
	elif [ ! -e "$rootdir" ] || ! ls -A "$rootdir"/* &>/dev/null; then
		get_cas_sources="get_cas_sources"
		mkdir -p "$rootdir"
	elif [[ $(head -n 1 "$rootdir/README.md" 2>/dev/null) != *Open*CAS*Linux* ]]; then
		get_cas_sources="get_cas_sources"
		local repo_name=${OPEN_CAS_GIT_REPO##*/}; repo_name=${repo_name%.git}
		rootdir="$rootdir/$repo_name"
	fi

	rootdir=$(realpath "$rootdir")
}

check_deps() {
	for dep in ${DEPS[@]}; do
		if ! which $dep &>/dev/null; then
			local failed_deps+="$dep "
		fi
	done

	if [ "$failed_deps" ]; then
		error "some dependencies not found - please provide those first: $failed_deps"
	fi
}

get_cas_sources() {
	echo -e "\n--- Cloning fresh Open CAS Linux sources into $rootdir"

	# remove empty dir to mitigate git cloning issue into existing dir
	if ! ls -A "$rootdir"/* &>/dev/null; then
		rmdir "$rootdir"
	fi

	git clone "$OPEN_CAS_GIT_REPO" "$rootdir"
	git -C "$rootdir" submodule update --init;
}

repo_install() {
	local url="$1"
	local dest="$2"
	local req_file="$rootdir/$dest/requirements.txt"

	echo -e "\n--- Installing git repo and requirements at $dest"

	if [ ! $no_clone ]; then
		if [ $force ]; then
			echo "    --- WARNING: force flag is used - wiping existing repos"
			rm -rf "$rootdir/$dest"
		else
			# remove unnecessary garbage to allow removing an empty directory
			rm -f "$rootdir/$dest/__init__.py"

			# Remove empty directories for git to be able to clone repos into them.
			# If they are not removed (because they are not empty), the next cloning step may fail.
			if [ -d "$rootdir/$dest" ] && ! ls -A "$rootdir/$dest"/* &>/dev/null; then
				rmdir "$rootdir/$dest"
			fi
		fi

		git clone "$url" "$rootdir/$dest"
	fi

	[ -f "$req_file" ] && pip install -r "$req_file"
}

add_global_path() {
	echo -e "\n--- Adding bash global path for superrunner"

	if [ -f ~/.bash_profile ]; then
		local bash_profile_file=~/.bash_profile
	elif [ -f ~/.profile ]; then
		local bash_profile_file=~/.profile
	elif [ -f ~/.bashrc ]; then
		local bash_profile_file=~/.bashrc
	else
		error "no bash profile file found"
	fi

	if ! grep -q "^PATH=" "$bash_profile_file"; then
		echo -e "\nPATH=\$PATH:\$SUPERRUNNER_PATH/bin\nexport PATH" >> "$bash_profile_file"
	elif ! grep -q "^PATH=.*SUPERRUNNER_PATH" "$bash_profile_file"; then
		sed -i "/^PATH=/ s|$|:\$SUPERRUNNER_PATH/bin|" "$bash_profile_file"
	fi
	if grep -q "^SUPERRUNNER_PATH=" "$bash_profile_file"; then
		sed -i "/^SUPERRUNNER_PATH=/ s|.*|SUPERRUNNER_PATH=\"$rootdir/$SUPERRUNNER_PATH\"|" "$bash_profile_file"
	else
		sed -i "/^PATH=/ s|^|SUPERRUNNER_PATH=\"$rootdir/$SUPERRUNNER_PATH\"\n|" "$bash_profile_file"
	fi

	# this sourcing will not work outside this script;
	# need to reload the environment when it finish
	source "$bash_profile_file"

	grep "SUPERRUNNER_PATH" "$bash_profile_file"
}

set_pytest_options() {
	echo -e "\n--- Setting pytest options"

	if grep -q "^addopts = $PYTEST_OPTS" "$rootdir/$PYTEST_CONFIG_FILE"; then
		# skip if already set
		true
	elif grep -q "^addopts =" "$rootdir/$PYTEST_CONFIG_FILE"; then
		# comment out old value and add new, instead of replacing
		sed -i "/^addopts =/ s|^|#|" "$rootdir/$PYTEST_CONFIG_FILE"
		sed -i "/^#addopts =/ s|$|\naddopts = $PYTEST_OPTS|" "$rootdir/$PYTEST_CONFIG_FILE"
	else
		# add if not found at all
		echo -e "addopts = $PYTEST_OPTS" >> "$rootdir/$PYTEST_CONFIG_FILE"
	fi

	grep "^addopts =" "$rootdir/$PYTEST_CONFIG_FILE"
}

add_ssh_keys() {
	local ip_num=$#
	while [ $ip_num -gt 0 ]; do
		local ip_list+=( $1 )
		shift
		((ip_num--))
	done

	echo -e "\n--- Copying pyblic ssh keys to remote platforms: ${ip_list[@]}"

	# create ssh keys if there aren't any
	if [ ! -f ~/.ssh/id_*.pub ]; then
		ssh-keygen -q -t ed25519 -N "" -f ~/.ssh/id_ed25519
	fi

	# copy ssh keys onto remote platforms
	for ip in ${ip_list[@]}; do
		ssh-copy-id -o "ConnectTimeout 30" $REMOTE_USER@$ip
	done
}

while (( $# )); do
	case "$1" in
		--sources-dir|-s)
			sources_dir="$2"
			shift
			;;
		--no-clone|-n)
			no_clone="no_clone"
			;;
		--force|-f)
			force="force"
			;;
		--help|-h)
			print_help
			exit 0
			;;
		*)
			if [ -f "$1" ]; then
				config=$(realpath "$1")
			else
				invalid_usage "option '$1' not recognized"
			fi
			;;
	esac
	shift
done

check_config
check_rootdir
check_deps

trap 'quit "$BASH_COMMAND" "$?"' EXIT


info "\n=== Preparing Open CAS Linux test environment in $rootdir ===\n"

[ $get_cas_sources ] && get_cas_sources

echo -e "\n--- Installing global requirements"
for req_file in "${REQ_FILES[@]}"; do
	pip install -r "$rootdir/$req_file"
done

repo_install "$TEST_FRAMEWORK_GIT_REPO" "$TEST_FRAMEWORK_PATH"
repo_install "$TEST_FRAMEWORK_PLUGIN_GIT_REPO" "$TEST_FRAMEWORK_PLUGIN_PATH"

if [[ "$test_exec_type" =~ "ssh" ]]; then
	repo_install "$SUPERRUNNER_GIT_REPO" "$SUPERRUNNER_PATH"
	add_global_path
	set_pytest_options
	add_ssh_keys ${test_exec_remote_ip[@]}
fi

echo -e "\n\e[32m=== ALL DONE ===\e[0m\n\nNOTE: To make sure your paths are working, please reload your environment (e.g. by logging out and in back again on the terminal).\n"
