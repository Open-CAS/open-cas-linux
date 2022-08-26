#!/bin/bash
#
# Copyright(c) 2012-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

SCRIPTPATH=`dirname $0`
SCRIPTPATH=`realpath $SCRIPTPATH`
KERNEL_DIR="${KERNEL_DIR:-/lib/modules/$(uname -r)/build/}"
KERNEL_VER="$(cd $KERNEL_DIR; make M=$SCRIPTPATH kernelversion)"
NPROC=`nproc`
DEFINE_FILE=$SCRIPTPATH/modules/generated_defines.h


add_define() {
	printf "#define %s\n" $1 >> $DEFINE_FILE
}

add_function() {
	printf "%s\n" $1 >> $DEFINE_FILE
}

__compile_module(){
	if [ $# -gt 1 ]
	then
		i=2
		while [ "$i" -le "$#" ]; do
			INCLUDE+=$(echo -e "\n#include <${!i}>\\n")
			i=$((i + 1))
		done
	else
		INCLUDE=""
	fi

	test_module_file=$test_module_dir/test_mod.c
	test_module_obj=$test_module_dir/test_mod.o

	mkdir -p $test_module_dir
	cp -f $SCRIPTPATH/configure.d/Makefile $test_module_dir

	############# TEST MODULE #############
	cat > $test_module_file <<- EOF
	#include <linux/module.h>
	#include <linux/kernel.h>
	$INCLUDE

	int init_module(void) {
		$1
		return 0;
	}
	void cleanup_module(void) {};
	MODULE_LICENSE("GPL");
	EOF
	#######################################

	echo "### $1 ###" >> $test_module_log

	make -C $test_module_dir KERNEL_DIR=${KERNEL_DIR} &>> $test_module_log

	return $?
}

compile_module(){
	config_file=$1
	shift

	test_module_dir=$SCRIPTPATH/configure.d/${config_file}_dir
	test_module_log=$SCRIPTPATH/configure.d/.${config_file}.log

	__compile_module $@
	local ret=$?

	rm -Rf $test_module_dir

	if [ $ret -eq 0 ]
	then
		rm -f $test_module_log
	fi

	return $ret
}

get_define(){
	config_file=$1
	define_name=$2
	include=$3
	test_module_dir=$SCRIPTPATH/configure.d/${config_file}_dir
	test_module_log=$SCRIPTPATH/configure.d/.${config_file}.log

	read -r -d '' CODE << EOM
	#define XSTR(x) STR(x)
	#define STR(x) #x
	#pragma message "$define_name " XSTR($define_name)
EOM

	__compile_module "$CODE" "$include"

	rm -Rf $test_module_dir

	grep -Pom 1 "note:.*$define_name .*" $test_module_log | sed 's/[^0-9.]*//g'
	local ret=$?

	rm -f $test_module_log

	return $ret
}

kernel_not_supp_fail() {
	echo "Current kernel is not supported!"
	rm $DEFINE_FILE
	exit 1
}

# $1 - name of function to be called
# $2 - path to file with valid configs
# $3 - name of processed template file
conf_run() {
	local OLD_IFS=$IFS
	IFS='?'

	case "$1" in
		"check") check $2 $3;;
		"apply") apply $2 ;;
	esac

	IFS=$OLD_IFS
}

