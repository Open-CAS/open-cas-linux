/*
* Copyright(c) 2012-2019 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#include <stdio.h>
#include <errno.h>
#include <assert.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <inttypes.h>
#include <fstab.h>
#include <linux/fs.h>
#include <linux/types.h>
#include <linux/major.h>
#include <mntent.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#include <sys/types.h>
#include <time.h>
#include "cas_lib.h"
#include "extended_err_msg.h"
#include "cas_lib_utils.h"
#include <pthread.h>
#include <stdbool.h>
#include <cas_ioctl_codes.h>

#include "csvparse.h"
#include "statistics_view.h"
#include "safeclib/safe_str_lib.h"
#include "ocf/ocf_cache.h"

#define IOCLASS_UNCLASSIFIED (0)

#define UNIT_REQUESTS "Requests"
#define UNIT_BLOCKS "4KiB blocks"

static inline float percentage(uint64_t numerator, uint64_t denominator)
{
	float result;
	if (denominator) {
		result = 100.0 * numerator / denominator;
	} else {
		result = 0;
	}
	return result;
}

static inline long unsigned int cache_line_in_4k(uint64_t size,
		ocf_cache_line_size_t cache_line_size)
{
	long unsigned int result;

	result = size * (cache_line_size / 4);

	return result;
}

static inline unsigned long bytes_to_4k(uint64_t size)
{
	return (size + 4095UL) >> 12;
}

static float calc_gb(uint32_t clines)
{
	return (float) clines * 4 * KiB / GiB;
}

static void print_dirty_for_time(uint32_t t, FILE *outfile)
{
	uint32_t d, h, m, s;

	fprintf(outfile, "%u,[s],", t);

	if (!t) {
		fprintf(outfile, "Cache clean");
		return;
	}

	d = t / (24 * 3600);
	h = (t % (24 * 3600)) / 3600;
	m = (t % 3600) / 60;
	s = (t % 60);

	if (d) {
		fprintf(outfile, "%u [d] ", d);
	}
	if (h) {
		fprintf(outfile, "%u [h] ", h);
	}
	if (m) {
		fprintf(outfile, "%u [m] ", m);
	}
	if (s) {
		fprintf(outfile, "%u [s] ", s);
	}
}

__attribute__((format(printf, 3, 4)))
static void print_kv_pair(FILE *outfile, const char *title, const char *fmt, ...)
{
	va_list ap;

	fprintf(outfile, TAG(KV_PAIR) "\"%s\",", title);
	va_start(ap, fmt);
	vfprintf(outfile, fmt, ap);
	va_end(ap);
	fprintf(outfile, "\n");
}

static void print_kv_pair_time(FILE *outfile, const char *title, uint32_t time)
{
	fprintf(outfile, TAG(KV_PAIR) "\"%s\",", title);
	print_dirty_for_time(time, outfile);
	fprintf(outfile, "\n");
}

static void begin_record(FILE *outfile)
{
	fprintf(outfile, TAG(RECORD) "\n");
}

static void print_table_header(FILE *outfile, uint32_t ncols, ...)
{
	va_list ap;
	const char *s;

	fprintf(outfile, TAG(TABLE_HEADER));
	va_start(ap, ncols);
	while (ncols--) {
		s = va_arg(ap, const char *);
		fprintf(outfile, "\"%s\"%s", s, ncols ? "," : "\n");
	}
	va_end(ap);
}

static void print_val_perc_table_elem(FILE *outfile, const char *tag,
				      const char *title, const char *unit,
				      uint64_t percent, const char * fmt,
				      va_list ap)
{
	float percent_val = (percent % 10 >= 5 ? percent+5 : percent) / 100.f;
	fprintf(outfile, "%s\"%s\",", tag, title);
	vfprintf(outfile, fmt, ap);
	fprintf(outfile, ",%.1f", percent_val);
	if (unit) {
		fprintf(outfile, ",\"[%s]\"", unit);
	}
	fprintf(outfile, "\n");
}

__attribute__((format(printf, 5, 6)))
static inline void print_val_perc_table_row(FILE *outfile, const char *title,
					    const char *unit, float percent,
					    const char *fmt, ...)
{
	va_list ap;
	va_start(ap, fmt);
	print_val_perc_table_elem(outfile, TAG(TABLE_ROW), title, unit,
				  percent, fmt, ap);
	va_end(ap);
}

__attribute__((format(printf, 5, 6)))
static inline void print_val_perc_table_section(FILE *outfile, const char *title,
						const char *unit, uint64_t percent,
						const char *fmt, ...)
{
	va_list ap;
	va_start(ap, fmt);
	print_val_perc_table_elem(outfile, TAG(TABLE_SECTION), title, unit,
				  percent, fmt, ap);
	va_end(ap);
}

static inline const char *make_row_title(const char *s1, const char *s2)
{
	static char buffer[64];
	snprintf(buffer, sizeof(buffer), "%s %s", s1, s2);
	return buffer;
}

static void print_core_conf(const struct kcas_core_info *info, FILE *outfile)
{
	uint64_t core_size;
	float core_size_gb;

	core_size = info->stats.core_size_bytes / KiB / 4;
	core_size_gb = calc_gb(core_size);

	print_kv_pair(outfile, "Core Id", "%i", info->core_id);
	print_kv_pair(outfile, "Core Device", "%s",
				info->core_path_name);
	print_kv_pair(outfile, "Exported Object", "/dev/cas%d-%d",
				info->cache_id, info->core_id);
	print_kv_pair(outfile, "Core Size", "%lu, [4KiB Blocks], %.2f, [GiB]",
				core_size, core_size_gb);
	print_kv_pair_time(outfile, "Dirty for", info->stats.dirty_for);

	print_kv_pair(outfile, "Status", "%s",
			get_core_state_name(info->state));

	print_kv_pair(outfile, "Seq cutoff threshold", "%llu, [KiB]",
				info->stats.seq_cutoff_threshold / KiB);

	print_kv_pair(outfile, "Seq cutoff policy", "%s",
				seq_cutoff_policy_to_name(info->stats.seq_cutoff_policy));
}

static void print_usage_header(FILE* outfile)
{
	print_table_header(outfile, 4, "Usage statistics", "Count",
			   "%", "[Units]");
}

static void print_usage_stats(struct ocf_stats_usage *stats, FILE* outfile)
{
	print_usage_header(outfile);

	print_val_perc_table_row(outfile, "Occupancy", UNIT_BLOCKS,
					stats->occupancy.fraction, "%lu", stats->occupancy.value);
	print_val_perc_table_row(outfile, "Free", UNIT_BLOCKS,
					stats->free.fraction, "%lu", stats->free.value);
	print_val_perc_table_row(outfile, "Clean", UNIT_BLOCKS,
					stats->clean.fraction, "%lu", stats->clean.value);
	print_val_perc_table_row(outfile, "Dirty", UNIT_BLOCKS,
					stats->dirty.fraction, "%lu", stats->dirty.value);
}

static void print_req_stats(const struct ocf_stats_requests *stats,
		FILE *outfile)
{
	print_table_header(outfile, 4, "Request statistics", "Count",
			   "%", "[Units]");

	print_val_perc_table_section(outfile, "Read hits",
				     UNIT_REQUESTS, stats->rd_hits.fraction, "%lu",
					 stats->rd_hits.value);
	print_val_perc_table_row(outfile, "Read partial misses",
				     UNIT_REQUESTS, stats->rd_partial_misses.fraction, "%lu",
					 stats->rd_partial_misses.value);
	print_val_perc_table_row(outfile, "Read full misses",
				     UNIT_REQUESTS, stats->rd_full_misses.fraction, "%lu",
					 stats->rd_full_misses.value);
	print_val_perc_table_row(outfile, "Read total",
				     UNIT_REQUESTS, stats->rd_total.fraction, "%lu",
					 stats->rd_total.value);

	print_val_perc_table_section(outfile, "Write hits",
				     UNIT_REQUESTS, stats->wr_hits.fraction, "%lu",
					 stats->wr_hits.value);
	print_val_perc_table_row(outfile, "Write partial misses",
				     UNIT_REQUESTS, stats->wr_partial_misses.fraction, "%lu",
					 stats->wr_partial_misses.value);
	print_val_perc_table_row(outfile, "Write full misses",
				     UNIT_REQUESTS, stats->wr_full_misses.fraction, "%lu",
					 stats->wr_full_misses.value);
	print_val_perc_table_row(outfile, "Write total",
				     UNIT_REQUESTS, stats->wr_total.fraction, "%lu",
					 stats->wr_total.value);

	print_val_perc_table_section(outfile, "Pass-Through reads",
				     UNIT_REQUESTS, stats->rd_pt.fraction, "%lu",
					 stats->rd_pt.value);
	print_val_perc_table_row(outfile, "Pass-Through writes",
				     UNIT_REQUESTS, stats->wr_pt.fraction, "%lu",
					 stats->wr_pt.value);
	print_val_perc_table_row(outfile, "Serviced requests",
				     UNIT_REQUESTS, stats->serviced.fraction, "%lu",
					 stats->serviced.value);

	print_val_perc_table_section(outfile, "Total requests",
				     UNIT_REQUESTS, stats->total.fraction, "%lu",
					 stats->total.value);
}

#define get_stat_name(__dst, __len, __name, __postfix) \
	memset(__dst, 0, __len); \
	snprintf(__dst, __len, "%s%s", __name, __postfix);


static void print_blk_stats(const struct ocf_stats_blocks *stats,
		bool cache_stats, FILE *outfile)
{
	print_table_header(outfile, 4, "Block statistics", "Count",
			   "%", "[Units]");

	char *postfix = (cache_stats ? "(s)" : "");
	size_t max_stat_len = 128;
	char stat_name[max_stat_len];

	get_stat_name(stat_name, max_stat_len, "Reads from core", postfix);
	print_val_perc_table_section(outfile, stat_name,
				     UNIT_BLOCKS, stats->core_volume_rd.fraction, "%lu",
					 stats->core_volume_rd.value);

	get_stat_name(stat_name, max_stat_len, "Writes to core", postfix);
	print_val_perc_table_row(outfile, stat_name,
				     UNIT_BLOCKS, stats->core_volume_wr.fraction, "%lu",
					 stats->core_volume_wr.value);

	get_stat_name(stat_name, max_stat_len, "Total to/from core", postfix);
	print_val_perc_table_row(outfile, stat_name,
				     UNIT_BLOCKS, stats->core_volume_total.fraction, "%lu",
					 stats->core_volume_total.value);

	print_val_perc_table_section(outfile, "Reads from cache",
				     UNIT_BLOCKS, stats->cache_volume_rd.fraction, "%lu",
					 stats->cache_volume_rd.value);

	print_val_perc_table_row(outfile, "Writes to cache",
				     UNIT_BLOCKS, stats->cache_volume_wr.fraction, "%lu",
					 stats->cache_volume_wr.value);

	print_val_perc_table_row(outfile, "Total to/from cache",
				     UNIT_BLOCKS, stats->cache_volume_total.fraction, "%lu",
					 stats->cache_volume_total.value);

	get_stat_name(stat_name, max_stat_len, "Reads from exported object",
					postfix);
	print_val_perc_table_section(outfile, stat_name,
				     UNIT_BLOCKS, stats->volume_rd.fraction, "%lu",
					 stats->volume_rd.value);

	get_stat_name(stat_name, max_stat_len, "Writes to exported object",
					postfix);
	print_val_perc_table_row(outfile, stat_name,
				     UNIT_BLOCKS, stats->volume_wr.fraction, "%lu",
					 stats->volume_wr.value);

	get_stat_name(stat_name, max_stat_len, "Total to/from exported object",
					postfix);
	print_val_perc_table_row(outfile, stat_name,
				     UNIT_BLOCKS, stats->volume_total.fraction, "%lu",
					 stats->volume_total.value);
}

static void print_err_stats(const struct ocf_stats_errors *stats,
		FILE *outfile)
{
	print_table_header(outfile, 4, "Error statistics", "Count", "%",
			   "[Units]");

	print_val_perc_table_section(outfile, "Cache read errors",
				     UNIT_REQUESTS, stats->cache_volume_rd.fraction, "%lu",
					 stats->cache_volume_rd.value);
	print_val_perc_table_row(outfile, "Cache write errors",
				     UNIT_REQUESTS, stats->cache_volume_wr.fraction, "%lu",
					 stats->cache_volume_wr.value);
	print_val_perc_table_row(outfile, "Cache total errors",
				     UNIT_REQUESTS, stats->cache_volume_total.fraction, "%lu",
					 stats->cache_volume_total.value);

	print_val_perc_table_section(outfile, "Core read errors",
				     UNIT_REQUESTS, stats->core_volume_rd.fraction, "%lu",
					 stats->core_volume_rd.value);
	print_val_perc_table_row(outfile, "Core write errors",
				     UNIT_REQUESTS, stats->core_volume_wr.fraction, "%lu",
					 stats->core_volume_wr.value);
	print_val_perc_table_row(outfile, "Core total errors",
				     UNIT_REQUESTS, stats->core_volume_total.fraction, "%lu",
					 stats->core_volume_total.value);

	print_val_perc_table_section(outfile, "Total errors",
				     UNIT_REQUESTS, stats->total.fraction, "%lu",
					 stats->total.value);
}

void cache_stats_core_counters(const struct kcas_core_info *info,
			struct kcas_get_stats *stats,
			unsigned int stats_filters, FILE *outfile)
{
	begin_record(outfile);

	if (stats_filters & STATS_FILTER_CONF)
		print_core_conf(info, outfile);

	if (stats_filters & STATS_FILTER_USAGE)
		print_usage_stats(&stats->usage, outfile);

	if (stats_filters & STATS_FILTER_REQ)
		print_req_stats(&stats->req, outfile);

	if (stats_filters & STATS_FILTER_BLK)
		print_blk_stats(&stats->blocks, false, outfile);

	if (stats_filters & STATS_FILTER_ERR)
		print_err_stats(&stats->errors, outfile);
}

static void print_stats_ioclass_conf(const struct kcas_io_class* io_class,
				     FILE* outfile)
{
	print_kv_pair(outfile, "IO class ID", "%d", io_class->class_id);
	print_kv_pair(outfile, "IO class name", "%s", io_class->info.name);
	if (-1 == io_class->info.priority) {
		print_kv_pair(outfile, "Eviction priority", "Pinned");
	} else {
		print_kv_pair(outfile, "Eviction priority", "%d",
			      io_class->info.priority);
	}
	print_kv_pair(outfile, "Selective allocation", "%s",
		      io_class->info.cache_mode != ocf_cache_mode_pt ?
		      "Yes" : "No");
}

static void print_stats_ioclass_usage(uint32_t part_id,
				      const struct ocf_stats_io_class* part_stats,
				      const struct ocf_stats_io_class* denominators,
				      FILE *outfile, uint32_t cache_size,
				      ocf_cache_line_size_t cache_line_size)
{
	float percent;
	uint64_t clean;

	print_table_header(outfile, 4, "Usage statistics", "Count", "%", "[Units]");

	percent = percentage(part_stats->occupancy_clines, cache_size);
	print_val_perc_table_section(outfile, "Occupancy", UNIT_BLOCKS, percent,
			"%ld",
			cache_line_in_4k(part_stats->occupancy_clines,
			cache_line_size));

	/* Occupancy, dirty, etc. information. */
	/* For now free stat should be printed for the unclassified IO class. */
	if (IOCLASS_UNCLASSIFIED == part_id) {
		print_val_perc_table_row(outfile, "Free", UNIT_BLOCKS,
					100.0f, "%ld",
					cache_line_in_4k(part_stats->free_clines,
					cache_line_size));
	} else {
		print_val_perc_table_row(outfile, "Free", UNIT_BLOCKS,
					     0.0f, "%d", 0);
	}

	clean = part_stats->occupancy_clines - part_stats->dirty_clines;
	percent = percentage(clean, part_stats->occupancy_clines);
	print_val_perc_table_row(outfile, "Clean", UNIT_BLOCKS, percent,
				"%ld",
				cache_line_in_4k(clean, cache_line_size));

	percent = percentage(part_stats->dirty_clines, part_stats->occupancy_clines);
	print_val_perc_table_row(outfile, "Dirty", UNIT_BLOCKS, percent,
				"%ld",
				cache_line_in_4k(part_stats->dirty_clines,
					cache_line_size));
}

