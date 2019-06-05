/*
* Copyright(c) 2012-2019 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#include "cas_cache.h"
#include "context.h"
#include "utils/utils_rpool.h"
#include "utils/utils_data.h"
#include "utils/utils_gc.h"
#include "utils/utils_mpool.h"
#include "threads.h"

struct cas_mpool *cas_bvec_pool;

struct cas_reserve_pool *cas_bvec_pages_rpool;

#define CAS_ALLOC_PAGE_LIMIT 1024
#define PG_cas PG_private

#define CAS_LOG_RATELIMIT HZ * 5
/* High burst limit to ensure cache init logs are printed properly */
#define CAS_LOG_BURST_LIMIT 50

static inline void _cas_page_set_priv(struct page *page)
{
	set_bit(PG_cas , &page->flags);
}

static inline void _cas_page_clear_priv(struct page *page)
{
	clear_bit(PG_cas , &page->flags);
	page->private = 0;
}

static inline int _cas_page_test_priv(struct page *page)
{
	return test_bit(PG_cas , &page->flags);
}

static void _cas_free_page_rpool(void *allocator_ctx, void *item)
{
	struct page *page = virt_to_page(item);

	_cas_page_clear_priv(page);
	__free_page(page);
}

static void _cas_page_set_cpu(struct page *page, int cpu)
{
	page->private = cpu;
}

void *_cas_alloc_page_rpool(void *allocator_ctx, int cpu)
{
	struct page *page;

	page = alloc_page(GFP_NOIO | __GFP_NORETRY);
	if (!page)
		return NULL;

	if (_cas_page_test_priv(page)) {
		printk(KERN_WARNING "CAS private bit is set\n");
		WARN(true, OCF_PREFIX_SHORT" CAS private bit is set\n");
	}

	_cas_page_set_priv(page);
	_cas_page_set_cpu(page, cpu);
	return page_address(page);
}

static int _cas_page_get_cpu(struct page *page)
{
	return page->private;
}

/* *** CONTEXT DATA OPERATIONS *** */

/*
 *
 */
ctx_data_t *__cas_ctx_data_alloc(uint32_t pages, bool zalloc)
{
	struct blk_data *data;
	uint32_t i;
	void *page_addr = NULL;
	struct page *page = NULL;
	int cpu;

	data = cas_mpool_new(cas_bvec_pool, pages);

	if (!data) {
		CAS_PRINT_RL(KERN_ERR "Couldn't allocate BIO vector.\n");
		return NULL;
	}

	data->size = pages;

	for (i = 0; i < pages; ++i) {
		page_addr = cas_rpool_try_get(cas_bvec_pages_rpool, &cpu);
		if (page_addr) {
			data->vec[i].bv_page = virt_to_page(page_addr);
			_cas_page_set_cpu(data->vec[i].bv_page, cpu);
		} else {
			data->vec[i].bv_page = alloc_page(GFP_NOIO);
		}

		if (!data->vec[i].bv_page)
			break;

		if (zalloc) {
			if (!page_addr) {
				page_addr = page_address(
						data->vec[i].bv_page);
			}
			memset(page_addr, 0, PAGE_SIZE);
		}

		data->vec[i].bv_len = PAGE_SIZE;
		data->vec[i].bv_offset = 0;
	}

	/* One of allocations failed */
	if (i != pages) {
		for (pages = 0; pages < i; pages++) {
			page = data->vec[i].bv_page;

			if (page && !(_cas_page_test_priv(page) &&
					!cas_rpool_try_put(cas_bvec_pages_rpool,
					page_address(page),
					_cas_page_get_cpu(page)))) {
				__free_page(page);
			}
		}

		cas_mpool_del(cas_bvec_pool, data, pages);
		data = NULL;
	} else {
		/* Initialize iterator */
		cas_io_iter_init(&data->iter, data->vec, data->size);
	}

	return data;
}

ctx_data_t *cas_ctx_data_alloc(uint32_t pages)
{
	return __cas_ctx_data_alloc(pages, false);
}

ctx_data_t *cas_ctx_data_zalloc(uint32_t pages)
{
	return __cas_ctx_data_alloc(pages, true);
}

/*
 *
 */
