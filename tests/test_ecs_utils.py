from unittest.mock import MagicMock, patch

import pytest

from ecs_utils import get_cluster_service_ips


@pytest.fixture
def mock_boto3_session():
    with patch("ecs_utils.boto3.Session") as mock_session_cls:
        session = MagicMock()
        mock_session_cls.return_value = session
        ecs = MagicMock()
        ec2 = MagicMock()
        session.client.side_effect = lambda name: {"ecs": ecs, "ec2": ec2}[name]
        yield session, ecs, ec2


def _setup_single_cluster_single_service(ecs, ec2, *, private=True):
    """Helper to wire up mocks for one cluster with one service."""
    ecs.list_clusters.return_value = {
        "clusterArns": ["arn:aws:ecs:us-east-1:123:cluster/web-staging"]
    }
    ecs.list_services.return_value = {
        "serviceArns": ["arn:aws:ecs:us-east-1:123:service/web-staging/nginx"]
    }
    ecs.list_tasks.return_value = {
        "taskArns": ["arn:aws:ecs:us-east-1:123:task/web-staging/abc123"]
    }
    ecs.describe_tasks.return_value = {
        "tasks": [
            {
                "taskArn": "arn:aws:ecs:us-east-1:123:task/web-staging/abc123",
                "containerInstanceArn": "arn:aws:ecs:us-east-1:123:container-instance/web-staging/ci-1",
            }
        ]
    }
    ecs.describe_container_instances.return_value = {
        "containerInstances": [{"ec2InstanceId": "i-001"}]
    }
    ip_key = "PrivateIpAddress" if private else "PublicIpAddress"
    ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-001",
                        ip_key: "10.0.0.5",
                        "Tags": [{"Key": "Name", "Value": "web-staging-host"}],
                    }
                ]
            }
        ]
    }


