"""Core domain models and enumerations for ChaosNet VPC topologies."""

from __future__ import annotations

from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class NodeType(StrEnum):
    """Supported infrastructure node types inside a VPC."""

    INTERNET_GATEWAY = "INTERNET_GATEWAY"
    LOAD_BALANCER = "LOAD_BALANCER"
    ROUTER = "ROUTER"
    NAT_GATEWAY = "NAT_GATEWAY"
    APP_INSTANCE = "APP_INSTANCE"
    DATABASE = "DATABASE"


class NodeStatus(StrEnum):
    """Operational state of a node."""

    UP = "UP"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"


class LinkStatus(StrEnum):
    """Operational state of a network link."""

    UP = "UP"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"


class SubnetType(StrEnum):
    """Network visibility classification for a subnet."""

    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"


class DBRole(StrEnum):
    """Replication role for DATABASE nodes."""

    PRIMARY = "PRIMARY"
    REPLICA = "REPLICA"


class Subnet(BaseModel):
    """Represents a VPC subnet within a single Availability Zone."""

    id: str = Field(..., description="Unique subnet identifier, e.g. 'subnet-pub-a'")
    cidr: str = Field(..., description="IPv4 CIDR block, e.g. '10.0.1.0/24'")
    az: str = Field(..., description="Parent Availability Zone ID")
    type: SubnetType = Field(..., description="PUBLIC or PRIVATE subnet type")


class AvailabilityZone(BaseModel):
    """Represents an isolated Availability Zone within a VPC."""

    id: str = Field(..., description="Unique AZ identifier, e.g. 'az-a'")
    name: str = Field(..., description="Human-readable AZ name, e.g. 'us-east-1a'")
    subnets: list[Subnet] = Field(
        default_factory=list,
        description="Subnets provisioned inside this Availability Zone",
    )


class VPC(BaseModel):
    """Represents the top-level Virtual Private Cloud container."""

    id: str = Field(..., description="Unique VPC identifier, e.g. 'vpc-main'")
    name: str = Field(default="chaosnet-vpc", description="Human-readable VPC name")
    cidr: str = Field(default="10.0.0.0/16", description="VPC IPv4 CIDR block")
    availability_zones: list[AvailabilityZone] = Field(
        default_factory=list,
        description="Availability Zones belonging to this VPC",
    )


class Node(BaseModel):
    """Represents a compute, routing, or storage resource in the VPC."""

    id: str = Field(..., description="Unique node identifier")
    type: NodeType = Field(..., description="Infrastructure category of the node")
    az: Optional[str] = Field(
        default=None,
        description="Availability Zone ID (None for VPC-global nodes like INTERNET_GATEWAY)",
    )
    subnet: Optional[str] = Field(
        default=None,
        description="Subnet ID (None for VPC-global nodes like INTERNET_GATEWAY)",
    )
    status: NodeStatus = Field(
        default=NodeStatus.UP,
        description="Current operational status",
    )
    latency_ms: float = Field(
        default=1.0,
        ge=0.0,
        description="Internal processing latency of the node in milliseconds",
    )
    capacity: int = Field(
        default=100,
        ge=1,
        description="Maximum concurrent requests or throughput units supported",
    )
    db_role: Optional[DBRole] = Field(
        default=None,
        description="Database role (PRIMARY or REPLICA); required when type is DATABASE",
    )
    active_connections: int = Field(
        default=0,
        ge=0,
        description="Current number of active routed connections",
    )

    @model_validator(mode="after")
    def validate_node_constraints(self) -> Node:
        """Ensure DATABASE nodes declare a role and non-DB nodes do not."""
        if self.type == NodeType.DATABASE and self.db_role is None:
            raise ValueError(f"DATABASE node '{self.id}' must specify db_role (PRIMARY or REPLICA).")
        if self.type != NodeType.DATABASE and self.db_role is not None:
            raise ValueError(f"Non-database node '{self.id}' ({self.type}) cannot specify db_role.")
        if self.type != NodeType.INTERNET_GATEWAY and (not self.az or not self.subnet):
            raise ValueError(
                f"Node '{self.id}' of type '{self.type}' must belong to an AZ and a subnet."
            )
        return self


class Link(BaseModel):
    """Represents a network connection between two nodes in the VPC."""

    source: str = Field(..., description="Source node ID")
    target: str = Field(..., description="Target node ID")
    latency: float = Field(
        default=1.0,
        ge=0.0,
        description="Network propagation latency in milliseconds",
    )
    bandwidth: int = Field(
        default=1000,
        ge=1,
        description="Link bandwidth capacity in Mbps",
    )
    status: LinkStatus = Field(
        default=LinkStatus.UP,
        description="Current operational status of the link",
    )
    packet_loss: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Fractional packet loss rate between 0.0 and 1.0",
    )
    bidirectional: bool = Field(
        default=True,
        description="Whether traffic can traverse the link in both directions",
    )


class TopologyConfig(BaseModel):
    """Root schema for loading a VPC topology from a scenario file."""

    vpc: VPC
    nodes: list[Node]
    links: list[Link]

    @model_validator(mode="after")
    def validate_references(self) -> TopologyConfig:
        """Verify that all AZ, subnet, and link endpoint references are valid."""
        az_map: dict[str, set[str]] = {}
        for az in self.vpc.availability_zones:
            if az.id in az_map:
                raise ValueError(f"Duplicate Availability Zone ID: '{az.id}'")
            az_map[az.id] = {subnet.id for subnet in az.subnets}

        node_ids: set[str] = set()
        primary_dbs = 0

        for node in self.nodes:
            if node.id in node_ids:
                raise ValueError(f"Duplicate node ID: '{node.id}'")
            node_ids.add(node.id)

            if node.az is not None:
                if node.az not in az_map:
                    raise ValueError(f"Node '{node.id}' references unknown AZ '{node.az}'.")
                if node.subnet not in az_map[node.az]:
                    raise ValueError(
                        f"Node '{node.id}' references subnet '{node.subnet}' "
                        f"which does not exist in AZ '{node.az}'."
                    )

            if node.type == NodeType.DATABASE and node.db_role == DBRole.PRIMARY:
                primary_dbs += 1

        if primary_dbs > 1:
            raise ValueError(f"Topology cannot start with more than 1 PRIMARY database (found {primary_dbs}).")

        for link in self.links:
            if link.source not in node_ids:
                raise ValueError(f"Link source '{link.source}' does not match any node ID.")
            if link.target not in node_ids:
                raise ValueError(f"Link target '{link.target}' does not match any node ID.")

        return self
