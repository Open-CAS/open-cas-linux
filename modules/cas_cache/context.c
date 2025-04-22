/*
* Copyright(c) 2012-2022 Intel Corporation
* Copyright(c) 2024 Huawei Technologies
* SPDX-License-Identifier: BSD-3-Clause
*/

#include "cas_cache.h"
#include "context.h"
#include "utils/utils_data.h"
#include "utils/utils_gc.h"
#include "utils/utils_mpool.h"
#include "threads.h"
#include <linux/kmemleak.h>
#include <linux/cpuhotplug.h>
#include <linux/cpu.h>

struct env_mpool *cas_bvec_pool;

#define CAS_ALLOC_PAGE_LIMIT 1024
#define PG_cas PG_private

#define CAS_LOG_RATELIMIT HZ * 5
/* High burst limit to ensure cache init logs are printed properly */
#define CAS_LOG_BURST_LIMIT 50

/* *** CONTEXT DATA OPERATIONS *** */

/*
 *
 */
static ctx_data_t *__cas_ctx_data_alloc(uint32_t pages)
{
	struct blk_data *data;
	uint32_t i;
	struct page *page = NULL;

	data = env_mpool_new(cas_bvec_pool, pages);

	if (!data) {
		CAS_PRINT_RL(KERN_ERR "Couldn't allocate BIO vector.\n");
		return NULL;
	}

	data->size = pages;

	for (i = 0; i < pages; ++i) {
		data->vec[i].bv_page = alloc_page(GFP_NOIO);

		if (!data->vec[i].bv_page)
			break;

		kmemleak_alloc(page_address(data->vec[i].bv_page), PAGE_SIZE, 1, GFP_NOIO);

		data->vec[i].bv_len = PAGE_SIZE;
		data->vec[i].bv_offset = 0;
	}

	/* One of allocations failed */
	if (i != pages) {
		for (pages = 0; pages < i; pages++) {
			page = data->vec[i].bv_page;
			__free_page(page);
		}

		env_mpool_del(cas_bvec_pool, data, pages);
		data = NULL;
	} else {
		/* Initialize iterator */
		cas_io_iter_init(&data->iter, data->vec, data->size);
	}

	return data;
}

static ctx_data_t *cas_ctx_data_alloc(uint32_t pages)
{
	return __cas_ctx_data_alloc(pages);
}

/*
 *
 */
static void cas_ctx_data_free(ctx_data_t *ctx_data)
{
	uint32_t i;
	struct page *page = NULL;
	struct blk_data *data = ctx_data;

	if (!data)
		return;

	for (i = 0; i < data->size; i++) {
		page = data->vec[i].bv_page;

		__free_page(page);
		kmemleak_free(page_address(page));
	}

	env_mpool_del(cas_bvec_pool, data, data->size);
}

static int _cas_ctx_data_mlock(ctx_data_t *ctx_data)
{
	return 0;
}

static void _cas_ctx_data_munlock(ctx_data_t *ctx_data)
{
}

static void cas_ctx_data_secure_erase(ctx_data_t *ctx_data)
{
	struct blk_data *data = ctx_data;
	uint32_t i;
	void *ptr;

	for (i = 0; i < data->size; i++) {
		ptr = page_address(data->vec[i].bv_page);
		memset(ptr, 0, PAGE_SIZE);
	}
}

/*
 *
 */
static uint32_t _cas_ctx_read_data(void *dst, ctx_data_t *src,
		uint32_t size)
{
	struct blk_data *data = src;

	return  cas_io_iter_cpy_to_data(dst, &data->iter, size);
}

/*
 *
 */
static uint32_t _cas_ctx_write_data(ctx_data_t *dst, const void *src,
		uint32_t size)
{
	struct blk_data *data = dst;

	return cas_io_iter_cpy_from_data(&data->iter, src, size);
}

/*
 *
 */
static uint32_t _cas_ctx_zero_data(ctx_data_t *dst, uint32_t size)
{
	struct blk_data *data = dst;

	return cas_io_iter_zero(&data->iter, size);
}

/*
 *
 */
static uint32_t _cas_ctx_seek_data(ctx_data_t *dst,
		ctx_data_seek_t seek, uint32_t offset)
{
	struct blk_data *data = dst;

	switch (seek) {
	case ctx_data_seek_begin:
		cas_io_iter_init(&data->iter, data->vec, data->size);

	case ctx_data_seek_current:
		/* TODO Implement this if needed or remove this from enum */
		break;

	default:
		BUG();
		return 0;
	}

	return cas_io_iter_move(&data->iter, offset);
}

/*
 *
 */
static uint64_t _cas_ctx_data_copy(ctx_data_t *dst, ctx_data_t *src,
		uint64_t to, uint64_t from, uint64_t bytes)
{
	struct blk_data *src_data = src, *dst_data = dst;

	return cas_data_cpy(dst_data->vec, dst_data->size, src_data->vec,
			src_data->size, to, from, bytes);
}

static int _cas_ctx_cleaner_init(ocf_cleaner_t c)
{
	return cas_create_cleaner_thread(c);
}

static void _cas_ctx_cleaner_kick(ocf_cleaner_t c)
{
	return cas_kick_cleaner_thread(c);
}

static void _cas_ctx_cleaner_stop(ocf_cleaner_t c)
{
	return cas_stop_cleaner_thread(c);
}

#define CAS_LOG_FORMAT_STRING_MAX_LEN 256

