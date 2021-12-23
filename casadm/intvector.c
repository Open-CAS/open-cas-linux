/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#include <stdlib.h>
#include <string.h>
#include "intvector.h"

#define DEFAULT_CAPACITY 11


struct intvector *vector_alloc()
{
	struct intvector *v = malloc(sizeof(struct intvector));
	if (!v) {
		return 0;
	}
	if (vector_alloc_placement(v)) {
		free(v);
		return 0;
	}
	return v;
}

int vector_alloc_placement(struct intvector *v)
{
	v->content = malloc(sizeof(int) * DEFAULT_CAPACITY);
	if (!v->content) {
		return 1;
	}
	v->size = 0;
	v->capacity = DEFAULT_CAPACITY;
	return 0;
}

int vector_reserve(struct intvector *v, int s)
{
	if (s < DEFAULT_CAPACITY || s < v->capacity) {
		return 0;
	}

	void *tmp = realloc(v->content, s*sizeof(int));
	if (!tmp) {
		return 1;
	}

	v->content = tmp;
	v->capacity = s;
	return 0;
}
void vector_free_placement(struct intvector *v)
{
	free(v->content);
}

void vector_free(struct intvector *v)
{
	vector_free_placement(v);
	free(v);
}

int vector_get(struct intvector *v, int i)
{
	return v->content[i];
}

int vector_set(struct intvector *v, int i, int x)
{
	v->content[i]=x;
	return 0;
}

int vector_zero(struct intvector *v)
{
	memset(v->content, 0, sizeof(int) * v->size);
	return 0;
}

int vector_push_back(struct intvector *v, int x)
{
	if (vector_capacity(v) == vector_size(v)) {
		if (vector_reserve(v, v->size*2)) {
			return 1;
		}
	}

	vector_set(v, v->size, x);
	v->size++;
	return 0;
}

int vector_size(struct intvector *v)
{
	return v->size;
}

int vector_capacity(struct intvector *v)
{
	return v->capacity;
}

int vector_resize(struct intvector *v, int s)
{
	if (vector_reserve(v, s)) {
		return 1;
	}
	v->size = s;
	return 0;
}
