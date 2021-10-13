/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#include "cas_cache.h"
#include "utils/utils_blk.h"
#include "threads.h"

extern u32 max_writeback_queue_size;
extern u32 writeback_queue_unblock_size;
extern u32 metadata_layout;
extern u32 unaligned_io;
extern u32 seq_cut_off_mb;
extern u32 use_io_scheduler;

struct cas_lazy_thread {
	char name[64];
	struct task_struct *thread;
	int (*threadfn)(void *data);
	void *data;
	wait_queue_head_t wq;
	atomic_t run;
	atomic_t stop;
};

static int cas_lazy_thread_fn(void *data)
{
	struct cas_lazy_thread *clt = data;
	int (*threadfn)(void *data) = clt->threadfn;
	void *threaddata = clt->data;

	while (wait_event_interruptible(clt->wq,
			atomic_read(&clt->stop) || atomic_read(&clt->run)));

	if (atomic_read(&clt->stop)) {
		kfree(clt);
		return 0;
	}

	kfree(clt);
	return threadfn(threaddata);
}

static struct cas_lazy_thread *cas_lazy_thread_create(
		int (*threadfn)(void *data), void *data, const char *fmt, ...)
{
	struct cas_lazy_thread *clt;
	va_list args;
	int error;

	clt = kmalloc(sizeof(*clt), GFP_KERNEL);
	if (!clt)
		return ERR_PTR(-ENOMEM);

	va_start(args, fmt);
	vsnprintf(clt->name, sizeof(clt->name), fmt, args);
	va_end(args);

	clt->thread = kthread_create(cas_lazy_thread_fn, clt, "%s", clt->name);
	if (IS_ERR(clt->thread)) {
		error = PTR_ERR(clt->thread);
		kfree(clt);
		return ERR_PTR(error);
	}

	clt->threadfn = threadfn;
	clt->data = data;
	init_waitqueue_head(&clt->wq);
	atomic_set(&clt->run, 0);
	atomic_set(&clt->stop, 0);
	wake_up_process(clt->thread);

	return clt;
}

/*
 * The caller must ensure that cas_lazy_thread wasn't released.
 */
static void cas_lazy_thread_stop(struct cas_lazy_thread *clt)
{
	atomic_set(&clt->stop, 1);
	wake_up(&clt->wq);
}

/*
 * The caller must ensure that cas_lazy_thread wasn't released.
 */
static void cas_lazy_thread_wake_up(struct cas_lazy_thread *clt)
{
	atomic_set(&clt->run, 1);
	wake_up(&clt->wq);
}

struct _cache_mngt_sync_context {
	struct completion cmpl;
	int *result;
};

struct _cache_mngt_async_context {
	struct completion cmpl;
	spinlock_t lock;
	int result;
	void (*compl_func)(ocf_cache_t cache);
};

/*
 * Value used to mark async call as completed. Used when OCF call already
 * finished, but complete function still has to be performed.
 */
#define ASYNC_CALL_FINISHED 1

static int _cache_mngt_async_callee_set_result(
	struct _cache_mngt_async_context *context,
	int error)
{
	bool interrupted;
	int ret;

	spin_lock(&context->lock);

	interrupted = (context->result == -KCAS_ERR_WAITING_INTERRUPTED);
	if (!interrupted)
		context->result = error ?: ASYNC_CALL_FINISHED;
	complete(&context->cmpl);

	ret = context->result;
	spin_unlock(&context->lock);

	return ret == ASYNC_CALL_FINISHED ? 0 : ret;
}

static int _cache_mngt_async_caller_set_result(
	struct _cache_mngt_async_context *context,
	int error)
{
	unsigned long lock_flags = 0;
	int result = error;

	spin_lock_irqsave(&context->lock, lock_flags);
	if (context->result)
		result = (context->result != ASYNC_CALL_FINISHED) ?
				context->result : 0;
	else if (result < 0)
		result = context->result = -KCAS_ERR_WAITING_INTERRUPTED;
	spin_unlock_irqrestore(&context->lock, lock_flags);

	return result;
}

static inline void _cache_mngt_async_context_init(
		struct _cache_mngt_async_context *context)
{
	init_completion(&context->cmpl);
	spin_lock_init(&context->lock);
	context->result = 0;
	context->compl_func = NULL;
}

static void _cache_mngt_lock_complete(ocf_cache_t cache, void *priv, int error)
{
	struct _cache_mngt_async_context *context = priv;
	int result;

	result = _cache_mngt_async_callee_set_result(context, error);

	if (result == -KCAS_ERR_WAITING_INTERRUPTED && error == 0)
		ocf_mngt_cache_unlock(cache);

	if (result == -KCAS_ERR_WAITING_INTERRUPTED)
		kfree(context);
}

static int _cache_mngt_lock_sync(ocf_cache_t cache)
{
	struct _cache_mngt_async_context *context;
	int result;

	context = kmalloc(sizeof(*context), GFP_KERNEL);
	if (!context)
		return -ENOMEM;

	_cache_mngt_async_context_init(context);

	ocf_mngt_cache_lock(cache, _cache_mngt_lock_complete, context);
	result = wait_for_completion_interruptible(&context->cmpl);

	result = _cache_mngt_async_caller_set_result(context, result);

	if (result != -KCAS_ERR_WAITING_INTERRUPTED)
		kfree(context);

	return result;
}

static void _cache_mngt_read_lock_complete(ocf_cache_t cache, void *priv,
		int error)
{
	struct _cache_mngt_async_context *context = priv;
	int result;

	result = _cache_mngt_async_callee_set_result(context, error);

	if (result == -KCAS_ERR_WAITING_INTERRUPTED && error == 0)
		ocf_mngt_cache_read_unlock(cache);

	if (result == -KCAS_ERR_WAITING_INTERRUPTED)
		kfree(context);
}

static int _cache_mngt_read_lock_sync(ocf_cache_t cache)
{
	struct _cache_mngt_async_context *context;
	int result;

	context = kmalloc(sizeof(*context), GFP_KERNEL);
	if (!context)
		return -ENOMEM;

	_cache_mngt_async_context_init(context);

	ocf_mngt_cache_read_lock(cache, _cache_mngt_read_lock_complete, context);
	result = wait_for_completion_interruptible(&context->cmpl);

	result = _cache_mngt_async_caller_set_result(context, result);

	if (result != -KCAS_ERR_WAITING_INTERRUPTED)
		kfree(context);

	return result;
}

static void _cache_mngt_save_sync_complete(ocf_cache_t cache, void *priv,
		int error)
{
	struct _cache_mngt_async_context *context = priv;
	int result;

	result = _cache_mngt_async_callee_set_result(context, error);

	if (result == -KCAS_ERR_WAITING_INTERRUPTED)
		kfree(context);
}

static int _cache_mngt_save_sync(ocf_cache_t cache)
{
	struct _cache_mngt_async_context *context;
	int result;

	context = kmalloc(sizeof(*context), GFP_KERNEL);
	if (!context)
		return -ENOMEM;

	_cache_mngt_async_context_init(context);

	ocf_mngt_cache_save(cache, _cache_mngt_save_sync_complete, context);
	result = wait_for_completion_interruptible(&context->cmpl);

	result = _cache_mngt_async_caller_set_result(context, result);

	if (result != -KCAS_ERR_WAITING_INTERRUPTED)
		kfree(context);

	return result;
}

static void _cache_mngt_cache_flush_uninterruptible_complete(ocf_cache_t cache,
		void *priv, int error)
{
	struct _cache_mngt_sync_context *context = priv;

	*context->result = error;
	complete(&context->cmpl);
}

/*
 * Since wait_for_completion() is used, hang tasks may occure if flush would
 * take long time.
 */
static int _cache_mngt_cache_flush_uninterruptible(ocf_cache_t cache)
{
	int result;
	struct _cache_mngt_sync_context context;
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);

	init_completion(&context.cmpl);
	context.result = &result;
	atomic_set(&cache_priv->flush_interrupt_enabled, 0);

	ocf_mngt_cache_flush(cache, _cache_mngt_cache_flush_uninterruptible_complete,
			&context);
	wait_for_completion(&context.cmpl);

	atomic_set(&cache_priv->flush_interrupt_enabled, 1);

	return result;
}

static void _cache_mngt_cache_purge_complete(ocf_cache_t cache, void *priv,
		int error)
{
	struct _cache_mngt_async_context *context = priv;
	int result;

	if (context->compl_func)
		context->compl_func(cache);

	result = _cache_mngt_async_callee_set_result(context, error);

	if (result == -KCAS_ERR_WAITING_INTERRUPTED)
		kfree(context);
}

/*
 * Possible return values:
 * 0 - completion was called and operation succeded
 * -KCAS_ERR_WAITING_INTERRUPTED - operation was canceled, caller must
 *		propagate error
 * other values - completion was called and operation failed
 */
static int _cache_mngt_cache_purge_sync(ocf_cache_t cache,
		void (*compl)(ocf_cache_t cache))
{
	int result;
	struct _cache_mngt_async_context *context;

	context = kmalloc(sizeof(*context), GFP_KERNEL);
	if (!context) {
		if (compl)
			compl(cache);
		return -ENOMEM;
	}

	_cache_mngt_async_context_init(context);
	context->compl_func = compl;

	ocf_mngt_cache_purge(cache, _cache_mngt_cache_purge_complete, context);
	result = wait_for_completion_interruptible(&context->cmpl);

	result = _cache_mngt_async_caller_set_result(context, result);

	if (result != -KCAS_ERR_WAITING_INTERRUPTED)
		kfree(context);

	return result;
}

static void _cache_mngt_core_purge_complete(ocf_core_t core, void *priv,
		int error)
{
	struct _cache_mngt_async_context *context = priv;
	int result;
	ocf_cache_t cache = ocf_core_get_cache(core);

	if (context->compl_func)
		context->compl_func(cache);

	result = _cache_mngt_async_callee_set_result(context, error);

	if (result == -KCAS_ERR_WAITING_INTERRUPTED)
		kfree(context);
}

/*
 * Possible return values:
 * 0 - completion was called and operation succeded
 * -KCAS_ERR_WAITING_INTERRUPTED - operation was canceled, caller must
 *		propagate error
 * other values - completion was called and operation failed
 */
static int _cache_mngt_core_purge_sync(ocf_core_t core, bool interruption,
		void (*compl)(ocf_cache_t cache))
{
	int result;
	struct _cache_mngt_async_context *context;
	ocf_cache_t cache = ocf_core_get_cache(core);

	context = kmalloc(sizeof(*context), GFP_KERNEL);
	if (!context) {
		if (compl)
			compl(cache);
		return -ENOMEM;
	}

	_cache_mngt_async_context_init(context);
	context->compl_func = compl;

	ocf_mngt_core_purge(core, _cache_mngt_core_purge_complete, context);
	result = wait_for_completion_interruptible(&context->cmpl);

	result = _cache_mngt_async_caller_set_result(context, result);

	if (result != -KCAS_ERR_WAITING_INTERRUPTED)
		kfree(context);

	return result;
}

static void _cache_mngt_cache_flush_complete(ocf_cache_t cache, void *priv,
		int error)
{
	struct _cache_mngt_async_context *context = priv;
	int result;

	if (context->compl_func)
		context->compl_func(cache);

	result = _cache_mngt_async_callee_set_result(context, error);

	if (result == -KCAS_ERR_WAITING_INTERRUPTED)
		kfree(context);
}

/*
 * Possible return values:
 * 0 - completion was called and operation succeded
 * -KCAS_ERR_WAITING_INTERRUPTED - operation was canceled, caller must
 *		propagate error, completion will be called asynchronously
 * other values - completion was called and operation failed
 */
