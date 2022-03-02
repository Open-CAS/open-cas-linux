/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
*/

#include <stdbool.h>
#include <string.h>
#include "argp.h"
#include "cas_lib.h"
#include "cas_lib_utils.h"
#include <sys/time.h>
#include <sys/stat.h>

#define PADDING "   "
#define MAX_OPT_HELP_LEN 30

extern cas_printf_t cas_printf;

static int is_su_requied(const cli_command* commands, int cmd)
{
	return commands[cmd].flags & CLI_SU_REQUIRED;
}

static int is_command_hidden(const cli_command* commands, int cmd)
{
	return commands[cmd].flags & CLI_COMMAND_HIDDEN;
}

static void print_short_usage(const app *app_values)
{
	cas_printf(LOG_INFO, "Usage: %s %s\n", app_values->name, app_values->info);
}

static void print_info(const app *app_values)
{
	cas_printf(LOG_INFO, "Try `%s --help | -H' for more information.\n", app_values->name);
}

char *get_short_name_string(const char short_name, char *buf)
{
	if (short_name) {
		snprintf(buf, 3, "-%c", short_name);
	} else {
		buf[0] = 0;
	}
	return buf;
}

char *command_name_with_slash(char *buf, size_t buf_size, char short_name, char *long_name) {
	if (short_name) {
		snprintf(buf, buf_size, "-%c/--%s", short_name, long_name);
	} else {
		snprintf(buf, buf_size, "--%s", long_name);
	}
	return buf;
}

char *command_name_in_brackets(char *buf, size_t buf_size, char short_name, char *long_name) {
	if (short_name) {
		snprintf(buf, buf_size, "--%s (-%c)", long_name, short_name);
	 } else {
		snprintf(buf, buf_size, "--%s", long_name);
	 }
	return buf;
}

void print_options_usage(int log_level, cli_option* options,
		const char *separator, int (*view)(cli_option* options, int flag),
		int flag)
{
	int print_separator = 0;
	int i;

	if (NULL == options) {
		return;
	}

	for (i = 0; options[i].long_name != NULL; ++i) {
		if (0 == view(&options[i], flag)) {
			continue;
		}

		if (print_separator) {
			/* Separator */
			cas_printf(log_level, "%s", separator);
		}
		print_separator = 1;

		/* Long option name */
		cas_printf(log_level, "--%s", options[i].long_name);

		/* Parameter */
		if (options[i].arg != NULL) {
			cas_printf(log_level, " <%s>",
			options[i].arg);
		}
	}
}

void print_command_header(const app *app_values, const cli_command *cmd)
{
	cas_printf(LOG_INFO, "%s%s\n\n", PADDING,
			cmd->long_desc != NULL ? cmd->long_desc : cmd->desc);
}

void print_list_options(cli_option* options, int flag,
		int (*view)(cli_option* options, int flag))
{
	char buffer[2048];

	for (; options->long_name != NULL; options++) {
		char *desc = options->desc;
		char short_name[3];

		if (0 == view(options, flag)) {
			continue;
		}

		if ((options->flags & CLI_OPTION_RANGE_INT)
		    || (options->flags & CLI_OPTION_DEFAULT_INT)) {
			desc = buffer;

			if ((options->flags & CLI_OPTION_RANGE_INT)
			    && (options->flags
				& CLI_OPTION_DEFAULT_INT)) {
				snprintf(buffer, sizeof(buffer), options->desc,
					 options->min_value,
					 options->max_value,
					 options->default_value);
			} else if (options->flags & CLI_OPTION_DEFAULT_INT) {
				snprintf(buffer, sizeof(buffer), options->desc,
					 options->default_value);
			} else if (options->flags & CLI_OPTION_RANGE_INT) {
				snprintf(buffer, sizeof(buffer), options->desc,
					 options->min_value,
					 options->max_value);
			}
		}

		get_short_name_string(options->short_name, short_name);
		if (options->arg != NULL) {
			char buf[MAX_OPT_HELP_LEN];
			if (options->flags & CLI_OPTION_OPTIONAL_ARG) {
				snprintf(buf, MAX_OPT_HELP_LEN, "--%s [<%s>]",
					 options->long_name, options->arg);
			} else {
				snprintf(buf, MAX_OPT_HELP_LEN, "--%s <%s>",
					 options->long_name, options->arg);
			}

			cas_printf(LOG_INFO, "%s%-4s%-32s%s\n", PADDING,
				   short_name, buf, desc);
		} else {
			cas_printf(LOG_INFO, "%s%-4s--%-30s%s\n", PADDING,
				   short_name, options->long_name, desc);
		}
	}
}

