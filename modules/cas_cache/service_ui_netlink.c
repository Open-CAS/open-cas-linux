/*
 * Copyright(c) 2026 Unvertical
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include "cas_cache.h"
#include "service_ui_netlink.h"
#include <cas_netlink.h>

#include <linux/overflow.h>
#include <net/genetlink.h>

static void *cas_nl_vcalloc(size_t n, size_t size)
{
	void *p;
	size_t total;

	if (check_mul_overflow(n, size, &total))
		return NULL;

	p = vmalloc(total);
	if (p)
		memset(p, 0, total);
	return p;
}

static struct genl_family cas_nl_family;

struct cas_nl_core_dump {
	uint16_t id;
	char *path;
	ocf_core_state_t state;
	bool exp_obj_exists;
	struct ocf_core_info info;
	struct ocf_stats_usage usage;
	struct ocf_stats_requests req;
	struct ocf_stats_blocks blocks;
	struct ocf_stats_errors errors;
	uint32_t seq_cutoff_threshold;
	uint32_t seq_cutoff_policy;
	uint32_t seq_detect_promotion_count;
};

struct cas_nl_ioclass_dump {
	uint32_t id;
	struct ocf_io_class_info info;
	struct ocf_stats_usage usage;
	struct ocf_stats_requests req;
	struct ocf_stats_blocks blocks;
};

struct cas_nl_cache_dump {
	uint16_t id;
	char *path;
	struct ocf_cache_info info;
	struct ocf_stats_usage usage;
	struct ocf_stats_requests req;
	struct ocf_stats_blocks blocks;
	struct ocf_stats_errors errors;
	/* Cleaning parameters */
	uint32_t cleaning_policy;
	uint32_t cleaning_alru_wake_up;
	uint32_t cleaning_alru_stale_time;
	uint32_t cleaning_alru_flush_max_buffers;
	uint32_t cleaning_alru_activity_threshold;
	uint32_t cleaning_alru_dirty_ratio_threshold;
	uint32_t cleaning_alru_dirty_ratio_inertia;
	uint32_t cleaning_acp_wake_up;
	uint32_t cleaning_acp_flush_max_buffers;
	/* Promotion parameters */
	uint32_t promotion_policy;
	uint32_t promotion_nhit_insertion_threshold;
	uint32_t promotion_nhit_trigger_threshold;
	/* Sub-records */
	int num_cores;
	struct cas_nl_core_dump *cores;
	int num_io_classes;
	struct cas_nl_ioclass_dump *io_classes;
};

struct cas_nl_dump_ctx {
	int num_caches;
	struct cas_nl_cache_dump *caches;
};

/* ---- Data collection (called under read lock) ---- */

static void cas_nl_collect_core(ocf_cache_t cache, uint16_t core_id,
		ocf_core_t core, struct cas_nl_core_dump *dst)
{
	const struct ocf_volume_uuid *uuid;
	struct cas_priv_top *priv_top;
	ocf_seq_cutoff_policy policy;

	dst->id = core_id;

	uuid = ocf_core_get_uuid(core);
	dst->path = uuid->data ? kstrdup(uuid->data, GFP_KERNEL) : NULL;

	ocf_core_get_info(core, &dst->info);
	dst->state = ocf_core_get_state(core);

	priv_top = cas_get_priv_top(core);
	dst->exp_obj_exists = priv_top->expobj_valid;

	ocf_stats_collect_core(core, &dst->usage, &dst->req,
			&dst->blocks, &dst->errors);

	ocf_mngt_core_get_seq_cutoff_threshold(core,
			&dst->seq_cutoff_threshold);
	if (ocf_mngt_core_get_seq_cutoff_policy(core, &policy) == 0)
		dst->seq_cutoff_policy = policy;
	ocf_mngt_core_get_seq_detect_promotion_count(core,
			&dst->seq_detect_promotion_count);
}

static int cas_nl_collect_cores(ocf_cache_t cache,
		struct cas_nl_cache_dump *dst)
{
	uint32_t i, j;
	ocf_core_t core;

	if (dst->info.core_count == 0) {
		dst->num_cores = 0;
		dst->cores = NULL;
		return 0;
	}