static int _cache_mngt_cache_flush_sync(ocf_cache_t cache, bool interruption,
		void (*compl)(ocf_cache_t cache))
{
	int result;
	struct _cache_mngt_async_context *context;
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);

	context = kmalloc(sizeof(*context), GFP_KERNEL);
	if (!context) {
		if (compl)
			compl(cache);
		return -ENOMEM;
	}

	_cache_mngt_async_context_init(context);
	context->compl_func = compl;
	atomic_set(&cache_priv->flush_interrupt_enabled, interruption);

	ocf_mngt_cache_flush(cache, _cache_mngt_cache_flush_complete, context);
	result = wait_for_completion_interruptible(&context->cmpl);

	result = _cache_mngt_async_caller_set_result(context, result);

	if (result != -KCAS_ERR_WAITING_INTERRUPTED)
		kfree(context);
	else if (result == -KCAS_ERR_WAITING_INTERRUPTED && interruption)
		ocf_mngt_cache_flush_interrupt(cache);

	atomic_set(&cache_priv->flush_interrupt_enabled, 1);

	return result;
}

static void _cache_mngt_core_flush_complete(ocf_core_t core, void *priv,
		int error)
{
	struct _cache_mngt_async_context *context = priv;
	int result;
	ocf_cache_t cache = ocf_core_get_cache(core);

	if (context->compl_func)
		context->compl_func(cache);

	result = _cache_mngt_async_callee_set_result(context, error);

	if (result == -KCAS_ERR_WAITING_INTERRUPTED)
		kfree(context);
}

/*
 * Possible return values:
 * 0 - completion was called and operation succeded
 * -KCAS_ERR_WAITING_INTERRUPTED - operation was canceled, caller must
 *		propagate error, completion will be called asynchronously
 * other values - completion was called and operation failed
 */
static int _cache_mngt_core_flush_sync(ocf_core_t core, bool interruption,
		void (*compl)(ocf_cache_t cache))
{
	int result;
	struct _cache_mngt_async_context *context;
	ocf_cache_t cache = ocf_core_get_cache(core);
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);

	context = kmalloc(sizeof(*context), GFP_KERNEL);
	if (!context) {
		if (compl)
			compl(cache);
		return -ENOMEM;
	}

	_cache_mngt_async_context_init(context);
	context->compl_func = compl;
	atomic_set(&cache_priv->flush_interrupt_enabled, interruption);

	ocf_mngt_core_flush(core, _cache_mngt_core_flush_complete, context);
	result = wait_for_completion_interruptible(&context->cmpl);

	result = _cache_mngt_async_caller_set_result(context, result);

	if (result != -KCAS_ERR_WAITING_INTERRUPTED)
		kfree(context);
	else if (result == -KCAS_ERR_WAITING_INTERRUPTED && interruption)
		ocf_mngt_cache_flush_interrupt(cache);

	atomic_set(&cache_priv->flush_interrupt_enabled, 1);

	return result;
}

static void _cache_mngt_core_flush_uninterruptible_complete(ocf_core_t core,
		void *priv, int error)
{
	struct _cache_mngt_sync_context *context = priv;

	*context->result = error;
	complete(&context->cmpl);
}

/*
 * Since wait_for_completion() is used, hang tasks may occure if flush would
 * take long time.
 */
static int _cache_mngt_core_flush_uninterruptible(ocf_core_t core)
{
	int result;
	struct _cache_mngt_sync_context context;
	ocf_cache_t cache = ocf_core_get_cache(core);
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);

	init_completion(&context.cmpl);
	context.result = &result;
	atomic_set(&cache_priv->flush_interrupt_enabled, 0);

	ocf_mngt_core_flush(core, _cache_mngt_core_flush_uninterruptible_complete,
			&context);
	wait_for_completion(&context.cmpl);

	atomic_set(&cache_priv->flush_interrupt_enabled, 1);

	return result;
}

struct _cache_mngt_stop_context {
	struct _cache_mngt_async_context async;
	int error;
	int flush_status;
	ocf_cache_t cache;
	struct cas_lazy_thread *finish_thread;
};

static void _cache_mngt_cache_priv_deinit(ocf_cache_t cache)
{
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);

	kfree(cache_priv->stop_context);

	vfree(cache_priv);
}

static int exit_instance_finish(void *data)
{
	struct cache_priv *cache_priv;
	struct _cache_mngt_stop_context *ctx = data;
	ocf_queue_t mngt_queue;
	int result = 0;

	cache_priv = ocf_cache_get_priv(ctx->cache);
	mngt_queue = cache_priv->mngt_queue;

	if (ctx->error && ctx->error != -OCF_ERR_WRITE_CACHE)
		BUG_ON(ctx->error);

	if (!ctx->error && ctx->flush_status)
		result = -KCAS_ERR_STOPPED_DIRTY;
	else
		result = ctx->error;

	if (!ocf_cache_is_standby(ctx->cache))
		cas_cls_deinit(ctx->cache);

	vfree(cache_priv);

	ocf_mngt_cache_unlock(ctx->cache);
	ocf_mngt_cache_put(ctx->cache);
	ocf_queue_put(mngt_queue);

	result = _cache_mngt_async_callee_set_result(&ctx->async, result);

	if (result == -KCAS_ERR_WAITING_INTERRUPTED)
		kfree(ctx);

	module_put_and_exit(0);
}

struct _cache_mngt_attach_context {
	struct _cache_mngt_async_context async;
	char cache_elevator[MAX_ELEVATOR_NAME];
	uint64_t min_free_ram;
	struct ocf_mngt_cache_device_config *device_cfg;
	ocf_cache_t cache;
	int ocf_start_error;
	struct cas_lazy_thread *rollback_thread;

	struct {
		bool priv_inited:1;
		bool cls_inited:1;
	};
};


static int cache_start_rollback(void *data)
{
	struct cache_priv *cache_priv;
	ocf_queue_t mngt_queue = NULL;
	struct _cache_mngt_attach_context *ctx = data;
	ocf_cache_t cache = ctx->cache;
	int result;

	if (ctx->cls_inited)
		cas_cls_deinit(cache);

	if (ctx->priv_inited) {
		cache_priv = ocf_cache_get_priv(cache);
		mngt_queue = cache_priv->mngt_queue;
		_cache_mngt_cache_priv_deinit(cache);
	}

	ocf_mngt_cache_unlock(cache);

	if (mngt_queue)
		ocf_queue_put(mngt_queue);

	result = _cache_mngt_async_callee_set_result(&ctx->async,
			ctx->ocf_start_error);

	if (result == -KCAS_ERR_WAITING_INTERRUPTED)
		kfree(ctx);

	module_put_and_exit(0);

	return 0;
}

static void _cache_mngt_cache_stop_rollback_complete(ocf_cache_t cache,
		void *priv, int error)
{
	struct _cache_mngt_attach_context *ctx = priv;

	if (error == -OCF_ERR_WRITE_CACHE)
		printk(KERN_WARNING "Cannot save cache state\n");
	else
		BUG_ON(error);

	cas_lazy_thread_wake_up(ctx->rollback_thread);
}

static void _cache_mngt_cache_stop_complete(ocf_cache_t cache, void *priv,
		int error)
{
	struct _cache_mngt_stop_context *context = priv;

	context->error = error;
	cas_lazy_thread_wake_up(context->finish_thread);
}

static int _cache_mngt_cache_stop_sync(ocf_cache_t cache)
{
	struct cache_priv *cache_priv;
	struct _cache_mngt_stop_context *context;
	int result = 0;

	cache_priv = ocf_cache_get_priv(cache);
	context = cache_priv->stop_context;

	_cache_mngt_async_context_init(&context->async);
	context->error = 0;
	context->cache = cache;

	ocf_mngt_cache_stop(cache, _cache_mngt_cache_stop_complete, context);
	result = wait_for_completion_interruptible(&context->async.cmpl);

	result = _cache_mngt_async_caller_set_result(&context->async, result);

	if (result != -KCAS_ERR_WAITING_INTERRUPTED)
		kfree(context);

	return result;
}

static uint16_t find_free_cache_id(ocf_ctx_t ctx)
{
	ocf_cache_t cache;
	uint16_t id;
	int result;

	for (id = OCF_CACHE_ID_MIN; id < OCF_CACHE_ID_MAX; id++) {
		result = mngt_get_cache_by_id(ctx, id, &cache);
		if (!result)
			ocf_mngt_cache_put(cache);
		else if (result == -OCF_ERR_CACHE_NOT_EXIST)
			break;
		else
			return OCF_CACHE_ID_INVALID;
	}

	return id;
}

static uint64_t _ffz(uint64_t word)
{
	int i;

	for (i = 0; i < sizeof(word)*8 && (word & 1); i++)
		word >>= 1;

	return i;
}

static uint16_t find_free_core_id(uint64_t *bitmap)
{
	uint16_t i, ret = OCF_CORE_MAX;
	bool zero_core_free = !(*bitmap & 0x1UL);

	/* check if any core id is free except 0 */
	for (i = 0; i * sizeof(uint64_t) * 8 < OCF_CORE_MAX; i++) {
		uint64_t ignore_mask = (i == 0) ? 1UL : 0UL;
		if (~(bitmap[i] | ignore_mask)) {
			ret = min((uint64_t)OCF_CORE_MAX,
					(uint64_t)(i * sizeof(uint64_t) * 8
					+ _ffz(bitmap[i] | ignore_mask)));
			break;
		}
	}

	/* return 0 only if no other core is free */
	if (ret == OCF_CORE_MAX && zero_core_free)
		return 0;

	return ret;
}

static void mark_core_id_used(ocf_cache_t cache, uint16_t core_id)
{
	uint64_t *bitmap;
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);

	bitmap = cache_priv->core_id_bitmap;

	set_bit(core_id, (unsigned long *)bitmap);
}

static void mark_core_id_free(ocf_cache_t cache, uint16_t core_id)
{
	uint64_t *bitmap;
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);

	bitmap = cache_priv->core_id_bitmap;

	clear_bit(core_id, (unsigned long *)bitmap);
}

static void _cache_read_unlock_put_cmpl(ocf_cache_t cache)
{
	ocf_mngt_cache_read_unlock(cache);
	ocf_mngt_cache_put(cache);
}

int cache_mngt_purge_object(const char *cache_name, size_t cache_name_len,
			const char *core_name, size_t core_name_len)
{
	ocf_cache_t cache;
	ocf_core_t core;
	int result;

	result = ocf_mngt_cache_get_by_name(cas_ctx, cache_name,
					cache_name_len, &cache);
	if (result)
		return result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result) {
		ocf_mngt_cache_put(cache);
		return result;
	}

	result = ocf_core_get_by_name(cache, core_name, core_name_len, &core);
	if (result) {
		ocf_mngt_cache_read_unlock(cache);
		ocf_mngt_cache_put(cache);
		return result;
	}

	result = _cache_mngt_core_purge_sync(core, true,
			_cache_read_unlock_put_cmpl);

	return result;
}

int cache_mngt_flush_object(const char *cache_name, size_t cache_name_len,
			const char *core_name, size_t core_name_len)
{
	ocf_cache_t cache;
	ocf_core_t core;
	int result;

	result = ocf_mngt_cache_get_by_name(cas_ctx, cache_name,
					cache_name_len, &cache);
	if (result)
		return result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result) {
		ocf_mngt_cache_put(cache);
		return result;
	}

	result = ocf_core_get_by_name(cache, core_name, core_name_len, &core);
	if (result) {
		ocf_mngt_cache_read_unlock(cache);
		ocf_mngt_cache_put(cache);
		return result;
	}

	result = _cache_mngt_core_flush_sync(core, true,
			_cache_read_unlock_put_cmpl);

	return result;
}