static void print_options_help(cli_option *options)
{
	char buffer[2048];
	int i;

	for (i = 0; options[i].long_name != NULL; ++i) {
		char *desc = options[i].desc;
		char short_name[3];
		if (options[i].flags & CLI_OPTION_HIDDEN) {
			continue;
		}

		if ((options[i].flags & CLI_OPTION_RANGE_INT)
		     || (options[i].flags & CLI_OPTION_DEFAULT_INT) ) {
			desc = buffer;

			if ((options[i].flags & CLI_OPTION_RANGE_INT)
			     && (options[i].flags & CLI_OPTION_DEFAULT_INT) ) {
				snprintf(buffer, sizeof(buffer), options[i].desc,
					options[i].min_value,
					options[i].max_value,
					options[i].default_value);
			} else if (options[i].flags & CLI_OPTION_DEFAULT_INT) {
				snprintf(buffer, sizeof(buffer), options[i].desc,
					options[i].default_value);
			} else if (options[i].flags & CLI_OPTION_RANGE_INT) {
				snprintf(buffer, sizeof(buffer), options[i].desc,
					options[i].min_value,
					options[i].max_value);
			}
		}
		get_short_name_string(options[i].short_name, short_name);
		if (options[i].arg != NULL) {
			char buf[MAX_OPT_HELP_LEN];
			if (options[i].flags & CLI_OPTION_OPTIONAL_ARG) {
				snprintf(buf, MAX_OPT_HELP_LEN, "--%s [<%s>]",
					 options[i].long_name,
					 options[i].arg);
			} else {
				snprintf(buf, MAX_OPT_HELP_LEN, "--%s <%s>",
					 options[i].long_name,
					 options[i].arg);
			}

			cas_printf(LOG_INFO, "%s%-4s%-32s%s\n", PADDING,
					short_name, buf, desc);
		} else {
			cas_printf(LOG_INFO, "%s%-4s--%-30s%s\n", PADDING,
					short_name, options[i].long_name,
					desc);
		}
	}
}

static void print_namespace_help(app *app_values, cli_command *cmd)
{
	char command_name[MAX_STR_LEN];
	char option_name[MAX_STR_LEN];
	cli_namespace *ns = cmd->namespace;
	int i;

	cas_printf(LOG_INFO, "Usage: %s --%s --%s <NAME>\n\n", app_values->name,
			cmd->name, ns->long_name);

	print_command_header(app_values, cmd);

	command_name_in_brackets(command_name, MAX_STR_LEN, cmd->short_name, cmd->name);
	command_name_in_brackets(option_name, MAX_STR_LEN, ns->short_name, ns->long_name);


	cas_printf(LOG_INFO, "Valid values of NAME are:\n");
	for (i = 0; ns->entries[i].name; ++i)
		cas_printf(LOG_INFO, "%s%s - %s\n", PADDING, ns->entries[i].name, ns->entries[i].desc);

	cas_printf(LOG_INFO, "\n");

	for (i = 0; ns->entries[i].name; ++i) {
		cas_printf(LOG_INFO, "Options that are valid with %s %s %s are:\n",
				command_name, option_name, ns->entries[i].name);
		print_options_help(ns->entries[i].options);
		if (ns->entries[i + 1].name)
			cas_printf(LOG_INFO, "\n");
	}
}

