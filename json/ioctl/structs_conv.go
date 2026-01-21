/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
 */

package ioctl

// #cgo CFLAGS: -I./../../modules/include/
// #include <cas_ioctl_codes.h>
import "C"
import (
	"unsafe"
)

/** kcas_get_stats struct conversion C to Go **/

func Conv_stats(C_kstats *C.struct_kcas_get_stats) Kcas_get_stats {
	res := Kcas_get_stats{
		Cache_id: uint16(C_kstats.cache_id),
		Core_id:  uint16(C_kstats.core_id),
		IO_class: uint16(C_kstats.part_id),
		Usage: Ocf_stats_usage{
			Occupancy: Ocf_stat{Value: uint64(C_kstats.usage.occupancy.value),
				Fraction: uint64(C_kstats.usage.occupancy.fraction)},
			Free: Ocf_stat{Value: uint64(C_kstats.usage.free.value),
				Fraction: uint64(C_kstats.usage.free.fraction)},
			Clean: Ocf_stat{Value: uint64(C_kstats.usage.clean.value),
				Fraction: uint64(C_kstats.usage.clean.fraction)},
			Dirty: Ocf_stat{Value: uint64(C_kstats.usage.dirty.value),
				Fraction: uint64(C_kstats.usage.dirty.fraction)},
		},
		Req: Ocf_stats_requests{
			Rd_hits: Ocf_stat{Value: uint64(C_kstats.req.rd_hits.value),
				Fraction: uint64(C_kstats.req.rd_hits.fraction)},
			Rd_partial_misses: Ocf_stat{Value: uint64(C_kstats.req.rd_partial_misses.value),
				Fraction: uint64(C_kstats.req.rd_partial_misses.fraction)},
			Rd_full_misses: Ocf_stat{Value: uint64(C_kstats.req.rd_full_misses.value),
				Fraction: uint64(C_kstats.req.rd_full_misses.fraction)},
			Rd_total: Ocf_stat{Value: uint64(C_kstats.req.rd_total.value),
				Fraction: uint64(C_kstats.req.rd_total.fraction)},
			Wr_hits: Ocf_stat{Value: uint64(C_kstats.req.wr_hits.value),
				Fraction: uint64(C_kstats.req.wr_hits.fraction)},
			Wr_partial_misses: Ocf_stat{Value: uint64(C_kstats.req.wr_partial_misses.value),
				Fraction: uint64(C_kstats.req.wr_partial_misses.fraction)},
			Wr_full_misses: Ocf_stat{Value: uint64(C_kstats.req.wr_full_misses.value),
				Fraction: uint64(C_kstats.req.wr_full_misses.fraction)},
			Wr_total: Ocf_stat{Value: uint64(C_kstats.req.wr_total.value),
				Fraction: uint64(C_kstats.req.wr_total.fraction)},
			Rd_pt: Ocf_stat{Value: uint64(C_kstats.req.rd_pt.value),
				Fraction: uint64(C_kstats.req.rd_pt.fraction)},
			Wr_pt: Ocf_stat{Value: uint64(C_kstats.req.wr_pt.value),
				Fraction: uint64(C_kstats.req.wr_pt.fraction)},
			Serviced: Ocf_stat{Value: uint64(C_kstats.req.serviced.value),
				Fraction: uint64(C_kstats.req.serviced.fraction)},
			Total: Ocf_stat{Value: uint64(C_kstats.req.total.value),
				Fraction: uint64(C_kstats.req.total.fraction)},
		},
		Blocks: Ocf_stats_blocks{
			Core_volume_rd: Ocf_stat{Value: uint64(C_kstats.blocks.core_volume_rd.value),
				Fraction: uint64(C_kstats.blocks.core_volume_rd.fraction)},
			Core_volume_wr: Ocf_stat{Value: uint64(C_kstats.blocks.core_volume_wr.value),
				Fraction: uint64(C_kstats.blocks.core_volume_wr.fraction)},
			Core_volume_total: Ocf_stat{Value: uint64(C_kstats.blocks.core_volume_total.value),
				Fraction: uint64(C_kstats.blocks.core_volume_total.fraction)},
			Cache_volume_rd: Ocf_stat{Value: uint64(C_kstats.blocks.cache_volume_rd.value),
				Fraction: uint64(C_kstats.blocks.cache_volume_rd.fraction)},
			Cache_volume_wr: Ocf_stat{Value: uint64(C_kstats.blocks.cache_volume_wr.value),
				Fraction: uint64(C_kstats.blocks.cache_volume_wr.fraction)},
			Cache_volume_total: Ocf_stat{Value: uint64(C_kstats.blocks.cache_volume_total.value),
				Fraction: uint64(C_kstats.blocks.cache_volume_total.fraction)},
			Volume_rd: Ocf_stat{Value: uint64(C_kstats.blocks.volume_rd.value),
				Fraction: uint64(C_kstats.blocks.volume_rd.fraction)},
			Volume_wr: Ocf_stat{Value: uint64(C_kstats.blocks.volume_wr.value),
				Fraction: uint64(C_kstats.blocks.volume_wr.fraction)},
			Volume_total: Ocf_stat{Value: uint64(C_kstats.blocks.volume_total.value),
				Fraction: uint64(C_kstats.blocks.volume_total.fraction)},
		},
		Errors: Ocf_stats_errors{
			Core_volume_rd: Ocf_stat{Value: uint64(C_kstats.errors.core_volume_rd.value),
				Fraction: uint64(C_kstats.errors.core_volume_rd.fraction)},
			Core_volume_wr: Ocf_stat{Value: uint64(C_kstats.errors.core_volume_wr.value),
				Fraction: uint64(C_kstats.errors.core_volume_wr.fraction)},
			Core_volume_total: Ocf_stat{Value: uint64(C_kstats.errors.core_volume_total.value),
				Fraction: uint64(C_kstats.errors.core_volume_total.fraction)},
			Cache_volume_rd: Ocf_stat{Value: uint64(C_kstats.errors.cache_volume_rd.value),
				Fraction: uint64(C_kstats.errors.cache_volume_rd.fraction)},
			Cache_volume_wr: Ocf_stat{Value: uint64(C_kstats.errors.cache_volume_wr.value),
				Fraction: uint64(C_kstats.errors.cache_volume_wr.fraction)},
			Cache_volume_total: Ocf_stat{Value: uint64(C_kstats.errors.cache_volume_total.value),
				Fraction: uint64(C_kstats.errors.cache_volume_total.fraction)},
			Total: Ocf_stat{Value: uint64(C_kstats.errors.total.value),
				Fraction: uint64(C_kstats.errors.total.fraction)},
		},
		ext_err_code: int(C_kstats.ext_err_code),
	}
	return res
}