	dst->cores = cas_nl_vcalloc(dst->info.core_count, sizeof(*dst->cores));
	if (!dst->cores)
		return -ENOMEM;

	for (i = 0, j = 0; j < dst->info.core_count && i < OCF_CORE_NUM; i++) {
		if (get_core_by_id(cache, i, &core))
			continue;

		cas_nl_collect_core(cache, i, core, &dst->cores[j]);
		j++;
	}

	dst->num_cores = j;
	return 0;
}

static int cas_nl_collect_io_classes(ocf_cache_t cache,
		struct cas_nl_cache_dump *dst)
{
	uint32_t i, j;
	int result;

	dst->io_classes = cas_nl_vcalloc(OCF_USER_IO_CLASS_MAX,
			sizeof(*dst->io_classes));
	if (!dst->io_classes)
		return -ENOMEM;

	for (i = 0, j = 0; i < OCF_USER_IO_CLASS_MAX; i++) {
		result = ocf_cache_io_class_get_info(cache, i,
				&dst->io_classes[j].info);
		if (result)
			continue;

		dst->io_classes[j].id = i;

		ocf_stats_collect_part_cache(cache, i,
				&dst->io_classes[j].usage,
				&dst->io_classes[j].req,
				&dst->io_classes[j].blocks);
		j++;
	}

	dst->num_io_classes = j;
	return 0;
}

static void cas_nl_collect_cleaning_params(ocf_cache_t cache,
		struct cas_nl_cache_dump *dst)
{
	ocf_cleaning_t type;

	if (ocf_mngt_cache_cleaning_get_policy(cache, &type) == 0)
		dst->cleaning_policy = type;

	ocf_mngt_cache_cleaning_get_param(cache, ocf_cleaning_alru,
			ocf_alru_wake_up_time, &dst->cleaning_alru_wake_up);
	ocf_mngt_cache_cleaning_get_param(cache, ocf_cleaning_alru,
			ocf_alru_stale_buffer_time,
			&dst->cleaning_alru_stale_time);
	ocf_mngt_cache_cleaning_get_param(cache, ocf_cleaning_alru,
			ocf_alru_flush_max_buffers,
			&dst->cleaning_alru_flush_max_buffers);
	ocf_mngt_cache_cleaning_get_param(cache, ocf_cleaning_alru,
			ocf_alru_activity_threshold,
			&dst->cleaning_alru_activity_threshold);
	ocf_mngt_cache_cleaning_get_param(cache, ocf_cleaning_alru,
			ocf_alru_dirty_ratio_threshold,
			&dst->cleaning_alru_dirty_ratio_threshold);
	ocf_mngt_cache_cleaning_get_param(cache, ocf_cleaning_alru,
			ocf_alru_dirty_ratio_inertia,
			&dst->cleaning_alru_dirty_ratio_inertia);
	ocf_mngt_cache_cleaning_get_param(cache, ocf_cleaning_acp,
			ocf_acp_wake_up_time, &dst->cleaning_acp_wake_up);
	ocf_mngt_cache_cleaning_get_param(cache, ocf_cleaning_acp,
			ocf_acp_flush_max_buffers,
			&dst->cleaning_acp_flush_max_buffers);
}

static void cas_nl_collect_promotion_params(ocf_cache_t cache,
		struct cas_nl_cache_dump *dst)
{
	ocf_promotion_t type;

	if (ocf_mngt_cache_promotion_get_policy(cache, &type) == 0)
		dst->promotion_policy = type;

	ocf_mngt_cache_promotion_get_param(cache, ocf_promotion_nhit,
			ocf_nhit_insertion_threshold,
			&dst->promotion_nhit_insertion_threshold);
	ocf_mngt_cache_promotion_get_param(cache, ocf_promotion_nhit,
			ocf_nhit_trigger_threshold,
			&dst->promotion_nhit_trigger_threshold);
}

static int cas_nl_collect_cache(uint16_t cache_id,
		struct cas_nl_cache_dump *dst)
{
	ocf_cache_t cache;
	const struct ocf_volume_uuid *uuid;
	int result;

	result = mngt_get_cache_by_id(cas_ctx, cache_id, &cache);
	if (result)
		return result;