static void print_command_help(app *app_values, cli_command *cmd)
{
	int all_mandatory = 1;
	int all_hidden = 1;
	int i;

	if (cmd->help) {
		(cmd->help)(app_values, cmd);
		return;
	}

	if (cmd->namespace) {
		print_namespace_help(app_values, cmd);
		return;
	}

	cas_printf(LOG_INFO, "Usage: %s --%s", app_values->name, cmd->name);

	if (cmd->options != NULL) {
		for (i = 0; cmd->options[i].long_name != NULL; ++i) {
			if (cmd->options[i].flags & CLI_OPTION_HIDDEN) {
				continue;
			}

			all_hidden = 0;

			if (cmd->options[i].flags & CLI_OPTION_REQUIRED) {
				cas_printf(LOG_INFO, " --%s", cmd->options[i].long_name);
				if (cmd->options[i].arg != NULL) {
					if (cmd->options[i].flags & CLI_OPTION_OPTIONAL_ARG) {
						cas_printf(LOG_INFO, " [<%s>]", cmd->options[i].arg);
					} else {
						cas_printf(LOG_INFO, " <%s>", cmd->options[i].arg);
					}
				}
			} else {
				all_mandatory = 0;
			}
		}

		if (!all_mandatory) {
			cas_printf(LOG_INFO, " [option...]");
		}
	}
	cas_printf(LOG_INFO, "\n\n");

	print_command_header(app_values, cmd);

	if (cmd->options && !all_hidden) {
		char option_name[MAX_STR_LEN];
		command_name_in_brackets(option_name, MAX_STR_LEN, cmd->short_name, cmd->name);
		cas_printf(LOG_INFO, "Options that are valid with %s are:\n", option_name);
		print_options_help(cmd->options);
	}
}

void print_help(const app *app_values, const cli_command *commands)
{
	int i;

	cas_printf(LOG_INFO, "%s\n\n", app_values->title);
	print_short_usage(app_values);
	cas_printf(LOG_INFO, "\nAvailable commands:\n");

	for (i = 0;; ++i) {
		char short_name[3];

		if (commands[i].name == NULL) {
			break;
		}

		if (is_command_hidden(commands, i))
			continue;

		get_short_name_string(commands[i].short_name, short_name);

		cas_printf(LOG_INFO, "%s%-4s--%-25s%s\n", PADDING, short_name,
				commands[i].name, commands[i].desc);
	}

	cas_printf(LOG_INFO, "\nFor detailed help on the above commands use --help after the command.\n"
			"e.g.\n%s%s --%s --help\n",
			PADDING, app_values->name, commands[0].name);

	if (app_values->man != NULL) {
		cas_printf(LOG_INFO,
			   "For more information, please refer to manual, Admin Guide (man %s)\n"
			   "or go to support page <https://open-cas.github.io>.\n",
			   app_values->man);
	} else {
		cas_printf(LOG_INFO,
			   "For more information, please refer to manual, Admin Guide\n"
			   "or go to support page <https://open-cas.github.io>.\n");
	}
}

static int args_is_unrecognized(const char *cmd)
{
	if (strempty(cmd)) {
		return 1;
	}

	if ('-' == cmd[0]) {
		char c = cmd[1];

		/* Check if short option (command) is proper */
		if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')) {
			if ('\0' == cmd[2]) {
				return 0;
			} else {
				return 1;
			}
		}

		if ('-' == cmd[1]) {
			char c = cmd[2];
			/* Long option (command), check if it is valid */

			if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')) {
				return 0;
			}
		}
	}

	return 1;
}

