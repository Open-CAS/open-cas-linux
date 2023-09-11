/*
 * Copyright(c) 2019-2021 Intel Corporation
 * Copyright(c) 2023 Huawei Technologies Co., Ltd.
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include "ocf_env_refcnt.h"
#include "ocf/ocf_err.h"
#include "ocf_env.h"

#define ENV_REFCNT_CB_ARMING 1
#define ENV_REFCNT_CB_ARMED 2

static void _env_refcnt_do_on_cpus_cb(struct work_struct *work)
{
	struct notify_cpu_work *ctx =
			container_of(work, struct notify_cpu_work, work);

	ctx->cb(ctx->priv);

	env_atomic_dec(&ctx->rc->notify.to_notify);
	wake_up(&ctx->rc->notify.notify_wait_queue);
}

static void _env_refcnt_do_on_cpus(struct env_refcnt *rc, env_refcnt_do_on_cpu_cb_t cb,
		void *priv)
{
	int cpu_no;
	struct notify_cpu_work *work;

	ENV_BUG_ON(env_atomic_read(&rc->notify.to_notify));

	for_each_online_cpu(cpu_no) {
		work = rc->notify.notify_work_items[cpu_no];

		env_atomic_inc(&rc->notify.to_notify);
		work->cb = cb;
		work->rc = rc;
		work->priv = priv;
		INIT_WORK(&work->work, _env_refcnt_do_on_cpus_cb);
		queue_work_on(cpu_no, rc->notify.notify_work_queue,
				&work->work);
	}

	wait_event(rc->notify.notify_wait_queue,
			!env_atomic_read(&rc->notify.to_notify));
}

static void _env_refcnt_init_pcpu(void *ctx)
{
	struct env_refcnt *rc = ctx;
	struct env_refcnt_pcpu *pcpu = this_cpu_ptr(rc->pcpu);

	pcpu->freeze = false;
	env_atomic64_set(&pcpu->counter, 0);
}

int env_refcnt_init(struct env_refcnt *rc, const char *name, size_t name_len)
{
	int cpu_no, result;

	env_memset(rc, sizeof(*rc), 0);

	env_strncpy(rc->name, sizeof(rc->name), name, name_len);

	rc->pcpu = alloc_percpu(struct env_refcnt_pcpu);
	if (!rc->pcpu)
		return -OCF_ERR_NO_MEM;

	init_waitqueue_head(&rc->notify.notify_wait_queue);
	rc->notify.notify_work_queue = alloc_workqueue("refcnt_%s", 0,
			0, rc->name);

	if (!rc->notify.notify_work_queue) {
		result = -OCF_ERR_NO_MEM;
		goto cleanup_pcpu;
	}

	rc->notify.notify_work_items = env_vzalloc(
		sizeof(*rc->notify.notify_work_items) * num_online_cpus());
	if (!rc->notify.notify_work_items) {
		result =  -OCF_ERR_NO_MEM;
		goto cleanup_wq;
	}

	for_each_online_cpu(cpu_no) {
		rc->notify.notify_work_items[cpu_no] = env_vmalloc(
				sizeof(*rc->notify.notify_work_items[cpu_no]));
		if (!rc->notify.notify_work_items[cpu_no]) {
			result = -OCF_ERR_NO_MEM;
			goto cleanup_work;
		}
	}

	result = env_spinlock_init(&rc->freeze.lock);
	if (result)
		goto cleanup_work;

	_env_refcnt_do_on_cpus(rc, _env_refcnt_init_pcpu, rc);

	rc->callback.pfn = NULL;
	rc->callback.priv = NULL;

	return 0;

cleanup_work:
	for_each_online_cpu(cpu_no) {
		if (rc->notify.notify_work_items[cpu_no]) {
			env_vfree(rc->notify.notify_work_items[cpu_no]);
			rc->notify.notify_work_items[cpu_no] = NULL;
		}
	}

	env_vfree(rc->notify.notify_work_items);
	rc->notify.notify_work_items = NULL;
cleanup_wq:
	destroy_workqueue(rc->notify.notify_work_queue);
	rc->notify.notify_work_queue = NULL;
cleanup_pcpu:
	free_percpu(rc->pcpu);
	rc->pcpu = NULL;

	return result;
}

void env_refcnt_deinit(struct env_refcnt *rc)
{
	int cpu_no;

	env_spinlock_destroy(&rc->freeze.lock);

	ENV_BUG_ON(env_atomic_read(&rc->notify.to_notify));
	for_each_online_cpu(cpu_no) {
		if (rc->notify.notify_work_items[cpu_no]) {
			env_vfree(rc->notify.notify_work_items[cpu_no]);
			rc->notify.notify_work_items[cpu_no] = NULL;
		}
	}

	env_vfree(rc->notify.notify_work_items);
	rc->notify.notify_work_items = NULL;
	destroy_workqueue(rc->notify.notify_work_queue);
	rc->notify.notify_work_queue = NULL;

	free_percpu(rc->pcpu);
	rc->pcpu = NULL;
}

static inline void _env_refcnt_call_freeze_cb(struct env_refcnt *rc)
{
	bool fire;

	fire = (env_atomic_cmpxchg(&rc->callback.armed, ENV_REFCNT_CB_ARMED, 0)
		== ENV_REFCNT_CB_ARMED);
	smp_mb();
	if (fire)
		rc->callback.pfn(rc->callback.priv);
}

void env_refcnt_dec(struct env_refcnt *rc)
{
	struct env_refcnt_pcpu *pcpu;
	bool freeze;
	int64_t countdown = 0;
	bool callback;
	unsigned long flags;

	pcpu = get_cpu_ptr(rc->pcpu);

	freeze = pcpu->freeze;

	if (!freeze)
		env_atomic64_dec(&pcpu->counter);

	put_cpu_ptr(pcpu);

	if (freeze) {
		env_spinlock_lock_irqsave(&rc->freeze.lock, flags);
		countdown = env_atomic64_dec_return(&rc->freeze.countdown);
		callback = !rc->freeze.initializing && countdown == 0;
		env_spinlock_unlock_irqrestore(&rc->freeze.lock, flags);

		if (callback)
			_env_refcnt_call_freeze_cb(rc);
	}
}

bool env_refcnt_inc(struct env_refcnt  *rc)
{
	struct env_refcnt_pcpu *pcpu;
	bool freeze;

	pcpu = get_cpu_ptr(rc->pcpu);

	freeze = pcpu->freeze;

	if (!freeze) {
		env_atomic64_inc(&pcpu->counter);
	}
		
	put_cpu_ptr(pcpu);

	return !freeze;
}

struct env_refcnt_freeze_ctx {
	struct env_refcnt *rc;
	env_atomic64 sum;
};

static void _env_refcnt_freeze_pcpu(void *_ctx)
{
	struct env_refcnt_freeze_ctx *ctx = _ctx;
	struct env_refcnt_pcpu *pcpu = this_cpu_ptr(ctx->rc->pcpu);

	pcpu->freeze = true;
	env_atomic64_add(env_atomic64_read(&pcpu->counter), &ctx->sum);
}

void env_refcnt_freeze(struct env_refcnt *rc)
{
	struct env_refcnt_freeze_ctx ctx;
	int freeze_cnt;
	bool callback;
	unsigned long flags;

	ctx.rc = rc;
	env_atomic64_set(&ctx.sum, 0);

	/* initiate freeze */
	env_spinlock_lock_irqsave(&rc->freeze.lock, flags);
	freeze_cnt = ++(rc->freeze.counter);
	if (freeze_cnt > 1) {
		env_spinlock_unlock_irqrestore(&rc->freeze.lock, flags);
		return;
	}
	rc->freeze.initializing = true;
	env_spinlock_unlock_irqrestore(&rc->freeze.lock, flags);

	/* notify CPUs about freeze */
	_env_refcnt_do_on_cpus(rc, _env_refcnt_freeze_pcpu, &ctx);

	/* update countdown */
	env_spinlock_lock_irqsave(&rc->freeze.lock, flags);
	env_atomic64_add(env_atomic64_read(&ctx.sum), &rc->freeze.countdown);
	rc->freeze.initializing = false;
	callback = (env_atomic64_read(&rc->freeze.countdown) == 0);
	env_spinlock_unlock_irqrestore(&rc->freeze.lock, flags);

	/* if countdown finished trigger callback */
	if (callback)
		_env_refcnt_call_freeze_cb(rc);
}