	result = cache_mngt_read_lock_sync(cache);
	if (result)
		goto put;

	dst->id = cache_id;

	result = ocf_cache_get_info(cache, &dst->info);
	if (result)
		goto unlock;

	if (dst->info.attached && !dst->info.standby_detached) {
		uuid = ocf_cache_get_uuid(cache);
		dst->path = uuid && uuid->data ?
				kstrdup(uuid->data, GFP_KERNEL) : NULL;
	}

	ocf_stats_collect_cache(cache, &dst->usage, &dst->req,
			&dst->blocks, &dst->errors);

	cas_nl_collect_cleaning_params(cache, dst);
	cas_nl_collect_promotion_params(cache, dst);

	result = cas_nl_collect_cores(cache, dst);
	if (result)
		goto unlock;

	result = cas_nl_collect_io_classes(cache, dst);

unlock:
	ocf_mngt_cache_read_unlock(cache);
put:
	ocf_mngt_cache_put(cache);
	return result;
}

/* ---- Visitor to collect cache IDs ---- */

struct cas_nl_list_ctx {
	uint16_t *ids;
	int count;
	int capacity;
};

static int cas_nl_list_visitor(ocf_cache_t cache, void *cntx)
{
	struct cas_nl_list_ctx *ctx = cntx;
	uint16_t id;

	if (cache_id_from_name(&id, ocf_cache_get_name(cache)))
		return 0;

	if (ctx->count >= ctx->capacity)
		return 1;

	ctx->ids[ctx->count++] = id;
	return 0;
}

/* ---- Free pre-collected data ---- */

static void cas_nl_free_cache_dump(struct cas_nl_cache_dump *d)
{
	int i;

	kfree(d->path);
	if (d->cores) {
		for (i = 0; i < d->num_cores; i++)
			kfree(d->cores[i].path);
		vfree(d->cores);
	}
	vfree(d->io_classes);
}

static void cas_nl_free_dump_ctx(struct cas_nl_dump_ctx *ctx)
{
	int i;

	if (!ctx)
		return;

	if (ctx->caches) {
		for (i = 0; i < ctx->num_caches; i++)
			cas_nl_free_cache_dump(&ctx->caches[i]);
		vfree(ctx->caches);
	}
	kfree(ctx);
}

/* ---- Netlink message builders ---- */

