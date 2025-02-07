# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved

import boto3
import json
import os
import typing as t

from dataclasses import dataclass, field
from functools import lru_cache
from hmalib.common.logging import get_logger
from hmalib.common.classification_models import (
    BankedContentIDClassificationLabel,
    BankIDClassificationLabel,
    BankSourceClassificationLabel,
    ClassificationLabel,
    Label,
)
from hmalib.common.config import HMAConfig
from hmalib.common.evaluator_models import (
    Action,
    ActionLabel,
    ActionRule,
    ThreatExchangeReactionLabel,
)
from hmalib.common.message_models import (
    ActionMessage,
    BankedSignal,
    MatchMessage,
    ReactionMessage,
)
from hmalib.lambdas.actions.action_performer import perform_label_action
from mypy_boto3_sqs import SQSClient

logger = get_logger(__name__)


@dataclass
class ActionEvaluatorConfig:
    """
    Simple holder for getting typed environment variables
    """

    actions_queue_url: str
    reactions_queue_url: str
    sqs_client: SQSClient

    @classmethod
    @lru_cache(maxsize=None)
    def get(cls):
        logger.info(
            "Initializing configs using table name %s", os.environ["CONFIG_TABLE_NAME"]
        )
        HMAConfig.initialize(os.environ["CONFIG_TABLE_NAME"])
        return cls(
            actions_queue_url=os.environ["ACTIONS_QUEUE_URL"],
            reactions_queue_url=os.environ["REACTIONS_QUEUE_URL"],
            sqs_client=boto3.client("sqs"),
        )


def lambda_handler(event, context):
    """
    This lambda is called when one or more matches are found. If a single hash matches
    multiple datasets, this will be called only once.

    Action labels are generated for each match message, then an action is performed
    corresponding to each action label.
    """
    config = ActionEvaluatorConfig.get()

    for sqs_record in event["Records"]:
        # TODO research max # sqs records / lambda_handler invocation
        sqs_record_body = json.loads(sqs_record["body"])
        match_message = MatchMessage.from_aws_json(sqs_record_body["Message"])

        logger.info("Evaluating match_message: %s", match_message)

        action_rules = get_action_rules()

        logger.info("Evaluating against action_rules: %s", action_rules)

        action_label_to_action_rules = get_actions_to_take(match_message, action_rules)
        action_labels = list(action_label_to_action_rules.keys())
        for action_label in action_labels:
            action_message = (
                ActionMessage.from_match_message_action_label_and_action_rules(
                    match_message,
                    action_label,
                    action_label_to_action_rules[action_label],
                )
            )
            config.sqs_client.send_message(
                QueueUrl=config.actions_queue_url,
                MessageBody=action_message.to_aws_json(),
            )

        if threat_exchange_reacting_is_enabled(match_message):
            threat_exchange_reaction_labels = get_threat_exchange_reaction_labels(
                match_message, action_labels
            )
            if threat_exchange_reaction_labels:
                for threat_exchange_reaction_label in threat_exchange_reaction_labels:
                    threat_exchange_reaction_message = (
                        ReactionMessage.from_match_message_and_label(
                            match_message, threat_exchange_reaction_label
                        )
                    )
                    config.sqs_client.send_message(
                        QueueUrl=config.reactions_queue_url,
                        MessageBody=threat_exchange_reaction_message.to_aws_json(),
                    )

    return {"evaluation_completed": "true"}


def get_actions_to_take(
    match_message: MatchMessage, action_rules: t.List[ActionRule]
) -> t.Dict[ActionLabel, t.List[ActionRule]]:
    """
    Returns action labels for each action rule that applies to a match message.
    """
    action_label_to_action_rules: t.Dict[ActionLabel, t.List[ActionRule]] = dict()
    for banked_signal in match_message.matching_banked_signals:
        for action_rule in action_rules:
            if action_rule_applies_to_classifications(
                action_rule, banked_signal.classifications
            ):
                if action_rule.action_label in action_label_to_action_rules:
                    action_label_to_action_rules[action_rule.action_label].append(
                        action_rule
                    )
                else:
                    action_label_to_action_rules[action_rule.action_label] = [
                        action_rule
                    ]
    action_label_to_action_rules = remove_superseded_actions(
        action_label_to_action_rules
    )
    return action_label_to_action_rules


def get_action_rules() -> t.List[ActionRule]:
    """
    TODO Research caching rules for a short bit of time (1 min? 5 min?) use @lru_cache to implement
    Returns the ActionRule objects stored in the config repository. Each ActionRule
    will have the following attributes: MustHaveLabels, MustNotHaveLabels, ActionLabel.
    """
    return ActionRule.get_all()


def action_rule_applies_to_classifications(
    action_rule: ActionRule, classifications: t.Set[Label]
) -> bool:
    """
    Evaluate if the action rule applies to the classifications. Return True if the action rule's "must have"
    labels are all present and none of the "must not have" labels are present in the classifications, otherwise return False.
    """
    return action_rule.must_have_labels.issubset(
        classifications
    ) and action_rule.must_not_have_labels.isdisjoint(classifications)


def get_actions() -> t.List[Action]:
    """
    TODO implement
    Returns the Action objects stored in the config repository. Each Action will have
    the following attributes: ActionLabel, Priority, SupersededByActionLabel (Priority
    and SupersededByActionLabel are used by remove_superseded_actions).
    """
    return [
        Action(
            ActionLabel("EnqueueForReview"),
            1,
            [ActionLabel("A_MORE_IMPORTANT_ACTION")],
        )
    ]


def remove_superseded_actions(
    action_label_to_action_rules: t.Dict[ActionLabel, t.List[ActionRule]],
) -> t.Dict[ActionLabel, t.List[ActionRule]]:
    """
    TODO implement
    Evaluates a dictionary of action labels and the associated action rules generated for
    a match message against the actions. Action labels that are superseded by another will
    be removed.
    """
    return action_label_to_action_rules


def threat_exchange_reacting_is_enabled(match_message: MatchMessage) -> bool:
    """
    TODO implement
    Looks up from a config whether ThreatExchange reacting is enabled. Initially this will be a global
    config, and this method will return True if reacting is enabled, False otherwise. At some point the
    config for reacting to ThreatExchange may be on a per collaboration basis. In that case, the config
    will be referenced for each collaboration involved (implied by the match message). If reacting
    is enabled for a given collaboration, a label will be added to the match message
    (e.g. "ThreatExchangeReactingEnabled:<collaboration-id>").
    """
    return True


def get_threat_exchange_reaction_labels(
    match_message: MatchMessage,
    action_labels: t.List[ActionLabel],
) -> t.List[Label]:
    """
    TODO implement
    Evaluates a collection of action_labels against some yet to be defined configuration
    (and possible business login) to produce
    """
    return [ThreatExchangeReactionLabel("SAW_THIS_TOO")]


if __name__ == "__main__":
    # For basic debugging

    action_rules = [
        ActionRule(
            name="Enqueue Mini-Castle for Review",
            action_label=ActionLabel("EnqueueMiniCastleForReview"),
            must_have_labels=set(
                [
                    BankIDClassificationLabel("303636684709969"),
                    ClassificationLabel("true_positive"),
                ]
            ),
            must_not_have_labels=set(
                [BankedContentIDClassificationLabel("3364504410306721")]
            ),
        ),
    ]

    banked_signal = BankedSignal(
        "4169895076385542",
        "303636684709969",
        "te",
    )
    banked_signal.add_classification("true_positive")

    match_message = MatchMessage("key", "hash", [banked_signal])

    action_label_to_action_rules = get_actions_to_take(match_message, action_rules)

    print(action_label_to_action_rules)
