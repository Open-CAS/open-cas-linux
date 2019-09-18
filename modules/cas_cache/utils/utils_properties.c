/*
* Copyright(c) 2012-2019 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#include "cas_cache.h"

#define INTERNAL_CALL 0
#define EXTERNAL_CALL 1

#define CAS_PROPERTIES_VERSION 101

#define VERSION_STR ".version"

/*
 * Difference between constant and non constant entry is store in LSB
 * e.g.:
 *	cas_property_string	 in binary 0000 1010
 *	cas_property_string_const in binary 0000 1011
 */

#define CAS_PROP_UNCONST(type) (type & ~CAS_PROPERTIES_CONST)
#define CAS_PROP_CHECK_CONST(type) (type & CAS_PROPERTIES_CONST)

enum cas_property_type {
	cas_property_string = 10,
	cas_property_string_const =
			(cas_property_string | CAS_PROPERTIES_CONST),
	cas_property_sint = 16,
	cas_property_sint_const = (cas_property_sint | CAS_PROPERTIES_CONST),
	cas_property_uint = 74,
	cas_property_uint_const = (cas_property_uint | CAS_PROPERTIES_CONST),
};

struct cas_properties {
	struct list_head list;
};

struct _cas_property {
	uint8_t type;
	char *key;
	struct list_head item;
	union {
		void *value;
		uint64_t value_uint;
		int64_t value_sint;
	};
};

struct cas_properties *cas_properties_create(void)
{
	struct cas_properties *props;
	int result;

	props = kzalloc(sizeof(*props), GFP_KERNEL);
	if (!props)
		return ERR_PTR(-ENOMEM);

	INIT_LIST_HEAD(&props->list);

	result = cas_properties_add_uint(props, VERSION_STR,
			CAS_PROPERTIES_VERSION, CAS_PROPERTIES_CONST);
	if (result) {
		kfree(props);
		return ERR_PTR(result);
	}

	result = cas_properties_add_uint(props, ".size", 0,
			CAS_PROPERTIES_NON_CONST);
	if (result) {
		kfree(props);
		return ERR_PTR(result);
	}

	return props;
}

void cas_properties_destroy(struct cas_properties *props)
{
	struct list_head *curr, *tmp;
	struct _cas_property *entry;

	list_for_each_safe(curr, tmp, &props->list) {
		entry = list_entry(curr, struct _cas_property, item);
		list_del(curr);
		if (cas_property_string == CAS_PROP_UNCONST(entry->type))
			kfree(entry->value);
		kfree(entry->key);
		kfree(entry);
	}

	kfree(props);
}

static uint64_t _cas_prop_get_size(struct cas_properties *props)
{
	struct list_head *curr;
	struct _cas_property *entry;
	uint64_t size_all = 0;

	list_for_each(curr, &props->list) {
		entry = list_entry(curr, struct _cas_property, item);

		size_all += cas_prop_strnlen(entry->key, MAX_STRING_SIZE) + 1;
		size_all += sizeof(entry->type);

		switch (CAS_PROP_UNCONST(entry->type)) {
		case cas_property_string:
			size_all += cas_prop_strnlen(entry->value,
					MAX_STRING_SIZE) + 1;
			break;
		case cas_property_sint:
			size_all += sizeof(entry->value_sint);
			break;
		case cas_property_uint:
			size_all += sizeof(entry->value_uint);
			break;
		default:
			return 0;
		}
	}

	return size_all;
}

static int _cas_prop_serialize_string(char *buffer, const uint64_t size,
	uint64_t *offset, char *value)
{
	uint64_t str_size = 0;

	str_size = cas_prop_strnlen(value, MAX_STRING_SIZE) + 1;

	if ((*offset + str_size) > size)
		return -ENOMEM;

	memcpy(buffer + *offset, value, str_size);
	*offset += str_size;

	return 0;
}

