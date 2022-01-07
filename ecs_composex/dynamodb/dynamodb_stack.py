#  -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# Copyright 2020-2021 John Mille <john@compose-x.io>

"""
Module to create the root stack for DynamoDB tables
"""
import warnings

from botocore.exceptions import ClientError
from compose_x_common.aws.dynamodb import TABLE_ARN_RE
from compose_x_common.compose_x_common import attributes_to_mapping, keyisset
from troposphere import GetAtt, Ref
from troposphere.dynamodb import Table as CfnTable

from ecs_composex.common import build_template, setup_logging
from ecs_composex.common.stacks import ComposeXStack
from ecs_composex.compose.x_resources import (
    ApiXResource,
    set_lookup_resources,
    set_new_resources,
    set_resources,
    set_use_resources,
)
from ecs_composex.dynamodb.dynamodb_params import (
    MAPPINGS_KEY,
    MOD_KEY,
    RES_KEY,
    TABLE_ARN,
    TABLE_NAME,
)
from ecs_composex.dynamodb.dynamodb_template import create_dynamodb_template
from ecs_composex.iam.import_sam_policies import get_access_types

LOG = setup_logging()


def get_dynamodb_table_config(table, account_id, resource_id):
    """

    :param Table table:
    :param str account_id:
    :param str resource_id:
    :return:
    """

    table_attributes_mapping = {
        TABLE_NAME.title: "TableName",
        TABLE_ARN.return_value: "TableArn",
    }
    client = table.lookup_session.client("dynamodb")
    try:
        table_r = client.describe_table(TableName=resource_id)["Table"]
        table_config = attributes_to_mapping(table_r, table_attributes_mapping)
        return table_config
    except client.exceptions.ResourceNotFoundException:
        return None
    except ClientError as error:
        LOG.error(error)
        raise


class Table(ApiXResource):
    """
    Class to represent a DynamoDB Table
    """

    policies_scaffolds = get_access_types(MOD_KEY)

    def init_outputs(self):
        self.output_properties = {
            TABLE_NAME: (self.logical_name, self.cfn_resource, Ref, None),
            TABLE_ARN: (
                f"{self.logical_name}{TABLE_ARN.title}",
                self.cfn_resource,
                GetAtt,
                TABLE_ARN.return_value,
            ),
        }


def resolve_lookup(lookup_resources, settings):
    """
    Lookup AWS Resource

    :param list[Table] lookup_resources:
    :param ecs_composex.common.settings.ComposeXSettings settings:
    """
    if not keyisset(MAPPINGS_KEY, settings.mappings):
        settings.mappings[MAPPINGS_KEY] = {}
    for resource in lookup_resources:
        resource.lookup_resource(
            TABLE_ARN_RE,
            get_dynamodb_table_config,
            CfnTable.resource_type,
            "dynamodb:table",
        )
        LOG.info(f"{RES_KEY}.{resource.name} - Matched to {resource.arn}")
        settings.mappings[MAPPINGS_KEY].update(
            {resource.logical_name: resource.mappings}
        )


class XStack(ComposeXStack):
    """
    Class for Dynamodb
    """

    def __init__(self, title, settings, **kwargs):
        set_resources(settings, Table, RES_KEY, MOD_KEY, mapping_key=MAPPINGS_KEY)
        x_resources = settings.compose_content[RES_KEY].values()
        use_resources = set_use_resources(x_resources, RES_KEY, False)
        if use_resources:
            warnings.warn(f"{RES_KEY} does not yet support Use.")
        lookup_resources = set_lookup_resources(x_resources, RES_KEY)
        if lookup_resources:
            resolve_lookup(lookup_resources, settings)
        new_resources = set_new_resources(x_resources, RES_KEY, False)
        if new_resources:
            stack_template = build_template("Root template for DynamoDB tables")
            super().__init__(title, stack_template, **kwargs)
            create_dynamodb_template(new_resources, stack_template, self)
        else:
            self.is_void = True
        for resource in x_resources:
            if resource.lookup:
                resource.stack = self
