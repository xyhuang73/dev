---
name: localdata-pipeline
description: Build and evolve the project's LocalData ingestion and backtest data layer from QMT (Q) and source CSV/Excel (T), including daily and minute bars, GUI import controls, and staged implementation.
metadata:
  short-description: Implement Q/T to LocalData pipeline
---

# LocalData pipeline

Use this skill when planning, implementing, debugging, or reviewing the project's QMT/Excel ingestion, LocalData storage, or backtest data access. Treat this as an incremental migration: preserve current app behavior while introducing the new data layer.

## User-defined terms and locations

- `Q`: QMT source data. Current QMT install is `D:\MinQmt\国金证券QMT交易端`; QMT writes standard-client history under its `datadir` when present. Do not assume `userdata_mini` exists.
- `T`: source daily-indicator CSV files under `E:\01_StockOrignData\A股数据_每日指标\每日指标` (the user calls this Excel data, but current files are CSV).
- `T` minute source: annual per-symbol CSV files under `E:\01_StockOrignData\A股分钟数据\A股_分时数据_沪深\1分钟_按年汇总\<year>_1min`.
- `LocalData`: normalized, user-owned backtest data. Final output root: `E:\03_back_test_data`.
- Backtests must support both cross-sectional/batch queries and timestamp-ordered event simulation. Do not load an entire multi-year/all-symbol dataset into memory for a single-symbol query.

## Storage and normalized contracts

- Use DuckDB as the queryable LocalData store (`E:\03_back_test_data\LocalData\market.duckdb`). Use Parquet for immutable snapshots/interchange when appropriate; keep source files untouched.
- Keep daily and intraday bars logically separate (`bars_1d`, `bars_1m`, and additional periods as needed); also maintain instruments, trading calendar, corporate actions/adjustment factors, and an import manifest.
- Canonical bar identity is `(symbol, period, timestamp)`. Store normalized symbols such as `600000.SH` and `000001.SZ`, period, timestamp, trading day, OHLC, volume, amount, adjustment factor where known, source (`Q` or `T`), source file, import batch, and ingestion time.
- Retain T's additional daily indicators as typed columns or a related daily-factors table; do not discard them when constructing OHLCV bars.
- Preserve units and source semantics. In particular, inspect whether volume is shares/lots and amount is yuan/thousand-yuan before conversion; record conversions in importer metadata.
- Resolve duplicate keys deterministically and visibly. Preserve provenance; never silently mix Q/T values. Prefer source-specific records or explicit configurable precedence.
- Partition bulk interchange snapshots by `period/year/month` or another demonstrated query key; avoid one-file-per-symbol-per-day small-file explosions. For the DuckDB store, cluster/order bulk inserts by `(period, timestamp, symbol)` and use date/symbol predicates in readers.

## Observed source schemas

- T daily-indicator CSV columns include `股票代码`, `交易日期`, OHLC, `昨收价`, `涨跌额`, `涨跌幅`, `成交量(手)`, `成交额(千元)`, turnover, valuation, shares, and market-cap columns. Missing indicators are expected; preserve nulls.
- T 1-minute CSV sample columns are `时间,代码,名称,开盘价,收盘价,最高价,最低价,成交量,成交额,涨幅,振幅`. A sample code is lowercase `sh600000`; normalize to `600000.SH`. Parse `时间` as local exchange time and derive `trading_day`.
- QMT local `.DAT` formats are period/client-version specific. Reuse a parser only for formats already validated in this repository. Existing daily DAT parser is in `BackTest/factor_local_datadir_panel.py`; do not assume it parses minute DAT. If QMT minute DAT cannot be decoded reliably, ingest minute bars from T first and leave Q minute ingestion as an explicit unsupported adapter until validated.

## GUI integration

- The existing import/update dialog is `GUI/UpdateStock.ui`, wired by `Prepare/update_stock_dialog.py`.
- Add a distinct `Import/Update LocalData` action without repurposing or mislabeling the current QMT download action. If helpful, expose source checkboxes (Q daily, Q minute, T daily, T minute) and date range; defaults should avoid unexpectedly importing the full universe/year.
- Run bulk scans/imports off the GUI thread. Stream coarse progress, counts, date coverage, skipped rows, conflicts, and errors to the existing main-window log relay.
- Persist the selected source paths and LocalData root in a dedicated data config, not by overloading `Config/qmt.json` beyond QMT connection/install settings.