static int args_is(const char *in, const char *arg, const char c)
{
	if (strempty(in)) {
		return 0;
	}

	if ('-' == in[0]) {
		if (0 != c && c == in[1]) {
			if ('\0' == in[2]) {
				return 1;
			}
		}

		if ('-' == in[1]) {
			/* Long option */
			if (0 == strncmp(&(in[2]), arg, MAX_STR_LEN)) {
				return 1;
			}
		}
	}

	return 0;
}

static int is_help(const char* cmd)
{
	return args_is(cmd, "help", 'H');
}

static int get_help_position(int argc, const char **argv)
{
	int i;
	for (i = 2; i < argc; i++) {
		if (is_help(argv[i])) {
			return i;
		}
	}

	return -1;
}

static int get_option(const cli_option *options, const char* opt)
{
	int i;

	for (i = 0; options[i].long_name; ++i) {
		if (args_is(opt, options[i].long_name, options[i].short_name)) {
			return i;
		}
	}

	return -1;
}

/**
 * log command as it was entered in CLI
 */
void log_command(int argc, const char **argv, int result, long long int timespan)
{
	const int def_cmd_buf_len = 100;
	int cmd_buf_len = def_cmd_buf_len;
	int cmd_len = 0;
	int i = 0;
	char *command = malloc(cmd_buf_len);

	if (!command) {
		cas_printf(LOG_ERR, "Memory allocation failed for logging.");
		return;
	}

	for (i = 0 ; i != argc ; ++i) {
		int tok_len = strnlen_s(argv[i], MAX_STR_LEN);
		/* if reconstructed command width is longer than current
		 * cmd_buf_len (length of command buffer), than resize it
		 * to make it twice as big.
		 */
		if (tok_len + 1 + cmd_len > cmd_buf_len) {
			cmd_buf_len = (tok_len + 1 + cmd_buf_len) * 2;
			char *tmp = realloc(command, cmd_buf_len);
			/* if reallocation failed, cancel logging */
			if (!tmp) {
				cas_printf(LOG_ERR,
					   "Memory allocation failed for logging.");
				free(command);
				return;
			}
			command = tmp;
		}
		/* append additional token to a string */
		memcpy_s(command + cmd_len, cmd_buf_len - cmd_len,
			 argv[i], tok_len);
		cmd_len += tok_len;
		/* either a space or a null terminator */
		command[cmd_len] = (i == argc - 1) ? 0 : ' ';
		cmd_len++;
	}

	caslog(LOG_DEBUG, "Casadm invoked with: \"%s\". "
			"Exit status is %d (%s). Command took %lld.%02lld s.",
			command, result, result? "failure" : "success",
			timespan / 1000, (timespan % 1000) / 10);
	free(command);
}

static inline long long int timeval_to_msec(struct timeval t)
{
	return 1000 * t.tv_sec + t.tv_usec / 1000;
}

/**
 * run command. Additionally log its execution and report any errors if
 * they've happened
 */
int run_command(cli_command *commands, int cmd, int argc, const char **argv)
{
	int result;
	const char *syslog_path = "/var/log/messages";
	struct timeval t0, t1;
	FILE *messages_f;
	long long int timespan;

	/* collect time */
	gettimeofday(&t0, NULL);
	/* collect stat buffer for syslog */
	messages_f = fopen(syslog_path, "r");
	if (messages_f) {
		fseek(messages_f, 0, SEEK_END);
		/* if opening file failed, don't stop command execution.
		 * - just omit checking for /var/log/messages at the end
		 */
	} else {
		/* ubuntu case*/
		syslog_path = "/var/log/syslog";
		messages_f = fopen(syslog_path, "r");
		if (messages_f) {
			fseek(messages_f, 0, SEEK_END);
		}
	}

	/* execute CAS command */
	result = commands[cmd].handle();
	gettimeofday(&t1, NULL);
	timespan = timeval_to_msec(t1) - timeval_to_msec(t0);

	if (commands[cmd].short_name != 'V') {
		log_command(argc, argv, result, timespan);
	}

	/* print extra warning message IF command ended with failure and
	 * syslog contains something */
	if (FAILURE == result && messages_f) {
		char line_buf[MAX_STR_LEN];
		bool kernel_said = false; /* set to true if CAS kernel module
					   * said anything during command
					   * execution */
		while (fgets(line_buf, MAX_STR_LEN - 1, messages_f)) {
			line_buf[MAX_STR_LEN - 1] = 0;
			if (strstr(line_buf, "CAS") &&
			    strstr(line_buf, "kernel")) {
				kernel_said = true;
			}
		}

		if (kernel_said) {
			fprintf(stderr, "Error occurred, "
				   "please see syslog (%s) for details. \n",
				   syslog_path);
		}
	}

	if (messages_f) {
		fclose(messages_f);
	}

	return result;
}