static void print_stats_ioclass_req(const struct ocf_stats_io_class* part_stats,
				    const struct ocf_stats_io_class* denominators,
				    FILE *outfile, uint64_t req_grand_total)
{
	const struct ocf_stats_req *req_stats;
	float percent;
	uint64_t hits;
	uint64_t serv_reqs = 0;
	uint64_t total_reqs = 0;

	print_table_header(outfile, 4, "Request statistics", "Count",
			   "%", "[Units]");

	/* Handling read operations. */
	req_stats = &part_stats->read_reqs;

	hits = req_stats->total - (req_stats->partial_miss + req_stats->full_miss);
	percent = percentage(hits, req_grand_total);
	print_val_perc_table_section(outfile, "Read hits", UNIT_REQUESTS, percent,
				 "%ld", hits);

	percent = percentage(req_stats->partial_miss, req_grand_total);
	print_val_perc_table_row(outfile, "Read partial misses", UNIT_REQUESTS,
				 percent, "%ld", req_stats->partial_miss);

	percent = percentage(req_stats->full_miss, req_grand_total);
	print_val_perc_table_row(outfile, "Read full misses", UNIT_REQUESTS,
				 percent, "%ld", req_stats->full_miss);

	percent = percentage(req_stats->total, req_grand_total);
	print_val_perc_table_row(outfile, "Read total", UNIT_REQUESTS,
				     percent, "%ld", req_stats->total);

	/* Handling write operations. */
	req_stats = &part_stats->write_reqs;

	hits = req_stats->total - (req_stats->partial_miss + req_stats->full_miss);
	percent = percentage(hits, req_grand_total);
	print_val_perc_table_section(outfile, "Write hits", UNIT_REQUESTS, percent,
				 "%ld", hits);

	percent = percentage(req_stats->partial_miss, req_grand_total);
	print_val_perc_table_row(outfile, "Write partial misses", UNIT_REQUESTS,
				 percent, "%ld", req_stats->partial_miss);

	percent = percentage(req_stats->full_miss, req_grand_total);
	print_val_perc_table_row(outfile, "Write full misses", UNIT_REQUESTS,
				 percent, "%ld", req_stats->full_miss);

	percent = percentage(req_stats->total, req_grand_total);
	print_val_perc_table_row(outfile, "Write total", UNIT_REQUESTS,
				     percent, "%ld", req_stats->total);

	/* Pass-Through requests. */
	percent = percentage(part_stats->read_reqs.pass_through, req_grand_total);
	print_val_perc_table_section(outfile, "Pass-Through reads", UNIT_REQUESTS,
				     percent, "%lu",
				     part_stats->read_reqs.pass_through);

	percent = percentage(part_stats->write_reqs.pass_through, req_grand_total);
	print_val_perc_table_row(outfile, "Pass-Through writes", UNIT_REQUESTS,
				 percent, "%lu",
				 part_stats->write_reqs.pass_through);

	/* Summary. */
	serv_reqs += part_stats->read_reqs.total;
	serv_reqs += part_stats->write_reqs.total;
	total_reqs = serv_reqs + part_stats->read_reqs.pass_through +
			part_stats->write_reqs.pass_through;

	percent = percentage(serv_reqs, req_grand_total);
	print_val_perc_table_row(outfile, "Serviced requests", UNIT_REQUESTS,
				 percent, "%lu", serv_reqs);

	percent = percentage(total_reqs, req_grand_total);
	print_val_perc_table_section(outfile, "Total requests", UNIT_REQUESTS,
				percent, "%lu", total_reqs);

}


