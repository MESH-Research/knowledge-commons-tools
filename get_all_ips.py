import boto3
import click


@click.command()
@click.argument("cluster_name", required=False)
@click.option("--service", "-s", help="Specific service name (optional)")
@click.option("--region", "-r", help="AWS region name", default="us-east-1")
@click.option("--profile", "-p", help="AWS profile name", default=None)
@click.option(
    "--private/--public",
    default=True,
    help="Use private IPs instead of public",
)
def get_ecs_service_ips(cluster_name, service, region, profile, private):
    """Get IP addresses of EC2 instances running ECS services.

    CLUSTER_NAME: Optional name of the ECS cluster. If not provided, checks all clusters.
    """
    session = boto3.Session(profile_name=profile, region_name=region)
    ecs_client = session.client("ecs")
    ec2_client = session.client("ec2")

    try:
        # Get list of clusters
        if cluster_name:
            clusters = [cluster_name]
        else:
            clusters_response = ecs_client.list_clusters()
            clusters = [
                c.split("/")[-1] for c in clusters_response["clusterArns"]
            ]

        if not clusters:
            click.echo("No ECS clusters found", err=True)
            return

        # Process each cluster
        for cluster in clusters:
            try:
                click.echo(f"\nCluster: {cluster}")
                click.echo("=" * (len(cluster) + 9))

                # Get services in the cluster
                if service:
                    services = [service]
                else:
                    services_response = ecs_client.list_services(
                        cluster=cluster
                    )
                    services = [
                        s.split("/")[-1]
                        for s in services_response["serviceArns"]
                    ]

                if not services:
                    click.echo(f"No services found in cluster", err=True)
                    continue

                instance_ids = set()
                service_to_instance = {}

                # For each service, get its tasks and their container instances
                for service_name in services:
                    try:
                        # Get tasks for the service
                        tasks = ecs_client.list_tasks(
                            cluster=cluster, serviceName=service_name
                        )["taskArns"]

                        if not tasks:
                            click.echo(
                                f"No running tasks found for service {service_name}",
                                err=True,
                            )
                            continue

                        # Get container instances for these tasks
                        task_details = ecs_client.describe_tasks(
                            cluster=cluster, tasks=tasks
                        )["tasks"]

                        # Get container instance ARNs
                        container_instance_arns = [
                            task["containerInstanceArn"]
                            for task in task_details
                            if "containerInstanceArn" in task
                        ]

                        if container_instance_arns:
                            # Get EC2 instance IDs
                            container_instances = (
                                ecs_client.describe_container_instances(
                                    cluster=cluster,
                                    containerInstances=container_instance_arns,
                                )["containerInstances"]
                            )

                            # Map service to EC2 instances
                            ec2_ids = [
                                ci["ec2InstanceId"]
                                for ci in container_instances
                            ]
                            instance_ids.update(ec2_ids)
                            service_to_instance[service_name] = ec2_ids

                    except ecs_client.exceptions.ServiceNotFoundException:
                        click.echo(
                            f"Service '{service_name}' not found", err=True
                        )
                        continue

                if not instance_ids:
                    click.echo(
                        "No EC2 instances found running services", err=True
                    )
                    continue

                # Get IP addresses of all instances
                ec2_details = ec2_client.describe_instances(
                    InstanceIds=list(instance_ids)
                )

                # Build instance details mapping
                instance_details = {}
                ip_type = "PrivateIpAddress" if private else "PublicIpAddress"

                for reservation in ec2_details["Reservations"]:
                    for instance in reservation["Instances"]:
                        if ip_type in instance:
                            instance_details[instance["InstanceId"]] = {
                                "ip": instance[ip_type],
                                "name": next(
                                    (
                                        tag["Value"]
                                        for tag in instance.get("Tags", [])
                                        if tag["Key"] == "Name"
                                    ),
                                    "No Name",
                                ),
                            }

                # Print results grouped by service
                for service_name, ec2_ids in service_to_instance.items():
                    click.echo(f"\nService: {service_name}")
                    for ec2_id in ec2_ids:
                        if ec2_id in instance_details:
                            details = instance_details[ec2_id]
                            click.echo(
                                f"  {details['ip']} ({ec2_id} - {details['name']})"
                            )

            except ecs_client.exceptions.ClusterNotFoundException:
                click.echo(f"Error: Cluster '{cluster}' not found", err=True)
                continue

    except Exception as e:
        click.echo(f"Unexpected error: {str(e)}", err=True)
        raise click.Abort()


if __name__ == "__main__":
    get_ecs_service_ips()