static int cas_nl_put_stats(struct sk_buff *skb, int attr_id,
		const struct ocf_stats_usage *usage,
		const struct ocf_stats_requests *req,
		const struct ocf_stats_blocks *blocks,
		const struct ocf_stats_errors *errors)
{
	struct nlattr *nest;

	nest = nla_nest_start(skb, attr_id);
	if (!nest)
		return -EMSGSIZE;

	/* Usage */
	if (nla_put_u64_64bit(skb, CAS_NL_STATS_A_USAGE_OCCUPANCY,
			usage->occupancy.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_USAGE_FREE,
			usage->free.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_USAGE_CLEAN,
			usage->clean.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_USAGE_DIRTY,
			usage->dirty.value, CAS_NL_STATS_A_UNSPEC))
		goto nla_failure;

	/* Requests */
	if (nla_put_u64_64bit(skb, CAS_NL_STATS_A_REQ_RD_HITS,
			req->rd_hits.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_REQ_RD_DEFERRED,
			req->rd_deferred.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_REQ_RD_PARTIAL_MISSES,
			req->rd_partial_misses.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_REQ_RD_FULL_MISSES,
			req->rd_full_misses.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_REQ_RD_TOTAL,
			req->rd_total.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_REQ_WR_HITS,
			req->wr_hits.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_REQ_WR_DEFERRED,
			req->wr_deferred.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_REQ_WR_PARTIAL_MISSES,
			req->wr_partial_misses.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_REQ_WR_FULL_MISSES,
			req->wr_full_misses.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_REQ_WR_TOTAL,
			req->wr_total.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_REQ_RD_PT,
			req->rd_pt.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_REQ_WR_PT,
			req->wr_pt.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_REQ_SERVICED,
			req->serviced.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_REQ_PREFETCH_READAHEAD,
			req->prefetch[ocf_pf_readahead].value,
			CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_REQ_CLEANER,
			req->cleaner.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_REQ_TOTAL,
			req->total.value, CAS_NL_STATS_A_UNSPEC))
		goto nla_failure;

	/* Blocks */
	if (nla_put_u64_64bit(skb, CAS_NL_STATS_A_BLOCKS_CORE_VOLUME_RD,
			blocks->core_volume_rd.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_BLOCKS_CORE_VOLUME_WR,
			blocks->core_volume_wr.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_BLOCKS_CORE_VOLUME_TOTAL,
			blocks->core_volume_total.value,
			CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_BLOCKS_CACHE_VOLUME_RD,
			blocks->cache_volume_rd.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_BLOCKS_CACHE_VOLUME_WR,
			blocks->cache_volume_wr.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_BLOCKS_CACHE_VOLUME_TOTAL,
			blocks->cache_volume_total.value,
			CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_BLOCKS_VOLUME_RD,
			blocks->volume_rd.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_BLOCKS_VOLUME_WR,
			blocks->volume_wr.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_BLOCKS_VOLUME_TOTAL,
			blocks->volume_total.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_BLOCKS_PT_RD,
			blocks->pass_through_rd.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_BLOCKS_PT_WR,
			blocks->pass_through_wr.value, CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_BLOCKS_PT_TOTAL,
			blocks->pass_through_total.value,
			CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb,
			CAS_NL_STATS_A_BLOCKS_PREFETCH_CORE_RD_READAHEAD,
			blocks->prefetch_core_rd[ocf_pf_readahead].value,
			CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb,
			CAS_NL_STATS_A_BLOCKS_PREFETCH_CACHE_WR_READAHEAD,
			blocks->prefetch_cache_wr[ocf_pf_readahead].value,
			CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_BLOCKS_CLEANER_CACHE_RD,
			blocks->cleaner_cache_rd.value,
			CAS_NL_STATS_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_STATS_A_BLOCKS_CLEANER_CORE_WR,
			blocks->cleaner_core_wr.value, CAS_NL_STATS_A_UNSPEC))
		goto nla_failure;

	/* Errors (optional - NULL for IO class stats) */
	if (errors &&
	    (nla_put_u64_64bit(skb, CAS_NL_STATS_A_ERRORS_CORE_VOLUME_RD,
			errors->core_volume_rd.value, CAS_NL_STATS_A_UNSPEC) ||
	     nla_put_u64_64bit(skb, CAS_NL_STATS_A_ERRORS_CORE_VOLUME_WR,
			errors->core_volume_wr.value, CAS_NL_STATS_A_UNSPEC) ||
	     nla_put_u64_64bit(skb, CAS_NL_STATS_A_ERRORS_CORE_VOLUME_TOTAL,
			errors->core_volume_total.value,
			CAS_NL_STATS_A_UNSPEC) ||
	     nla_put_u64_64bit(skb, CAS_NL_STATS_A_ERRORS_CACHE_VOLUME_RD,
			errors->cache_volume_rd.value, CAS_NL_STATS_A_UNSPEC) ||
	     nla_put_u64_64bit(skb, CAS_NL_STATS_A_ERRORS_CACHE_VOLUME_WR,
			errors->cache_volume_wr.value, CAS_NL_STATS_A_UNSPEC) ||
	     nla_put_u64_64bit(skb, CAS_NL_STATS_A_ERRORS_CACHE_VOLUME_TOTAL,
			errors->cache_volume_total.value,
			CAS_NL_STATS_A_UNSPEC) ||
	     nla_put_u64_64bit(skb, CAS_NL_STATS_A_ERRORS_TOTAL,
			errors->total.value, CAS_NL_STATS_A_UNSPEC)))
		goto nla_failure;

	nla_nest_end(skb, nest);
	return 0;

nla_failure:
	nla_nest_cancel(skb, nest);
	return -EMSGSIZE;
}

