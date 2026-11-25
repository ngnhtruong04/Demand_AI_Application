import json
import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median
import numpy as np
import polars as pl


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DataValidationError(ValueError):
    """Raised when data validation fails inside the pipeline."""


# ---------------------------------------------------------------------------
# DatasetSplits
# ---------------------------------------------------------------------------


@dataclass
class DatasetSplits:
    """Lightweight container for train / validation / test Polars DataFrames."""

    train: pl.DataFrame
    validation: pl.DataFrame
    test: pl.DataFrame

    def as_dict(self) -> dict[str, pl.DataFrame]:
        return {"train": self.train, "validation": self.validation, "test": self.test}

    def map(self, func: Callable[[pl.DataFrame], pl.DataFrame]) -> "DatasetSplits":
        return DatasetSplits(
            train=func(self.train),
            validation=func(self.validation),
            test=func(self.test),
        )




# ---------------------------------------------------------------------------
# FeatureEngineeringArtifacts
# ---------------------------------------------------------------------------


@dataclass
class FeatureEngineeringArtifacts:
    """Return value of run_feature_engineering."""

    splits: DatasetSplits
    feature_columns: tuple[str, ...]
    categorical_columns: tuple[str, ...]
    feature_groups: dict[str, tuple[str, ...]]
    saved_paths: Mapping[str, Path]
    metadata_path: Path | None
    warnings: tuple[str, ...]


# ---------------------------------------------------------------------------
# PipelineConfig  (verbatim from notebook — frozen dataclass)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineConfig:
    """Cấu hình dùng chung nhưng không ràng buộc hai pipeline với nhau.

    Attributes:
        input_root: Thư mục gốc chứa output của LoadMergeSplit.
        output_dir: Thư mục nhận feature-engineered Parquet và metadata.
        eda_output_dir: Thư mục lưu EDA; ``None`` dùng ``output_dir/eda_reports``.
        date_column: Tên cột thời gian.
        target_column: Tên biến mục tiêu.
        series_keys: Các cột cùng định danh một chuỗi thời gian.
        forecast_horizon: Forecast horizon được ghi vào metadata.
        sales_lags: Calendar-day lags được giữ làm model feature.
        interaction_lags: Lags cần tính cho interaction; 8–13 chỉ là trung gian.
        direct_interaction_lags: Interaction lags được giữ trong output.
        summary_lags: Lags dùng để tính mean/min/max.
        discount_lags: Calendar-day lags của bảy discount columns.
        lag_metric_sample_size: Số dòng train tối đa dùng trong EDA lag metrics.
        random_seed: Seed cho sampling và Mutual Information.
        apply_reference_transform: Bật sqrt + centering của notebook tham khảo.
        expected_feature_count: Mốc kiểm tra mềm, không làm pipeline thất bại.
    """

    input_root: Path = Path("/kaggle/input")
    output_dir: Path = Path("/kaggle/working/rohlik_feature_engineered")
    eda_output_dir: Path | None = None
    date_column: str = "date"
    target_column: str = "sales"
    series_keys: tuple[str, ...] = ("unique_id", "warehouse")
    forecast_horizon: int = 14
    sales_lags: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 14, 21, 28)
    interaction_lags: tuple[int, ...] = (*range(1, 15), 21, 28)
    direct_interaction_lags: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 14, 21, 28)
    summary_lags: tuple[int, ...] = tuple(range(1, 15))
    discount_lags: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 14, 21, 28)
    lag_metric_sample_size: int = 250_000
    feature_evaluation_sample_size: int = 100_000
    drift_bins: int = 10
    redundancy_threshold: float = 0.95
    ablation_folds: int = 3
    ablation_horizon: int = 14
    random_seed: int = 42
    apply_reference_transform: bool = False
    expected_feature_count: int | None = 139
    weight_column: str | None = None
    show_progress: bool = False  # disabled in SSE mode to avoid tqdm overhead
    fixed_lightgbm_params: Mapping[str, object] = field(
        default_factory=lambda: {
            "n_estimators": 500,
            "learning_rate": 0.05,
            "num_leaves": 31,
            "max_depth": -1,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "reg_alpha": 0.0,
            "reg_lambda": 0.0,
            "verbosity": -1,
            "n_jobs": -1,
        }
    )

    name_column: str = "name"
    name_feature: str = "name_0"
    missing_token: str = "__missing__"
    order_column: str = "total_orders"
    price_column: str = "sell_price_main"
    max_discount_feature: str = "max_discount"
    discounted_price_feature: str = "discounted_price"
    required_split_files: tuple[str, ...] = (
        "train.parquet",
        "validation.parquet",
        "test.parquet",
    )
    non_feature_columns: frozenset[str] = frozenset(
        {"id", "unique_id", "date", "sales", "split", "availability"}
    )
    categorical_candidates: tuple[str, ...] = (
        "warehouse",
        "name",
        "L1_category_name_en",
        "L2_category_name_en",
        "L3_category_name_en",
        "L4_category_name_en",
        "holiday_name",
        "name_0",
    )
    discrete_feature_candidates: tuple[str, ...] = (
        "year",
        "month",
        "weekday",
        "day",
    )

    def __post_init__(self) -> None:
        """Kiểm tra các giá trị cấu hình có thể làm sai temporal features."""
        if self.forecast_horizon < 1:
            raise ValueError("forecast_horizon phải >= 1.")
        if self.lag_metric_sample_size < 1:
            raise ValueError("lag_metric_sample_size phải >= 1.")
        if self.feature_evaluation_sample_size < 1:
            raise ValueError("feature_evaluation_sample_size phải >= 1.")
        if self.drift_bins < 2:
            raise ValueError("drift_bins phải >= 2.")
        if not 0 < self.redundancy_threshold <= 1:
            raise ValueError("redundancy_threshold phải nằm trong (0, 1].")
        if self.ablation_folds < 1 or self.ablation_horizon < 1:
            raise ValueError("ablation_folds và ablation_horizon phải >= 1.")
        for field_name in ("sales_lags", "interaction_lags", "discount_lags"):
            values = getattr(self, field_name)
            if not values or any(value < 1 for value in values):
                raise ValueError(f"{field_name} phải chứa các số nguyên dương.")

    # ── Properties (verbatim) ─────────────────────────────────────────────

    @property
    def discount_columns(self) -> tuple[str, ...]:
        """Tên bảy discount columns gốc."""
        return tuple(f"type_{index}_discount" for index in range(7))

    @property
    def sales_lag_columns(self) -> tuple[str, ...]:
        """Tên các sales lag model features."""
        return tuple(f"sales_{lag}" for lag in self.sales_lags)

    @property
    def discount_lag_columns(self) -> tuple[str, ...]:
        """Tên toàn bộ discount lag model features."""
        return tuple(
            f"{column}_{lag}"
            for column in self.discount_columns
            for lag in self.discount_lags
        )

    @property
    def direct_sales_order_columns(self) -> tuple[str, ...]:
        """Tên sales-order interaction features được giữ trong output."""
        return tuple(f"sales_order_{lag}" for lag in self.direct_interaction_lags)

    @property
    def direct_sales_price_columns(self) -> tuple[str, ...]:
        """Tên sales-price interaction features được giữ trong output."""
        return tuple(f"sales_price_{lag}" for lag in self.direct_interaction_lags)

    @property
    def summary_feature_columns(self) -> tuple[str, ...]:
        """Tên chín summary features của sales, sales-order và sales-price."""
        return (
            "sales_mean",
            "sales_order_mean",
            "sales_price_mean",
            "sales_min",
            "sales_order_min",
            "sales_price_min",
            "sales_max",
            "sales_order_max",
            "sales_price_max",
        )

    @property
    def engineered_feature_columns(self) -> tuple[str, ...]:
        """Danh sách feature chắc chắn phải được pipeline tạo mới."""
        return (
            "year",
            "month",
            "weekday",
            "day",
            "sin_dayofyear",
            "cos_dayofyear",
            self.name_feature,
            self.max_discount_feature,
            self.discounted_price_feature,
            *self.sales_lag_columns,
            *self.direct_sales_order_columns,
            *self.direct_sales_price_columns,
            *self.summary_feature_columns,
            *self.discount_lag_columns,
        )

    def feature_groups(
        self,
        available_features: Sequence[str],
    ) -> dict[str, tuple[str, ...]]:
        """Phân loại model features thành các nhóm phục vụ ablation."""
        available = tuple(dict.fromkeys(available_features))
        groups = {
            "time": ("year", "month", "weekday", "day", "sin_dayofyear", "cos_dayofyear"),
            "name": (self.name_feature,),
            "discount_price": (self.max_discount_feature, self.discounted_price_feature),
            "sales_lag": self.sales_lag_columns,
            "sales_order": self.direct_sales_order_columns,
            "sales_price": self.direct_sales_price_columns,
            "summary": self.summary_feature_columns,
            "discount_lag": self.discount_lag_columns,
        }
        engineered = {column for values in groups.values() for column in values}
        result: dict[str, tuple[str, ...]] = {
            "base": tuple(column for column in available if column not in engineered)
        }
        result.update(
            {
                name: tuple(column for column in values if column in available)
                for name, values in groups.items()
            }
        )
        return result