void env_refcnt_register_zero_cb(struct env_refcnt *rc, env_refcnt_cb_t cb,
		void *priv)
{
	bool callback;
	bool concurrent_arming;
	unsigned long flags;

	concurrent_arming = (env_atomic_inc_return(&rc->callback.armed)
		> ENV_REFCNT_CB_ARMING);
	ENV_BUG_ON(concurrent_arming);

	/* arm callback */
	rc->callback.pfn = cb;
	rc->callback.priv = priv;
	smp_wmb();
	env_atomic_set(&rc->callback.armed, ENV_REFCNT_CB_ARMED);

	/* fire callback in case countdown finished */
	env_spinlock_lock_irqsave(&rc->freeze.lock, flags);
	callback = (env_atomic64_read(&rc->freeze.countdown) == 0 && !rc->freeze.initializing);
	env_spinlock_unlock_irqrestore(&rc->freeze.lock, flags);

	if (callback)
		_env_refcnt_call_freeze_cb(rc);
}

static void _env_refcnt_unfreeze_pcpu(void *_ctx)
{
	struct env_refcnt_freeze_ctx *ctx = _ctx;
	struct env_refcnt_pcpu *pcpu = this_cpu_ptr(ctx->rc->pcpu);

	ENV_BUG_ON(!pcpu->freeze);

	env_atomic64_set(&pcpu->counter, 0);
	pcpu->freeze = false;
}