void cache_stats_inactive_usage(int ctrl_fd, const struct kcas_cache_info *cache_info,
		      unsigned int cache_id, FILE* outfile)
{
	print_table_header(outfile, 4, "Inactive usage statistics", "Count",
			   "%", "[Units]");

    print_val_perc_table_row(outfile, "Inactive Occupancy", UNIT_BLOCKS,
				percentage(cache_info->info.inactive.occupancy,
					cache_info->info.size),
					"%lu",
					cache_line_in_4k(cache_info->info.inactive.occupancy,
					cache_info->info.cache_line_size / KiB));

    print_val_perc_table_row(outfile, "Inactive Clean", UNIT_BLOCKS,
				percentage(cache_info->info.inactive.occupancy -
					cache_info->info.inactive.dirty,
					cache_info->info.occupancy),
					"%lu",
					cache_line_in_4k(cache_info->info.inactive.occupancy -
					cache_info->info.inactive.dirty,
					cache_info->info.cache_line_size / KiB));

    print_val_perc_table_row(outfile, "Inactive Dirty", UNIT_BLOCKS,
				percentage(cache_info->info.inactive.dirty,
					cache_info->info.occupancy),
					"%lu",
					cache_line_in_4k(cache_info->info.inactive.dirty,
					cache_info->info.cache_line_size / KiB));
}