# ---------------------------------------------------------------------------
# Singleton default config (avoids re-constructing on every request)
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = PipelineConfig()


# ---------------------------------------------------------------------------
#  Pipeline
# ---------------------------------------------------------------------------

def validate_base_splits(splits: DatasetSplits, config: PipelineConfig) -> None:
    '''Kiểm tra schema, cột bắt buộc, availability, khóa và thứ tự thời gian.

    Hàm độc lập này được cả hai class gọi riêng, nên một class không cần
    phụ thuộc kết quả chạy của class còn lại.
    '''
    required = (*config.series_keys, config.date_column, config.target_column)
    reference_columns = splits.train.columns
    reference_schema = splits.train.schema

    for name, frame in splits.as_dict().items():
        require_columns(frame, required, table_name=name)
        if "availability" in frame.columns:
            raise DataValidationError(f"{name} vẫn còn cột availability.")
        if frame.columns != reference_columns or frame.schema != reference_schema:
            raise DataValidationError(f"Schema hoặc thứ tự cột của {name} không giống train.")
        if frame.schema[config.date_column] != pl.Date:
            raise DataValidationError(f"{name}.{config.date_column} phải có dtype pl.Date.")

        nulls = frame.select(
            [pl.col(column).null_count().alias(column) for column in (*config.series_keys, config.date_column)]
        )
        if sum(nulls.row(0)):
            raise DataValidationError(f"{name} có null trong series keys hoặc date.")

        duplicate_count = (
            frame.group_by([*config.series_keys, config.date_column])
            .len()
            .filter(pl.col("len") > 1)
            .height
        )
        if duplicate_count:
            raise DataValidationError(f"{name} có {duplicate_count} nhóm observation key trùng.")

    date = config.date_column
    if splits.train[date].min() != splits.validation[date].min():
        if not splits.train[date].max() < splits.validation[date].min():
            raise DataValidationError("Train và validation bị chồng lấn thời gian.")
        if not splits.validation[date].max() < splits.test[date].min():
            raise DataValidationError("Validation và test bị chồng lấn thời gian.")




def validate_base_test(frame: pl.DataFrame, config: PipelineConfig) -> None:
    '''Kiểm tra schema, cột bắt buộc, availability, khóa của tập test.'''
    required = (*config.series_keys, config.date_column, config.target_column)
    require_columns(frame, required, table_name="test")
    if "availability" in frame.columns:
        raise DataValidationError("test vẫn còn cột availability.")
    if frame.schema[config.date_column] != pl.Date:
        raise DataValidationError(f"test.{config.date_column} phải có dtype pl.Date.")

    nulls = frame.select(
        [pl.col(column).null_count().alias(column) for column in (*config.series_keys, config.date_column)]
    )
    if sum(nulls.row(0)):
        raise DataValidationError("test có null trong series keys hoặc date.")

    duplicate_count = (
        frame.group_by([*config.series_keys, config.date_column])
        .len()
        .filter(pl.col("len") > 1)
        .height
    )
    if duplicate_count:
        raise DataValidationError(f"test có {duplicate_count} nhóm observation key trùng.")


def require_columns(
    frame: pl.DataFrame,
    columns: Sequence[str],
    table_name: str = "frame",
) -> None:
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise DataValidationError(f"[{table_name}] Missing columns: {missing}")


