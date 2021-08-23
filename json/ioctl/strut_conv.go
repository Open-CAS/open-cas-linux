/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

package ioctl

// #cgo CFLAGS: -I./../../modules/include/ -I/Ocf_env_headers.h
/*
#include <cas_ioctl_codes.h>
*/
import "C"
import (
	"unsafe"
)

/** kcas_get_stats struct conversion C to Go **/

func Conv_stats(C_kstats C.struct_kcas_get_stats) Kcas_get_stats {
	res := Kcas_get_stats{
		Cache_id:    uint16(C_kstats.cache_id),
		Core_id:     uint16(C_kstats.core_id),
		IO_class_id: uint16(C_kstats.part_id),
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
			Wr_full_misses: Ocf_stat{Value: uint64(C_kstats.req.wr_full_misses.value), Fraction: uint64(C_kstats.req.wr_full_misses.fraction)},
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
			Cache_volume_total: Ocf_stat{Value: uint64(C_kstats.blocks.cache_volume_total.value), Fraction: uint64(C_kstats.blocks.cache_volume_total.fraction)},
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
	}
	return res
}

/** cache_info struct conversion C to Go **/

func Conv_cache_info(C_cache_info C.struct_kcas_cache_info) Kcas_cache_info {

	var core_id []uint16
	for _, v := range (*[C.OCF_CORE_MAX]uint16)(unsafe.Pointer(&C_cache_info.core_id[0]))[:C.OCF_CORE_MAX:C.OCF_CORE_MAX] {
		if v > 0 {
			core_id = append(core_id, v)
		}
	}
	var cache_mode string
	if 0 <= C_cache_info.info.cache_mode {
		cache_mode = ocf_cache_mode_str[C_cache_info.info.cache_mode]
	} else {
		cache_mode = "none"
	}

	res := Kcas_cache_info{
		Cache_id:        uint16(C_cache_info.cache_id),
		Cache_path_name: C.GoString(&C_cache_info.cache_path_name[0]),
		Core_id:         core_id,
		Info: Ocf_cache_info{
			Attached:    bool(C_cache_info.info.attached),
			Volume_type: uint8(C_cache_info.info.volume_type),
			State:       ocf_cache_state_str[C_cache_info.info.state],
			Size:        uint32(C_cache_info.info.size),
			Inactive_cores: Core_stats{
				Occupancy: Ocf_stat{Value: uint64(C_cache_info.info.inactive.occupancy.value),
					Fraction: uint64(C_cache_info.info.inactive.occupancy.fraction)},
				Clean: Ocf_stat{Value: uint64(C_cache_info.info.inactive.clean.value),
					Fraction: uint64(C_cache_info.info.inactive.clean.fraction)},
				Dirty: Ocf_stat{Value: uint64(C_cache_info.info.inactive.dirty.value),
					Fraction: uint64(C_cache_info.info.inactive.dirty.fraction)},
			},
			Occupancy:     uint32(C_cache_info.info.occupancy),
			Dirty:         uint32(C_cache_info.info.dirty),
			Dirty_for:     uint64(C_cache_info.info.dirty_for),
			Dirty_initial: uint32(C_cache_info.info.dirty_initial),
			Cache_mode:    cache_mode,
			Fallback_pt: Fallback_pt_stats{
				Error_counter: int(C_cache_info.info.fallback_pt.error_counter),
				Status:        bool(C_cache_info.info.fallback_pt.status),
			},
			Cleaning_policy:     ocf_cleaning_str[C_cache_info.info.cleaning_policy],
			Promotion_policy:    ocf_promotion_str[C_cache_info.info.promotion_policy],
			Cache_line_size:     uint64(C_cache_info.info.cache_line_size),
			Flushed:             uint32(C_cache_info.info.flushed),
			Core_count:          uint32(C_cache_info.info.core_count),
			Metadata_footprint:  uint64(C_cache_info.info.metadata_footprint),
			Metadata_end_offset: uint64(C_cache_info.info.metadata_end_offset),
		},
		Metadata_mode: metadata_mode_str[C_cache_info.metadata_mode],
		ext_err_code:  int(C_cache_info.ext_err_code),
	}
	return res
}

/** core_info struct conversion C to Go **/

func Conv_core_info(kcore_info C.struct_kcas_core_info) Kcas_core_info {

	res := Kcas_core_info{
		Core_path_name: C.GoString(&kcore_info.core_path_name[0]),
		Cache_id:       uint16(kcore_info.cache_id),
		Core_id:        uint16(kcore_info.core_id),
		Info: Ocf_core_info{
			Core_size:            uint64(kcore_info.info.core_size),
			Core_size_bytes:      uint64(kcore_info.info.core_size_bytes),
			Flushed:              uint32(kcore_info.info.flush_operation.flushed),
			Dirty:                uint32(kcore_info.info.flush_operation.dirty),
			Dirty_for:            uint64(kcore_info.info.dirty_for),
			Seq_cutoff_threshold: uint32(kcore_info.info.seq_cutoff_threshold),
			Seq_cutoff_policy:    ocf_seq_cutoff_policy_str[kcore_info.info.seq_cutoff_policy],
		},
		State: ocf_core_state_str[kcore_info.state],
	}
	return res
}

/** io_class struct conversion C to Go **/

func Conv_io_class(kio_class C.struct_kcas_io_class) Kcas_io_class {
	var cache_mode string
	if 0 <= kio_class.info.cache_mode {
		cache_mode = ocf_cache_mode_str[kio_class.info.cache_mode]
	} else {
		cache_mode = "none"
	}

	res := Kcas_io_class{
		Cache_id: uint16(kio_class.cache_id),
		Class_id: uint32(kio_class.class_id),
		Info: Ocf_io_class_info{
			Name:            C.GoString(&kio_class.info.name[0]),
			Cache_mode:      cache_mode,
			Priority:        int16(kio_class.info.priority),
			Curr_size:       uint32(kio_class.info.curr_size),
			Min_size:        int32(kio_class.info.min_size),
			Max_size:        int32(kio_class.info.max_size),
			Cleaning_policy: ocf_cleaning_str[kio_class.info.cleaning_policy_type],
		},
		ext_err_code: int(kio_class.ext_err_code),
	}
	return res
}
