/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

package ioctl

// #cgo CFLAGS: -I./../../modules/include/ -I/ocf_env_headers.h
/*
#include <cas_ioctl_codes.h>
*/
import "C"
import (
	"log"
	"os"
	"syscall"
	"unsafe"
)

/** Get CAS exported device file descriptor **/

func Read_fd() uintptr {
	file, err := os.Open("/dev/cas_ctrl")
	if err != nil {
		log.Fatal(err)
	}
	return file.Fd()
}

/** Use syscall ioctl to get get_kcas_stats structs **/

func Ioctl_get_kcas_stats(fd uintptr, cache_id, core_id, part_id uint16) C.struct_kcas_get_stats {
	C_kstats := C.struct_kcas_get_stats{cache_id: C.ushort(cache_id),
		core_id: C.ushort(core_id), part_id: C.ushort(part_id)}
	_, _, err := syscall.Syscall(syscall.SYS_IOCTL, fd, C.KCAS_IOCTL_GET_STATS,
		uintptr(unsafe.Pointer(&C_kstats)))
	if err != 0 {
		log.Fatal(err)
	}
	return C_kstats
}

/** Use syscall ioctl to get cache info struct **/

func Ioctl_cache_info(fd uintptr, cache_id uint16) C.struct_kcas_cache_info {
	C_kcache_info := C.struct_kcas_cache_info{cache_id: C.ushort(cache_id)}
	_, _, err := syscall.Syscall(syscall.SYS_IOCTL, fd, C.KCAS_IOCTL_CACHE_INFO,
		uintptr(unsafe.Pointer(&C_kcache_info)))
	if err != 0 {
		log.Fatal(err)
	}
	return C_kcache_info
}

/** Use syscall ioctl to get core info struct **/

func Ioctl_core_info(fd uintptr, cache_id, core_id uint16) C.struct_kcas_core_info {
	C_kcore_info := C.struct_kcas_core_info{cache_id: C.ushort(cache_id), core_id: C.ushort(core_id)}
	_, _, err := syscall.Syscall(syscall.SYS_IOCTL, fd, C.KCAS_IOCTL_CORE_INFO,
		uintptr(unsafe.Pointer(&C_kcore_info)))
	if err != 0 {
		log.Fatal(err)
	}
	return C_kcore_info
}

/** Use syscall ioctl to get io class struct **/

func Ioctl_io_class(fd uintptr, cache_id, class_id uint16) C.struct_kcas_io_class {
	C_kio_class := C.struct_kcas_io_class{cache_id: C.ushort(cache_id), class_id: C.uint(class_id)}
	_, _, err := syscall.Syscall(syscall.SYS_IOCTL, fd, C.KCAS_IOCTL_PARTITION_INFO,
		uintptr(unsafe.Pointer(&C_kio_class)))
	if err != 0 {
		log.Fatal(err)
	}
	return C_kio_class
}