void env_refcnt_unfreeze(struct env_refcnt *rc)
{
	struct env_refcnt_freeze_ctx ctx;
	int freeze_cnt;
	unsigned long flags;

	env_spinlock_lock_irqsave(&rc->freeze.lock, flags);
	freeze_cnt = --(rc->freeze.counter);
	env_spinlock_unlock_irqrestore(&rc->freeze.lock, flags);

	ENV_BUG_ON(freeze_cnt < 0);
	if (freeze_cnt > 0)
		return;

	ENV_BUG_ON(env_atomic64_read(&rc->freeze.countdown));
	/* disarm callback */
	env_atomic_set(&rc->callback.armed, 0);
	smp_wmb();

	/* notify CPUs about unfreeze */
	ctx.rc = rc;
	_env_refcnt_do_on_cpus(rc, _env_refcnt_unfreeze_pcpu, &ctx);
}

bool env_refcnt_frozen(struct env_refcnt *rc)
{
	bool frozen;
	unsigned long flags;

	env_spinlock_lock_irqsave(&rc->freeze.lock, flags);
	frozen =  !!rc->freeze.counter;
	env_spinlock_unlock_irqrestore(&rc->freeze.lock, flags);

	return frozen;
}

bool env_refcnt_zeroed(struct env_refcnt *rc)
{
	bool frozen;
	bool initializing;
	int64_t countdown;
	unsigned long flags;

	env_spinlock_lock_irqsave(&rc->freeze.lock, flags);
	frozen = !!rc->freeze.counter;
	initializing = rc->freeze.initializing;
	countdown = env_atomic64_read(&rc->freeze.countdown);
	env_spinlock_unlock_irqrestore(&rc->freeze.lock, flags);

	return frozen && !initializing && countdown == 0;
}