int cache_mngt_purge_device(const char *cache_name, size_t name_len)
{
	int result;
	ocf_cache_t cache;

	result = ocf_mngt_cache_get_by_name(cas_ctx, cache_name,
					name_len, &cache);
	if (result)
		return result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result) {
		ocf_mngt_cache_put(cache);
		return result;
	}

	result = _cache_mngt_cache_purge_sync(cache, _cache_read_unlock_put_cmpl);

	return result;
}

int cache_mngt_flush_device(const char *cache_name, size_t name_len)
{
	int result;
	ocf_cache_t cache;

	result = ocf_mngt_cache_get_by_name(cas_ctx, cache_name,
					name_len, &cache);
	if (result)
		return result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result) {
		ocf_mngt_cache_put(cache);
		return result;
	}

	result = _cache_mngt_cache_flush_sync(cache, true,
			_cache_read_unlock_put_cmpl);

	return result;
}

struct cache_mngt_set_cleaning_policy_context {
	struct completion cmpl;
	int *result;
};

static void cache_mngt_set_cleaning_policy_cmpl(void *priv, int error)
{
	struct cache_mngt_set_cleaning_policy_context *context = priv;

	*context->result = error;

	complete(&context->cmpl);
}

int cache_mngt_set_cleaning_policy(ocf_cache_t cache, uint32_t type)
{
	struct cache_mngt_set_cleaning_policy_context context;
	int result;

	result = _cache_mngt_lock_sync(cache);
	if (result)
		return result;

	init_completion(&context.cmpl);
	context.result = &result;

	ocf_mngt_cache_cleaning_set_policy(cache, type,
			cache_mngt_set_cleaning_policy_cmpl, &context);
	wait_for_completion(&context.cmpl);

	ocf_mngt_cache_unlock(cache);
	return result;
}

int cache_mngt_get_cleaning_policy(ocf_cache_t cache, uint32_t *type)
{
	ocf_cleaning_t tmp_type;
	int result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result)
		return result;

	result = ocf_mngt_cache_cleaning_get_policy(cache, &tmp_type);

	if (result == 0)
		*type = tmp_type;

	ocf_mngt_cache_read_unlock(cache);
	return result;
}

int cache_mngt_set_cleaning_param(ocf_cache_t cache, ocf_cleaning_t type,
		uint32_t param_id, uint32_t param_value)
{
	int result;

	result = _cache_mngt_lock_sync(cache);
	if (result)
		return result;

	result = ocf_mngt_cache_cleaning_set_param(cache, type,
			param_id, param_value);
	if (result)
		goto out;

	result = _cache_mngt_save_sync(cache);

out:
	ocf_mngt_cache_unlock(cache);
	return result;
}

int cache_mngt_get_cleaning_param(ocf_cache_t cache, ocf_cleaning_t type,
		uint32_t param_id, uint32_t *param_value)
{
	int result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result)
		return result;

	result = ocf_mngt_cache_cleaning_get_param(cache, type,
			param_id, param_value);

	ocf_mngt_cache_read_unlock(cache);
	return result;
}

int cache_mngt_set_promotion_policy(ocf_cache_t cache, uint32_t type)
{
	int result;

	result = _cache_mngt_lock_sync(cache);
	if (result) {
		return result;
	}

	result = ocf_mngt_cache_promotion_set_policy(cache, type);
	if (result)
		goto out;

	result = _cache_mngt_save_sync(cache);

out:
	ocf_mngt_cache_unlock(cache);
	return result;
}

int cache_mngt_get_promotion_policy(ocf_cache_t cache, uint32_t *type)
{
	int result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result) {
		return result;
	}

	*type = ocf_mngt_cache_promotion_get_policy(cache);

	ocf_mngt_cache_read_unlock(cache);
	return result;
}

int cache_mngt_set_promotion_param(ocf_cache_t cache, ocf_promotion_t type,
		uint32_t param_id, uint32_t param_value)
{
	int result;

	result = _cache_mngt_lock_sync(cache);
	if (result) {
		return result;
	}

	result = ocf_mngt_cache_promotion_set_param(cache, type, param_id,
			param_value);

	ocf_mngt_cache_unlock(cache);
	return result;
}

int cache_mngt_get_promotion_param(ocf_cache_t cache, ocf_promotion_t type,
		uint32_t param_id, uint32_t *param_value)
{
	int result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result) {
		return result;
	}

	result = ocf_mngt_cache_promotion_get_param(cache, type, param_id,
			param_value);

	ocf_mngt_cache_read_unlock(cache);
	return result;
}

struct get_paths_ctx {
	char *core_path_name_tab;
	int max_count;
	int position;
};

int _cache_mngt_core_pool_get_paths_visitor(ocf_uuid_t uuid, void *ctx)
{
	struct get_paths_ctx *visitor_ctx = ctx;

	if (visitor_ctx->position >= visitor_ctx->max_count)
		return 0;

	if (copy_to_user((void __user *)visitor_ctx->core_path_name_tab +
			(visitor_ctx->position * MAX_STR_LEN),
			uuid->data, uuid->size)) {
		return -ENODATA;
	}

	visitor_ctx->position++;

	return 0;
}

int cache_mngt_core_pool_get_paths(struct kcas_core_pool_path *cmd_info)
{
	struct get_paths_ctx visitor_ctx = {0};
	int result;

	visitor_ctx.core_path_name_tab = cmd_info->core_path_tab;
	visitor_ctx.max_count = cmd_info->core_pool_count;

	result = ocf_mngt_core_pool_visit(cas_ctx,
			_cache_mngt_core_pool_get_paths_visitor,
			&visitor_ctx);

	cmd_info->core_pool_count = visitor_ctx.position;
	return result;
}

int cache_mngt_core_pool_remove(struct kcas_core_pool_remove *cmd_info)
{
	struct ocf_volume_uuid uuid;
	ocf_volume_t vol;

	uuid.data = cmd_info->core_path_name;
	uuid.size = strnlen(cmd_info->core_path_name, MAX_STR_LEN);

	vol = ocf_mngt_core_pool_lookup(cas_ctx, &uuid,
			ocf_ctx_get_volume_type(cas_ctx,
					BLOCK_DEVICE_VOLUME));
	if (!vol)
		return -OCF_ERR_CORE_NOT_AVAIL;

	ocf_volume_close(vol);
	ocf_mngt_core_pool_remove(cas_ctx, vol);

	return 0;
}

struct cache_mngt_metadata_probe_context {
	struct completion cmpl;
	struct kcas_cache_check_device *cmd_info;
	int *result;
};

static void cache_mngt_metadata_probe_end(void *priv, int error,
		struct ocf_metadata_probe_status *status)
{
	struct cache_mngt_metadata_probe_context *context = priv;
	struct kcas_cache_check_device *cmd_info = context->cmd_info;

	*context->result = error;

	if (error == -OCF_ERR_NO_METADATA) {
		cmd_info->is_cache_device = false;
		cmd_info->metadata_compatible = false;
		*context->result = 0;
	} else if (error == -OCF_ERR_METADATA_VER || error == 0) {
		cmd_info->is_cache_device = true;
		cmd_info->metadata_compatible = !error;
		cmd_info->clean_shutdown = status->clean_shutdown;
		cmd_info->cache_dirty = status->cache_dirty;
		*context->result = 0;
	}

	complete(&context->cmpl);
}

int cache_mngt_cache_check_device(struct kcas_cache_check_device *cmd_info)
{
	struct cache_mngt_metadata_probe_context context;
	struct block_device *bdev;
	ocf_volume_t volume;
	char holder[] = "CAS CHECK CACHE DEVICE\n";
	int result;

	bdev = blkdev_get_by_path(cmd_info->path_name, (FMODE_EXCL|FMODE_READ),
			holder);
	if (IS_ERR(bdev)) {
		return (PTR_ERR(bdev) == -EBUSY) ?
				-OCF_ERR_NOT_OPEN_EXC :
				-OCF_ERR_INVAL_VOLUME_TYPE;
	}

	result = cas_blk_open_volume_by_bdev(&volume, bdev);
	if (result)
		goto out_bdev;

	init_completion(&context.cmpl);
	context.cmd_info = cmd_info;
	context.result = &result;

	ocf_metadata_probe(cas_ctx, volume, cache_mngt_metadata_probe_end,
			&context);
	wait_for_completion(&context.cmpl);

	cas_blk_close_volume(volume);
out_bdev:
	blkdev_put(bdev, (FMODE_EXCL|FMODE_READ));
	return result;
}

int cache_mngt_prepare_core_cfg(struct ocf_mngt_core_config *cfg,
		struct kcas_insert_core *cmd_info)
{
	char core_name[OCF_CORE_NAME_SIZE] = {};
	ocf_cache_t cache;
	uint16_t core_id;
	int result;

	if (strnlen(cmd_info->core_path_name, MAX_STR_LEN) >= MAX_STR_LEN)
		return -OCF_ERR_INVAL;

	if (cmd_info->core_id == OCF_CORE_MAX) {
		result = mngt_get_cache_by_id(cas_ctx, cmd_info->cache_id,
				&cache);
		if (result && result != -OCF_ERR_CACHE_NOT_EXIST) {
			return result;
		} else if (!result) {
			struct cache_priv *cache_priv;
			cache_priv = ocf_cache_get_priv(cache);
			ocf_mngt_cache_put(cache);

			core_id = find_free_core_id(cache_priv->core_id_bitmap);
			if (core_id == OCF_CORE_MAX)
				return -OCF_ERR_INVAL;

			cmd_info->core_id = core_id;
		}
	}

	snprintf(core_name, sizeof(core_name), "core%d", cmd_info->core_id);

	memset(cfg, 0, sizeof(*cfg));
	env_strncpy(cfg->name, OCF_CORE_NAME_SIZE, core_name, OCF_CORE_NAME_SIZE);

	cfg->uuid.data = cmd_info->core_path_name;
	cfg->uuid.size = strnlen(cmd_info->core_path_name, MAX_STR_LEN) + 1;
	cfg->try_add = cmd_info->try_add;

	if (!cas_bdev_exist(cfg->uuid.data))
		return -OCF_ERR_INVAL_VOLUME_TYPE;

	if (cmd_info->update_path)
		return 0;

	result = cas_blk_identify_type(cfg->uuid.data, &cfg->volume_type);
	if (OCF_ERR_NOT_OPEN_EXC == abs(result)) {
		printk(KERN_WARNING OCF_PREFIX_SHORT
			"Cannot open device %s exclusively. "
		        "It is already opened by another program!\n",
			cmd_info->core_path_name);
	}

	return result;
}

static int cache_mngt_update_core_uuid(ocf_cache_t cache, const char *core_name,
				size_t name_len, ocf_uuid_t uuid)
{
	ocf_core_t core;
	ocf_volume_t vol;
	struct bd_object *bdvol;
	int result;

	if (ocf_core_get_by_name(cache, core_name, name_len, &core)) {
		/* no such core */
		return -ENODEV;
	}

	if (ocf_core_get_state(core) != ocf_core_state_active) {
		/* core inactive */
		return -ENODEV;
	}

	/* get bottom device volume for this core */
	vol = ocf_core_get_volume(core);
	bdvol = bd_object(vol);

	if (!cas_bdev_match(uuid->data, bdvol->btm_bd)) {
		printk(KERN_ERR "UUID provided does not match target core device\n");
		return -ENODEV;
	}

	result = ocf_mngt_core_set_uuid(core, uuid);
	if (result)
		return result;

	return _cache_mngt_save_sync(cache);
}

