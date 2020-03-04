/*
* Copyright(c) 2020 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#include <linux/module.h>
#include <linux/debugfs.h>
#include "debugfs.h"
#include "ocf/ocf_debug.h"

#ifdef CAS_DEBUGFS

static struct dentry *cas_debugfs_dir;

#define DEFINE_CAS_DEBUGFS_ATTRIBUTE(__fops, __read, __write)		\
static int __fops ## _open(struct inode *inode, struct file *file)	\
{									\
	file->private_data = inode->i_private;				\
	return 0;							\
}									\
static const struct file_operations __fops = {				\
	.owner	 = THIS_MODULE,						\
	.open	 = __fops ## _open,					\
	.read	 = __read,						\
	.write	 = __write,						\
	.llseek  = no_llseek,						\
}

int cas_debugfs_add_cache(ocf_cache_t cache)
{
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);
	struct dentry *dir, *caches_dir, *cores_dir;

	caches_dir = debugfs_lookup("caches", cas_debugfs_dir);
	BUG_ON(!caches_dir);

	dir = debugfs_create_dir(ocf_cache_get_name(cache), caches_dir);
	dput(caches_dir);
	if (!dir)
		return -ENOMEM;

	cores_dir = debugfs_create_dir("cores", dir);
	if (!cores_dir)
		goto err;

	debugfs_create_atomic_t("flush_interrupt_enabled", 0444,
			     dir, &cache_priv->flush_interrupt_enabled);

	cache_priv->debugfs_dir = dir;

	return 0;

err:
	debugfs_remove_recursive(dir);
	return -ENOMEM;
}

void cas_debugfs_remove_cache(ocf_cache_t cache)
{
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);

	debugfs_remove_recursive(cache_priv->debugfs_dir);
}

static ssize_t seq_cutoff_read(struct file *file, char __user *buf,
		size_t count, loff_t *f_pos)
{
	char *tmp_buf;
	struct ocf_dbg_seq_cutoff_status *status;
	ocf_core_t core = file->private_data;
	int i, len = 0, result;
	int buf_len = 38 * OCF_SEQ_CUTOFF_MAX_STREAMS;

	if (*f_pos > 0)
		return 0;

	tmp_buf = kmalloc(buf_len + sizeof(*status), GFP_KERNEL);
	if (!tmp_buf)
		return 0;

	status = (void *)tmp_buf + buf_len;

	ocf_dbg_get_seq_cutoff_status(core, status);

	for (i = 0; i < OCF_SEQ_CUTOFF_MAX_STREAMS; i++) {
		len += snprintf(tmp_buf + len, buf_len - len, "%016llx %016llx %c %c\n",
				status->streams[i].last,
				status->streams[i].bytes,
				status->streams[i].rw ? 'W' : 'R',
				status->streams[i].active ? 'T' : 'F');
	}

	result = simple_read_from_buffer(buf, count, f_pos, tmp_buf, len);

	kfree(tmp_buf);

	return result;
}

DEFINE_CAS_DEBUGFS_ATTRIBUTE(seq_cutoff_fops, seq_cutoff_read, NULL);

int cas_debugfs_add_core(ocf_core_t core)
{
	ocf_cache_t cache = ocf_core_get_cache(core);
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);
	struct dentry *cores_dir, *dir, *file;

	cores_dir = debugfs_lookup("cores", cache_priv->debugfs_dir);
	BUG_ON(!cores_dir);

	dir = debugfs_create_dir(ocf_core_get_name(core), cores_dir);
	dput(cores_dir);
	if (!dir)
		return -ENOMEM;

	file = debugfs_create_file("seq_cutoff", 0444, dir, core,
			&seq_cutoff_fops);
	if (!file)
		goto err;

	ocf_core_set_priv(core, dir);

	return 0;

err:
	debugfs_remove_recursive(dir);
	return -ENOMEM;
}

void cas_debugfs_remove_core(ocf_core_t core)
{
	debugfs_remove_recursive(ocf_core_get_priv(core));
}

int cas_debugfs_init(void)
{
	struct dentry *dir;

	cas_debugfs_dir = debugfs_create_dir("opencas", NULL);
	if (!cas_debugfs_dir)
		return -ENOMEM;

	dir = debugfs_create_dir("caches", cas_debugfs_dir);
	if (!dir)
		goto err;

	return 0;

err:
	debugfs_remove_recursive(cas_debugfs_dir);
	return -ENOMEM;
}

void cas_debugfs_deinit(void)
{
	debugfs_remove_recursive(cas_debugfs_dir);
}

#else

int cas_debugfs_add_cache(ocf_cache_t cache)
{
	return 0;
}

void cas_debugfs_remove_cache(ocf_cache_t cache)
{
	return;
}

int cas_debugfs_add_core(ocf_core_t core)
{
	return 0;
}

void cas_debugfs_remove_core(ocf_core_t core)
{
	return;
}

int cas_debugfs_init(void)
{
	return 0;
}

void cas_debugfs_deinit(void)
{
	return;
}

#endif
