/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

package ioctl

import (
	"encoding/json"
	"fmt"
)

/** Marshal GoStructs into JSON **/

func Marshal_kcas_stats(kstats Kcas_get_stats) ([]byte, error) {
	kstats_b, err := json.MarshalIndent(kstats, "", "  ")
	fmt.Println("Statistics: ", string(kstats_b), "\n")
	return kstats_b, err
}

func Marshal_kcache_info(kcache_info Kcas_cache_info) ([]byte, error) {
	kcache_info_b, err := json.MarshalIndent(kcache_info, "", "  ")
	fmt.Println("Cache info: ", string(kcache_info_b), "\n")
	return kcache_info_b, err
}

func Marshal_kcore_info(kcore_info Kcas_core_info) ([]byte, error) {
	kcore_info_b, err := json.MarshalIndent(kcore_info, "", "  ")
	fmt.Println("Core info: ", string(kcore_info_b), "\n")
	return kcore_info_b, err
}

func Marshal_kio_class(kio_class Kcas_io_class) ([]byte, error) {
	kio_class_b, err := json.MarshalIndent(kio_class, "", "  ")
	fmt.Println("IO class", string(kio_class_b), "\n")
	return kio_class_b, err
}