class TestGetClusterServiceIps:
    def test_returns_dict_keyed_by_cluster_service(self, mock_boto3_session):
        _, ecs, ec2 = mock_boto3_session
        _setup_single_cluster_single_service(ecs, ec2)

        result = get_cluster_service_ips("us-east-1", None, None, None, True)

        assert ("web-staging", "nginx") in result
        assert result[("web-staging", "nginx")] == ["10.0.0.5"]

    def test_specific_cluster(self, mock_boto3_session):
        _, ecs, ec2 = mock_boto3_session
        _setup_single_cluster_single_service(ecs, ec2)

        result = get_cluster_service_ips(
            "us-east-1", None, "web-staging", None, True
        )

        ecs.list_clusters.assert_not_called()
        assert ("web-staging", "nginx") in result

    def test_specific_service(self, mock_boto3_session):
        _, ecs, ec2 = mock_boto3_session
        _setup_single_cluster_single_service(ecs, ec2)

        result = get_cluster_service_ips(
            "us-east-1", None, "web-staging", "nginx", True
        )

        ecs.list_services.assert_not_called()
        assert ("web-staging", "nginx") in result

    def test_public_ips(self, mock_boto3_session):
        _, ecs, ec2 = mock_boto3_session
        _setup_single_cluster_single_service(ecs, ec2, private=False)

        result = get_cluster_service_ips(
            "us-east-1", None, None, None, False
        )

        assert result[("web-staging", "nginx")] == ["10.0.0.5"]

    def test_no_clusters_returns_empty(self, mock_boto3_session):
        _, ecs, ec2 = mock_boto3_session
        ecs.list_clusters.return_value = {"clusterArns": []}

        result = get_cluster_service_ips("us-east-1", None, None, None, True)

        assert result == {}

    def test_no_services_returns_empty(self, mock_boto3_session):
        _, ecs, ec2 = mock_boto3_session
        ecs.list_clusters.return_value = {
            "clusterArns": ["arn:aws:ecs:us-east-1:123:cluster/web-staging"]
        }
        ecs.list_services.return_value = {"serviceArns": []}

        result = get_cluster_service_ips("us-east-1", None, None, None, True)

        assert result == {}

    def test_no_tasks_skips_service(self, mock_boto3_session):
        _, ecs, ec2 = mock_boto3_session
        ecs.list_clusters.return_value = {
            "clusterArns": ["arn:aws:ecs:us-east-1:123:cluster/web-staging"]
        }
        ecs.list_services.return_value = {
            "serviceArns": ["arn:aws:ecs:us-east-1:123:service/web-staging/nginx"]
        }
        ecs.list_tasks.return_value = {"taskArns": []}

        result = get_cluster_service_ips("us-east-1", None, None, None, True)

        assert result == {}

    def test_multiple_clusters_and_services(self, mock_boto3_session):
        _, ecs, ec2 = mock_boto3_session
        ecs.list_clusters.return_value = {
            "clusterArns": [
                "arn:aws:ecs:us-east-1:123:cluster/staging",
                "arn:aws:ecs:us-east-1:123:cluster/production",
            ]
        }
        ecs.list_services.side_effect = [
            {"serviceArns": ["arn:aws:ecs:us-east-1:123:service/staging/nginx"]},
            {"serviceArns": ["arn:aws:ecs:us-east-1:123:service/production/nginx"]},
        ]
        ecs.list_tasks.side_effect = [
            {"taskArns": ["arn:aws:ecs:us-east-1:123:task/staging/t1"]},
            {"taskArns": ["arn:aws:ecs:us-east-1:123:task/production/t2"]},
        ]
        ecs.describe_tasks.side_effect = [
            {
                "tasks": [
                    {
                        "taskArn": "t1",
                        "containerInstanceArn": "arn:ci-1",
                    }
                ]
            },
            {
                "tasks": [
                    {
                        "taskArn": "t2",
                        "containerInstanceArn": "arn:ci-2",
                    }
                ]
            },
        ]
        ecs.describe_container_instances.side_effect = [
            {"containerInstances": [{"ec2InstanceId": "i-001"}]},
            {"containerInstances": [{"ec2InstanceId": "i-002"}]},
        ]
        ec2.describe_instances.side_effect = [
            {
                "Reservations": [
                    {
                        "Instances": [
                            {
                                "InstanceId": "i-001",
                                "PrivateIpAddress": "10.0.0.1",
                                "Tags": [],
                            }
                        ]
                    }
                ]
            },
            {
                "Reservations": [
                    {
                        "Instances": [
                            {
                                "InstanceId": "i-002",
                                "PrivateIpAddress": "10.0.1.1",
                                "Tags": [],
                            }
                        ]
                    }
                ]
            },
        ]

        result = get_cluster_service_ips("us-east-1", None, None, None, True)

        assert result[("staging", "nginx")] == ["10.0.0.1"]
        assert result[("production", "nginx")] == ["10.0.1.1"]

    def test_fargate_tasks_without_container_instance(self, mock_boto3_session):
        """Fargate tasks don't have containerInstanceArn."""
        _, ecs, ec2 = mock_boto3_session
        ecs.list_clusters.return_value = {
            "clusterArns": ["arn:aws:ecs:us-east-1:123:cluster/web"]
        }
        ecs.list_services.return_value = {
            "serviceArns": ["arn:aws:ecs:us-east-1:123:service/web/app"]
        }
        ecs.list_tasks.return_value = {
            "taskArns": ["arn:aws:ecs:us-east-1:123:task/web/t1"]
        }
        ecs.describe_tasks.return_value = {
            "tasks": [{"taskArn": "t1"}]  # no containerInstanceArn
        }

        result = get_cluster_service_ips("us-east-1", None, None, None, True)

        assert result == {}

    def test_uses_profile(self, mock_boto3_session):
        session, ecs, ec2 = mock_boto3_session
        _setup_single_cluster_single_service(ecs, ec2)

        get_cluster_service_ips("us-east-1", "myprofile", None, None, True)

        from ecs_utils import boto3

        boto3.Session.assert_called_with(
            profile_name="myprofile", region_name="us-east-1"
        )