static int cas_nl_put_cache_msg(struct sk_buff *skb, u32 portid, u32 seq,
		const struct cas_nl_cache_dump *c)
{
	void *hdr;
	struct nlattr *cache_nest, *nest;

	hdr = genlmsg_put(skb, portid, seq, &cas_nl_family, NLM_F_MULTI,
			CAS_NL_CMD_DUMP);
	if (!hdr)
		return -EMSGSIZE;

	cache_nest = nla_nest_start(skb, CAS_NL_A_CACHE);
	if (!cache_nest)
		goto nla_failure;

	/* Identification */
	if (nla_put_u16(skb, CAS_NL_CACHE_A_ID, c->id))
		goto nla_failure;
	if (c->path && nla_put_string(skb, CAS_NL_CACHE_A_PATH, c->path))
		goto nla_failure;

	/* Configuration */
	if (nla_put_u8(skb, CAS_NL_CACHE_A_STATE, c->info.state) ||
	    nla_put_u8(skb, CAS_NL_CACHE_A_MODE, c->info.cache_mode) ||
	    nla_put_u32(skb, CAS_NL_CACHE_A_LINE_SIZE, c->info.cache_line_size))
		goto nla_failure;

	if (c->info.attached &&
	    nla_put_flag(skb, CAS_NL_CACHE_A_ATTACHED))
		goto nla_failure;
	if (c->info.standby_detached &&
	    nla_put_flag(skb, CAS_NL_CACHE_A_STANDBY_DETACHED))
		goto nla_failure;

	/* Size and occupancy */
	if (nla_put_u32(skb, CAS_NL_CACHE_A_SIZE, c->info.size) ||
	    nla_put_u32(skb, CAS_NL_CACHE_A_OCCUPANCY, c->info.occupancy) ||
	    nla_put_u32(skb, CAS_NL_CACHE_A_DIRTY, c->info.dirty) ||
	    nla_put_u64_64bit(skb, CAS_NL_CACHE_A_DIRTY_FOR,
			c->info.dirty_for, CAS_NL_CACHE_A_UNSPEC) ||
	    nla_put_u32(skb, CAS_NL_CACHE_A_DIRTY_INITIAL,
			c->info.dirty_initial) ||
	    nla_put_u32(skb, CAS_NL_CACHE_A_FLUSHED, c->info.flushed) ||
	    nla_put_u32(skb, CAS_NL_CACHE_A_CORE_COUNT, c->info.core_count))
		goto nla_failure;

	/* Metadata */
	if (nla_put_u64_64bit(skb, CAS_NL_CACHE_A_METADATA_FOOTPRINT,
			c->info.metadata_footprint, CAS_NL_CACHE_A_UNSPEC) ||
	    nla_put_u32(skb, CAS_NL_CACHE_A_METADATA_END_OFFSET,
			c->info.metadata_end_offset))
		goto nla_failure;

	/* Fallback pass-through */
	if (nla_put_u32(skb, CAS_NL_CACHE_A_FALLBACK_PT_ERRORS,
			c->info.fallback_pt.error_counter) ||
	    nla_put_u8(skb, CAS_NL_CACHE_A_FALLBACK_PT_STATUS,
			c->info.fallback_pt.status))
		goto nla_failure;

	/* Inactive core stats */
	if (nla_put_u64_64bit(skb, CAS_NL_CACHE_A_INACTIVE_OCCUPANCY,
			c->info.inactive.occupancy.value,
			CAS_NL_CACHE_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_CACHE_A_INACTIVE_CLEAN,
			c->info.inactive.clean.value, CAS_NL_CACHE_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_CACHE_A_INACTIVE_DIRTY,
			c->info.inactive.dirty.value, CAS_NL_CACHE_A_UNSPEC))
		goto nla_failure;

	/* Cleaning parameters */
	nest = nla_nest_start(skb, CAS_NL_CACHE_A_CLEANING_PARAMS);
	if (!nest)
		goto nla_failure;
	if (nla_put_u32(skb, CAS_NL_CLEANING_A_POLICY, c->cleaning_policy) ||
	    nla_put_u32(skb, CAS_NL_CLEANING_A_ALRU_WAKE_UP,
			c->cleaning_alru_wake_up) ||
	    nla_put_u32(skb, CAS_NL_CLEANING_A_ALRU_STALE_TIME,
			c->cleaning_alru_stale_time) ||
	    nla_put_u32(skb, CAS_NL_CLEANING_A_ALRU_FLUSH_MAX_BUFFERS,
			c->cleaning_alru_flush_max_buffers) ||
	    nla_put_u32(skb, CAS_NL_CLEANING_A_ALRU_ACTIVITY_THRESHOLD,
			c->cleaning_alru_activity_threshold) ||
	    nla_put_u32(skb, CAS_NL_CLEANING_A_ALRU_DIRTY_RATIO_THRESHOLD,
			c->cleaning_alru_dirty_ratio_threshold) ||
	    nla_put_u32(skb, CAS_NL_CLEANING_A_ALRU_DIRTY_RATIO_INERTIA,
			c->cleaning_alru_dirty_ratio_inertia) ||
	    nla_put_u32(skb, CAS_NL_CLEANING_A_ACP_WAKE_UP,
			c->cleaning_acp_wake_up) ||
	    nla_put_u32(skb, CAS_NL_CLEANING_A_ACP_FLUSH_MAX_BUFFERS,
			c->cleaning_acp_flush_max_buffers)) {
		nla_nest_cancel(skb, nest);
		goto nla_failure;
	}
	nla_nest_end(skb, nest);

	/* Promotion parameters */
	nest = nla_nest_start(skb, CAS_NL_CACHE_A_PROMOTION_PARAMS);
	if (!nest)
		goto nla_failure;
	if (nla_put_u32(skb, CAS_NL_PROMOTION_A_POLICY,
			c->promotion_policy) ||
	    nla_put_u32(skb, CAS_NL_PROMOTION_A_NHIT_INSERTION_THRESHOLD,
			c->promotion_nhit_insertion_threshold) ||
	    nla_put_u32(skb, CAS_NL_PROMOTION_A_NHIT_TRIGGER_THRESHOLD,
			c->promotion_nhit_trigger_threshold)) {
		nla_nest_cancel(skb, nest);
		goto nla_failure;
	}
	nla_nest_end(skb, nest);

	/* Statistics */
	if (cas_nl_put_stats(skb, CAS_NL_CACHE_A_STATS,
			&c->usage, &c->req, &c->blocks, &c->errors))
		goto nla_failure;

	nla_nest_end(skb, cache_nest);
	genlmsg_end(skb, hdr);
	return 0;

nla_failure:
	genlmsg_cancel(skb, hdr);
	return -EMSGSIZE;
}

