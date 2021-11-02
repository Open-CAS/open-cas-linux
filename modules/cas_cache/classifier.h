/*
* Copyright(c) 2019-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef __CLASSIFIER_H__
#define __CLASSIFIER_H__

struct cas_cls_rule;

/* Initialize classifier and create rules for existing I/O classes */
int cas_cls_init(ocf_cache_t cache);

/* Deinitialize classifier and remove rules */
void cas_cls_deinit(ocf_cache_t cache);

/* Allocate and initialize classification rule */
int cas_cls_rule_create(ocf_cache_t cache,
		ocf_part_id_t part_id, const char* rule,
		struct cas_cls_rule **cls_rule);

/* Deinit classification rule */
void cas_cls_rule_destroy(ocf_cache_t cache, struct cas_cls_rule *r);

/* Bind classification rule to io class */
void cas_cls_rule_apply(ocf_cache_t cache, ocf_part_id_t part_id,
		struct cas_cls_rule *r);

/* Determine I/O class for bio */
ocf_part_id_t cas_cls_classify(ocf_cache_t cache, struct bio *bio);


#endif
