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

## Long-term statistics

Consumption history is published as **external statistics** under
`ha_usms:<meter>` (for example `ha_usms:electricity_meter_55014488`), not under
the meter sensor's own entity id. The meter sensor reports *remaining* prepaid
units, which is a level and must not be summed, so keeping the cumulative
consumption series on a separate external id is what stops Home Assistant's
recorder raising a recurring "entity no longer has a state class" repair.

On upgrade the integration migrates any existing `sensor.<meter>` statistics to
the new external id automatically: it writes a JSON backup of the legacy rows to
`config/ha_usms/statistics_backup/`, copies them, verifies the copy, and only
then removes the old series. If you had added a meter to the **Energy dashboard**
or a statistics graph, repoint it from `sensor.<meter>` to `ha_usms:<meter>`
after upgrading (the meter's own sensor entity keeps its id and is unchanged).

## Month-end projections

Each meter gains three projection sensors, computed from that meter's own
recorded daily history, so they are not tuned to any particular account:

- **Projected Month Consumption** — month-to-date usage plus the remaining days
  at a blended recent daily rate.
- **Projected Month Cost** — that projected consumption priced on the USMS
  residential tariff.
- **Credit Runs Out** — a timestamp of when the remaining prepaid units are
  projected to be exhausted at the current rate.

Projections are empty until a meter has a little recorded history, and sharpen
as the month fills in.

## Configuration

After installation:

- Open Settings
- Select `Devices & services`
- Click the floating blue `Add Integration` button
- Search for and select `HA-USMS`
- Enter your username and password
- Submit

## Cost in the Energy dashboard

Each meter also publishes a cost statistic in B$, alongside its consumption
statistic: `ha_usms:electricity_meter_<number>_cost` and
`ha_usms:water_meter_<number>_cost`. Point the Energy dashboard at it under
*Settings → Dashboards → Energy*: edit the grid consumption (or water) source,
choose *Use an entity tracking the total costs*, and pick the meter's `Cost`
statistic. A fixed price would be wrong for USMS, whose tariff is tiered.

It records what each hour actually cost, not a tariff estimate. USMS is prepaid:
a top-up buys units priced on the tiers, counted over that calendar month's
purchases, and the meter uses units oldest first. Units left over from last
month's dearer top-ups are therefore still charged at their price into the new
month, and the cheaper tier only starts once they run out. The integration takes
each hour's cost from the meter's own credit balance, recorded every update, so
it follows all of this exactly.

Hours with no credit reading to go by - history from before the credit was
recorded, and the latest hour or two until the next reading - are priced from the
tariff on the calendar month's consumption instead, and the latest hours are
corrected once their reading arrives. When the integration was unable to update
for a while, the credit lost over the gap is spread across its hours by
consumption.

## USMS login captcha (October 2026)

USMS added an image captcha to its login in October 2026, which broke every
version of this integration up to 1.2.2: Home Assistant logged `USMSLoginError:
Invalid login.` and retried forever, even though the password was correct.

From 1.3.0 the integration needs no extra setup for this. The underlying
[usms](https://github.com/azsaurr/usms) library (1.2.0 and later) solves the captcha
itself with a small bundled model that runs on numpy alone, so nothing else -
no add-on and no external service - has to be installed. See the library's
README for how it works.

If USMS rejects every captcha answer in a row, the update is simply retried at
the next poll. Home Assistant only asks you to re-enter your credentials when
USMS actually rejects the password.

## To-Do

- [ ] Improve README
- [x] Re-structure source code files
- [x] Support for configuration via GUI
- [ ] Go through Home Assistant's [development checklist](https://developers.home-assistant.io/docs/development_checklist) (see `custom_components/ha_usms/quality_scale.yaml` for per-rule status)
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
- [ddddocr](https://github.com/sml2h3/ddddocr) by sml2h3 (MIT), whose OCR model the usms library's captcha solver is derived from
