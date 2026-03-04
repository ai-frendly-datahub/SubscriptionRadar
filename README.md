# SubscriptionRadar

SubscriptionRadar tracks subscription and pricing-plan news, extracts matched entities, stores
results in DuckDB, and generates an HTML report.

## Usage

```bash
python main.py --category subscription
python main.py --category subscription --recent-days 7 --keep-days 90
pytest tests/ -v
```