static void print_stats_ioclass_blk(const struct ocf_stats_io_class* part_stats,
		const struct ocf_stats_io_class* denominators, FILE *outfile,
		ocf_cache_line_size_t cache_line_size)
{
	float percent;

	print_table_header(outfile, 4, "Block statistics", "Count", "%",
			   "[Units]");

	/* Handling read operations. */
	percent = percentage(part_stats->blocks.read, denominators->blocks.read);
	print_val_perc_table_section(outfile, "Blocks reads", UNIT_BLOCKS,
				     percent, "%ld",
				     bytes_to_4k(part_stats->blocks.read));

	/* Handling write operations. */
	percent = percentage(part_stats->blocks.write, denominators->blocks.write);
	print_val_perc_table_section(outfile, "Blocks writes", UNIT_BLOCKS,
				     percent, "%ld",
				     bytes_to_4k(part_stats->blocks.write));
}

/**
 * print statistics regarding single io class (partition)
 */
void print_stats_ioclass(const struct kcas_cache_info *cache_info,
			 const struct kcas_io_class *io_class,
			 FILE *outfile, unsigned int stats_filters,
			 struct ocf_stats_io_class *denominators, uint64_t req_grand_total,
			 ocf_cache_line_size_t cache_line_size)
{
	const struct ocf_stats_io_class *part_stats;
	uint32_t part_id;

	part_id = io_class->class_id;
	part_stats = &io_class->stats;

	begin_record(outfile);

	if (stats_filters & STATS_FILTER_CONF) {
		print_stats_ioclass_conf(io_class, outfile);
	}

	if (stats_filters & STATS_FILTER_USAGE) {
		print_stats_ioclass_usage(part_id, part_stats, denominators,
					  outfile, cache_info->info.size,
					  cache_line_size);
	}

	if (stats_filters & STATS_FILTER_REQ) {
		print_stats_ioclass_req(part_stats, denominators, outfile, req_grand_total);
	}

	if (stats_filters & STATS_FILTER_BLK) {
		print_stats_ioclass_blk(part_stats, denominators, outfile,
					cache_line_size);
	}
}

