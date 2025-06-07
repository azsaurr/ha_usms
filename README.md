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

## Install

### If you have [HACS](https://hacs.xyz/) installed

HA-USMS is now available in the [Home Assistant Community Store](https://hacs.xyz/)!

Use this button and enter the URL for your Home Assistant instance for easy installation.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=azsaurr&repository=HA-USMS)

#### Alternatively

- Open HACS from the sidebar of your Home Assistant dashboard
- Search for `HA-USMS` in the search bar
- Click on the 3-dot menu and click `Download`
- Select the (default) latest version and begin the download
- Reboot Home Assistant for changes to take effect

### Manual installation without HACS

- Download the latest release from here: https://github.com/azsaurr/ha_usms/releases/latest
- Extract the downloaded `.zip` file
- Copy and paste `custom_components/ha_usms` from this repo to `<home_assistant>/config/custom_components/ha_usms`
- Reboot Home Assistant for changes to take effect

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
- [x] Re-structure source code files
- [x] Support for configuration via GUI
- [ ] Go through Home Assistant's [development checklist](https://developers.home-assistant.io/docs/development_checklist)
- [x] Publish package to HACS store
- [x] Support for water meter

## License

Distributed under the MIT License. See `LICENSE` for more information.

## Acknowledgments

This project was made possible with help from…

- [Home Assistant Developer Documentation](https://developers.home-assistant.io/docs/creating_component_index)
- [Home Assistant Community Store](https://hacs.xyz/)
- Scaffolded using [ludeeus/integration_blueprint](https://github.com/ludeeus/integration_blueprint)
- [homeassistant-statistics](https://github.com/klausj1/homeassistant-statistics), which provided useful reference for importing statistics
- [USMS Portal](https://www.usms.com.bn/smartmeter/about.html) for providing access to smart meter data
- [usms](https://github.com/azsaurr/usms), wrapper for interacting with the USMS portal
