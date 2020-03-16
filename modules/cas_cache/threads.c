/*
* Copyright(c) 2012-2019 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#include "threads.h"
#include "cas_cache.h"

#define MAX_THREAD_NAME_SIZE 48

struct cas_thread_info {
	atomic_t stop;
	struct completion compl;
	struct completion sync_compl;
	void *sync_data;
	wait_queue_head_t wq;
	atomic_t kicked;
	struct task_struct *thread;
	char name[MAX_THREAD_NAME_SIZE];
};

static int _cas_io_queue_thread(void *data)
{
	ocf_queue_t q = data;
	struct cas_thread_info *info;

	BUG_ON(!q);

	/* complete the creation of the thread */
	info = ocf_queue_get_priv(q);
	BUG_ON(!info);

	CAS_DAEMONIZE(info->thread->comm);

	complete(&info->compl);

	/* Continue working until signaled to exit. */
	do {
		/* Wait until there are completed read misses from the HDDs,
		 * or a stop.
		 */
		wait_event_interruptible(info->wq, ocf_queue_pending_io(q) ||
				atomic_read(&info->stop));

		ocf_queue_run(q);

	} while (!atomic_read(&info->stop) || ocf_queue_pending_io(q));

	WARN(ocf_queue_pending_io(q), "Still pending IO requests\n");

	/* If we get here, then thread was signalled to terminate.
	 * So, let's free memory and exit.
	 */
	wait_for_completion(&info->compl);
	printk(KERN_DEBUG "Thread %s stopped\n", info->name);
	kfree(info);
	module_put_and_exit(0);

	return 0;
}

static void _cas_cleaner_complete(ocf_cleaner_t c, uint32_t interval)
{
	struct cas_thread_info *info = ocf_cleaner_get_priv(c);
	uint32_t *ms = info->sync_data;

	*ms = interval;
	complete(&info->sync_compl);
}

static int _cas_cleaner_thread(void *data)
{
	ocf_cleaner_t c = data;
	ocf_cache_t cache = ocf_cleaner_get_cache(c);
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);
	struct cas_thread_info *info;
	uint32_t ms;

	BUG_ON(!c);

	ENV_BUG_ON(!cache_priv);
	/* complete the creation of the thread */
	info = ocf_cleaner_get_priv(c);
	BUG_ON(!info);

	CAS_DAEMONIZE(info->thread->comm);

	complete(&info->compl);

	info->sync_data = &ms;
	ocf_cleaner_set_cmpl(c, _cas_cleaner_complete);

	do {
		if (atomic_read(&info->stop))
			break;

		atomic_set(&info->kicked, 0);
		init_completion(&info->sync_compl);
		ocf_cleaner_run(c, cache_priv->io_queues[smp_processor_id()]);
		wait_for_completion(&info->sync_compl);

		/*
		 * In case of nop cleaning policy we don't want to perform cleaning
		 * until cleaner_kick() is called.
		 */
		if (ms == OCF_CLEANER_DISABLE) {
			wait_event_interruptible(info->wq, atomic_read(&info->kicked) ||
					atomic_read(&info->stop));
		} else {
			wait_event_interruptible_timeout(info->wq,
					atomic_read(&info->kicked) || atomic_read(&info->stop),
					msecs_to_jiffies(ms));
		}
	} while (true);

	wait_for_completion(&info->compl);
	kfree(info);
	module_put_and_exit(0);

	return 0;
}

static int _cas_metadata_updater_thread(void *data)
{
	ocf_metadata_updater_t mu = data;
	struct cas_thread_info *info;

	BUG_ON(!mu);

	/* complete the creation of the thread */
	info = ocf_metadata_updater_get_priv(mu);
	BUG_ON(!info);

	CAS_DAEMONIZE(info->thread->comm);

	complete(&info->compl);

	do {
		if (atomic_read(&info->stop))
			break;

		atomic_set(&info->kicked, 0);
		if (ocf_metadata_updater_run(mu))
			continue;

		wait_event_interruptible(info->wq, atomic_read(&info->stop) ||
				atomic_read(&info->kicked));
	} while (true);

	wait_for_completion(&info->compl);
	kfree(info);
	module_put_and_exit(0);

	return 0;
}

