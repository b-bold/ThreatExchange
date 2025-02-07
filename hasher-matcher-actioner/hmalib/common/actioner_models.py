# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved

import hmalib.common.config as config
import json
import typing as t

from dataclasses import dataclass, field, fields
from hmalib.common.message_models import BankedSignal
from hmalib.common.logging import get_logger
from hmalib.common.message_models import MatchMessage
from requests import get, post, put, delete, Response

logger = get_logger(__name__)


class ActionPerformer(config.HMAConfigWithSubtypes):
    """
    An ActionPerfomer is the configuration + the code to perform an action.

    All actions share the same namespace (so that a post action and a
    "send to review" action can't both be called "IActionReview")

    ActionPerformer.get("action_name").perform_action(match_message)
    """

    @staticmethod
    def get_subtype_classes():
        return [
            WebhookPostActionPerformer,
            WebhookGetActionPerformer,
            WebhookPutActionPerformer,
            WebhookDeleteActionPerformer,
        ]

    # Implemented by subtypes
    def perform_action(self, match_message: MatchMessage) -> None:
        raise NotImplementedError


@dataclass
class WebhookActionPerformer(ActionPerformer):
    """Superclass for webhooks"""

    url: str

    def perform_action(self, match_message: MatchMessage) -> None:
        self.call(data=json.dumps(match_message.to_aws()))

    def call(self, data: str) -> Response:
        raise NotImplementedError()


@dataclass
class WebhookPostActionPerformer(WebhookActionPerformer):
    """Hit an arbitrary endpoint with a POST"""

    def call(self, data: str) -> Response:
        return post(self.url, data)


@dataclass
class WebhookGetActionPerformer(WebhookActionPerformer):
    """Hit an arbitrary endpoint with a GET"""

    def call(self, _data: str) -> Response:
        return get(self.url)


@dataclass
class WebhookPutActionPerformer(WebhookActionPerformer):
    """Hit an arbitrary endpoint with a PUT"""

    def call(self, data: str) -> Response:
        return put(self.url, data)


@dataclass
class WebhookDeleteActionPerformer(WebhookActionPerformer):
    """Hit an arbitrary endpoint with a DELETE"""

    def call(self, _data: str) -> Response:
        return delete(self.url)


if __name__ == "__main__":

    banked_signals = [
        BankedSignal("2862392437204724", "bank 4", "te"),
        BankedSignal("4194946153908639", "bank 4", "te"),
    ]
    match_message = MatchMessage("key", "hash", banked_signals)

    configs: t.List[ActionPerformer] = [
        WebhookDeleteActionPerformer(
            "DeleteWebhook", "https://webhook.site/ff7ebc37-514a-439e-9a03-46f86989e195"
        ),
        WebhookPutActionPerformer(
            "PutWebook", "https://webhook.site/ff7ebc37-514a-439e-9a03-46f86989e195"
        ),
    ]

    for action_config in configs:
        action_config.perform_action(match_message)