static void _cache_mngt_log_core_device_path(ocf_core_t core)
{
	ocf_cache_t cache = ocf_core_get_cache(core);
	const ocf_uuid_t core_uuid = (const ocf_uuid_t)ocf_core_get_uuid(core);

	printk(KERN_INFO OCF_PREFIX_SHORT "Adding device %s as core %s "
			"to cache %s\n", (const char*)core_uuid->data,
			ocf_core_get_name(core), ocf_cache_get_name(cache));
}

static int _cache_mngt_core_device_loaded_visitor(ocf_core_t core, void *cntx)
{
	uint16_t core_id = OCF_CORE_ID_INVALID;
	ocf_cache_t cache = ocf_core_get_cache(core);

	_cache_mngt_log_core_device_path(core);

	core_id_from_name(&core_id, ocf_core_get_name(core));

	mark_core_id_used(cache, core_id);

	return 0;
}

struct _cache_mngt_add_core_context {
	struct completion cmpl;
	ocf_core_t *core;
	int *result;
};

/************************************************************
 * Function for adding a CORE object to the cache instance. *
 ************************************************************/

static void _cache_mngt_add_core_complete(ocf_cache_t cache,
		ocf_core_t core, void *priv, int error)
{
	struct _cache_mngt_add_core_context *context = priv;

	*context->core = core;
	*context->result = error;
	complete(&context->cmpl);
}

static void _cache_mngt_generic_complete(void *priv, int error);

int cache_mngt_add_core_to_cache(const char *cache_name, size_t name_len,
		struct ocf_mngt_core_config *cfg,
		struct kcas_insert_core *cmd_info)
{
	struct _cache_mngt_add_core_context add_context;
	struct _cache_mngt_sync_context remove_context;
	ocf_cache_t cache;
	ocf_core_t core;
	ocf_core_id_t core_id;
	int result, remove_core_result;

	result = ocf_mngt_cache_get_by_name(cas_ctx, cache_name,
					name_len, &cache);
	if (cfg->try_add && (result == -OCF_ERR_CACHE_NOT_EXIST)) {
		result = ocf_mngt_core_pool_add(cas_ctx, &cfg->uuid,
				cfg->volume_type);
		if (result) {
			cmd_info->ext_err_code =
					-OCF_ERR_CANNOT_ADD_CORE_TO_POOL;
			printk(KERN_ERR OCF_PREFIX_SHORT
					"Error occurred during"
					" adding core to detached core pool\n");
		} else {
			printk(KERN_INFO OCF_PREFIX_SHORT
					"Successfully added"
					" core to core pool\n");
		}
		return result;
	} else if (result) {
		return result;
	}

	result = _cache_mngt_lock_sync(cache);
	if (result) {
		ocf_mngt_cache_put(cache);
		return result;
	}

	if (cmd_info && cmd_info->update_path) {
		result = cache_mngt_update_core_uuid(cache, cfg->name,
						OCF_CORE_NAME_SIZE, &cfg->uuid);
		ocf_mngt_cache_unlock(cache);
		ocf_mngt_cache_put(cache);
		return result;
	}

	cfg->seq_cutoff_threshold = seq_cut_off_mb * MiB;
	cfg->seq_cutoff_promotion_count = 8;

	init_completion(&add_context.cmpl);
	add_context.core = &core;
	add_context.result = &result;

	ocf_mngt_cache_add_core(cache, cfg, _cache_mngt_add_core_complete,
			&add_context);
	wait_for_completion(&add_context.cmpl);
	if (result)
		goto error_affter_lock;

	result = kcas_core_create_exported_object(core);
	if (result)
		goto error_after_add_core;

	result = kcas_core_activate_exported_object(core);
	if (result)
		goto error_after_create_exported_object;

	result = core_id_from_name(&core_id, cfg->name);
	if (result)
		goto error_after_create_exported_object;

	mark_core_id_used(cache, core_id);

	ocf_mngt_cache_unlock(cache);
	ocf_mngt_cache_put(cache);

	_cache_mngt_log_core_device_path(core);

	return 0;

error_after_create_exported_object:
	kcas_core_destroy_exported_object(core);

error_after_add_core:
	init_completion(&remove_context.cmpl);
	remove_context.result = &remove_core_result;
	ocf_mngt_cache_remove_core(core, _cache_mngt_generic_complete,
			&remove_context);
	wait_for_completion(&remove_context.cmpl);

error_affter_lock:
	ocf_mngt_cache_unlock(cache);
	ocf_mngt_cache_put(cache);

	return result;
}

static int _cache_mngt_remove_core_flush(ocf_cache_t cache,
		struct kcas_remove_core *cmd)
{
	int result = 0;
	ocf_core_t core;
	bool core_active;

	if (cmd->force_no_flush)
		return 0;

	/* Getting cache for the second time is workaround to make flush error
	   handling easier and avoid dealing with synchronizing issues */
	result = ocf_mngt_cache_get(cache);
	if (result)
		return result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result)
		goto put;

	result = get_core_by_id(cache, cmd->core_id, &core);
	if (result < 0)
		goto unlock;

	core_active = (ocf_core_get_state(core) == ocf_core_state_active);

	if (!core_active) {
		result = -OCF_ERR_CORE_IN_INACTIVE_STATE;
		goto unlock;
	}

	if (!ocf_mngt_core_is_dirty(core)) {
		result = 0;
		goto unlock;
	}

	return _cache_mngt_core_flush_sync(core, true,
				_cache_read_unlock_put_cmpl);

unlock:
	ocf_mngt_cache_read_unlock(cache);
put:
	ocf_mngt_cache_put(cache);
	return result;
}

static void _cache_mngt_generic_complete(void *priv, int error)
{
	struct _cache_mngt_sync_context *context = priv;

	*context->result = error;
	complete(&context->cmpl);
}

static void _cache_mngt_remove_core_fallback(ocf_cache_t cache, ocf_core_t core)
{
	struct _cache_mngt_sync_context context;
	int result;

	printk(KERN_ERR "Removing core failed. Detaching %s.%s\n",
			ocf_cache_get_name(cache),
			ocf_core_get_name(core));

	init_completion(&context.cmpl);
	context.result = &result;

	ocf_mngt_cache_detach_core(core,
			_cache_mngt_generic_complete, &context);

	wait_for_completion(&context.cmpl);

	if (!result)
		return;

	printk(KERN_ERR "Detaching %s.%s\n failed. Please retry the remove operation",
			ocf_cache_get_name(cache),
			ocf_core_get_name(core));
}

static int _cache_mngt_remove_core_prepare(ocf_cache_t cache, ocf_core_t core,
		struct kcas_remove_core *cmd)
{
	int result = 0;
	bool core_active;

	core_active = ocf_core_get_state(core) == ocf_core_state_active;

	if (!core_active)
		return -OCF_ERR_CORE_IN_INACTIVE_STATE;

	result = kcas_core_destroy_exported_object(core);
	if (result)
		return result;

	if (cmd->force_no_flush)
		return 0;

	result = _cache_mngt_core_flush_uninterruptible(core);

	if (!result)
		return 0;

	_cache_mngt_remove_core_fallback(cache, core);

	return -KCAS_ERR_DETACHED;
}

int cache_mngt_remove_core_from_cache(struct kcas_remove_core *cmd)
{
	struct _cache_mngt_sync_context context;
	int result;
	ocf_cache_t cache;
	ocf_core_t core;

	result = mngt_get_cache_by_id(cas_ctx, cmd->cache_id, &cache);
	if (result)
		return result;

	result = _cache_mngt_remove_core_flush(cache, cmd);
	if (result)
		goto put;

	result = _cache_mngt_lock_sync(cache);
	if (result)
		goto put;

	result = get_core_by_id(cache, cmd->core_id, &core);
	if (result < 0) {
		goto unlock;
	}

	result = _cache_mngt_remove_core_prepare(cache, core, cmd);
	if (result)
		goto unlock;

	init_completion(&context.cmpl);
	context.result = &result;

	if (cmd->detach) {
		ocf_mngt_cache_detach_core(core,
				_cache_mngt_generic_complete, &context);
	} else {
		ocf_mngt_cache_remove_core(core,
				_cache_mngt_generic_complete, &context);
	}

	wait_for_completion(&context.cmpl);

	if (!result && !cmd->detach)
		mark_core_id_free(cache, cmd->core_id);

unlock:
	ocf_mngt_cache_unlock(cache);
put:
	ocf_mngt_cache_put(cache);
	return result;
}

int cache_mngt_remove_inactive_core(struct kcas_remove_inactive *cmd)
{
	struct _cache_mngt_sync_context context;
	int result = 0;
	ocf_cache_t cache;
	ocf_core_t core;

	result = mngt_get_cache_by_id(cas_ctx, cmd->cache_id, &cache);
	if (result)
		return result;

	result = _cache_mngt_lock_sync(cache);
	if (result)
		goto put;

	result = get_core_by_id(cache, cmd->core_id, &core);
	if (result < 0) {
		goto unlock;
	}

	result = (ocf_core_get_state(core) == ocf_core_state_active);
	if (result) {
		result = -KCAS_ERR_CORE_IN_ACTIVE_STATE;
		goto unlock;
	}

	if (ocf_mngt_core_is_dirty(core) && !cmd->force) {
		result = -KCAS_ERR_INACTIVE_CORE_IS_DIRTY;
		goto unlock;
	}

	/*
	 * Destroy exported object - in case of error during destruction of
	 * exported object, instead of trying rolling this back we rather
	 * inform user about error.
	 */
	result = kcas_core_destroy_exported_object(core);
	if (result)
		goto unlock;

	init_completion(&context.cmpl);
	context.result = &result;

	ocf_mngt_cache_remove_core(core, _cache_mngt_generic_complete,
			&context);

	wait_for_completion(&context.cmpl);

	if (!result) {
		mark_core_id_free(cache, cmd->core_id);
	}

unlock:
	ocf_mngt_cache_unlock(cache);
put:
	ocf_mngt_cache_put(cache);
	return result;
}

int cache_mngt_reset_stats(const char *cache_name, size_t cache_name_len,
				const char *core_name, size_t core_name_len)
{
	ocf_cache_t cache;
	ocf_core_t core;
	int result = 0;

	result = ocf_mngt_cache_get_by_name(cas_ctx, cache_name, cache_name_len,
						&cache);
	if (result)
		return result;

	result = _cache_mngt_lock_sync(cache);
	if (result) {
		ocf_mngt_cache_put(cache);
		return result;
	}

	if (core_name) {
		result = ocf_core_get_by_name(cache, core_name,
					core_name_len, &core);
		if (result)
			goto out;

		ocf_core_stats_initialize(core);
	} else {
		ocf_core_stats_initialize_all(cache);
	}

out:
	ocf_mngt_cache_unlock(cache);
	ocf_mngt_cache_put(cache);
	return result;
}

static inline void io_class_info2cfg(ocf_part_id_t part_id,
		struct ocf_io_class_info *info, struct ocf_mngt_io_class_config *cfg)
{
	cfg->class_id = part_id;
	cfg->name = info->name;
	cfg->prio = info->priority;
	cfg->cache_mode = info->cache_mode;
	cfg->max_size = info->max_size;
}

int cache_mngt_set_partitions(const char *cache_name, size_t name_len,
		struct kcas_io_classes *cfg)
{
	ocf_cache_t cache;
	struct ocf_mngt_io_classes_config *io_class_cfg;
	struct cas_cls_rule *cls_rule[OCF_USER_IO_CLASS_MAX];
	ocf_part_id_t class_id;
	int result;

	io_class_cfg = kzalloc(sizeof(struct ocf_mngt_io_class_config) *
			OCF_USER_IO_CLASS_MAX, GFP_KERNEL);
	if (!io_class_cfg)
		return -OCF_ERR_NO_MEM;

