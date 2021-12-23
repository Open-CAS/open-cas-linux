/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef __STAT_VIEW
#define __STAT_VIEW

#include <stdio.h>

/* each line of statistics may be assigned one fo these semantic formats,
 * to which it will be converted */

enum tag_type {
	FREEFORM, /**< free form text */
	KV_PAIR, /**< key value pair. sequence of kv-pairs will be aligned to
		    columns, but no table-styleborders will be drawn */
	TABLE_ROW, /**< regular table row */
	TABLE_HEADER, /**< table header */
	TABLE_SECTION, /**< first row of a table section */
	DATA_SET, /**< set of records */
	RECORD, /**< one record of data */
	TREE_HEADER,
	TREE_BRANCH,
	TREE_LEAF,
	UNDEFINED_TAG /**< occurence of this (or anything else out of
			 above tags) will immediately break processing */
};

#define TAG(x) #x ","
#define TAG_NAME(x) #x

enum format {
	TEXT, /**< output in text (formatted tables) form */
	CSV, /**< output in csv form */
	RAW_CSV, /**< csv form without transformations */
	PLAIN /**<debug setting: print intermediate format */
};

/**
 * @param infile - file in statistics_view intermediate format
 * @param outfile - file to which statistics need to be printed
 * @param format - desired format of an output.
 */
int stat_format_output(FILE *infile, FILE *outfile, int format);

/*
 * EXAMPLE OF AN INTERMEDIATE FORMAT:
 *
 * DATA_SET,
 * RECORD,
 * KV_PAIR,Cache Id, 1
 * KV_PAIR,Cache Size, 5425999, [4KiB Blocks], 20.70, [GiB]
 * KV_PAIR,Cache Occupancy, 1340, [4KiB Blocks], 0.01, [GiB],  0.02, [%]
 * KV_PAIR,Metadata end offset, 79025
 * KV_PAIR,Dirty cache lines, 0
 * KV_PAIR,Clean cache lines, 1340
 * KV_PAIR,Cache Device, /dev/sdb
 * KV_PAIR,Core Devices, 15
 * KV_PAIR,Write Policy, wt
 * KV_PAIR,Eviction Policy, lru
 * KV_PAIR,Cleaning Policy, alru
 * KV_PAIR,Metadata Variant, "max (Maximum Performance, default)"
 * KV_PAIR,Metadata Memory Footprint, 345.4, [MiB]
 * KV_PAIR,Status, Running
 * TABLE_HEADER,Request statistics,Count,%
 * TABLE_SECTION,"Read hits", 180,  11.6
 * TABLE_ROW,"Read partial misses", 1,   0.1
 * TABLE_ROW,"Read full misses", 1370,  88.3
 * TABLE_ROW,"Read total", 1551, 100.0
 * TABLE_SECTION,"Write hits", 0,   0.0
 * TABLE_ROW,"Write partial misses", 0,   0.0
 * TABLE_ROW,"Write full misses", 0,   0.0
 * TABLE_ROW,"Write total", 0,   0.0
 *
 * In each of output formats, first CSV column (referred to as a "tag")
 * will be removed from output and used by formatter thread as a hint
 */
#endif /*__STAT_VIEW */