static int cas_nl_put_core_msg(struct sk_buff *skb, u32 portid, u32 seq,
		uint16_t cache_id, const struct cas_nl_core_dump *c)
{
	void *hdr;
	struct nlattr *core_nest;

	hdr = genlmsg_put(skb, portid, seq, &cas_nl_family, NLM_F_MULTI,
			CAS_NL_CMD_DUMP);
	if (!hdr)
		return -EMSGSIZE;

	core_nest = nla_nest_start(skb, CAS_NL_A_CORE);
	if (!core_nest)
		goto nla_failure;

	/* Identification */
	if (nla_put_u16(skb, CAS_NL_CORE_A_CACHE_ID, cache_id) ||
	    nla_put_u16(skb, CAS_NL_CORE_A_ID, c->id))
		goto nla_failure;
	if (c->path && nla_put_string(skb, CAS_NL_CORE_A_PATH, c->path))
		goto nla_failure;

	/* State */
	if (nla_put_u8(skb, CAS_NL_CORE_A_STATE, c->state))
		goto nla_failure;
	if (c->exp_obj_exists &&
	    nla_put_flag(skb, CAS_NL_CORE_A_EXP_OBJ_EXISTS))
		goto nla_failure;

	/* Size */
	if (nla_put_u64_64bit(skb, CAS_NL_CORE_A_SIZE,
			c->info.core_size, CAS_NL_CORE_A_UNSPEC) ||
	    nla_put_u64_64bit(skb, CAS_NL_CORE_A_SIZE_BYTES,
			c->info.core_size_bytes, CAS_NL_CORE_A_UNSPEC))
		goto nla_failure;

	/* Dirty data */
	if (nla_put_u32(skb, CAS_NL_CORE_A_DIRTY, c->info.dirty) ||
	    nla_put_u64_64bit(skb, CAS_NL_CORE_A_DIRTY_FOR,
			c->info.dirty_for, CAS_NL_CORE_A_UNSPEC) ||
	    nla_put_u32(skb, CAS_NL_CORE_A_FLUSHED, c->info.flushed))
		goto nla_failure;

	/* Sequential cutoff */
	if (nla_put_u32(skb, CAS_NL_CORE_A_SEQ_CUTOFF_THRESHOLD,
			c->seq_cutoff_threshold) ||
	    nla_put_u8(skb, CAS_NL_CORE_A_SEQ_CUTOFF_POLICY,
			c->seq_cutoff_policy) ||
	    nla_put_u32(skb, CAS_NL_CORE_A_SEQ_CUTOFF_PROMO_COUNT,
			c->seq_detect_promotion_count))
		goto nla_failure;

	/* Statistics */
	if (cas_nl_put_stats(skb, CAS_NL_CORE_A_STATS,
			&c->usage, &c->req, &c->blocks, &c->errors))
		goto nla_failure;

	nla_nest_end(skb, core_nest);
	genlmsg_end(skb, hdr);
	return 0;

nla_failure:
	genlmsg_cancel(skb, hdr);
	return -EMSGSIZE;
}