static int _cas_create_thread(struct cas_thread_info **pinfo,
		int (*threadfn)(void *), void *priv, int cpu,
		const char *fmt, ...)
{
	struct cas_thread_info *info;
	struct task_struct *thread;
	va_list args;

	info = kzalloc(sizeof(*info), GFP_KERNEL);
	if (!info)
		return -ENOMEM;

	atomic_set(&info->stop, 0);
	init_completion(&info->compl);
	init_completion(&info->sync_compl);
	init_waitqueue_head(&info->wq);

	va_start(args, fmt);
	vsnprintf(info->name, sizeof(info->name), fmt, args);
	va_end(args);

	thread = kthread_create(threadfn, priv, "%s", info->name);
	if (IS_ERR(thread)) {
		kfree(info);
		/* Propagate error code as PTR_ERR */
		return PTR_ERR(thread);
	}
	info->thread = thread;

	BUG_ON(!try_module_get(THIS_MODULE));

	/* Affinitize thread to core */
	if (cpu != CAS_CPUS_ALL)
		kthread_bind(thread, cpu);

	if (pinfo)
		*pinfo = info;

	return 0;

}

static void _cas_start_thread(struct cas_thread_info *info)
{
	wake_up_process(info->thread);
	wait_for_completion(&info->compl);

	printk(KERN_DEBUG "Thread %s started\n", info->name);
}

static void _cas_stop_thread(struct cas_thread_info *info)
{
	if (info && info->thread) {
		reinit_completion(&info->compl);
		atomic_set(&info->stop, 1);
		wake_up(&info->wq);
		complete(&info->compl);
	}
}

int cas_create_queue_thread(ocf_queue_t q, int cpu)
{
	struct cas_thread_info *info;
	ocf_cache_t cache = ocf_queue_get_cache(q);
	int result;

	result = _cas_create_thread(&info, _cas_io_queue_thread, q, cpu,
			"cas_io_%s_%d", ocf_cache_get_name(cache), cpu);
	if (!result) {
		ocf_queue_set_priv(q, info);
		_cas_start_thread(info);
	}

	return result;
}

void cas_kick_queue_thread(ocf_queue_t q)
{
	struct cas_thread_info *info = ocf_queue_get_priv(q);
	wake_up(&info->wq);
}


void cas_stop_queue_thread(ocf_queue_t q)
{
	struct cas_thread_info *info = ocf_queue_get_priv(q);
	ocf_queue_set_priv(q, NULL);
	_cas_stop_thread(info);
}

int cas_create_cleaner_thread(ocf_cleaner_t c)
{
	struct cas_thread_info *info;
	ocf_cache_t cache = ocf_cleaner_get_cache(c);
	int result;

	result = _cas_create_thread(&info, _cas_cleaner_thread, c,
			CAS_CPUS_ALL, "cas_clean_%s",
			ocf_cache_get_name(cache));
	if (!result) {
		ocf_cleaner_set_priv(c, info);
		_cas_start_thread(info);
	}

	return result;
}

void cas_kick_cleaner_thread(ocf_cleaner_t c)
{
	struct cas_thread_info *info = ocf_cleaner_get_priv(c);
	atomic_set(&info->kicked, 1);
	wake_up(&info->wq);
}

void cas_stop_cleaner_thread(ocf_cleaner_t c)
{
	struct cas_thread_info *info = ocf_cleaner_get_priv(c);
	ocf_cleaner_set_priv(c, NULL);
	_cas_stop_thread(info);
}

int cas_create_metadata_updater_thread(ocf_metadata_updater_t mu)
{
	struct cas_thread_info *info;
	int result;

	result = _cas_create_thread(&info, _cas_metadata_updater_thread,
			mu, CAS_CPUS_ALL, "ocf_metadata_updater_%s",
			ocf_cache_get_name(ocf_metadata_updater_get_cache(mu)));
	if (!result) {
		ocf_metadata_updater_set_priv(mu, info);
		_cas_start_thread(info);
	}

	return result;
}

void cas_kick_metadata_updater_thread(ocf_metadata_updater_t mu)
{
	struct cas_thread_info *info = ocf_metadata_updater_get_priv(mu);
	atomic_set(&info->kicked, 1);
	wake_up(&info->wq);
}


void cas_stop_metadata_updater_thread(ocf_metadata_updater_t mu)
{
	struct cas_thread_info *info = ocf_metadata_updater_get_priv(mu);
	ocf_metadata_updater_set_priv(mu, NULL);
	_cas_stop_thread(info);
}

