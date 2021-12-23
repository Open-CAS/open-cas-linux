#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

casadm_help = [
    r"Cache Acceleration Software Linux",
    r"Usage: casadm \<command\> \[option\.\.\.\]",
    r"Available commands:",
    r"-S  --start-cache              Start new cache instance or load using metadata",
    r"-T  --stop-cache               Stop cache instance",
    r"-X  --set-param                Set various runtime parameters",
    r"-G  --get-param                Get various runtime parameters",
    r"-Q  --set-cache-mode           Set cache mode",
    r"-A  --add-core                 Add core device to cache instance",
    r"-R  --remove-core              Remove core device from cache instance",
    r"--remove-detached          Remove core device from core pool",
    r"-L  --list-caches              List all cache instances and core devices",
    r"-P  --stats                    Print statistics for cache instance",
    r"-Z  --reset-counters           Reset cache statistics for core device within cache instance",
    r"-F  --flush-cache              Flush all dirty data from the caching device to core devices",
    r"-E  --flush-core               Flush dirty data of a given core from the caching device "
    r"to this core device",
    r"-C  --io-class                 Manage IO classes",
    r"-V  --version                  Print CAS version",
    r"-H  --help                     Print help",
    r"--zero-metadata            Clear metadata from caching device",
    r"For detailed help on the above commands use --help after the command\.",
    r"e\.g\.",
    r"casadm --start-cache --help",
    r"For more information, please refer to manual, Admin Guide \(man casadm\)",
    r"or go to support page \<https://open-cas\.github\.io\>\."
]

help_help = [
    r"Usage: casadm --help",
    r"Print help"
]

version_help = [
    r"Usage: casadm --version \[option\.\.\.\]",
    r"Print CAS version",
    r"Options that are valid with --version \(-V\) are:"
    r"-o  --output-format \<FORMAT\>        Output format: \{table|csv\}"
]

ioclass_help = [
    r"Usage: casadm --io-class \{--load-config|--list\}",
    r"Manage IO classes",
    r"Loads configuration for IO classes:",
    r"Usage: casadm --io-class --load-config --cache-id \<ID\> --file \<FILE\>",
    r"Options that are valid with --load-config \(-C\) are:",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\>",
    r"-f  --file \<FILE\>                   Configuration file containing IO class definition",
    r"Lists currently configured IO classes:",
    r"Usage: casadm --io-class --list --cache-id \<ID\> \[option\.\.\.\]",
    r"Options that are valid with --list \(-L\) are:",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\>",
    r"-o  --output-format \<FORMAT\>        Output format: \{table|csv\}"
]

flush_core_help = [
    r"Usage: casadm --flush-core --cache-id \<ID\> --core-id \<ID\>",
    r"Flush dirty data of a given core from the caching device to this core device",
    r"Options that are valid with --flush-core \(-E\) are:",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\>",
    r"-j  --core-id \<ID\>                  Identifier of core \<0-4095\> within given cache "
    r"instance"
]

flush_cache_help = [
    r"Usage: casadm --flush-cache --cache-id \<ID\>",
    r"Flush all dirty data from the caching device to core devices",
    r"Options that are valid with --flush-cache \(-F\) are:",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\>"
]

reset_counters_help = [
    r"Usage: casadm --reset-counters --cache-id \<ID\> \[option\.\.\.\]",
    r"Reset cache statistics for core device within cache instance",
    r"Options that are valid with --reset-counters \(-Z\) are:",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\>",
    r"-j  --core-id \<ID\>                  Identifier of core \<0-4095\> within given cache "
    r"instance. If not specified, statistics are reset for all cores in cache instance\."
]

stats_help = [
    r"Usage: casadm --stats --cache-id \<ID\> \[option\.\.\.\]",
    r"Print statistics for cache instance",
    r"Options that are valid with --stats \(-P\) are:",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\>",
    r"-j  --core-id \<ID\>                  Limit display of core-specific statistics to only ones "
    r"pertaining to a specific core. If this option is not given, casadm will display statistics "
    r"pertaining to all cores assigned to given cache instance\.",
    r"-d  --io-class-id \[\<ID\>\]            Display per IO class statistics",
    r"-f  --filter \<FILTER-SPEC\>          Apply filters from the following set: "
    r"\{all, conf, usage, req, blk, err\}",
    r"-o  --output-format \<FORMAT\>        Output format: \{table|csv\}"
]