static int _cas_prop_parse_string(const char *buffer, const uint64_t size,
	uint64_t *offset, char **str)
{
	char *tmp_str = NULL;
	uint64_t str_size = 0;

	if (*offset >= size)
		return -ENOMEM;

	str_size = cas_prop_strnlen(&buffer[*offset], size - *offset ) + 1;

	if (str_size > size - *offset) {
		/* no null terminator at the end of buffer */
		return -ENOMEM;
	}

	tmp_str = kstrdup(&buffer[*offset], GFP_KERNEL);
	if (!tmp_str)
		return -ENOMEM;

	*offset += str_size;
	*str = tmp_str;

	return 0;
}

static int _cas_prop_serialize_int(char *buffer, const uint64_t size,
	uint64_t *offset, uint64_t number)
{
	int32_t i;

	/*
	 * To prevent issue connected with byte order we
	 * serialize integer byte by byte.
	 */
	for (i = 0; i < sizeof(number); i++) {
		char byte = number & 0xFF;

		if (*offset < size)
			buffer[*offset] = byte;
		else
			return -ENOMEM;

		(*offset)++;
		number = number >> 8;
	}

	return 0;
}

static int _cas_prop_serialize_uint(char *buffer, const uint64_t size,
	uint64_t *offset, uint64_t number)
{
	return _cas_prop_serialize_int(buffer, size, offset, number);
}


static int _cas_prop_serialize_sint(char *buffer, const uint64_t size,
	uint64_t *offset, int64_t number)
{
	return _cas_prop_serialize_int(buffer, size, offset, (uint64_t) number);

}

static int _cas_prop_parse_int(const char *buffer,
	const uint64_t size, uint64_t *offset, uint64_t *number)
{
	int32_t i;
	uint64_t byte;

	*number = 0;

	/*
	 * To prevent issue connected with byte order we
	 * parse integer byte by byte.
	 */
	for (i = 0; i < sizeof(*number); i++) {
		if (*offset >= size)
			return -ENOMEM;

		byte = buffer[*offset] & 0xFF;
		byte = byte << (i * 8);

		*number |= byte;

		(*offset)++;
	}

	return 0;
}

static int _cas_prop_parse_uint(const char *buffer,
	const uint64_t size, uint64_t *offset, uint64_t *number)
{
	return _cas_prop_parse_int(buffer, size, offset, number);
}

static int _cas_prop_parse_sint(const char *buffer,
	const uint64_t size, uint64_t *offset, int64_t *number)
{
	return _cas_prop_parse_int(buffer, size, offset, (uint64_t *) number);
}

static int _cas_prop_serialize(struct _cas_property *entry, void *buffer,
	const uint64_t size, uint64_t *offset)
{
	uint64_t item_size = 0;
	void *item;
	int result = 0;

	if (*offset > size)
		return -ENOMEM;

	/*
	 * Each entry is represented in buffer in order as below
	 * (e.g. in case we have entry with integer) :
	 * <-----	     entry		----->
	 * <-      key        -><-type-><-  integer ->
	 * <-     X bytes     -><1 byte><-  8 byte  ->
	 * |		       |       |             |
	 */

	/*
	 * First step - serialize key
	 */

	item_size = cas_prop_strnlen(entry->key, MAX_STRING_SIZE) + 1;
	item = entry->key;

	if ((*offset + item_size) > size)
		return -ENOMEM;

	memcpy(buffer + *offset, item, item_size);
	*offset += item_size;

	/*
	 * Second step - serialize type
	 */

	item_size = sizeof(entry->type);
	item = &entry->type;

	if ((*offset + item_size) > size)
		return -ENOMEM;

	memcpy(buffer + *offset, item, item_size);
	*offset += item_size;

	/*
	 * Third step - serialize value
	 */

	switch (CAS_PROP_UNCONST(entry->type)) {
	case cas_property_string:
		/* Serialize string */
		result = _cas_prop_serialize_string(buffer, size, offset,
				entry->value);
		break;
	case cas_property_sint:
		/* Serialize signed integer */
		result = _cas_prop_serialize_sint(buffer, size, offset,
				entry->value_uint);
		break;
	case cas_property_uint:
		/* Serialize unsigned integer */
		result = _cas_prop_serialize_uint(buffer, size, offset,
				entry->value_uint);
		break;
	default:
		result = -EINVAL;
		break;
	}

	return result;
}

