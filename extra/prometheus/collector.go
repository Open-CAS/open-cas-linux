// Copyright(c) 2026 Unvertical
// SPDX-License-Identifier: BSD-3-Clause

package main

/*
#cgo CFLAGS: -I../../libopencas -I../../modules/include
#include "libopencas.h"
*/
import "C"

import (
	"fmt"
	"log"
	"time"

	"github.com/prometheus/client_golang/prometheus"
)

// Collector implements prometheus.Collector and fetches CAS state on each scrape.
type Collector struct {
	up             *prometheus.Desc
	scrapeDuration *prometheus.Desc

	// Cache metrics
	cacheInfo              *prometheus.Desc
	cacheSize              *prometheus.Desc
	cacheLineSize          *prometheus.Desc
	cacheOccupancy         *prometheus.Desc
	cacheDirty             *prometheus.Desc
	cacheDirtyFor          *prometheus.Desc
	cacheDirtyInitial      *prometheus.Desc
	cacheFlushed           *prometheus.Desc
	cacheCoreCount         *prometheus.Desc
	cacheMetaFootprint     *prometheus.Desc
	cacheMetaEndOffset     *prometheus.Desc
	cacheFallbackPTErrors  *prometheus.Desc
	cacheInactiveOccupancy *prometheus.Desc
	cacheInactiveClean     *prometheus.Desc
	cacheInactiveDirty     *prometheus.Desc

	// Core metrics
	coreInfo            *prometheus.Desc
	coreSizeBytes       *prometheus.Desc
	coreDirty           *prometheus.Desc
	coreDirtyFor        *prometheus.Desc
	coreFlushed         *prometheus.Desc
	coreSeqCutoffThresh *prometheus.Desc

	// IO class metrics
	ioclassInfo     *prometheus.Desc
	ioclassCurrSize *prometheus.Desc
	ioclassMinSize  *prometheus.Desc
	ioclassMaxSize  *prometheus.Desc

	// Stats metrics (shared structure, different label sets)
	cacheStats   statsDescs
	coreStats    statsDescs
	ioclassStats statsDescs
}

type statsDescs struct {
	usageOccupancy     *prometheus.Desc
	usageFree          *prometheus.Desc
	usageClean         *prometheus.Desc
	usageDirty         *prometheus.Desc
	reqRdHits          *prometheus.Desc
	reqRdDeferred      *prometheus.Desc
	reqRdPartialMisses *prometheus.Desc
	reqRdFullMisses    *prometheus.Desc
	reqRdTotal         *prometheus.Desc
	reqWrHits          *prometheus.Desc
	reqWrDeferred      *prometheus.Desc
	reqWrPartialMisses *prometheus.Desc
	reqWrFullMisses    *prometheus.Desc
	reqWrTotal         *prometheus.Desc
	reqRdPT            *prometheus.Desc
	reqWrPT            *prometheus.Desc
	reqServiced        *prometheus.Desc
	reqPrefetchRA      *prometheus.Desc
	reqCleaner         *prometheus.Desc
	reqTotal           *prometheus.Desc
	blocksCoreRd       *prometheus.Desc
	blocksCoreWr       *prometheus.Desc
	blocksCoreTotal    *prometheus.Desc
	blocksCacheRd      *prometheus.Desc
	blocksCacheWr      *prometheus.Desc
	blocksCacheTotal   *prometheus.Desc
	blocksVolumeRd     *prometheus.Desc
	blocksVolumeWr     *prometheus.Desc
	blocksVolumeTotal  *prometheus.Desc
	blocksPTRd         *prometheus.Desc
	blocksPTWr         *prometheus.Desc
	blocksPTTotal      *prometheus.Desc
	blocksPrefetchCoreRdRA *prometheus.Desc
	blocksPrefetchCacheWrRA *prometheus.Desc
	blocksCleanerCacheRd *prometheus.Desc
	blocksCleanerCoreWr  *prometheus.Desc
	errorsCoreRd       *prometheus.Desc
	errorsCoreWr       *prometheus.Desc
	errorsCoreTotal    *prometheus.Desc
	errorsCacheRd      *prometheus.Desc
	errorsCacheWr      *prometheus.Desc
	errorsCacheTotal   *prometheus.Desc
	errorsTotal        *prometheus.Desc
}

