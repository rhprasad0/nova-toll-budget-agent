"""Run the circuit breaker against an in-memory AWS with two child accounts."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError

PATH = Path(__file__).parents[2] / "org-circuit-breaker" / "handler.py"
spec = importlib.util.spec_from_file_location("circuit_breaker", PATH)
assert spec and spec.loader
breaker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(breaker)

DEV, LIVE, POLICY = "111111111111", "222222222222", "p-deny"
TAG = breaker.TAG


class Pager:
    def __init__(self, page: dict[str, Any]) -> None:
        self.page = page

    def paginate(self, **_: object) -> list[dict[str, Any]]:
        return [self.page]


class Account:
    """Resources in one child account, shared by its service clients."""

    def __init__(self) -> None:
        self.db = {
            "DBInstanceArn": "db",
            "DBInstanceIdentifier": "db",
            "DBInstanceStatus": "available",
            "TagList": [],
        }
        self.ec2 = {"InstanceId": "i-1", "State": {"Name": "running"}, "Tags": []}
        self.concurrency: dict[str, int | None] = {"capped": 5, "open": None}
        self.function_tags: dict[str, dict[str, str]] = {"capped": {}, "open": {}}
        self.provisioned: dict[str, dict[str, int]] = {"capped": {}, "open": {}}
        self.primary = {"Id": "P", "ARN": "P", "Enabled": True, "Staging": False}
        self.staging = {"Id": "S", "ARN": "S", "Enabled": True, "Staging": True}
        self.cf_tags: dict[str, list[dict[str, str]]] = {"P": [], "S": []}
        self.fail_rds_stop = False

    def client(self, service: str) -> object:
        return {
            "rds": Rds,
            "ec2": Ec2,
            "lambda": Lambda,
            "cloudfront": CloudFront,
        }[service](self)


class Service:
    def __init__(self, account: Account) -> None:
        self.account = account

    def get_paginator(self, operation: str) -> Pager:
        return Pager(self.pages[operation]())


class Rds(Service):
    def __init__(self, account: Account) -> None:
        super().__init__(account)
        self.pages = {"describe_db_instances": lambda: {"DBInstances": [account.db]}}

    def add_tags_to_resource(self, Tags: list[dict[str, str]], **_: object) -> None:
        self.account.db["TagList"] = Tags

    def remove_tags_from_resource(self, **_: object) -> None:
        self.account.db["TagList"] = []

    def stop_db_instance(self, **_: object) -> None:
        if self.account.fail_rds_stop:
            raise ClientError({"Error": {"Code": "Nope"}}, "StopDBInstance")
        self.account.db["DBInstanceStatus"] = "stopped"

    def start_db_instance(self, **_: object) -> None:
        self.account.db["DBInstanceStatus"] = "available"


class Ec2(Service):
    def __init__(self, account: Account) -> None:
        super().__init__(account)
        self.pages = {
            "describe_instances": lambda: {
                "Reservations": [{"Instances": [account.ec2]}]
            }
        }

    def describe_regions(self) -> dict[str, Any]:
        return {"Regions": [{"RegionName": "us-east-1"}]}

    def create_tags(self, Tags: list[dict[str, str]], **_: object) -> None:
        self.account.ec2["Tags"] = Tags

    def delete_tags(self, **_: object) -> None:
        self.account.ec2["Tags"] = []

    def stop_instances(self, **_: object) -> None:
        self.account.ec2["State"]["Name"] = "stopped"

    def start_instances(self, **_: object) -> None:
        self.account.ec2["State"]["Name"] = "running"


class Lambda(Service):
    def __init__(self, account: Account) -> None:
        super().__init__(account)
        self.pages = {
            "list_functions": lambda: {
                "Functions": [
                    {"FunctionArn": name, "FunctionName": name}
                    for name in account.concurrency
                ]
            }
        }

    def get_paginator(self, operation: str) -> Any:  # noqa: ANN401
        if operation != "list_provisioned_concurrency_configs":
            return super().get_paginator(operation)
        provisioned = self.account.provisioned

        class ProvisionedPager:
            def paginate(self, FunctionName: str) -> list[dict[str, Any]]:
                return [
                    {
                        "ProvisionedConcurrencyConfigs": [
                            {
                                "FunctionArn": f"arn:function:{FunctionName}:{alias}",
                                "RequestedProvisionedConcurrentExecutions": count,
                            }
                            for alias, count in provisioned[FunctionName].items()
                        ]
                    }
                ]

        return ProvisionedPager()

    def delete_provisioned_concurrency_config(
        self, FunctionName: str, Qualifier: str
    ) -> None:
        del self.account.provisioned[FunctionName][Qualifier]

    def put_provisioned_concurrency_config(
        self, FunctionName: str, Qualifier: str, ProvisionedConcurrentExecutions: int
    ) -> None:
        self.account.provisioned[FunctionName][Qualifier] = (
            ProvisionedConcurrentExecutions
        )

    def list_tags(self, Resource: str) -> dict[str, Any]:
        return {"Tags": dict(self.account.function_tags[Resource])}

    def tag_resource(self, Resource: str, Tags: dict[str, str]) -> None:
        self.account.function_tags[Resource].update(Tags)

    def untag_resource(self, Resource: str, TagKeys: list[str]) -> None:
        for key in TagKeys:
            del self.account.function_tags[Resource][key]

    def get_function_concurrency(self, FunctionName: str) -> dict[str, int]:
        value = self.account.concurrency[FunctionName]
        return {} if value is None else {"ReservedConcurrentExecutions": value}

    def put_function_concurrency(
        self, FunctionName: str, ReservedConcurrentExecutions: int
    ) -> None:
        if ReservedConcurrentExecutions < sum(
            self.account.provisioned[FunctionName].values()
        ):
            raise ClientError(
                {"Error": {"Code": "InvalidParameterValueException"}},
                "PutFunctionConcurrency",
            )
        self.account.concurrency[FunctionName] = ReservedConcurrentExecutions

    def delete_function_concurrency(self, FunctionName: str) -> None:
        self.account.concurrency[FunctionName] = None


class CloudFront(Service):
    def __init__(self, account: Account) -> None:
        super().__init__(account)
        self.pages = {
            "list_distributions": lambda: {
                "DistributionList": {"Items": [account.primary, account.staging]}
            }
        }

    def _distribution(self, identifier: str) -> dict[str, Any]:
        return self.account.primary if identifier == "P" else self.account.staging

    def list_tags_for_resource(self, Resource: str) -> dict[str, Any]:
        return {"Tags": {"Items": list(self.account.cf_tags[Resource])}}

    def tag_resource(self, Resource: str, Tags: dict[str, Any]) -> None:
        self.account.cf_tags[Resource] = Tags["Items"]

    def untag_resource(self, Resource: str, **_: object) -> None:
        self.account.cf_tags[Resource] = []

    def get_distribution_config(self, Id: str) -> dict[str, Any]:
        enabled = self._distribution(Id)["Enabled"]
        return {"ETag": "e", "DistributionConfig": {"Enabled": enabled}}

    def update_distribution(
        self, Id: str, IfMatch: str, DistributionConfig: dict[str, Any]
    ) -> None:
        assert IfMatch == "e"
        self._distribution(Id)["Enabled"] = DistributionConfig["Enabled"]


class World:
    def __init__(self) -> None:
        self.accounts = {DEV: Account(), LIVE: Account()}
        self.attached: set[str] = set()
        self.denied_roles: set[str] = set()
        self.attach_failures: set[str] = set()
        self.spend = "100"
        self.limit = "250"

    def client(self, service: str, **_: object) -> object:
        return {"budgets": Budgets, "organizations": Orgs, "sts": Sts}[service](self)

    def session(self, aws_access_key_id: str, **_: object) -> object:
        account = self.accounts[aws_access_key_id]

        class Session:
            def client(self, service: str, **_: object) -> object:
                return account.client(service)

        return Session()


class Budgets:
    def __init__(self, world: World) -> None:
        self.world = world

    def describe_budget(self, **_: object) -> dict[str, Any]:
        return {
            "Budget": {
                "CalculatedSpend": {"ActualSpend": {"Amount": self.world.spend}},
                "BudgetLimit": {"Amount": self.world.limit},
            }
        }


class Sts:
    def __init__(self, world: World) -> None:
        self.world = world

    def assume_role(self, RoleArn: str, **_: object) -> dict[str, Any]:
        account = RoleArn.split(":")[4]
        assert RoleArn.endswith(":role/OrganizationAccountAccessRole")
        if account in self.world.denied_roles:
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "AssumeRole")
        return {
            "Credentials": {
                "AccessKeyId": account,
                "SecretAccessKey": "s",
                "SessionToken": "t",
            }
        }


class Orgs:
    def __init__(self, world: World) -> None:
        self.world = world

    def get_paginator(self, _operation: str) -> Pager:
        targets = [{"TargetId": account} for account in self.world.attached]
        return Pager({"Targets": targets})

    def attach_policy(self, PolicyId: str, TargetId: str) -> None:
        assert PolicyId == POLICY
        if TargetId in self.world.attach_failures:
            raise ClientError(
                {"Error": {"Code": "ConcurrentModificationException"}}, "AttachPolicy"
            )
        self.world.attached.add(TargetId)

    def detach_policy(self, PolicyId: str, TargetId: str) -> None:
        assert PolicyId == POLICY
        self.world.attached.remove(TargetId)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    state = World()
    monkeypatch.setattr(breaker.boto3, "client", state.client)
    monkeypatch.setattr(breaker.boto3, "Session", state.session)
    monkeypatch.setenv("TARGET_ACCOUNT_IDS", f"{DEV},{LIVE}")
    monkeypatch.setenv("SCP_POLICY_ID", POLICY)
    monkeypatch.setenv("MANAGEMENT_ACCOUNT_ID", "333333333333")
    monkeypatch.setenv("BUDGET_NAME", "budget")
    return state


def assert_untouched(account: Account) -> None:
    assert account.db["DBInstanceStatus"] == "available"
    assert account.db["TagList"] == []
    assert account.ec2["State"]["Name"] == "running"
    assert account.ec2["Tags"] == []
    assert account.concurrency == {"capped": 5, "open": None}
    assert account.function_tags == {"capped": {}, "open": {}}
    assert account.primary["Enabled"] is True
    assert account.cf_tags["P"] == []


def assert_down(account: Account) -> None:
    assert account.db["DBInstanceStatus"] == "stopped"
    assert account.ec2["State"]["Name"] == "stopped"
    assert account.concurrency == {"capped": 0, "open": 0}
    assert account.function_tags == {"capped": {TAG: "5"}, "open": {TAG: "none"}}
    assert account.primary["Enabled"] is False
    assert account.staging["Enabled"] is True


@pytest.mark.parametrize("spend", ["100", "250", "250.00"])
def test_at_or_under_limit_does_nothing(world: World, spend: str) -> None:
    world.spend = spend
    breaker.handler({})
    assert world.attached == set()
    assert_untouched(world.accounts[DEV])
    assert_untouched(world.accounts[LIVE])


def test_over_limit_takes_both_accounts_down(world: World) -> None:
    world.spend = "250.01"
    assert breaker.handler({})["tripped"] == [DEV, LIVE]
    assert world.attached == {DEV, LIVE}
    assert_down(world.accounts[DEV])
    assert_down(world.accounts[LIVE])


def test_repeat_sweep_keeps_prior_state_and_restops_restarted_database(
    world: World,
) -> None:
    world.spend = "300"
    breaker.handler({})
    world.accounts[DEV].db["DBInstanceStatus"] = "available"
    # A new month: spend has reset, but only a person may bring it back.
    world.spend = "1"
    breaker.handler({"source": "aws.events"})
    assert world.attached == {DEV, LIVE}
    assert_down(world.accounts[DEV])


def test_manual_attachment_trips_only_that_account(world: World) -> None:
    world.attached.add(DEV)
    assert breaker.handler({})["tripped"] == [DEV]
    assert_down(world.accounts[DEV])
    assert_untouched(world.accounts[LIVE])


def test_restore_returns_exact_prior_state(world: World) -> None:
    world.spend = "300"
    breaker.handler({})
    world.spend = "1"
    assert breaker.handler({"action": "restore"})["restored"] == [DEV, LIVE]
    assert world.attached == set()
    assert_untouched(world.accounts[DEV])
    assert_untouched(world.accounts[LIVE])


def test_restore_refuses_while_over_limit(world: World) -> None:
    world.spend = "300"
    breaker.handler({})
    with pytest.raises(RuntimeError, match="raise the budget limit"):
        breaker.handler({"action": "restore"})
    assert world.attached == {DEV, LIVE}
    assert_down(world.accounts[DEV])


def test_one_failed_resource_finishes_the_sweep_then_raises(world: World) -> None:
    world.spend = "300"
    world.accounts[DEV].fail_rds_stop = True
    with pytest.raises(RuntimeError, match="1 resources failed"):
        breaker.handler({})
    assert world.attached == {DEV, LIVE}
    assert world.accounts[DEV].ec2["State"]["Name"] == "stopped"
    assert_down(world.accounts[LIVE])


def test_unreachable_account_does_not_shield_the_other(world: World) -> None:
    world.spend = "300"
    world.denied_roles.add(DEV)
    with pytest.raises(RuntimeError, match="1 resources failed"):
        breaker.handler({})
    assert world.attached == {DEV, LIVE}
    assert_down(world.accounts[LIVE])


def test_failed_attach_still_sweeps_both_accounts(world: World) -> None:
    world.spend = "300"
    world.attach_failures.add(DEV)
    with pytest.raises(RuntimeError, match="1 resources failed"):
        breaker.handler({})
    assert world.attached == {LIVE}
    assert_down(world.accounts[DEV])
    assert_down(world.accounts[LIVE])


def test_restore_recovers_an_account_detached_by_hand(world: World) -> None:
    world.spend = "300"
    breaker.handler({})
    world.attached.discard(DEV)
    world.spend = "1"
    breaker.handler({"action": "restore"})
    assert world.attached == set()
    assert_untouched(world.accounts[DEV])
    assert_untouched(world.accounts[LIVE])


def test_provisioned_concurrency_is_removed_and_restored(world: World) -> None:
    account = world.accounts[LIVE]
    account.provisioned["capped"]["live"] = 1
    world.spend = "300"
    breaker.handler({})
    assert account.concurrency["capped"] == 0
    assert account.provisioned["capped"] == {}
    assert account.function_tags["capped"] == {TAG: "5 live=1"}
    breaker.handler({})
    assert account.function_tags["capped"] == {TAG: "5 live=1"}
    world.spend = "1"
    breaker.handler({"action": "restore"})
    assert account.provisioned["capped"] == {"live": 1}
    assert_untouched(account)


def test_restore_leaves_resources_that_were_already_off(world: World) -> None:
    account = world.accounts[DEV]
    account.db["DBInstanceStatus"] = "stopped"
    account.ec2["State"]["Name"] = "stopped"
    account.primary["Enabled"] = False
    world.spend = "300"
    breaker.handler({})
    world.spend = "1"
    breaker.handler({"action": "restore"})
    assert account.db["DBInstanceStatus"] == "stopped"
    assert account.ec2["State"]["Name"] == "stopped"
    assert account.primary["Enabled"] is False
    assert account.concurrency == {"capped": 5, "open": None}


def test_restore_keeps_the_policy_on_an_account_it_could_not_restore(
    world: World,
) -> None:
    world.spend = "300"
    breaker.handler({})
    world.spend = "1"
    world.accounts[DEV].db["DBInstanceStatus"] = "stopping"
    with pytest.raises(RuntimeError, match="1 resources failed"):
        breaker.handler({"action": "restore"})
    assert world.attached == {DEV}
    assert_untouched(world.accounts[LIVE])