class RohlikFeatureEngineeringPipeline:
    '''Tạo feature cho ba split với history policy chống target leakage.

    History policy:
        - Train row chỉ tra sales tại ngày quá khứ trong train.
        - Validation không sử dụng target bên trong validation horizon.
        - Test sử dụng train + validation vì cả hai nằm trước test origin,
          nhưng không sử dụng target bên trong test horizon.
        - Discount lags dùng full exogenous timeline và không đọc sales.
    '''

    def __init__(self, config: PipelineConfig) -> None:
        '''Khởi tạo feature engineering pipeline.'''
        self.config = config

    def _add_time_features(self, frame: pl.DataFrame) -> pl.DataFrame:
        '''Tạo calendar và cyclical day-of-year features.'''
        date = self.config.date_column
        require_columns(frame, [date], table_name="feature input")
        dtype = frame.schema[date]
        if dtype == pl.String:
            frame = frame.with_columns(pl.col(date).str.to_date(strict=True).alias(date))
        elif dtype != pl.Date:
            frame = frame.with_columns(pl.col(date).cast(pl.Date).alias(date))

        return (
            frame.with_columns(
                pl.col(date).dt.year().cast(pl.Int16).alias("year"),
                pl.col(date).dt.month().cast(pl.UInt8).alias("month"),
                pl.col(date).dt.weekday().cast(pl.UInt8).alias("weekday"),
                pl.col(date).dt.day().cast(pl.UInt8).alias("day"),
                pl.col(date).dt.ordinal_day().cast(pl.UInt16).alias("__dayofyear"),
            )
            .with_columns(
                (2 * math.pi * pl.col("__dayofyear") / 365.0)
                .sin().cast(pl.Float32).alias("sin_dayofyear"),
                (2 * math.pi * pl.col("__dayofyear") / 365.0)
                .cos().cast(pl.Float32).alias("cos_dayofyear"),
            )
            .drop("__dayofyear")
        )

    def _add_name_feature(self, frame: pl.DataFrame) -> pl.DataFrame:
        '''Trích prefix trước dấu gạch dưới của tên sản phẩm ẩn danh.

        Ví dụ `Apple_12` trở thành `Apple`. Null, chuỗi rỗng hoặc tên
        không có token hợp lệ được thay bằng `missing_token`.
        '''
        source = self.config.name_column
        feature = self.config.name_feature
        require_columns(frame, [source], table_name="feature input")
        cleaned = pl.col(source).cast(pl.String).fill_null("").str.strip_chars()
        return frame.with_columns(
            pl.when(cleaned == "")
            .then(pl.lit(self.config.missing_token))
            .otherwise(cleaned.str.extract(r"^([^_\s]+)", group_index=1))
            .fill_null(self.config.missing_token)
            .alias(feature)
        )

    def _normalize_discounts(self, frame: pl.DataFrame) -> pl.DataFrame:
        '''Đổi discount âm/null thành 0 và xác nhận discount không vượt 1.'''
        columns = self.config.discount_columns
        require_columns(frame, columns, table_name="feature input")
        expressions = []
        for column in columns:
            value = pl.col(column).cast(pl.Float32)
            expressions.append(
                pl.when(value.is_null() | (value < 0))
                .then(pl.lit(0.0, dtype=pl.Float32))
                .otherwise(value)
                .cast(pl.Float32)
                .alias(column)
            )
        normalized = frame.with_columns(expressions)
        bounds = normalized.select(
            pl.min_horizontal(columns).min().alias("minimum"),
            pl.max_horizontal(columns).max().alias("maximum"),
        ).row(0, named=True)
        if bounds["minimum"] < 0 or bounds["maximum"] > 1:
            raise DataValidationError(f"Discount ngoài [0, 1]: {bounds}")
        return normalized

    def _add_discount_price_features(self, frame: pl.DataFrame) -> pl.DataFrame:
        '''Tạo max_discount và giá sau mức discount lớn nhất.'''
        require_columns(
            frame,
            [self.config.price_column, *self.config.discount_columns],
            table_name="feature input",
        )
        result = frame.with_columns(
            pl.max_horizontal(self.config.discount_columns)
            .cast(pl.Float32)
            .alias(self.config.max_discount_feature)
        )
        return result.with_columns(
            (
                pl.col(self.config.price_column).cast(pl.Float32)
                * (1.0 - pl.col(self.config.max_discount_feature))
            )
            .cast(pl.Float32)
            .alias(self.config.discounted_price_feature)
        )

    def _prepare_sales_history(self, frame: pl.DataFrame) -> pl.DataFrame:
        '''Giữ observation key và target cần cho calendar sales lookup.'''
        return frame.select(
            *[
                pl.col(key).cast(pl.String).alias(key)
                for key in self.config.series_keys
            ],
            pl.col(self.config.date_column),
            pl.col(self.config.target_column).cast(pl.Float32).alias(self.config.target_column),
        )

    def _add_sales_lags(
        self,
        frame: pl.DataFrame,
        observed_history: pl.DataFrame,
        split_name: str,
    ) -> pl.DataFrame:
        '''Tạo sales lag bằng calendar-date join với history được phép dùng.'''
        lag_columns = self.config.sales_lag_columns
        existing = [column for column in lag_columns if column in frame.columns]
        result = frame.drop(existing) if existing else frame
        temp_keys = [f"__sales_lag_key_{key}" for key in self.config.series_keys]
        result = result.with_columns(
            [
                pl.col(key).cast(pl.String).alias(temp)
                for key, temp in zip(self.config.series_keys, temp_keys)
            ]
        )
        history = observed_history.select(
            *[
                pl.col(key).cast(pl.String).alias(temp)
                for key, temp in zip(self.config.series_keys, temp_keys)
            ],
            pl.col(self.config.date_column),
            pl.col(self.config.target_column).cast(pl.Float32).alias("__historical_sales"),
        )
        for lag, column in zip(self.config.sales_lags, lag_columns):
           
            lookup = history.select(
                *temp_keys,
                (pl.col(self.config.date_column) + pl.duration(days=lag))
                .cast(pl.Date).alias(self.config.date_column),
                pl.col("__historical_sales").alias(column),
            )
            result = result.join(
                lookup,
                on=[*temp_keys, self.config.date_column],
                how="left",
                validate="m:1",
            )
        return result.drop(temp_keys)

    def _prepare_interaction_history(self, frame: pl.DataFrame) -> pl.DataFrame:
        '''Giữ target, total orders và discounted price của history được phép dùng.'''
        return frame.select(
            *[
                pl.col(key).cast(pl.String).alias(key)
                for key in self.config.series_keys
            ],
            pl.col(self.config.date_column),
            pl.col(self.config.target_column).cast(pl.Float32).alias(self.config.target_column),
            pl.col(self.config.order_column).cast(pl.Float32).alias(self.config.order_column),
            pl.col(self.config.discounted_price_feature)
            .cast(pl.Float32).alias(self.config.discounted_price_feature),
        )

    @staticmethod
    def _safe_sqrt(column: str) -> pl.Expr:
        '''Tính sqrt cho giá trị hữu hạn không âm; trường hợp khác trả 0.'''
        value = pl.col(column)
        return (
            pl.when(value.is_not_null() & value.is_finite() & (value >= 0))
            .then(value.sqrt())
            .otherwise(pl.lit(0.0, dtype=pl.Float32))
            .cast(pl.Float32)
        )

    def _add_interaction_summary_features(
        self,
        frame: pl.DataFrame,
        observed_history: pl.DataFrame,
        split_name: str,
    ) -> pl.DataFrame:
        '''Tạo sales-order, sales-price và chín summary features.'''
        all_order = [f"sales_order_{lag}" for lag in self.config.interaction_lags]
        all_price = [f"sales_price_{lag}" for lag in self.config.interaction_lags]
        replaceable = [*all_order, *all_price, *self.config.summary_feature_columns]
        existing = [column for column in replaceable if column in frame.columns]
        result = frame.drop(existing) if existing else frame
        temp_keys = [f"__interaction_key_{key}" for key in self.config.series_keys]
        result = result.with_columns(
            [
                pl.col(key).cast(pl.String).alias(temp)
                for key, temp in zip(self.config.series_keys, temp_keys)
            ]
        )
        history = observed_history.select(
            *[
                pl.col(key).cast(pl.String).alias(temp)
                for key, temp in zip(self.config.series_keys, temp_keys)
            ],
            pl.col(self.config.date_column),
            pl.col(self.config.target_column).alias("__source_sales"),
            pl.col(self.config.order_column).alias("__source_orders"),
            pl.col(self.config.discounted_price_feature).alias("__source_price"),
        )
        summary_sales = []
        for lag in (self.config.interaction_lags):
            lagged_sales = f"__lagged_sales_{lag}"
            lagged_orders = f"__lagged_orders_{lag}"
            lagged_price = f"__lagged_price_{lag}"
            order_feature = f"sales_order_{lag}"
            price_feature = f"sales_price_{lag}"
            lookup = history.select(
                *temp_keys,
                (pl.col(self.config.date_column) + pl.duration(days=lag))
                .cast(pl.Date).alias(self.config.date_column),
                pl.col("__source_sales").alias(lagged_sales),
                pl.col("__source_orders").alias(lagged_orders),
                pl.col("__source_price").alias(lagged_price),
            )
            result = result.join(
                lookup,
                on=[*temp_keys, self.config.date_column],
                how="left",
                validate="m:1",
            )
            sales_value = pl.col(lagged_sales)
            order_value = pl.col(lagged_orders)
            price_value = pl.col(lagged_price)
            current_orders = pl.col(self.config.order_column).cast(pl.Float32)
            current_price = pl.col(self.config.discounted_price_feature).cast(pl.Float32)
            expressions = [
                pl.when(
                    sales_value.is_not_null()
                    & order_value.is_not_null()
                    & (order_value != 0)
                )
                .then(sales_value * current_orders / order_value)
                .otherwise(None)
                .cast(pl.Float32)
                .alias(order_feature),
                pl.when(
                    sales_value.is_not_null()
                    & price_value.is_not_null()
                    & (price_value != 0)
                )
                .then(sales_value * (1.0 - (current_price - price_value) / price_value))
                .otherwise(None)
                .cast(pl.Float32)
                .alias(price_feature),
            ]
            if lag in self.config.summary_lags:
                summary_column = f"__summary_sales_{lag}"
                expressions.append(sales_value.cast(pl.Float32).alias(summary_column))
                summary_sales.append(summary_column)
            result = result.with_columns(expressions).drop(
                lagged_sales, lagged_orders, lagged_price
            )

        summary_order = [f"sales_order_{lag}" for lag in self.config.summary_lags]
        summary_price = [f"sales_price_{lag}" for lag in self.config.summary_lags]
        raw_columns = (
            "__raw_sales_mean", "__raw_sales_order_mean", "__raw_sales_price_mean",
            "__raw_sales_min", "__raw_sales_order_min", "__raw_sales_price_min",
            "__raw_sales_max", "__raw_sales_order_max", "__raw_sales_price_max",
        )
        result = result.with_columns(
            pl.mean_horizontal(summary_sales).cast(pl.Float32).alias(raw_columns[0]),
            pl.mean_horizontal(summary_order).cast(pl.Float32).alias(raw_columns[1]),
            pl.mean_horizontal(summary_price).cast(pl.Float32).alias(raw_columns[2]),
            pl.min_horizontal(summary_sales).cast(pl.Float32).alias(raw_columns[3]),
            pl.min_horizontal(summary_order).cast(pl.Float32).alias(raw_columns[4]),
            pl.min_horizontal(summary_price).cast(pl.Float32).alias(raw_columns[5]),
            pl.max_horizontal(summary_sales).cast(pl.Float32).alias(raw_columns[6]),
            pl.max_horizontal(summary_order).cast(pl.Float32).alias(raw_columns[7]),
            pl.max_horizontal(summary_price).cast(pl.Float32).alias(raw_columns[8]),
        )

        if self.config.apply_reference_transform:
            baseline = self._safe_sqrt(raw_columns[2])
            result = result.with_columns(
                [
                    (self._safe_sqrt(column) - baseline).alias(column)
                    for column in (
                        *self.config.direct_sales_order_columns,
                        *self.config.direct_sales_price_columns,
                    )
                ]
            ).with_columns(
                (self._safe_sqrt(raw_columns[0]) - baseline).alias("sales_mean"),
                (self._safe_sqrt(raw_columns[1]) - baseline).alias("sales_order_mean"),
                baseline.alias("sales_price_mean"),
                (self._safe_sqrt(raw_columns[3]) - baseline).alias("sales_min"),
                (self._safe_sqrt(raw_columns[4]) - baseline).alias("sales_order_min"),
                (self._safe_sqrt(raw_columns[5]) - baseline).alias("sales_price_min"),
                (self._safe_sqrt(raw_columns[6]) - baseline).alias("sales_max"),
                (self._safe_sqrt(raw_columns[7]) - baseline).alias("sales_order_max"),
                (self._safe_sqrt(raw_columns[8]) - baseline).alias("sales_price_max"),
            )
        else:
            result = result.with_columns(
                [
                    pl.col(raw).alias(output)
                    for raw, output in zip(raw_columns, self.config.summary_feature_columns)
                ]
            )

        intermediate = [
            f"{prefix}_{lag}"
            for prefix in ("sales_order", "sales_price")
            for lag in self.config.interaction_lags
            if lag not in self.config.direct_interaction_lags
        ]
        return result.drop([*temp_keys, *summary_sales, *raw_columns, *intermediate])

    def recompute_target_dependent_features(
        self,
        frame: pl.DataFrame,
        observed_history: pl.DataFrame | None = None,
    ) -> pl.DataFrame:
        """Recompute sales lags, interaction features, and summary statistics across a continuous timeline."""
        history = frame if observed_history is None else observed_history
        sales_hist = self._prepare_sales_history(history)
        with_sales = self._add_sales_lags(frame, sales_hist, "test")
        interaction_hist = self._prepare_interaction_history(history)
        return self._add_interaction_summary_features(with_sales, interaction_hist, "test")

    def _prepare_discount_source(self, splits: DatasetSplits | pl.DataFrame) -> pl.DataFrame:
        '''Ghép exogenous discount timeline mà không đưa target vào source.'''
        target_frame = splits.test if isinstance(splits, DatasetSplits) else splits
        source = (
            target_frame.select(
                *[
                    pl.col(key).cast(pl.String).alias(key)
                    for key in self.config.series_keys
                ],
                pl.col(self.config.date_column),
                *[
                    pl.col(column).cast(pl.Float32).alias(column)
                    for column in self.config.discount_columns
                ],
            )
            .unique(subset=[*self.config.series_keys, self.config.date_column], keep="first")
            .sort(*self.config.series_keys, self.config.date_column)
        )
        return source

    def _add_discount_lags(
        self,
        frame: pl.DataFrame,
        discount_source: pl.DataFrame,
        split_name: str,
    ) -> pl.DataFrame:
        '''Tạo 70 discount lag features bằng calendar-date join.'''
        existing = [
            column for column in self.config.discount_lag_columns
            if column in frame.columns
        ]
        result = frame.drop(existing) if existing else frame
        temp_keys = [f"__discount_key_{key}" for key in self.config.series_keys]
        result = result.with_columns(
            [
                pl.col(key).cast(pl.String).alias(temp)
                for key, temp in zip(self.config.series_keys, temp_keys)
            ]
        )
        source = discount_source.select(
            *[
                pl.col(key).cast(pl.String).alias(temp)
                for key, temp in zip(self.config.series_keys, temp_keys)
            ],
            pl.col(self.config.date_column),
            *self.config.discount_columns,
        )
        for lag in self.config.discount_lags:
            lookup = source.select(
                *temp_keys,
                (pl.col(self.config.date_column) + pl.duration(days=lag))
                .cast(pl.Date).alias(self.config.date_column),
                *[
                    pl.col(column).alias(f"{column}_{lag}")
                    for column in self.config.discount_columns
                ],
            )
            result = result.join(
                lookup,
                on=[*temp_keys, self.config.date_column],
                how="left",
                validate="m:1",
            )
        return result.drop(temp_keys)

    def _validate_output(self, splits: DatasetSplits | pl.DataFrame) -> None:
        '''Kiểm tra schema và toàn bộ feature bắt buộc sau transform.'''
        frame = splits.test if isinstance(splits, DatasetSplits) else splits
        required = self.config.engineered_feature_columns
        require_columns(frame, required, table_name="test")
        wrong_discount_dtype = [
            column for column in self.config.discount_lag_columns
            if frame.schema[column] != pl.Float32
        ]
        if wrong_discount_dtype:
            raise DataValidationError(
                f"test có discount lag không phải Float32: {wrong_discount_dtype}"
            )

    def _model_columns(
        self,
        splits: DatasetSplits | pl.DataFrame,
    ) -> tuple[
        tuple[str, ...],
        tuple[str, ...],
        Mapping[str, tuple[str, ...]],
    ]:
        '''Xác định model, categorical và feature-group contracts.'''
        frame = splits.test if isinstance(splits, DatasetSplits) else splits
        features = tuple(
            column for column in frame.columns
            if column not in self.config.non_feature_columns
        )
        categorical = tuple(
            column for column in self.config.categorical_candidates
            if column in features
        )
        groups = self.config.feature_groups(features)
        return features, categorical, groups

