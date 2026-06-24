/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
 */

package ioctl

// #cgo CFLAGS: -I./../../modules/include/ -I./../../casadm
// #include <extended_err_msg.h>
// #include <./../../casadm/extended_err_msg.c>
// #include <cas_ioctl_codes.h>
import "C"
import (
	"errors"
	"syscall"
	"unsafe"
)

/** CAS control device path **/

var Cas_ctrl_path string = "/dev/cas_ctrl"

/** Use syscall ioctl to get get_kcas_stats structs **/
// returned values of syscall r1, r2 skipped (register1 value, register2 value, Errno error)

func Ioctl_get_kcas_stats(fd uintptr, cache_id, core_id, part_id uint16) (C.struct_kcas_get_stats, error) {
	C_kstats := C.struct_kcas_get_stats{cache_id: C.ushort(cache_id),
		core_id: C.ushort(core_id), part_id: C.ushort(part_id)}
	_, _, ioctl_err := syscall.Syscall(syscall.SYS_IOCTL, fd, C.KCAS_IOCTL_GET_STATS,
		uintptr(unsafe.Pointer(&C_kstats)))
	if C_kstats.ext_err_code == 0 {
		ext_err := ext_err_code_to_string(int(C_kstats.ext_err_code))
		return C_kstats, ext_err
	}
	return C_kstats, ioctl_err
}

/** Use syscall ioctl to get cache info struct **/

func Ioctl_cache_info(fd uintptr, cache_id uint16) (C.struct_kcas_cache_info, error) {
	C_kcache_info := C.struct_kcas_cache_info{cache_id: C.ushort(cache_id)}
	_, _, ioctl_err := syscall.Syscall(syscall.SYS_IOCTL, fd, C.KCAS_IOCTL_CACHE_INFO,
		uintptr(unsafe.Pointer(&C_kcache_info)))
	if C_kcache_info.ext_err_code == 0 {
		ext_err := ext_err_code_to_string(int(C_kcache_info.ext_err_code))
		return C_kcache_info, ext_err
	}
	return C_kcache_info, ioctl_err
}

/** Use syscall ioctl to get core info struct **/

func Ioctl_core_info(fd uintptr, cache_id, core_id uint16) (C.struct_kcas_core_info, error) {
	C_kcore_info := C.struct_kcas_core_info{cache_id: C.ushort(cache_id), core_id: C.ushort(core_id)}
	_, _, ioctl_err := syscall.Syscall(syscall.SYS_IOCTL, fd, C.KCAS_IOCTL_CORE_INFO,
		uintptr(unsafe.Pointer(&C_kcore_info)))
	if C_kcore_info.ext_err_code == 0 {
		ext_err := ext_err_code_to_string(int(C_kcore_info.ext_err_code))
		return C_kcore_info, ext_err
	}
	return C_kcore_info, ioctl_err
}

/** Use syscall ioctl to get io class struct **/

func Ioctl_io_class(fd uintptr, cache_id, class_id uint16) (C.struct_kcas_io_class, error) {
	C_kio_class := C.struct_kcas_io_class{cache_id: C.ushort(cache_id), class_id: C.uint(class_id)}
	_, _, ioctl_err := syscall.Syscall(syscall.SYS_IOCTL, fd, C.KCAS_IOCTL_PARTITION_INFO,
		uintptr(unsafe.Pointer(&C_kio_class)))
	if C_kio_class.ext_err_code == 0 {
		ext_err := ext_err_code_to_string(int(C_kio_class.ext_err_code))
		return C_kio_class, ext_err
	}
	return C_kio_class, ioctl_err
}

/** Use syscall ioctl to get list of cache ids **/

func Ioctl_list_cache(fd uintptr) (C.struct_kcas_cache_list, error) {
	C_kcache_list := C.struct_kcas_cache_list{}
	_, _, ioctl_err := syscall.Syscall(syscall.SYS_IOCTL, fd, C.KCAS_IOCTL_LIST_CACHE,
		uintptr(unsafe.Pointer(&C_kcache_list)))
	if C_kcache_list.ext_err_code == 0 {
		ext_err := ext_err_code_to_string(int(C_kcache_list.ext_err_code))
		return C_kcache_list, ext_err
	}
	return C_kcache_list, ioctl_err
}

/** maping CAS ext_err_code to Go string error messages */
func ext_err_code_to_string(ext_err_code int) error {
	if ext_err_code == 0 {
		return nil
	}
	return errors.New(C.GoString(C.cas_strerr(C.int(ext_err_code))))
}
