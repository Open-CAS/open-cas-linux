/*
 * Copyright(c) 2026 Unvertical
 * SPDX-License-Identifier: BSD-3-Clause
 */

package main

/*
#cgo CFLAGS: -I../../libopencas -I../../modules/include
#cgo LDFLAGS: -L../../libopencas -lopencas
#include <string.h>
#include "libopencas.h"
*/
import "C"

import (
	"fmt"
	"path/filepath"
	"unsafe"
)

// resolveDevPath resolves symlinks to get the short device name (e.g.
// /dev/disk/by-id/... -> /dev/sda1). Falls back to the original path
// if resolution fails.
func resolveDevPath(path string) string {
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil {
		return path
	}
	return resolved
}

type DumpResult struct {
	Caches    []C.struct_cas_nl_cache
	Cores     []C.struct_cas_nl_core
	IOClasses []C.struct_cas_nl_ioclass
}

func Dump() (*DumpResult, error) {
	var cr C.struct_cas_nl_dump_result

	ret := C.cas_nl_dump(&cr)
	if ret != 0 {
		return nil, fmt.Errorf("cas_nl_dump: %s", C.GoString(C.strerror(-ret)))
	}

	result := &DumpResult{}

	if cr.num_caches > 0 {
		result.Caches = unsafe.Slice(cr.caches, cr.num_caches)
	}
	if cr.num_cores > 0 {
		result.Cores = unsafe.Slice(cr.cores, cr.num_cores)
	}
	if cr.num_ioclasses > 0 {
		result.IOClasses = unsafe.Slice(cr.ioclasses, cr.num_ioclasses)
	}

	return result, nil
}

func (r *DumpResult) Free() {
	if r == nil {
		return
	}
	var cr C.struct_cas_nl_dump_result
	if len(r.Caches) > 0 {
		cr.caches = &r.Caches[0]
	}
	if len(r.Cores) > 0 {
		cr.cores = &r.Cores[0]
	}
	if len(r.IOClasses) > 0 {
		cr.ioclasses = &r.IOClasses[0]
	}
	C.cas_nl_dump_free(&cr)
	r.Caches = nil
	r.Cores = nil
	r.IOClasses = nil
}

// String helpers for labels

func CacheStateStr(state uint8) string {
	if state&(1<<4) != 0 { return "standby" }
	if state&(1<<3) != 0 { return "incomplete" }
	if state&(1<<2) != 0 { return "detached" }
	if state&(1<<1) != 0 { return "stopping" }
	if state&(1<<0) != 0 { return "running" }
	return "not_running"
}

func CacheModeStr(mode uint8) string {
	names := []string{"wt", "wb", "wa", "pt", "wi", "wo"}
	if int(mode) < len(names) { return names[mode] }
	return "unknown"
}

func CoreStateStr(state uint8) string {
	if state == 0 { return "active" }
	if state == 1 { return "inactive" }
	return "unknown"
}

func CleaningPolicyStr(p uint32) string {
	names := []string{"nop", "alru", "acp"}
	if int(p) < len(names) { return names[p] }
	return "unknown"
}

func PromotionPolicyStr(p uint32) string {
	names := []string{"always", "nhit"}
	if int(p) < len(names) { return names[p] }
	return "unknown"
}

func SeqCutoffPolicyStr(p uint8) string {
	names := []string{"always", "full", "never"}
	if int(p) < len(names) { return names[p] }
	return "unknown"
}

// C string helper
func cStr(arr []C.char) string {
	// Find NUL terminator
	for i, c := range arr {
		if c == 0 {
			return C.GoStringN((*C.char)(unsafe.Pointer(&arr[0])), C.int(i))
		}
	}
	return C.GoStringN((*C.char)(unsafe.Pointer(&arr[0])), C.int(len(arr)))
}