RAW_DATA_COLUMNS: tuple[str, ...] = (
    "unique_id",
    "date",
    "warehouse",
    "total_orders",
    "sales",
    "sell_price_main",
    "type_0_discount",
    "type_1_discount",
    "type_2_discount",
    "type_3_discount",
    "type_4_discount",
    "type_5_discount",
    "type_6_discount",
    "name",
    "product_unique_id",
    "L1_category_name_en",
    "L2_category_name_en",
    "L3_category_name_en",
    "L4_category_name_en",
    "holiday_name",
    "holiday",
    "shops_closed",
    "winter_school_holidays",
    "school_holidays",
)

DISCOUNT_COLUMNS: tuple[str, ...] = (
    "type_0_discount",
    "type_1_discount",
    "type_2_discount",
    "type_3_discount",
    "type_4_discount",
    "type_5_discount",
    "type_6_discount",
)

CALENDAR_COLUMNS: tuple[str, ...] = (
    "holiday_name",
    "holiday",
    "shops_closed",
    "winter_school_holidays",
    "school_holidays",
)

def _safe_median(values: Sequence[float], default: float | None = None) -> float | None:
    clean = [float(v) for v in values if v is not None and np.isfinite(float(v))]
    return float(median(clean)) if clean else default


def _order_group_expr(
    l1_col: str,
    special_l1_categories: Sequence[str],
) -> pl.Expr:
    """
    Normal items share one warehouse/day total_orders.

    Special L1 categories, e.g. Bakery, get their own correlated
    warehouse/day total_orders.
    """
    special = {str(x).strip().lower() for x in special_l1_categories}

    return (
        pl.when(pl.col(l1_col).is_null())
        .then(pl.lit("__BASE__"))
        .when(
            pl.col(l1_col)
            .cast(pl.Utf8)
            .str.strip_chars()
            .str.to_lowercase()
            .is_in(list(special))
        )
        .then(
            pl.col(l1_col)
            .cast(pl.Utf8)
            .str.strip_chars()
            .str.to_lowercase()
        )
        .otherwise(pl.lit("__BASE__"))
        .alias("__order_group")
    )


