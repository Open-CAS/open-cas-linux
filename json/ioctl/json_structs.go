/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

package ioctl

/*
#include <cas_ioctl_codes.h>
*/
import "C"

/** IOCTL_KCAS_GET_STATS structs **/

type Kcas_get_stats struct {
	Cache_id     uint16             `json:"Cache id"`
	Core_id      uint16             `json:"Core id"`
	IO_class_id  uint16             `json:"Part id"`
	Usage        Ocf_stats_usage    `json:"Usage"`
	Req          Ocf_stats_requests `json:"Requests"`
	Blocks       Ocf_stats_blocks   `json:"Blocks"`
	Errors       Ocf_stats_errors   `json:"Errors"`
	ext_err_code int
}

type Ocf_stats_usage struct {
	Occupancy Ocf_stat `json:"Occupancy"`
	Free      Ocf_stat `json:"Free"`
	Clean     Ocf_stat `json:"Clean"`
	Dirty     Ocf_stat `json:"Dirty"`
}

type Ocf_stats_requests struct {
	Rd_hits           Ocf_stat `json:"Read hits"`
	Rd_partial_misses Ocf_stat `json:"Read partial misses"`
	Rd_full_misses    Ocf_stat `json:"Read  full misses"`
	Rd_total          Ocf_stat `json:"Read total"`
	Wr_hits           Ocf_stat `json:"Write hits"`
	Wr_partial_misses Ocf_stat `json:"Write partial misses"`
	Wr_full_misses    Ocf_stat `json:"Write full misses"`
	Wr_total          Ocf_stat `json:"Write total"`
	Rd_pt             Ocf_stat `json:"Pass-Trough reads"`
	Wr_pt             Ocf_stat `json:"Pass-Trough writes"`
	Serviced          Ocf_stat `json:"Serviced requests"`
	Total             Ocf_stat `json:"Total requests"`
}

type Ocf_stats_blocks struct {
	Core_volume_rd     Ocf_stat `json:"Reads from core(s)"`
	Core_volume_wr     Ocf_stat `json:"Writes from core(s)"`
	Core_volume_total  Ocf_stat `json:"Total to/from core(s)"`
	Cache_volume_rd    Ocf_stat `json:"Reads from cache(s)"`
	Cache_volume_wr    Ocf_stat `json:"Writes from cache(s)"`
	Cache_volume_total Ocf_stat `json:"Total to/from cache(s)"`
	Volume_rd          Ocf_stat `json:"Reads from exported object(s)"`
	Volume_wr          Ocf_stat `json:"Writes from exported object(s)"`
	Volume_total       Ocf_stat `json:"Total to/from exported object(s)"`
}

type Ocf_stats_errors struct {
	Core_volume_rd     Ocf_stat `json:"Core read errors"`
	Core_volume_wr     Ocf_stat `json:"Core write errors"`
	Core_volume_total  Ocf_stat `json:"Core total errors"`
	Cache_volume_rd    Ocf_stat `json:"Cache read errors"`
	Cache_volume_wr    Ocf_stat `json:"Cache write errors"`
	Cache_volume_total Ocf_stat `json:"Cache total errors"`
	Total              Ocf_stat `json:"Total errors"`
}

type Ocf_stat struct {
	Value    uint64 `json:"page"`
	Fraction uint64 `json:"fraction"`
}

/** IOCTL_CACHE_INFO structs **/

type Kcas_cache_info struct {
	Cache_id        uint16         `json:"Cache id"`
	Cache_path_name string         `json:"Cache device"`
	Core_id         []uint16       `json:"Core(s) id(s)"`
	Info            Ocf_cache_info `json:"Cache details"`
	Metadata_mode   string         `json:"Metadata mode"`
	ext_err_code    int
}

type Ocf_cache_info struct {
	Attached            bool              `json:"Attached"`
	Volume_type         uint8             `json:"Volume type"` // mby enum -> convert to str?
	State               string            `json:"Status"`
	Size                uint32            `json:"Size [cache lines]"`
	Inactive_cores      Core_stats        `json:"Inactive cores"`
	Occupancy           uint32            `json:"Occupancy [cache lines]"`
	Dirty               uint32            `json:"Dirty [cache lines]"`
	Dirty_for           uint64            `json:"Dirty for [s]"`
	Dirty_initial       uint32            `json:"Initially dirty [cache lines]"`
	Cache_mode          string            `json:"Cache mode"`
	Fallback_pt         Fallback_pt_stats `json:"Pass-Trough fallback statistics"`
	Cleaning_policy     string            `json:"Cleaning policy"`
	Promotion_policy  	string            `json:"Promotion policy"`
	Cache_line_size     uint64            `json:"Cache line size [KiB]"`
	Flushed             uint32            `json:"Flushed blocks"`
	Core_count          uint32            `json:"Core count"`
	Metadata_footprint  uint64            `json:"Metadata footprint [B]"`
	Metadata_end_offset uint64            `json:"Metadata end offset [4 KiB blocks]"`
}

type Core_stats struct {
	Occupancy Ocf_stat `json:"Occupancy"`
	Clean     Ocf_stat `json:"Clean"`
	Dirty     Ocf_stat `json:"Dirty"`
}

type Fallback_pt_stats struct {
	Error_counter int  `json:"IO errors count"`
	Status        bool `json:"Status"`
}

/** IOCTL_CORE_INFO structs **/

type Kcas_core_info struct {
	Core_path_name string        `json:"Core path"`
	Cache_id       uint16        `json:"Cache id"`
	Core_id        uint16        `json:"Core id"`
	Info           Ocf_core_info `json:"Core details"`
	State          string        `json:"State"`
	ext_err_code   int
}

type Ocf_core_info struct {
	Core_size            uint64 `json:"Core size [line size]"`
	Core_size_bytes      uint64 `json:"Core size [B]"`
	Flushed              uint32 `json:"Flushed blocks"`
	Dirty                uint32 `json:"Dirty blocks"`
	Dirty_for            uint64 `json:"Dirty for [s]"`
	Seq_cutoff_threshold uint32 `json:"Sequential cutoff threshold [B]"`
	Seq_cutoff_policy    string `json:"Sequential cutoff policy [B]"`
}

/** IOCTL_KCAS_IO_CLASS structs **/

type Kcas_io_class struct {
	Cache_id     uint16            `json:"Cache id"`
	Class_id     uint32            `json:"Class id"`
	Info         Ocf_io_class_info "IO class details"
	ext_err_code int
}

type Ocf_io_class_info struct {
	Name            string `json:"Name"`
	Cache_mode      string `json:"Cache mode"`
	Priority        int16  `json:"Priority"`
	Curr_size       uint32 `json:"Current size [cache line]"`
	Min_size        int32  `json:"Min size [cache line]"`
	Max_size        int32  `json:"Max size [cache line]"`
	Cleaning_policy string `json:"Cleaning policy"`
}