## Local strategy and backtest integration

- Local strategies consume canonical `Bar`/panel data through a `MarketDataGateway` or `LocalDataRepository`; strategy logic must not know about QMT DAT, source CSV/Excel, DuckDB SQL, or XTQuant connectivity.
- Provide three shared query shapes: `load_bars(symbols, period, start, end, fields=None)` for bounded time series; `load_cross_section(trading_day, symbols, period='1d', fields=None)` for batch cross-sectional work; and `iter_events(symbols, period, start, end, chunk_size=...)` for timestamp-ordered event simulation.
- Extend backtest job configuration with `dataset_id`, `period`, `source_policy`, `universe_id`, and date range. Suggested source policies: `prefer_Q`, `prefer_T`, `Q_only`, `T_only`. Preserve Q/T provenance and apply precedence at query time; never silently overwrite one source with another during ingest.
- Cross-sectional readers should fetch only the requested trading day/date range and universe. Event readers should stream bounded chunks ordered by `(timestamp, symbol)` and preserve deterministic ordering for same-time events. Single-symbol access must be a bounded symbol/period/time query.
- Migrate old readers through adapters. Existing `BackTest/factor_market_panel.py` switches between local DAT and XTQuant, and `BackTest/factor_local_datadir_panel.py` contains a verified QMT daily DAT parser; route these behind the gateway before rewriting strategies.
- Migrate one daily cross-sectional strategy first, then one minute event strategy. Keep strategy signal and portfolio logic unchanged during data-source migration; convert only at the gateway boundary.
- Treat ingestion and backtest execution as separate stages. T daily/minute and verified Q daily can feed LocalData even while XTQuant is unavailable. Do not block these adapters on Q's external service. Q minute ingestion remains unavailable until its API or file format is independently validated.
- Audit actual engine readiness before describing strategy integration as complete. In this repository `BackTest/engines/vector_engine.py` only dispatches implemented runners (others return placeholders), and `BackTest/engines/event_engine.py` is currently a placeholder. LocalData readers alone do not make those backtest modes executable; implement and validate the engines separately.

## Staged implementation workflow

For roadmap work, deliver one bounded stage at a time and keep the stages independently usable:

1. **Inventory and schema**: inspect representative files from every source and periods/years; confirm encodings, delimiters, headers, units, symbol mapping, timestamps, duplicate behavior, and data coverage. Write the schema and data contract before bulk conversion.
2. **LocalData foundation**: add database dependency/config, schema creation, import manifest, idempotent upsert/replace-by-range, and targeted query functions. Verify single-symbol and single-day reads do not scan/materialize all data.
3. **T daily and minute adapters**: implement CSV streaming/chunked ingestion, type normalization, unit conversions, symbol normalization, and row-level rejects. Preserve original files.
4. **Q adapters**: reuse verified Q daily DAT parser. Implement Q minute only after byte-layout/API validation; do not conflate quote-server availability with local-file importability.
5. **GUI actions**: wire source selection/date ranges to background import workers; surface progress and manifest results. Keep Q download and LocalData import as separate operations.
6. **Backtest gateway and config**: add the repository/gateway query shapes and `dataset_id/source_policy/period` to job config; route one existing panel reader through it while preserving its output schema.
7. **Cross-sectional migration**: migrate one daily strategy and compare its prepared panel/signals against the existing path over a fixed date range.
8. **Event reader and engine**: implement ordered chunk iteration first, then event queue, strategy callbacks, matching, fees/slippage, portfolio updates, and replay artifacts. Do not present an event-mode placeholder as a real backtest.
9. **Coverage and performance review**: report annual row counts/storage/import time and single-symbol/year query performance. Add schema/version metadata and reproducible import batches.

Do not claim a stage is complete solely because a database file exists. Verify the actual row counts, sample values, units, date coverage, and query path for each supported source.

For implementation details and schema examples, read [references/data-layout-and-stages.md](references/data-layout-and-stages.md).
