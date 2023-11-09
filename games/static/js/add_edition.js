import { syncSelectInputUntilChanged } from './utils.js';

let syncData = [
  {
    "source": "#id_game",
    "source_value": "dataset.name",
    "target": "#id_name",
    "target_value": "value"
  },
  {
    "source": "#id_game",
    "source_value": "textContent",
    "target": "#id_sort_name",
    "target_value": "value"
  },
  {
    "source": "#id_game",
    "source_value": "dataset.year",
    "target": "#id_year_released",
    "target_value": "value"
  },  
]

syncSelectInputUntilChanged(syncData, "form");