func newStatsDescs(prefix string, labels []string, includeErrors bool) statsDescs {
	s := statsDescs{
		usageOccupancy:     prometheus.NewDesc(prefix+"_usage_occupancy_blocks", "Occupied cache lines (4 KiB)", labels, nil),
		usageFree:          prometheus.NewDesc(prefix+"_usage_free_blocks", "Free cache lines (4 KiB)", labels, nil),
		usageClean:         prometheus.NewDesc(prefix+"_usage_clean_blocks", "Clean cache lines (4 KiB)", labels, nil),
		usageDirty:         prometheus.NewDesc(prefix+"_usage_dirty_blocks", "Dirty cache lines (4 KiB)", labels, nil),
		reqRdHits:          prometheus.NewDesc(prefix+"_requests_read_hits_total", "Read hits", labels, nil),
		reqRdDeferred:      prometheus.NewDesc(prefix+"_requests_read_deferred_total", "Read deferred", labels, nil),
		reqRdPartialMisses: prometheus.NewDesc(prefix+"_requests_read_partial_misses_total", "Read partial misses", labels, nil),
		reqRdFullMisses:    prometheus.NewDesc(prefix+"_requests_read_full_misses_total", "Read full misses", labels, nil),
		reqRdTotal:         prometheus.NewDesc(prefix+"_requests_read_total", "Total read requests", labels, nil),
		reqWrHits:          prometheus.NewDesc(prefix+"_requests_write_hits_total", "Write hits", labels, nil),
		reqWrDeferred:      prometheus.NewDesc(prefix+"_requests_write_deferred_total", "Write deferred", labels, nil),
		reqWrPartialMisses: prometheus.NewDesc(prefix+"_requests_write_partial_misses_total", "Write partial misses", labels, nil),
		reqWrFullMisses:    prometheus.NewDesc(prefix+"_requests_write_full_misses_total", "Write full misses", labels, nil),
		reqWrTotal:         prometheus.NewDesc(prefix+"_requests_write_total", "Total write requests", labels, nil),
		reqRdPT:            prometheus.NewDesc(prefix+"_requests_read_passthrough_total", "Read pass-through", labels, nil),
		reqWrPT:            prometheus.NewDesc(prefix+"_requests_write_passthrough_total", "Write pass-through", labels, nil),
		reqServiced:        prometheus.NewDesc(prefix+"_requests_serviced_total", "Requests serviced from cache", labels, nil),
		reqPrefetchRA:      prometheus.NewDesc(prefix+"_requests_prefetch_readahead_total", "Readahead prefetch requests", labels, nil),
		reqCleaner:         prometheus.NewDesc(prefix+"_requests_cleaner_total", "Cleaner requests", labels, nil),
		reqTotal:           prometheus.NewDesc(prefix+"_requests_total", "Total requests", labels, nil),
		blocksCoreRd:       prometheus.NewDesc(prefix+"_blocks_core_read_total", "Blocks read from core (4 KiB)", labels, nil),
		blocksCoreWr:       prometheus.NewDesc(prefix+"_blocks_core_write_total", "Blocks written to core (4 KiB)", labels, nil),
		blocksCoreTotal:    prometheus.NewDesc(prefix+"_blocks_core_total", "Total blocks core (4 KiB)", labels, nil),
		blocksCacheRd:      prometheus.NewDesc(prefix+"_blocks_cache_read_total", "Blocks read from cache (4 KiB)", labels, nil),
		blocksCacheWr:      prometheus.NewDesc(prefix+"_blocks_cache_write_total", "Blocks written to cache (4 KiB)", labels, nil),
		blocksCacheTotal:   prometheus.NewDesc(prefix+"_blocks_cache_total", "Total blocks cache (4 KiB)", labels, nil),
		blocksVolumeRd:     prometheus.NewDesc(prefix+"_blocks_exported_read_total", "Blocks read from exported obj (4 KiB)", labels, nil),
		blocksVolumeWr:     prometheus.NewDesc(prefix+"_blocks_exported_write_total", "Blocks written to exported obj (4 KiB)", labels, nil),
		blocksVolumeTotal:  prometheus.NewDesc(prefix+"_blocks_exported_total", "Total blocks exported obj (4 KiB)", labels, nil),
		blocksPTRd:         prometheus.NewDesc(prefix+"_blocks_passthrough_read_total", "Blocks read pass-through (4 KiB)", labels, nil),
		blocksPTWr:         prometheus.NewDesc(prefix+"_blocks_passthrough_write_total", "Blocks written pass-through (4 KiB)", labels, nil),
		blocksPTTotal:      prometheus.NewDesc(prefix+"_blocks_passthrough_total", "Total blocks pass-through (4 KiB)", labels, nil),
		blocksPrefetchCoreRdRA:  prometheus.NewDesc(prefix+"_blocks_prefetch_core_read_readahead_total", "Blocks read from core by readahead prefetch (4 KiB)", labels, nil),
		blocksPrefetchCacheWrRA: prometheus.NewDesc(prefix+"_blocks_prefetch_cache_write_readahead_total", "Blocks written to cache by readahead prefetch (4 KiB)", labels, nil),
		blocksCleanerCacheRd: prometheus.NewDesc(prefix+"_blocks_cleaner_cache_read_total", "Blocks read from cache by cleaner (4 KiB)", labels, nil),
		blocksCleanerCoreWr:  prometheus.NewDesc(prefix+"_blocks_cleaner_core_write_total", "Blocks written to core by cleaner (4 KiB)", labels, nil),
	}
	if includeErrors {
		s.errorsCoreRd =    prometheus.NewDesc(prefix+"_errors_core_read_total", "Core read errors", labels, nil)
		s.errorsCoreWr =    prometheus.NewDesc(prefix+"_errors_core_write_total", "Core write errors", labels, nil)
		s.errorsCoreTotal = prometheus.NewDesc(prefix+"_errors_core_total", "Total core errors", labels, nil)
		s.errorsCacheRd =   prometheus.NewDesc(prefix+"_errors_cache_read_total", "Cache read errors", labels, nil)
		s.errorsCacheWr =   prometheus.NewDesc(prefix+"_errors_cache_write_total", "Cache write errors", labels, nil)
		s.errorsCacheTotal =prometheus.NewDesc(prefix+"_errors_cache_total", "Total cache errors", labels, nil)
		s.errorsTotal =     prometheus.NewDesc(prefix+"_errors_total", "Total errors", labels, nil)
	}
	return s
}

