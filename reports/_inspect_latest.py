import os, glob, pandas as pd
files = sorted(glob.glob('E:/MinQMT/F3_test/dev/reports/strategy/strategy_backtest_S000001_2026*/strategy_backtest_S000001_*.xlsx'))
if not files:
    files = sorted(glob.glob('E:/MinQMT/F3_test/dev/reports/strategy/strategy_backtest_S000001_2026*.xlsx'))
fp = files[-1]
print('最新 Excel:', fp)
xl = pd.ExcelFile(fp)
print('Sheet:', xl.sheet_names)
print()
print('=== 逐笔买卖明细 (head) ===')
df = pd.read_excel(fp, sheet_name='逐笔买卖明细')
print(df.head(8).to_string(index=False))
print('总笔数:', len(df), '  买:', int((df.action=='buy').sum()), '  卖:', int((df.action=='sell').sum()))
if 'sell_kind' in df.columns:
    print('卖出分类:', df[df.action=='sell']['sell_kind'].value_counts().to_dict())
print()
print('=== 组合收益统计 ===')
print(pd.read_excel(fp, sheet_name='组合收益统计').to_string(index=False))
print()
print('=== 按ETF汇总统计 (top 5) ===')
ps = pd.read_excel(fp, sheet_name='按ETF汇总统计')
print(ps.head(5).to_string(index=False))