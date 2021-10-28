#
# Copyright(c) 2020-2021 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

from enum import Enum
from types import MethodType
from datetime import datetime

from schema import Schema, Use, And, SchemaError, Or


class ValidatableParameter(Enum):
    """
    Parameter enumeration together with schema for validating this parameter
    If given parameter is always valid put False as its value, otherwise use proper Schema object
    """

    def __new__(cls, schema: Schema):
        if not (isinstance(schema, Schema) or not schema):
            raise Exception(
                f"Invalid {cls.__name__} value. Expected: Schema instance or False, got: {schema}"
            )

        # Trick for changing value which is supplied by enum
        # This way we can access Schema from enumeration member instance and still have Enum
        # properties maintained
        obj = object.__new__(cls)
        obj._value_ = obj
        obj.schema = schema
        obj.validate = MethodType(cls.validate, obj)

        return obj

    def validate(self, param):
        if self.schema:
            param = self.schema.validate(param)

        return param

    def __repr__(self):
        return f"<{type(self).__name__}.{self.name}>"

    def __str__(self):
        return str(self.name)


class PercentileMetric:
    def __init__(self, value):
        value = float(value)

        if not 0 < value < 100:
            raise SchemaError("Invalid percentile value")

        self.value = value

    def __str__(self):
        return f"p{self.value:g}".replace(".", "_")


class IOMetric(ValidatableParameter):
    read_IOPS = Schema(Use(int))
    write_IOPS = Schema(Use(int))
    read_BW = Schema(Use(int))
    write_BW = Schema(Use(int))
    read_CLAT_AVG = Schema(Use(int))
    write_CLAT_AVG = Schema(Use(int))
    read_CLAT_PERCENTILES = Schema({Use(PercentileMetric): Use(int)})
    write_CLAT_PERCENTILES = Schema({Use(PercentileMetric): Use(int)})

BuildTypes = ["master", "pr", "other"]

class ConfigParameter(ValidatableParameter):
    CAS_VERSION = Schema(Use(str))
    DUT = Schema(Use(str))
    TEST_NAME = Schema(str)
    BUILD_TYPE = Schema(Or(*BuildTypes))
    CACHE_CONFIG = Schema(
        {"cache_mode": Use(str), "cache_line_size": Use(str), "cleaning_policy": Use(str)}
    )
    CACHE_TYPE = Schema(Use(str))
    CORE_TYPE = Schema(Use(str))
    TIMESTAMP = Schema(And(datetime, Use(str)))


class WorkloadParameter(ValidatableParameter):
    NUM_JOBS = Schema(Use(int))
    QUEUE_DEPTH = Schema(Use(int))


class MetricContainer:
    def __init__(self, metric_type):
        self.metrics = {}
        self.metric_type = metric_type

    def insert_metric(self, metric, kind):
        if not isinstance(kind, self.metric_type):
            raise Exception(f"Invalid metric type. Expected: {self.metric_type}, got: {type(kind)}")

        if kind.value:
            metric = kind.value.validate(metric)

        self.metrics[kind] = metric

    @property
    def is_empty(self):
        return len(self.metrics) == 0

    def to_serializable_dict(self):
        # No easy way for json.dump to deal with custom classes (especially custom Enums)
        def stringify_dict(d):
            new_dict = {}
            for k, v in d.items():
                k = str(k)

                if isinstance(v, dict):
                    v = stringify_dict(v)
                elif isinstance(v, int):
                    pass
                elif isinstance(v, float):
                    pass
                else:
                    v = str(v)

                new_dict[k] = v

            return new_dict

        return stringify_dict(self.metrics)


class PerfContainer:
    def __init__(self):
        self.conf_params = MetricContainer(ConfigParameter)

        self.workload_params = MetricContainer(WorkloadParameter)

        self.cache_metrics = MetricContainer(IOMetric)
        self.core_metrics = MetricContainer(IOMetric)
        self.exp_obj_metrics = MetricContainer(IOMetric)

    def insert_config_param(self, param, kind: ConfigParameter):
        self.conf_params.insert_metric(param, kind)

    def insert_config_from_cache(self, cache):
        cache_config = {
            "cache_mode": cache.get_cache_mode(),
            "cache_line_size": cache.get_cache_line_size(),
            "cleaning_policy": cache.get_cleaning_policy(),
        }

        self.conf_params.insert_metric(cache_config, ConfigParameter.CACHE_CONFIG)

    def insert_workload_param(self, param, kind: WorkloadParameter):
        self.workload_params.insert_metric(param, kind)

    @staticmethod
    def _insert_metrics_from_fio(container, result):
        result = result.job

        container.insert_metric(result.read.iops, IOMetric.read_IOPS)
        container.insert_metric(result.write.iops, IOMetric.write_IOPS)
        container.insert_metric(result.read.bw, IOMetric.read_BW)
        container.insert_metric(result.write.bw, IOMetric.write_BW)
        container.insert_metric(result.read.clat_ns.mean, IOMetric.read_CLAT_AVG)
        container.insert_metric(result.write.clat_ns.mean, IOMetric.write_CLAT_AVG)
        if hasattr(result.read.clat_ns, "percentile"):
            container.insert_metric(
                vars(result.read.clat_ns.percentile), IOMetric.read_CLAT_PERCENTILES
            )
        if hasattr(result.write.clat_ns, "percentile"):
            container.insert_metric(
                vars(result.write.clat_ns.percentile), IOMetric.write_CLAT_PERCENTILES
            )

    def insert_cache_metric(self, metric, kind: IOMetric):
        self.cache_metrics.insert_metric(metric, kind)

    def insert_cache_metrics_from_fio_job(self, fio_results):
        self._insert_metrics_from_fio(self.cache_metrics, fio_results)

    def insert_core_metric(self, metric, kind: IOMetric):
        self.core_metrics.insert_metric(metric, kind)

    def insert_core_metrics_from_fio_job(self, fio_results):
        self._insert_metrics_from_fio(self.core_metrics, fio_results)

    def insert_exp_obj_metric(self, metric, kind: IOMetric):
        self.exp_obj_metrics.insert_metric(metric, kind)

    def insert_exp_obj_metrics_from_fio_job(self, fio_results):
        self._insert_metrics_from_fio(self.exp_obj_metrics, fio_results)

    @property
    def is_empty(self):
        return (
            self.conf_params.is_empty
            and self.workload_params.is_empty
            and self.cache_metrics.is_empty
            and self.core_metrics.is_empty
            and self.exp_obj_metrics.is_empty
        )

    def to_serializable_dict(self):
        ret = {**self.conf_params.to_serializable_dict()}

        if not self.workload_params.is_empty:
            ret["workload_params"] = self.workload_params.to_serializable_dict()
        if not self.cache_metrics.is_empty:
            ret["cache_io"] = self.cache_metrics.to_serializable_dict()
        if not self.core_metrics.is_empty:
            ret["core_io"] = self.core_metrics.to_serializable_dict()
        if not self.exp_obj_metrics.is_empty:
            ret["exp_obj_io"] = self.exp_obj_metrics.to_serializable_dict()

        return ret
