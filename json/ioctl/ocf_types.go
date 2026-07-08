/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
 */

package ioctl

// #cgo CFLAGS: -I./../../modules/include/
// #include <cas_ioctl_codes.h>
import "C"

const (
	invalid_cache_id = C.OCF_CACHE_ID_INVALID 
	Invalid_core_id  = C.OCF_CORE_ID_INVALID 
	Invalid_io_class = C.OCF_IO_CLASS_INVALID 
)

/** ocf enum -> string mapping **/

var ocf_cache_state_str = []string{"running", "stopping", "initializing", "incomplete", "passive", "max"}
var ocf_core_state_str = []string{"active", "inactive", "max"}
var ocf_cache_mode_str = []string{"wt", "wb", "wa", "pt", "wi", "wo", "max"}
var ocf_cleaning_policy_str = []string{"nop", "alru", "acp", "max"}
var ocf_seq_cutoff_policy_str = []string{"always", "full", "never", "max"}
var ocf_promotion_str = []string{"always", "nhit", "max"}
