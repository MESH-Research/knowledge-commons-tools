import boto3


def get_cluster_service_ips(
    region: str,
    profile: str | None,
    cluster_name: str | None,
    service: str | None,
    private: bool,
) -> dict[tuple[str, str], list[str]]:
    """Get IP addresses of EC2 instances running ECS services.

    Returns a dict mapping (cluster_name, service_name) to a list of IP addresses.
    """
    session = boto3.Session(profile_name=profile, region_name=region)
    ecs_client = session.client("ecs")
    ec2_client = session.client("ec2")

    result: dict[tuple[str, str], list[str]] = {}

    if cluster_name:
        clusters = [cluster_name]
    else:
        clusters_response = ecs_client.list_clusters()
        clusters = [
            c.split("/")[-1] for c in clusters_response["clusterArns"]
        ]

    if not clusters:
        return result

    for cluster in clusters:
        if service:
            services = [service]
        else:
            services_response = ecs_client.list_services(cluster=cluster)
            services = [
                s.split("/")[-1] for s in services_response["serviceArns"]
            ]

        if not services:
            continue

        instance_ids = set()
        service_to_instances: dict[str, list[str]] = {}

        for service_name in services:
            tasks = ecs_client.list_tasks(
                cluster=cluster, serviceName=service_name
            )["taskArns"]

            if not tasks:
                continue

            task_details = ecs_client.describe_tasks(
                cluster=cluster, tasks=tasks
            )["tasks"]

            container_instance_arns = [
                task["containerInstanceArn"]
                for task in task_details
                if "containerInstanceArn" in task
            ]

            if not container_instance_arns:
                continue

            container_instances = ecs_client.describe_container_instances(
                cluster=cluster,
                containerInstances=container_instance_arns,
            )["containerInstances"]

            ec2_ids = [ci["ec2InstanceId"] for ci in container_instances]
            instance_ids.update(ec2_ids)
            service_to_instances[service_name] = ec2_ids

        if not instance_ids:
            continue

        ec2_details = ec2_client.describe_instances(
            InstanceIds=list(instance_ids)
        )

        ip_type = "PrivateIpAddress" if private else "PublicIpAddress"
        instance_ips: dict[str, str] = {}

        for reservation in ec2_details["Reservations"]:
            for instance in reservation["Instances"]:
                if ip_type in instance:
                    instance_ips[instance["InstanceId"]] = instance[ip_type]

        for service_name, ec2_ids in service_to_instances.items():
            ips = [
                instance_ips[eid] for eid in ec2_ids if eid in instance_ips
            ]
            if ips:
                result[(cluster, service_name)] = ips

    return result
