/*
* Copyright(c) 2019-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#include "cas_cache.h"
#include "linux_kernel_version.h"
#include "classifier.h"
#include "classifier_defs.h"
#include <linux/namei.h>

/* Kernel log prefix */
#define CAS_CLS_LOG_PREFIX OCF_PREFIX_SHORT"[Classifier]"

/* Production version logs */
#define CAS_CLS_MSG(severity, format, ...) \
	printk(severity CAS_CLS_LOG_PREFIX " " format, ##__VA_ARGS__);

/* Set to 1 to enable debug logs */
#define CAS_CLASSIFIER_CLS_DEBUG 0

#if 1 == CAS_CLASSIFIER_CLS_DEBUG
/* Debug log */
#define CAS_CLS_DEBUG_MSG(format, ...) \
	CAS_CLS_MSG(KERN_INFO, format, ##__VA_ARGS__)
/* Trace log */
#define CAS_CLS_DEBUG_TRACE(format, ...) \
	trace_printk(format, ##__VA_ARGS__)

#else
#define CAS_CLS_DEBUG_MSG(format, ...)
#define CAS_CLS_DEBUG_TRACE(format, ...)
#endif

/* Done condition test - always accepts and stops evaluation */
static cas_cls_eval_t _cas_cls_done_test(struct cas_classifier *cls,
		struct cas_cls_condition *c, struct cas_cls_io *io,
		ocf_part_id_t part_id)
{
	cas_cls_eval_t ret = {.yes = 1, .stop = 1};
	return ret;
}

/* Metadata condition test */
static cas_cls_eval_t _cas_cls_metadata_test(struct cas_classifier *cls,
		struct cas_cls_condition *c, struct cas_cls_io *io,
		ocf_part_id_t part_id)
{
	if (!io->page)
		return cas_cls_eval_no;

	if (PageAnon(io->page))
		return cas_cls_eval_no;

	if (PageSlab(io->page) || PageCompound(io->page)) {
		/* A filesystem issues IO on pages that does not belongs
		 * to the file page cache. It means that it is a
		 * part of metadata
		 */
		return cas_cls_eval_yes;
	}

	if (!io->page->mapping) {
		/* XFS case, page are allocated internally and do not
		 * have references into inode
		 */
		return cas_cls_eval_yes;
	}

	if (!io->inode)
		return cas_cls_eval_no;

	if (S_ISBLK(io->inode->i_mode)) {
		/* EXT3 and EXT4 case. Metadata IO is performed into pages
		 * of block device cache
		 */
		return cas_cls_eval_yes;
	}

	if (S_ISDIR(io->inode->i_mode)) {
		return cas_cls_eval_yes;
	}

	return cas_cls_eval_no;
}

/* Direct I/O condition test function */
static cas_cls_eval_t _cas_cls_direct_test(struct cas_classifier *cls,
		struct cas_cls_condition *c, struct cas_cls_io *io,
		ocf_part_id_t part_id)
{
	if (!io->page)
		return cas_cls_eval_no;

	if (PageAnon(io->page))
		return cas_cls_eval_yes;

	return cas_cls_eval_no;
}

/* Generic condition constructor for conditions without operands (e.g. direct,
 * metadata) */
static int _cas_cls_generic_ctr(struct cas_classifier *cls,
		struct cas_cls_condition *c, char *data)
{
	if (data) {
		CAS_CLS_MSG(KERN_ERR, "Unexpected operand in condition\n");
		return -EINVAL;
	}
	return 0;
}

/* Generic condition destructor */
static void _cas_cls_generic_dtr(struct cas_classifier *cls,
		struct cas_cls_condition *c)
{
	if (c->context)
		kfree(c->context);
	c->context = NULL;
}

/* Numeric condition constructor. @data is expected to contain either
 * plain number string or range specifier (e.g. "gt:4096"). */
static int _cas_cls_numeric_ctr(struct cas_classifier* cls,
		struct cas_cls_condition *c, char *data)
{
	struct cas_cls_numeric *ctx;
	int result;
	char *ptr;

	if (!data || strlen(data) == 0) {
		CAS_CLS_MSG(KERN_ERR, "Missing numeric condition operand\n");
		return -EINVAL;
	}

	ctx = kmalloc(sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;

	ctx->operator = cas_cls_numeric_eq;

	ptr = strpbrk(data, ":");
	if (ptr) {
		/* Terminate sub-string containing arithmetic operator */
		*ptr = '\0';
		++ptr;

		if (!strcmp(data, "eq")) {
			ctx->operator = cas_cls_numeric_eq;
		} else if (!strcmp(data, "ne")) {
			ctx->operator = cas_cls_numeric_ne;
		} else if (!strcmp(data, "lt")) {
			ctx->operator = cas_cls_numeric_lt;
		} else if (!strcmp(data, "gt")) {
			ctx->operator = cas_cls_numeric_gt;
		} else if (!strcmp(data, "le")) {
			ctx->operator = cas_cls_numeric_le;
		} else if (!strcmp(data, "ge")) {
			ctx->operator = cas_cls_numeric_ge;
		} else {
			CAS_CLS_MSG(KERN_ERR, "Invalid numeric operator \n");
			result = -EINVAL;
			goto error;
		}

	} else {
		/* Plain number case */
		ptr = data;
	}

	result = kstrtou64(ptr, 10, &ctx->v_u64);
	if (result) {
		CAS_CLS_MSG(KERN_ERR, "Invalid numeric operand\n");
		goto error;
	}

	CAS_CLS_DEBUG_MSG("\t\t - Using operator %d with value %llu\n",
			ctx->operator, ctx->v_u64);

	c->context = ctx;
	return 0;

error:
	kfree(ctx);
	return result;
}

/* String condition constructor. @data is expected to contain string
 * to be matched. */
static int _cas_cls_string_ctr(struct cas_classifier *cls,
		struct cas_cls_condition *c, char *data)
{
	size_t len;
	struct cas_cls_string *ctx;

	if (!data) {
		CAS_CLS_MSG(KERN_ERR, "Missing string specifier\n");
		return -EINVAL;
	}

	len = strnlen(data, MAX_STRING_SPECIFIER_LEN);
	if (len == 0) {
		CAS_CLS_MSG(KERN_ERR, "String specifier is empty\n");
		return -EINVAL;
	}
	if (len == MAX_STRING_SPECIFIER_LEN) {
		CAS_CLS_MSG(KERN_ERR, "String specifier is too long\n");
		return -EINVAL;
	}

	ctx = kmalloc(sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;

	strncpy(ctx->string, data, MAX_STRING_SPECIFIER_LEN);
	ctx->len = len;

	c->context = ctx;

	return 0;
}

/* Unsigned int numeric test function */
static cas_cls_eval_t _cas_cls_numeric_test_u(
		struct cas_cls_condition *c, uint64_t val)
{
	struct cas_cls_numeric *ctx = c->context;

	switch (ctx->operator) {
	case cas_cls_numeric_eq:
		return val == ctx->v_u64 ? cas_cls_eval_yes : cas_cls_eval_no;
	case cas_cls_numeric_ne:
		return val != ctx->v_u64 ? cas_cls_eval_yes : cas_cls_eval_no;
	case cas_cls_numeric_lt:
		return val < ctx->v_u64 ? cas_cls_eval_yes : cas_cls_eval_no;
	case cas_cls_numeric_gt:
		return val > ctx->v_u64 ? cas_cls_eval_yes : cas_cls_eval_no;
	case cas_cls_numeric_le:
		return val <= ctx->v_u64 ? cas_cls_eval_yes : cas_cls_eval_no;
	case cas_cls_numeric_ge:
		return val >= ctx->v_u64 ? cas_cls_eval_yes : cas_cls_eval_no;
	}

	return cas_cls_eval_no;
}

#ifdef CAS_WLTH_SUPPORT
/* Write lifetime hint condition test */
static cas_cls_eval_t _cas_cls_wlth_test(struct cas_classifier *cls,
			      struct cas_cls_condition *c, struct cas_cls_io *io,
			      ocf_part_id_t part_id)
{
	return _cas_cls_numeric_test_u(c, io->bio->bi_write_hint);
}
#endif


/* Io class test function */
static cas_cls_eval_t _cas_cls_io_class_test(struct cas_classifier *cls,
		struct cas_cls_condition *c, struct cas_cls_io *io,
		ocf_part_id_t part_id)
{

	return _cas_cls_numeric_test_u(c, part_id);
}

/* File size test function */
static cas_cls_eval_t _cas_cls_file_size_test(
		struct cas_classifier *cls, struct cas_cls_condition *c,
		struct cas_cls_io *io, ocf_part_id_t part_id)
{
	if (!io->inode)
		return cas_cls_eval_no;

	if (S_ISBLK(io->inode->i_mode))
		return cas_cls_eval_no;

	if (!S_ISREG(io->inode->i_mode))
		return cas_cls_eval_no;

	return _cas_cls_numeric_test_u(c, i_size_read(io->inode));
}

/* Resolve path to inode */
static void _cas_cls_directory_resolve(struct cas_classifier *cls,
		struct cas_cls_directory *ctx)
{
	struct path path;
	struct inode *inode;
	int error;
	int o_res;
	unsigned long o_ino;

	o_res = ctx->resolved;
	o_ino = ctx->i_ino;

	error = kern_path(ctx->pathname, LOOKUP_FOLLOW, &path);
	if (error) {
		ctx->resolved = 0;
		if (o_res) {
			CAS_CLS_DEBUG_MSG("Removed inode resolution for %s\n",
					ctx->pathname);
		}
		return;
	}

	inode = path.dentry->d_inode;
	ctx->i_ino = inode->i_ino;
	ctx->resolved = 1;
	path_put(&path);

	if (!o_res) {
		CAS_CLS_DEBUG_MSG("Resolved %s to inode: %lu\n", ctx->pathname,
				ctx->i_ino);
	} else if (o_ino != ctx->i_ino) {
		CAS_CLS_DEBUG_MSG("Changed inode resolution for %s: %lu => %lu"
				"\n", ctx->pathname, o_ino, ctx->i_ino);
	}
}

/* Inode resolving work entry point */
static void _cas_cls_directory_resolve_work(struct work_struct *work)
{
	struct cas_cls_directory *ctx;

	ctx = container_of(work, struct cas_cls_directory, d_work.work);

	_cas_cls_directory_resolve(ctx->cls, ctx);

	queue_delayed_work(ctx->cls->wq, &ctx->d_work,
			msecs_to_jiffies(ctx->resolved ? 5000 : 1000));
}

/* Get unaliased dentry for given dir inode */
static struct dentry *_cas_cls_dir_get_inode_dentry(struct inode *inode)
{
	struct dentry *d = NULL, *iter;
	CAS_ALIAS_NODE_TYPE *pos; /* alias list current element */

	if (CAS_DENTRY_LIST_EMPTY(&inode->i_dentry))
		return NULL;

	spin_lock(&inode->i_lock);

	if (S_ISDIR(inode->i_mode))
		goto unlock;

	CAS_INODE_FOR_EACH_DENTRY(pos, &inode->i_dentry) {
		iter = CAS_ALIAS_NODE_TO_DENTRY(pos);
		spin_lock(&iter->d_lock);
		if (!d_unhashed(iter))
			d = iter;
		spin_unlock(&iter->d_lock);
		if (d)
			break;
	}

unlock:
	spin_unlock(&inode->i_lock);
	return d;
}

/* Directory condition test function */
static cas_cls_eval_t _cas_cls_directory_test(
		struct cas_classifier *cls, struct cas_cls_condition *c,
		struct cas_cls_io *io, ocf_part_id_t part_id)
{
	struct cas_cls_directory *ctx;
	struct inode *inode, *p_inode;
	struct dentry *dentry, *p_dentry;

	ctx = c->context;
	inode = io->inode;

	if (!inode || !ctx->resolved)
		return cas_cls_eval_no;

	/* I/O target inode dentry */
	dentry = _cas_cls_dir_get_inode_dentry(inode);
	if (!dentry)
		return cas_cls_eval_no;

	/* Walk up directory tree starting from I/O destination
	 * dir until current dir inode matches condition inode or top
	 * directory is reached. */
	while (inode) {
		if (inode->i_ino == ctx->i_ino)
			return cas_cls_eval_yes;
		spin_lock(&dentry->d_lock);
		p_dentry = dentry->d_parent;
		if (!p_dentry) {
			spin_unlock(&dentry->d_lock);
			return cas_cls_eval_no;
		}
		p_inode = p_dentry->d_inode;
		spin_unlock(&dentry->d_lock);
		if (p_inode != inode) {
			inode = p_inode;
			dentry = p_dentry;
		} else {
			inode = NULL;
		}
	}

	return cas_cls_eval_no;
}

/* Directory condition constructor */
static int _cas_cls_directory_ctr(struct cas_classifier *cls,
		struct cas_cls_condition *c, char *data)
{
	struct cas_cls_directory *ctx;

	if (!data || strlen(data) == 0) {
		CAS_CLS_MSG(KERN_ERR, "Missing directory specifier\n");
		return -EINVAL;
	}

	ctx = kmalloc(sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;

	ctx->cls = cls;
	ctx->resolved = 0;
	ctx->pathname = kstrdup(data, GFP_KERNEL);
	if (!ctx->pathname) {
		kfree(ctx);
		return -ENOMEM;
	}

	INIT_DELAYED_WORK(&ctx->d_work, _cas_cls_directory_resolve_work);
	queue_delayed_work(cls->wq, &ctx->d_work,
			msecs_to_jiffies(10));

	c->context = ctx;

	return 0;
}

/* Directory condition destructor */
static void _cas_cls_directory_dtr(struct cas_classifier *cls,
		struct cas_cls_condition *c)
{
	struct cas_cls_directory *ctx;
	ctx = c->context;

	if (!ctx)
		return;

	cancel_delayed_work_sync(&ctx->d_work);
	kfree(ctx->pathname);
	kfree(ctx);
}

/* Core id test function */
static cas_cls_eval_t _cas_cls_core_id_test(
		struct cas_classifier *cls, struct cas_cls_condition *c,
		struct cas_cls_io *io, ocf_part_id_t part_id)
{
	char *core_id_str;
	uint64_t core_id;
	struct bio *bio = io->bio;

	core_id_str = strrchr(CAS_BIO_GET_DEV(bio)->disk_name, '-');
	if (!core_id_str)
		return cas_cls_eval_no;

	/* First character of @core_id_str is '-', which we don't want to compare */
	core_id_str += 1;

	if (kstrtou64(core_id_str, 10, &core_id))
		return cas_cls_eval_no;

	return _cas_cls_numeric_test_u(c, core_id);
}

/* Core id condition constructor */
static int _cas_cls_core_id_ctr(struct cas_classifier *cls,
		struct cas_cls_condition *c, char *data)
{
	struct cas_cls_numeric *ctx;
	int result;

	result = _cas_cls_numeric_ctr(cls, c, data);
	if (result)
		return result;

	ctx = c->context;

	if (ctx->v_u64 < OCF_CORE_ID_MIN || ctx->v_u64 > OCF_CORE_ID_MAX) {
		CAS_CLS_MSG(KERN_ERR, "Core id have to be within <%u-%u> range\n",
				OCF_CORE_ID_MIN, OCF_CORE_ID_MAX);
		result = -EINVAL;
		goto error;
	}

	return 0;

error:
	kfree(c->context);
	return result;
}

/* Core id condition destructor */
static void _cas_cls_core_id_dtr(struct cas_classifier *cls,
		struct cas_cls_condition *c)
{
	if (c->context)
		kfree(c->context);
	c->context = NULL;
}

/* File extension test function */
static cas_cls_eval_t _cas_cls_extension_test(
		struct cas_classifier *cls, struct cas_cls_condition *c,
		struct cas_cls_io *io, ocf_part_id_t part_id)
{
	struct cas_cls_string *ctx;
	struct inode *inode;
	struct dentry *dentry;
	char *extension;
	uint32_t len;

	ctx = c->context;
	inode = io->inode;

	if (!inode)
		return cas_cls_eval_no;

	/* I/O target inode dentry */
	dentry = _cas_cls_dir_get_inode_dentry(inode);
	if (!dentry)
		return cas_cls_eval_no;

	extension = strrchr(dentry->d_name.name, '.');
	if (!extension)
		return cas_cls_eval_no;

	/* First character of @extension is '.', which we don't want to compare */
	len = dentry->d_name.len - (extension - (char*)dentry->d_name.name) - 1;
	if (len != ctx->len)
		return cas_cls_eval_no;

	if (strncmp(ctx->string, extension + 1, len) == 0)
		return cas_cls_eval_yes;

	return cas_cls_eval_no;
}

/* File name prefix test function */
static cas_cls_eval_t _cas_cls_file_name_prefix_test(
		struct cas_classifier *cls, struct cas_cls_condition *c,
		struct cas_cls_io *io, ocf_part_id_t part_id)
{
	struct cas_cls_string *ctx;
	struct inode *inode;
	struct dentry *dentry;
	uint32_t len;

	ctx = c->context;
	inode = io->inode;

	if (!inode)
		return cas_cls_eval_no;

	/* I/O target inode dentry */
	dentry = _cas_cls_dir_get_inode_dentry(inode);

	/* Check if dentry and its name is valid */
	if (!dentry || !dentry->d_name.name)
		return cas_cls_eval_no;

	/* Check if name is not too short, we expect full prefix in name */
	if (dentry->d_name.len < ctx->len)
		return cas_cls_eval_no;

	/* Final string comparison check */
	len = min(ctx->len, dentry->d_name.len);
	if (strncmp(dentry->d_name.name, ctx->string, len) == 0)
		return cas_cls_eval_yes;

	return cas_cls_eval_no;
}

/* LBA test function */
static cas_cls_eval_t _cas_cls_lba_test(
		struct cas_classifier *cls, struct cas_cls_condition *c,
		struct cas_cls_io *io, ocf_part_id_t part_id)
{
	uint64_t lba = CAS_BIO_BISECTOR(io->bio);

	return _cas_cls_numeric_test_u(c, lba);
}

/* PID test function */
static cas_cls_eval_t _cas_cls_pid_test(
		struct cas_classifier *cls, struct cas_cls_condition *c,
		struct cas_cls_io *io, ocf_part_id_t part_id)
{
	/* 'current' is kernel macro that allows to access control block of
	   currently executing task */
	struct task_struct *ti = current;

	return _cas_cls_numeric_test_u(c, ti->pid);
}

/* Process name test function */
static cas_cls_eval_t _cas_cls_process_name_test(
		struct cas_classifier *cls, struct cas_cls_condition *c,
		struct cas_cls_io *io, ocf_part_id_t part_id)
{
	struct cas_cls_string *ctx;
	/* 'current' is kernel macro that allows to access control block of
	   currently executing task */
	struct task_struct *ti = current;
	char comm[TASK_COMM_LEN];
	uint32_t len;

	ctx = c->context;

	get_task_comm(comm, ti);

	len = strnlen(comm, TASK_COMM_LEN);
	if (len != ctx->len)
		return cas_cls_eval_no;

	if (strncmp(ctx->string, comm, len) == 0)
		return cas_cls_eval_yes;

	return cas_cls_eval_no;
}

/* File offset test function */
static cas_cls_eval_t _cas_cls_file_offset_test(
		struct cas_classifier *cls, struct cas_cls_condition *c,
		struct cas_cls_io *io, ocf_part_id_t part_id)
{
	struct inode *inode;
	struct dentry *dentry;
	uint64_t offset;

	inode = io->inode;

	if (!inode)
		return cas_cls_eval_no;

	/* I/O target inode dentry */
	dentry = _cas_cls_dir_get_inode_dentry(inode);
	if (!dentry)
		return cas_cls_eval_no;

	offset = PAGE_SIZE * io->page->index +
		io->bio->bi_io_vec->bv_offset;

	return _cas_cls_numeric_test_u(c, offset);
}

/* Request size test function */
static cas_cls_eval_t _cas_cls_request_size_test(
		struct cas_classifier *cls, struct cas_cls_condition *c,
		struct cas_cls_io *io, ocf_part_id_t part_id)
{
	return _cas_cls_numeric_test_u(c, CAS_BIO_BISIZE(io->bio));
}

/* Array of condition handlers */
static struct cas_cls_condition_handler _handlers[] = {
	{ "done", _cas_cls_done_test, _cas_cls_generic_ctr },
	{ "metadata", _cas_cls_metadata_test, _cas_cls_generic_ctr },
	{ "direct", _cas_cls_direct_test, _cas_cls_generic_ctr },
	{ "io_class", _cas_cls_io_class_test, _cas_cls_numeric_ctr,
			_cas_cls_generic_dtr },
	{ "file_size", _cas_cls_file_size_test, _cas_cls_numeric_ctr,
			_cas_cls_generic_dtr },
	{ "directory", _cas_cls_directory_test, _cas_cls_directory_ctr,
			_cas_cls_directory_dtr },
	{ "core_id", _cas_cls_core_id_test, _cas_cls_core_id_ctr,
			_cas_cls_core_id_dtr },
	{ "extension", _cas_cls_extension_test, _cas_cls_string_ctr,
			_cas_cls_generic_dtr },
	{ "file_name_prefix", _cas_cls_file_name_prefix_test, _cas_cls_string_ctr,
			_cas_cls_generic_dtr },
	{ "lba", _cas_cls_lba_test, _cas_cls_numeric_ctr, _cas_cls_generic_dtr },
	{ "pid", _cas_cls_pid_test, _cas_cls_numeric_ctr, _cas_cls_generic_dtr },
	{ "process_name", _cas_cls_process_name_test, _cas_cls_string_ctr,
					_cas_cls_generic_dtr },
	{ "file_offset", _cas_cls_file_offset_test, _cas_cls_numeric_ctr,
					_cas_cls_generic_dtr },
	{ "request_size", _cas_cls_request_size_test, _cas_cls_numeric_ctr,
					_cas_cls_generic_dtr },
#ifdef CAS_WLTH_SUPPORT
	{ "wlth", _cas_cls_wlth_test, _cas_cls_numeric_ctr,
			_cas_cls_generic_dtr},
#endif
	{ NULL }
};

/* Get condition handler for condition string token */
static struct cas_cls_condition_handler *_cas_cls_lookup_handler(
		const char *token)
{
	struct cas_cls_condition_handler *h = _handlers;

	while (h->token) {
		if (strcmp(h->token, token) == 0)
			return h;
		h++;
	}

	return NULL;
}

/* Deallocate condition */
static void _cas_cls_free_condition(struct cas_classifier *cls,
		struct cas_cls_condition *c)
{
	if (c->handler->dtr)
		c->handler->dtr(cls, c);
	kfree(c);
}

/* Allocate condition */
static struct cas_cls_condition * _cas_cls_create_condition(
		struct cas_classifier *cls, const char *token,
		char *data, int l_op)
{
	struct cas_cls_condition_handler *h;
	struct cas_cls_condition *c;
	int result;

	h = _cas_cls_lookup_handler(token);
	if (!h) {
		CAS_CLS_DEBUG_MSG("Cannot find handler for condition"
				" %s\n", token);
		return ERR_PTR(-ENOENT);
	}

	c = kmalloc(sizeof(*c), GFP_KERNEL);
	if (!c)
		return ERR_PTR(-ENOMEM);

	c->handler = h;
	c->context = NULL;
	c->l_op = l_op;

	if (c->handler->ctr) {
		result = c->handler->ctr(cls, c, data);
		if (result) {
			kfree(c);
			return ERR_PTR(result);
		}
	}

	CAS_CLS_DEBUG_MSG("\t\t - Created condition %s\n", token);

	return c;
}

/* Read single codnition from text input and return cas_cls_condition
 * representation. *rule pointer is advanced to point to next condition.
 * Input @rule string is modified to speed up parsing (selected bytes are
 * overwritten with 0).
 *
 * *l_op contains logical operator from previous condition and gets overwritten
 * with operator read from currently parsed condition.
 *
 * Returns pointer to condition if successfull.
 * Returns NULL if no more conditions in string.
 * Returns error pointer in case of syntax or runtime error.
 */
static struct cas_cls_condition *_cas_cls_parse_condition(
		struct cas_classifier *cls, char **rule,
		enum cas_cls_logical_op *l_op)
{
	char *token = *rule;	/* Condition token substring (e.g. file_size) */
	char *operand = NULL;	/* Operand substring (e.g. "lt:4096" or path) */
	char *ptr;		/* Current position in input string */
	char *last = token;	/* Last seen substring in condition */
	char op = 'X';		/* Logical operator at the end of condition */
	struct cas_cls_condition *c;	/* Output condition */

	if (**rule == '\0') {
		/* Empty condition */
		return NULL;
	}

	ptr = strpbrk(*rule, ":&|");
	if (!ptr) {
		/* No operands in condition (e.g. "metadata"), no logical
		 * operators following condition - we're done with parsing. */
		goto create;
	}

	if (*ptr == ':') {
		/* Operand found - terminate token string and move forward. */
		*ptr = '\0';
		ptr += 1;
		operand = ptr;
		last = ptr;

		ptr = strpbrk(ptr, "&|");
		if (!ptr) {
			/* No operator past condition - create rule and exit */
			goto create;
		}
	}

	/* Remember operator value and zero target byte to terminate previous
	 * string (token or operand) */
	op = *ptr;
	*ptr = '\0';

create:
	c = _cas_cls_create_condition(cls, token, operand, *l_op);
	*l_op = (op == '|' ? cas_cls_logical_or : cas_cls_logical_and);

	/* Set *rule to character past current condition and logical operator */
	if (ptr) {
		/* Set pointer for next iteration */
		*rule = ptr + 1;
	} else {
		/* Set pointer to terminating zero */
		*rule = last + strlen(last);
	}

	return c;
}

/* Parse all conditions in rule text description. @rule might be overwritten */
static int _cas_cls_parse_conditions(struct cas_classifier *cls,
		struct cas_cls_rule *r, char *rule)
{
	char *start;
	struct cas_cls_condition *c;
	enum cas_cls_logical_op l_op = cas_cls_logical_or;

	start = rule;
	for (;;) {
		c = _cas_cls_parse_condition(cls, &start, &l_op);
		if (IS_ERR(c))
			return PTR_ERR(c);
		if (!c)
			break;

		list_add_tail(&c->list, &r->conditions);
	}

	return 0;
}

static struct cas_classifier* cas_get_classifier(ocf_cache_t cache)
{
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);

	ENV_BUG_ON(!cache_priv);
	return cache_priv->classifier;
}

static void cas_set_classifier(ocf_cache_t cache,
		struct cas_classifier* cls)
{
	struct cache_priv *cache_priv = ocf_cache_get_priv(cache);

	ENV_BUG_ON(!cache_priv);
	cache_priv->classifier = cls;
}

void _cas_cls_rule_destroy(struct cas_classifier *cls,
		struct cas_cls_rule *r)
{
	struct list_head *item, *n;
	struct cas_cls_condition *c = NULL;

	if (!r)
		return;

	list_for_each_safe(item, n, &r->conditions) {
		c = list_entry(item, struct cas_cls_condition, list);
		list_del(item);
		_cas_cls_free_condition(cls, c);
	}

	kfree(r);
}

/* Destroy rule */
void cas_cls_rule_destroy(ocf_cache_t cache, struct cas_cls_rule *r)
{
	struct cas_classifier *cls = cas_get_classifier(cache);
	BUG_ON(!cls);
	_cas_cls_rule_destroy(cls, r);
}

/* Create rule from text description. @rule might be overwritten */
static struct cas_cls_rule *_cas_cls_rule_create(struct cas_classifier *cls,
		ocf_part_id_t part_id, char *rule)
{
	struct cas_cls_rule *r;
	int result;

	if (part_id == 0 || rule[0] == '\0')
		return NULL;

	r = kmalloc(sizeof(*r), GFP_KERNEL);
	if (!r)
		return ERR_PTR(-ENOMEM);

	r->part_id = part_id;
	INIT_LIST_HEAD(&r->conditions);
	result = _cas_cls_parse_conditions(cls, r, rule);
	if (result) {
		_cas_cls_rule_destroy(cls, r);
		return ERR_PTR(result);
	}

	return r;
}

/* Update rule associated with given io class */
void cas_cls_rule_apply(ocf_cache_t cache,
		ocf_part_id_t part_id, struct cas_cls_rule *new)
{
	struct cas_classifier *cls;
	struct cas_cls_rule *old = NULL, *elem;
	struct list_head *item, *_n;

	cls = cas_get_classifier(cache);
	BUG_ON(!cls);

	write_lock(&cls->lock);

	/* Walk through list of rules in reverse order (tail to head), visiting
	 * rules from high to low part_id */
	list_for_each_prev_safe(item, _n, &cls->rules) {
		elem = list_entry(item, struct cas_cls_rule, list);

		if (elem->part_id == part_id) {
			old = elem;
			list_del(item);
		}

		if (elem->part_id < part_id)
			break;
	}

	/* Insert new element past loop cursor */
	if (new)
		list_add(&new->list, item);

	write_unlock(&cls->lock);

	_cas_cls_rule_destroy(cls, old);

	if (old)
		CAS_CLS_DEBUG_MSG("Removed rule for class %d\n", part_id);
	if (new)
		CAS_CLS_DEBUG_MSG("New rule for class  %d\n", part_id);

	return;
}

/*
 * Translate classification rule error from linux error code to CAS error code.
 * Internal classifier functions use PTR_ERR / ERR_PTR macros to propagate
 * error in pointers. These macros do not work well with CAS error codes, so
 * this function is used to form fine-grained CAS error code when returning
 * from classifier management function.
 */
static int _cas_cls_rule_err_to_cass_err(int err)
{
	switch (err) {
	case -ENOENT:
		return KCAS_ERR_CLS_RULE_UNKNOWN_CONDITION;
	case -EINVAL:
		return KCAS_ERR_CLS_RULE_INVALID_SYNTAX;
	default:
		return err;
	}
}

/* Create and apply classification rule for given class id */
static int _cas_cls_rule_init(ocf_cache_t cache, ocf_part_id_t part_id)
{
	struct cas_classifier *cls;
	struct ocf_io_class_info *info;
	struct cas_cls_rule *r;
	int result;

	cls = cas_get_classifier(cache);
	if (!cls)
		 return -EINVAL;

	info = kzalloc(sizeof(*info), GFP_KERNEL);
	if (!info)
		return -ENOMEM;

	result = ocf_cache_io_class_get_info(cache, part_id, info);
	if (result) {
		if (result == -OCF_ERR_IO_CLASS_NOT_EXIST)
			result = 0;
		goto exit;
	}

	if (strnlen(info->name, sizeof(info->name)) == sizeof(info->name)) {
		CAS_CLS_MSG(KERN_ERR, "IO class name not null terminated\n");
		result = -EINVAL;
		goto exit;
	}

	r = _cas_cls_rule_create(cls, part_id, info->name);
	if (IS_ERR(r)) {
		result = _cas_cls_rule_err_to_cass_err(PTR_ERR(r));
		goto exit;
	}

	cas_cls_rule_apply(cache, part_id, r);

exit:
	kfree(info);
	return result;
}

/* Create classification rule from text description */
int cas_cls_rule_create(ocf_cache_t cache,
		ocf_part_id_t part_id, const char* rule,
		struct cas_cls_rule **cls_rule)
{
	struct cas_cls_rule *r = NULL;
	struct cas_classifier *cls;
	char *_rule;
	int ret;

	if (!cls_rule)
		return -EINVAL;

	cls = cas_get_classifier(cache);
	if (!cls)
		return -EINVAL;

	if (strnlen(rule, OCF_IO_CLASS_NAME_MAX) == OCF_IO_CLASS_NAME_MAX) {
		CAS_CLS_MSG(KERN_ERR, "IO class name not null terminated\n");
		return -EINVAL;
	}

	/* Make description copy as _cas_cls_rule_create might modify input
	 * string */
	_rule = kstrdup(rule, GFP_KERNEL);
	if (!_rule)
		 return -ENOMEM;

	r = _cas_cls_rule_create(cls, part_id, _rule);
	if (IS_ERR(r))
		ret = _cas_cls_rule_err_to_cass_err(PTR_ERR(r));
	else {
		CAS_CLS_DEBUG_MSG("Created rule: %s => %d\n", rule, part_id);
		*cls_rule = r;
		ret = 0;
	}

	kfree(_rule);
	return ret;
}

/* Deinitialize classifier and remove rules */
void cas_cls_deinit(ocf_cache_t cache)
{
	struct cas_classifier *cls;
	struct list_head *item, *n;
	struct cas_cls_rule *r = NULL;

	cls = cas_get_classifier(cache);
	ENV_BUG_ON(!cls);

	list_for_each_safe(item, n, &cls->rules) {
		r = list_entry(item, struct cas_cls_rule, list);
		list_del(item);
		_cas_cls_rule_destroy(cls, r);
	}

	destroy_workqueue(cls->wq);

	kfree(cls);
	cas_set_classifier(cache, NULL);

	CAS_CLS_MSG(KERN_INFO, "Deinitialized IO classifier\n");

	return;
}

/* Initialize classifier context */
static struct cas_classifier *_cas_cls_init(void)
{
	struct cas_classifier *cls;

	cls = kzalloc(sizeof(*cls), GFP_KERNEL);
	if (!cls)
		return ERR_PTR(-ENOMEM);

	INIT_LIST_HEAD(&cls->rules);

	cls->wq = alloc_workqueue("kcas_clsd", WQ_UNBOUND | WQ_FREEZABLE, 1);
	if (!cls->wq) {
		kfree(cls);
		return ERR_PTR(-ENOMEM);
	}

	rwlock_init(&cls->lock);

	CAS_CLS_MSG(KERN_INFO, "Initialized IO classifier\n");

	return cls;
}

/* Initialize classifier and create rules for existing I/O classes */
int cas_cls_init(ocf_cache_t cache)
{
	struct cas_classifier *cls;
	unsigned result = 0;
	unsigned i;

	cls = _cas_cls_init();
	if (IS_ERR(cls))
		return PTR_ERR(cls);
	cas_set_classifier(cache, cls);

	/* Update rules for all I/O classes except 0 - this is default for all
	 * unclassified I/O */
	for (i = 1; i < OCF_USER_IO_CLASS_MAX; i++) {
		result = _cas_cls_rule_init(cache, i);
		if (result)
			break;
	}

	if (result)
		cas_cls_deinit(cache);

	return result;
}

/* Determine whether io matches rule */
static cas_cls_eval_t cas_cls_process_rule(struct cas_classifier *cls,
		struct cas_cls_rule *r, struct cas_cls_io *io,
		ocf_part_id_t *part_id)
{
	struct list_head *item;
	struct cas_cls_condition *c;
	cas_cls_eval_t ret = cas_cls_eval_no, rr;

	CAS_CLS_DEBUG_TRACE(" Processing rule for class %d\n", r->part_id);
	list_for_each(item, &r->conditions) {

		c = list_entry(item, struct cas_cls_condition, list);

		if (!ret.yes && c->l_op == cas_cls_logical_and)
			break;

		rr = c->handler->test(cls, c, io, *part_id);
		CAS_CLS_DEBUG_TRACE("  Processing condition %s => %d, stop:%d "
				"(l_op: %d)\n", c->handler->token, rr.yes,
				rr.stop, (int)c->l_op);

		ret.yes = (c->l_op == cas_cls_logical_and) ?
			rr.yes && ret.yes :
			rr.yes || ret.yes;
		ret.stop = rr.stop;

		if (ret.stop)
			break;
	}

	CAS_CLS_DEBUG_TRACE("  Rule %d output => %d stop: %d\n", r->part_id,
		ret.yes, ret.stop);

	return ret;
}

/* Fill in cas_cls_io for given bio - it is assumed that ctx is
 * zeroed upon entry */
static void _cas_cls_get_bio_context(struct bio *bio,
	struct cas_cls_io *ctx)
{
	struct page *page = NULL;

	if (!bio)
		return;
	ctx->bio = bio;

	if (!CAS_SEGMENT_BVEC(bio_iovec(bio)))
		return;

	page = bio_page(bio);

	if (!page)
		return;
	ctx->page = page;

	if (PageAnon(page))
		return;

	if (PageSlab(page) || PageCompound(page))
		return;

	if (!page->mapping)
		return;

	ctx->inode = page->mapping->host;

	return;
}

/* Determine I/O class for bio */
ocf_part_id_t cas_cls_classify(ocf_cache_t cache, struct bio *bio)
{
	struct cas_classifier *cls;
	struct cas_cls_io io = {};
	struct list_head *item;
	struct cas_cls_rule *r;
	ocf_part_id_t part_id = 0;
	cas_cls_eval_t ret;

	cls = cas_get_classifier(cache);
	if (!cls)
		return 0;

	_cas_cls_get_bio_context(bio, &io);

	read_lock(&cls->lock);
	CAS_CLS_DEBUG_TRACE("%s\n", "Starting processing");
	list_for_each(item, &cls->rules) {
		r = list_entry(item, struct cas_cls_rule, list);
		ret = cas_cls_process_rule(cls, r, &io, &part_id);
		if (ret.yes)
			part_id = r->part_id;
		if (ret.stop)
			break;
	}
	read_unlock(&cls->lock);

	return part_id;
}

