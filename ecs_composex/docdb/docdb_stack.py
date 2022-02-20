#  -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# Copyright 2020-2022 John Mille <john@compose-x.io>

"""
AWS DocumentDB entrypoint for ECS ComposeX
"""

import warnings

from compose_x_common.aws.rds import RDS_DB_CLUSTER_ARN_RE
from compose_x_common.compose_x_common import attributes_to_mapping, keyisset
from troposphere import AWS_ACCOUNT_ID, AWS_PARTITION, AWS_REGION, GetAtt, Ref, Sub
from troposphere.docdb import DBCluster as CfnDBCluster

from ecs_composex.common import setup_logging
from ecs_composex.common.stacks import ComposeXStack
from ecs_composex.compose.x_resources import (
    DatabaseXResource,
    set_lookup_resources,
    set_new_resources,
    set_resources,
    set_use_resources,
)
from ecs_composex.docdb.docdb_params import (
    DOCDB_ID,
    DOCDB_NAME,
    DOCDB_PORT,
    MAPPINGS_KEY,
    MOD_KEY,
    RES_KEY,
)
from ecs_composex.docdb.docdb_template import (
    create_docdb_template,
    init_doc_db_template,
)
from ecs_composex.iam.import_sam_policies import get_access_types
from ecs_composex.rds.rds_params import DB_CLUSTER_ARN, DB_SECRET_ARN, DB_SG
from ecs_composex.rds_resources_settings import lookup_rds_resource, lookup_rds_secret
from ecs_composex.vpc.vpc_params import STORAGE_SUBNETS

LOG = setup_logging()


def get_db_cluster_config(db, account_id, resource_id):
    """

    :para DocDb db:
    :param account_id:
    :param resource_id:
    :return:
    """
    client = db.lookup_session.client("docdb")
    try:
        db_config_r = client.describe_db_clusters(
            DBClusterIdentifier=db.arn,
            Filters=[
                {
                    "Name": "engine",
                    "Values": [
                        "docdb",
                    ],
                },
            ],
        )["DBClusters"]
        db_cluster = db_config_r[0]
    except (client.exceptions.DBClusterNotFoundFault,) as error:
        LOG.error(f"{db.module_name}.{db.name} - Failed to retrieve configuration")
        LOG.error(error)
        raise
    if keyisset("VpcSecurityGroups", db_config_r):
        db_config_r["VpcSecurityGroups"] = [
            sg
            for sg in db_config_r["VpcSecurityGroups"]
            if keyisset("Status", sg) and sg["Status"] == "active"
        ]

    attributes_mappings = {
        db.db_port_parameter: "Port",
        db.db_sg_parameter: "VpcSecurityGroups::0::VpcSecurityGroupId",
        db.db_cluster_arn_parameter: "DBClusterArn",
    }
    config = attributes_to_mapping(db_cluster, attributes_mappings)
    return config


class DocDb(DatabaseXResource):
    """
    Class to manage DocDB
    """

    subnets_param = STORAGE_SUBNETS
    policies_scaffolds = get_access_types(MOD_KEY)

    def __init__(self, name, definition, module_name, settings, mapping_key=None):
        """
        Init method

        :param str name:
        :param dict definition:
        :param ecs_composex.common.settings.ComposeXSettings settings:
        """
        self.db_secret = None
        self.db_sg = None
        self.db_subnets_group = None
        super().__init__(
            name, definition, module_name, settings, mapping_key=mapping_key
        )
        self.set_override_subnets()
        self.db_sg_parameter = DB_SG
        self.db_secret_arn_parameter = DB_SECRET_ARN
        self.db_port_parameter = DOCDB_PORT
        self.db_cluster_arn_parameter = DB_CLUSTER_ARN

    def init_outputs(self):
        """
        Method to init the DocDB output attributes
        """
        self.output_properties = {
            DOCDB_NAME: (self.logical_name, self.cfn_resource, Ref, None),
            self.db_port_parameter: (
                f"{self.logical_name}{self.db_port_parameter.return_value}",
                self.cfn_resource,
                GetAtt,
                self.db_port_parameter.return_value,
            ),
            self.db_secret_arn_parameter: (
                self.db_secret.title,
                self.db_secret,
                Ref,
                None,
            ),
            self.db_sg_parameter: (
                self.db_sg.title,
                self.db_sg,
                GetAtt,
                self.db_sg_parameter.return_value,
            ),
            self.db_cluster_arn_parameter: (
                f"{self.logical_name}{self.db_cluster_arn_parameter.title}",
                self.cfn_resource,
                Sub,
                f"arn:${{{AWS_PARTITION}}}:rds:${{{AWS_REGION}}}:${{{AWS_ACCOUNT_ID}}}:"
                f"${{{self.cfn_resource.title}}}",
            ),
            DOCDB_ID: (
                f"{self.logical_name}{DOCDB_ID.return_value}",
                self.cfn_resource,
                GetAtt,
                DOCDB_ID.return_value,
            ),
        }

    def lookup_resource(
        self,
        arn_re,
        native_lookup_function,
        cfn_resource_type,
        tagging_api_id,
        subattribute_key=None,
    ):
        """
        Method to self-identify properties
        :return:
        """
        lookup_rds_resource(
            self,
            arn_re,
            native_lookup_function,
            cfn_resource_type,
            tagging_api_id,
            subattribute_key,
        )


def resolve_lookup(lookup_resources, settings):
    """
    Lookup AWS Resources

    :param list[DocDb] lookup_resources:
    :param ecs_composex.common.settings.ComposeXSettings settings:
    """
    if not keyisset(MAPPINGS_KEY, settings.mappings):
        settings.mappings[MAPPINGS_KEY] = {}
    for resource in lookup_resources:
        resource.lookup_resource(
            RDS_DB_CLUSTER_ARN_RE,
            get_db_cluster_config,
            CfnDBCluster.resource_type,
            "rds:cluster",
            "cluster",
        )
        if keyisset("secret", resource.lookup):
            lookup_rds_secret(resource, resource.lookup["secret"])
        resource.generate_cfn_mappings_from_lookup_properties()
        resource.generate_outputs()
        settings.mappings[MAPPINGS_KEY].update(
            {resource.logical_name: resource.mappings}
        )


class XStack(ComposeXStack):
    """
    Class for the Stack of DocDB
    """

    def __init__(self, title, settings, **kwargs):
        set_resources(settings, DocDb, RES_KEY, MOD_KEY, mapping_key=MAPPINGS_KEY)
        x_resources = settings.compose_content[RES_KEY].values()
        use_resources = set_use_resources(x_resources, RES_KEY, False)
        if use_resources:
            warnings.warn(f"{RES_KEY} does not yet support Use.")
        lookup_resources = set_lookup_resources(x_resources, RES_KEY)
        if lookup_resources or use_resources:
            resolve_lookup(lookup_resources, settings)
        new_resources = set_new_resources(x_resources, RES_KEY, True)

        if new_resources:
            stack_template = init_doc_db_template()
            super().__init__(title, stack_template, **kwargs)
            create_docdb_template(stack_template, new_resources, settings, self)
        else:
            self.is_void = True

        for resource in settings.compose_content[RES_KEY].values():
            resource.stack = self