/** cache_info struct conversion C to Go **/

func Conv_cache_info(C_kcache_info *C.struct_kcas_cache_info) Kcas_cache_info {

	/** fields with no standard initialization rquired  */
	attached_cores := get_attached_cores(C_kcache_info)
	state := valid_enum_idx(int(C_kcache_info.info.state), ocf_cache_state_str)
	cache_mode := valid_enum_idx(int(C_kcache_info.info.cache_mode), ocf_cache_mode_str)
	cleaning_policy := valid_enum_idx(int(C_kcache_info.info.cleaning_policy), ocf_cleaning_policy_str)
	promotion_policy := valid_enum_idx(int(C_kcache_info.info.promotion_policy), ocf_promotion_str)

	res := Kcas_cache_info{
		Cache_id:        uint16(C_kcache_info.cache_id),
		Cache_path_name: C.GoString(&C_kcache_info.cache_path_name[0]),
		Attached_cores:  attached_cores,
		Info: Ocf_cache_info{
			Attached:    bool(C_kcache_info.info.attached),
			volume_type: uint8(C_kcache_info.info.volume_type),
			State:       state,
			Size:        uint32(C_kcache_info.info.size),
			Inactive_cores: Core_stats{
				Occupancy: Ocf_stat{Value: uint64(C_kcache_info.info.inactive.occupancy.value),
					Fraction: uint64(C_kcache_info.info.inactive.occupancy.fraction)},
				Clean: Ocf_stat{Value: uint64(C_kcache_info.info.inactive.clean.value),
					Fraction: uint64(C_kcache_info.info.inactive.clean.fraction)},
				Dirty: Ocf_stat{Value: uint64(C_kcache_info.info.inactive.dirty.value),
					Fraction: uint64(C_kcache_info.info.inactive.dirty.fraction)},
			},
			Occupancy:     uint32(C_kcache_info.info.occupancy),
			Dirty:         uint32(C_kcache_info.info.dirty),
			Dirty_for:     uint64(C_kcache_info.info.dirty_for),
			Dirty_initial: uint32(C_kcache_info.info.dirty_initial),
			Cache_mode:    cache_mode,
			Fallback_pt: Fallback_pt_stats{
				Error_counter: int(C_kcache_info.info.fallback_pt.error_counter),
				Status:        bool(C_kcache_info.info.fallback_pt.status),
			},
			Cleaning_policy:     cleaning_policy,
			Promotion_policy:    promotion_policy,
			Cache_line_size:     uint64(C_kcache_info.info.cache_line_size),
			Flushed:             uint32(C_kcache_info.info.flushed),
			Core_count:          uint32(C_kcache_info.info.core_count),
			Metadata_footprint:  uint64(C_kcache_info.info.metadata_footprint),
			Metadata_end_offset: uint64(C_kcache_info.info.metadata_end_offset),
		},
		ext_err_code: int(C_kcache_info.ext_err_code),
	}
	return res
}

