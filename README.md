# USMS Smart Meter Custom Integration for Home Assistant

[USMS](https://www.usms.com.bn/smartmeter/about.html) is a digital platform for electric and water meters in Brunei. This integration allows Home Assistant to poll data from your USMS account.

Getting started is as easy as providing your login information (username and password), and Home Assistant will handle the rest. After configuration, every meter under the account will be made available in Home Assistant, alongside the following values as extra attributes:

- `Credit` - remaining balance/credit
- `Unit` - remaining unit, also the default state of the entity
- `Last update` - timestamp of last update by USMS
- `Last refresh` - timestamp of last refresh attempt by the integration
- `Currency` - currency in BND (Brunei Dollars)
- `Last month consumption` - the total consumption of this meter last month
- `Last month cost` - the cost for the total consumption of this meter last month
- `This month consumption` - the total consumption of this meter this month
- `This month cost` - the cost for the total consumption of this meter this month

Each meter also has two associated buttons. The `Download and Import History` button will fetch all data and import them as long-term statistics, allowing the meter to be imported into Home Assistant's Energy dashboard. The `Recalculate Statistics` button is mostly for fixing broken statistics, if any.

> **Note:** For now only electric meters are supported since I do not have the smart water meter installed yet.

## Install

### If you have [HACS](https://hacs.xyz/) installed

- Open HACS
- Click on the 3-dot menu on the top right of the page
- Select `Custom repositories`
- Copy and paste this repository into the text field:
    ```https://github.com/azsaurr/ha_usms```
- Select `Integration` from the dropdown
- Click `Add`

### Manual installation

- Download the source code of this repository
- Extract the downloaded `.zip` file
- Copy and paste ```./config/custom_components/ha_usms``` from this repo to ```<home_assistant>/config/custom_components/ha_usms```

## Configuration

After installation:

- Open Settings
- Select `Devices & services`
- Click the floating blue `Add Integration` button
- Search for and select `HA-USMS`
- Enter your username and password
- Submit

## To-Do

- [ ] Improve README
- [X] Re-structure source code files
- [X] Support for configuration via GUI
- [ ] Go through Home Assistant's [development checklist](https://developers.home-assistant.io/docs/development_checklist)
- [ ] Publish package to HACS store
- [ ] Support for water meter

## License

Distributed under the MIT License. See `LICENSE` for more information.

## Acknowledgments

This project was made possible with help from…

- [Home Assistant Developer Documentation](https://developers.home-assistant.io/docs/creating_component_index)
- Scaffolded using [ludeeus/integration_blueprint](https://github.com/ludeeus/integration_blueprint)
- [homeassistant-statistics](https://github.com/klausj1/homeassistant-statistics), which provided useful reference for importing statistics
- [USMS Portal](https://www.usms.com.bn/smartmeter/about.html) for providing access to smart meter data
- [usms](https://github.com/azsaurr/usms), wrapper for interacting with the USMS portal