def simulate_total_order_feature(
    history: pl.DataFrame,
    forecast_items: pl.DataFrame,
    cutoff_date: date | None = None,
    horizon_days: int = 14,
    round_to_integer: bool = True,
    warehouse_defaults: Mapping | None = None,
    series_keys: Sequence[str] = ("unique_id", "warehouse"),
    date_col: str = "date",
    order_col: str = "total_orders",
    **kwargs,
) -> pl.DataFrame:
    """Simulate future total_orders as the median of the closest 4 days of the same weekday per unique_id."""
    keys = [k for k in series_keys if k in forecast_items.columns]
    if not keys:
        keys = ["unique_id"]

    if history.schema[date_col] != pl.Date:
        history = history.with_columns(pl.col(date_col).cast(pl.Date))

    if cutoff_date is None:
        cutoff_date = history.select(pl.col(date_col).max()).item()

    valid_history = (
        history
        .filter(
            (pl.col(date_col) <= cutoff_date)
            & pl.col(order_col).is_not_null()
            & pl.col(order_col).is_finite()
        )
        .with_columns(pl.col(date_col).dt.weekday().alias("__weekday"))
    )

    # Median of closest 4 days of the same weekday
    weekday_medians = (
        valid_history
        .sort([*keys, "__weekday", date_col])
        .group_by([*keys, "__weekday"], maintain_order=True)
        .tail(4)
        .group_by([*keys, "__weekday"])
        .agg(pl.col(order_col).median().alias(order_col))
    )

    # Fallback to recent item median if specific weekday is absent
    item_medians = (
        valid_history
        .sort([*keys, date_col])
        .group_by(keys, maintain_order=True)
        .tail(4)
        .group_by(keys)
        .agg(pl.col(order_col).median().alias("__item_fallback"))
    )

    target_dtype = history.schema.get(order_col, pl.Float64)
    overall_fallback = (
        valid_history.select(pl.col(order_col).median()).item()
        if valid_history.height > 0 else 0
    )

    future_dates = [cutoff_date + timedelta(days=i) for i in range(1, horizon_days + 1)]
    dates_df = pl.DataFrame({date_col: future_dates}).with_columns(
        pl.col(date_col).dt.weekday().alias("__weekday")
    )

    result = (
        forecast_items
        .select(keys)
        .unique()
        .join(dates_df, how="cross")
        .join(weekday_medians, on=[*keys, "__weekday"], how="left")
        .join(item_medians, on=keys, how="left")
        .with_columns(
            pl.coalesce([pl.col(order_col), pl.col("__item_fallback"), pl.lit(overall_fallback)])
            .alias(order_col)
        )
    )

    if round_to_integer:
        result = result.with_columns(pl.col(order_col).round(0))

    return (
        result
        .select([*keys, date_col, pl.col(order_col).cast(target_dtype)])
        .sort([*keys, date_col])
    )



