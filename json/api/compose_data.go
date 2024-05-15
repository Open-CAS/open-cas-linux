/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
 */

package api

import (
	"os"

	"github.com/Open-CAS/open-cas-linux/json/ioctl"
)

/** packages of JSON marshalable structs with packed CAS info for easy use in RESTful API */

type Cache_with_cores struct {
	// default value of ptr is nil
	Cache_info *ioctl.Kcas_cache_info  `json:"Cache"`
	Cores_info []*ioctl.Kcas_core_info `json:"Cores"`
}

type Cache_list_pkg []Cache_with_cores

/** Retriving caches and their cores info from CAS */

func List_caches() (Cache_list_pkg, error) {
	var cache_list_pkg Cache_list_pkg

	/** retive list of caches id from ioclt */
	cache_id_list, ioctl_err := get_cache_id_list()

	/** early log and return in case of cache_list_id retrieve error
	which is needed in further caches iteration for ioctl calls */
	if check_err(ioctl_err, ioctl_err.Error(), log_console) {
		return cache_list_pkg, ioctl_err
	}

	/**  create array of caches with list of their cores */
	cache_id_list_len := len(cache_id_list)
	cache_list_pkg = make([]Cache_with_cores, cache_id_list_len)

	for cache_idx, cache_id := range cache_id_list {
		/** retrieve cache info */
		cache_info, ioctl_err := get_cache_info(cache_id)

		/** in case of get_cache_info error, log error and skip adding that cache and it's cores to package */
		if check_err(ioctl_err, ioctl_err.Error(), log_console) {
			return cache_list_pkg, ioctl_err
		}

		/** create array of cores for each cache */
		cores_id_list_len := len(cache_info.Attached_cores)
		cache_list_pkg[cache_idx].Cores_info = make([]*ioctl.Kcas_core_info, cores_id_list_len)

		/** fill array of caches & their cores with retrieved cache info */
		cache_list_pkg[cache_idx].Cache_info = &cache_info

		for core_idx, core_id := range cache_info.Attached_cores {
			/** retrieve core info for table of cores assigned to cache */
			core_info, ioctl_err := get_core_info(cache_id, core_id)

			/** in case of get_core_info error, log error and skip adding that core to package */
			if check_err(ioctl_err, ioctl_err.Error(), log_console) {
				return cache_list_pkg, ioctl_err
			}

			/** fill array of cores with retrieved core info */
			cache_list_pkg[cache_idx].Cores_info[core_idx] = &core_info
		}
	}
	/** return array of caches with their cores list and no error */
	return cache_list_pkg, nil
}

/** retriving CAS structures with ioctl syscalls and converting them into Go Marshalable structs */

/** retrieves C cache info struct with ioctl syscall and converts it into Golang cache info struct
also provides errno type error into standard golang error conversion */
func get_cache_info(cache_id uint16) (ioctl.Kcas_cache_info, error) {
	/** retrieve file descriptor of exported object cas_ctrl
	and close with defer after completing all tasks */
	cas_ctrl, fd_err := os.Open(ioctl.Cas_ctrl_path)
	if check_err(fd_err, "Cannot open device exclusively", log_console) {
		return ioctl.Kcas_cache_info{}, fd_err
	}
	defer cas_ctrl.Close()

	C_cache_info, ioctl_err := ioctl.Ioctl_cache_info(cas_ctrl.Fd(), cache_id)
	cache_info := ioctl.Conv_cache_info(&C_cache_info)
	ioctl_err = errno_to_error(ioctl_err)
	return cache_info, ioctl_err
}

/** retrieves C core info struct with ioctl syscall and converts it into Golang core info struct
also provides errno type error into standard golang error conversion */
func get_core_info(cache_id, core_id uint16) (ioctl.Kcas_core_info, error) {
	/** retrieve file descriptor of exported object cas_ctrl
	and close with defer after completing all tasks */
	cas_ctrl, fd_err := os.Open(ioctl.Cas_ctrl_path)
	if check_err(fd_err, "Cannot open device exclusively", log_console) {
		return ioctl.Kcas_core_info{}, fd_err
	}
	defer cas_ctrl.Close()

	C_core_info, ioctl_err := ioctl.Ioctl_core_info(cas_ctrl.Fd(), cache_id, core_id)
	core_info := ioctl.Conv_core_info(&C_core_info)
	ioctl_err = errno_to_error(ioctl_err)
	return core_info, ioctl_err
}

/** retrieves C io class struct with ioctl syscall and converts it into Golang io class struct
also provides errno type error into standard golang error conversion */
func get_io_class(cache_id, io_class_id uint16) (ioctl.Kcas_io_class, error) {
	/** retrieves file descriptor of exported object cas_ctrl
	and close with defer after completing all tasks */
	cas_ctrl, fd_err := os.Open(ioctl.Cas_ctrl_path)
	if check_err(fd_err, "Cannot open device exclusively", log_console) {
		return ioctl.Kcas_io_class{}, fd_err
	}
	defer cas_ctrl.Close()

	C_io_class, ioctl_err := ioctl.Ioctl_io_class(cas_ctrl.Fd(), cache_id, io_class_id)
	io_class := ioctl.Conv_io_class(&C_io_class)
	ioctl_err = errno_to_error(ioctl_err)
	return io_class, ioctl_err
}

/** retrieves C statistics struct with ioctl syscall and converts it into Golang statistics struct
also provides errno type error into standard golang error conversion */
func get_stats(cache_id, core_id, io_class_id uint16) (ioctl.Kcas_get_stats, error) {
	/** retrieve file descriptor of exported object cas_ctrl
	and close with defer after completing all tasks */
	cas_ctrl, fd_err := os.Open(ioctl.Cas_ctrl_path)
	if check_err(fd_err, "Cannot open device exclusively", log_console) {
		return ioctl.Kcas_get_stats{}, fd_err
	}
	defer cas_ctrl.Close()

	C_stats, ioctl_err := ioctl.Ioctl_get_kcas_stats(cas_ctrl.Fd(), cache_id, core_id, io_class_id)
	stats := ioctl.Conv_stats(&C_stats)
	ioctl_err = errno_to_error(ioctl_err)
	return stats, ioctl_err
}

/** retrieves C list of cache id's with ioctl syscall and converts it into Golang slice of cache id's
also provides errno type error into standard golang error conversion */
func get_cache_id_list() ([]uint16, error) {
	/** retrieves file descriptor of exported object cas_ctrl
	and close with defer after completing all tasks */
	cas_ctrl, fd_err := os.Open(ioctl.Cas_ctrl_path)
	if check_err(fd_err, "Cannot open device exclusively", log_console) {
		return []uint16{}, fd_err
	}
	defer cas_ctrl.Close()

	C_cache_list, ioctl_err := ioctl.Ioctl_list_cache(cas_ctrl.Fd())
	cache_list := ioctl.Conv_cache_id_list(&C_cache_list)
	ioctl_err = errno_to_error(ioctl_err)
	return cache_list, ioctl_err
}

/** validate file descriptor */
func valid_fd(fd uintptr) bool {
	return fd > 0
}