func (s *statsDescs) all() []*prometheus.Desc {
	descs := []*prometheus.Desc{
		s.usageOccupancy, s.usageFree, s.usageClean, s.usageDirty,
		s.reqRdHits, s.reqRdDeferred, s.reqRdPartialMisses, s.reqRdFullMisses, s.reqRdTotal,
		s.reqWrHits, s.reqWrDeferred, s.reqWrPartialMisses, s.reqWrFullMisses, s.reqWrTotal,
		s.reqRdPT, s.reqWrPT, s.reqServiced, s.reqPrefetchRA, s.reqCleaner, s.reqTotal,
		s.blocksCoreRd, s.blocksCoreWr, s.blocksCoreTotal,
		s.blocksCacheRd, s.blocksCacheWr, s.blocksCacheTotal,
		s.blocksVolumeRd, s.blocksVolumeWr, s.blocksVolumeTotal,
		s.blocksPTRd, s.blocksPTWr, s.blocksPTTotal,
		s.blocksPrefetchCoreRdRA, s.blocksPrefetchCacheWrRA,
		s.blocksCleanerCacheRd, s.blocksCleanerCoreWr,
		s.errorsCoreRd, s.errorsCoreWr, s.errorsCoreTotal,
		s.errorsCacheRd, s.errorsCacheWr, s.errorsCacheTotal,
		s.errorsTotal,
	}
	var out []*prometheus.Desc
	for _, d := range descs {
		if d != nil {
			out = append(out, d)
		}
	}
	return out
}

