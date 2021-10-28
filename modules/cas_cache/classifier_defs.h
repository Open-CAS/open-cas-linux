/*
* Copyright(c) 2019-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef __CLASSIFIER_DEFS_H__
#define __CLASSIFIER_DEFS_H__

#define MAX_STRING_SPECIFIER_LEN 256

/* Rule matches 1:1 with io class. It contains multiple conditions with
 * associated logical operator (and/or) */
struct cas_cls_rule {
	/* Rules list element */
	struct list_head list;

	/* Associated partition id */
	ocf_part_id_t part_id;

	/* Conditions for this rule */
	struct list_head conditions;
};

/* Classifier context - one per cache instance. */
struct cas_classifier {
	/* Rules list head */
	struct list_head rules;

	/* Directory inode resolving workqueue */
	struct workqueue_struct *wq;

	/* Lock for rules list */
	rwlock_t lock __attribute__((aligned(64)));
};

struct cas_cls_condition_handler;

/* cas_cls_condition represents single test (e.g. file_size <= 4K) plus
 * logical operator (and/or) to combine evaluation of this condition with
 * previous conditions within one rule */
struct cas_cls_condition {
	/* Condition handler */
	struct cas_cls_condition_handler *handler;

	/* Conditions list element */
	struct list_head list;

	/* Data specific to this condition instance */
	void *context;

	/* Logical operator to apply to previous conditions evaluation */
	int l_op;
};

/* Helper structure aggregating I/O data often accessed by condition handlers */
struct cas_cls_io {
	/* bio */
	struct bio *bio;

	/* First page associated with bio */
	struct page *page;

	/* Inode associated with page */
	struct inode *inode;
};

/* Condition evaluation return flags */
typedef struct cas_cls_eval {
	uint8_t yes  : 1;
	uint8_t stop : 1;
} cas_cls_eval_t;

static const cas_cls_eval_t cas_cls_eval_yes = { .yes = 1 };
static const cas_cls_eval_t cas_cls_eval_no = { };

/* Logical operators */
enum cas_cls_logical_op {
	cas_cls_logical_and = 0,
	cas_cls_logical_or
};

/* Condition handler - abstraction over different kinds of condition checks
 * (e.g. file size, metadata). Does not contain all the data required to
 * evaluate condition (e.g. actual file size value), these are stored in
 * @context member of cas_cls_condition object, provided as input argument to
 * test, ctr and dtr callbacks. */
struct cas_cls_condition_handler {
	/* String representing this condition class */
	const char *token;

	/* Condition test */
	cas_cls_eval_t (*test)(struct cas_classifier *cls,
			struct cas_cls_condition *c, struct cas_cls_io *io,
			ocf_part_id_t part_id);

	/* Condition constructor */
	int (*ctr)(struct cas_classifier *cls, struct cas_cls_condition *c,
			char *data);

	/* Condition destructor */
	void (*dtr)(struct cas_classifier *cls, struct cas_cls_condition *c);
};

/* Numeric condition numeric operators */
enum cas_cls_numeric_op {
	cas_cls_numeric_eq = 0,
	cas_cls_numeric_ne = 1,
	cas_cls_numeric_lt = 2,
	cas_cls_numeric_gt = 3,
	cas_cls_numeric_le = 4,
	cas_cls_numeric_ge = 5,
};

/* Numeric condition context */
struct cas_cls_numeric {
	/* Arithmetic operator */
	enum cas_cls_numeric_op operator;

	/* Condition operand as unsigned int */
	uint64_t v_u64;
};

/* String condition context */
struct cas_cls_string {
	/* String specifier*/
	char string[MAX_STRING_SPECIFIER_LEN];

	/* String length */
	uint32_t len;
};

/* Directory condition context */
struct cas_cls_directory {
	/* 1 if directory had been resolved */
	int resolved;

	/* Dir path */
	char *pathname;

	/* Resolved inode */
	unsigned long i_ino;

	/* Back pointer to classifier context */
	struct cas_classifier *cls;

	/* Work item associated with resolving dir for this condition */
	struct delayed_work d_work;
};

#endif