static int count_arg_params(const char **argv, int argc)
{
	int i = 0;

	for (i = 0; i < argc; i++) {
		if ('-' == argv[i][0] && 0 != argv[i][1]) {
			break;
		}
	}

	return i;
}

void configure_cli_commands(cli_command *commands)
{
	cli_command *cmd = commands;
	int ret;

	while(cmd->name) {
		if (cmd->configure) {
			ret = cmd->configure(cmd);
			if (ret < 0) {
				cmd->flags |= CLI_COMMAND_HIDDEN;
			}
		}
		cmd++;
	}
}

int args_parse(app *app_values, cli_command *commands, int argc, const char **argv)
{
	int i, j, k, status = SUCCESS;
	int args_count, args_offset;
	const char **args_list = NULL;
	const char* cmd_name = argv[1];
	cli_ns_entry *entry = NULL;
	cli_option *options;
	int cmd, first_opt;

	if (argc < 2) {
		cas_printf(LOG_ERR, "No command given.\n");
		print_info(app_values);
		return FAILURE;
	}

	if (args_is_unrecognized(cmd_name)) {
		cas_printf(LOG_ERR, "Unrecognized command %s\n", cmd_name);
		print_info(app_values);
		return FAILURE;
	}

	for (i = 0;; ++i) {
		if (commands[i].name == NULL) {
			if (is_help(cmd_name)) {
				print_help(app_values, commands);
				return SUCCESS;
			} else {
				cas_printf(LOG_ERR, "Unrecognized command %s\n",
						cmd_name);
				print_info(app_values);
			}
			return FAILURE;
		} else if (args_is(cmd_name, commands[i].name, commands[i].short_name)) {
			cmd = i;
			break;
		}
	}

	configure_cli_commands(commands);

	if (argc >= 3 && get_help_position(argc, argv) != -1) {
		if (!is_command_hidden(commands, i)) {
			print_command_help(app_values, &commands[i]);
		}
		return SUCCESS;
	}

	if (is_su_requied(commands, cmd)) {
		if (getuid() != 0) {
			cas_printf(LOG_ERR, "Must be run as root.\n");
			return FAILURE;
		}
	}

	if (commands[cmd].options) {
		options = commands[cmd].options;
		first_opt = 2;
	} else if (commands[cmd].namespace) {
		if (argc < 3) {
			cas_printf(LOG_ERR, "Missing namespace option.\n");
			print_info(app_values);
			return FAILURE;
		}
		if (argc < 4) {
			cas_printf(LOG_ERR, "Missing namespace name.\n");
			print_info(app_values);
			return FAILURE;
		}
		if (!args_is(argv[2], commands[cmd].namespace->long_name,
				commands[cmd].namespace->short_name)) {
			cas_printf(LOG_ERR, "Unrecognized option.\n");
			print_info(app_values);
			return FAILURE;
		}

		entry = commands[cmd].namespace->entries;
		while (true) {
			if (!strcmp(argv[3], entry->name))
				break;
			if (!(++entry)->name) {
				cas_printf(LOG_ERR, "Unrecognized namespace entry.\n");
				print_info(app_values);
				return FAILURE;
			}
		}
		options = entry->options;
		first_opt = 4;
	} else {
		return run_command(commands, cmd, argc, argv);
	}

	/* for each possible option:
	 *  - if it is required, check if it is supplied exactly once
	 *  - if it is not required, check if it is supplied at most once
	 */
	for (i = 0; options[i].long_name; ++i) {
		char option_name[MAX_STR_LEN];

		/* count occurrences of an option (k as counter) */
		k = 0;
		for (j = first_opt; j < argc; ++j) {
			if (args_is(argv[j], options[i].long_name,
					options[i].short_name)) {
				k++;
			}
		}

		command_name_with_slash(option_name, MAX_STR_LEN,
			options[i].short_name, options[i].long_name);

		if (options[i].flags & CLI_OPTION_REQUIRED) {
			if (!k) {
				cas_printf(LOG_ERR, "Missing required option %s\n",  option_name);
				print_info(app_values);
				return FAILURE;
			}
		}
		if (k > 1) {
			cas_printf(LOG_ERR, "Option supplied more than once %s\n", option_name);
			print_info(app_values);
			return FAILURE;
		}
	}

	/* Store parameters for arguments. Terminate each list with NULL element.
	 * Accomodate for max no of parameters */
	args_list = malloc(sizeof(*args_list) * (argc + 1));

	if (args_list == NULL) {
		return FAILURE;
	}

	/* iterate over all arguments that were actually passed to the CLI */
	args_count = args_offset = 0;
	for (i = first_opt; i < argc; ++i) {
		int opt;

		if (args_is_unrecognized(argv[i])) {
			cas_printf(LOG_ERR, "Invalid format %s\n",
					argv[i]);
			print_info(app_values);

			status = FAILURE;
			goto free_args;
		}

		opt = get_option(options, argv[i]);
		if (opt == -1) {
			cas_printf(LOG_ERR, "Unrecognized option %s\n",
					argv[i]);
			print_info(app_values);

			status = FAILURE;
			goto free_args;
		}

		if (options[opt].arg != NULL) {

			/* Count params for current argument. */
			args_count = count_arg_params(&argv[i + 1], argc - i - 1);

			if (args_count == 0 && !(options[opt].flags & CLI_OPTION_OPTIONAL_ARG)) {

				cas_printf(LOG_ERR, "Missing required argument in %s\n",
						argv[i]);
				print_info(app_values);

				status = FAILURE;
				goto free_args;
			}

			if (-1 != options[opt].args_count &&
				args_count != options[opt].args_count &&
				(0 != args_count || !(options[opt].flags & CLI_OPTION_OPTIONAL_ARG))) {

				cas_printf(LOG_ERR, "Invalid number of arguments for %s\n",
						argv[i]);
				print_info(app_values);

				status = FAILURE;
				goto free_args;
			}

			/* Add params for current argument.
			 * Terminate list with NULL element.*/
			for (k = args_offset, j = 0; j < args_count; j++) {
				args_list[k++] = argv[j + i + 1];
			}
			args_list[args_offset + args_count] = NULL;

			i += args_count;
		}

		if (commands[cmd].command_handle_opts) {
			status = commands[cmd].command_handle_opts(
					options[opt].long_name,
					&args_list[args_offset]);
		} else if (commands[cmd].namespace_handle_opts) {
			status = commands[cmd].namespace_handle_opts(
					entry->name,
					options[opt].long_name,
					&args_list[args_offset]);
		} else {
			cas_printf(LOG_ERR, "Internal error\n");
			status = FAILURE;
			goto free_args;
		}
		args_offset += args_count;

		if (0 != status) {
			cas_printf(LOG_ERR, "Error during options handling\n");
			print_info(app_values);

			status = FAILURE;
			goto free_args;
		}
	}

	status = run_command(commands, cmd, argc, argv);

free_args:
	if (NULL != args_list) {
		free(args_list);
		args_list = NULL;
	}

	return status;
}