	for (class_id = 0; class_id < OCF_USER_IO_CLASS_MAX; class_id++) {
		io_class_cfg->config[class_id].class_id = class_id;

		if (!cfg->info[class_id].name[0]) {
			io_class_cfg->config[class_id].class_id = class_id;
			continue;
		}

		io_class_info2cfg(class_id, &cfg->info[class_id],
				&io_class_cfg->config[class_id]);
	}

	result = ocf_mngt_cache_get_by_name(cas_ctx, cache_name,
					name_len, &cache);
	if (result)
		goto out_get;

	for (class_id = 0; class_id < OCF_USER_IO_CLASS_MAX; class_id++) {
		result = cas_cls_rule_create(cache, class_id,
				cfg->info[class_id].name,
				&cls_rule[class_id]);
		if (result)
			goto out_cls;
	}

	result = _cache_mngt_lock_sync(cache);
	if (result)
		goto out_cls;

	result = ocf_mngt_cache_io_classes_configure(cache, io_class_cfg);
	if (result == -OCF_ERR_IO_CLASS_NOT_EXIST)
		result = 0;
	if(result)
		goto out_configure;

	result = _cache_mngt_save_sync(cache);
	if (result)
		goto out_configure;

	for (class_id = 0; class_id < OCF_USER_IO_CLASS_MAX; class_id++)
		cas_cls_rule_apply(cache, class_id, cls_rule[class_id]);

out_configure:
	ocf_mngt_cache_unlock(cache);
out_cls:
	if (result) {
		while (class_id--)
			cas_cls_rule_destroy(cache, cls_rule[class_id]);
	}
	ocf_mngt_cache_put(cache);
out_get:
	kfree(io_class_cfg);
	return result;
}

static int _cache_mngt_create_core_exp_obj(ocf_core_t core, void *cntx)
{
	int result;

	result = kcas_core_create_exported_object(core);
	if (result)
		return result;

	result = kcas_core_activate_exported_object(core);

	return result;
}

static int _cache_mngt_destroy_core_exp_obj(ocf_core_t core, void *cntx)
{
	if (kcas_core_destroy_exported_object(core)) {
		ocf_cache_t cache = ocf_core_get_cache(core);

		printk(KERN_ERR "Cannot to destroy exported object, %s.%s\n",
				ocf_cache_get_name(cache),
				ocf_core_get_name(core));
	}

	return 0;
}

static int cache_mngt_initialize_core_exported_objects(ocf_cache_t cache)
{
	int result;

	result = ocf_core_visit(cache, _cache_mngt_create_core_exp_obj, NULL,
			true);
	if (result) {
		/* Need to cleanup */
		ocf_core_visit(cache, _cache_mngt_destroy_core_exp_obj, NULL,
				true);
	}

	return result;
}

static int cache_mngt_destroy_cache_exp_obj(ocf_cache_t cache)
{
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);
	int ret;

	if (!cache_priv->cache_exp_obj_initialized)
		return 0;

	ret = kcas_cache_destroy_exported_object(cache);

	if (ret) {
		printk(KERN_ERR "Cannot destroy %s exported object\n",
				ocf_cache_get_name(cache));
	} else {
		cache_priv->cache_exp_obj_initialized = false;
	}

	return ret;
}

static int cache_mngt_initialize_cache_exported_object(ocf_cache_t cache)
{
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);
	int result;

	result = kcas_cache_create_exported_object(cache);
	if (result)
		return result;

	result = kcas_cache_activate_exported_object(cache);
	if (result) {
		cache_mngt_destroy_cache_exp_obj(cache);
		return result;
	}

	cache_priv->cache_exp_obj_initialized = true;

	return 0;
}

int cache_mngt_prepare_cache_device_cfg(struct ocf_mngt_cache_device_config *cfg,
		char *cache_path)
{
	int result = 0;

	memset(cfg, 0, sizeof(*cfg));

	if (strnlen(cache_path, MAX_STR_LEN) == MAX_STR_LEN)
		return -OCF_ERR_INVAL;

	cfg->uuid.data = cache_path;
	cfg->uuid.size = strnlen(cfg->uuid.data, MAX_STR_LEN) + 1;
	cfg->perform_test = false;

	if (cfg->uuid.size == 1) {
		// empty string means empty uuid
		cfg->uuid.size = 0;
		return 0;
	}

	if (cfg->uuid.size > 1) {
		result = cas_blk_identify_type(cfg->uuid.data,
			&cfg->volume_type);
	}

	return result;
}


int cache_mngt_prepare_cache_cfg(struct ocf_mngt_cache_config *cfg,
		struct ocf_mngt_cache_attach_config *attach_cfg,
		struct kcas_start_cache *cmd)
{
	int init_cache, result;
	char cache_name[OCF_CACHE_NAME_SIZE];
	uint16_t cache_id;

	if (!cmd)
		return -OCF_ERR_INVAL;

	if (cmd->cache_id == OCF_CACHE_ID_INVALID) {
		cache_id = find_free_cache_id(cas_ctx);
		if (cache_id == OCF_CACHE_ID_INVALID)
			return -OCF_ERR_INVAL;

		cmd->cache_id = cache_id;
	}

	cache_name_from_id(cache_name, cmd->cache_id);

	memset(cfg, 0, sizeof(*cfg));
	memset(attach_cfg, 0, sizeof(*attach_cfg));

	result = cache_mngt_prepare_cache_device_cfg(&attach_cfg->device,
			cmd->cache_path_name);
	if (result)
		return result;

	if (attach_cfg->device.uuid.size <= 1)
		return -OCF_ERR_INVAL;

	strncpy(cfg->name, cache_name, OCF_CACHE_NAME_SIZE - 1);
	cfg->cache_mode = cmd->caching_mode;
	cfg->cache_line_size = cmd->line_size;
	cfg->promotion_policy = ocf_promotion_default;
	cfg->cleaning_policy = cmd->cleaning_policy_type;
	cfg->cache_line_size = cmd->line_size;
	cfg->pt_unaligned_io = !unaligned_io;
	cfg->use_submit_io_fast = !use_io_scheduler;
	cfg->locked = true;
	cfg->metadata_volatile = false;
	cfg->metadata_layout = metadata_layout;

	cfg->backfill.max_queue_size = max_writeback_queue_size;
	cfg->backfill.queue_unblock_size = writeback_queue_unblock_size;
	attach_cfg->cache_line_size = cmd->line_size;
	attach_cfg->force = cmd->force;
	attach_cfg->discard_on_start = true;

	init_cache = cmd->init_cache;

	switch (init_cache) {
	case CACHE_INIT_LOAD:
		attach_cfg->open_cores = true;
	case CACHE_INIT_NEW:
	case CACHE_INIT_STANDBY:
		break;
	default:
		return -OCF_ERR_INVAL;
	}


	return 0;
}

static void _cache_mngt_log_cache_device_path(ocf_cache_t cache,
		struct ocf_mngt_cache_device_config *device_cfg)
{
	printk(KERN_INFO OCF_PREFIX_SHORT "Adding device %s as cache %s\n",
			(const char*)device_cfg->uuid.data,
			ocf_cache_get_name(cache));
}

static void _cas_queue_kick(ocf_queue_t q)
{
	return cas_kick_queue_thread(q);
}

static void _cas_queue_stop(ocf_queue_t q)
{
	return cas_stop_queue_thread(q);
}


const struct ocf_queue_ops queue_ops = {
	.kick = _cas_queue_kick,
	.stop = _cas_queue_stop,
};

static int _cache_mngt_start_queues(ocf_cache_t cache)
{
	uint32_t cpus_no = num_online_cpus();
	struct cache_priv *cache_priv;
	int result, i;

	cache_priv = ocf_cache_get_priv(cache);

	for (i = 0; i < cpus_no; i++) {
		result = ocf_queue_create(cache, &cache_priv->io_queues[i],
				&queue_ops);
		if (result)
			goto err;

		result = cas_create_queue_thread(cache_priv->io_queues[i], i);
		if (result) {
			ocf_queue_put(cache_priv->io_queues[i]);
			goto err;
		}
	}

	result = ocf_queue_create(cache, &cache_priv->mngt_queue, &queue_ops);
	if (result)
		goto err;

	result = cas_create_queue_thread(cache_priv->mngt_queue, CAS_CPUS_ALL);
	if (result) {
		ocf_queue_put(cache_priv->mngt_queue);
		goto err;
	}

	ocf_mngt_cache_set_mngt_queue(cache, cache_priv->mngt_queue);

	return 0;
err:
	while (--i >= 0)
		ocf_queue_put(cache_priv->io_queues[i]);

	return result;
}

static void init_instance_complete(struct _cache_mngt_attach_context *ctx,
		ocf_cache_t cache)
{
	ocf_volume_t cache_obj;
	struct bd_object *bd_cache_obj;
	struct block_device *bdev;
	const char *name;

	cache_obj = ocf_cache_get_volume(cache);
	BUG_ON(!cache_obj);

	bd_cache_obj = bd_object(cache_obj);
	bdev = bd_cache_obj->btm_bd;

	/* If we deal with whole device, reread partitions */
	if (cas_bdev_whole(bdev) == bdev)
		cas_reread_partitions(bdev);

	/* Set other back information */
	name = block_dev_get_elevator_name(
			casdsk_disk_get_queue(bd_cache_obj->dsk));
	if (name)
		strlcpy(ctx->cache_elevator, name, MAX_ELEVATOR_NAME);
}

static void _cache_mngt_start_complete(ocf_cache_t cache, void *priv, int error)
{
	struct _cache_mngt_attach_context *ctx = priv;
	int caller_status;

	if (error == -OCF_ERR_NO_FREE_RAM) {
		ocf_mngt_get_ram_needed(cache, ctx->device_cfg,
				&ctx->min_free_ram);
	}

	caller_status =_cache_mngt_async_callee_set_result(&ctx->async, error);
	if (caller_status == -KCAS_ERR_WAITING_INTERRUPTED) {
		/* Attach/load was interrupted. Rollback asynchronously. */
		if (!error) {
			printk(KERN_WARNING "Cache added successfully, "
					"but waiting interrupted. Rollback\n");
		}
		ctx->ocf_start_error = error;
		ocf_mngt_cache_stop(cache,
				_cache_mngt_cache_stop_rollback_complete, ctx);
	}
}

static int _cache_mngt_cache_priv_init(ocf_cache_t cache)
{
	struct cache_priv *cache_priv;
	uint32_t cpus_no = num_online_cpus();

	cache_priv = vzalloc(sizeof(*cache_priv) +
			cpus_no * sizeof(*cache_priv->io_queues));
	if (!cache_priv)
		return -ENOMEM;

	cache_priv->stop_context =
		env_malloc(sizeof(*cache_priv->stop_context), GFP_KERNEL);
	if (!cache_priv->stop_context) {
		vfree(cache_priv);
		return -ENOMEM;
	}

	atomic_set(&cache_priv->flush_interrupt_enabled, 1);

	ocf_cache_set_priv(cache, cache_priv);

	return 0;
}

struct cache_mngt_check_metadata_context {
	struct completion cmpl;
	char *cache_name;
	int *result;
};

static void cache_mngt_check_metadata_end(void *priv, int error,
		struct ocf_metadata_probe_status *status)
{
	struct cache_mngt_check_metadata_context *context = priv;

	*context->result = error;

	if (error == -OCF_ERR_NO_METADATA) {
		printk(KERN_ERR "No cache metadata found!\n");
	} else if (error == -OCF_ERR_METADATA_VER) {
		printk(KERN_ERR "Cache metadata version mismatch\n");
	} else if (error) {
		printk(KERN_ERR "Failed to load cache metadata!\n");
	} else if (strncmp(status->cache_name, context->cache_name,
			OCF_CACHE_NAME_SIZE)) {
		*context->result = -OCF_ERR_CACHE_NAME_MISMATCH;
		printk(KERN_ERR "Loaded cache name is invalid: %s!\n",
				status->cache_name);
	}