def generate_future_price_feature(
    history: pl.DataFrame,
    forecast_items: pl.DataFrame,
    future_dates: Sequence[date],
    date_col: str = "date",
    item_col: str = "unique_id",
    price_col: str = "sell_price_main",
    lookback_days: int = 84,
    random_seed: int = 43,
) -> pl.DataFrame:
    """
    Generate future prices empirically from historical item prices.

    Logic:
    - item-specific
    - weekday-aware
    - samples observed historical values rather than copying the latest row
    - falls back to the item's overall historical price distribution
    """
    required = {item_col, date_col, price_col}

    missing = required - set(history.columns)
    if missing:
        raise ValueError(
            f"history is missing required price columns: {sorted(missing)}"
        )

    if history.schema[date_col] != pl.Date:
        history = history.with_columns(
            pl.col(date_col).cast(pl.Date)
        )

    end_date = max(future_dates)
    start_date = end_date - timedelta(days=lookback_days - 1)

    valid = (
        history
        .filter(
            (pl.col(date_col) >= start_date)
            & (pl.col(date_col) <= max(future_dates))
            & pl.col(price_col).is_not_null()
            & pl.col(price_col).is_finite()
            & (pl.col(price_col) > 0)
        )
        .with_columns(
            (pl.col(date_col).dt.weekday() - 1)
            .cast(pl.Int8)
            .alias("__weekday"),
            pl.col(price_col)
            .cast(pl.Float64)
            .alias("__price"),
        )
    )

    rng = np.random.default_rng(random_seed)

    history_map: dict[
        object,
        dict[int, list[float]]
    ] = defaultdict(lambda: defaultdict(list))

    for row in valid.select(
        [item_col, "__weekday", "__price"]
    ).to_dicts():
        history_map[row[item_col]][int(row["__weekday"])].append(
            float(row["__price"])
        )

    future_item_ids = sorted(
        forecast_items.select([item_col]).unique().to_series().to_list()
    )

    rows: list[dict] = []

    for item_id in future_item_ids:
        item_history = history_map.get(item_id, {})

        if not item_history:
            raise ValueError(
                f"No valid historical price found for item {item_id!r}."
            )

        all_prices = [
            p
            for values in item_history.values()
            for p in values
        ]

        for future_date in future_dates:
            weekday = future_date.weekday()

            candidates = item_history.get(
                weekday,
                all_prices,
            )

            price = float(
                rng.choice(candidates)
            )

            rows.append(
                {
                    item_col: item_id,
                    date_col: future_date,
                    price_col: round(price, 2),
                }
            )

    return pl.DataFrame(rows)


def generate_future_discount_features(
    history: pl.DataFrame,
    forecast_items: pl.DataFrame,
    future_dates: Sequence[date],
    date_col: str = "date",
    item_col: str = "unique_id",
    discount_columns: Sequence[str] = DISCOUNT_COLUMNS,
    lookback_days: int = 84,
    random_seed: int = 44,
) -> pl.DataFrame:
    """
    Generate future discounts from item-specific historical empirical
    distributions, conditioned on weekday.

    Zero discounts naturally remain common when zero dominates the
    item's historical distribution.
    """
    required = {item_col, date_col, *discount_columns}

    missing = required - set(history.columns)
    if missing:
        raise ValueError(
            f"history is missing discount columns: {sorted(missing)}"
        )

    if history.schema[date_col] != pl.Date:
        history = history.with_columns(
            pl.col(date_col).cast(pl.Date)
        )

    end_date = max(future_dates)
    start_date = end_date - timedelta(days=lookback_days - 1)

    valid = (
        history
        .filter(
            (pl.col(date_col) >= start_date)
            & (pl.col(date_col) <= max(future_dates))
        )
        .with_columns(
            (pl.col(date_col).dt.weekday() - 1)
            .cast(pl.Int8)
            .alias("__weekday")
        )
    )

    rng = np.random.default_rng(random_seed)

    distributions: dict[
        object,
        dict[str, dict[int, list[float]]]
    ] = defaultdict(
        lambda: defaultdict(
            lambda: defaultdict(list)
        )
    )

    select_cols = [item_col, "__weekday", *discount_columns]

    for row in valid.select(select_cols).to_dicts():
        item_id = row[item_col]
        weekday = int(row["__weekday"])

        for col in discount_columns:
            value = row[col]

            if value is None:
                continue

            value = float(value)

            if not np.isfinite(value):
                continue

            distributions[item_id][col][weekday].append(value)

    future_item_ids = sorted(
        forecast_items.select([item_col]).unique().to_series().to_list()
    )

    rows: list[dict] = []

    for item_id in future_item_ids:
        if item_id not in distributions:
            raise ValueError(
                f"No historical discount distribution found for item {item_id!r}."
            )

        for future_date in future_dates:
            weekday = future_date.weekday()

            row = {
                item_col: item_id,
                date_col: future_date,
            }

            for col in discount_columns:
                by_weekday = distributions[item_id][col]

                candidates = by_weekday.get(weekday)

                if not candidates:
                    candidates = [
                        value
                        for values in by_weekday.values()
                        for value in values
                    ]

                if candidates:
                    value = float(rng.choice(candidates))
                else:
                    value = 0.0

                row[col] = value

            rows.append(row)

    return pl.DataFrame(rows)


def _build_prior_year_calendar(
    calendar_history: pl.DataFrame,
    future_dates: Sequence[date],
    date_col: str,
) -> pl.DataFrame:
    """
    Fill future calendar features from the same month/day one year earlier.

    A Feb-29 future date falls back to Feb-28 of the previous year.
    """
    required = {date_col, *CALENDAR_COLUMNS}
    missing = required - set(calendar_history.columns)

    if missing:
        raise ValueError(
            "calendar_history is missing required columns: "
            f"{sorted(missing)}"
        )

    if calendar_history.schema[date_col] != pl.Date:
        calendar_history = calendar_history.with_columns(
            pl.col(date_col).cast(pl.Date)
        )

    lookup_rows: list[dict] = []

    for future_date in future_dates:
        try:
            source_date = future_date.replace(
                year=future_date.year - 1
            )
        except ValueError:
            # Feb-29 → previous year's Feb-28.
            source_date = future_date.replace(
                year=future_date.year - 1,
                day=28,
            )

        lookup_rows.append(
            {
                "__future_date": future_date,
                "__source_date": source_date,
            }
        )

    date_map = pl.DataFrame(lookup_rows)

    calendar = (
        date_map
        .join(
            calendar_history.select(
                [
                    pl.col(date_col).alias("__source_date"),
                    *[
                        pl.col(c).alias(c)
                        for c in CALENDAR_COLUMNS
                    ],
                ]
            ),
            on="__source_date",
            how="left",
        )
        .select(
            [
                pl.col("__future_date").alias(date_col),
                *CALENDAR_COLUMNS,
            ]
        )
    )

    if calendar.select(
        pl.any_horizontal(
            [pl.col(c).is_null() for c in CALENDAR_COLUMNS]
        ).any()
    ).item():
        calendar = calendar.with_columns(
            [
                pl.col(c).fill_null(0) if c != "holiday_name" else pl.col(c)
                for c in CALENDAR_COLUMNS
            ]
        )

    return calendar