list_help = [
    r"Usage: casadm --list-caches \[option\.\.\.\]",
    r"List all cache instances and core devices",
    r"Options that are valid with --list-caches \(-L\) are:",
    r"-o  --output-format \<FORMAT\>        Output format: \{table|csv\}"
]

remove_detached_help = [
    r"Usage: casadm --remove-detached --device \<DEVICE\>",
    r"Remove core device from core pool",
    r"Options that are valid with --remove-detached are:",
    r"-d  --device \<DEVICE\>               Path to core device"
]

remove_core_help = [
    r"Usage: casadm --remove-core --cache-id \<ID\> --core-id \<ID\> \[option\.\.\.\]",
    r"Remove core device from cache instance",
    r"Options that are valid with --remove-core \(-R\) are:",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\>",
    r"-j  --core-id \<ID\>                  Identifier of core \<0-4095\> within given cache "
    r"instance",
    r"-f  --force                         Force remove inactive core"
]

add_core_help = [
    r"Usage: casadm --add-core --cache-id \<ID\> --core-device \<DEVICE\> \[option\.\.\.\]",
    r"Add core device to cache instance",
    r"Options that are valid with --add-core \(-A\) are:",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\>",
    r"-j  --core-id \<ID\>                  Identifier of core \<0-4095\> within given cache "
    r"instance",
    r"-d  --core-device \<DEVICE\>          Path to core device"

]

set_cache_mode_help = [
    r"Usage: casadm --set-cache-mode --cache-mode \<NAME\> --cache-id \<ID\> \[option\.\.\.\]",
    r"Set cache mode",
    r"Options that are valid with --set-cache-mode \(-Q\) are:",
    r"-c  --cache-mode \<NAME\>             Cache mode. Available cache modes: \{wt|wb|wa|pt|wo\}",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\>",
    r"-f  --flush-cache \<yes|no\>          Flush all dirty data from cache before switching "
    r"to new mode\. Option is required when switching from Write-Back or Write-Only mode"
]

get_params_help = [
    r"Usage: casadm --get-param --name \<NAME\>",
    r"Get various runtime parameters",
    r"Valid values of NAME are:",
    r"seq-cutoff - Sequential cutoff parameters",
    r"cleaning - Cleaning policy parameters",
    r"cleaning-alru - Cleaning policy ALRU parameters",
    r"cleaning-acp - Cleaning policy ACP parameters",
    r"promotion - Promotion policy parameters",
    r"promotion-nhit - Promotion policy NHIT parameters",
    r"Options that are valid with --get-param \(-G\) --name \(-n\) seq-cutoff are:",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\>",
    r"-j  --core-id \<ID\>                  Identifier of core \<0-4095\> within given cache "
    r"instance",
    r"-o  --output-format \<FORMAT\>        Output format: \{table|csv\}",
    r"Options that are valid with --get-param \(-G\) --name \(-n\) cleaning are:",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\>",
    r"-o  --output-format \<FORMAT\>        Output format: \{table|csv\}",
    r"Options that are valid with --get-param \(-G\) --name \(-n\) cleaning-alru are:",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\>",
    r"-o  --output-format \<FORMAT\>        Output format: \{table|csv\}",
    r"Options that are valid with --get-param \(-G\) --name \(-n\) cleaning-acp are:",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\>",
    r"-o  --output-format \<FORMAT\>        Output format: \{table|csv\}",
    r"Options that are valid with --get-param \(-G\) --name \(-n\) promotion are:",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\>",
    r"-o  --output-format \<FORMAT\>        Output format: \{table|csv\}",
    r"Options that are valid with --get-param \(-G\) --name \(-n\) promotion-nhit are:",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\>",
    r"-o  --output-format \<FORMAT\>        Output format: \{table|csv\}"
]