	complete(&context->cmpl);
}

static int _cache_mngt_check_metadata(struct ocf_mngt_cache_config *cfg,
		char *cache_path_name)
{
	struct cache_mngt_check_metadata_context context;
	struct block_device *bdev;
	ocf_volume_t volume;
	char holder[] = "CAS CHECK METADATA\n";
	int result;

	bdev = blkdev_get_by_path(cache_path_name, (FMODE_EXCL|FMODE_READ),
			holder);
	if (IS_ERR(bdev)) {
		return (PTR_ERR(bdev) == -EBUSY) ?
			-OCF_ERR_NOT_OPEN_EXC :
			-OCF_ERR_INVAL_VOLUME_TYPE;
	}

	result = cas_blk_open_volume_by_bdev(&volume, bdev);
	if (result)
		goto out_bdev;

	init_completion(&context.cmpl);
	context.cache_name = cfg->name;
	context.result = &result;

	ocf_metadata_probe(cas_ctx, volume, cache_mngt_check_metadata_end,
			&context);
	wait_for_completion(&context.cmpl);

	cas_blk_close_volume(volume);
out_bdev:
	blkdev_put(bdev, (FMODE_EXCL|FMODE_READ));
	return result;
}

static int _cache_start_finalize(ocf_cache_t cache, int init_mode,
		bool activate)
{
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);
	struct _cache_mngt_attach_context *ctx = cache_priv->attach_context;
	int result;

	_cache_mngt_log_cache_device_path(cache, ctx->device_cfg);

	if (activate || init_mode != CACHE_INIT_STANDBY) {
		result = cas_cls_init(cache);
		if (result) {
			ctx->ocf_start_error = result;
			return result;
		}
		ctx->cls_inited = true;
	}

	if (activate)
		cache_mngt_destroy_cache_exp_obj(cache);

	/* after destroying exported object activate should follow
	 * load path */
	init_mode = activate ? CACHE_INIT_LOAD : init_mode;

	switch(init_mode) {
	case CACHE_INIT_LOAD:
		result = cache_mngt_initialize_core_exported_objects(cache);
		if (result) {
			ctx->ocf_start_error = result;
			return result;
		}
		ocf_core_visit(cache, _cache_mngt_core_device_loaded_visitor,
				NULL, false);
		break;
	case CACHE_INIT_STANDBY:
		result = cache_mngt_initialize_cache_exported_object(cache);
		if (result) {
			ctx->ocf_start_error = result;
			return result;
		}
		break;
	case CACHE_INIT_NEW:
		break;
	default:
		BUG();
	}

	init_instance_complete(ctx, cache);

	return 0;
}

int cache_mngt_check_bdev(struct ocf_mngt_cache_device_config *device_cfg,
		bool force)
{
	char holder[] = "CAS START\n";
	struct block_device *bdev;
	int part_count;
	bool is_part;

	bdev = blkdev_get_by_path(device_cfg->uuid.data,
			(FMODE_EXCL|FMODE_READ), holder);
	if (IS_ERR(bdev)) {
		return (PTR_ERR(bdev) == -EBUSY) ?
				-OCF_ERR_NOT_OPEN_EXC :
				-OCF_ERR_INVAL_VOLUME_TYPE;
	}

	is_part = (cas_bdev_whole(bdev) != bdev);
	part_count = cas_blk_get_part_count(bdev);
	blkdev_put(bdev, (FMODE_EXCL|FMODE_READ));

	if (!is_part && part_count > 1 && !force)
		return -KCAS_ERR_CONTAINS_PART;

	return 0;
}

int cache_mngt_failover_detach(struct kcas_failover_detach *cmd)
{
	ocf_cache_t cache;
	struct cache_priv *cache_priv;
	char cache_name[OCF_CACHE_NAME_SIZE];
	int result = 0;
	struct _cache_mngt_sync_context context = {
		.result = &result
	};

	init_completion(&context.cmpl);

	if (!try_module_get(THIS_MODULE))
		return -KCAS_ERR_SYSTEM;

	cache_name_from_id(cache_name, cmd->cache_id);

	result = ocf_mngt_cache_get_by_name(cas_ctx, cache_name,
			OCF_CACHE_NAME_SIZE, &cache);
	if (result)
		goto out_module_put;

	if (!ocf_cache_is_standby(cache)) {
		result = -OCF_ERR_CACHE_EXIST;
		goto out_cache_put;
	}

	cache_priv = ocf_cache_get_priv(cache);
	if (!cache_priv->cache_exp_obj_initialized) {
		result = -KCAS_ERR_DETACHED;
		goto out_cache_put;
	}

	result = cache_mngt_destroy_cache_exp_obj(cache);
	if (result)
		goto out_cache_put;

	result = _cache_mngt_lock_sync(cache);
	if (result)
		goto out_cache_put;

	ocf_mngt_cache_failover_detach(cache, _cache_mngt_generic_complete,
			&context);

	wait_for_completion(&context.cmpl);
	ocf_mngt_cache_unlock(cache);

out_cache_put:
	ocf_mngt_cache_put(cache);
out_module_put:
	module_put(THIS_MODULE);
	return result;
}

int cache_mngt_activate(struct ocf_mngt_cache_device_config *cfg,
		struct kcas_failover_activate *cmd)
{
	struct _cache_mngt_attach_context *context;
	ocf_cache_t cache;
	struct cache_priv *cache_priv;
	ocf_volume_t cache_volume;
	const struct ocf_volume_uuid *cache_uuid;
	char cache_name[OCF_CACHE_NAME_SIZE];
	int result = 0;

	if (!try_module_get(THIS_MODULE))
		return -KCAS_ERR_SYSTEM;

	cache_name_from_id(cache_name, cmd->cache_id);

	result = ocf_mngt_cache_get_by_name(cas_ctx, cache_name,
			OCF_CACHE_NAME_SIZE, &cache);
	if (result)
		goto out_module_put;

	if (!ocf_cache_is_standby(cache)) {
		result = -OCF_ERR_CACHE_EXIST;
		goto out_cache_put;
	}

	result = _cache_mngt_lock_sync(cache);
	if (result)
		goto out_cache_put;

	if (strnlen(cmd->cache_path, MAX_STR_LEN) > 0) {
		cache_volume = ocf_cache_get_volume(cache);
		cache_uuid = ocf_volume_get_uuid(cache_volume);
		if (cache_uuid->size > 0 &&
				strcmp(cfg->uuid.data, cache_uuid->data)
				!= 0) {
			result = cache_mngt_check_bdev(cfg, false);
			if (result)
				goto out_cache_unlock;
		}
	}

	context = kzalloc(sizeof(*context), GFP_KERNEL);
	if (!context) {
		result = -ENOMEM;
		goto out_cache_unlock;
	}

	/* TODO: doesn't this need to be copied to avoid use-after-free
	 * in case where calle is interrupted and returns???
	 */
	context->device_cfg = cfg;
	context->cache = cache;

	cache_priv = ocf_cache_get_priv(cache);
	cache_priv->attach_context = context;

	context->rollback_thread = cas_lazy_thread_create(cache_start_rollback,
			context, "cas_cache_rollback_complete");
	if (IS_ERR(context->rollback_thread)) {
		result = PTR_ERR(context->rollback_thread);
		goto err_free_context;
	}
	_cache_mngt_async_context_init(&context->async);

	ocf_mngt_cache_activate(cache, cfg, _cache_mngt_start_complete,
			context);
	result = wait_for_completion_interruptible(&context->async.cmpl);

	result = _cache_mngt_async_caller_set_result(&context->async, result);
	if (result == -KCAS_ERR_WAITING_INTERRUPTED)
		goto out_cache_put;

	cas_lazy_thread_stop(context->rollback_thread);

	if (result)
		goto err_free_context;

	result = _cache_start_finalize(cache, -1, true);

err_free_context:
	kfree(context);
	cache_priv->attach_context = NULL;

out_cache_unlock:
	ocf_mngt_cache_unlock(cache);
out_cache_put:
	ocf_mngt_cache_put(cache);
out_module_put:
	module_put(THIS_MODULE);
	return result;
}

int cache_mngt_init_instance(struct ocf_mngt_cache_config *cfg,
		struct ocf_mngt_cache_attach_config *attach_cfg,
		struct kcas_start_cache *cmd)
{
	struct _cache_mngt_attach_context *context;
	ocf_cache_t cache;
	struct cache_priv *cache_priv;
	int result = 0, rollback_result = 0;

	if (!try_module_get(THIS_MODULE))
		return -KCAS_ERR_SYSTEM;

	result = cache_mngt_check_bdev(&attach_cfg->device, attach_cfg->force);
	if (result) {
		module_put(THIS_MODULE);
		return result;
	}

	if (cmd->init_cache == CACHE_INIT_LOAD)
		result = _cache_mngt_check_metadata(cfg, cmd->cache_path_name);
	if (result) {
		module_put(THIS_MODULE);
		return result;
	}

	context = kzalloc(sizeof(*context), GFP_KERNEL);
	if (!context) {
		module_put(THIS_MODULE);
		return -ENOMEM;
	}

	context->rollback_thread = cas_lazy_thread_create(cache_start_rollback,
			context, "cas_cache_rollback_complete");
	if (IS_ERR(context->rollback_thread)) {
		result = PTR_ERR(context->rollback_thread);
		kfree(context);
		module_put(THIS_MODULE);
		return result;
	}

	context->device_cfg = &attach_cfg->device;
	_cache_mngt_async_context_init(&context->async);

	/* Start cache. Returned cache instance will be locked as it was set
	 * in configuration.
	 */
	result = ocf_mngt_cache_start(cas_ctx, &cache, cfg, NULL);
	if (result) {
		cas_lazy_thread_stop(context->rollback_thread);
		kfree(context);
		module_put(THIS_MODULE);
		return result;
	}
	context->cache = cache;

	result = _cache_mngt_cache_priv_init(cache);
	if (result)
		goto err;
	context->priv_inited = true;

	result = _cache_mngt_start_queues(cache);
	if (result)
		goto err;

	cache_priv = ocf_cache_get_priv(cache);
	cache_priv->attach_context = context;

	switch (cmd->init_cache) {
	case CACHE_INIT_NEW:
		ocf_mngt_cache_attach(cache, attach_cfg,
				_cache_mngt_start_complete, context);
		break;
	case CACHE_INIT_LOAD:
		ocf_mngt_cache_load(cache, attach_cfg,
				_cache_mngt_start_complete, context);
		break;
	case CACHE_INIT_STANDBY:
		ocf_mngt_cache_standby(cache, attach_cfg,
				_cache_mngt_start_complete, context);
		break;
	default:
		result = -OCF_ERR_INVAL;
		goto err;
	}
	result = wait_for_completion_interruptible(&context->async.cmpl);

	result = _cache_mngt_async_caller_set_result(&context->async, result);
	if (result == -KCAS_ERR_WAITING_INTERRUPTED)
		return result;

	if (result)
		goto err;

	strlcpy(cmd->cache_elevator, context->cache_elevator,
			MAX_ELEVATOR_NAME);
	cmd->min_free_ram = context->min_free_ram;

	result = _cache_start_finalize(cache, cmd->init_cache, false);
	if (result)
		goto err;

	cas_lazy_thread_stop(context->rollback_thread);

	kfree(context);
	cache_priv->attach_context = NULL;

	ocf_mngt_cache_unlock(cache);

	return result;
err:
	_cache_mngt_async_context_init(&context->async);
	ocf_mngt_cache_stop(cache, _cache_mngt_cache_stop_rollback_complete,
			context);
	rollback_result = wait_for_completion_interruptible(&context->async.cmpl);

