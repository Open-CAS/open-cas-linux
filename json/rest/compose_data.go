/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

package rest

import (
	"fmt"

	"example.com/json/ioctl"
)

func List_caches(fd uintptr) {
	fmt.Println("\nLIST_CACHES_WITH_CORES\n")

	C_cache_info := ioctl.Ioctl_cache_info(fd, 1)
	cache_info := ioctl.Conv_cache_info(C_cache_info)
	ioctl.Marshal_kcache_info(cache_info)

	for _, v := range cache_info.Core_id {
		C_kcore_info := ioctl.Ioctl_core_info(fd, cache_info.Cache_id, v)
		kcore_info := ioctl.Conv_core_info(C_kcore_info)
		ioctl.Marshal_kcore_info(kcore_info)
	}
}

func Get_stats(fd uintptr, req_get_stats Stats_info) {
	fmt.Println("\nGET_STATS\n")

	if req_get_stats.Req_cache_info {
		C_cache_info := ioctl.Ioctl_cache_info(fd, req_get_stats.Cache_id)
		kcache_info := ioctl.Conv_cache_info(C_cache_info)
		ioctl.Marshal_kcache_info(kcache_info)
	}

	if req_get_stats.Req_core_info {
		C_kcore_info := ioctl.Ioctl_core_info(fd, req_get_stats.Cache_id, req_get_stats.Core_id)
		kcore_info := ioctl.Conv_core_info(C_kcore_info)
		ioctl.Marshal_kcore_info(kcore_info)
	}

	if req_get_stats.Req_io_class_info {
		C_kio_class := ioctl.Ioctl_io_class(fd, req_get_stats.Cache_id, uint16(req_get_stats.Io_class))
		kio_class := ioctl.Conv_io_class(C_kio_class)
		ioctl.Marshal_kio_class(kio_class)
	}

	C_kstats := ioctl.Ioctl_get_kcas_stats(fd, req_get_stats.Cache_id,
		req_get_stats.Core_id, uint16(req_get_stats.Io_class))
	kstats := ioctl.Conv_stats(C_kstats)
	ioctl.Marshal_kcas_stats(kstats)
}
