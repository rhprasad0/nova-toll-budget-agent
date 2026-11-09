"""Shut down the child accounts when organization spend passes the budget limit.

The attached deny-all SCP is the tripped state. Every run while it is attached
sweeps again, because RDS restarts a stopped database after seven days. Each
changed resource carries a tag recording how to put it back.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

LOG = logging.getLogger()
LOG.setLevel(logging.INFO)

TAG = "circuit-breaker-prior"
ROLE = "OrganizationAccountAccessRole"

Client = Any
Failures = list[str]


def pages(client: Client, operation: str, key: str, **kwargs: object) -> Iterator[Any]:
    for page in client.get_paginator(operation).paginate(**kwargs):
        yield from page.get(key) or []


@contextmanager
def recorded(failures: Failures, label: str) -> Iterator[None]:
    """One stuck resource must not stop the rest of the sweep."""
    try:
        yield
    except (BotoCoreError, ClientError):
        LOG.exception("failed: %s", label)
        failures.append(label)


def instances(ec2: Client) -> Iterator[Any]:
    for reservation in pages(ec2, "describe_instances", "Reservations"):
        yield from reservation["Instances"]


def tag_map(tags: list[dict[str, str]] | None) -> dict[str, str]:
    return {tag["Key"]: tag["Value"] for tag in tags or []}


def distributions(cloudfront: Client) -> Iterator[Any]:
    for page in cloudfront.get_paginator("list_distributions").paginate():
        yield from page["DistributionList"].get("Items") or []


def cloudfront_tags(cloudfront: Client, arn: str) -> dict[str, str]:
    tags = cloudfront.list_tags_for_resource(Resource=arn)["Tags"]
    return tag_map(tags.get("Items"))


def set_enabled(cloudfront: Client, distribution_id: str, enabled: bool) -> None:
    current = cloudfront.get_distribution_config(Id=distribution_id)
    config = current["DistributionConfig"]
    config["Enabled"] = enabled
    cloudfront.update_distribution(
        Id=distribution_id, IfMatch=current["ETag"], DistributionConfig=config
    )


def trip_rds(rds: Client, failures: Failures) -> None:
    for db in pages(rds, "describe_db_instances", "DBInstances"):
        if db["DBInstanceStatus"] != "available":
            continue
        arn = db["DBInstanceArn"]
        with recorded(failures, arn):
            if TAG not in tag_map(db.get("TagList")):
                rds.add_tags_to_resource(
                    ResourceName=arn, Tags=[{"Key": TAG, "Value": "stopped"}]
                )
            rds.stop_db_instance(DBInstanceIdentifier=db["DBInstanceIdentifier"])


def restore_rds(rds: Client, failures: Failures) -> None:
    for db in pages(rds, "describe_db_instances", "DBInstances"):
        if TAG not in tag_map(db.get("TagList")):
            continue
        arn = db["DBInstanceArn"]
        with recorded(failures, arn):
            if db["DBInstanceStatus"] == "stopped":
                rds.start_db_instance(DBInstanceIdentifier=db["DBInstanceIdentifier"])
            elif db["DBInstanceStatus"] != "available":
                failures.append(arn)
                continue
            rds.remove_tags_from_resource(ResourceName=arn, TagKeys=[TAG])


def trip_ec2(ec2: Client, failures: Failures) -> None:
    for instance in instances(ec2):
        if instance["State"]["Name"] != "running":
            continue
        instance_id = instance["InstanceId"]
        with recorded(failures, instance_id):
            if TAG not in tag_map(instance.get("Tags")):
                ec2.create_tags(
                    Resources=[instance_id], Tags=[{"Key": TAG, "Value": "stopped"}]
                )
            ec2.stop_instances(InstanceIds=[instance_id])


def restore_ec2(ec2: Client, failures: Failures) -> None:
    for instance in instances(ec2):
        if TAG not in tag_map(instance.get("Tags")):
            continue
        instance_id = instance["InstanceId"]
        with recorded(failures, instance_id):
            state = instance["State"]["Name"]
            if state == "stopped":
                ec2.start_instances(InstanceIds=[instance_id])
            elif state != "running":
                failures.append(instance_id)
                continue
            ec2.delete_tags(Resources=[instance_id], Tags=[{"Key": TAG}])


def trip_lambda(lam: Client, failures: Failures) -> None:
    for function in pages(lam, "list_functions", "Functions"):
        arn, name = function["FunctionArn"], function["FunctionName"]
        with recorded(failures, arn):
            # Reserved concurrency cannot go below provisioned, so remove it first.
            provisioned = {
                config["FunctionArn"].rsplit(":", 1)[1]: config[
                    "RequestedProvisionedConcurrentExecutions"
                ]
                for config in pages(
                    lam,
                    "list_provisioned_concurrency_configs",
                    "ProvisionedConcurrencyConfigs",
                    FunctionName=name,
                )
            }
            # A later sweep sees 0 here, so only the first one may record it.
            if TAG not in lam.list_tags(Resource=arn)["Tags"]:
                prior = lam.get_function_concurrency(FunctionName=name).get(
                    "ReservedConcurrentExecutions"
                )
                value = " ".join(
                    ["none" if prior is None else str(prior)]
                    + [f"{alias}={count}" for alias, count in provisioned.items()]
                )
                lam.tag_resource(Resource=arn, Tags={TAG: value})
            for alias in provisioned:
                lam.delete_provisioned_concurrency_config(
                    FunctionName=name, Qualifier=alias
                )
            lam.put_function_concurrency(
                FunctionName=name, ReservedConcurrentExecutions=0
            )


def restore_lambda(lam: Client, failures: Failures) -> None:
    for function in pages(lam, "list_functions", "Functions"):
        arn, name = function["FunctionArn"], function["FunctionName"]
        with recorded(failures, arn):
            prior = lam.list_tags(Resource=arn)["Tags"].get(TAG)
            if prior is None:
                continue
            reserved, *provisioned = prior.split()
            if reserved == "none":
                lam.delete_function_concurrency(FunctionName=name)
            else:
                lam.put_function_concurrency(
                    FunctionName=name, ReservedConcurrentExecutions=int(reserved)
                )
            for item in provisioned:
                alias, count = item.split("=")
                lam.put_provisioned_concurrency_config(
                    FunctionName=name,
                    Qualifier=alias,
                    ProvisionedConcurrentExecutions=int(count),
                )
            lam.untag_resource(Resource=arn, TagKeys=[TAG])


def trip_cloudfront(cloudfront: Client, failures: Failures) -> None:
    for distribution in distributions(cloudfront):
        # A staging distribution only receives traffic through its primary.
        if distribution.get("Staging") or not distribution["Enabled"]:
            continue
        arn = distribution["ARN"]
        with recorded(failures, arn):
            if TAG not in cloudfront_tags(cloudfront, arn):
                cloudfront.tag_resource(
                    Resource=arn,
                    Tags={"Items": [{"Key": TAG, "Value": "enabled"}]},
                )
            set_enabled(cloudfront, distribution["Id"], False)


def restore_cloudfront(cloudfront: Client, failures: Failures) -> None:
    for distribution in distributions(cloudfront):
        arn = distribution["ARN"]
        with recorded(failures, arn):
            if TAG not in cloudfront_tags(cloudfront, arn):
                continue
            set_enabled(cloudfront, distribution["Id"], True)
            cloudfront.untag_resource(Resource=arn, TagKeys={"Items": [TAG]})


def sweep(account: str, restore: bool, failures: Failures) -> None:
    credentials = boto3.client("sts").assume_role(
        RoleArn=f"arn:aws:iam::{account}:role/{ROLE}",
        RoleSessionName="circuit-breaker",
    )["Credentials"]
    session = boto3.Session(
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
    )
    regional: dict[str, Callable[[Client, Failures], None]] = (
        {"rds": restore_rds, "ec2": restore_ec2, "lambda": restore_lambda}
        if restore
        else {"rds": trip_rds, "ec2": trip_ec2, "lambda": trip_lambda}
    )
    global_step = restore_cloudfront if restore else trip_cloudfront
    with recorded(failures, f"{account}/cloudfront"):
        global_step(session.client("cloudfront", region_name="us-east-1"), failures)
    regions = session.client("ec2", region_name="us-east-1").describe_regions()
    for region in regions["Regions"]:
        name = region["RegionName"]
        for service, step in regional.items():
            with recorded(failures, f"{account}/{name}/{service}"):
                step(session.client(service, region_name=name), failures)


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    targets = os.environ["TARGET_ACCOUNT_IDS"].split(",")
    policy_id = os.environ["SCP_POLICY_ID"]
    budget = boto3.client("budgets").describe_budget(
        AccountId=os.environ["MANAGEMENT_ACCOUNT_ID"],
        BudgetName=os.environ["BUDGET_NAME"],
    )["Budget"]
    spend = Decimal(budget["CalculatedSpend"]["ActualSpend"]["Amount"])
    limit = Decimal(budget["BudgetLimit"]["Amount"])
    over = spend > limit

    organizations = boto3.client("organizations")
    attached = {
        target["TargetId"]
        for target in pages(
            organizations, "list_targets_for_policy", "Targets", PolicyId=policy_id
        )
    } & set(targets)
    failures: Failures = []

    if event.get("action") == "restore":
        if over:
            raise RuntimeError(
                f"spend {spend} is over limit {limit}; raise the budget limit first"
            )
        # Every target, so an account whose SCP was detached by hand still recovers.
        for account in sorted(targets):
            account_failures: Failures = []
            with recorded(account_failures, account):
                sweep(account, True, account_failures)
                if not account_failures and account in attached:
                    organizations.detach_policy(PolicyId=policy_id, TargetId=account)
            failures += account_failures
        result = {"restored": sorted(targets), "spend": str(spend)}
    else:
        # Without an overrun, a manual attachment trips only that account.
        accounts = set(targets) if over else attached
        # One account's failure must not protect the other from its sweep.
        for account in sorted(accounts):
            if account not in attached:
                with recorded(failures, f"{account}/attach"):
                    organizations.attach_policy(PolicyId=policy_id, TargetId=account)
            with recorded(failures, account):
                sweep(account, False, failures)
        result = {"tripped": sorted(accounts), "spend": str(spend)}

    LOG.info("%s", result)
    if failures:
        raise RuntimeError(f"{len(failures)} resources failed: {failures}")
    return result