func (s *statsDescs) describe(ch chan<- *prometheus.Desc) {
	for _, d := range s.all() {
		ch <- d
	}
}

func (s *statsDescs) collect(ch chan<- prometheus.Metric, st *C.struct_cas_nl_stats, labels ...string) {
	gauge := func(desc *prometheus.Desc, v C.uint64_t) {
		if desc != nil {
			ch <- prometheus.MustNewConstMetric(desc, prometheus.GaugeValue, float64(v), labels...)
		}
	}
	counter := func(desc *prometheus.Desc, v C.uint64_t) {
		if desc != nil {
			ch <- prometheus.MustNewConstMetric(desc, prometheus.CounterValue, float64(v), labels...)
		}
	}

	gauge(s.usageOccupancy, st.usage_occupancy)
	gauge(s.usageFree, st.usage_free)
	gauge(s.usageClean, st.usage_clean)
	gauge(s.usageDirty, st.usage_dirty)

	counter(s.reqRdHits, st.req_rd_hits)
	counter(s.reqRdDeferred, st.req_rd_deferred)
	counter(s.reqRdPartialMisses, st.req_rd_partial_misses)
	counter(s.reqRdFullMisses, st.req_rd_full_misses)
	counter(s.reqRdTotal, st.req_rd_total)
	counter(s.reqWrHits, st.req_wr_hits)
	counter(s.reqWrDeferred, st.req_wr_deferred)
	counter(s.reqWrPartialMisses, st.req_wr_partial_misses)
	counter(s.reqWrFullMisses, st.req_wr_full_misses)
	counter(s.reqWrTotal, st.req_wr_total)
	counter(s.reqRdPT, st.req_rd_pt)
	counter(s.reqWrPT, st.req_wr_pt)
	counter(s.reqServiced, st.req_serviced)
	counter(s.reqPrefetchRA, st.req_prefetch_readahead)
	counter(s.reqCleaner, st.req_cleaner)
	counter(s.reqTotal, st.req_total)

	counter(s.blocksCoreRd, st.blocks_core_rd)
	counter(s.blocksCoreWr, st.blocks_core_wr)
	counter(s.blocksCoreTotal, st.blocks_core_total)
	counter(s.blocksCacheRd, st.blocks_cache_rd)
	counter(s.blocksCacheWr, st.blocks_cache_wr)
	counter(s.blocksCacheTotal, st.blocks_cache_total)
	counter(s.blocksVolumeRd, st.blocks_volume_rd)
	counter(s.blocksVolumeWr, st.blocks_volume_wr)
	counter(s.blocksVolumeTotal, st.blocks_volume_total)
	counter(s.blocksPTRd, st.blocks_pt_rd)
	counter(s.blocksPTWr, st.blocks_pt_wr)
	counter(s.blocksPTTotal, st.blocks_pt_total)
	counter(s.blocksPrefetchCoreRdRA, st.blocks_prefetch_core_rd_readahead)
	counter(s.blocksPrefetchCacheWrRA, st.blocks_prefetch_cache_wr_readahead)
	counter(s.blocksCleanerCacheRd, st.blocks_cleaner_cache_rd)
	counter(s.blocksCleanerCoreWr, st.blocks_cleaner_core_wr)

	counter(s.errorsCoreRd, st.errors_core_rd)
	counter(s.errorsCoreWr, st.errors_core_wr)
	counter(s.errorsCoreTotal, st.errors_core_total)
	counter(s.errorsCacheRd, st.errors_cache_rd)
	counter(s.errorsCacheWr, st.errors_cache_wr)
	counter(s.errorsCacheTotal, st.errors_cache_total)
	counter(s.errorsTotal, st.errors_total)
}