void cas_ctx_data_free(ctx_data_t *ctx_data)
{
	uint32_t i;
	struct page *page = NULL;
	struct blk_data *data = ctx_data;

	if (!data)
		return;

	for (i = 0; i < data->size; i++) {
		page = data->vec[i].bv_page;

		if (!(_cas_page_test_priv(page) && !cas_rpool_try_put(
				cas_bvec_pages_rpool,
				page_address(page),
				_cas_page_get_cpu(page))))
			__free_page(page);
	}

	cas_mpool_del(cas_bvec_pool, data, data->size);
}

static int _cas_ctx_data_mlock(ctx_data_t *ctx_data)
{
	return 0;
}

static void _cas_ctx_data_munlock(ctx_data_t *ctx_data)
{
}

void cas_ctx_data_secure_erase(ctx_data_t *ctx_data)
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

static int _cas_ctx_metadata_updater_init(ocf_metadata_updater_t mu)
{
	return cas_create_metadata_updater_thread(mu);
}

static void _cas_ctx_metadata_updater_kick(ocf_metadata_updater_t mu)
{
	return cas_kick_metadata_updater_thread(mu);
}

static void _cas_ctx_metadata_updater_stop(ocf_metadata_updater_t mu)
{
	return cas_stop_metadata_updater_thread(mu);
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
	char *format;
	if (((unsigned)lvl) >= sizeof(level))
		return -EINVAL;

	format = kasprintf(GFP_ATOMIC, "%s%s", level[lvl], fmt);
	if (!format)
		return -ENOMEM;

	vprintk(format, args);

	kfree(format);

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

		.metadata_updater = {
			.init = _cas_ctx_metadata_updater_init,
			.kick = _cas_ctx_metadata_updater_kick,
			.stop = _cas_ctx_metadata_updater_stop,
		},

		.logger = {
			.print = _cas_ctx_logger_print,
			.print_rl = _cas_ctx_logger_print_rl,
			.dump_stack = _cas_ctx_logger_dump_stack,
		},
	},
};

/* *** CONTEXT INITIALIZATION *** */

int cas_initialize_context(void)
{
	struct blk_data data;
	int ret;

	ret = ocf_ctx_create(&cas_ctx, &ctx_cfg);
	if (ret < 0)
		return ret;

	cas_bvec_pool = cas_mpool_create(sizeof(data), sizeof(data.vec[0]),
			GFP_NOIO, 7, "cas_biovec");

	if (!cas_bvec_pool) {
		printk(KERN_ERR "Cannot create BIO vector memory pool\n");
		ret = -ENOMEM;
		goto err_ctx;
	}

	cas_bvec_pages_rpool = cas_rpool_create(CAS_ALLOC_PAGE_LIMIT,
			NULL, PAGE_SIZE, _cas_alloc_page_rpool,
			_cas_free_page_rpool, NULL);
	if (!cas_bvec_pages_rpool) {
		printk(KERN_ERR "Cannot create reserve pool for "
				"BIO vector memory pool\n");
		ret = -ENOMEM;
		goto err_mpool;
	}

	cas_garbage_collector_init();

	ret = block_dev_init();
	if (ret) {
		printk(KERN_ERR "Cannot initialize block device layer\n");
		goto err_rpool;

	}

	ret = atomic_dev_init();
	if (ret) {
		printk(KERN_ERR "Cannot initialize atomic device layer\n");
		goto err_block_dev;
	}

	return 0;

err_block_dev:
	block_dev_deinit();
err_rpool:
	cas_rpool_destroy(cas_bvec_pages_rpool, _cas_free_page_rpool, NULL);
err_mpool:
	cas_mpool_destroy(cas_bvec_pool);
err_ctx:
	ocf_ctx_put(cas_ctx);

	return ret;
}

void cas_cleanup_context(void)
{
	block_dev_deinit();
	atomic_dev_deinit();
	cas_garbage_collector_deinit();
	cas_mpool_destroy(cas_bvec_pool);
	cas_rpool_destroy(cas_bvec_pages_rpool, _cas_free_page_rpool, NULL);

	ocf_ctx_put(cas_ctx);
}

/* *** CONTEXT DATA HELPER FUNCTION *** */

/*
 *
 */
struct blk_data *cas_alloc_blk_data(uint32_t size, gfp_t flags)
{
	struct blk_data *data = cas_mpool_new_f(cas_bvec_pool, size, flags);

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

	cas_mpool_del(cas_bvec_pool, data, data->size);
}