	rollback_result = _cache_mngt_async_caller_set_result(&context->async,
			rollback_result);

	if (rollback_result != -KCAS_ERR_WAITING_INTERRUPTED)
		kfree(context);

	return result;
}

/**
 * @brief routine implementing dynamic sequential cutoff parameter switching
 * @param[in] cache cache to which the change pertains
 * @param[in] core core to which the change pertains
 * or NULL for setting value for all cores attached to specified cache
 * @param[in] thresh new sequential cutoff threshold value
 * @return exit code of successful completion is 0;
 * nonzero exit code means failure
 */

int cache_mngt_set_seq_cutoff_threshold(ocf_cache_t cache, ocf_core_t core,
		uint32_t thresh)
{
	int result;

	result = _cache_mngt_lock_sync(cache);
	if (result)
		return result;

	if (core) {
		result = ocf_mngt_core_set_seq_cutoff_threshold(core, thresh);
	} else {
		result = ocf_mngt_core_set_seq_cutoff_threshold_all(cache,
				thresh);
	}

	if (result)
		goto out;

	result = _cache_mngt_save_sync(cache);

out:
	ocf_mngt_cache_unlock(cache);
	return result;
}

/**
 * @brief routine implementing dynamic sequential cutoff parameter switching
 * @param[in] cache cache to which the change pertains
 * @param[in] core core to which the change pertains
 * or NULL for setting value for all cores attached to specified cache
 * @param[in] policy new sequential cutoff policy value
 * @return exit code of successful completion is 0;
 * nonzero exit code means failure
 */

int cache_mngt_set_seq_cutoff_policy(ocf_cache_t cache, ocf_core_t core,
		ocf_seq_cutoff_policy policy)
{
	int result;

	result = _cache_mngt_lock_sync(cache);
	if (result)
		return result;

	if (core)
		result = ocf_mngt_core_set_seq_cutoff_policy(core, policy);
	else
		result = ocf_mngt_core_set_seq_cutoff_policy_all(cache, policy);

	if (result)
		goto out;

	result = _cache_mngt_save_sync(cache);

out:
	ocf_mngt_cache_unlock(cache);
	return result;
}

/**
 * @brief routine implementing dynamic sequential cutoff parameter switching
 * @param[in] cache cache to which the change pertains
 * @param[in] core core to which the change pertains
 * or NULL for setting value for all cores attached to specified cache
 * @param[in] count new sequential cutoff promotion request count value
 * @return exit code of successful completion is 0;
 * nonzero exit code means failure
 */

int cache_mngt_set_seq_cutoff_promotion_count(ocf_cache_t cache,
		ocf_core_t core, uint32_t count)
{
	int result;

	result = _cache_mngt_lock_sync(cache);
	if (result)
		return result;

	if (core) {
		result = ocf_mngt_core_set_seq_cutoff_promotion_count(core,
				count);
	} else {
		result = ocf_mngt_core_set_seq_cutoff_promotion_count_all(cache,
				count);
	}

	if (result)
		goto out;

	result = _cache_mngt_save_sync(cache);

out:
	ocf_mngt_cache_unlock(cache);
	return result;
}

/**
 * @brief Get sequential cutoff threshold value
 * @param[in] core OCF core
 * @param[out] thresh sequential cutoff threshold value
 * @return exit code of successful completion is 0;
 * nonzero exit code means failure
 */

int cache_mngt_get_seq_cutoff_threshold(ocf_core_t core, uint32_t *thresh)
{
	ocf_cache_t cache = ocf_core_get_cache(core);
	int result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result)
		return result;

	result = ocf_mngt_core_get_seq_cutoff_threshold(core, thresh);

	ocf_mngt_cache_read_unlock(cache);
	return result;
}

/**
 * @brief Get sequential cutoff policy
 * @param[in] core OCF core
 * @param[out] thresh sequential cutoff policy
 * @return exit code of successful completion is 0;
 * nonzero exit code means failure
 */

int cache_mngt_get_seq_cutoff_policy(ocf_core_t core,
		ocf_seq_cutoff_policy *policy)
{
	ocf_cache_t cache = ocf_core_get_cache(core);
	int result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result)
		return result;

	result = ocf_mngt_core_get_seq_cutoff_policy(core, policy);

	ocf_mngt_cache_read_unlock(cache);
	return result;
}

/**
 * @brief Get sequential cutoff promotion request count value
 * @param[in] core OCF core
 * @param[out] count sequential cutoff promotion request count value
 * @return exit code of successful completion is 0;
 * nonzero exit code means failure
 */

int cache_mngt_get_seq_cutoff_promotion_count(ocf_core_t core,
		uint32_t *count)
{
	ocf_cache_t cache = ocf_core_get_cache(core);
	int result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result)
		return result;

	result = ocf_mngt_core_get_seq_cutoff_promotion_count(core, count);

	ocf_mngt_cache_read_unlock(cache);
	return result;
}

static int _cache_flush_with_lock(ocf_cache_t cache)
{
	int result = 0;

	result = ocf_mngt_cache_get(cache);
	if (result)
		return result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result) {
		ocf_mngt_cache_put(cache);
		return result;
	}

	result = _cache_mngt_cache_flush_sync(cache, true,
			_cache_read_unlock_put_cmpl);

	return result;
}

/**
 * @brief routine implementing dynamic cache mode switching
 * @param cache_name name of cache to which operation applies
 * @param mode target mode (WRITE_THROUGH, WRITE_BACK, WRITE_AROUND etc.)
 * @param flush shall we flush dirty data during switch, or shall we flush
 *            all remaining dirty data before entering new mode?
 */
int cache_mngt_set_cache_mode(const char *cache_name, size_t name_len,
			ocf_cache_mode_t mode, uint8_t flush)
{
	ocf_cache_mode_t old_mode;
	ocf_cache_t cache;
	int result;

	result = ocf_mngt_cache_get_by_name(cas_ctx, cache_name,
					name_len, &cache);
	if (result)
		return result;

	old_mode = ocf_cache_get_mode(cache);
	if (old_mode == mode) {
		printk(KERN_INFO "%s is in requested cache mode already\n", cache_name);
		result = 0;
		goto put;
	}

	if (flush) {
		result = _cache_flush_with_lock(cache);
		if (result)
			goto put;
	}

	result = _cache_mngt_lock_sync(cache);
	if (result)
		goto put;

	if (old_mode != ocf_cache_get_mode(cache)) {
		printk(KERN_WARNING "%s cache mode changed during flush\n",
				ocf_cache_get_name(cache));
		goto unlock;
	}

	if (flush) {
		result = _cache_mngt_cache_flush_uninterruptible(cache);
		if (result)
			goto unlock;
	}

	result = ocf_mngt_cache_set_mode(cache, mode);
	if (result)
		goto unlock;

	result = _cache_mngt_save_sync(cache);
	if (result) {
		printk(KERN_ERR "%s: Failed to save new cache mode. "
				"Restoring old one!\n", cache_name);
		ocf_mngt_cache_set_mode(cache, old_mode);
	}

unlock:
	ocf_mngt_cache_unlock(cache);
put:
	ocf_mngt_cache_put(cache);
	return result;
}

/**
 * @brief routine implements --stop-cache command.
 * @param[in] cache_name caching device name to be removed
 * @param[in] flush Boolean: shall we flush dirty data before removing cache.
 *		if yes, flushing may still be interrupted by user (in which case
 *		device won't be actually removed and error will be returned)
 */
int cache_mngt_exit_instance(const char *cache_name, size_t name_len, int flush)
{
	ocf_cache_t cache;
	struct cache_priv *cache_priv;
	ocf_queue_t mngt_queue;
	int status = 0, flush_status = 0;
	struct _cache_mngt_stop_context *context;

	status = ocf_mngt_cache_get_by_name(cas_ctx, cache_name,
					name_len, &cache);
	if (status)
		return status;

	cache_priv = ocf_cache_get_priv(cache);
	mngt_queue = cache_priv->mngt_queue;
	context = cache_priv->stop_context;

	/*
	 * Flush cache. Flushing may take a long time, so we allow user
	 * to interrupt this operation. Hence we do first flush before
	 * disabling exported object to avoid restoring it in case
	 * of interruption. That means some new dirty data could appear
	 * in cache during flush operation which will not be flushed
	 * this time, so we need to flush cache again after disabling
	 * exported object. The second flush should be much faster.
	*/
	if (flush && ocf_cache_is_running(cache))
		status = _cache_flush_with_lock(cache);
	if (status)
		goto put;

	status = _cache_mngt_lock_sync(cache);
	if (status)
		goto put;

	context->finish_thread = cas_lazy_thread_create(exit_instance_finish,
			context, "cas_%s_stop", cache_name);
	if (IS_ERR(context->finish_thread)) {
		status = PTR_ERR(context->finish_thread);
		goto unlock;
	}

	/* Destroy cache devices */
	status = kcas_cache_destroy_all_core_exported_objects(cache);
	if (status != 0) {
		printk(KERN_WARNING
				"Failed to remove all cached devices\n");
		goto stop_thread;
	}
	status = kcas_cache_destroy_exported_object(cache);
	if (status != 0) {
		printk(KERN_WARNING
				"Failed to remove cache exported object\n");
		goto stop_thread;
	}

	/* Flush cache again. This time we don't allow interruption. */
	if (flush && ocf_cache_is_running(cache))
		flush_status = _cache_mngt_cache_flush_uninterruptible(cache);
	context->flush_status = flush_status;

	if (flush && !flush_status)
		BUG_ON(ocf_mngt_cache_is_dirty(cache));

	/* Stop cache device - ignore interrupts */
	status = _cache_mngt_cache_stop_sync(cache);
	if (status == -KCAS_ERR_WAITING_INTERRUPTED)
		printk(KERN_WARNING
				"Waiting for cache stop interrupted. "
				"Stop will finish asynchronously.\n");

	if ((status == 0 || status == -KCAS_ERR_WAITING_INTERRUPTED) &&
			flush_status) {
		/* "removed dirty" error has a precedence over "interrupted" */
		return KCAS_ERR_STOPPED_DIRTY;
	}

	return status;

stop_thread:
	cas_lazy_thread_stop(context->finish_thread);
unlock:
	ocf_mngt_cache_unlock(cache);
put:
	ocf_mngt_cache_put(cache);
	return status;
}

struct cache_mngt_list_ctx {
	struct kcas_cache_list *list;
	int pos;
};

static int cache_mngt_list_caches_visitor(ocf_cache_t cache, void *cntx)
{
	struct cache_mngt_list_ctx *context = cntx;
	struct kcas_cache_list *list = context->list;
	uint16_t id;

	BUG_ON(cache_id_from_name(&id, ocf_cache_get_name(cache)));

	if (context->pos++ < list->id_position)
		return 0;

	if (list->in_out_num >= ARRAY_SIZE(list->cache_id_tab))
		return 1;

	list->cache_id_tab[list->in_out_num] = id;
	list->in_out_num++;

	return 0;
}

int cache_mngt_list_caches(struct kcas_cache_list *list)
{
	struct cache_mngt_list_ctx context = {
		.list = list,
		.pos = 0
	};

	list->in_out_num = 0;
	return ocf_mngt_cache_visit(cas_ctx, cache_mngt_list_caches_visitor,
			&context);
}

int cache_mngt_interrupt_flushing(const char *cache_name, size_t name_len)
{
	ocf_cache_t cache;
	struct cache_priv *cache_priv;
	int result;

	result = ocf_mngt_cache_get_by_name(cas_ctx, cache_name,
					name_len, &cache);
	if (result)
		return result;

	cache_priv = ocf_cache_get_priv(cache);

	if (atomic_read(&cache_priv->flush_interrupt_enabled))
		ocf_mngt_cache_flush_interrupt(cache);

	ocf_mngt_cache_put(cache);

	return 0;

}

