/*
 * Copyright(c) 2026 Unvertical
 * SPDX-License-Identifier: BSD-3-Clause
 *
 * Userspace client library for the Open CAS Generic Netlink interface.
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <sys/socket.h>
#include <linux/netlink.h>
#include <linux/genetlink.h>

#include <cas_netlink.h>
#include "libopencas.h"

/* NLA helpers */

static struct nlattr *nla_next(struct nlattr *nla, int *remaining)
{
	int len = NLA_ALIGN(nla->nla_len);

	*remaining -= len;
	return (struct nlattr *)((char *)nla + len);
}

static int nla_ok(struct nlattr *nla, int remaining)
{
	return remaining >= (int)sizeof(struct nlattr) &&
	       nla->nla_len >= sizeof(struct nlattr) &&
	       nla->nla_len <= remaining;
}

static void *nla_data(struct nlattr *nla)
{
	return (char *)nla + NLA_HDRLEN;
}

static int nla_len(struct nlattr *nla)
{
	return nla->nla_len - NLA_HDRLEN;
}

static uint8_t nla_get_u8(struct nlattr *nla)
{
	return *(uint8_t *)nla_data(nla);
}

static uint16_t nla_get_u16(struct nlattr *nla)
{
	return *(uint16_t *)nla_data(nla);
}

static uint32_t nla_get_u32(struct nlattr *nla)
{
	return *(uint32_t *)nla_data(nla);
}

static uint64_t nla_get_u64(struct nlattr *nla)
{
	uint64_t val;

	memcpy(&val, nla_data(nla), sizeof(val));
	return val;
}

static void nla_get_str(struct nlattr *nla, char *dst, size_t dst_size)
{
	int len = nla_len(nla);

	if (len <= 0) {
		dst[0] = '\0';
		return;
	}
	if ((size_t)len >= dst_size)
		len = dst_size - 1;
	memcpy(dst, nla_data(nla), len);
	dst[len] = '\0';
}

#define nla_for_each(pos, remaining) \
	for (; nla_ok(pos, remaining); pos = nla_next(pos, &(remaining)))

/* Netlink socket helpers */

#define NL_BUF_SIZE	65536

struct nl_ctx {
	int fd;
	uint32_t seq;
	uint32_t pid;
	uint16_t family_id;
};

