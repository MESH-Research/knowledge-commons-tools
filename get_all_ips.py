import click

from ecs_utils import get_cluster_service_ips


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
    try:
        result = get_cluster_service_ips(
            region, profile, cluster_name, service, private
        )
    except Exception as e:
        click.echo(f"Unexpected error: {str(e)}", err=True)
        raise click.Abort()

    if not result:
        click.echo("No EC2 instances found running services", err=True)
        return

    current_cluster = None
    for (cluster, service_name), ips in sorted(result.items()):
        if cluster != current_cluster:
            current_cluster = cluster
            click.echo(f"\nCluster: {cluster}")
            click.echo("=" * (len(cluster) + 9))

        click.echo(f"\nService: {service_name}")
        for ip in ips:
            click.echo(f"  {ip}")


if __name__ == "__main__":
    get_ecs_service_ips()
