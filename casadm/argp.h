/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#ifndef _ARGP_H
#define _ARGP_H

#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

enum CLI_OPTION_FLAGS {
	CLI_OPTION_REQUIRED		= 1 << 0,
	CLI_OPTION_HIDDEN		= 1 << 1,
	CLI_OPTION_RANGE_INT		= 1 << 2, /*! if option has a min/max value */
	CLI_OPTION_DEFAULT_INT		= 1 << 3, /*! if option has a default value */
	CLI_OPTION_OPTIONAL_ARG		= 1 << 4,  /*! if option argument is optional */
	CLI_OPTION_SUBCMD		= 1 << 5  /*! if option is a subcmd */
};

enum CLI_COMMAND_FLAGS {
	CLI_SU_REQUIRED			= 1 << 0,
	CLI_COMMAND_HIDDEN		= 1 << 1
};

#define	ERROR		-1
#define	SUCCESS		0
#define	FAILURE		1

/**
 * structure repsesenting each single option for CLI command (i.e. -i, -j for -R)
 */
typedef struct {
	char short_name;	/*!< short option name, one-letter. i.e. 'i' representing -i
				 *!< as --cache-id */
	char* long_name;	/*!< long option name (in above described case it would be
				 *!< "cache-id" */
	char* desc;		/*!< description of an option (longer text...
				 *!< may contain single %d for default value and/or pair of %d marks
				 *!< for range of correct values. If it has both, default must come
				 *!< after the range, so be careful about wording such messages) */
	int args_count;		/*!< number of arguments (0 - no arguments, -1 - unspecified) */
	char* arg;		/*!< type of an argument, descriptive. i.e. "NUM", "NAME" */
	int flags;		/*!< as per CLI_OPTION_FLAGS */
	int min_value;		/*!< min parameter value. (optional) */
	int max_value;		/*!< max parameter value. (optional) */
	int default_value;	/*!< default parameter value. (optional) */
	int priv;		/*!< Private filed for command handler */
} cli_option;

/*
 * In namespace entries options array is nested in another flexible array
 * (array of entries), so it cannot be flexible array itself. Because of that
 * we make it static array of options with reasonable lenght.
 */
#define MAX_OPTIONS 32

typedef struct {
	char* name;		/*!< namespace entry name */
	char* desc;		/*!< description of an namespace entry */
	cli_option options[MAX_OPTIONS];
				/*!< pointer to first element in null-terminated array of cli_option */
} cli_ns_entry;

typedef struct {
	char short_name;	/*!< short name of namespace */
	char* long_name;	/*!< long name of namespace */
	cli_ns_entry entries[];	/*!< null-terminated array of namespace entries */
} cli_namespace;

typedef struct {
	const char* name;
	char* info;
	char* title;
	char* doc;
	char* man;
	int block;
} app;

struct _cli_command;
typedef struct _cli_command cli_command;

/**
 * structure representing each CLI command, i.e. -S, -T...
 */
struct _cli_command {
	char* name;		/*!< name of command (i.e. "start-cache" for --start-cache) */

	char short_name;	/*!< short name of command (i.e. "S" for -S/--start-cache) */

	char* desc;		/*!< description that appears with "casadm -H" invocation */

	char* long_desc;	/*!< option descripotion that appears with "casadm -O -H invocation */

	cli_option* options;	/*!< pointer to first element in null-terminated array of cli_option */

	int (*command_handle_opts)(char*, const char**);
				/*! function pointer to function that processes options to command */

	cli_namespace* namespace;
				/*! namespace description */

	int (*namespace_handle_opts)(char*, char*, const char**);
				/*! function pointer to function that processes options to namespace */

	int (*handle)(void);	/*! function pointer to function that executes a command */

	int flags;		/*! command flags, as per CLI_COMMAND_FLAGS */

	void (*help)(app *app_values, cli_command *cmd);
				/*! Custom help provider */
	int (*configure)(cli_command *cmd);
				/*! function pointer to function that configures command */
};

char *command_name_in_brackets(char *buf, size_t buf_size, char short_name, char *long_name);

void print_help(const app *app_values, const cli_command *commands);

void print_options_usage(int log_level, cli_option* options,
		const char *separator, int (*view)(cli_option* options, int flag),
		int flag);

void print_list_options(cli_option* options, int flag,
		int (*view)(cli_option* options, int flag));

void print_command_header(const app *app_values, const cli_command *cmd);

void configure_cli_commands(cli_command *commands);

int args_parse(app *app_values, cli_command *commands, int argc, const char **argv);

#endif