int cache_mngt_get_stats(struct kcas_get_stats *stats)
{
	int result;
	ocf_cache_t cache;
	ocf_core_t core = NULL;

	result = mngt_get_cache_by_id(cas_ctx, stats->cache_id, &cache);
	if (result)
		return result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result)
		goto put;

	if (stats->core_id == OCF_CORE_ID_INVALID &&
			stats->part_id == OCF_IO_CLASS_INVALID) {
		result = ocf_stats_collect_cache(cache, &stats->usage, &stats->req,
				&stats->blocks, &stats->errors);
		if (result)
			goto unlock;

	} else if (stats->part_id == OCF_IO_CLASS_INVALID) {
		result = get_core_by_id(cache, stats->core_id, &core);
		if (result)
			goto unlock;

		result = ocf_stats_collect_core(core, &stats->usage, &stats->req,
				&stats->blocks, &stats->errors);
		if (result)
			goto unlock;

	} else {
		if (stats->core_id == OCF_CORE_ID_INVALID) {
			result = ocf_stats_collect_part_cache(cache, stats->part_id,
					&stats->usage, &stats->req, &stats->blocks);
		} else {
			result = get_core_by_id(cache, stats->core_id, &core);
			if (result)
				goto unlock;

			result = ocf_stats_collect_part_core(core, stats->part_id,
					&stats->usage, &stats->req, &stats->blocks);
		}
	}

unlock:
	ocf_mngt_cache_read_unlock(cache);
put:
	ocf_mngt_cache_put(cache);
	return result;
}

int cache_mngt_get_info(struct kcas_cache_info *info)
{
	uint32_t i, j;
	int result;
	ocf_cache_t cache;
	ocf_core_t core;
	const struct ocf_volume_uuid *uuid;

	result = mngt_get_cache_by_id(cas_ctx, info->cache_id, &cache);
	if (result)
		return result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result)
		goto put;

	result = ocf_cache_get_info(cache, &info->info);
	if (result)
		goto unlock;

	if (info->info.attached && !info->info.failover_detached) {
		uuid = ocf_cache_get_uuid(cache);
		BUG_ON(!uuid);
		strlcpy(info->cache_path_name, uuid->data,
				min(sizeof(info->cache_path_name), uuid->size));
	} else {
		memset(info->cache_path_name, 0, sizeof(info->cache_path_name));
	}

	/* Collect cores IDs */
	for (i = 0, j = 0; j < info->info.core_count &&
			i < OCF_CORE_MAX; i++) {
		if (get_core_by_id(cache, i, &core))
			continue;

		info->core_id[j] = i;
		j++;
	}

unlock:
	ocf_mngt_cache_read_unlock(cache);
put:
	ocf_mngt_cache_put(cache);
	return result;
}

int cache_mngt_get_io_class_info(struct kcas_io_class *part)
{
	int result;
	uint16_t cache_id = part->cache_id;
	uint32_t io_class_id = part->class_id;
	ocf_cache_t cache;

	result = mngt_get_cache_by_id(cas_ctx, cache_id, &cache);
	if (result)
		return result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result) {
		ocf_mngt_cache_put(cache);
		return result;
	}

	result = ocf_cache_io_class_get_info(cache, io_class_id, &part->info);
	if (result)
		goto end;

end:
	ocf_mngt_cache_read_unlock(cache);
	ocf_mngt_cache_put(cache);
	return result;
}

int cache_mngt_get_core_info(struct kcas_core_info *info)
{
	ocf_cache_t cache;
	ocf_core_t core;
	const struct ocf_volume_uuid *uuid;
	int result;

	result = mngt_get_cache_by_id(cas_ctx, info->cache_id, &cache);
	if (result)
		return result;

	result = _cache_mngt_read_lock_sync(cache);
	if(result)
		goto put;

	result = get_core_by_id(cache, info->core_id, &core);
	if (result < 0) {
		result = OCF_ERR_CORE_NOT_AVAIL;
		goto unlock;
	}

	result = ocf_core_get_info(core, &info->info);
	if (result)
		goto unlock;

	uuid = ocf_core_get_uuid(core);

	if (uuid->data) {
		strlcpy(info->core_path_name, uuid->data,
				min(sizeof(info->core_path_name), uuid->size));
	}

	info->state = ocf_core_get_state(core);

unlock:
	ocf_mngt_cache_read_unlock(cache);
put:
	ocf_mngt_cache_put(cache);
	return result;
}

static int cache_mngt_wait_for_rq_finish_visitor(ocf_core_t core, void *cntx)
{
	ocf_volume_t obj = ocf_core_get_volume(core);
	struct bd_object *bdobj = bd_object(obj);

	while (atomic64_read(&bdobj->pending_rqs))
		io_schedule();

	return 0;
}

void cache_mngt_wait_for_rq_finish(ocf_cache_t cache)
{
	ocf_core_visit(cache, cache_mngt_wait_for_rq_finish_visitor, NULL, true);
}

int cache_mngt_set_core_params(struct kcas_set_core_param *info)
{
	ocf_cache_t cache;
	ocf_core_t core = NULL;
	int result;

	result = mngt_get_cache_by_id(cas_ctx, info->cache_id, &cache);
	if (result)
		return result;

	if (info->core_id != OCF_CORE_ID_INVALID) {
		result = get_core_by_id(cache, info->core_id, &core);
		if (result)
			goto out;
	}

	switch (info->param_id) {
	case core_param_seq_cutoff_threshold:
		result = cache_mngt_set_seq_cutoff_threshold(cache, core,
				info->param_value);
		break;
	case core_param_seq_cutoff_policy:
		result = cache_mngt_set_seq_cutoff_policy(cache, core,
				info->param_value);
		break;
	case core_param_seq_cutoff_promotion_count:
		result = cache_mngt_set_seq_cutoff_promotion_count(cache,
				core, info->param_value);
		break;
	default:
		result = -EINVAL;
	}

out:
	ocf_mngt_cache_put(cache);
	return result;
}

int cache_mngt_get_core_params(struct kcas_get_core_param *info)
{
	ocf_cache_t cache;
	ocf_core_t core;
	int result;

	result = mngt_get_cache_by_id(cas_ctx, info->cache_id, &cache);
	if (result)
		return result;

	result = get_core_by_id(cache, info->core_id, &core);
	if (result)
		goto out;

	switch (info->param_id) {
	case core_param_seq_cutoff_threshold:
		result = cache_mngt_get_seq_cutoff_threshold(core,
				&info->param_value);
		break;
	case core_param_seq_cutoff_policy:
		result = cache_mngt_get_seq_cutoff_policy(core,
				&info->param_value);
		break;
	case core_param_seq_cutoff_promotion_count:
		result = cache_mngt_get_seq_cutoff_promotion_count(core,
				&info->param_value);
		break;
	default:
		result = -EINVAL;
	}

out:
	ocf_mngt_cache_put(cache);
	return result;
}

int cache_mngt_set_cache_params(struct kcas_set_cache_param *info)
{
	ocf_cache_t cache;
	int result;

	result = mngt_get_cache_by_id(cas_ctx, info->cache_id, &cache);
	if (result)
		return result;

	switch (info->param_id) {
	case cache_param_cleaning_policy_type:
		result = cache_mngt_set_cleaning_policy(cache,
				info->param_value);
		break;

	case cache_param_cleaning_alru_wake_up_time:
		result = cache_mngt_set_cleaning_param(cache,
				ocf_cleaning_alru, ocf_alru_wake_up_time,
				info->param_value);
		break;
	case cache_param_cleaning_alru_stale_buffer_time:
		result = cache_mngt_set_cleaning_param(cache,
				ocf_cleaning_alru, ocf_alru_stale_buffer_time,
				info->param_value);
		break;
	case cache_param_cleaning_alru_flush_max_buffers:
		result = cache_mngt_set_cleaning_param(cache,
				ocf_cleaning_alru, ocf_alru_flush_max_buffers,
				info->param_value);
		break;
	case cache_param_cleaning_alru_activity_threshold:
		result = cache_mngt_set_cleaning_param(cache,
				ocf_cleaning_alru, ocf_alru_activity_threshold,
				info->param_value);
		break;

	case cache_param_cleaning_acp_wake_up_time:
		result = cache_mngt_set_cleaning_param(cache,
				ocf_cleaning_acp, ocf_acp_wake_up_time,
				info->param_value);
		break;
	case cache_param_cleaning_acp_flush_max_buffers:
		result = cache_mngt_set_cleaning_param(cache,
				ocf_cleaning_acp, ocf_acp_flush_max_buffers,
				info->param_value);
		break;
	case cache_param_promotion_policy_type:
		result = cache_mngt_set_promotion_policy(cache, info->param_value);
		break;
	case cache_param_promotion_nhit_insertion_threshold:
		result = cache_mngt_set_promotion_param(cache, ocf_promotion_nhit,
				ocf_nhit_insertion_threshold, info->param_value);
		break;
	case cache_param_promotion_nhit_trigger_threshold:
		result = cache_mngt_set_promotion_param(cache, ocf_promotion_nhit,
				ocf_nhit_trigger_threshold, info->param_value);
		break;
	default:
		result = -EINVAL;
	}

	ocf_mngt_cache_put(cache);
	return result;
}

int cache_mngt_get_cache_params(struct kcas_get_cache_param *info)
{
	ocf_cache_t cache;
	int result;

	result = mngt_get_cache_by_id(cas_ctx, info->cache_id, &cache);
	if (result)
		return result;

	switch (info->param_id) {
	case cache_param_cleaning_policy_type:
		result = cache_mngt_get_cleaning_policy(cache,
				&info->param_value);
		break;

	case cache_param_cleaning_alru_wake_up_time:
		result = cache_mngt_get_cleaning_param(cache,
				ocf_cleaning_alru, ocf_alru_wake_up_time,
				&info->param_value);
		break;
	case cache_param_cleaning_alru_stale_buffer_time:
		result = cache_mngt_get_cleaning_param(cache,
				ocf_cleaning_alru, ocf_alru_stale_buffer_time,
				&info->param_value);
		break;
	case cache_param_cleaning_alru_flush_max_buffers:
		result = cache_mngt_get_cleaning_param(cache,
				ocf_cleaning_alru, ocf_alru_flush_max_buffers,
				&info->param_value);
		break;
	case cache_param_cleaning_alru_activity_threshold:
		result = cache_mngt_get_cleaning_param(cache,
				ocf_cleaning_alru, ocf_alru_activity_threshold,
				&info->param_value);
		break;

	case cache_param_cleaning_acp_wake_up_time:
		result = cache_mngt_get_cleaning_param(cache,
				ocf_cleaning_acp, ocf_acp_wake_up_time,
				&info->param_value);
		break;
	case cache_param_cleaning_acp_flush_max_buffers:
		result = cache_mngt_get_cleaning_param(cache,
				ocf_cleaning_acp, ocf_acp_flush_max_buffers,
				&info->param_value);
		break;
	case cache_param_promotion_policy_type:
		result = cache_mngt_get_promotion_policy(cache, &info->param_value);
		break;
	case cache_param_promotion_nhit_insertion_threshold:
		result = cache_mngt_get_promotion_param(cache, ocf_promotion_nhit,
				ocf_nhit_insertion_threshold, &info->param_value);
		break;
	case cache_param_promotion_nhit_trigger_threshold:
		result = cache_mngt_get_promotion_param(cache, ocf_promotion_nhit,
				ocf_nhit_trigger_threshold, &info->param_value);
		break;
	default:
		result = -EINVAL;
	}

	ocf_mngt_cache_put(cache);
	return result;
}
