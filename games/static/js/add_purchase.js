import { syncSelectInputUntilChanged } from './utils.js'

let syncData = [
  {
    "source": "#id_edition",
    "source_value": "dataset.platform",
    "target": "#id_platform",
    "target_value": "value"
  }
]

syncSelectInputUntilChanged(syncData, "form")