static int read_io_class_stats(int ctrl_fd, int cache_id, int core_id,
			       int part_id,
			       struct kcas_io_class *io_class_tmp,
			       struct kcas_io_class *io_class_out)
{
	memset(io_class_tmp, 0, sizeof(*io_class_tmp));

	io_class_tmp->cache_id = cache_id;
	io_class_tmp->class_id = part_id;
	if (core_id != OCF_CORE_ID_INVALID) {
		io_class_tmp->core_id = core_id;
		io_class_tmp->get_stats = 1;
	}

	if (ioctl(ctrl_fd, KCAS_IOCTL_PARTITION_INFO, io_class_tmp) < 0) {
		io_class_out->ext_err_code = io_class_tmp->ext_err_code;
		return FAILURE;
	}

	io_class_out->ext_err_code = io_class_tmp->ext_err_code;
	strncpy_s(io_class_out->info.name, sizeof(io_class_out->info.name),
		  io_class_tmp->info.name, sizeof(io_class_tmp->info.name) - 1);
	io_class_out->class_id = io_class_tmp->class_id;
	io_class_out->info.priority = io_class_tmp->info.priority;
	io_class_out->info.cache_mode = io_class_tmp->info.cache_mode;

	return SUCCESS;

}

static inline void accum_block_stats(struct ocf_stats_block *to, const struct ocf_stats_block *from)
{
	to->read += from->read;
	to->write += from->write;
}