int cas_properties_serialize(struct cas_properties *props,
		struct casdsk_props_conf *caches_serialized_conf)
{
	int result = 0;
	uint64_t offset = 0, size;
	uint16_t crc = 0;
	void *buffer;
	struct list_head *curr;
	struct _cas_property *entry;

	size = _cas_prop_get_size(props);
	if (size == 0)
		return -EINVAL;

	buffer = vzalloc(size);
	if (!buffer)
		return -ENOMEM;

	/*
	 * Update first entry on list - size of buffer
	 */
	result = cas_properties_add_uint(props, ".size", size,
			CAS_PROPERTIES_CONST);
	if (result)
		goto error_after_buffer_allocation;

	/*
	 * Serialize each entry, one by one
	 */
	list_for_each(curr, &props->list) {
		entry = list_entry(curr, struct _cas_property, item);
		result = _cas_prop_serialize(entry, buffer, size, &offset);
		if (result)
			goto error_after_buffer_allocation;
	}

	crc = crc16(0, buffer, size);

	caches_serialized_conf->buffer = buffer;
	caches_serialized_conf->size = size;
	caches_serialized_conf->crc = crc;
	return result;

error_after_buffer_allocation:
	vfree(buffer);
	return result;
}

void cas_properties_print(struct cas_properties *props)
{
	struct list_head *curr;
	struct _cas_property *entry;
	char *abc;

	/*
	 * Serialize each entry, one by one
	 */
	list_for_each(curr, &props->list) {
		entry = list_entry(curr, struct _cas_property, item);
		printk(KERN_DEBUG "[Upgrade] Key: %s", entry->key);
		switch (CAS_PROP_UNCONST(entry->type)) {
		case cas_property_string:
			printk(", string, ");
			abc = (char *)entry->value;
			printk("Value: %s ", abc);
			break;
		case cas_property_sint:
			break;
		case cas_property_uint:
			printk(", uint, ");
			printk("Value: %llu ", entry->value_uint);
			break;
		default:
			printk("Invalid type!");
			break;
		}
		printk("\n");
	}
}

static int _cas_prop_parse_version(const char *buffer, uint64_t *offset,
		uint64_t *version, int trigger)
{
	int result = 0;
	char *key = NULL;
	uint8_t type;

	result = _cas_prop_parse_string(buffer, strlen(VERSION_STR) + 1,
			offset, &key);
	if (result)
		goto error_during_parse_key;

	if (strcmp(VERSION_STR, key)) {
		result = -EINVAL;
		goto error_after_parse_key;
	}

	type = buffer[*offset];
	if (cas_property_uint_const != type) {
		result = -EINVAL;
		goto error_after_parse_key;
	}
	*offset += sizeof(type);

	result = _cas_prop_parse_uint(buffer,
			strlen(VERSION_STR) + 1 + sizeof(type) +
			sizeof(*version), offset, version);
	if (result)
		goto error_after_parse_key;

	/*
	 * In case that is external call
	 * we don't need check version.
	 */
	if (trigger == INTERNAL_CALL && *version != CAS_PROPERTIES_VERSION) {
		printk(KERN_ERR "Version of interface using to parse is "
				"different than version used to serialize\n");
		result = -EPERM;
	}

error_after_parse_key:
	kfree(key);
error_during_parse_key:
	return result;
}

int cas_properites_parse_version(struct casdsk_props_conf *caches_serialized_conf,
		uint64_t *version)
{
	uint64_t offset = 0;
	char *buffer = NULL;

	buffer = (char *) caches_serialized_conf->buffer;
	if (!buffer)
		return -EINVAL;

	return _cas_prop_parse_version(buffer, &offset, version, EXTERNAL_CALL);
}