def create_future_feature_frame(
    test_frame: pl.DataFrame,
    horizon_days: int = 14,
    config: PipelineConfig = DEFAULT_CONFIG,
    round_to_integer: bool = True,
    warehouse_defaults: Mapping | None = None,
    calendar_history: pl.DataFrame | None = None,
    special_l1_categories: Sequence[str] = ("Bakery",),
    total_orders_lookback_days: int = 84,
    price_lookback_days: int = 84,
    discount_lookback_days: int = 84,
    random_seed: int = 42,
    cutoff_date: date | str | None = None,
) -> pl.DataFrame:
    """
    Generate future model-input data with the exact raw-data schema.

    Future values:
    - total_orders:
        warehouse × date × order-group simulation.
        Normal items share one warehouse/day value.
        Special categories such as Bakery get correlated separate values.
    - sales:
        NULL for every future row.
    - price:
        empirically generated per item/date.
    - discounts:
        empirically generated per item/date/weekday.
    - calendar:
        copied from the same calendar date in the previous year.
    - metadata:
        carried from the latest historical item row.
    """
    if horizon_days <= 0:
        raise ValueError("horizon_days must be greater than 0.")

    missing_raw = set(RAW_DATA_COLUMNS) - set(test_frame.columns)

    # calendar columns may be supplied in a separate calendar_history,
    # but should still exist in the expected output schema.
    if missing_raw:
        raise ValueError(
            f"test_frame is missing required raw columns: {sorted(missing_raw)}"
        )

    date_col = config.date_column
    target_col = config.target_column
    order_col = config.order_column
    keys = list(config.series_keys)

    if date_col not in test_frame.columns:
        raise ValueError(f"Missing date column: {date_col!r}")

    if test_frame.schema[date_col] != pl.Date:
        test_frame = test_frame.with_columns(
            pl.col(date_col).cast(pl.Date)
        )

    if cutoff_date is None:
        cutoff_date = test_frame.select(
            pl.col(date_col).max()
        ).item()
    elif isinstance(cutoff_date, str):
        cutoff_date = date.fromisoformat(cutoff_date)
    elif isinstance(cutoff_date, datetime):
        cutoff_date = cutoff_date.date()

    future_dates = [
        cutoff_date + timedelta(days=i)
        for i in range(1, horizon_days + 1)
    ]

    # ------------------------------------------------------------------
    # 1. Future item/date grid with latest static metadata.
    # ------------------------------------------------------------------
    static_cols = [
        "name",
        "product_unique_id",
        "L1_category_name_en",
        "L2_category_name_en",
        "L3_category_name_en",
        "L4_category_name_en",
    ]

    forecast_items = (
        test_frame
        .sort([*keys, date_col])
        .group_by(keys)
        .agg([pl.col(col).last().alias(col) for col in static_cols])
    )

    future = forecast_items.join(
        pl.DataFrame({date_col: future_dates}),
        how="cross",
    )

    # ------------------------------------------------------------------
    # 3. Simulate total_orders.
    # ------------------------------------------------------------------
    simulated_orders = simulate_total_order_feature(
        history=test_frame,
        forecast_items=forecast_items,
        cutoff_date=cutoff_date,
        horizon_days=horizon_days,
        round_to_integer=round_to_integer,
        warehouse_defaults=warehouse_defaults,
        series_keys=config.series_keys,
        date_col=date_col,
        order_col=order_col,
        l1_category_col="L1_category_name_en",
        special_l1_categories=special_l1_categories,
        lookback_days=total_orders_lookback_days,
        random_seed=random_seed,
    )

    future = future.join(
        simulated_orders,
        on=[*keys, date_col],
        how="left",
    )

    # ------------------------------------------------------------------
    # 4. Generate future price.
    # ------------------------------------------------------------------
    generated_price = generate_future_price_feature(
        history=test_frame,
        forecast_items=forecast_items,
        future_dates=future_dates,
        date_col=date_col,
        item_col="unique_id",
        price_col="sell_price_main",
        lookback_days=price_lookback_days,
        random_seed=random_seed + 1,
    )

    future = future.join(
        generated_price,
        on=["unique_id", date_col],
        how="left",
    )

    # ------------------------------------------------------------------
    # 5. Generate future discounts.
    # ------------------------------------------------------------------
    generated_discounts = generate_future_discount_features(
        history=test_frame,
        forecast_items=forecast_items,
        future_dates=future_dates,
        date_col=date_col,
        item_col="unique_id",
        discount_columns=DISCOUNT_COLUMNS,
        lookback_days=discount_lookback_days,
        random_seed=random_seed + 2,
    )

    future = future.join(
        generated_discounts,
        on=["unique_id", date_col],
        how="left",
    )

    # ------------------------------------------------------------------
    # 6. Prior-year calendar.
    #
    # IMPORTANT:
    # calendar_history should contain at least the prior year's
    # calendar rows for the future dates.
    # ------------------------------------------------------------------
    if calendar_history is None:
        calendar_history = test_frame

    prior_year_calendar = _build_prior_year_calendar(
        calendar_history=calendar_history,
        future_dates=future_dates,
        date_col=date_col,
    )

    future = future.join(
        prior_year_calendar,
        on=date_col,
        how="left",
    )

    # ------------------------------------------------------------------
    # 7. sales must always be NULL.
    # ------------------------------------------------------------------
    future = future.with_columns(
        pl.lit(None)
        .cast(test_frame.schema[target_col])
        .alias(target_col)
    )

    # ------------------------------------------------------------------
    # 8. Exact output schema.
    # ------------------------------------------------------------------
    target_schema = {
        col: test_frame.schema[col]
        for col in RAW_DATA_COLUMNS
    }

    exprs: list[pl.Expr] = []

    for col in RAW_DATA_COLUMNS:
        dtype = target_schema[col]

        if col == target_col:
            exprs.append(
                pl.lit(None)
                .cast(dtype)
                .alias(col)
            )

        elif col == order_col:
            exprs.append(pl.col(col).round(0).cast(dtype).alias(col))

        elif col == "sell_price_main":
            exprs.append(pl.col(col).round(2).cast(dtype).alias(col))

        else:
            exprs.append(pl.col(col).cast(dtype).alias(col))

    result = (
        future
        .select(exprs)
        .sort([*keys, date_col])
    )

    # ------------------------------------------------------------------
    # 9. Fill nulls from sparse-history left joins, then validate.
    #
    # Items with near-zero sales (Deadstock candidates) may lack prior-year
    # calendar rows or price/discount history, producing nulls after left
    # joins. Fill numeric/bool cols with 0 so they still get all 14 future
    # rows instead of failing or being silently dropped by downstream joins.
    # String categoricals come from last() agg so they are always non-null.
    # ponytail: fill-with-0 is correct for calendar flags and discounts;
    #           price=0 is a weak fallback — upgrade to median if it causes
    #           model drift on price-sensitive categories.
    # ------------------------------------------------------------------
    str_dtypes = {pl.Utf8, pl.String, pl.Categorical}
    fill_cols = [
        c for c in RAW_DATA_COLUMNS
        if c not in (target_col, "holiday_name")
        and result.schema.get(c) not in str_dtypes
        and c != date_col
        and c not in keys
    ]
    null_in_fill = {
        c: result[c].null_count()
        for c in fill_cols
        if result[c].null_count() > 0
    }
    if null_in_fill:
        result = result.with_columns([
            pl.col(c).fill_null(0) for c in null_in_fill
        ])

    if result.columns != list(RAW_DATA_COLUMNS):
        raise DataValidationError(
            "Schema mismatch!\n"
            f"Expected: {list(RAW_DATA_COLUMNS)}\n"
            f"Got: {result.columns}"
        )

    if result.height == 0:
        raise DataValidationError(
            "Future feature frame is empty."
        )

    # sales must be completely NULL.
    sales_nulls = result.select(pl.col(target_col).null_count()).item()
    if sales_nulls != result.height:
        raise DataValidationError(f"Expected all {target_col!r} values to be NULL.")

    # Confirm no remaining nulls in non-target, non-holiday cols.
    non_target_cols = [c for c in RAW_DATA_COLUMNS if c not in (target_col, "holiday_name")]
    null_counts = result.select([pl.col(c).null_count() for c in non_target_cols]).row(0)
    for col, count in zip(non_target_cols, null_counts):
        if count > 0:
            raise DataValidationError(
                f"Column {col!r} has {count} NULL values in future data."
            )

    # total_orders must be a non-negative integer.
    bad_orders = result.filter(
        (pl.col(order_col) < 0)
        | (
            pl.col(order_col)
            != pl.col(order_col).cast(pl.Int64)
        )
    )

    if bad_orders.height > 0:
        raise DataValidationError(
            "total_orders contains invalid values."
        )

    return result


