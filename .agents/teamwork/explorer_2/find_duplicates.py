import pandas as pd
from pathlib import Path

train_data = Path('d:/PROJECT/ZALO-AI-CHALLENGE-2026/data/train/data')

def find_duplicates_in_shops():
    for shop_dir in sorted(train_data.glob('biz_*')):
        for f in shop_dir.glob('*.xlsx'):
            try:
                # check first sheet
                df = pd.read_excel(f, nrows=1000)
                # check if there are duplicate rows
                dups = df.duplicated().sum()
                if dups > 0:
                    print(f"Shop {shop_dir.name} File {f.name}: {dups} duplicated rows in first 1000")
            except Exception as e:
                pass
        for f in shop_dir.glob('*.csv'):
            try:
                df = pd.read_csv(f, nrows=1000)
                dups = df.duplicated().sum()
                if dups > 0:
                    print(f"Shop {shop_dir.name} File {f.name}: {dups} duplicated rows in first 1000")
            except Exception as e:
                pass

find_duplicates_in_shops()