static inline void accum_req_stats(struct ocf_stats_req *to, const struct ocf_stats_req *from)
{
	to->full_miss += from->full_miss;
	to->partial_miss += from->partial_miss;
	to->total += from->total;
	to->pass_through += from->pass_through;
}

/**
 * @brief print per-io-class statistics for all configured io classes
 *
 */
int cache_stats_ioclasses(int ctrl_fd, const struct kcas_cache_info *cache_info,
			  unsigned int cache_id, unsigned int core_id,
			  int io_class_id, FILE *outfile,
			  unsigned int stats_filters)
{
	int i, j, _core_id;
	struct ocf_stats_io_class denominators;
	struct ocf_stats_io_class* part_stats_cum;
	struct ocf_stats_io_class* part_stats_core;
	struct kcas_io_class io_class_new[OCF_IO_CLASS_MAX] = {};
	struct kcas_io_class io_class_tmp;
	uint64_t req_grand_total = 0;
	memset(&denominators, 0, sizeof(denominators));

	if (-1 != io_class_id && io_class_id >= OCF_IO_CLASS_MAX) {
		cas_printf(LOG_ERR, "Partition %d does not exists\n", io_class_id);
		return FAILURE;
	}

	for (i = 0; i < OCF_IO_CLASS_MAX; ++i) {
		/* print stats for each ioclass */

		if (!cache_info->info.core_count) {
			if (read_io_class_stats(ctrl_fd, cache_id, 0, i,
						&io_class_tmp,
						&io_class_new[i])) {
				if (io_class_new[i].ext_err_code ==
				    OCF_ERR_IO_CLASS_NOT_EXIST) {
					continue;
				}

				cas_printf(LOG_ERR,
					   "Error while retrieving stats for partition %d\n",
					   i);
				print_err(io_class_new[i].ext_err_code);
				goto cleanup;
			}
		} else {
			for (j = 0; j < cache_info->info.core_count; ++j) {

				_core_id = cache_info->core_id[j];
				if (core_id != OCF_CORE_ID_INVALID && core_id != _core_id) {
					continue;
				}

				if (read_io_class_stats(ctrl_fd, cache_id,
							_core_id, i,
							&io_class_tmp,
							&io_class_new[i])) {
					if (io_class_new[i].ext_err_code ==
					    OCF_ERR_IO_CLASS_NOT_EXIST) {
						continue;
					}

					cas_printf(LOG_ERR,
						   "Error while retrieving stats for partition %d, core %d\n",
						   i, core_id);
					print_err(io_class_new[i].ext_err_code);
					goto cleanup;
				}

				part_stats_cum = &io_class_new[i].stats;
				part_stats_core = &io_class_tmp.stats;

				part_stats_cum->free_clines =
					part_stats_core->free_clines;

				part_stats_cum->occupancy_clines +=
					part_stats_core->occupancy_clines;
				part_stats_cum->dirty_clines +=
					part_stats_core->dirty_clines;

				accum_block_stats(&part_stats_cum->blocks,
						  &part_stats_core->blocks);
				accum_req_stats(&part_stats_cum->read_reqs,
						&part_stats_core->read_reqs);
				accum_req_stats(&part_stats_cum->write_reqs,
						&part_stats_core->write_reqs);
			}
		}
	}

	for (i = 0; i < OCF_IO_CLASS_MAX; ++i) {
		if (io_class_new[i].ext_err_code == OCF_ERR_IO_CLASS_NOT_EXIST) {
			continue;
		}
		const struct ocf_stats_io_class *ps = &io_class_new[i].stats;

		denominators.occupancy_clines += ps->occupancy_clines;
		denominators.dirty_clines += ps->dirty_clines;

		accum_block_stats(&denominators.blocks, &ps->blocks);

		accum_req_stats(&denominators.read_reqs, &ps->read_reqs);
		accum_req_stats(&denominators.write_reqs, &ps->write_reqs);
	}
	req_grand_total += denominators.read_reqs.total;
	req_grand_total += denominators.read_reqs.pass_through;
	req_grand_total += denominators.write_reqs.total;
	req_grand_total += denominators.write_reqs.pass_through;

	if (-1 == io_class_id) {
		for (i = 0; i < OCF_IO_CLASS_MAX; ++i) {
			if (io_class_new[i].ext_err_code == OCF_ERR_IO_CLASS_NOT_EXIST) {
				continue;
			}
			print_stats_ioclass(cache_info, &io_class_new[i],
					outfile, stats_filters, &denominators, req_grand_total,
					cache_info->info.cache_line_size / KiB);
		}
	} else {
		if (io_class_new[io_class_id].ext_err_code == OCF_ERR_IO_CLASS_NOT_EXIST) {
			cas_printf(LOG_ERR, "Partition %d does not exists\n", io_class_id);
			return FAILURE;
		}
		print_stats_ioclass(cache_info, &io_class_new[io_class_id],
				outfile, stats_filters, &denominators, req_grand_total,
				cache_info->info.cache_line_size / KiB);
	}

	return SUCCESS;

cleanup:
	close(ctrl_fd);

	if (outfile != stdout) {
		fclose(outfile);
	}
	return FAILURE;
}