set_params_help = [
    r"Usage: casadm --set-param --name \<NAME\>",
    r"Set various runtime parameters",
    r"Valid values of NAME are:",
    r"seq-cutoff - Sequential cutoff parameters",
    r"cleaning - Cleaning policy parameters",
    r"promotion - Promotion policy parameters",
    r"promotion-nhit - Promotion policy NHIT parameters",
    r"cleaning-alru - Cleaning policy ALRU parameters",
    r"cleaning-acp - Cleaning policy ACP parameters",
    r"Options that are valid with --set-param \(-X\) --name \(-n\) seq-cutoff are:",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\>",
    r"-j  --core-id \<ID\>                  Identifier of core \<0-4095\> within given cache "
    r"instance",
    r"-t  --threshold \<KiB\>               Sequential cutoff activation threshold \[KiB\]",
    r"-p  --policy \<POLICY\>               Sequential cutoff policy. Available policies: "
    r"\{always|full|never\}",
    r"Options that are valid with --set-param \(-X\) --name \(-n\) cleaning are:",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\>",
    r"-p  --policy \<POLICY\>               Cleaning policy type. Available policy types: "
    r"\{nop|alru|acp\}",
    r"Options that are valid with --set-param \(-X\) --name \(-n\) promotion are:",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\>",
    r"-p  --policy \<POLICY\>               Promotion policy type. Available policy types: "
    r"\{always|nhit\}",
    r"Options that are valid with --set-param \(-X\) --name \(-n\) promotion-nhit are:",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\>",
    r"-t  --threshold \<NUMBER\>            Number of requests for given core line after which "
    r"NHIT policy allows insertion into cache \<2-1000\> \(default: 3\)",
    r"-o  --trigger \<NUMBER\>              Cache occupancy value over which NHIT promotion "
    r"is active \<0-100\>\[\%\] \(default: 80\%\)",
    r"Options that are valid with --set-param \(-X\) --name \(-n\) cleaning-alru are:",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\>",
    r"-w  --wake-up \<NUMBER\>              Period of time between awakenings of flushing thread "
    r"\<0-3600\>\[s\] \(default: 20 s\)",
    r"-s  --staleness-time \<NUMBER\>       Time that has to pass from the last write operation "
    r"before a dirty cache block can be scheduled to be flushed \<1-3600\>\[s\] \(default: 120 s\)",
    r"-b  --flush-max-buffers \<NUMBER\>    Number of dirty cache blocks to be flushed in one "
    r"cleaning cycle \<1-10000\> \(default: 100\)",
    r"-t  --activity-threshold \<NUMBER\>   Cache idle time before flushing thread can start "
    r"\<0-1000000\>\[ms\] \(default: 10000 ms\)",
    r"Options that are valid with --set-param \(-X\) --name \(-n\) cleaning-acp are:",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\>",
    r"   -w  --wake-up \<NUMBER\>              Time between ACP cleaning thread iterations "
    r"\<0-10000\>\[ms\] \(default: 10 ms\)",
    r"-b  --flush-max-buffers \<NUMBER\>    Number of cache lines flushed in single ACP cleaning "
    r"thread iteration \<1-10000\> \(default: 128\)"
]

stop_cache_help = [
    r"Usage: casadm --stop-cache --cache-id \<ID\> \[option\.\.\.\]",
    r"Stop cache instance",
    r"Options that are valid with --stop-cache \(-T\) are:",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\>",
    r"-n  --no-data-flush                 Do not flush dirty data \(may be dangerous\)"
]

start_cache_help = [
    r"Usage: casadm --start-cache --cache-device \<DEVICE\> \[option\.\.\.\]",
    r"Start new cache instance or load using metadata",
    r"Options that are valid with --start-cache \(-S\) are:",
    r"-d  --cache-device \<DEVICE\>         Caching device to be used",
    r"-i  --cache-id \<ID\>                 Identifier of cache instance \<1-16384\> "
    r"\(if not provided, the first available number will be used\)",
    r"-l  --load                          Load cache metadata from caching device "
    r"\(DANGEROUS - see manual or Admin Guide for details\)",
    r"-f  --force                         Force the creation of cache instance",
    r"-c  --cache-mode \<NAME\>             Set cache mode from available: \{wt|wb|wa|pt|wo\} "
    r"Write-Through, Write-Back, Write-Around, Pass-Through, Write-Only; "
    r"without this parameter Write-Through will be set by default",
    r"-x  --cache-line-size \<NUMBER\>      Set cache line size in kibibytes: "
    r"\{4,8,16,32,64\}\[KiB\] \(default: 4\)"
]

zero_metadata_help = [
    r"Usage: casadm --zero-metadata --device \<DEVICE\>",
    r"Clear metadata from caching device",
    r"Options that are valid with --zero-metadata are:",
    r"-d  --device \<DEVICE\>               Path to device on which metadata would be cleared"
    r"-f  --force                         Ignore potential dirty data on cache device"
]

unrecognized_stderr = [
    r"Unrecognized command -\S+",
]

unrecognized_stdout = [
    r"Try \`casadm --help | -H\' for more information\."
]
