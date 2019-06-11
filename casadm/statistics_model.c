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

#define ALLOWED_NUMBER_OF_ATTEMPTS 10

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
				      float percent, const char * fmt,
				      va_list ap)
{
	fprintf(outfile, "%s\"%s\",", tag, title);
	vfprintf(outfile, fmt, ap);
	fprintf(outfile, ",%.1f", percent);
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
						const char *unit, float percent,
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

static void print_core_conf(const struct kcas_core_info *info,
			    uint32_t cache_size, FILE *outfile,
			    ocf_cache_line_size_t cache_line_size)
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

static void print_core_usage(const struct ocf_stats_core* exp_obj_stats,
			     uint32_t cache_size, uint32_t cache_occupancy,
			     FILE* outfile, ocf_cache_line_size_t line_size)
{
	print_usage_header(outfile);

	print_val_perc_table_row(outfile, "Occupancy", UNIT_BLOCKS,
				percentage(exp_obj_stats->cache_occupancy,
					cache_size),
				"%lu",
				cache_line_in_4k(exp_obj_stats->cache_occupancy,
					line_size));
	print_val_perc_table_row(outfile, "Free", UNIT_BLOCKS,
				percentage(cache_size - cache_occupancy, cache_size),
				"%lu",
				cache_line_in_4k(cache_size - cache_occupancy,
					line_size));
	print_val_perc_table_row(outfile, "Clean", UNIT_BLOCKS,
				percentage(exp_obj_stats->cache_occupancy - exp_obj_stats->dirty,
					exp_obj_stats->cache_occupancy),
				"%lu",
				cache_line_in_4k(exp_obj_stats->cache_occupancy - exp_obj_stats->dirty,
					line_size));
	print_val_perc_table_row(outfile, "Dirty", UNIT_BLOCKS,
				percentage(exp_obj_stats->dirty,
					exp_obj_stats->cache_occupancy),
				"%lu",
				cache_line_in_4k(exp_obj_stats->dirty,
					line_size));
}

static void print_req_section(const struct ocf_stats_req *stats, const char *op_name,
			      FILE *outfile, uint64_t total_reqs)
{
	uint64_t cache_hits;
	float percent;

	cache_hits = stats->total - (stats->full_miss + stats->partial_miss);

	percent = percentage(cache_hits, total_reqs);
	print_val_perc_table_section(outfile, make_row_title(op_name, "hits"),
				     UNIT_REQUESTS, percent, "%lu", cache_hits);

	percent = percentage(stats->partial_miss, total_reqs);
	print_val_perc_table_row(outfile, make_row_title(op_name, "partial misses"),
				 UNIT_REQUESTS, percent, "%lu", stats->partial_miss);

	percent = percentage(stats->full_miss, total_reqs);
	print_val_perc_table_row(outfile, make_row_title(op_name, "full misses"),
				 UNIT_REQUESTS, percent, "%lu", stats->full_miss);

	percent = percentage(stats->total, total_reqs);
	print_val_perc_table_row(outfile, make_row_title(op_name, "total"),
				 UNIT_REQUESTS, percent, "%lu", stats->total);
}

static void print_req_stats(const struct ocf_stats_core *exp_obj_stats,
			    FILE *outfile)
{
	const struct ocf_stats_req *req_stats;
	float percent;
	uint64_t total_reqs = 0, serv_reqs = 0;

	print_table_header(outfile, 4, "Request statistics", "Count",
			   "%", "[Units]");

	total_reqs += exp_obj_stats->read_reqs.total;
	total_reqs += exp_obj_stats->write_reqs.total;

	serv_reqs = total_reqs;

	total_reqs += exp_obj_stats->read_reqs.pass_through;
	total_reqs += exp_obj_stats->write_reqs.pass_through;

	/* Section for reads. */
	req_stats = &exp_obj_stats->read_reqs;
	print_req_section(req_stats, "Read", outfile, total_reqs);

	/* Section for writes. */
	req_stats = &exp_obj_stats->write_reqs;
	print_req_section(req_stats, "Write", outfile, total_reqs);

	/* Pass-Through requests. */
	percent = percentage(exp_obj_stats->read_reqs.pass_through, total_reqs);
	print_val_perc_table_section(outfile, "Pass-Through reads", UNIT_REQUESTS,
				     percent, "%lu",
				     exp_obj_stats->read_reqs.pass_through);

	percent = percentage(exp_obj_stats->write_reqs.pass_through, total_reqs);
	print_val_perc_table_row(outfile, "Pass-Through writes", UNIT_REQUESTS,
				 percent, "%lu",
				 exp_obj_stats->write_reqs.pass_through);

	/* Summary. */
	percent = percentage(serv_reqs, total_reqs);
	print_val_perc_table_row(outfile, "Serviced requests", UNIT_REQUESTS,
				 percent, "%lu", serv_reqs);

	print_val_perc_table_section(outfile, "Total requests", UNIT_REQUESTS,
				     total_reqs ? 100.0f : 0.0f, "%lu",
				     total_reqs);
}

static void print_block_section(const struct ocf_stats_block *stats_4k,
				const char *dev_name, FILE *outfile,
				ocf_cache_line_size_t cache_line_size)
{
	uint64_t total_4k;
	float percent;

	total_4k = stats_4k->read + stats_4k->write;

	percent = percentage(stats_4k->read, total_4k);
	print_val_perc_table_section(outfile,
				     make_row_title("Reads from", dev_name),
				     UNIT_BLOCKS, percent, "%lu", stats_4k->read);

	percent = percentage(stats_4k->write, total_4k);
	print_val_perc_table_row(outfile,
				 make_row_title("Writes to", dev_name),
				 UNIT_BLOCKS, percent, "%lu", stats_4k->write);

	print_val_perc_table_row(outfile,
				 make_row_title("Total to/from", dev_name),
				 UNIT_BLOCKS, total_4k ? 100.0f : 0.0f, "%lu",
				 total_4k);
}

static struct ocf_stats_block convert_block_stats_to_4k(
			const struct ocf_stats_block *stats)
{
	struct ocf_stats_block stats_4k;
	stats_4k.read = bytes_to_4k(stats->read);
	stats_4k.write = bytes_to_4k(stats->write);
	return stats_4k;
}

void print_block_stats(const struct ocf_stats_core *exp_obj_stats,
		       FILE *outfile, ocf_cache_line_size_t cache_line_size)
{
	struct ocf_stats_block cache_volume_stats_4k =
		convert_block_stats_to_4k(&exp_obj_stats->cache_volume);
	struct ocf_stats_block core_volume_stats_4k =
		convert_block_stats_to_4k(&exp_obj_stats->core_volume);
	struct ocf_stats_block core_stats_4k  =
		convert_block_stats_to_4k(&exp_obj_stats->core);

	print_table_header(outfile, 4, "Block statistics", "Count",
				"%", "[Units]");

	print_block_section(&core_volume_stats_4k, "core", outfile,
				cache_line_size);
	print_block_section(&cache_volume_stats_4k, "cache", outfile,
				cache_line_size);
	print_block_section(&core_stats_4k, "exported object", outfile,
				cache_line_size);
}

static void print_error_section(const struct ocf_stats_error *stats,
				const char *section_name, FILE *outfile)
{
	uint64_t total = 0;
	float percent;

	total = stats->read + stats->write;

	percent = percentage(stats->read, total);
	print_val_perc_table_section(outfile,
				     make_row_title(section_name , "read errors"),
				     UNIT_REQUESTS, percent, "%u", stats->read);
	percent = percentage(stats->write, total);
	print_val_perc_table_row(outfile,
				 make_row_title(section_name, "write errors"),
				 UNIT_REQUESTS, percent, "%u", stats->write);
	print_val_perc_table_row(outfile,
				 make_row_title(section_name, "total errors"),
				 UNIT_REQUESTS, total ? 100.0f : 0.0f, "%lu", total);
}

static void print_error_stats_total(const struct ocf_stats_error *cache_stats,
				    const struct ocf_stats_error *core_stats,
				    FILE *outfile)
{
	uint64_t total;

	total = cache_stats->read + cache_stats->write +
		core_stats->read + core_stats->write;

	print_val_perc_table_section(outfile, "Total errors", UNIT_REQUESTS,
				     total ? 100.0f : 0.0f, "%lu", total);
}

static void print_error_stats(const struct ocf_stats_core *exp_obj_stats,
			      FILE *outfile)
{
	print_table_header(outfile, 4, "Error statistics", "Count", "%", "[Units]");

	print_error_section(&exp_obj_stats->cache_errors, "Cache", outfile);
	print_error_section(&exp_obj_stats->core_errors, "Core", outfile);

	print_error_stats_total(&exp_obj_stats->cache_errors,
				&exp_obj_stats->core_errors, outfile);
}

void cache_stats_core_counters(const struct kcas_core_info *info,
			       uint32_t cache_size, uint32_t cache_occupancy,
			       unsigned int stats_filters, FILE *outfile,
			       ocf_cache_line_size_t cache_line_size)
{
	const struct ocf_stats_core *stats = &info->stats;

	begin_record(outfile);
	if (stats_filters & STATS_FILTER_CONF) {
		print_core_conf(info, cache_size, outfile, cache_line_size);
	}

	if (stats_filters & STATS_FILTER_USAGE) {
		print_core_usage(stats, cache_size, cache_occupancy,
				 outfile, cache_line_size);
	}

	if (stats_filters & STATS_FILTER_REQ) {
		print_req_stats(stats, outfile);
	}

	if (stats_filters & STATS_FILTER_BLK) {
		print_block_stats(stats, outfile, cache_line_size);
	}

	if (stats_filters & STATS_FILTER_ERR) {
		print_error_stats(stats, outfile);
	}
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

	if (ioctl(ctrl_fd, KCAS_IOCTL_PARTITION_STATS, io_class_tmp) < 0) {
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

int cache_stats_cores(int ctrl_fd, const struct kcas_cache_info *cache_info,
		      unsigned int cache_id, unsigned int core_id, int io_class_id,
		      FILE *outfile, unsigned int stats_filters)
{
	int i;
	int _core_id;
	uint32_t cache_size;
	ocf_cache_line_size_t cache_line_size;
	struct kcas_core_info core_info;

	for (i = 0; i < cache_info->info.core_count; ++i) {
		/* if user only requested stats pertaining to a specific core,
		   skip all other cores */
		_core_id = cache_info->core_id[i];
		if ((core_id != OCF_CORE_ID_INVALID) && (core_id != _core_id)) {
			continue;
		}
		/* call function to print stats */
		if (get_core_info(ctrl_fd, cache_id, _core_id, &core_info)) {
			cas_printf(LOG_ERR, "Error while retrieving stats for core %d\n", _core_id);
			print_err(core_info.ext_err_code);
			return FAILURE;
		}

		cache_size = cache_info->info.size;
		cache_line_size = cache_info->info.cache_line_size / KiB;

		cache_stats_core_counters(&core_info, cache_size,
				cache_info->info.occupancy,
				stats_filters, outfile, cache_line_size);
	}

	return SUCCESS;
}

int cache_stats_conf(int ctrl_fd, const struct kcas_cache_info *cache_info,
		     unsigned int cache_id, FILE *outfile,
		     unsigned int stats_filters)
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

	print_kv_pair(outfile, "Write Policy", "%s%s",
		      (flush_progress && cache_info->info.cache_mode != ocf_cache_mode_wb)
		      ? "wb->" : "", cache_mode_to_name(cache_info->info.cache_mode));
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

int cache_stats_usage(int ctrl_fd, const struct kcas_cache_info *cache_info,
		      unsigned int cache_id, FILE* outfile)
{
	print_usage_header(outfile);

	print_val_perc_table_row(outfile, "Occupancy", UNIT_BLOCKS,
				percentage(cache_info->info.occupancy,
					cache_info->info.size),
					"%lu",
					cache_line_in_4k(cache_info->info.occupancy,
					cache_info->info.cache_line_size / KiB));

	print_val_perc_table_row(outfile, "Free", UNIT_BLOCKS,
				percentage(cache_info->info.size -
					cache_info->info.occupancy,
					cache_info->info.size),
					"%lu",
					cache_line_in_4k(cache_info->info.size -
					cache_info->info.occupancy,
					cache_info->info.cache_line_size / KiB));

	print_val_perc_table_row(outfile, "Clean", UNIT_BLOCKS,
				percentage(cache_info->info.occupancy -
					cache_info->info.dirty,
					cache_info->info.occupancy),
					"%lu",
					cache_line_in_4k(cache_info->info.occupancy -
					cache_info->info.dirty,
					cache_info->info.cache_line_size / KiB));

	print_val_perc_table_row(outfile, "Dirty", UNIT_BLOCKS,
				percentage(cache_info->info.dirty,
					cache_info->info.occupancy),
					"%lu",
					cache_line_in_4k(cache_info->info.dirty,
					cache_info->info.cache_line_size / KiB));

	return SUCCESS;
}

int cache_stats_inactive_usage(int ctrl_fd, const struct kcas_cache_info *cache_info,
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

	return SUCCESS;
}

int cache_stats_counters(int ctrl_fd, const struct kcas_cache_info *cache_info,
			 unsigned int cache_id, FILE *outfile,
			 unsigned int stats_filters)
{
	int i;
	int _core_id;
	struct ocf_stats_core *stats;
	struct ocf_stats_core total_stats;
	struct kcas_core_info core_info;

	struct ocf_stats_error total_cache_errors, total_core_errors;

	memset(&total_stats, 0, sizeof(total_stats));

	memset(&total_cache_errors, 0, sizeof(total_cache_errors));
	memset(&total_core_errors, 0, sizeof(total_core_errors));

	for (i = 0; i < cache_info->info.core_count; ++i) {
		/* if user only requested stats pertaining to a specific core,
		   skip all other cores */
		_core_id = cache_info->core_id[i];
		/* call function to print stats */
		if (get_core_info(ctrl_fd, cache_id, _core_id, &core_info)) {
			cas_printf(LOG_ERR, "Error while retrieving stats for core %d\n", _core_id);
			print_err(core_info.ext_err_code);
			return FAILURE;
		}

		stats = &core_info.stats;

		/* Convert block stats to 4k before adding them up. This way
		  sum of block stats for cores is consistent with cache
		  stats */
		stats->cache_volume = convert_block_stats_to_4k(&stats->cache_volume);
		stats->core_volume = convert_block_stats_to_4k(&stats->core_volume);
		stats->core = convert_block_stats_to_4k(&stats->core);

		accum_block_stats(&total_stats.cache_volume, &stats->cache_volume);
		accum_block_stats(&total_stats.core_volume, &stats->core_volume);
		accum_block_stats(&total_stats.core, &stats->core);

		accum_req_stats(&total_stats.read_reqs, &stats->read_reqs);
		accum_req_stats(&total_stats.write_reqs, &stats->write_reqs);

		accum_error_stats(&total_cache_errors, &stats->cache_errors);
		accum_error_stats(&total_core_errors, &stats->core_errors);
	}

	/* Totals for requests stats. */
	if (stats_filters & STATS_FILTER_REQ) {
		print_req_stats(&total_stats, outfile);
	}

	/* Totals for blocks stats. */
	if (stats_filters & STATS_FILTER_BLK) {
		print_table_header(outfile, 4, "Block statistics", "Count",
				   "%", "[Units]");
		print_block_section(&total_stats.core_volume, "core(s)", outfile,
					cache_info->info.cache_line_size / KiB);
		print_block_section(&total_stats.cache_volume, "cache", outfile,
					cache_info->info.cache_line_size / KiB);
		print_block_section(&total_stats.core, "exported object(s)", outfile,
					cache_info->info.cache_line_size / KiB);
	}

	/* Totals for error stats. */
	if (stats_filters & STATS_FILTER_ERR) {
		print_table_header(outfile, 4, "Error statistics", "Count", "%",
				   "[Units]");
		print_error_section(&total_cache_errors, "Cache", outfile);
		print_error_section(&total_core_errors, "Core", outfile);

		print_error_stats_total(&total_cache_errors, &total_core_errors,
					outfile);
	}

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

bool _usage_stats_is_valid(struct kcas_cache_info *cmd_info)
{
	return (cmd_info->info.size >= cmd_info->info.occupancy);
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
	int attempt_no = 0;
	struct kcas_cache_info cache_info;

	ctrl_fd = open_ctrl_device();

	if (ctrl_fd < 0) {
		print_err(KCAS_ERR_SYSTEM);
		return FAILURE;
	}

	/**
	 *
	 * Procedure of printing out statistics is as follows:
	 *
	 *
	 * statistics_model.c (retrieve structures from kernel, don't do formatting)
	 *       |
	 *       v
	 *  abstract CSV notation with prefixes (as a temporary file)
	 *       |
	 *       v
	 * statistics_view (parse basic csv notation, generate proper output)
	 *       |
	 *       v
	 *  desired output format
	 *
	 */

	/* 1 is writing end, 0 is reading end of a pipe */
	FILE *intermediate_file[2];

	if (create_pipe_pair(intermediate_file)) {
		cas_printf(LOG_ERR,"Failed to create unidirectional pipe.\n");
		close(ctrl_fd);
		return FAILURE;
	}

	/* Select file to which statistics shall be printed and
	 *
	 */
	FILE *outfile;

	outfile = stdout;

	/**
	 * printing in statistics will be performed in separate
	 * thread, so that we can interleave statistics collecting
	 * and formatting tables
	 */
	struct stats_printout_ctx printout_ctx;
	printout_ctx.intermediate = intermediate_file[0];
	printout_ctx.out = outfile;
	printout_ctx.type = (OUTPUT_FORMAT_CSV == output_format ? CSV : TEXT);
	pthread_t thread;
	pthread_create(&thread, 0, stats_printout, &printout_ctx);

	memset(&cache_info, 0, sizeof(cache_info));

	cache_info.cache_id = cache_id;

	do {
		if (0 != attempt_no) {
			usleep(300 * 1000);
		}

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

		attempt_no++;
	} while (false == _usage_stats_is_valid(&cache_info) &&
		(attempt_no < ALLOWED_NUMBER_OF_ATTEMPTS));

	if (stats_filters & STATS_FILTER_IOCLASS) {
		if (cache_stats_ioclasses(ctrl_fd, &cache_info, cache_id,
					core_id, io_class_id,
					intermediate_file[1],
					stats_filters)) {
			return FAILURE;
		}
	} else if (core_id == OCF_CORE_ID_INVALID) {

		begin_record(intermediate_file[1]);
		if (stats_filters & STATS_FILTER_CONF) {
			if (cache_stats_conf(ctrl_fd, &cache_info,
						cache_id,
						intermediate_file[1],
						stats_filters)) {
				ret = FAILURE;
				goto cleanup;
			}
		}

		if (stats_filters & STATS_FILTER_USAGE) {
			if (cache_stats_usage(ctrl_fd, &cache_info,
						cache_id,
						intermediate_file[1])) {
				ret = FAILURE;
				goto cleanup;
			}
		}
		if ((cache_info.info.state & (1 << ocf_cache_state_incomplete))
				&& stats_filters & STATS_FILTER_USAGE) {
			if (cache_stats_inactive_usage(ctrl_fd, &cache_info,
						cache_id,
						intermediate_file[1])) {
				ret = FAILURE;
				goto cleanup;
			}
		}

		if (stats_filters & STATS_FILTER_COUNTERS) {
			if (cache_stats_counters(ctrl_fd, &cache_info,
						cache_id,
						intermediate_file[1],
						stats_filters)) {
				ret = FAILURE;
				goto cleanup;
			}
		}

	} else {
		/* print per core statistics. this may include:
		 * - core header
		 * - core counters
		 * - core per io class statistics
		 *
		 * depending on which set of statistics is enabled via -f/-d switches.
		 */
		if (cache_stats_cores(ctrl_fd, &cache_info, cache_id,
					core_id, io_class_id,
					intermediate_file[1], stats_filters)) {

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

	if (outfile != stdout) {
		fclose(outfile);
	}
	return ret;
}