static int cas_nl_put_ioclass_msg(struct sk_buff *skb, u32 portid, u32 seq,
		uint16_t cache_id, const struct cas_nl_ioclass_dump *c)
{
	void *hdr;
	struct nlattr *ioc_nest;

	hdr = genlmsg_put(skb, portid, seq, &cas_nl_family, NLM_F_MULTI,
			CAS_NL_CMD_DUMP);
	if (!hdr)
		return -EMSGSIZE;

	ioc_nest = nla_nest_start(skb, CAS_NL_A_IO_CLASS);
	if (!ioc_nest)
		goto nla_failure;

	/* Identification */
	if (nla_put_u16(skb, CAS_NL_IOCLASS_A_CACHE_ID, cache_id) ||
	    nla_put_u32(skb, CAS_NL_IOCLASS_A_ID, c->id))
		goto nla_failure;
	if (c->info.name[0] &&
	    nla_put_string(skb, CAS_NL_IOCLASS_A_NAME, c->info.name))
		goto nla_failure;

	/* Configuration */
	if (nla_put_u8(skb, CAS_NL_IOCLASS_A_CACHE_MODE, c->info.cache_mode) ||
	    nla_put_u16(skb, CAS_NL_IOCLASS_A_PRIORITY,
			(uint16_t)c->info.priority) ||
	    nla_put_u32(skb, CAS_NL_IOCLASS_A_CURR_SIZE, c->info.curr_size) ||
	    nla_put_u32(skb, CAS_NL_IOCLASS_A_MIN_SIZE, c->info.min_size) ||
	    nla_put_u32(skb, CAS_NL_IOCLASS_A_MAX_SIZE, c->info.max_size) ||
	    nla_put_u8(skb, CAS_NL_IOCLASS_A_CLEANING_POLICY,
			c->info.cleaning_policy_type))
		goto nla_failure;

	/* Statistics (no errors for IO class) */
	if (cas_nl_put_stats(skb, CAS_NL_IOCLASS_A_STATS,
			&c->usage, &c->req, &c->blocks, NULL))
		goto nla_failure;

	nla_nest_end(skb, ioc_nest);
	genlmsg_end(skb, hdr);
	return 0;

nla_failure:
	genlmsg_cancel(skb, hdr);
	return -EMSGSIZE;
}

/* ---- GENL dump callbacks ---- */