var (
	cacheLabels   = []string{"cache_id", "short_path", "path"}
	coreLabels    = []string{"cache_id", "core_id", "short_path", "path"}
	ioclassLabels = []string{"cache_id", "ioclass_id", "name"}
)

func NewCollector() *Collector {
	return &Collector{
		up:             prometheus.NewDesc("opencas_up", "Whether the Open CAS netlink interface is reachable", nil, nil),
		scrapeDuration: prometheus.NewDesc("opencas_scrape_duration_seconds", "Time spent collecting metrics from the kernel", nil, nil),

		cacheInfo:              prometheus.NewDesc("opencas_cache_info", "Cache instance info (always 1)", append(cacheLabels, "state", "mode", "cleaning_policy", "promotion_policy"), nil),
		cacheSize:              prometheus.NewDesc("opencas_cache_size_blocks", "Cache size in cache lines (4 KiB)", cacheLabels, nil),
		cacheLineSize:          prometheus.NewDesc("opencas_cache_line_size_bytes", "Cache line size in bytes", cacheLabels, nil),
		cacheOccupancy:         prometheus.NewDesc("opencas_cache_occupancy_blocks", "Cache occupancy in cache lines", cacheLabels, nil),
		cacheDirty:             prometheus.NewDesc("opencas_cache_dirty_blocks", "Dirty cache lines", cacheLabels, nil),
		cacheDirtyFor:          prometheus.NewDesc("opencas_cache_dirty_for_seconds", "Seconds since cache became dirty", cacheLabels, nil),
		cacheDirtyInitial:      prometheus.NewDesc("opencas_cache_dirty_initial_blocks", "Initial dirty cache lines at start", cacheLabels, nil),
		cacheFlushed:           prometheus.NewDesc("opencas_cache_flushed_blocks", "Flushed cache lines", cacheLabels, nil),
		cacheCoreCount:         prometheus.NewDesc("opencas_cache_core_count", "Number of cores attached", cacheLabels, nil),
		cacheMetaFootprint:     prometheus.NewDesc("opencas_cache_metadata_footprint_bytes", "Metadata memory footprint", cacheLabels, nil),
		cacheMetaEndOffset:     prometheus.NewDesc("opencas_cache_metadata_end_offset", "Metadata end offset on device", cacheLabels, nil),
		cacheFallbackPTErrors:  prometheus.NewDesc("opencas_cache_fallback_pt_errors_total", "Fallback pass-through errors", cacheLabels, nil),
		cacheInactiveOccupancy: prometheus.NewDesc("opencas_cache_inactive_occupancy_blocks", "Inactive core occupancy", cacheLabels, nil),
		cacheInactiveClean:     prometheus.NewDesc("opencas_cache_inactive_clean_blocks", "Inactive core clean lines", cacheLabels, nil),
		cacheInactiveDirty:     prometheus.NewDesc("opencas_cache_inactive_dirty_blocks", "Inactive core dirty lines", cacheLabels, nil),

		coreInfo:            prometheus.NewDesc("opencas_core_info", "Core instance info (always 1)", append(coreLabels, "state", "seq_cutoff_policy"), nil),
		coreSizeBytes:       prometheus.NewDesc("opencas_core_size_bytes", "Core device size in bytes", coreLabels, nil),
		coreDirty:           prometheus.NewDesc("opencas_core_dirty_blocks", "Dirty cache lines for this core", coreLabels, nil),
		coreDirtyFor:        prometheus.NewDesc("opencas_core_dirty_for_seconds", "Seconds since core became dirty", coreLabels, nil),
		coreFlushed:         prometheus.NewDesc("opencas_core_flushed_blocks", "Flushed cache lines for this core", coreLabels, nil),
		coreSeqCutoffThresh: prometheus.NewDesc("opencas_core_seq_cutoff_threshold_bytes", "Sequential cutoff threshold", coreLabels, nil),

		ioclassInfo:     prometheus.NewDesc("opencas_ioclass_info", "IO class info (always 1)", append(ioclassLabels, "mode", "priority"), nil),
		ioclassCurrSize: prometheus.NewDesc("opencas_ioclass_size_blocks", "Current IO class size in cache lines", ioclassLabels, nil),
		ioclassMinSize:  prometheus.NewDesc("opencas_ioclass_min_size", "IO class minimum size", ioclassLabels, nil),
		ioclassMaxSize:  prometheus.NewDesc("opencas_ioclass_max_size", "IO class maximum size", ioclassLabels, nil),

		cacheStats:   newStatsDescs("opencas_cache", cacheLabels, true),
		coreStats:    newStatsDescs("opencas_core", coreLabels, true),
		ioclassStats: newStatsDescs("opencas_ioclass", ioclassLabels, false),
	}
}