static inline void accum_error_stats(struct ocf_stats_error *to,
				     const struct ocf_stats_error *from)
{
	to->read += from->read;
	to->write += from->write;
}

int cache_stats_conf(int ctrl_fd, const struct kcas_cache_info *cache_info,
		     unsigned int cache_id, FILE *outfile)
{
	float flush_progress = 0;
	float value;
	const char *units;
	long unsigned int cache_size;
	const char *cache_path;
	char dev_path[MAX_STR_LEN];
	int inactive_cores;

	if (get_dev_path(cache_info->cache_path_name, dev_path, sizeof(dev_path)) != SUCCESS)
		cache_path = cache_info->cache_path_name;
	else
		cache_path = dev_path;

	flush_progress = calculate_flush_progress(cache_info->info.dirty,
			cache_info->info.flushed);

	print_kv_pair(outfile, "Cache Id", "%d",
		      cache_info->cache_id);

	cache_size = cache_line_in_4k(cache_info->info.size,
			cache_info->info.cache_line_size / KiB);

	print_kv_pair(outfile, "Cache Size", "%lu, [4KiB Blocks], %.2f, [GiB]",
		      cache_size,
		      (float) cache_size * (4 * KiB) / GiB);

	print_kv_pair(outfile, "Cache Device", "%s",
		      cache_path);
	print_kv_pair(outfile, "Core Devices", "%d",
		      cache_info->info.core_count);
	inactive_cores = get_inactive_core_count(cache_info);
	if (inactive_cores < 0)
		return FAILURE;
	print_kv_pair(outfile, "Inactive Core Devices", "%d", inactive_cores);

	print_kv_pair(outfile, "Write Policy", "%s",
		      cache_mode_to_name(cache_info->info.cache_mode));
	print_kv_pair(outfile, "Eviction Policy", "%s",
		      eviction_policy_to_name(cache_info->info.eviction_policy));
	print_kv_pair(outfile, "Cleaning Policy", "%s",
		      cleaning_policy_to_name(cache_info->info.cleaning_policy));
	print_kv_pair(outfile, "Cache line size", "%llu, [KiB]",
		      cache_info->info.cache_line_size / KiB);

	metadata_memory_footprint(cache_info->info.metadata_footprint,
				  &value, &units);
	print_kv_pair(outfile, "Metadata Memory Footprint", "%.1f, [%s]",
		      value, units);

	print_kv_pair_time(outfile, "Dirty for", cache_info->info.dirty_for);

	print_kv_pair(outfile, "Metadata Mode", "%s",
		      metadata_mode_to_name(cache_info->metadata_mode));

	if (flush_progress) {
		print_kv_pair(outfile, "Status", "%s (%3.1f %%)",
			      "Flushing", flush_progress);
	} else {
		print_kv_pair(outfile, "Status", "%s",
				get_cache_state_name(cache_info->info.state));
	}

	return SUCCESS;
}

void cache_stats_counters(struct kcas_get_stats *cache_stats, FILE *outfile,
		unsigned int stats_filters)
{
	/* Totals for requests stats. */
	if (stats_filters & STATS_FILTER_REQ)
		print_req_stats(&cache_stats->req, outfile);

	/* Totals for blocks stats. */
	if (stats_filters & STATS_FILTER_BLK)
		print_blk_stats(&cache_stats->blocks, true, outfile);

	/* Totals for error stats. */
	if (stats_filters & STATS_FILTER_ERR)
		print_err_stats(&cache_stats->errors, outfile);
}

static int cache_stats(int ctrl_fd, const struct kcas_cache_info *cache_info,
		      unsigned int cache_id, FILE *outfile, unsigned int stats_filters)
{
	struct kcas_get_stats cache_stats = {};
	cache_stats.cache_id = cache_id;
	cache_stats.core_id = OCF_CORE_ID_INVALID;
	cache_stats.part_id = OCF_IO_CLASS_INVALID;

	if (ioctl(ctrl_fd, KCAS_IOCTL_GET_STATS, &cache_stats) < 0)
		return FAILURE;

	begin_record(outfile);

	if (stats_filters & STATS_FILTER_CONF)
		cache_stats_conf(ctrl_fd, cache_info, cache_id, outfile);

	if (stats_filters & STATS_FILTER_USAGE)
		print_usage_stats(&cache_stats.usage, outfile);

	if ((cache_info->info.state & (1 << ocf_cache_state_incomplete))
			&& (stats_filters & STATS_FILTER_USAGE)) {
		cache_stats_inactive_usage(ctrl_fd, cache_info, cache_id, outfile);
	}

	if (stats_filters & STATS_FILTER_COUNTERS)
		cache_stats_counters(&cache_stats, outfile, stats_filters);

	return SUCCESS;
}

