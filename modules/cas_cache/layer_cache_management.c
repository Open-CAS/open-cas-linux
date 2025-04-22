/*
* Copyright(c) 2012-2022 Intel Corporation
* Copyright(c) 2023-2024 Huawei Technologies Co., Ltd.
* SPDX-License-Identifier: BSD-3-Clause
*/

#include "cas_cache.h"
#include "ocf/ocf_cache.h"
#include "ocf/ocf_core.h"
#include "ocf/ocf_def.h"
#include "ocf/ocf_err.h"
#include "ocf/ocf_mngt.h"
#include "ocf/ocf_queue.h"
#include "ocf/ocf_volume.h"
#include "threads.h"
#include "volume/obj_blk.h"

extern u32 max_writeback_queue_size;
extern u32 writeback_queue_unblock_size;
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

static inline void _cache_mngt_async_context_init_common(
		struct _cache_mngt_async_context *context)
{
	spin_lock_init(&context->lock);
	context->result = 0;
	context->compl_func = NULL;
}

static inline void _cache_mngt_async_context_init(
		struct _cache_mngt_async_context *context)
{
	init_completion(&context->cmpl);
	_cache_mngt_async_context_init_common(context);
}

static inline void _cache_mngt_async_context_reinit(
		struct _cache_mngt_async_context *context)
{
	reinit_completion(&context->cmpl);
	_cache_mngt_async_context_init_common(context);
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

static int _inc_cache_refcnt_visitor(ocf_cache_t cache, void *priv)
{
	return ocf_mngt_cache_get(cache);
}

static int _inc_cache_refcnt_visitor_rollback(ocf_cache_t cache, void *priv)
{
	ocf_mngt_cache_put(cache);

	return 0;
}

static int _dec_cache_refcnt_visitor(ocf_cache_t cache, void *priv)
{
	ocf_mngt_cache_put(cache);

	return 0;
}

static int cache_ml_get(ocf_cache_t main_cache)
{
	return ocf_mngt_cache_ml_visit_from_bottom(main_cache,
			_inc_cache_refcnt_visitor,
			_inc_cache_refcnt_visitor_rollback, NULL);
}

static void cache_ml_put(ocf_cache_t main_cache)
{
	int status;

	status = ocf_mngt_cache_ml_visit_from_bottom(main_cache,
			_dec_cache_refcnt_visitor, NULL , NULL);
	BUG_ON(status);
}

static int _read_lock_cache_visitor(ocf_cache_t cache, void *priv)
{
	return _cache_mngt_read_lock_sync(cache);
}

static int _read_lock_cache_visitor_rollback(ocf_cache_t cache, void *priv)
{
	ocf_mngt_cache_read_unlock(cache);

	return 0;
}

static int _read_unlock_cache_visitor(ocf_cache_t cache, void *priv)
{
	ocf_mngt_cache_read_unlock(cache);

	return 0;
}

static int cache_ml_read_lock(ocf_cache_t main_cache)
{
	return ocf_mngt_cache_ml_visit_from_bottom(main_cache,
			_read_lock_cache_visitor,
			_read_lock_cache_visitor_rollback, NULL);
}

static void cache_ml_read_unlock(ocf_cache_t main_cache)
{
	int status;

	status = ocf_mngt_cache_ml_visit_from_bottom(main_cache,
			_read_unlock_cache_visitor, NULL, NULL);

	BUG_ON(status);
}

static int _lock_cache_visitor(ocf_cache_t cache, void *priv)
{
	return _cache_mngt_lock_sync(cache);
}

static int _lock_cache_visitor_rollback(ocf_cache_t cache, void *priv)
{
	ocf_mngt_cache_unlock(cache);

	return 0;
}

static int _unlock_cache_visitor(ocf_cache_t cache, void *priv)
{
	ocf_mngt_cache_unlock(cache);

	return 0;
}

static int cache_ml_lock(ocf_cache_t main_cache)
{
	return ocf_mngt_cache_ml_visit_from_bottom(main_cache,
			_lock_cache_visitor,
			_lock_cache_visitor_rollback, NULL);
}

static void cache_ml_unlock(ocf_cache_t main_cache)
{
	int status;

	status = ocf_mngt_cache_ml_visit_from_bottom(main_cache,
			_unlock_cache_visitor, NULL, NULL);

	BUG_ON(status);
}

static int _get_level_count_visitor(ocf_cache_t cache, void *priv)
{
	int *count = (int*)priv;

	*count += 1;

	return 0;
}

static int cache_ml_get_level_count(ocf_cache_t main_cache)
{
	int count = 0;
	int status;

	status = ocf_mngt_cache_ml_visit_from_bottom(main_cache,
			_get_level_count_visitor, NULL, &count);

	return status == 0 ? count : -1;
}

struct get_ml_cache_ids_ctx {
	int buffer_size;
	int buffer_position;
	ocf_cache_t *buffer;
};

static int _get_ptr_visitor(ocf_cache_t cache, void *priv)
{
	struct get_ml_cache_ids_ctx *ctx = priv;

	if (ctx->buffer_position >= ctx->buffer_size)
		return -EINVAL;

	ctx->buffer[ctx->buffer_position] = cache;

	ctx->buffer_position++;

	return 0;
}

static int cache_ml_get_ptrs(ocf_cache_t main_cache, ocf_cache_t *buffer,
		int buffer_size)
{
	struct get_ml_cache_ids_ctx ctx;
	ctx.buffer_size = buffer_size;
	ctx.buffer = buffer;
	ctx.buffer_position = 0;

	return ocf_mngt_cache_ml_visit_from_top(main_cache,
			_get_ptr_visitor, NULL, &ctx);
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

static int _flush_cache_visitor(ocf_cache_t cache, void *priv)
{
	bool interruption = (bool)priv;

	if (!ocf_cache_is_device_attached(cache))
		return 0;

	return _cache_mngt_cache_flush_sync(cache, interruption, NULL);

}

static int _flush_ml_cache(ocf_cache_t main_cache)
{
	int status;
	bool interruption = true;

	status = cache_ml_get(main_cache);
	if (status)
		return status;

	status = cache_ml_read_lock(main_cache);
	if (status)
		goto lock_err;

	status = ocf_mngt_cache_ml_visit_from_top(main_cache,
			_flush_cache_visitor, NULL, (void*)interruption);

	cache_ml_read_unlock(main_cache);
lock_err:
	cache_ml_put(main_cache);

	return status;
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
	int cache_ml_levels;
	ocf_cache_t *cache_ml_ptrs;
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
	struct _cache_mngt_stop_context *stop_ctx = data;
	ocf_queue_t mngt_queue;
	int result = 0;
	ocf_cache_t cache;
	int i;

	if (stop_ctx->error && stop_ctx->error != -OCF_ERR_WRITE_CACHE)
		BUG_ON(stop_ctx->error);

	if (!stop_ctx->error && stop_ctx->flush_status)
		result = -KCAS_ERR_STOPPED_DIRTY;
	else
		result = stop_ctx->error;

	/*
	 * The IDs in stop_ctx->cache_ml_ptrs are ordered from the topmost to the
	 * bottom. The bottommost cache (main cache) requires different
	 * handling as it must notify the user's thread about the completed
	 * stop operation
	*/
	for (i = 0; i < stop_ctx->cache_ml_levels - 1; i++) {
		cache = stop_ctx->cache_ml_ptrs[i];
		cache_priv = ocf_cache_get_priv(cache);
		mngt_queue = cache_priv->mngt_queue;

		if (!ocf_cache_is_standby(cache))
			cas_cls_deinit(cache);

		kfree(cache_priv->stop_context);
		vfree(cache_priv);
		ocf_mngt_cache_unlock(cache);
		ocf_mngt_cache_put(cache);
		ocf_queue_put(mngt_queue);
		module_put(THIS_MODULE);
	}

	if (!ocf_cache_is_standby(stop_ctx->cache))
		cas_cls_deinit(stop_ctx->cache);

	vfree(stop_ctx->cache_ml_ptrs);
	cache_priv = ocf_cache_get_priv(stop_ctx->cache);
	mngt_queue = cache_priv->mngt_queue;

	vfree(cache_priv);

	ocf_mngt_cache_unlock(stop_ctx->cache);
	ocf_mngt_cache_put(stop_ctx->cache);
	ocf_queue_put(mngt_queue);

	result = _cache_mngt_async_callee_set_result(&stop_ctx->async, result);

	if (result == -KCAS_ERR_WAITING_INTERRUPTED)
		kfree(stop_ctx);

	CAS_MODULE_PUT_AND_EXIT(0);
}

struct _cache_mngt_attach_context {
	struct _cache_mngt_async_context async;
	uint64_t min_free_ram;
	struct ocf_mngt_cache_device_config device_cfg;
	char cache_path[MAX_STR_LEN];
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

	CAS_MODULE_PUT_AND_EXIT(0);

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
	context->flush_status = 0;
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

	if (ocf_cache_is_standby(cache)) {
		ocf_mngt_cache_put(cache);
		return -OCF_ERR_CACHE_STANDBY;
	}

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

	result = ocf_mngt_cache_promotion_get_policy(cache, type);

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

static int _cache_mngt_core_pool_get_paths_visitor(ocf_uuid_t uuid, void *ctx)
{
	struct get_paths_ctx *visitor_ctx = ctx;

	if (visitor_ctx->position >= visitor_ctx->max_count)
		return 0;

	if (visitor_ctx->core_path_name_tab == NULL) {
		return -EFAULT ;
	}
	if (uuid->data == NULL || uuid->size == 0) {
		return -ENODATA;
	}
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
	cas_bdev_handle_t bdev_handle;
	struct block_device *bdev;
	ocf_volume_t volume;
	char holder[] = "CAS CHECK CACHE DEVICE\n";
	int result;

	bdev_handle = cas_bdev_open_by_path(cmd_info->path_name,
			(CAS_BLK_MODE_EXCL | CAS_BLK_MODE_READ), holder);
	if (IS_ERR(bdev_handle)) {
		return (PTR_ERR(bdev_handle) == -EBUSY) ?
				-OCF_ERR_NOT_OPEN_EXC :
				-OCF_ERR_INVAL_VOLUME_TYPE;
	}
	bdev = cas_bdev_get_from_handle(bdev_handle);

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
	cas_bdev_release(bdev_handle,
			(CAS_BLK_MODE_EXCL | CAS_BLK_MODE_READ), holder);
	return result;
}

int cache_mngt_prepare_core_cfg(struct ocf_mngt_core_config *cfg,
		struct kcas_insert_core *cmd_info)
{
	char core_name[OCF_CORE_NAME_SIZE] = {};
	ocf_cache_t cache = NULL;
	uint16_t core_id;
	int result;

	if (strnlen(cmd_info->core_path_name, MAX_STR_LEN) >= MAX_STR_LEN)
		return -OCF_ERR_INVAL;

	if (cmd_info->try_add && cmd_info->core_id == OCF_CORE_MAX)
		return -OCF_ERR_INVAL;

	result = mngt_get_cache_by_id(cas_ctx, cmd_info->cache_id, &cache);
	if (result && result != -OCF_ERR_CACHE_NOT_EXIST) {
		return result;
	} else if (!result && ocf_cache_is_standby(cache)) {
		ocf_mngt_cache_put(cache);
		return -OCF_ERR_CACHE_STANDBY;
	}

	if (cmd_info->core_id == OCF_CORE_MAX) {
		struct cache_priv *cache_priv;

		if (!cache)
			return -OCF_ERR_CACHE_NOT_EXIST;

		cache_priv = ocf_cache_get_priv(cache);
		core_id = find_free_core_id(cache_priv->core_id_bitmap);
		if (core_id == OCF_CORE_MAX)
			return -OCF_ERR_INVAL;

		cmd_info->core_id = core_id;
	}

	if (cache) {
		ocf_mngt_cache_put(cache);
		cache = NULL;
	}

	snprintf(core_name, sizeof(core_name), "core%d", cmd_info->core_id);

	memset(cfg, 0, sizeof(*cfg));
	env_strncpy(cfg->name, OCF_CORE_NAME_SIZE, core_name, OCF_CORE_NAME_SIZE);

	cfg->uuid.data = cmd_info->core_path_name;
	cfg->uuid.size = strnlen(cmd_info->core_path_name, MAX_STR_LEN) + 1;
	cfg->try_add = cmd_info->try_add;
	cfg->seq_cutoff_promote_on_threshold = true;

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

	if (ocf_cache_is_device_attached(cache))
		result = _cache_mngt_save_sync(cache);

	return result;
}

static void _cache_mngt_log_core_device_path(ocf_core_t core)
{
	ocf_cache_t cache = ocf_core_get_cache(core);
	const ocf_uuid_t core_uuid = (const ocf_uuid_t)ocf_core_get_uuid(core);

	printk(KERN_INFO OCF_PREFIX_SHORT "Adding device %s as core %s "
			"to cache %s\n", core_uuid->data
			? (const char *)core_uuid->data : "NULL",
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

	/* Due to linux thread scheduling nature, we prefer to promote streams
	 * as early as we reasonably can. One way to achieve that is to set
	 * promotion count really low, which unfortunately significantly increases
	 * number of accesses to shared structures. The other way is to promote
	 * streams which reach cutoff threshold, as we can reasonably assume that
	 * they are likely be continued after thread is rescheduled to another CPU.
	 */
	cfg->seq_cutoff_promote_on_threshold = true;

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

	if (!ocf_cache_ml_is_main(cache)) {
		result = -OCF_ERR_CACHE_NOT_MAIN;
		goto put;
	}
	
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

	if (result != -OCF_ERR_CORE_NOT_REMOVED && !cmd->detach)
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

#ifndef OCF_DEBUG_STATS
int cache_mngt_reset_stats(const char *cache_name, size_t cache_name_len,
				const char *core_name, size_t core_name_len)
#else
int cache_mngt_reset_stats(const char *cache_name, size_t cache_name_len,
	const char *core_name, size_t core_name_len, int composite_volume_member_id)
#endif
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
#ifdef OCF_DEBUG_STATS
		result = ocf_composite_volume_stats_initialize(cache, core,
					composite_volume_member_id);
		if (result)
			goto out;
#endif
	} else {
		result = ocf_core_stats_initialize_all(cache);
#ifdef OCF_DEBUG_STATS
		if (result)
			goto out;
		result = ocf_composite_volume_stats_initialize_all_cores(cache,
					composite_volume_member_id);
#endif
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

	if (ocf_cache_is_standby(cache)) {
		result = -OCF_ERR_CACHE_STANDBY;
		goto out_not_running;
	}

	if (!ocf_cache_is_device_attached(cache)) {
		result = -OCF_ERR_CACHE_DETACHED;
		goto out_not_running;
	}

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
out_not_running:
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

	cache_priv->cache_exp_obj_initialized = true;

	return 0;
}

static int cache_mngt_create_cache_device_cfg(
		struct ocf_mngt_cache_device_config *cfg, char *cache_path)
{
	int result = 0;
	int path_size = strnlen(cache_path, MAX_STR_LEN) + 1;
	struct ocf_volume_uuid uuid;
	ocf_composite_volume_t composite_volume;
	ocf_volume_type_t volume_type;
	uint8_t volume_type_id;
	char *cache_path_copy, *cache_path_copy_ptr;
	char* vol_path;
	memset(cfg, 0, sizeof(*cfg));

	if (path_size >= MAX_STR_LEN || path_size == 0)
		return -OCF_ERR_INVAL;

	cache_path_copy = vzalloc(path_size);
	if (!cache_path_copy)
		return -OCF_ERR_NO_MEM;
	cache_path_copy_ptr = cache_path_copy;

	strncpy(cache_path_copy, cache_path, path_size);

	result = ocf_composite_volume_create(&composite_volume, cas_ctx);
	if (result) {
		vfree(cache_path_copy);
		return result;
	}

	uuid.data = vzalloc(path_size);
	if (uuid.data == NULL) {
		ocf_composite_volume_destroy(composite_volume);
		vfree(cache_path_copy);
		return -OCF_ERR_NO_MEM;
	}

	uuid.data = strncpy(uuid.data, cache_path, path_size);
	uuid.size = path_size;
	ocf_composite_volume_set_uuid(composite_volume, &uuid, true);

	uuid.data = NULL;
	uuid.size = 0;

	while ((vol_path = strsep(&cache_path_copy, ",")) != NULL) {

		result = cas_blk_identify_type(vol_path, &volume_type_id);
		if (result)
			goto err;

		volume_type = ocf_ctx_get_volume_type(cas_ctx, volume_type_id);
		if (!volume_type) {
			result = -OCF_ERR_INVAL;
			goto err;
		}

		uuid.data = vol_path;
		uuid.size = strnlen(vol_path, MAX_STR_LEN) + 1;

		result = ocf_composite_volume_add(composite_volume,
				volume_type, &uuid, cfg->volume_params);
		if (result)
			goto err;

	}

	cfg->perform_test = false;
	cfg->volume = composite_volume;
	vfree(cache_path_copy_ptr);

	return 0;

err:
	vfree(cache_path_copy_ptr);

	ocf_composite_volume_destroy(composite_volume);

	return result;
}

int cache_mngt_attach_cache_cfg(char *cache_name, size_t name_len,
		struct ocf_mngt_cache_config *cfg,
		struct ocf_mngt_cache_attach_config *attach_cfg,
		struct kcas_start_cache *cmd)
{
	int result;

	if (!cmd)
		return -OCF_ERR_INVAL;

	memset(cfg, 0, sizeof(*cfg));
	memset(attach_cfg, 0, sizeof(*attach_cfg));

	result = cache_mngt_create_cache_device_cfg(&attach_cfg->device,
			cmd->cache_path_name);
	if (result)
		return result;

	//TODO maybe attach should allow to change cache line size?
	//cfg->cache_line_size = cmd->line_size;
	cfg->use_submit_io_fast = !use_io_scheduler;
	cfg->locked = true;
#ifdef CAS_COMMUNITY_MODE
	cfg->metadata_volatile = false;
#else
	cfg->metadata_volatile = true;
#endif

	cfg->backfill.max_queue_size = max_writeback_queue_size;
	cfg->backfill.queue_unblock_size = writeback_queue_unblock_size;
	attach_cfg->cache_line_size = cmd->line_size;
	attach_cfg->force = cmd->force;
	attach_cfg->discard_on_start = true;

	return 0;
}

static void cache_mngt_destroy_cache_device_cfg(
		struct ocf_mngt_cache_device_config *cfg)
{
	ocf_volume_destroy(cfg->volume);
}

int cache_mngt_create_cache_cfg(struct ocf_mngt_cache_config *cfg,
		struct ocf_mngt_cache_attach_config *attach_cfg,
		struct kcas_start_cache *cmd)
{
	int init_cache, result;
	char cache_name[OCF_CACHE_NAME_SIZE];
	uint16_t cache_id;

	if (!cmd)
		return -OCF_ERR_INVAL;

	if (cmd->init_cache == CACHE_INIT_LOAD ||
			cmd->init_cache == CACHE_INIT_STANDBY_LOAD) {
		if (cmd->cache_id != OCF_CACHE_ID_INVALID) {
			printk(KERN_WARNING "Specifying cache id while loading "
					"cache is forbidden\n");
			return -OCF_ERR_INVAL;
		}

		if (cmd->line_size != ocf_cache_line_size_none) {
			printk(KERN_WARNING "Specifying cache line size while "
					"loading cache is forbidden\n");
			return -OCF_ERR_INVAL;
		}
		if (cmd->caching_mode != ocf_cache_mode_none) {
			printk(KERN_WARNING "Specifying cache mode while "
					"loading cache is forbidden\n");
			return -OCF_ERR_INVAL;
		}
	} else if (cmd->cache_id == OCF_CACHE_ID_INVALID) {
		cache_id = find_free_cache_id(cas_ctx);
		if (cache_id == OCF_CACHE_ID_INVALID)
			return -OCF_ERR_INVAL;

		cmd->cache_id = cache_id;
	}

	cache_name_from_id(cache_name, cmd->cache_id);

	memset(cfg, 0, sizeof(*cfg));
	memset(attach_cfg, 0, sizeof(*attach_cfg));

	result = cache_mngt_create_cache_device_cfg(&attach_cfg->device,
			cmd->cache_path_name);
	if (result)
		return result;

#ifdef CAS_COMMUNITY_MODE
	cfg->allow_override_defaults = true;
	attach_cfg->allow_override_defaults = true;
#endif /* CAS_COMMUNITY_MODE */

	strncpy(cfg->name, cache_name, OCF_CACHE_NAME_SIZE - 1);
	cfg->cache_mode = cmd->caching_mode;
	cfg->cache_line_size = cmd->line_size;
	cfg->promotion_policy = ocf_promotion_default;
	cfg->cache_line_size = cmd->line_size;
	cfg->use_submit_io_fast = !use_io_scheduler;
	cfg->locked = true;
#ifdef CAS_COMMUNITY_MODE
	cfg->metadata_volatile = false;
#else
	cfg->metadata_volatile = true;
#endif

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
	case CACHE_INIT_STANDBY_NEW:
	case CACHE_INIT_STANDBY_LOAD:
		break;
	default:
		return -OCF_ERR_INVAL;
	}


	return 0;
}

static void _cache_mngt_log_cache_device_path(ocf_cache_t cache,
		const char *cache_path)
{
	printk(KERN_INFO OCF_PREFIX_SHORT "Adding device %s as cache %s\n",
			cache_path, ocf_cache_get_name(cache));
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
	uint32_t cpus_no = num_possible_cpus();
	struct cache_priv *cache_priv;
	int result, i;

	cache_priv = ocf_cache_get_priv(cache);

	for (i = 0; i < cpus_no; i++) {
		result = ocf_queue_create(cache, &cache_priv->io_queues[i],
				&queue_ops);
		if (result)
			goto err;

		result = cas_create_queue_thread(cache,
				cache_priv->io_queues[i], i);
		if (result) {
			ocf_queue_put(cache_priv->io_queues[i]);
			goto err;
		}
	}

	result = ocf_queue_create_mngt(cache, &cache_priv->mngt_queue,
			&queue_ops);
	if (result)
		goto err;

	result = cas_create_queue_thread(cache,
			cache_priv->mngt_queue, CAS_CPUS_ALL);
	if (result) {
		ocf_queue_put(cache_priv->mngt_queue);
		cache_priv->mngt_queue = NULL;
		goto err;
	}

	return 0;
err:
	while (--i >= 0)
		ocf_queue_put(cache_priv->io_queues[i]);

	return result;
}

static int check_block_device(ocf_volume_t volume, void *priv,
		ocf_composite_visitor_member_state_t s)
{
	struct bd_object *bd_cache_obj = bd_object(volume);
	struct block_device *bdev = bd_cache_obj->btm_bd;

	/* If we deal with whole device, reread partitions */
	if (cas_bdev_whole(bdev) == bdev)
		cas_reread_partitions(bdev);

	return 0;
}

static void init_instance_complete(struct _cache_mngt_attach_context* ctx,
		ocf_cache_t cache)
{
	ocf_volume_t cache_obj;
	int volume_type_id;

	cache_obj = ocf_cache_get_volume(cache);
	BUG_ON(!cache_obj);

	volume_type_id = ocf_ctx_get_volume_type_id(cas_ctx,
			ocf_volume_get_type(cache_obj));
	BUG_ON(volume_type_id != OCF_VOLUME_TYPE_COMPOSITE);

	ocf_composite_volume_member_visit(cache_obj, check_block_device, NULL,
			ocf_composite_visitor_member_state_attached);
}

static void calculate_min_ram_size(ocf_cache_t cache,
		struct _cache_mngt_attach_context *ctx)
{
	uint64_t volume_size;
	int result;

	ctx->min_free_ram = 0;

	result = cache_mngt_create_cache_device_cfg(&ctx->device_cfg,
			ctx->cache_path);
	if (result)
			goto end;

	result = ocf_volume_open(ctx->device_cfg.volume,
			ctx->device_cfg.volume_params);
	if (result)
		goto destroy_config;

	volume_size = ocf_volume_get_length(ctx->device_cfg.volume);
	ctx->min_free_ram = ocf_mngt_get_ram_needed(cache, volume_size);
	ocf_volume_close(ctx->device_cfg.volume);

destroy_config:
	cache_mngt_destroy_cache_device_cfg(&ctx->device_cfg);
end:
	if (result)
		printk(KERN_WARNING "Cannot calculate amount of DRAM needed\n");
}

static void _cache_mngt_attach_complete(ocf_cache_t cache, void *priv,
		int error)
{
	struct _cache_mngt_attach_context *ctx = priv;
	int caller_status;
	char *path;

	cache_mngt_destroy_cache_device_cfg(&ctx->device_cfg);

	if (!error) {
		path = (char *)ocf_volume_get_uuid(ocf_cache_get_volume(
					cache))->data;
		printk(KERN_INFO "Succsessfully attached %s\n", path);
	}

	if (error == -OCF_ERR_NO_FREE_RAM)
		calculate_min_ram_size(cache, ctx);

	caller_status =_cache_mngt_async_callee_set_result(&ctx->async, error);
	if (caller_status != -KCAS_ERR_WAITING_INTERRUPTED)
		return;

	kfree(ctx);
	ocf_mngt_cache_unlock(cache);
	ocf_mngt_cache_put(cache);
}

static void _cache_mngt_start_complete(ocf_cache_t cache, void *priv, int error)
{
	struct _cache_mngt_attach_context *ctx = priv;
	int caller_status;

	cache_mngt_destroy_cache_device_cfg(&ctx->device_cfg);

	if (error == -OCF_ERR_NO_FREE_RAM)
		calculate_min_ram_size(cache, ctx);

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
	uint32_t cpus_no = num_possible_cpus();

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

struct cache_mngt_probe_metadata_context {
	struct completion cmpl;
	char *cache_name;
	int *result;

	char *cache_name_meta;
	ocf_cache_mode_t *cache_mode_meta;
	ocf_cache_line_size_t *cache_line_size_meta;
};

static void cache_mngt_probe_metadata_end(void *priv, int error,
		struct ocf_metadata_probe_status *status)
{
	struct cache_mngt_probe_metadata_context *context = priv;

	*context->result = error;

	if (error == -OCF_ERR_NO_METADATA) {
		printk(KERN_ERR "No cache metadata found!\n");
		goto err;
	} else if (error == -OCF_ERR_METADATA_VER) {
		printk(KERN_ERR "Cache metadata version mismatch\n");
		goto err;
	} else if (error) {
		printk(KERN_ERR "Failed to load cache metadata!\n");
		goto err;
	}

	strscpy(context->cache_name_meta, status->cache_name,
			OCF_CACHE_NAME_SIZE);
	*(context->cache_mode_meta) = status->cache_mode;
	*(context->cache_line_size_meta) = status->cache_line_size;
err:
	complete(&context->cmpl);
}

static int _cache_mngt_probe_metadata(char *cache_path_name,
		char *cache_name_meta, ocf_cache_mode_t *cache_mode_meta,
		ocf_cache_line_size_t *cache_line_size_meta)
{
	struct cache_mngt_probe_metadata_context context;
	cas_bdev_handle_t bdev_handle;
	struct block_device *bdev;
	ocf_volume_t volume;
	char holder[] = "CAS CHECK METADATA\n";
	int result;

	bdev_handle = cas_bdev_open_by_path(cache_path_name,
			(CAS_BLK_MODE_EXCL | CAS_BLK_MODE_READ), holder);
	if (IS_ERR(bdev_handle)) {
		return (PTR_ERR(bdev_handle) == -EBUSY) ?
				-OCF_ERR_NOT_OPEN_EXC :
				-OCF_ERR_INVAL_VOLUME_TYPE;
	}
	bdev = cas_bdev_get_from_handle(bdev_handle);

	result = cas_blk_open_volume_by_bdev(&volume, bdev);
	if (result)
		goto out_bdev;

	init_completion(&context.cmpl);
	context.result = &result;
	context.cache_name_meta = cache_name_meta;
	context.cache_mode_meta = cache_mode_meta;
	context.cache_line_size_meta = cache_line_size_meta;

	ocf_metadata_probe(cas_ctx, volume, cache_mngt_probe_metadata_end,
			&context);
	wait_for_completion(&context.cmpl);

	cas_blk_close_volume(volume);
out_bdev:
	cas_bdev_release(bdev_handle,
			(CAS_BLK_MODE_EXCL | CAS_BLK_MODE_READ), holder);
	return result;
}

static int _volume_set_nomerge_flag_visitor(ocf_volume_t subvol, void *priv,
		ocf_composite_visitor_member_state_t s) {
	struct request_queue *cache_q;
	struct bd_object *bvol;
	struct block_device *bd;

	bvol = bd_object(subvol);
	bd = cas_disk_get_blkdev(bvol->dsk);
	cache_q = bd->bd_disk->queue;

	cas_cache_set_no_merges_flag(cache_q);

	return 0;
}

static void _cache_save_device_properties(ocf_cache_t cache)
{
	struct block_device *bd;
	struct bd_object *bvol;
	struct request_queue *cache_q;
	int vol_type;
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);
	ocf_volume_t cache_vol = ocf_cache_get_volume(cache);
	vol_type = ocf_ctx_get_volume_type_id(cas_ctx,
			ocf_volume_get_type(cache_vol));

	BUG_ON(vol_type != OCF_VOLUME_TYPE_COMPOSITE);

	bvol = bd_object(ocf_composite_volume_get_subvolume_by_index(cache_vol, 0));
	bd = cas_disk_get_blkdev(bvol->dsk);
	cache_q = bd->bd_disk->queue;

	cache_priv->device_properties.queue_limits = cache_q->limits;
	cache_priv->device_properties.flush =
				CAS_CHECK_QUEUE_FLUSH(cache_q);
	cache_priv->device_properties.fua =
				CAS_CHECK_QUEUE_FUA(cache_q);
}

static int _cache_start_finalize(ocf_cache_t cache, int init_mode,
		bool activate)
{
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);
	struct _cache_mngt_attach_context *ctx = cache_priv->attach_context;
	int result;

	_cache_mngt_log_cache_device_path(cache, ctx->cache_path);

	if (activate || (init_mode != CACHE_INIT_STANDBY_NEW &&
			init_mode != CACHE_INIT_STANDBY_LOAD)) {
		result = cas_cls_init(cache);
		if (result) {
			ctx->ocf_start_error = result;
			return result;
		}
		ctx->cls_inited = true;

		_cache_save_device_properties(cache);

		ocf_composite_volume_member_visit(ocf_cache_get_volume(cache),
				_volume_set_nomerge_flag_visitor, NULL,
				ocf_composite_visitor_member_state_attached);
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
	case CACHE_INIT_STANDBY_NEW:
	case CACHE_INIT_STANDBY_LOAD:
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

struct _check_cache_bdev_ctx {
	ocf_cache_t cache;
	bool allow_override_partitions;
	/* The device properties must match the running cache properties */
	bool cmp_running_cache_properties;
	struct {
		struct queue_limits queue_limits;
		bool flush;
		bool fua;
	} device_properties;
	/* The device properties must match `device_properties` field */
	bool cmp_device_properties;
};

static int cache_mngt_check_bdev(ocf_volume_t volume, void *priv,
		ocf_composite_visitor_member_state_t s)
{
	char holder[] = "CAS START\n";
	cas_bdev_handle_t bdev_handle;
	struct block_device *bdev;
	int part_count;
	bool is_part;
	bool reattach_properties_diff = false, composite_properties_diff = false;
	struct cache_priv *cache_priv;
	const struct ocf_volume_uuid *uuid = ocf_volume_get_uuid(volume);
	struct _check_cache_bdev_ctx *ctx = priv;
	/* The only reason to use blk_stack_limits() is checking compatibility of
	   the new device with the original cache. But since the functions modifies
	   content of queue_limits, we use copy of the orignial struct
	   */
	struct queue_limits tmp_limits;

	bdev_handle = cas_bdev_open_by_path(uuid->data,
			(CAS_BLK_MODE_EXCL | CAS_BLK_MODE_READ), holder);
	if (IS_ERR(bdev_handle)) {
		return (PTR_ERR(bdev_handle) == -EBUSY) ?
				-OCF_ERR_NOT_OPEN_EXC :
				-OCF_ERR_INVAL_VOLUME_TYPE;
	}
	bdev = cas_bdev_get_from_handle(bdev_handle);

	is_part = (cas_bdev_whole(bdev) != bdev);
	part_count = cas_blk_get_part_count(bdev);

	if (ctx->cmp_running_cache_properties) {
		ENV_BUG_ON(!ctx->cache);

		cache_priv = ocf_cache_get_priv(ctx->cache);
		tmp_limits = cache_priv->device_properties.queue_limits;

		reattach_properties_diff = blk_stack_limits(&tmp_limits,
				&bdev->bd_disk->queue->limits, 0);
		reattach_properties_diff |= tmp_limits.misaligned;
		reattach_properties_diff |= (
				CAS_CHECK_QUEUE_FLUSH(bdev->bd_disk->queue) !=
				cache_priv->device_properties.flush
				);
		reattach_properties_diff |= (
				CAS_CHECK_QUEUE_FUA(bdev->bd_disk->queue) !=
				cache_priv->device_properties.fua
				);
	}

	if (ctx->cmp_device_properties) {
		tmp_limits = ctx->device_properties.queue_limits;

		composite_properties_diff = blk_stack_limits(&tmp_limits,
				&bdev->bd_disk->queue->limits, 0);
		composite_properties_diff |= tmp_limits.misaligned;
		composite_properties_diff |=
				(CAS_CHECK_QUEUE_FLUSH(bdev->bd_disk->queue) !=
				 ctx->device_properties.flush
				);
		composite_properties_diff |=
				(CAS_CHECK_QUEUE_FUA(bdev->bd_disk->queue) !=
				ctx->device_properties.fua
				);
	}

	cas_bdev_release(bdev_handle,
			(CAS_BLK_MODE_EXCL | CAS_BLK_MODE_READ), holder);

	if (!is_part && part_count > 1 && !ctx->allow_override_partitions)
		return -KCAS_ERR_CONTAINS_PART;

	if (reattach_properties_diff)
		return -KCAS_ERR_DEVICE_PROPERTIES_MISMATCH;

	if (composite_properties_diff)
		return -KCAS_ERR_COMPOSITE_PROPERTIES_INCONSISTENT;

	return 0;
}

static int composite_mngt_get_device_properties(ocf_volume_t volume,
		struct queue_limits *limits, bool *flush, bool *fua)
{
	char holder[] = "CAS START\n";
	cas_bdev_handle_t bdev_handle;
	struct block_device *bdev;
	ocf_volume_t subvol =
		ocf_composite_volume_get_subvolume_by_index(volume, 0);
	const struct ocf_volume_uuid *uuid = ocf_volume_get_uuid(subvol);

	bdev_handle = cas_bdev_open_by_path(uuid->data,
			(CAS_BLK_MODE_EXCL | CAS_BLK_MODE_READ), holder);
	if (IS_ERR(bdev_handle)) {
		return (PTR_ERR(bdev_handle) == -EBUSY) ?
				-OCF_ERR_NOT_OPEN_EXC :
				-OCF_ERR_INVAL_VOLUME_TYPE;
	}
	bdev = cas_bdev_get_from_handle(bdev_handle);

	*limits = bdev->bd_disk->queue->limits;
	*flush = CAS_CHECK_QUEUE_FLUSH(bdev->bd_disk->queue);
	*fua = CAS_CHECK_QUEUE_FUA(bdev->bd_disk->queue);

	cas_bdev_release(bdev_handle,
			(CAS_BLK_MODE_EXCL | CAS_BLK_MODE_READ), holder);

	return 0;
}

static int cache_mngt_check_multi_bdev(ocf_volume_t volume, bool force,
		bool reattach, ocf_cache_t cache)
{
	int ret;
	struct _check_cache_bdev_ctx ctx;
	int volume_type_id = ocf_ctx_get_volume_type_id(cas_ctx,
			ocf_volume_get_type(volume));

	BUG_ON(volume_type_id != OCF_VOLUME_TYPE_COMPOSITE);
	ENV_BUG_ON(reattach && !cache);

	ctx.allow_override_partitions = force;
	ctx.cmp_running_cache_properties = reattach;
	ctx.cmp_device_properties = true;
	ctx.cache = cache;
	ret = composite_mngt_get_device_properties(volume,
			&ctx.device_properties.queue_limits, &ctx.device_properties.flush,
			&ctx.device_properties.fua);
	if (ret)
		return ret;

	return ocf_composite_volume_member_visit(volume, cache_mngt_check_bdev,
			&ctx, ocf_composite_visitor_member_state_attached);
}

int cache_mngt_standby_detach(struct kcas_standby_detach *cmd)
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
		result = -KCAS_ERR_STANDBY_DETACHED;
		goto out_cache_put;
	}

	result = cache_mngt_destroy_cache_exp_obj(cache);
	if (result)
		goto out_cache_put;

	result = _cache_mngt_lock_sync(cache);
	if (result)
		goto out_cache_put;

	ocf_mngt_cache_standby_detach(cache, _cache_mngt_generic_complete,
			&context);

	wait_for_completion(&context.cmpl);
	ocf_mngt_cache_unlock(cache);

out_cache_put:
	ocf_mngt_cache_put(cache);
out_module_put:
	module_put(THIS_MODULE);
	return result;
}

int cache_mngt_create_cache_standby_activate_cfg(
		struct ocf_mngt_cache_standby_activate_config *cfg,
		struct kcas_standby_activate *cmd)
{
	int result;

	if (cmd->cache_id == OCF_CACHE_ID_INVALID)
		return -OCF_ERR_INVAL;

	memset(cfg, 0, sizeof(*cfg));

	result = cache_mngt_create_cache_device_cfg(&cfg->device,
			cmd->cache_path);
	if (result)
		return result;

	cfg->open_cores = true;

	return 0;
}

static void _cache_mngt_detache_cache_complete(ocf_cache_t cache, void *priv,
		int error)
{
	struct _cache_mngt_async_context *context = priv;
	int result;

	result = _cache_mngt_async_callee_set_result(context, error);

	if (result != -KCAS_ERR_WAITING_INTERRUPTED)
		return;

	kfree(context);
	ocf_mngt_cache_unlock(cache);
	kfree(context);
}

static int _update_composite_attach_uuid_visitor(ocf_volume_t subvol,
		void *priv, ocf_composite_visitor_member_state_t s)
{
	ocf_uuid_t new_cuuid = priv;
	char *new_cuuid_str = (char *)new_cuuid->data;
	const struct ocf_volume_uuid *subvol_uuid;
	size_t new_cuuid_tmp_len = env_strnlen(new_cuuid_str, new_cuuid->size);
	int ret = 0;

	if (unlikely(new_cuuid_tmp_len + 2 > new_cuuid->size)) {
		printk(KERN_ERR "The new UUID won't fit the allocated buffer. "
				"Buffer len %zu, buffer content %s\n",
				new_cuuid->size, new_cuuid_str);
		BUG();
	}

	if (new_cuuid_tmp_len > 0) {
		new_cuuid_str[new_cuuid_tmp_len] = ',';
		new_cuuid_tmp_len++;
	}

	if (s & ocf_composite_visitor_member_state_attached) {
		subvol_uuid = ocf_volume_get_uuid(subvol);
		if (new_cuuid_tmp_len + (subvol_uuid->size-1) >
				new_cuuid->size) {

			printk(KERN_ERR "The new UUID won't fit the allocated "
					"buffer. Buffer len %zu, buffer content"
					" %s. Subvol uuid %s\n",
					new_cuuid->size, new_cuuid_str,
					(char *)subvol_uuid->data);
			BUG();
		}

		subvol_uuid = ocf_volume_get_uuid(subvol);
		ret = env_memcpy(new_cuuid_str + new_cuuid_tmp_len,
				new_cuuid->size - new_cuuid_tmp_len,
				subvol_uuid->data, subvol_uuid->size);
		ENV_BUG_ON(ret);
	} else {
		new_cuuid_str[new_cuuid_tmp_len] = '-';
		new_cuuid_tmp_len++;
	}

	return 0;
}

struct kcas_composite_cache_resize_ctx {
	struct _cache_mngt_async_context async_ctx;
	struct ocf_volume_uuid composite_new_uuid;
	struct ocf_volume_uuid tgt_vol_uuid;
	ocf_cache_t cache;
};

static void _cache_mngt_attach_composite_complete(ocf_cache_t cache, void *priv,
		int error)
{
	struct kcas_composite_cache_resize_ctx *context = priv;
	ocf_volume_t cvol = ocf_cache_get_volume(cache);
	int result;

	if (!error) {
		printk(KERN_INFO "%s: Successfully attached %s to composite "
				"cache\n", ocf_cache_get_name(cache),
				(char *)context->tgt_vol_uuid.data);

		ocf_composite_volume_member_visit(cvol,
				_update_composite_attach_uuid_visitor,
				&context->composite_new_uuid,
				ocf_composite_visitor_member_state_any);

		ocf_composite_volume_set_uuid(cvol,
				&context->composite_new_uuid, true);

		ocf_composite_volume_member_visit(ocf_cache_get_volume(cache),
				_volume_set_nomerge_flag_visitor, NULL,
				ocf_composite_visitor_member_state_attached);
	} else {
		printk(KERN_ERR "%s: Failed to attach %s to composite cache\n",
				ocf_cache_get_name(cache),
				(char *)context->tgt_vol_uuid.data);
		vfree(context->composite_new_uuid.data);
	}

	result = _cache_mngt_async_callee_set_result(&context->async_ctx,
			error);

	if (result != -KCAS_ERR_WAITING_INTERRUPTED)
		return;

	ocf_mngt_cache_unlock(cache);
	vfree(context->tgt_vol_uuid.data);
	kfree(context);
	ocf_mngt_cache_put(cache);
}

static void _cache_mngt_detach_composite_complete(ocf_cache_t cache, void *priv,
		int error)
{
	struct kcas_composite_cache_resize_ctx *context = priv;
	ocf_volume_t cvol = ocf_cache_get_volume(cache);
	int result;

	if (!error) {
		printk(KERN_INFO "%s: Successfully detached %s from composite "
				"cache\n", ocf_cache_get_name(cache),
				(char *)context->tgt_vol_uuid.data);

		ocf_composite_volume_member_visit(cvol,
				_update_composite_attach_uuid_visitor,
				&context->composite_new_uuid,
				ocf_composite_visitor_member_state_any);

		ocf_composite_volume_set_uuid(cvol,
				&context->composite_new_uuid, true);
	} else {
		printk(KERN_ERR "%s: Failed to detach %s from composite cache"
				"\n", ocf_cache_get_name(cache),
				(char *)context->tgt_vol_uuid.data);

		vfree(context->composite_new_uuid.data);
	}

	result = _cache_mngt_async_callee_set_result(&context->async_ctx,
			error);

	if (result != -KCAS_ERR_WAITING_INTERRUPTED)
		return;

	ocf_mngt_cache_unlock(cache);
	vfree(context->tgt_vol_uuid.data);
	kfree(context);
	ocf_mngt_cache_put(cache);
}

int cache_mngt_attach_device(const char *cache_name, size_t name_len,
		const char *device, struct ocf_mngt_cache_attach_config *attach_cfg)
{
	struct _cache_mngt_attach_context *context;
	ocf_cache_t cache;
	int result = 0;

	result = ocf_mngt_cache_get_by_name(cas_ctx, cache_name,
			OCF_CACHE_NAME_SIZE, &cache);
	if (result)
		goto err_get;

	result = _cache_mngt_lock_sync(cache);
	if (result)
		goto err_lock;

	result = cache_mngt_check_multi_bdev(attach_cfg->device.volume,
			attach_cfg->force, true, cache);
	if (result)
		goto err_ctx;

	context = kzalloc(sizeof(*context), GFP_KERNEL);
	if (!context) {
		result = -ENOMEM;
		goto err_ctx;
	}

	context->device_cfg = attach_cfg->device;

	_cache_mngt_async_context_init(&context->async);

	ocf_mngt_cache_attach(cache, attach_cfg, _cache_mngt_attach_complete,
			context);
	result = wait_for_completion_interruptible(&context->async.cmpl);

	result = _cache_mngt_async_caller_set_result(&context->async, result);
	if (result == -KCAS_ERR_WAITING_INTERRUPTED)
		goto err_get;

	kfree(context);
err_ctx:
	ocf_mngt_cache_unlock(cache);
err_lock:
	ocf_mngt_cache_put(cache);
err_get:
	return result;
}

int cache_mngt_activate(struct ocf_mngt_cache_standby_activate_config *cfg,
		struct kcas_standby_activate *cmd)
{
	struct _cache_mngt_attach_context *context;
	ocf_cache_t cache;
	struct cache_priv *cache_priv;
	char cache_name[OCF_CACHE_NAME_SIZE];
	int result = 0, rollback_result = 0;

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

	/*
	 * We ignore partitions detected on the cache device despite we
	 * know at this point that activate is gonna fail. We want OCF
	 * to compare data on drive and in DRAM to provide more specific
	 * error code.
	 */
	result = cache_mngt_check_multi_bdev(cfg->device.volume, true, false,
			NULL);
	if (result)
		goto out_cache_unlock;

	context = kzalloc(sizeof(*context), GFP_KERNEL);
	if (!context) {
		result = -ENOMEM;
		goto out_cache_unlock;
	}

	strncpy(context->cache_path, cmd->cache_path, MAX_STR_LEN-1);
	context->device_cfg = cfg->device;
	context->cache = cache;

	cache_priv = ocf_cache_get_priv(cache);
	cache_priv->attach_context = context;
	/* All the required memory has been alocated and initialized on cache_init,
	 * just set the flag to allow deinit*/
	context->priv_inited = true;

	context->rollback_thread = cas_lazy_thread_create(cache_start_rollback,
			context, "cas_cache_rollback_complete");
	if (IS_ERR(context->rollback_thread)) {
		result = PTR_ERR(context->rollback_thread);
		goto err_free_context;
	}
	_cache_mngt_async_context_init(&context->async);

	ocf_mngt_cache_standby_activate(cache, cfg, _cache_mngt_start_complete,
			context);
	result = wait_for_completion_interruptible(&context->async.cmpl);

	result = _cache_mngt_async_caller_set_result(&context->async, result);
	if (result == -KCAS_ERR_WAITING_INTERRUPTED)
		goto out_cache_put;
	if (result)
		goto activate_err;

	result = _cache_start_finalize(cache, -1, true);
	if (result)
		goto finalize_err;

activate_err:
	cas_lazy_thread_stop(context->rollback_thread);

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

finalize_err:
	_cache_mngt_async_context_reinit(&context->async);
	ocf_mngt_cache_stop(cache, _cache_mngt_cache_stop_rollback_complete,
			context);
	rollback_result = wait_for_completion_interruptible(&context->async.cmpl);

	rollback_result = _cache_mngt_async_caller_set_result(&context->async,
							rollback_result);

	if (rollback_result != -KCAS_ERR_WAITING_INTERRUPTED)
		kfree(context);

	module_put(THIS_MODULE);
	return result;
}

static void _cache_mngt_add_upper_cmpl(ocf_cache_t cache, ocf_cache_t lower_cache,
				 void *priv, int err)
{
	struct _cache_mngt_sync_context *ctx = priv;

	*ctx->result = err;
	complete(&ctx->cmpl);
}

int cache_mngt_init_instance(struct ocf_mngt_cache_config *cfg,
		struct ocf_mngt_cache_attach_config *attach_cfg,
		struct kcas_start_cache *cmd)
{
	struct _cache_mngt_attach_context *context;
	struct _cache_mngt_sync_context sync_ctx;
	ocf_cache_t cache, tmp_cache, lower_cache = NULL;
	char cache_name_meta[OCF_CACHE_NAME_SIZE];
	char lower_cache_name[OCF_CACHE_NAME_SIZE];
	struct cache_priv *cache_priv;
	int result = 0, rollback_result = 0;
	ocf_cache_mode_t cache_mode_meta;
	ocf_cache_line_size_t cache_line_size_meta;

	if (!try_module_get(THIS_MODULE)) {
		ocf_volume_destroy(attach_cfg->device.volume);
		return -KCAS_ERR_SYSTEM;
	}

	result = cache_mngt_check_multi_bdev(attach_cfg->device.volume,
			attach_cfg->force, false, NULL);
	if (result) {
		module_put(THIS_MODULE);
		return result;
	}

	switch (cmd->init_cache) {
	case CACHE_INIT_LOAD:
	case CACHE_INIT_STANDBY_LOAD:
		result = _cache_mngt_probe_metadata(cmd->cache_path_name,
				cache_name_meta, &cache_mode_meta,
				&cache_line_size_meta);
		if (result) {
			ocf_volume_destroy(attach_cfg->device.volume);
			module_put(THIS_MODULE);
			return result;
		}

		/* Need to return name from metadata now for caller to properly
		 * communicate the error to user */
		if (cache_id_from_name(&cmd->cache_id, cache_name_meta)) {
			printk(KERN_ERR "Improper cache name format on %s.\n",
					cmd->cache_path_name);

			ocf_volume_destroy(attach_cfg->device.volume);
			module_put(THIS_MODULE);
			return -OCF_ERR_START_CACHE_FAIL;
		}

		result = ocf_mngt_cache_get_by_name(cas_ctx, cache_name_meta,
				OCF_CACHE_NAME_SIZE, &tmp_cache);

		if (result != -OCF_ERR_CACHE_NOT_EXIST) {
			printk(KERN_ERR "Can't load %s. Cache using that name "
					"already exists.\n", cache_name_meta);

			ocf_mngt_cache_put(tmp_cache);
			ocf_volume_destroy(attach_cfg->device.volume);
			module_put(THIS_MODULE);
			return -OCF_ERR_CACHE_EXIST;
		}

		result = 0;
		strscpy(cfg->name, cache_name_meta, OCF_CACHE_NAME_SIZE);
		cfg->cache_mode = cache_mode_meta;
		cfg->cache_line_size = cache_line_size_meta;
	default:
		break;
	}

	if (cmd->lower_cache_id != OCF_CACHE_ID_INVALID) {
		cache_name_from_id(lower_cache_name, cmd->lower_cache_id);

		result = ocf_mngt_cache_get_by_name(cas_ctx, lower_cache_name,
				      sizeof(lower_cache_name), &lower_cache);
		if (result) {
			ocf_volume_destroy(attach_cfg->device.volume);
			module_put(THIS_MODULE);
			printk(KERN_WARNING "Cache with id %u doesn't exist.\n",
					cmd->lower_cache_id);
			return result;
		}

		if (ocf_cache_ml_is_upper(lower_cache)) {
			ocf_mngt_cache_put(lower_cache);
			ocf_volume_destroy(attach_cfg->device.volume);
			module_put(THIS_MODULE);
			printk(KERN_WARNING "Cache with id %u isn't the main "
					"cache in the multi-level stack.\n",
					cmd->lower_cache_id);
			return -OCF_ERR_CACHE_NOT_MAIN;
		}

		result = cache_ml_get(lower_cache);
		if (result) {
			ocf_mngt_cache_put(lower_cache);
			ocf_volume_destroy(attach_cfg->device.volume);
			module_put(THIS_MODULE);
			return result;
		}

		ocf_mngt_cache_put(lower_cache);
	}

	context = kzalloc(sizeof(*context), GFP_KERNEL);
	if (!context) {
		result = -ENOMEM;
		goto err_prestart;
	}

	context->rollback_thread = cas_lazy_thread_create(cache_start_rollback,
			context, "cas_cache_rollback_complete");
	if (IS_ERR(context->rollback_thread)) {
		result = PTR_ERR(context->rollback_thread);
		kfree(context);
		goto err_prestart;
	}

	strncpy(context->cache_path, cmd->cache_path_name, MAX_STR_LEN-1);
	context->device_cfg = attach_cfg->device;
	_cache_mngt_async_context_init(&context->async);

	/* Start cache. Returned cache instance will be locked as it was set
	 * in configuration.
	 */
	result = ocf_mngt_cache_start(cas_ctx, &cache, cfg, NULL);
	if (result) {
		cas_lazy_thread_stop(context->rollback_thread);
		kfree(context);
		goto err_prestart;
	}
	context->cache = cache;

	result = _cache_mngt_cache_priv_init(cache);
	if (result) {
		ocf_volume_destroy(attach_cfg->device.volume);
		goto err;
	}
	context->priv_inited = true;

	result = _cache_mngt_start_queues(cache);
	if (result) {
		ocf_volume_destroy(attach_cfg->device.volume);
		goto err;
	}

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
	case CACHE_INIT_STANDBY_NEW:
		ocf_mngt_cache_standby_attach(cache, attach_cfg,
				_cache_mngt_start_complete, context);
		break;
	case CACHE_INIT_STANDBY_LOAD:
		ocf_mngt_cache_standby_load(cache, attach_cfg,
				_cache_mngt_start_complete, context);
		break;
	default:
		result = -OCF_ERR_INVAL;
		goto err;
	}
	result = wait_for_completion_interruptible(&context->async.cmpl);

	result = _cache_mngt_async_caller_set_result(&context->async, result);
	if (result == -KCAS_ERR_WAITING_INTERRUPTED) {
		ocf_mngt_cache_put(lower_cache);
		return result;
	}

	if (result)
		goto err;

	result = _cache_start_finalize(cache, cmd->init_cache, false);
	if (result)
		goto err;

	if (lower_cache) {
		result = cache_ml_lock(lower_cache);
		if (result)
			goto err;

		sync_ctx.result = &result;
		init_completion(&sync_ctx.cmpl);

		ocf_mngt_cache_ml_add_cache(lower_cache, cache,
				 _cache_mngt_add_upper_cmpl, &sync_ctx);

		wait_for_completion(&sync_ctx.cmpl);
		if (result) {
			printk(KERN_WARNING "Couldn't add upper cache %d\n",
					result);
			cache_ml_unlock(lower_cache);
			goto err;
		}

		/* At this point the cache is part of multi-level stack,
		 * so cache_ml_put() is going to affect is, thus we need
		 * to get it once again to compensate.
		 */
		result = ocf_mngt_cache_get(cache);
		BUG_ON(result);

		cache_ml_put(lower_cache);
	}

	cas_lazy_thread_stop(context->rollback_thread);

	kfree(context);
	cache_priv->attach_context = NULL;

	if (lower_cache)
		cache_ml_unlock(lower_cache);
	else
		ocf_mngt_cache_unlock(cache);

	return result;

err:
	if (lower_cache)
		cache_ml_put(lower_cache);

	cmd->min_free_ram = context->min_free_ram;

	_cache_mngt_async_context_reinit(&context->async);
	ocf_mngt_cache_stop(cache, _cache_mngt_cache_stop_rollback_complete,
			context);
	rollback_result = wait_for_completion_interruptible(&context->async.cmpl);

	rollback_result = _cache_mngt_async_caller_set_result(&context->async,
			rollback_result);

	if (rollback_result != -KCAS_ERR_WAITING_INTERRUPTED)
		kfree(context);

	return result;

/* No fallback here. It's meant to be a separate error path. */
err_prestart:
	if (lower_cache)
		cache_ml_put(lower_cache);
	ocf_volume_destroy(attach_cfg->device.volume);
	module_put(THIS_MODULE);

	return result;
}

/**
 * @brief routine implementing get OCF parameter
 * @param[in] cache cache to which the change pertains
 * @param[in] core core to which the change pertains
 * or NULL for setting value for all cores attached to specified cache
 * @param[in] param_name OCF parameter name (ocf_prefetcher, ocf_classifier etc ...)
 * @param[in] list list of policies and values
 * @return exit code of successful completion is 0;
 * nonzero exit code means failure
 */

static int _cache_mngt_get_ocf_param(ocf_cache_t cache, ocf_core_t core,
		const char *param_name, struct ocf_policy_list *list)
{
	int result;

	result = _cache_mngt_lock_sync(cache);
	if (result)
		return result;

	if (core) {
		result = ocf_core_get_ocf_param_value(core, param_name, list);
	} else {
		result = ocf_cache_get_ocf_param_value(cache, param_name, list);
	}

	ocf_mngt_cache_unlock(cache);
	return result;
}

/**
 * @brief routine implementing dynamic set of OCF parameter
 * @param[in] cache cache to which the change pertains
 * @param[in] core core to which the change pertains
 * or NULL for setting value for all cores attached to specified cache
 * @param[in] param_name OCF parameter name (ocf_prefetcher, ocf_classifier etc ...)
 * @param[in] enable enable or disable parameter
 * @param[in] list list of policies to enable or disable (optional)
 * @return exit code of successful completion is 0;
 * nonzero exit code means failure
 */

static int _cache_mngt_set_ocf_param(ocf_cache_t cache, ocf_core_t core,
		const char *param_name, bool enable, struct ocf_policy_list *list)
{
	int result;

	result = _cache_mngt_lock_sync(cache);
	if (result)
		return result;

	if (core) {
		result = ocf_core_set_ocf_param(core, param_name, enable, list);
	} else {
		result = ocf_cache_set_ocf_param(cache, param_name, enable, list);
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

static int cache_mngt_set_seq_cutoff_promotion_count(ocf_cache_t cache,
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

static int cache_mngt_get_seq_cutoff_promotion_count(ocf_core_t core,
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

	if (ocf_cache_is_standby(cache)) {
		result = -OCF_ERR_CACHE_STANDBY;
		goto put;
	}

	if (!ocf_cache_is_device_attached(cache)) {
		result = -OCF_ERR_CACHE_DETACHED;
		goto put;
	}

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

#define UUID_SHRINK -1
#define UUID_EXPAND 1
static int _composite_resize_prepare_uuid(ocf_cache_t cache,
		ocf_uuid_t new_cuuid, uint32_t tgt_vol_path_len, int shrink)
{
	size_t new_cuuid_size;
	int missing_subvol_mark;

	if (shrink != UUID_SHRINK && shrink != UUID_EXPAND)
		return -EINVAL;

	/* The detached path is substituted with a dash so an additional byte
	 * must be allocated. On sub volume attach the byte must be freed
	 */
	missing_subvol_mark = (shrink == UUID_SHRINK ? 1 : -1);

	new_cuuid_size = ocf_volume_get_uuid(ocf_cache_get_volume(cache))->size;
	new_cuuid_size += shrink * (int)tgt_vol_path_len;
	new_cuuid_size += missing_subvol_mark;

	if (new_cuuid_size < 0 || new_cuuid_size >= OCF_VOLUME_UUID_MAX_SIZE) {
		printk(KERN_ERR "Invalid composite UUID size\n");
		return -EINVAL;
	}

	new_cuuid->data = vzalloc(new_cuuid_size);
	if (!new_cuuid->data)
		return -ENOMEM;

	new_cuuid->size = new_cuuid_size;

	return 0;
}

int cache_mngt_composite_cache_detach(const char *cache_name, size_t name_len,
		char *target_subvol_path, size_t target_size_max_len)
{
	ocf_cache_t cache;
	int status = 0;
	struct kcas_composite_cache_resize_ctx *context;
	size_t tgt_path_len = strnlen(target_subvol_path, target_size_max_len);

	if (tgt_path_len == 0 || tgt_path_len >= MAX_STR_LEN)
		return -EINVAL;

	context = kzalloc(sizeof(struct kcas_composite_cache_resize_ctx),
			GFP_KERNEL);
	if (!context)
		return -ENOMEM;

	_cache_mngt_async_context_init(&context->async_ctx);

	context->tgt_vol_uuid.size = tgt_path_len + 1;

	context->tgt_vol_uuid.data = vzalloc(context->tgt_vol_uuid.size);
	if (!context->tgt_vol_uuid.data) {
		status = -OCF_ERR_NO_MEM;
		goto err_tgt_vol_uuid;
	}

	status = env_memcpy(context->tgt_vol_uuid.data,
			context->tgt_vol_uuid.size,
			target_subvol_path, tgt_path_len);
	BUG_ON(status);

	status = ocf_mngt_cache_get_by_name(cas_ctx, cache_name, name_len,
			&cache);
	if (status)
		goto err_get_cache;

	if (ocf_cache_is_running(cache))
		status = _cache_flush_with_lock(cache);
	if (status)
		goto err_flush;

	status = _cache_mngt_lock_sync(cache);
	if (status)
		goto err_lock;

	status = _composite_resize_prepare_uuid(cache,
			&context->composite_new_uuid, tgt_path_len,
			UUID_SHRINK);
	if (status)
		goto err_new_cuuid;

	ocf_mngt_cache_detach_composite(cache,
			_cache_mngt_detach_composite_complete,
			&context->tgt_vol_uuid, context);
	status = wait_for_completion_interruptible(&context->async_ctx.cmpl);
	status = _cache_mngt_async_caller_set_result(&context->async_ctx,
			status);
	if (status == -KCAS_ERR_WAITING_INTERRUPTED) {
		printk(KERN_WARNING "Waiting for cache detach interrupted. "
				"The operation will finish asynchronously.\n");
		goto end;
	}

err_new_cuuid:
	ocf_mngt_cache_unlock(cache);
err_lock:
err_flush:
	ocf_mngt_cache_put(cache);
err_get_cache:
	vfree(context->tgt_vol_uuid.data);
err_tgt_vol_uuid:
	kfree(context);
end:
	return status;
}

static int _attach_composite_check_bdev(ocf_cache_t cache, ocf_uuid_t uuid,
		ocf_volume_type_t type, bool force)
{
	int ret;
	ocf_volume_t vol;
	struct _check_cache_bdev_ctx ctx = {};

	ret = ocf_volume_create(&vol, type, uuid);
	if (ret)
		goto end;

	ctx.allow_override_partitions = force;
	ctx.cmp_running_cache_properties = true;
	ctx.cache = cache;

	ret = cache_mngt_check_bdev(vol, &ctx, 0);

	ocf_volume_destroy(vol);
end:
	return ret;

}

int cache_mngt_attach_composite_cache(const char *cache_name, size_t name_len,
		uint8_t tgt_subvol_id, char *new_vol_path,
		size_t new_vol_path_max_len, bool force)
{
	ocf_cache_t cache;
	int status = 0;
	struct kcas_composite_cache_resize_ctx *context;
	ocf_volume_type_t vol_type;
	uint8_t vol_type_id;
	size_t tgt_vol_uuid_size;

	tgt_vol_uuid_size = env_strnlen(new_vol_path, new_vol_path_max_len);
	if (tgt_vol_uuid_size >= OCF_VOLUME_UUID_MAX_SIZE ||
			tgt_vol_uuid_size == 0) {
		return -OCF_ERR_INVAL;
	}

	status = ocf_mngt_cache_get_by_name(cas_ctx, cache_name, name_len,
			&cache);
	if (status)
		return status;

	status = cas_blk_identify_type(new_vol_path, &vol_type_id);
	if (status) {
		status = -OCF_ERR_INVAL;
		goto err_put;
	}

	vol_type = ocf_ctx_get_volume_type(cas_ctx, vol_type_id);
	if (status) {
		status = -OCF_ERR_INVAL;
		goto err_put;
	}

	context = kzalloc(sizeof(struct kcas_composite_cache_resize_ctx),
			GFP_KERNEL);
	if (!context) {
		status = -OCF_ERR_NO_MEM;
		goto err_put;
	}
	_cache_mngt_async_context_init(&context->async_ctx);

	status = _cache_mngt_lock_sync(cache);
	if (status)
		goto err_lock;

	context->tgt_vol_uuid.size = tgt_vol_uuid_size + 1;
	context->tgt_vol_uuid.data = vzalloc(context->tgt_vol_uuid.size);
	if (!context->tgt_vol_uuid.data) {
		status = -OCF_ERR_NO_MEM;
		goto err_tgt_vol_uuid;
	}
	status = env_memcpy(context->tgt_vol_uuid.data,
			context->tgt_vol_uuid.size,
			new_vol_path, new_vol_path_max_len);
	BUG_ON(status);

	status = _attach_composite_check_bdev(cache, &context->tgt_vol_uuid,
			vol_type, force);
	if (status)
		goto err_cuuid;

	status = _composite_resize_prepare_uuid(cache,
			&context->composite_new_uuid, tgt_vol_uuid_size,
			UUID_EXPAND);
	if (status)
		goto err_cuuid;

	ocf_mngt_cache_attach_composite(cache, &context->tgt_vol_uuid,
			tgt_subvol_id, vol_type, NULL,
			_cache_mngt_attach_composite_complete,
			&context->async_ctx);

	status = wait_for_completion_interruptible(&context->async_ctx.cmpl);
	status = _cache_mngt_async_caller_set_result(&context->async_ctx,
			status);
	if (status == -KCAS_ERR_WAITING_INTERRUPTED) {
		printk(KERN_WARNING "Composite attach interrupted. "
				"The operation will finish asynchronously.\n");
		goto end;
	}


err_cuuid:
	vfree(context->tgt_vol_uuid.data);
err_tgt_vol_uuid:
	ocf_mngt_cache_unlock(cache);
err_lock:
	kfree(context);
err_put:
	ocf_mngt_cache_put(cache);
end:
	return status;
}

int cache_mngt_detach_cache(const char *cache_name, size_t name_len)
{
	ocf_cache_t cache;
	int status = 0;
	struct _cache_mngt_async_context *context;

	context = kmalloc(sizeof(*context), GFP_KERNEL);
	if (!context)
		return -ENOMEM;

	_cache_mngt_async_context_init(context);

	status = ocf_mngt_cache_get_by_name(cas_ctx, cache_name,
					name_len, &cache);
	if (status)
		goto err_get_cache;

	if (ocf_cache_is_running(cache))
		status = _cache_flush_with_lock(cache);
	if (status)
		goto err_flush;

	status = _cache_mngt_lock_sync(cache);
	if (status)
		goto err_lock;

	ocf_mngt_cache_detach(cache, _cache_mngt_detache_cache_complete, context);

	status = wait_for_completion_interruptible(&context->cmpl);
	status = _cache_mngt_async_caller_set_result(context, status);

	if (status == -KCAS_ERR_WAITING_INTERRUPTED) {
		printk(KERN_WARNING "Waiting for cache detach interrupted. "
				"The operation will finish asynchronously.\n");
		goto err_int;
	}

	ocf_mngt_cache_unlock(cache);
err_lock:
err_flush:
	ocf_mngt_cache_put(cache);
err_get_cache:
	kfree(context);
err_int:
	return status;
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
	int status = 0, flush_status = 0;
	struct _cache_mngt_stop_context *context;

	status = ocf_mngt_cache_get_by_name(cas_ctx, cache_name, name_len,
			&cache);
	if (status)
		return status;

	status = cache_ml_get(cache);
	/* Resolving cache name has a side effect of incrementing the refcnt */
	ocf_mngt_cache_put(cache);
	if (status)
		return status;

	/*
	 * Flush cache. Flushing may take a long time, so we allow user
	 * to interrupt this operation. Hence we do first flush before
	 * disabling exported object to avoid restoring it in case
	 * of interruption. That means some new dirty data could appear
	 * in cache during flush operation which will not be flushed
	 * this time, so we need to flush cache again after disabling
	 * exported object. The second flush should be much faster.
	*/
	if (flush)
		status = _flush_ml_cache(cache);
	if (status)
		goto put;

	status = cache_ml_lock(cache);
	if (status)
		goto put;

	cache_priv = ocf_cache_get_priv(cache);
	context = cache_priv->stop_context;

	context->cache_ml_levels = cache_ml_get_level_count(cache);
	if (context->cache_ml_levels == -1) {
		status = -EINVAL;
		goto unlock;
	}

	context->cache_ml_ptrs = vzalloc(
			sizeof(ocf_cache_t) * context->cache_ml_levels
			);
	if (!context->cache_ml_ptrs) {
		status = -ENOMEM;
		goto unlock;
	}

	status = cache_ml_get_ptrs(cache, context->cache_ml_ptrs,
			context->cache_ml_levels);
	if (status)
		goto free_ml_cache_ptrs_buffer;

	context->finish_thread = cas_lazy_thread_create(exit_instance_finish,
			context, "cas_%s_stop", cache_name);
	if (IS_ERR(context->finish_thread)) {
		status = PTR_ERR(context->finish_thread);
		goto free_ml_cache_ptrs_buffer;
	}

	if (!ocf_cache_is_standby(cache)) {
		status = kcas_cache_destroy_all_core_exported_objects(cache);
		if (status != 0) {
			printk(KERN_WARNING
					"Failed to remove all cached devices\n");
			goto stop_thread;
		}
	} else {
		status = cache_mngt_destroy_cache_exp_obj(cache);
		if (status != 0) {
			printk(KERN_WARNING
					"Failed to remove cache exported object\n");
			goto stop_thread;
		}
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
free_ml_cache_ptrs_buffer:
	vfree(context->cache_ml_ptrs);
unlock:
	cache_ml_unlock(cache);
put:
	cache_ml_put(cache);
	return status;
}

static int remove_instance_finish(void *data)
{
	struct cache_priv *cache_priv;
	struct _cache_mngt_stop_context *stop_ctx = data;
	ocf_queue_t mngt_queue;
	int result = 0;

	if (stop_ctx->error && stop_ctx->error != -OCF_ERR_WRITE_CACHE)
		BUG_ON(stop_ctx->error);

	if (!stop_ctx->error && stop_ctx->flush_status)
		result = -KCAS_ERR_STOPPED_DIRTY;
	else
		result = stop_ctx->error;

	if (!ocf_cache_is_standby(stop_ctx->cache))
		cas_cls_deinit(stop_ctx->cache);

	cache_priv = ocf_cache_get_priv(stop_ctx->cache);
	mngt_queue = cache_priv->mngt_queue;

	vfree(cache_priv);

	ocf_mngt_cache_unlock(stop_ctx->cache);
	ocf_mngt_cache_put(stop_ctx->cache);
	ocf_queue_put(mngt_queue);

	result = _cache_mngt_async_callee_set_result(&stop_ctx->async, result);

	if (result == -KCAS_ERR_WAITING_INTERRUPTED)
		kfree(stop_ctx);

	CAS_MODULE_PUT_AND_EXIT(0);
}

static void _cache_mngt_remove_complete(ocf_cache_t main_cache,
		ocf_cache_t removed_cache, void *priv, int error)
{
	struct _cache_mngt_async_context *context = priv;
	struct cache_priv *cache_priv;
	struct _cache_mngt_stop_context *stop_context;
	int result;

	result = _cache_mngt_async_callee_set_result(context, error);
	if (result != -KCAS_ERR_WAITING_INTERRUPTED)
		return;

	cache_priv = ocf_cache_get_priv(removed_cache);
	stop_context = cache_priv->stop_context;

	if (!error) {
		ocf_mngt_cache_unlock(removed_cache);
		ocf_mngt_cache_put(removed_cache);
	}
	
	cache_ml_unlock(main_cache);
	cache_ml_put(main_cache);
	cas_lazy_thread_stop(stop_context->finish_thread);
	stop_context->finish_thread = NULL;
	kfree(context);
}

int cache_mngt_remove(const char *cache_name, size_t name_len)
{
	ocf_cache_t cache, main_cache;
	struct cache_priv *cache_priv;
	int status = 0;
	struct _cache_mngt_stop_context *stop_context;
	struct _cache_mngt_async_context *async_ctx;

	status = ocf_mngt_cache_get_by_name(cas_ctx, cache_name, name_len,
			&cache);
	if (status)
		return status;

	main_cache = ocf_cache_ml_get_lowest_cache(cache);

	status = cache_ml_get(main_cache);
	if (status) {
		ocf_mngt_cache_put(cache);
		return status;
	}

	/* Because of calling ocf_mngt_cache_get_by_name() and cache_ml_get()
	   the target cache's refcnt is incremented twice, but keeping only one
	   reference throughout the remove operation is sufficient as well.
	   Decrement it ASAP */
	ocf_mngt_cache_put(cache);

	if (ocf_cache_ml_is_lower(cache)) {
		printk(KERN_ERR "%s: only the top caches can be removed\n",
				ocf_cache_get_name(cache));
		status = -EINVAL;
		goto put;
	}

	if (ocf_cache_is_device_attached(cache)) {
		status = _cache_flush_with_lock(cache);
		if (status)
			goto put;
	}

	status = cache_ml_lock(main_cache);
	if (status)
		goto put;

	// Re-check the topology after locking the main cache
	if (ocf_cache_ml_is_lower(cache)) {
		printk(KERN_ERR "%s: only the top caches can be removed\n",
				ocf_cache_get_name(cache));
		status = -EINVAL;
		goto unlock;
	}

	async_ctx = kmalloc(sizeof(*async_ctx), GFP_KERNEL);
	if (!async_ctx) {
		status = -ENOMEM;
		goto unlock;
	}
	_cache_mngt_async_context_init(async_ctx);

	cache_priv = ocf_cache_get_priv(cache);
	stop_context = cache_priv->stop_context;

	stop_context->finish_thread = cas_lazy_thread_create(
			remove_instance_finish, stop_context, "cas_%s_stop",
			cache_name);
	if (IS_ERR(stop_context->finish_thread)) {
		status = PTR_ERR(stop_context->finish_thread);
		goto free_ctx;
	}

	ocf_mngt_cache_ml_remove_cache(main_cache,
			_cache_mngt_remove_complete, async_ctx);
	status = wait_for_completion_interruptible(&async_ctx->cmpl);
	status = _cache_mngt_async_caller_set_result(async_ctx,
			status);
	if (status == -KCAS_ERR_WAITING_INTERRUPTED) {
		printk(KERN_WARNING
				"Waiting for cache remove interrupted. "
				"Cache has been removed from multi-level.\n");
		return status;
	} else if (status) {
		goto cancel_thread;
	}

	kfree(async_ctx);

	cache_ml_unlock(main_cache);
	cache_ml_put(main_cache);

	/* Stop cache device - ignore interrupts */
	status = _cache_mngt_cache_stop_sync(cache);
	if (status == -KCAS_ERR_WAITING_INTERRUPTED) {
		printk(KERN_WARNING
				"Waiting for cache stop interrupted. "
				"Stop will finish asynchronously.\n");
		return status;
	}

	return status;

cancel_thread:
	cas_lazy_thread_stop(stop_context->finish_thread);
	stop_context->finish_thread = NULL;
free_ctx:
	kfree(async_ctx);
unlock:
	cache_ml_unlock(main_cache);
put:
	cache_ml_put(main_cache);

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

#ifdef OCF_DEBUG_STATS
static int composite_volume_get_member_stats(ocf_cache_t cache,
	struct kcas_get_stats *stats)
{
	int result;
	struct stats_ctx stats_ctx= { stats->core_id, stats->part_id,
				      stats->composite_volume_member_id };
	if (stats->core_id == OCF_CORE_ID_INVALID &&
		stats->part_id == OCF_IO_CLASS_INVALID) {
		result = ocf_composite_volume_get_member_stats(cache, stats_ctx,
				&stats->blocks, _composite_volume_member_stats_cache);
	} else if (stats->part_id == OCF_IO_CLASS_INVALID) {
		result = ocf_composite_volume_get_member_stats(cache, stats_ctx,
				&stats->blocks, _composite_volume_member_stats_core);
	} else {
		if (stats->core_id == OCF_CORE_ID_INVALID) {
			result = ocf_composite_volume_get_member_stats(cache, stats_ctx,
					&stats->blocks,
					_composite_volume_member_stats_part_cache);
		} else {
			result = ocf_composite_volume_get_member_stats(cache, stats_ctx,
					&stats->blocks,
					_composite_volume_member_stats_part_core);
		}
	}
	return result;
}
#endif

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

#ifdef OCF_DEBUG_STATS
	if (stats->composite_volume_member_id != OCF_COMPOSITE_VOLUME_MEMBER_ID_INVALID){
		result = composite_volume_get_member_stats(cache, stats);
		if (result)
			goto unlock;
	} else
#endif
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
	uint16_t upper_cache_id = OCF_CACHE_ID_INVALID;
	uint16_t lower_cache_id = OCF_CACHE_ID_INVALID;

	result = mngt_get_cache_by_id(cas_ctx, info->cache_id, &cache);
	if (result)
		return result;

	result = _cache_mngt_read_lock_sync(cache);
	if (result)
		goto put;

	if (ocf_cache_ml_is_lower(cache)) {
		 result = cache_id_from_name(
				&upper_cache_id,
				ocf_cache_get_name(
					ocf_cache_ml_get_upper_cache(cache)
					)
				);
		 if (result)
			 goto put;
	}
	if (ocf_cache_ml_is_upper(cache)) {
		 result = cache_id_from_name(
				&lower_cache_id,
				ocf_cache_get_name(
					ocf_cache_ml_get_lower_cache(cache)
					)
				);
		 if (result)
			 goto put;
	}

	result = ocf_cache_get_info(cache, &info->info);
	if (result)
		goto unlock;

	if (info->info.attached && !info->info.standby_detached) {
		uuid = ocf_cache_get_uuid(cache);
		BUG_ON(!uuid);
		strscpy(info->cache_path_name, uuid->data,
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

	info->upper_level_cache_id = upper_cache_id;
	info->lower_level_cache_id = lower_cache_id;

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
	ocf_volume_t vol;
	struct bd_object *bdvol;
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
		strscpy(info->core_path_name, uuid->data,
				min(sizeof(info->core_path_name), uuid->size));
	}

	info->state = ocf_core_get_state(core);

	vol = ocf_core_get_volume(ocf_cache_ml_get_lowest_core(core));
	bdvol = bd_object(vol);
	info->exp_obj_exists = bdvol->expobj_valid;

unlock:
	ocf_mngt_cache_read_unlock(cache);
put:
	ocf_mngt_cache_put(cache);
	return result;
}

int cache_mngt_get_ocf_param(struct kcas_get_ocf_param *info)
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
	info->list.list_size = 0;

	result = _cache_mngt_get_ocf_param(cache, core, info->param_name, &info->list);

out:
	info->ext_err_code = result;
	ocf_mngt_cache_put(cache);
	return result;
}

int cache_mngt_set_ocf_param(struct kcas_set_ocf_param *info)
{
	ocf_cache_t cache;
	ocf_core_t core = NULL;
	struct ocf_policy_list list;
	int result;
	char *policy = info->policy[0] == '\0' ? NULL : info->policy;

	result = mngt_get_cache_by_id(cas_ctx, info->cache_id, &cache);
	if (result)
		return result;

	if (info->core_id != OCF_CORE_ID_INVALID) {
		result = get_core_by_id(cache, info->core_id, &core);
		if (result)
			goto out;
	}
	ocf_parse_policy_list(policy, &list);
	result = _cache_mngt_set_ocf_param(cache, core, info->param_name, info->enable, &list);
	if (result)
		goto out;

	result = _cache_mngt_save_sync(cache);

out:
	info->ext_err_code = result;
	ocf_mngt_cache_put(cache);
	return result;
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

#ifdef CLEANER_ENABLE
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
#endif	// CLEANER_ENABLE
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
#ifdef CLEANER_ENABLE
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
#endif	// CLEANER_ENABLE
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
