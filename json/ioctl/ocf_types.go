/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
 */

package ioctl

var ocf_cache_state_str = [...]string{"running", "stopping", "initializing", "incomplete", "max"}
var ocf_core_state_str = [...]string{"active", "inactive", "max"}
var ocf_cache_mode_str = [...]string{"wt", "wb", "wa", "pt", "wi", "wo", "max"}
var ocf_cleaning_str = [...]string{"nop", "alru", "acp", "max"}
var metadata_mode_str = [...]string{"invalid", "normal", "atomic"}
var ocf_seq_cutoff_policy_str = [...]string{"always", "full", "never", "max"}
var ocf_promotion_str = [...]string{"always", "nhit", "max"}
