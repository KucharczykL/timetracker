from datetime import datetime

import requests

url = "https://data.kurzy.cz/json/meny/b[6]den[{0}].json"
date_format = "%Y%m%d"
years = range(2000, datetime.now().year + 1)
dates = [
    datetime.strftime(datetime(day=1, month=1, year=year), format=date_format)
    for year in years
]
for date in dates:
    final_url = url.format(date)
    year = date[:4]
    response = requests.get(final_url)
    response.raise_for_status()
    data = response.json()
    if kurzy := data.get("kurzy"):
        with open("output.yaml", mode="a") as o:
            rates = [
                f"""
- model: games.exchangerate
            fields:
            currency_from: {currency_name}
            currency_to: CZK
            year: {year}
            rate: {kurzy.get(currency_name, {}).get("dev_stred", 0)}
                """
                for currency_name in ["EUR", "USD", "CNY"]
                if kurzy.get(currency_name)
            ]
            o.writelines(rates)
    # time.sleep(0.5)