struct cas_properties *
cas_properites_parse(struct casdsk_props_conf *caches_serialized_conf)
{
	struct cas_properties *props;
	char *key = NULL, *value = NULL, *buffer = NULL;
	int result;
	uint8_t type;
	uint64_t uint_value, size = 0, offset = 0, version = 0;
	uint16_t crc;
	int64_t sint_value;
	bool constant = false;

	props = cas_properties_create();
	if (IS_ERR(props))
		return ERR_PTR(-ENOMEM);

	if (!caches_serialized_conf) {
		result = -EINVAL;
		goto error_after_props_allocation;
	}

	buffer = (char *) caches_serialized_conf->buffer;
	if (!buffer) {
		result = -EINVAL;
		goto error_after_props_allocation;
	}

	size = caches_serialized_conf->size;
	crc = crc16(0, buffer, size);
	if (crc != caches_serialized_conf->crc) {
		printk(KERN_ERR "Cache configuration corrupted");
		result = -EINVAL;
		goto error_after_props_allocation;
	}

	/*
	 * Parse first entry on list - version of interface used to
	 * serialization
	 */
	result = _cas_prop_parse_version(buffer, &offset, &version,
			INTERNAL_CALL);
	if (result)
		goto error_after_props_allocation;

	while (offset < size) {
		/*
		 * Parse key of entry
		 */
		result = _cas_prop_parse_string(buffer, size, &offset, &key);
		if (result)
			goto error_after_props_allocation;

		/*
		 * Parse type of entry
		 */
		if (offset + sizeof(type) > size) {
			kfree(key);
			goto error_after_props_allocation;
		}

		memcpy(&type, buffer + offset, sizeof(type));
		offset += sizeof(type);

		constant = CAS_PROP_CHECK_CONST(type);
		type = CAS_PROP_UNCONST(type);

		switch (type) {
		case cas_property_string:
			/* Parse string */
			result = _cas_prop_parse_string(buffer, size, &offset,
					&value);
			if (result)
				break;

			/*
			 * Add new entry with string to CAS properties instance
			 */
			result |= cas_properties_add_string(props, key, value,
					constant);
			kfree(value);
			break;
		case cas_property_sint:
			/* Parse signed integer */
			result = _cas_prop_parse_sint(buffer, size, &offset,
					&sint_value);
			/* Add new entry with signed integer to CAS properties
			 * instance
			 */
			result |= cas_properties_add_sint(props, key,
					sint_value, constant);
			break;
		case cas_property_uint:
			/* Parse unsigned integer */
			result = _cas_prop_parse_uint(buffer, size, &offset,
					&uint_value);
			/* Add new entry with unsigned integer to CAS properties
			 * instance
			 */
			result |= cas_properties_add_uint(props, key,
					uint_value, constant);
			break;
		default:
			result = -EINVAL;
			break;
		}

		/*
		 * In case when we added new entry,
		 * we not need hold key value longer.
		 */
		kfree(key);

		if (result)
			goto error_after_props_allocation;
	}

	return props;

error_after_props_allocation:
	cas_properties_destroy(props);
	return ERR_PTR(result);
}

static struct _cas_property *_cas_prop_find(const struct cas_properties *props,
	const char *key)
{
	struct list_head *curr;
	struct _cas_property *entry;

	list_for_each(curr, &props->list) {
		entry = list_entry(curr, struct _cas_property, item);
		if (strncmp(key, entry->key, MAX_STRING_SIZE) == 0)
			return entry;
	}
	return ERR_PTR(-ENOENT);
}

static struct _cas_property *_cas_prop_alloc_entry_key(const char *key)
{
	struct _cas_property *entry;

	entry =  kzalloc(sizeof(*entry), GFP_KERNEL);
	if (!entry)
		return ERR_PTR(-ENOMEM);

	entry->key = kstrdup(key, GFP_KERNEL);
	if (!entry->key) {
		kfree(entry);
		return ERR_PTR(-ENOMEM);
	}

	INIT_LIST_HEAD(&entry->item);

	return entry;
}

/*
 * ADD
 */

