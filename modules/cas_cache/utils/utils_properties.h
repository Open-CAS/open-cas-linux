/*
* Copyright(c) 2012-2019 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#ifndef UTILS_PROPERTIES_H_
#define UTILS_PROPERTIES_H_

#ifdef __KERNEL__
#define cas_prop_strncpy(dest, dest_size, src, src_size) \
		strlcpy(dest, src, dest_size)
#define cas_prop_strnlen(string, size) strnlen(string, size)
#else
#define cas_prop_strncpy(dest, dest_size, src, src_size) \
		strncpy(dest, src, src_size)
#define cas_prop_strnlen(string, size) strlen(string)
#endif

#include "../../cas_disk/cas_disk.h"

#define MAX_STRING_SIZE 4095

#define CAS_PROPERTIES_NON_CONST false
#define CAS_PROPERTIES_CONST true

/**
 * @file utils_properties.h
 * @brief CAS cache interface for collect and serialization CAS properties
 */

/**
 * @brief Handler for instance of CAS properties
 */
struct cas_properties;

/**
 * @brief Initialize instance of CAS properties
 *
 * @return Handler to instance of interface
 */
struct cas_properties *cas_properties_create(void);

/**
 * @brief De-initialize instance of CAS properties
 *
 * @param props Handler to instance to de-initialize
 */
void cas_properties_destroy(struct cas_properties *props);

/**
 * @brief Serialize given CAS properties instance to continuous buffer
 *
 * @param props instance of CAS properties
 * @param idisk conf instance of CAS properties
 * @return result of serialize CAS properties
 */
int cas_properties_serialize(struct cas_properties *props,
	struct casdsk_props_conf *caches_serialized_conf);

/**
 * @brief Parse of first entry given continuous buffer to get version of
 *        interface which been used to serialize
 *
 * @param buffer pointer to continuous buffer with serialized CAS properties
 * @param version pointer to memory where we will put version
 * @return result of getting version, 0 success
 */
int cas_properites_parse_version(struct casdsk_props_conf *caches_serialized_conf,
		uint64_t *version);

/**
 * @brief Parse of given continuous buffer to CAS properties instance
 *
 * @param buffer pointer to continuous buffer with serialized CAS properties
 * @return handler to CAS properties instance
 */
struct cas_properties *
cas_properites_parse(struct casdsk_props_conf *caches_serialized_conf);

/**
 * @brief Add unsigned integer to CAS properties instance
 *
 * @param props CAS properties instance to add variable
 * @param key key paired with variable
 * @param value value of variable
 * @param private if true value cannot be updated
 * @return result of adding 0 success
 */
int cas_properties_add_uint(struct cas_properties *props, const char *key,
	uint64_t value, bool private);

/**
 * @brief Add signed integer to CAS properties instance
 *
 * @param props CAS properties instance to add variable
 * @param key key paired with variable
 * @param value value of variable
 * @param private if true value cannot be updated
 * @return result of adding 0 success
 */
int cas_properties_add_sint(struct cas_properties *props, const char *key,
	int64_t value, bool private);

/**
 * @brief Add string to CAS properties instance
 *
 * @param props CAS properties instance to add variable
 * @param key key paired with variable
 * @param value value of variable
 * @param private if true value cannot be updated
 * @return result of adding 0 success
 */
int cas_properties_add_string(struct cas_properties *props, const char *key,
	const char *value, bool private);

/**
 * @brief Get unsigned integer to CAS properties instance
 *
 * @param props CAS properties instance to add variable
 * @param key key paired with variable
 * @param value pointer to memory where we will put value
 * @return result of getting 0 success
 */
int cas_properties_get_uint(struct cas_properties *props, const char *key,
	uint64_t *value);

/**
 * @brief Get signed integer to CAS properties instance
 *
 * @param props CAS properties instance to add variable
 * @param key key paired with variable
 * @param value pointer to memory where we will put value
 * @return result of getting 0 success
 */
int cas_properties_get_sint(struct cas_properties *props, const char *key,
	int64_t *value);

/**
 * @brief Get string integer to CAS properties instance
 *
 * @param props CAS properties instance to add variable
 * @param key key paired with variable
 * @param value pointer to memory where we will put value
 * @param size size of destination memory
 * @return result of getting 0 success, 1 error, 2 not enough space
 *	in destination
 */
int cas_properties_get_string(struct cas_properties *props, const char *key,
	char *value, uint32_t size);


void cas_properties_print(struct cas_properties *props);
#endif /* UTILS_PROPERTIES_H_ */