func (c *Collector) Describe(ch chan<- *prometheus.Desc) {
	ch <- c.up
	ch <- c.scrapeDuration

	ch <- c.cacheInfo
	ch <- c.cacheSize
	ch <- c.cacheLineSize
	ch <- c.cacheOccupancy
	ch <- c.cacheDirty
	ch <- c.cacheDirtyFor
	ch <- c.cacheDirtyInitial
	ch <- c.cacheFlushed
	ch <- c.cacheCoreCount
	ch <- c.cacheMetaFootprint
	ch <- c.cacheMetaEndOffset
	ch <- c.cacheFallbackPTErrors
	ch <- c.cacheInactiveOccupancy
	ch <- c.cacheInactiveClean
	ch <- c.cacheInactiveDirty

	ch <- c.coreInfo
	ch <- c.coreSizeBytes
	ch <- c.coreDirty
	ch <- c.coreDirtyFor
	ch <- c.coreFlushed
	ch <- c.coreSeqCutoffThresh

	ch <- c.ioclassInfo
	ch <- c.ioclassCurrSize
	ch <- c.ioclassMinSize
	ch <- c.ioclassMaxSize

	c.cacheStats.describe(ch)
	c.coreStats.describe(ch)
	c.ioclassStats.describe(ch)
}

func (c *Collector) Collect(ch chan<- prometheus.Metric) {
	t0 := time.Now()
	result, err := Dump()
	duration := time.Since(t0).Seconds()

	ch <- prometheus.MustNewConstMetric(c.scrapeDuration, prometheus.GaugeValue, duration)

	if err != nil {
		log.Printf("scrape failed: %v", err)
		ch <- prometheus.MustNewConstMetric(c.up, prometheus.GaugeValue, 0)
		return
	}
	defer result.Free()

	ch <- prometheus.MustNewConstMetric(c.up, prometheus.GaugeValue, 1)

	for i := range result.Caches {
		ca := &result.Caches[i]
		cid := fmt.Sprintf("%d", ca.id)
		path := cStr(ca.path[:])
		shortPath := resolveDevPath(path)
		labels := []string{cid, shortPath, path}

		ch <- prometheus.MustNewConstMetric(c.cacheInfo, prometheus.GaugeValue, 1,
			cid, shortPath, path,
			CacheStateStr(uint8(ca.state)), CacheModeStr(uint8(ca.mode)),
			CleaningPolicyStr(uint32(ca.cleaning.policy)),
			PromotionPolicyStr(uint32(ca.promotion.policy)))

		ch <- prometheus.MustNewConstMetric(c.cacheSize, prometheus.GaugeValue, float64(ca.size), labels...)
		ch <- prometheus.MustNewConstMetric(c.cacheLineSize, prometheus.GaugeValue, float64(ca.line_size), labels...)
		ch <- prometheus.MustNewConstMetric(c.cacheOccupancy, prometheus.GaugeValue, float64(ca.occupancy), labels...)
		ch <- prometheus.MustNewConstMetric(c.cacheDirty, prometheus.GaugeValue, float64(ca.dirty), labels...)
		ch <- prometheus.MustNewConstMetric(c.cacheDirtyFor, prometheus.GaugeValue, float64(ca.dirty_for), labels...)
		ch <- prometheus.MustNewConstMetric(c.cacheDirtyInitial, prometheus.GaugeValue, float64(ca.dirty_initial), labels...)
		ch <- prometheus.MustNewConstMetric(c.cacheFlushed, prometheus.GaugeValue, float64(ca.flushed), labels...)
		ch <- prometheus.MustNewConstMetric(c.cacheCoreCount, prometheus.GaugeValue, float64(ca.core_count), labels...)
		ch <- prometheus.MustNewConstMetric(c.cacheMetaFootprint, prometheus.GaugeValue, float64(ca.metadata_footprint), labels...)
		ch <- prometheus.MustNewConstMetric(c.cacheMetaEndOffset, prometheus.GaugeValue, float64(ca.metadata_end_offset), labels...)
		ch <- prometheus.MustNewConstMetric(c.cacheFallbackPTErrors, prometheus.CounterValue, float64(ca.fallback_pt_errors), labels...)
		ch <- prometheus.MustNewConstMetric(c.cacheInactiveOccupancy, prometheus.GaugeValue, float64(ca.inactive_occupancy), labels...)
		ch <- prometheus.MustNewConstMetric(c.cacheInactiveClean, prometheus.GaugeValue, float64(ca.inactive_clean), labels...)
		ch <- prometheus.MustNewConstMetric(c.cacheInactiveDirty, prometheus.GaugeValue, float64(ca.inactive_dirty), labels...)

		c.cacheStats.collect(ch, &ca.stats, labels...)
	}

	for i := range result.Cores {
		co := &result.Cores[i]
		cid := fmt.Sprintf("%d", co.cache_id)
		oid := fmt.Sprintf("%d", co.id)
		path := cStr(co.path[:])
		shortPath := resolveDevPath(path)
		labels := []string{cid, oid, shortPath, path}

		ch <- prometheus.MustNewConstMetric(c.coreInfo, prometheus.GaugeValue, 1,
			cid, oid, shortPath, path,
			CoreStateStr(uint8(co.state)),
			SeqCutoffPolicyStr(uint8(co.seq_cutoff_policy)))

		ch <- prometheus.MustNewConstMetric(c.coreSizeBytes, prometheus.GaugeValue, float64(co.size_bytes), labels...)
		ch <- prometheus.MustNewConstMetric(c.coreDirty, prometheus.GaugeValue, float64(co.dirty), labels...)
		ch <- prometheus.MustNewConstMetric(c.coreDirtyFor, prometheus.GaugeValue, float64(co.dirty_for), labels...)
		ch <- prometheus.MustNewConstMetric(c.coreFlushed, prometheus.GaugeValue, float64(co.flushed), labels...)
		ch <- prometheus.MustNewConstMetric(c.coreSeqCutoffThresh, prometheus.GaugeValue, float64(co.seq_cutoff_threshold), labels...)

		c.coreStats.collect(ch, &co.stats, labels...)
	}

	for i := range result.IOClasses {
		io := &result.IOClasses[i]
		cid := fmt.Sprintf("%d", io.cache_id)
		oid := fmt.Sprintf("%d", io.id)
		name := cStr(io.name[:])
		labels := []string{cid, oid, name}

		ch <- prometheus.MustNewConstMetric(c.ioclassInfo, prometheus.GaugeValue, 1,
			cid, oid, name,
			CacheModeStr(uint8(io.cache_mode)),
			fmt.Sprintf("%d", int16(io.priority)))

		ch <- prometheus.MustNewConstMetric(c.ioclassCurrSize, prometheus.GaugeValue, float64(io.curr_size), labels...)
		ch <- prometheus.MustNewConstMetric(c.ioclassMinSize, prometheus.GaugeValue, float64(io.min_size), labels...)
		ch <- prometheus.MustNewConstMetric(c.ioclassMaxSize, prometheus.GaugeValue, float64(io.max_size), labels...)

		c.ioclassStats.collect(ch, &io.stats, labels...)
	}
}