static int nl_open(struct nl_ctx *ctx)
{
	struct sockaddr_nl addr = {
		.nl_family = AF_NETLINK,
	};
	socklen_t addrlen = sizeof(addr);

	ctx->fd = socket(AF_NETLINK, SOCK_DGRAM, NETLINK_GENERIC);
	if (ctx->fd < 0)
		return -errno;

	if (bind(ctx->fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
		close(ctx->fd);
		return -errno;
	}

	if (getsockname(ctx->fd, (struct sockaddr *)&addr,
			&addrlen) < 0) {
		close(ctx->fd);
		return -errno;
	}

	ctx->pid = addr.nl_pid;
	ctx->seq = 1;
	return 0;
}

static void nl_close(struct nl_ctx *ctx)
{
	close(ctx->fd);
}

static int nl_send(struct nl_ctx *ctx, struct nlmsghdr *nlh)
{
	struct sockaddr_nl addr = {
		.nl_family = AF_NETLINK,
	};
	ssize_t ret;

	nlh->nlmsg_pid = ctx->pid;
	nlh->nlmsg_seq = ctx->seq++;

	ret = sendto(ctx->fd, nlh, nlh->nlmsg_len, 0,
		     (struct sockaddr *)&addr, sizeof(addr));
	if (ret < 0)
		return -errno;
	return 0;
}

static int nl_resolve_family(struct nl_ctx *ctx, const char *name)
{
	char buf[4096];
	struct nlmsghdr *nlh;
	struct genlmsghdr *genl;
	struct nlattr *nla;
	int len, attrlen;

	memset(buf, 0, sizeof(buf));
	nlh = (struct nlmsghdr *)buf;
	nlh->nlmsg_len = NLMSG_LENGTH(GENL_HDRLEN);
	nlh->nlmsg_type = GENL_ID_CTRL;
	nlh->nlmsg_flags = NLM_F_REQUEST;

	genl = NLMSG_DATA(nlh);
	genl->cmd = CTRL_CMD_GETFAMILY;
	genl->version = 1;

	nla = (struct nlattr *)((char *)buf + nlh->nlmsg_len);
	nla->nla_type = CTRL_ATTR_FAMILY_NAME;
	nla->nla_len = NLA_HDRLEN + strlen(name) + 1;
	memcpy(nla_data(nla), name, strlen(name) + 1);
	nlh->nlmsg_len += NLA_ALIGN(nla->nla_len);

	if (nl_send(ctx, nlh))
		return -1;

	len = recv(ctx->fd, buf, sizeof(buf), 0);
	if (len < 0)
		return -errno;

	nlh = (struct nlmsghdr *)buf;
	if (nlh->nlmsg_type == NLMSG_ERROR) {
		struct nlmsgerr *err = NLMSG_DATA(nlh);

		return err->error;
	}

	genl = NLMSG_DATA(nlh);
	nla = (struct nlattr *)((char *)genl + GENL_HDRLEN);
	attrlen = nlh->nlmsg_len - NLMSG_LENGTH(GENL_HDRLEN);

	nla_for_each(nla, attrlen) {
		if (nla->nla_type == CTRL_ATTR_FAMILY_ID) {
			ctx->family_id = nla_get_u16(nla);
			return 0;
		}
	}

	return -ENOENT;
}

static int nl_send_dump_request(struct nl_ctx *ctx)
{
	char buf[256];
	struct nlmsghdr *nlh;
	struct genlmsghdr *genl;

	memset(buf, 0, sizeof(buf));
	nlh = (struct nlmsghdr *)buf;
	nlh->nlmsg_len = NLMSG_LENGTH(GENL_HDRLEN);
	nlh->nlmsg_type = ctx->family_id;
	nlh->nlmsg_flags = NLM_F_REQUEST | NLM_F_DUMP;

	genl = NLMSG_DATA(nlh);
	genl->cmd = CAS_NL_CMD_DUMP;
	genl->version = CAS_NL_FAMILY_VERSION;

	return nl_send(ctx, nlh);
}

/* Record parsers */

static void parse_stats(struct nlattr *nest, struct cas_nl_stats *s)
{
	struct nlattr *nla = nla_data(nest);
	int remaining = nla_len(nest);

	nla_for_each(nla, remaining) {
		int type = nla->nla_type & NLA_TYPE_MASK;

		switch (type) {
		case CAS_NL_STATS_A_USAGE_OCCUPANCY:
			s->usage_occupancy = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_USAGE_FREE:
			s->usage_free = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_USAGE_CLEAN:
			s->usage_clean = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_USAGE_DIRTY:
			s->usage_dirty = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_REQ_RD_HITS:
			s->req_rd_hits = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_REQ_RD_DEFERRED:
			s->req_rd_deferred = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_REQ_RD_PARTIAL_MISSES:
			s->req_rd_partial_misses = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_REQ_RD_FULL_MISSES:
			s->req_rd_full_misses = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_REQ_RD_TOTAL:
			s->req_rd_total = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_REQ_WR_HITS:
			s->req_wr_hits = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_REQ_WR_DEFERRED:
			s->req_wr_deferred = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_REQ_WR_PARTIAL_MISSES:
			s->req_wr_partial_misses = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_REQ_WR_FULL_MISSES:
			s->req_wr_full_misses = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_REQ_WR_TOTAL:
			s->req_wr_total = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_REQ_RD_PT:
			s->req_rd_pt = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_REQ_WR_PT:
			s->req_wr_pt = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_REQ_SERVICED:
			s->req_serviced = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_REQ_PREFETCH_READAHEAD:
			s->req_prefetch_readahead = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_REQ_CLEANER:
			s->req_cleaner = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_REQ_TOTAL:
			s->req_total = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_BLOCKS_CORE_VOLUME_RD:
			s->blocks_core_rd = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_BLOCKS_CORE_VOLUME_WR:
			s->blocks_core_wr = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_BLOCKS_CORE_VOLUME_TOTAL:
			s->blocks_core_total = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_BLOCKS_CACHE_VOLUME_RD:
			s->blocks_cache_rd = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_BLOCKS_CACHE_VOLUME_WR:
			s->blocks_cache_wr = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_BLOCKS_CACHE_VOLUME_TOTAL:
			s->blocks_cache_total = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_BLOCKS_VOLUME_RD:
			s->blocks_volume_rd = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_BLOCKS_VOLUME_WR:
			s->blocks_volume_wr = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_BLOCKS_VOLUME_TOTAL:
			s->blocks_volume_total = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_BLOCKS_PT_RD:
			s->blocks_pt_rd = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_BLOCKS_PT_WR:
			s->blocks_pt_wr = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_BLOCKS_PT_TOTAL:
			s->blocks_pt_total = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_BLOCKS_PREFETCH_CORE_RD_READAHEAD:
			s->blocks_prefetch_core_rd_readahead =
					nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_BLOCKS_PREFETCH_CACHE_WR_READAHEAD:
			s->blocks_prefetch_cache_wr_readahead =
					nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_BLOCKS_CLEANER_CACHE_RD:
			s->blocks_cleaner_cache_rd = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_BLOCKS_CLEANER_CORE_WR:
			s->blocks_cleaner_core_wr = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_ERRORS_CORE_VOLUME_RD:
			s->errors_core_rd = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_ERRORS_CORE_VOLUME_WR:
			s->errors_core_wr = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_ERRORS_CORE_VOLUME_TOTAL:
			s->errors_core_total = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_ERRORS_CACHE_VOLUME_RD:
			s->errors_cache_rd = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_ERRORS_CACHE_VOLUME_WR:
			s->errors_cache_wr = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_ERRORS_CACHE_VOLUME_TOTAL:
			s->errors_cache_total = nla_get_u64(nla);
			break;
		case CAS_NL_STATS_A_ERRORS_TOTAL:
			s->errors_total = nla_get_u64(nla);
			break;
		}
	}
}

static void parse_cleaning_params(struct nlattr *nest,
				  struct cas_nl_cleaning_params *p)
{
	struct nlattr *nla = nla_data(nest);
	int remaining = nla_len(nest);

	nla_for_each(nla, remaining) {
		int type = nla->nla_type & NLA_TYPE_MASK;

		switch (type) {
		case CAS_NL_CLEANING_A_POLICY:
			p->policy = nla_get_u32(nla);
			break;
		case CAS_NL_CLEANING_A_ALRU_WAKE_UP:
			p->alru_wake_up = nla_get_u32(nla);
			break;
		case CAS_NL_CLEANING_A_ALRU_STALE_TIME:
			p->alru_stale_time = nla_get_u32(nla);
			break;
		case CAS_NL_CLEANING_A_ALRU_FLUSH_MAX_BUFFERS:
			p->alru_flush_max_buffers = nla_get_u32(nla);
			break;
		case CAS_NL_CLEANING_A_ALRU_ACTIVITY_THRESHOLD:
			p->alru_activity_threshold = nla_get_u32(nla);
			break;
		case CAS_NL_CLEANING_A_ALRU_DIRTY_RATIO_THRESHOLD:
			p->alru_dirty_ratio_threshold = nla_get_u32(nla);
			break;
		case CAS_NL_CLEANING_A_ALRU_DIRTY_RATIO_INERTIA:
			p->alru_dirty_ratio_inertia = nla_get_u32(nla);
			break;
		case CAS_NL_CLEANING_A_ACP_WAKE_UP:
			p->acp_wake_up = nla_get_u32(nla);
			break;
		case CAS_NL_CLEANING_A_ACP_FLUSH_MAX_BUFFERS:
			p->acp_flush_max_buffers = nla_get_u32(nla);
			break;
		}
	}
}

static void parse_promotion_params(struct nlattr *nest,
				   struct cas_nl_promotion_params *p)
{
	struct nlattr *nla = nla_data(nest);
	int remaining = nla_len(nest);

	nla_for_each(nla, remaining) {
		int type = nla->nla_type & NLA_TYPE_MASK;

		switch (type) {
		case CAS_NL_PROMOTION_A_POLICY:
			p->policy = nla_get_u32(nla);
			break;
		case CAS_NL_PROMOTION_A_NHIT_INSERTION_THRESHOLD:
			p->nhit_insertion_threshold = nla_get_u32(nla);
			break;
		case CAS_NL_PROMOTION_A_NHIT_TRIGGER_THRESHOLD:
			p->nhit_trigger_threshold = nla_get_u32(nla);
			break;
		}
	}
}

static void parse_cache_record(struct nlattr *nest,
			       struct cas_nl_cache *c)
{
	struct nlattr *nla = nla_data(nest);
	int remaining = nla_len(nest);

	memset(c, 0, sizeof(*c));

	nla_for_each(nla, remaining) {
		int type = nla->nla_type & NLA_TYPE_MASK;

		switch (type) {
		case CAS_NL_CACHE_A_ID:
			c->id = nla_get_u16(nla);
			break;
		case CAS_NL_CACHE_A_PATH:
			nla_get_str(nla, c->path, sizeof(c->path));
			break;
		case CAS_NL_CACHE_A_STATE:
			c->state = nla_get_u8(nla);
			break;
		case CAS_NL_CACHE_A_MODE:
			c->mode = nla_get_u8(nla);
			break;
		case CAS_NL_CACHE_A_LINE_SIZE:
			c->line_size = nla_get_u32(nla);
			break;
		case CAS_NL_CACHE_A_ATTACHED:
			c->attached = true;
			break;
		case CAS_NL_CACHE_A_STANDBY_DETACHED:
			c->standby_detached = true;
			break;
		case CAS_NL_CACHE_A_SIZE:
			c->size = nla_get_u32(nla);
			break;
		case CAS_NL_CACHE_A_OCCUPANCY:
			c->occupancy = nla_get_u32(nla);
			break;
		case CAS_NL_CACHE_A_DIRTY:
			c->dirty = nla_get_u32(nla);
			break;
		case CAS_NL_CACHE_A_DIRTY_FOR:
			c->dirty_for = nla_get_u64(nla);
			break;
		case CAS_NL_CACHE_A_DIRTY_INITIAL:
			c->dirty_initial = nla_get_u32(nla);
			break;
		case CAS_NL_CACHE_A_FLUSHED:
			c->flushed = nla_get_u32(nla);
			break;
		case CAS_NL_CACHE_A_CORE_COUNT:
			c->core_count = nla_get_u32(nla);
			break;
		case CAS_NL_CACHE_A_METADATA_FOOTPRINT:
			c->metadata_footprint = nla_get_u64(nla);
			break;
		case CAS_NL_CACHE_A_METADATA_END_OFFSET:
			c->metadata_end_offset = nla_get_u32(nla);
			break;
		case CAS_NL_CACHE_A_FALLBACK_PT_ERRORS:
			c->fallback_pt_errors = nla_get_u32(nla);
			break;
		case CAS_NL_CACHE_A_FALLBACK_PT_STATUS:
			c->fallback_pt_status = nla_get_u8(nla);
			break;
		case CAS_NL_CACHE_A_INACTIVE_OCCUPANCY:
			c->inactive_occupancy = nla_get_u64(nla);
			break;
		case CAS_NL_CACHE_A_INACTIVE_CLEAN:
			c->inactive_clean = nla_get_u64(nla);
			break;
		case CAS_NL_CACHE_A_INACTIVE_DIRTY:
			c->inactive_dirty = nla_get_u64(nla);
			break;
		case CAS_NL_CACHE_A_CLEANING_PARAMS:
			parse_cleaning_params(nla, &c->cleaning);
			break;
		case CAS_NL_CACHE_A_PROMOTION_PARAMS:
			parse_promotion_params(nla, &c->promotion);
			break;
		case CAS_NL_CACHE_A_STATS:
			parse_stats(nla, &c->stats);
			break;
		}
	}
}

static void parse_core_record(struct nlattr *nest,
			      struct cas_nl_core *c)
{
	struct nlattr *nla = nla_data(nest);
	int remaining = nla_len(nest);

	memset(c, 0, sizeof(*c));

	nla_for_each(nla, remaining) {
		int type = nla->nla_type & NLA_TYPE_MASK;

		switch (type) {
		case CAS_NL_CORE_A_CACHE_ID:
			c->cache_id = nla_get_u16(nla);
			break;
		case CAS_NL_CORE_A_ID:
			c->id = nla_get_u16(nla);
			break;
		case CAS_NL_CORE_A_PATH:
			nla_get_str(nla, c->path, sizeof(c->path));
			break;
		case CAS_NL_CORE_A_STATE:
			c->state = nla_get_u8(nla);
			break;
		case CAS_NL_CORE_A_EXP_OBJ_EXISTS:
			c->exp_obj_exists = true;
			break;
		case CAS_NL_CORE_A_SIZE:
			c->size = nla_get_u64(nla);
			break;
		case CAS_NL_CORE_A_SIZE_BYTES:
			c->size_bytes = nla_get_u64(nla);
			break;
		case CAS_NL_CORE_A_DIRTY:
			c->dirty = nla_get_u32(nla);
			break;
		case CAS_NL_CORE_A_DIRTY_FOR:
			c->dirty_for = nla_get_u64(nla);
			break;
		case CAS_NL_CORE_A_FLUSHED:
			c->flushed = nla_get_u32(nla);
			break;
		case CAS_NL_CORE_A_SEQ_CUTOFF_THRESHOLD:
			c->seq_cutoff_threshold = nla_get_u32(nla);
			break;
		case CAS_NL_CORE_A_SEQ_CUTOFF_POLICY:
			c->seq_cutoff_policy = nla_get_u8(nla);
			break;
		case CAS_NL_CORE_A_SEQ_CUTOFF_PROMO_COUNT:
			c->seq_cutoff_promo_count = nla_get_u32(nla);
			break;
		case CAS_NL_CORE_A_STATS:
			parse_stats(nla, &c->stats);
			break;
		}
	}
}

static void parse_ioclass_record(struct nlattr *nest,
				 struct cas_nl_ioclass *c)
{
	struct nlattr *nla = nla_data(nest);
	int remaining = nla_len(nest);

	memset(c, 0, sizeof(*c));

	nla_for_each(nla, remaining) {
		int type = nla->nla_type & NLA_TYPE_MASK;

		switch (type) {
		case CAS_NL_IOCLASS_A_CACHE_ID:
			c->cache_id = nla_get_u16(nla);
			break;
		case CAS_NL_IOCLASS_A_ID:
			c->id = nla_get_u32(nla);
			break;
		case CAS_NL_IOCLASS_A_NAME:
			nla_get_str(nla, c->name, sizeof(c->name));
			break;
		case CAS_NL_IOCLASS_A_CACHE_MODE:
			c->cache_mode = nla_get_u8(nla);
			break;
		case CAS_NL_IOCLASS_A_PRIORITY:
			c->priority = (int16_t)nla_get_u16(nla);
			break;
		case CAS_NL_IOCLASS_A_CURR_SIZE:
			c->curr_size = nla_get_u32(nla);
			break;
		case CAS_NL_IOCLASS_A_MIN_SIZE:
			c->min_size = nla_get_u32(nla);
			break;
		case CAS_NL_IOCLASS_A_MAX_SIZE:
			c->max_size = nla_get_u32(nla);
			break;
		case CAS_NL_IOCLASS_A_CLEANING_POLICY:
			c->cleaning_policy = nla_get_u8(nla);
			break;
		case CAS_NL_IOCLASS_A_STATS:
			parse_stats(nla, &c->stats);
			break;
		}
	}
}

/* Dynamic array helper */

struct record_list {
	void *data;
	int count;
	int capacity;
	size_t elem_size;
};

static int record_list_append(struct record_list *l, void *elem)
{
	if (l->count >= l->capacity) {
		int newcap = l->capacity ? l->capacity * 2 : 8;
		void *newdata;

		newdata = realloc(l->data, newcap * l->elem_size);
		if (!newdata)
			return -ENOMEM;
		l->data = newdata;
		l->capacity = newcap;
	}
	memcpy((char *)l->data + l->count * l->elem_size,
	       elem, l->elem_size);
	l->count++;
	return 0;
}

/* Message handler */

static int handle_message(struct nlmsghdr *nlh,
			  struct record_list *caches,
			  struct record_list *cores,
			  struct record_list *ioclasses)
{
	struct genlmsghdr *genl;
	struct nlattr *nla;
	int remaining;

	genl = NLMSG_DATA(nlh);
	nla = (struct nlattr *)((char *)genl + GENL_HDRLEN);
	remaining = nlh->nlmsg_len - NLMSG_LENGTH(GENL_HDRLEN);

	nla_for_each(nla, remaining) {
		int type = nla->nla_type & NLA_TYPE_MASK;
		int ret;

		switch (type) {
		case CAS_NL_A_CACHE: {
			struct cas_nl_cache c;

			parse_cache_record(nla, &c);
			ret = record_list_append(caches, &c);
			if (ret)
				return ret;
			break;
		}
		case CAS_NL_A_CORE: {
			struct cas_nl_core c;

			parse_core_record(nla, &c);
			ret = record_list_append(cores, &c);
			if (ret)
				return ret;
			break;
		}
		case CAS_NL_A_IO_CLASS: {
			struct cas_nl_ioclass c;

			parse_ioclass_record(nla, &c);
			ret = record_list_append(ioclasses, &c);
			if (ret)
				return ret;
			break;
		}
		}
	}

	return 0;
}

/* Public API */

int cas_nl_dump(struct cas_nl_dump_result *result)
{
	struct nl_ctx ctx = { 0 };
	char *buf = NULL;
	int ret;
	struct record_list caches = {
		.elem_size = sizeof(struct cas_nl_cache),
	};
	struct record_list cores = {
		.elem_size = sizeof(struct cas_nl_core),
	};
	struct record_list ioclasses = {
		.elem_size = sizeof(struct cas_nl_ioclass),
	};

	memset(result, 0, sizeof(*result));

	buf = malloc(NL_BUF_SIZE);
	if (!buf)
		return -ENOMEM;

	ret = nl_open(&ctx);
	if (ret)
		goto out_buf;

	ret = nl_resolve_family(&ctx, CAS_NL_FAMILY_NAME);
	if (ret)
		goto out_close;

	ret = nl_send_dump_request(&ctx);
	if (ret)
		goto out_close;

	while (1) {
		struct nlmsghdr *nlh;
		int len, remaining;
		bool done = false;

		len = recv(ctx.fd, buf, NL_BUF_SIZE, 0);
		if (len < 0) {
			ret = -errno;
			break;
		}

		nlh = (struct nlmsghdr *)buf;
		remaining = len;

		while (NLMSG_OK(nlh, remaining)) {
			if (nlh->nlmsg_type == NLMSG_DONE) {
				done = true;
				break;
			}
			if (nlh->nlmsg_type == NLMSG_ERROR) {
				struct nlmsgerr *err;

				err = NLMSG_DATA(nlh);
				ret = err->error;
				done = true;
				break;
			}

			ret = handle_message(nlh, &caches,
					     &cores, &ioclasses);
			if (ret) {
				done = true;
				break;
			}
			nlh = NLMSG_NEXT(nlh, remaining);
		}

		if (done)
			break;
	}

out_close:
	nl_close(&ctx);
out_buf:
	free(buf);

	if (ret) {
		free(caches.data);
		free(cores.data);
		free(ioclasses.data);
		return ret;
	}

	result->caches = caches.data;
	result->num_caches = caches.count;
	result->cores = cores.data;
	result->num_cores = cores.count;
	result->ioclasses = ioclasses.data;
	result->num_ioclasses = ioclasses.count;
	return 0;
}

void cas_nl_dump_free(struct cas_nl_dump_result *result)
{
	free(result->caches);
	free(result->cores);
	free(result->ioclasses);
	memset(result, 0, sizeof(*result));
}