int cas_properties_add_uint(struct cas_properties *props, const char *key,
	uint64_t value, bool constant)
{
	struct _cas_property *entry;

	/*
	 * Looks for entry with same key,
	 * if it is exist - update, if not  - create new
	 */
	entry = _cas_prop_find(props, key);
	if (IS_ERR(entry)) {
		entry = _cas_prop_alloc_entry_key(key);
		if (IS_ERR(entry))
			return PTR_ERR(entry);
		list_add_tail(&entry->item, &props->list);
	} else if (cas_property_uint != entry->type) {
		/*
		 * We can update only non constant entry,
		 * so we need compare type only with non constant type.
		 */
		return -EINVAL;
	}

	entry->type = constant ? cas_property_uint_const : cas_property_uint;
	entry->value_uint = value;

	return 0;
}

int cas_properties_add_sint(struct cas_properties *props, const char *key,
	int64_t value, bool constant)
{
	struct _cas_property *entry;

	/*
	 * Looks for entry with same key,
	 * if it is exist - update, if not  - create new
	 */
	entry = _cas_prop_find(props, key);
	if (IS_ERR(entry)) {
		entry = _cas_prop_alloc_entry_key(key);
		if (IS_ERR(entry))
			return PTR_ERR(entry);
		list_add_tail(&entry->item, &props->list);
	} else if (cas_property_sint != entry->type) {
		/*
		 * We can update only non constant entry,
		 * so we need compare type only with non constant type.
		 */
		return -EINVAL;
	}

	entry->type = constant ? cas_property_sint_const : cas_property_sint;
	entry->value_sint = value;

	return 0;
}

int cas_properties_add_string(struct cas_properties *props, const char *key,
	const char *value, bool constant)
{
	struct _cas_property *entry;
	char *tmp_value = NULL;

	tmp_value = kstrdup(value, GFP_KERNEL);
	if (!tmp_value)
		return -ENOMEM;

	/*
	 * Looks for entry with same key,
	 * if it is exist - update, if not  - create new
	 */
	entry = _cas_prop_find(props, key);
	if (IS_ERR(entry)) {
		entry = _cas_prop_alloc_entry_key(key);
		if (IS_ERR(entry)) {
			kfree(tmp_value);
			return PTR_ERR(entry);
		}
		list_add_tail(&entry->item, &props->list);
	} else {
		if (cas_property_string != entry->type) {
			/*
			 * We can update only non constant entry,
			 * so we need compare type only with non constant type.
			 */
			kfree(tmp_value);
			return -EINVAL;
		}

		kfree(entry->value);
	}

	entry->type = constant ? cas_property_string_const :
			cas_property_string;
	entry->value = tmp_value;

	return 0;
}

/*
 * GET
 */

int cas_properties_get_uint(struct cas_properties *props, const char *key,
	uint64_t *value)
{
	struct _cas_property *entry;

	entry = _cas_prop_find(props, key);
	if ((IS_ERR(entry) == 0) && (cas_property_uint ==
			CAS_PROP_UNCONST(entry->type))) {
		*value = entry->value_uint;
		return 0;
	}

	return IS_ERR(entry) ? PTR_ERR(entry) : -EINVAL;
}

int cas_properties_get_sint(struct cas_properties *props, const char *key,
	int64_t *value)
{
	struct _cas_property *entry;

	entry = _cas_prop_find(props, key);
	if ((IS_ERR(entry) == 0) && (cas_property_sint ==
			CAS_PROP_UNCONST(entry->type))) {
		*value = entry->value_sint;
		return 0;
	}

	return IS_ERR(entry) ? PTR_ERR(entry) : -EINVAL;
}

int cas_properties_get_string(struct cas_properties *props, const char *key,
	char *value, uint32_t size)
{
	struct _cas_property *entry;

	entry = _cas_prop_find(props, key);
	if ((IS_ERR(entry) == 0) && (cas_property_string ==
			CAS_PROP_UNCONST(entry->type))) {
		/* Check if size of destination memory is enough */
		if (size < cas_prop_strnlen(entry->value, MAX_STRING_SIZE) + 1)
			return -ENOMEM;

		cas_prop_strncpy(value, size, entry->value,
			cas_prop_strnlen(entry->value, MAX_STRING_SIZE));
		return 0;
	}

	return IS_ERR(entry) ? PTR_ERR(entry) : -EINVAL;
}
