"""Adds config flow for HA-USMS."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from slugify import slugify
from usms import AsyncUSMSAccount
from usms.exceptions.errors import USMSLoginError

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER, MIN_SCAN_INTERVAL


class HAUSMSFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for HA-USMS."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle a flow initialized by the user."""
        _errors = {}
        if user_input is not None:
            try:
                await self._test_credentials(
                    username=user_input[CONF_USERNAME],
                    password=user_input[CONF_PASSWORD],
                )
            except USMSLoginError as exception:
                LOGGER.exception(exception)
                _errors["base"] = "auth"
            else:
                await self.async_set_unique_id(
                    ## Do NOT use this in production code
                    ## The unique_id should never be something that can change
                    ## https://developers.home-assistant.io/docs/config_entries_config_flow_handler#unique-ids
                    unique_id=slugify(user_input[CONF_USERNAME], separator="_")
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"USMS Account {user_input[CONF_USERNAME]}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=(user_input or {}).get(CONF_USERNAME, vol.UNDEFINED),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        ),
                    ),
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                        ),
                    ),
                },
            ),
            errors=_errors,
        )

    async def _test_credentials(self, username: str, password: str) -> None:
        """Validate credentials."""
        await AsyncUSMSAccount.create(username, password)

    async def async_step_reconfigure(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle a reconfigure flow initialized by the user."""
        _errors = {}
        if user_input is not None:
            try:
                await self._test_credentials(
                    username=user_input[CONF_USERNAME],
                    password=user_input[CONF_PASSWORD],
                )
            except USMSLoginError as exception:
                LOGGER.exception(exception)
                _errors["base"] = "auth"
            else:
                await self.async_set_unique_id(
                    unique_id=slugify(user_input[CONF_USERNAME], separator="_")
                )
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(),
                    data_updates=user_input,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=(user_input or {}).get(CONF_USERNAME, vol.UNDEFINED),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        ),
                    ),
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                        ),
                    ),
                },
            ),
            errors=_errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,  # noqa: ARG004
    ) -> HAUSMSOptionsFlowHandler:
        """Create the options flow."""
        return HAUSMSOptionsFlowHandler()


class HAUSMSOptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow for HA-USMS."""

    async def async_step_init(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle options flow."""
        if user_input is not None:
            options = self.config_entry.options | user_input
            return self.async_create_entry(title="", data=options)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): (vol.All(vol.Coerce(int), vol.Clamp(min=MIN_SCAN_INTERVAL))),
                }
            ),
        )