int cache_stats_cores(int ctrl_fd, const struct kcas_cache_info *cache_info,
		      unsigned int cache_id, unsigned int core_id, int io_class_id,
		      FILE *outfile, unsigned int stats_filters)
{
	struct kcas_core_info core_info;
	struct kcas_get_stats stats;

	if (get_core_info(ctrl_fd, cache_id, core_id, &core_info)) {
		cas_printf(LOG_ERR, "Error while retrieving stats for core %d\n", core_id);
		print_err(core_info.ext_err_code);
		return FAILURE;
	}

	stats.cache_id = cache_id;
	stats.core_id = core_id;
	stats.part_id = OCF_IO_CLASS_INVALID;

	if (ioctl(ctrl_fd, KCAS_IOCTL_GET_STATS, &stats) < 0) {
		cas_printf(LOG_ERR, "Error while retrieving stats for core %d\n", core_id);
		print_err(core_info.ext_err_code);
		return FAILURE;
	}

	cache_stats_core_counters(&core_info, &stats, stats_filters, outfile);

	return SUCCESS;
}

struct stats_printout_ctx
{
	FILE *intermediate;
	FILE *out;
	int type;
	int result;
};
void *stats_printout(void *ctx)
{
	struct stats_printout_ctx *spc = ctx;
	if (stat_format_output(spc->intermediate,
			       spc->out, spc->type)) {
		cas_printf(LOG_ERR, "An error occured during statistics formatting.\n");
		spc->result = FAILURE;
	} else {
		spc->result = SUCCESS;
	}

	return 0;
}

/**
 * @brief print cache statistics in various variants
 *
 * this routine implements -P (--stats) subcommand of casadm.
 * @param cache_id id of a cache, to which stats query pertains
 * @param stats_filters subset of statistics to be displayed. If filters are not
 *        specified STATS_FILTER_DEFAULT are displayd.
 * @param fpath path to an output CSV file to which statistics shall be printed. single "-"
 *        can be passed as a path, to generate CSV to stdout. Henceforth non-NULL value of
 *        fpath is a sign that stats shall be printed in CSV-format, and NULL value will]
 *        cause stats to be printed in pretty tables.
 *
 * @return SUCCESS upon successful printing of statistic. FAILURE if any error happens
 */
int cache_status(unsigned int cache_id, unsigned int core_id, int io_class_id,
		 unsigned int stats_filters, unsigned int output_format)
{
	int ctrl_fd, i;
	int ret = SUCCESS;
	struct kcas_cache_info cache_info;

	ctrl_fd = open_ctrl_device();

	if (ctrl_fd < 0) {
		print_err(KCAS_ERR_SYSTEM);
		return FAILURE;
	}

	/* 1 is writing end, 0 is reading end of a pipe */
	FILE *intermediate_file[2];

	if (create_pipe_pair(intermediate_file)) {
		cas_printf(LOG_ERR,"Failed to create unidirectional pipe.\n");
		close(ctrl_fd);
		return FAILURE;
	}

	/**
	 * printing in statistics will be performed in separate
	 * thread, so that we can interleave statistics collecting
	 * and formatting tables
	 */
	struct stats_printout_ctx printout_ctx;
	printout_ctx.intermediate = intermediate_file[0];
	printout_ctx.out = stdout;
	printout_ctx.type = (OUTPUT_FORMAT_CSV == output_format ? CSV : TEXT);
	pthread_t thread;
	pthread_create(&thread, 0, stats_printout, &printout_ctx);

	memset(&cache_info, 0, sizeof(cache_info));

	cache_info.cache_id = cache_id;

	if (ioctl(ctrl_fd, KCAS_IOCTL_CACHE_INFO, &cache_info) < 0) {
		cas_printf(LOG_ERR, "Cache Id %d not running\n", cache_id);
		ret = FAILURE;
		goto cleanup;
	}

	/* Check if core exists in cache */
	if (core_id != OCF_CORE_ID_INVALID) {
		for (i = 0; i < cache_info.info.core_count; ++i) {
			if (core_id == cache_info.core_id[i]) {
				break;
			}
		}
		if (i == cache_info.info.core_count) {
			cas_printf(LOG_ERR, "No such core device in cache.\n");
			ret = FAILURE;
			goto cleanup;
		}
	}

	if (stats_filters & STATS_FILTER_IOCLASS) {
		if (cache_stats_ioclasses(ctrl_fd, &cache_info, cache_id,
					core_id, io_class_id,
					intermediate_file[1],
					stats_filters)) {
			return FAILURE;
		}
	} else if (core_id == OCF_CORE_ID_INVALID) {
		if (cache_stats(ctrl_fd, &cache_info, cache_id, intermediate_file[1],
					stats_filters)) {
			ret = FAILURE;
			goto cleanup;
		}
	} else {
		if (cache_stats_cores(ctrl_fd, &cache_info, cache_id, core_id,
					io_class_id, intermediate_file[1], stats_filters)) {
			ret = FAILURE;
			goto cleanup;
		}
	}

cleanup:
	close(ctrl_fd);
	fclose(intermediate_file[1]);
	pthread_join(thread, 0);
	if (printout_ctx.result) {
		ret = 1;
	}

	fclose(intermediate_file[0]);

	return ret;
}
