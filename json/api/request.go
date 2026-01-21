/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause
 */

package api

import (
	"encoding/json"
	"errors"
	"os"
)

/** Request structures */

type Request struct {
	Command string `json:"command"`
	Rparams Params `json:"params"`
}

/** parameters to varius request types*/

type Params interface {
	Read()
}

/** most specyfic stats for concrete core with specyfied io class*/
type Params_stats struct {
	Cache_id uint16 `json:"cache id"` // obligatory
	Core_id  uint16 `json:"core id"`  // obligatory
	Io_class uint16 `json:"io class"` // obligatory
}

/** cache level stats */
type Params_stats_cache struct {
	Cache_id uint16 `json:"cache id"` // obligatory
}

/** core level stats */
type Params_stats_core struct {
	Cache_id uint16 `json:"cache id"` // obligatory
	Core_id  uint16 `json:"core id"`  // obligatory

}

/** io class level stats */
type Params_stats_io_class struct {
	Cache_id uint16 `json:"cache id"` // obligatory
	Io_class uint16 `json:"io class"` // obligatory
}

type Params_list_caches struct {
}

type Params_cache_info struct {
	Cache_id uint16 `json:"cache id"` // obligatory
}

type Params_core_info struct {
	Cache_id uint16 `json:"cache id"` // obligatory
	Core_id  uint16 `json:"core id"`  // obligatory
}

type Params_io_class_info struct {
	Cache_id uint16 `json:"cache id"` // obligatory
	Io_class uint16 `json:"io class"` // obligatory
}

/** Request parameters constructors */

func CreateParamsStats(cache_id, core_id, io_class_id uint16) *Params_stats {
	return &Params_stats{
		Cache_id: cache_id,
		Core_id:  core_id,
		Io_class: io_class_id,
	}
}

func CreateParamsStatsCache(cache_id uint16) *Params_stats_cache {
	return &Params_stats_cache{
		Cache_id: cache_id,
	}
}

func CreateParamsStatsCore(cache_id, core_id uint16) *Params_stats_core {
	return &Params_stats_core{
		Cache_id: cache_id,
		Core_id:  core_id,
	}
}

func CreateParamsStatsIoClass(cache_id, io_class_id uint16) *Params_stats_io_class {
	return &Params_stats_io_class{
		Cache_id: cache_id,
		Io_class: io_class_id,
	}
}
func CreateParamsCacheList() *Params_list_caches {
	return &Params_list_caches{}
}

func CreateParamsCacheInfo(cache_id uint16) *Params_cache_info {
	return &Params_cache_info{
		Cache_id: cache_id,
	}
}

func CreateParamsCoreInfo(cache_id, core_id uint16) *Params_core_info {
	return &Params_core_info{
		Cache_id: cache_id,
		Core_id:  core_id,
	}
}
func CreateParamsIoclassInfo(cache_id, io_class_id uint16) *Params_io_class_info {
	return &Params_io_class_info{
		Cache_id: cache_id,
		Io_class: io_class_id,
	}
}

/** factory design pattern for creating customized in header command parameters */
func NewRequest(command string) (Params, error) {
	if command == "opencas.cache.stats.get" {
		return new(Params_stats_cache), nil
	}
	if command == "opencas.cache.core.stats.get" {
		return new(Params_core_info), nil
	}
	if command == "opencas.cache.ioclass.stats.get" {
		return new(Params_io_class_info), nil
	}
	if command == "opencas.cache.core.ioclass.stats.get" {
		return new(Params_stats), nil
	}
	if command == "opencas.cache_list.get" {
		return new(Params_list_caches), nil
	}
	if command == "opencas.cache.info.get" {
		return new(Params_cache_info), nil
	}
	if command == "opencas.core.info.get" {
		return new(Params_core_info), nil
	}
	if command == "opencas.ioclass.info.get" {
		return new(Params_io_class_info), nil
	}
	return nil, errors.New("Invalid input parameter")
}

/** read JSON from stdin functions */

func (request *Params_stats) Read() {
	decode_request_err := json.NewDecoder(os.Stdin).Decode(request)
	if decode_request_err != nil {
		log_console("Invalid input parameter")
	}
}

func (request *Params_stats_cache) Read() {
	decode_request_err := json.NewDecoder(os.Stdin).Decode(request)
	if decode_request_err != nil {
		log_console("Invalid input parameter")
	}
}

func (request *Params_stats_core) Read() {
	decode_request_err := json.NewDecoder(os.Stdin).Decode(request)
	if decode_request_err != nil {
		log_console("Invalid input parameter")
	}
}

func (request *Params_stats_io_class) Read() {
	decode_request_err := json.NewDecoder(os.Stdin).Decode(request)
	if decode_request_err != nil {
		log_console("Invalid input parameter")
	}
}

func (request *Params_list_caches) Read() {
	decode_request_err := json.NewDecoder(os.Stdin).Decode(request)
	if decode_request_err != nil {
		log_console("Invalid input parameter")
	}
}

func (request *Params_cache_info) Read() {
	decode_request_err := json.NewDecoder(os.Stdin).Decode(request)
	if decode_request_err != nil {
		log_console("Invalid input parameter")
	}
}

func (request *Params_core_info) Read() {
	decode_request_err := json.NewDecoder(os.Stdin).Decode(request)
	if decode_request_err != nil {
		log_console("Invalid input parameter")
	}
}

func (request *Params_io_class_info) Read() {
	decode_request_err := json.NewDecoder(os.Stdin).Decode(request)
	if decode_request_err != nil {
		log_console("Invalid input parameter")
	}
}
