/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef __INTVECTOR_H
#define __INTVECTOR_H
struct intvector
{
	int capacity;
	int size;
	int *content;
};
/* names of these functions (mostly) correspond to std::vector */

struct intvector *vector_alloc();

int vector_alloc_placement(struct intvector *v);

int vector_reserve(struct intvector *v, int s);

void vector_free(struct intvector *v);

void vector_free_placement(struct intvector *v);

int vector_get(struct intvector *v, int i);

int vector_set(struct intvector *v, int i, int x);

int vector_zero(struct intvector *v);

int vector_push_back(struct intvector *v, int x);

int vector_size(struct intvector *v);

int vector_capacity(struct intvector *v);

int vector_resize(struct intvector *v, int s);

#endif
