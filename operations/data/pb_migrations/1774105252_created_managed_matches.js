/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const collection = new Collection({
    "createRule": null,
    "deleteRule": null,
    "fields": [
      {
        "autogeneratePattern": "[a-z0-9]{15}",
        "hidden": false,
        "id": "text3208210256",
        "max": 15,
        "min": 15,
        "name": "id",
        "pattern": "^[a-z0-9]+$",
        "presentable": false,
        "primaryKey": true,
        "required": true,
        "system": true,
        "type": "text"
      },
      {
        "autogeneratePattern": "",
        "hidden": false,
        "id": "text1579384326",
        "max": 0,
        "min": 0,
        "name": "name",
        "pattern": "",
        "presentable": false,
        "primaryKey": false,
        "required": true,
        "system": false,
        "type": "text"
      },
      {
        "hidden": false,
        "id": "select2063623452",
        "maxSelect": 0,
        "name": "status",
        "presentable": false,
        "required": true,
        "system": false,
        "type": "select",
        "values": [
          "queued",
          "running",
          "completed",
          "failed",
          "aborted",
          "interrupted"
        ]
      },
      {
        "hidden": false,
        "id": "json3219281744",
        "maxSize": 0,
        "name": "seats",
        "presentable": false,
        "required": true,
        "system": false,
        "type": "json"
      },
      {
        "autogeneratePattern": "",
        "hidden": false,
        "id": "text934806468",
        "max": 0,
        "min": 0,
        "name": "fallback_bot_id",
        "pattern": "",
        "presentable": false,
        "primaryKey": false,
        "required": true,
        "system": false,
        "type": "text"
      },
      {
        "hidden": false,
        "id": "number1403670683",
        "max": null,
        "min": null,
        "name": "round_count",
        "onlyInt": false,
        "presentable": false,
        "required": true,
        "system": false,
        "type": "number"
      },
      {
        "hidden": false,
        "id": "json3109850413",
        "maxSize": 0,
        "name": "time_control",
        "presentable": false,
        "required": true,
        "system": false,
        "type": "json"
      },
      {
        "hidden": false,
        "id": "select444643669",
        "maxSelect": 0,
        "name": "timeout_policy",
        "presentable": false,
        "required": true,
        "system": false,
        "type": "select",
        "values": [
          "loss_on_time",
          "switch_to_fallback",
          "abort_match"
        ]
      },
      {
        "hidden": false,
        "id": "select1907566933",
        "maxSelect": 0,
        "name": "execution_mode",
        "presentable": false,
        "required": true,
        "system": false,
        "type": "select",
        "values": [
          "bot_api"
        ]
      },
      {
        "autogeneratePattern": "",
        "hidden": false,
        "id": "text2678771233",
        "max": 0,
        "min": 0,
        "name": "replay_match_id",
        "pattern": "",
        "presentable": false,
        "primaryKey": false,
        "required": false,
        "system": false,
        "type": "text"
      },
      {
        "hidden": false,
        "id": "number2912327715",
        "max": null,
        "min": null,
        "name": "current_round_number",
        "onlyInt": false,
        "presentable": false,
        "required": false,
        "system": false,
        "type": "number"
      },
      {
        "hidden": false,
        "id": "json2465839912",
        "maxSize": 0,
        "name": "aggregate_results",
        "presentable": false,
        "required": false,
        "system": false,
        "type": "json"
      }
    ],
    "id": "pbc_159250117",
    "indexes": [],
    "listRule": null,
    "name": "managed_matches",
    "system": false,
    "type": "base",
    "updateRule": null,
    "viewRule": null
  });

  return app.save(collection);
}, (app) => {
  const collection = app.findCollectionByNameOrId("pbc_159250117");

  return app.delete(collection);
})