static int _cas_ctx_logger_open(ocf_logger_t logger)
{
	void __percpu *priv;

	priv = alloc_percpu(char[CAS_LOG_FORMAT_STRING_MAX_LEN]);
	if (!priv)
		return -ENOMEM;

	ocf_logger_set_priv(logger, priv);

	return 0;
}

static void _cas_ctx_logger_close(ocf_logger_t logger)
{
	void __percpu *priv = ocf_logger_get_priv(logger);

	free_percpu(priv);
}

/*
 *
 */
static int _cas_ctx_logger_print(ocf_logger_t logger, ocf_logger_lvl_t lvl,
		const char *fmt, va_list args)
{
	static const char* level[] =  {
		[log_emerg] = KERN_EMERG,
		[log_alert] = KERN_ALERT,
		[log_crit] = KERN_CRIT,
		[log_err] = KERN_ERR,
		[log_warn] = KERN_WARNING,
		[log_notice] = KERN_NOTICE,
		[log_info] = KERN_INFO,
		[log_debug] = KERN_DEBUG,
	};
	int ret;
	void __percpu *priv;
	char *buf;

	if (((unsigned)lvl) >= sizeof(level)/sizeof(level[0]))
		return -EINVAL;

	priv = ocf_logger_get_priv(logger);
	buf = get_cpu_ptr(priv);

	/* Try to prepend log level prefix to format string. If this fails
	 * for any reason, we just fall back to user provided format string */
	ret = snprintf(buf, CAS_LOG_FORMAT_STRING_MAX_LEN, "%s%s", level[lvl],
			fmt);
	if (ret >= CAS_LOG_FORMAT_STRING_MAX_LEN)
		vprintk(fmt, args);
	else
		vprintk(buf, args);


	put_cpu_ptr(priv);

	return 0;
}

/*
 *
 */
static int _cas_ctx_logger_print_rl(ocf_logger_t logger, const char *func_name)
{
	static DEFINE_RATELIMIT_STATE(cas_log_rl, CAS_LOG_RATELIMIT,
			CAS_LOG_BURST_LIMIT);

	if (!func_name)
		return -EINVAL;

	return ___ratelimit(&cas_log_rl, func_name);
}

/*
 *
 */
static int _cas_ctx_logger_dump_stack(ocf_logger_t logger)
{
	dump_stack();

	return 0;
}

static const struct ocf_ctx_config ctx_cfg = {
	.name = "CAS Linux Kernel",
	.ops = {
		.data = {
			.alloc = cas_ctx_data_alloc,
			.free = cas_ctx_data_free,
			.mlock = _cas_ctx_data_mlock,
			.munlock = _cas_ctx_data_munlock,
			.read = _cas_ctx_read_data,
			.write = _cas_ctx_write_data,
			.zero = _cas_ctx_zero_data,
			.seek = _cas_ctx_seek_data,
			.copy = _cas_ctx_data_copy,
			.secure_erase = cas_ctx_data_secure_erase,
		},

		.cleaner = {
			.init = _cas_ctx_cleaner_init,
			.kick = _cas_ctx_cleaner_kick,
			.stop = _cas_ctx_cleaner_stop,
		},

		.logger = {
			.open = _cas_ctx_logger_open,
			.close = _cas_ctx_logger_close,
			.print = _cas_ctx_logger_print,
			.print_rl = _cas_ctx_logger_print_rl,
			.dump_stack = _cas_ctx_logger_dump_stack,
		},
	},
};

/* *** CONTEXT INITIALIZATION *** */

int cas_initialize_context(void)
{
	int ret;

	ret = ocf_ctx_create(&cas_ctx, &ctx_cfg);
	if (ret < 0)
		return ret;

	cas_bvec_pool = env_mpool_create(sizeof(struct blk_data),
			sizeof(struct bio_vec), GFP_NOIO, 7, true,
			"cas_biovec", true);

	if (!cas_bvec_pool) {
		printk(KERN_ERR "Cannot create BIO vector memory pool\n");
		ret = -ENOMEM;
		goto err_ctx;
	}

	cas_garbage_collector_init();

	ret = block_dev_init();
	if (ret) {
		printk(KERN_ERR "Cannot initialize block device layer\n");
		goto err_mpool;

	}
	ret = cpuhp_setup_state(CPUHP_AP_ONLINE_DYN, "Linux/opencas:online",
			cas_starting_cpu, cas_ending_cpu);
	if (ret < 0) {
		pr_err("open-cas: failed to register hotplug callbacks, ret=%d\n", ret);
		goto err_mpool;
	}

	return 0;

err_mpool:
	env_mpool_destroy(cas_bvec_pool);
err_ctx:
	ocf_ctx_put(cas_ctx);

	return ret;
}

void cas_cleanup_context(void)
{
	cpuhp_remove_state(CPUHP_AP_ONLINE_DYN);
	cas_garbage_collector_deinit();
	env_mpool_destroy(cas_bvec_pool);

	ocf_ctx_put(cas_ctx);
}

/* *** CONTEXT DATA HELPER FUNCTION *** */

/*
 *
 */
struct blk_data *cas_alloc_blk_data(uint32_t size, gfp_t flags)
{
	struct blk_data *data = env_mpool_new_f(cas_bvec_pool, size, flags);

	if (data)
		data->size = size;

	return data;
}

/*
 *
 */
void cas_free_blk_data(struct blk_data *data)
{
	if (!data)
		return;

	env_mpool_del(cas_bvec_pool, data, data->size);
}