/** core_info struct conversion C to Go **/

func Conv_core_info(C_kcore_info *C.struct_kcas_core_info) Kcas_core_info {

	/** fields with no standard initialization rquired  */
	seq_cutoff_policy := valid_enum_idx(int(C_kcore_info.info.seq_cutoff_policy), ocf_seq_cutoff_policy_str)
	state := valid_enum_idx(int(C_kcore_info.state), ocf_core_state_str)

	res := Kcas_core_info{
		Core_path_name: C.GoString(&C_kcore_info.core_path_name[0]),
		cache_id:       uint16(C_kcore_info.cache_id),
		Core_id:        uint16(C_kcore_info.core_id),
		Info: Ocf_core_info{
			Core_size:            uint64(C_kcore_info.info.core_size),
			Core_size_bytes:      uint64(C_kcore_info.info.core_size_bytes),
			Flushed:              uint32(C_kcore_info.info.flushed),
			Dirty:                uint32(C_kcore_info.info.dirty),
			Dirty_for:            uint64(C_kcore_info.info.dirty_for),
			Seq_cutoff_threshold: uint32(C_kcore_info.info.seq_cutoff_threshold),
			Seq_cutoff_policy:    seq_cutoff_policy,
		},
		State:        state,
		ext_err_code: int(C_kcore_info.ext_err_code),
	}
	return res
}

/** io_class struct conversion C to Go **/

func Conv_io_class(C_kio_class *C.struct_kcas_io_class) Kcas_io_class {

	/** fields with no standard initialization rquired  */
	cache_mode := valid_enum_idx(int(C_kio_class.info.cache_mode), ocf_cache_mode_str)
	cleaning_policy := valid_enum_idx(int(C_kio_class.info.cleaning_policy_type), ocf_cleaning_policy_str)

	res := Kcas_io_class{
		cache_id: uint16(C_kio_class.cache_id),
		Class_id: uint32(C_kio_class.class_id),
		Info: Ocf_io_class_info{
			Name:            C.GoString(&C_kio_class.info.name[0]),
			Cache_mode:      cache_mode,
			Priority:        int16(C_kio_class.info.priority),
			Curr_size:       uint32(C_kio_class.info.curr_size),
			Min_size:        int32(C_kio_class.info.min_size),
			Max_size:        int32(C_kio_class.info.max_size),
			Cleaning_policy: cleaning_policy,
		},
		ext_err_code: int(C_kio_class.ext_err_code),
	}
	return res
}

// converts C type uint16[CACHE_LIST_ID_LIMIT] to Go slice []uint16
// picks only valid caches and appends to result slice
func Conv_cache_id_list(C_kcache_list *C.struct_kcas_cache_list) []uint16 {
	var valid_cache_ids []uint16
	cache_id_list := (*[C.CACHE_LIST_ID_LIMIT]uint16)(unsafe.Pointer(&C_kcache_list.cache_id_tab[0]))[:C.CACHE_LIST_ID_LIMIT:C.CACHE_LIST_ID_LIMIT]

	// Go in range for syntax - for index, value := range collection {}
	for _, cache_id := range cache_id_list {
		if valid_cache_id(cache_id) {
			valid_cache_ids = append(valid_cache_ids, cache_id)
		} else {
			break
		}
	}
	return valid_cache_ids
}

/** helper functions for initializations of no standard types **/

// converts C type uint16[OCF_CORE_MAX] to Go slice []uint16
// picks only valid cores and appends to result slice
func get_attached_cores(C_kcache_info *C.struct_kcas_cache_info) []uint16 {
	var valid_core_ids []uint16

	/** conversion C cores_id array to Golang slice */
	core_ids := (*[C.OCF_CORE_MAX]uint16)(unsafe.Pointer(&C_kcache_info.core_id[0]))[:C.OCF_CORE_MAX:C.OCF_CORE_MAX]
	for core_idx := 0; core_idx < int(C_kcache_info.info.core_count); core_idx++ {
		if valid_core_id(core_ids[core_idx]) {
			valid_core_ids = append(valid_core_ids, core_ids[core_idx])
		}
	}
	return valid_core_ids
}

/** checks for valid core id */

func valid_core_id(core_id uint16) bool {
	return core_id < C.OCF_CORE_MAX
}

/** checks for valid cache id */

func valid_cache_id(cache_id uint16) bool {
	return C.OCF_CACHE_ID_MIN <= cache_id && cache_id < C.CACHE_LIST_ID_LIMIT
}

/** checks if enum value as idx is out of range and returns valid value or default value */

func valid_enum_idx(idx int, enum_str_slice []string) string {
	if 0 <= idx && idx < len(enum_str_slice) {
		return enum_str_slice[idx]
	} else {
		return "undefined"
	}
}