static int cas_nl_dump_start(struct netlink_callback *cb)
{
	struct cas_nl_dump_ctx *ctx;
	struct cas_nl_list_ctx list_ctx;
	int i, j, result;

	ctx = kzalloc(sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;

	/* Collect cache IDs — allocate for the max possible to avoid a race
	 * between a separate get_count call and the visit call.
	 */
	list_ctx.ids = kmalloc_array(OCF_CACHE_ID_MAX, sizeof(uint16_t),
			GFP_KERNEL);
	if (!list_ctx.ids) {
		kfree(ctx);
		return -ENOMEM;
	}
	list_ctx.count = 0;
	list_ctx.capacity = OCF_CACHE_ID_MAX;

	ocf_mngt_cache_visit(cas_ctx, cas_nl_list_visitor, &list_ctx);

	if (list_ctx.count == 0) {
		kfree(list_ctx.ids);
		cb->args[3] = (long)ctx;
		return 0;
	}

	/* Pre-collect data for all caches */
	ctx->caches = cas_nl_vcalloc(list_ctx.count, sizeof(*ctx->caches));
	if (!ctx->caches) {
		kfree(list_ctx.ids);
		kfree(ctx);
		return -ENOMEM;
	}

	for (i = 0, j = 0; i < list_ctx.count; i++) {
		result = cas_nl_collect_cache(list_ctx.ids[i],
				&ctx->caches[j]);
		if (result == 0)
			j++;
		/* Skip caches that disappeared between list and collect */
	}

	ctx->num_caches = j;
	kfree(list_ctx.ids);
	cb->args[3] = (long)ctx;

	return 0;
}

/*
 * Dump iteration state stored in cb->args:
 *   args[0] = cache index
 *   args[1] = phase: 0=cache record, 1=core records, 2=ioclass records
 *   args[2] = index within current phase
 */
static int cas_nl_dump(struct sk_buff *skb, struct netlink_callback *cb)
{
	struct cas_nl_dump_ctx *ctx = (void *)cb->args[3];
	int cache_idx = cb->args[0];
	int phase = cb->args[1];
	int sub_idx = cb->args[2];
	u32 portid = NETLINK_CB(cb->skb).portid;
	u32 seq = cb->nlh->nlmsg_seq;
	struct cas_nl_cache_dump *cache;
	int result;

	while (cache_idx < ctx->num_caches) {
		cache = &ctx->caches[cache_idx];

		if (phase == 0) {
			result = cas_nl_put_cache_msg(skb, portid, seq, cache);
			if (result)
				goto out;
			phase = 1;
			sub_idx = 0;
		}

		if (phase == 1) {
			while (sub_idx < cache->num_cores) {
				result = cas_nl_put_core_msg(skb, portid, seq,
						cache->id,
						&cache->cores[sub_idx]);
				if (result)
					goto out;
				sub_idx++;
			}
			phase = 2;
			sub_idx = 0;
		}

		if (phase == 2) {
			while (sub_idx < cache->num_io_classes) {
				result = cas_nl_put_ioclass_msg(skb, portid,
						seq, cache->id,
						&cache->io_classes[sub_idx]);
				if (result)
					goto out;
				sub_idx++;
			}
		}

		/* Move to next cache */
		cache_idx++;
		phase = 0;
		sub_idx = 0;
	}

out:
	cb->args[0] = cache_idx;
	cb->args[1] = phase;
	cb->args[2] = sub_idx;

	return skb->len;
}

static int cas_nl_dump_done(struct netlink_callback *cb)
{
	cas_nl_free_dump_ctx((void *)cb->args[3]);

	return 0;
}

/* ---- GENL family definition ---- */

static const struct nla_policy cas_nl_policy[CAS_NL_A_MAX + 1] = {
	[CAS_NL_A_CACHE]	= { .type = NLA_NESTED },
	[CAS_NL_A_CORE]	= { .type = NLA_NESTED },
	[CAS_NL_A_IO_CLASS]	= { .type = NLA_NESTED },
};

static const struct genl_split_ops cas_nl_ops[] = {
	{
		.cmd		= CAS_NL_CMD_DUMP,
		.start		= cas_nl_dump_start,
		.dumpit		= cas_nl_dump,
		.done		= cas_nl_dump_done,
		.flags		= GENL_CMD_CAP_DUMP,
	},
};

static struct genl_family cas_nl_family = {
	.name		= CAS_NL_FAMILY_NAME,
	.version	= CAS_NL_FAMILY_VERSION,
	.maxattr	= CAS_NL_A_MAX,
	.policy		= cas_nl_policy,
	.split_ops	= cas_nl_ops,
	.n_split_ops	= ARRAY_SIZE(cas_nl_ops),
	.module		= THIS_MODULE,
};

int cas_nl_init(void)
{
	return genl_register_family(&cas_nl_family);
}

void cas_nl_deinit(void)
{
	genl_unregister_family(&cas_nl_family);
}