def run_feature_engineering(
    splits: DatasetSplits,
    config: PipelineConfig,
    emit: Callable[[str, str, Any], None],
    *,
    save: bool = False,
) -> FeatureEngineeringArtifacts:
    """Run the complete Rohlik feature engineering pipeline using the Class.

    This delegates the underlying transformations to `RohlikFeatureEngineeringPipeline`
    instance methods. The ``emit`` hook is called at every step boundary so the 
    SSE route can forward real-time progress to the browser.
    """
    t0 = time.perf_counter()
    
    # ── Initialize the Pipeline instance ──────────────────────────────────
    pipeline = RohlikFeatureEngineeringPipeline(config)

    # Ignore train and val; only test needed
    test_frame = splits.test if isinstance(splits, DatasetSplits) else splits

    # ── Step 0: Validation on test frame ──────────────────────────────────
    validate_base_test(test_frame, config)

    # ── Step 1: Deterministic base transforms ─────────────────────────────
    emit(
        "deterministic_transforms",
        "running",
        "Applying calendar, pricing, and promotional transforms…",
    )
    _t = time.perf_counter()
    deterministic = (
        test_frame
        .pipe(pipeline._add_time_features)
        .pipe(pipeline._add_name_feature)
        .pipe(pipeline._normalize_discounts)
        .pipe(pipeline._add_discount_price_features)
    )
    emit(
        "deterministic_transforms",
        "done",
        {
            "test_rows": deterministic.height,
            "elapsed_s": round(time.perf_counter() - _t, 3),
        },
    )

    # ── Step 2: Sales lag features ────────────────────────────────────────
    emit(
        "sales_lags",
        "running",
        "Computing sales momentum and calendar lag features…",
    )
    _t = time.perf_counter()
    sales_history = pipeline._prepare_sales_history(deterministic)
    with_sales_lags = pipeline._add_sales_lags(
        deterministic, sales_history, "test"
    )
    del sales_history
    emit(
        "sales_lags",
        "done",
        {
            "lag_count": len(config.sales_lags),
            "columns_added": list(config.sales_lag_columns),
            "elapsed_s": round(time.perf_counter() - _t, 3),
        },
    )

    # ── Step 3: Interaction + summary features ────────────────────────────
    emit(
        "interaction_features",
        "running",
        "Computing interaction and rolling summary features…",
    )
    _t = time.perf_counter()
    interaction_history = pipeline._prepare_interaction_history(deterministic)
    with_interactions = pipeline._add_interaction_summary_features(
        with_sales_lags, interaction_history, "test"
    )
    del with_sales_lags, interaction_history
    emit(
        "interaction_features",
        "done",
        {
            "interaction_lag_count": len(config.interaction_lags),
            "direct_kept": len(config.direct_interaction_lags),
            "summary_features": list(config.summary_feature_columns),
            "elapsed_s": round(time.perf_counter() - _t, 3),
        },
    )

    # ── Step 4: Discount lag features ─────────────────────────────────────
    n_discount_features = len(config.discount_columns) * len(config.discount_lags)
    emit(
        "discount_lags",
        "running",
        "Computing discount and promotional lag features…",
    )
    _t = time.perf_counter()
    discount_source = pipeline._prepare_discount_source(deterministic)
    del deterministic  # free memory — no longer needed

    engineered = pipeline._add_discount_lags(
        with_interactions, discount_source, "test"
    )
    del with_interactions, discount_source  # free memory
    emit(
        "discount_lags",
        "done",
        {
            "feature_count": n_discount_features,
            "elapsed_s": round(time.perf_counter() - _t, 3),
        },
    )

    # ── Step 5: Output validation ─────────────────────────────────────────
    emit("validation", "running", "Validating 139 ML feature columns and schema…")
    _t = time.perf_counter()
    
    pipeline._validate_output(engineered)
    feature_columns, categorical_columns, feature_groups_ = pipeline._model_columns(engineered)
    
    pipeline_warnings: list[str] = []
    expected = config.expected_feature_count
    if expected is not None and len(feature_columns) != expected:
        pipeline_warnings.append(
            f"Feature count hiện tại là {len(feature_columns)}, "
            f"khác mốc dự kiến {expected}."
        )
        
    emit(
        "validation",
        "done",
        {
            "feature_count": len(feature_columns),
            "categorical_count": len(categorical_columns),
            "warnings": pipeline_warnings,
            "elapsed_s": round(time.perf_counter() - _t, 3),
        },
    )

    # ── Step 6: Write (optional) ──────────────────────────────────────────
    saved_paths: Mapping[str, Path] = {}
    metadata_path: Path | None = None
    if save:
        emit(
            "write",
            "running",
            f"Writing test Parquet to {config.output_dir}…",
        )
        _t = time.perf_counter()
        config.output_dir.mkdir(parents=True, exist_ok=True)
        test_parquet = config.output_dir / "test_features.parquet"
        engineered.write_parquet(test_parquet, compression="zstd", compression_level=3)
        saved_paths = {"test": test_parquet}
        emit(
            "write",
            "done",
            {
                "output_dir": str(config.output_dir),
                "elapsed_s": round(time.perf_counter() - _t, 3),
            },
        )

    # ── Final summary ─────────────────────────────────────────────────────
    total_elapsed = round(time.perf_counter() - t0, 3)
    emit(
        "complete",
        "done",
        {
            "feature_count": len(feature_columns),
            "categorical_feature_count": len(categorical_columns),
            "test_rows": engineered.height,
            "warnings": pipeline_warnings,
            "total_elapsed_s": total_elapsed,
        },
    )

    # Wrap in DatasetSplits for caller compatibility
    splits_out = DatasetSplits(train=engineered, validation=engineered, test=engineered)

    return FeatureEngineeringArtifacts(
        splits=splits_out,
        feature_columns=feature_columns,
        categorical_columns=categorical_columns,
        feature_groups=feature_groups_,
        saved_paths=saved_paths,
        metadata_path=metadata_path,
        warnings=tuple(pipeline_warnings),
    )