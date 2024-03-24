/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
 */

package api

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/Jeffail/gabs"
	"github.com/Open-CAS/open-cas-linux/json/ioctl"
)

func Json_api() {

	var buffer interface{}
	decode_header_err := json.NewDecoder(os.Stdin).Decode(&buffer)
	if check_err(decode_header_err, "Invalid input parameter", log_console) {
		err_sys.write_errors_to_console()
		return
	}
	strB, _ := json.Marshal(buffer)

	jsonParsed, err := gabs.ParseJSON(strB)
	if check_err(err, "Invalid input parameter", log_console) {
		err_sys.write_errors_to_console()
		return
	}

	command, ok := jsonParsed.Path("command").Data().(string)
	if !ok {
		log_console("Invalid input parameter")
		err_sys.write_errors_to_console()
		return
	}

	/** Comand interpretation section and retrieving json response */

	if command == "opencas.cache.stats.get" {
		// it appears as float64 is default format to read json in this package
		cache_id, _ := jsonParsed.Search("params", "cache id").Data().(float64)
		params := CreateParamsStatsCache(uint16(cache_id))
		json_get_stats_cache(*params)
	}

	if command == "opencas.cache.core.stats.get" {
		cache_id, _ := jsonParsed.Search("params", "cache id").Data().(float64)
		core_id, _ := jsonParsed.Search("params", "core id").Data().(float64)
		params := CreateParamsStatsCore(uint16(cache_id), uint16(core_id))
		json_get_stats_core(*params)
	}

	if command == "opencas.cache.ioclass.stats.get" {
		cache_id, _ := jsonParsed.Search("params", "cache id").Data().(float64)
		io_class, _ := jsonParsed.Search("params", "io class").Data().(float64)
		params := CreateParamsStatsIoClass(uint16(cache_id), uint16(io_class))
		json_get_stats_io_class(*params)
	}

	if command == "opencas.cache.core.ioclass.stats.get" {
		cache_id, _ := jsonParsed.Search("params", "cache id").Data().(float64)
		core_id, _ := jsonParsed.Search("params", "core id").Data().(float64)
		io_class, _ := jsonParsed.Search("params", "io class").Data().(float64)
		params := CreateParamsStats(uint16(cache_id), uint16(core_id), uint16(io_class))
		json_get_stats(*params)
	}

	if command == "opencas.cache_list.get" {
		json_list_caches()
	}

	if command == "opencas.cache.info.get" {
		cache_id, _ := jsonParsed.Search("params", "cache id").Data().(float64)
		params := CreateParamsCacheInfo(uint16(cache_id))
		json_get_cache_info(*params)
	}

	if command == "opencas.cache.core.info.get" {
		cache_id, _ := jsonParsed.Search("params", "cache id").Data().(float64)
		core_id, _ := jsonParsed.Search("params", "core id").Data().(float64)
		params := CreateParamsCoreInfo(uint16(cache_id), uint16(core_id))
		json_get_core_info(*params)
	}

	if command == "opencas.cache.ioclass.info.get" {
		cache_id, _ := jsonParsed.Search("params", "cache id").Data().(float64)
		io_class, _ := jsonParsed.Search("params", "io class").Data().(float64)
		params := CreateParamsIoclassInfo(uint16(cache_id), uint16(io_class))
		json_get_io_class_info(*params)
	}

	/** if some errors occured - error log is not empty write errors list */
	if len(err_sys.Log_error_list) != 0 {
		err_sys.write_errors_to_console()
	}

}

/** json get stats with different levels */

func json_get_stats(request Params_stats) {
	stats_pkg, get_stats_err := get_stats(request.Cache_id, request.Core_id, request.Io_class)
	if check_err(get_stats_err, get_stats_err.Error(), log_console) {
		return
	}

	stats_pkg_b, marshall_err := json.MarshalIndent(stats_pkg, "", "  ")
	if check_err(marshall_err, "failed marshaling JSON response", log_console) {
		return
	}
	fmt.Println(string(stats_pkg_b))
}

func json_get_stats_cache(request Params_stats_cache) {
	stats_pkg, get_stats_err := get_stats(request.Cache_id, ioctl.Invalid_core_id, ioctl.Invalid_io_class)
	if check_err(get_stats_err, get_stats_err.Error(), log_console) {
		return
	}

	stats_pkg_b, marshall_err := json.MarshalIndent(stats_pkg, "", "  ")
	if check_err(marshall_err, "failed marshaling JSON response", log_console) {
		return
	}
	fmt.Println(string(stats_pkg_b))
}

func json_get_stats_core(request Params_stats_core) {
	stats_pkg, get_stats_err := get_stats(request.Cache_id, request.Core_id, ioctl.Invalid_io_class)
	if check_err(get_stats_err, get_stats_err.Error(), log_console) {
		return
	}

	stats_pkg_b, marshall_err := json.MarshalIndent(stats_pkg, "", "  ")
	if check_err(marshall_err, "failed marshaling JSON response", log_console) {
		return
	}
	fmt.Println(string(stats_pkg_b))
}

func json_get_stats_io_class(request Params_stats_io_class) {
	stats_pkg, get_stats_err := get_stats(request.Cache_id, ioctl.Invalid_core_id, request.Io_class)
	if check_err(get_stats_err, get_stats_err.Error(), log_console) {
		return
	}

	stats_pkg_b, marshall_err := json.MarshalIndent(stats_pkg, "", "  ")
	if check_err(marshall_err, "failed marshaling JSON response", log_console) {
		return
	}
	fmt.Println(string(stats_pkg_b))
}

/** json get cache_list */

func json_list_caches() {
	cache_list_pkg, list_caches_err := List_caches()
	if check_err(list_caches_err, list_caches_err.Error(), log_console) {
		return
	}

	cache_list_pkg_b, marshall_err := json.MarshalIndent(cache_list_pkg, "", "  ")
	if check_err(marshall_err, "failed marshaling JSON response", log_console) {
		return
	}
	fmt.Println(string(cache_list_pkg_b))
}

/** json get CAS with different levels */

func json_get_cache_info(request Params_cache_info) {
	cache_info, cache_info_err := get_cache_info(request.Cache_id)
	if check_err(cache_info_err, cache_info_err.Error(), log_console) {
		return
	}

	cache_info_b, marshall_err := json.MarshalIndent(cache_info, "", "  ")
	if check_err(marshall_err, "failed marshaling JSON response", log_console) {
		return
	}
	fmt.Println(string(cache_info_b))
}

func json_get_core_info(request Params_core_info) {
	core_info, core_info_err := get_core_info(request.Cache_id, request.Core_id)
	if check_err(core_info_err, core_info_err.Error(), log_console) {
		return
	}

	core_info_b, marshall_err := json.MarshalIndent(core_info, "", "  ")
	if check_err(marshall_err, "failed marshaling JSON response", log_console) {
		return
	}
	fmt.Println(string(core_info_b))
}

func json_get_io_class_info(request Params_io_class_info) {
	io_class_info, io_class_info_err := get_io_class(request.Cache_id, request.Io_class)
	if check_err(io_class_info_err, io_class_info_err.Error(), log_console) {
		return
	}

	io_class_info_b, marshall_err := json.MarshalIndent(io_class_info, "", "  ")
	if check_err(marshall_err, "failed marshaling JSON response", log_console) {
		return
	}
	fmt.Println(string(io_class_info_b))
}
